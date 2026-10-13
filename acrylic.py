#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 磨砂玻璃（亚克力）背景
==============================
Qt 只能画自己窗口**里面**的东西——"把窗口背后的桌面模糊掉"这件事它做不到，
必须交给 DWM。这里把两条路封装起来，按系统版本自动挑：

* **Win10 1803+ / Win11**：`SetWindowCompositionAttribute` +
  `ACCENT_ENABLE_ACRYLICBLURBEHIND`（亚克力：模糊 + 噪点）或
  `ACCENT_ENABLE_BLURBEHIND`（纯高斯模糊）。
  这条路对"分层窗口"（Qt 的 `WA_TranslucentBackground`）也有效，
  所以能和 QSS 的圆角半透明卡片叠着用。
* 同时把窗口区域用 `SetWindowRgn` 裁成圆角：模糊是按**窗口矩形**糊的，
  不裁的话圆角外面也会糊出一块方的，露馅。注意它按**物理像素**算
  （见 `apply_round_region` 的注释，高 DPI 下漏乘会裁掉一大块）。

拿不到（Win7/8、或系统策略挡住、或根本不是 Windows）就返回空串，
调用方回退成"只有半透明、没有模糊"——不会报错，也不会变成一块不透明的板子。

⚠️ `SetWindowCompositionAttribute` 是**未公开**接口，只能 `getattr` 探测；
哪天系统把它删了，这里就自动降级，不影响程序运行。

Win10 上的一个坑：亚克力(4) 从 1803 起有"拖动窗口严重卡顿"的已知问题，
所以 Win10 走纯模糊(3)，Win11 才用亚克力(4)。
"""

from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == "win32"

# SetWindowCompositionAttribute 的 Attribute 取值
WCA_ACCENT_POLICY = 19

# ACCENT_STATE
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

# Win10 1803 开始才有亚克力/模糊；低于这个版本就别折腾了
_MIN_BUILD_BLUR = 17134
# Win11
_WIN11_BUILD = 22000


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),      # 0xAABBGGRR
        ("AnimationId", ctypes.c_int),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def windows_build() -> int:
    """当前 Windows 的构建号；非 Windows 返回 0。"""
    if not IS_WINDOWS:
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def _abgr(color: str, alpha: int) -> int:
    """`#RRGGBB` → DWM 要的 `0xAABBGGRR`（注意字节序是反的）。"""
    text = str(color).lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        text = "1A1C22"
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return ((max(0, min(255, alpha)) & 0xFF) << 24) | (blue << 16) | (green << 8) | red


def _hwnd(widget) -> int:
    """拿到原生窗口句柄（顺带保证窗口已经创建）。"""
    return int(widget.winId())


# --------------------------------------------------------------------------
# 两条底层路径
# --------------------------------------------------------------------------
def _set_accent(hwnd: int, state: int, gradient_color: int, flags: int = 2) -> bool:
    """调用未公开的 SetWindowCompositionAttribute 设置亚克力/模糊。"""
    try:
        user32 = ctypes.windll.user32
        func = getattr(user32, "SetWindowCompositionAttribute", None)
        if func is None:
            return False
        func.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WINCOMPATTRDATA)]
        func.restype = ctypes.c_int
        policy = _ACCENT_POLICY(state, flags, gradient_color, 0)
        data = _WINCOMPATTRDATA(
            WCA_ACCENT_POLICY,
            ctypes.cast(ctypes.byref(policy), ctypes.c_void_p),
            ctypes.sizeof(policy),
        )
        return bool(func(ctypes.c_void_p(hwnd), ctypes.byref(data)))
    except Exception:
        return False


def region_metrics(logical_w: int, logical_h: int, radius: int,
                   ratio: float) -> "tuple[int, int, int]":
    """算出 `CreateRoundRectRgn` 要的 `(宽, 高, 圆角直径)`，单位**物理像素**。

    单独抽成纯函数是为了能自检：这个换算漏了 `ratio` 就会在高 DPI 下把窗口
    裁小一圈（dpr=1 的机器上看不出来），属于"肉眼很难发现、但用户一装就坏"
    的那类 bug。
    """
    w = max(1, int(round(max(1, logical_w) * ratio)))
    h = max(1, int(round(max(1, logical_h) * ratio)))
    diameter = max(2, int(round(max(1, radius) * ratio)) * 2)
    return w, h, diameter


def apply_round_region(widget, radius: int) -> bool:
    """把窗口裁成圆角（模糊是按窗口矩形糊的，不裁会露出方角）。

    `SetWindowRgn` **不会**跟着窗口缩放，所以每次尺寸变化都要重新调一次；
    调用方一般放在 `resizeEvent` 里。

    ⚠️ `SetWindowRgn` 收的是**物理像素**，而 Qt 的 `width()/height()` 是逻辑像素。
    高 DPI（比如 125%）下不乘 `devicePixelRatio` 就会把窗口裁小一圈——
    右下角那一条连按钮都显示不出来。换算见 `region_metrics()`。

    成功时区域所有权交给系统，不能自己删。
    """
    if not IS_WINDOWS:
        return False
    try:
        hwnd = _hwnd(widget)
        if not hwnd:
            return False
        ratio = float(widget.devicePixelRatio() or 1.0)
        width, height, diameter = region_metrics(widget.width(), widget.height(),
                                                radius, ratio)
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        # CreateRoundRectRgn 的 right/bottom 要 +1（它按"右下角坐标"理解）
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1,
                                         diameter, diameter)
        if not region:
            return False
        if not user32.SetWindowRgn(ctypes.c_void_p(hwnd), region, True):
            gdi32.DeleteObject(region)      # 没交出去就自己收尾，别泄漏
            return False
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def enable_blur(widget, *, radius: int = 22, tint: str = "#1A1C22",
                opacity: float = 0.55) -> str:
    """给顶层窗口开磨砂背景。

    参数
    ----
    radius  圆角半径（用来裁窗口区域，要和 QSS 里的圆角一致）
    tint    玻璃的底色，`#RRGGBB`
    opacity 底色浓度 0~1（越高越暗、越不透明）

    返回实际生效的方案名；空串表示没成功（调用方应回退到纯半透明）。
    """
    if not IS_WINDOWS:
        return ""
    build = windows_build()
    if build and build < _MIN_BUILD_BLUR:
        return ""
    try:
        hwnd = _hwnd(widget)
    except Exception:
        return ""
    if not hwnd:
        return ""

    alpha = int(round(max(0.0, min(1.0, float(opacity))) * 255))
    color = _abgr(tint, alpha)
    state = (ACCENT_ENABLE_ACRYLICBLURBEHIND if build >= _WIN11_BUILD
             else ACCENT_ENABLE_BLURBEHIND)

    if _set_accent(hwnd, state, color):
        apply_round_region(widget, radius)
        return "acrylic" if state == ACCENT_ENABLE_ACRYLICBLURBEHIND else "blur"
    return ""


def disable_blur(widget) -> bool:
    """关掉磨砂（把 accent 状态置回 DISABLED）。"""
    if not IS_WINDOWS:
        return False
    try:
        hwnd = _hwnd(widget)
    except Exception:
        return False
    if not hwnd:
        return False
    return _set_accent(hwnd, ACCENT_DISABLED, 0)


def describe() -> str:
    """给日志/自检用的一句话描述。"""
    build = windows_build()
    if not IS_WINDOWS:
        return "非 Windows，磨砂不可用"
    if not build:
        return "拿不到系统版本，按不支持处理"
    if build < _MIN_BUILD_BLUR:
        return f"Windows build {build} 太老，不支持磨砂"
    if getattr(ctypes.windll.user32, "SetWindowCompositionAttribute", None) is None:
        return f"Windows build {build}，但系统没提供 SetWindowCompositionAttribute"
    kind = "亚克力" if build >= _WIN11_BUILD else "模糊"
    return f"Windows build {build}，可用（{kind}）"


if __name__ == "__main__":
    print(describe())
    if IS_WINDOWS:
        print(f"  SetWindowCompositionAttribute: "
              f"{getattr(ctypes.windll.user32, 'SetWindowCompositionAttribute', None) is not None}")
        print(f"  SetWindowRgn: "
              f"{getattr(ctypes.windll.user32, 'SetWindowRgn', None) is not None}")
