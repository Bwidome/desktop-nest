#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实窗口探针（只给 `dev/test_dodge_live.py` 用）
================================================

为什么必须单独起一个进程
------------------------
窗口避让在 `covering_windows()` 里会按 **PID** 把"本程序的窗口"全部排除掉
（菜单栏、收纳面板、设置窗、右键菜单都不能触发自我隐藏）。
所以测试里的"遮挡窗口"如果也用同一个 Python 进程创建，**永远测不出遮挡**——
它会被当成自己人。必须另起一个进程，才等价于"别的应用"。

用法
----
    python dev/_dodge_probe_window.py <x> <y> <w> <h> <ready_file>

起来之后建一个普通顶层窗口（带标题、不带 TOOLWINDOW），进入消息循环，
并把 `READY <hwnd>` 写进 `ready_file` 供主进程确认。

主进程通过窗口类名 / 标题找到它，再用 `SetWindowPos` / `ShowWindow` /
`WM_CLOSE` 控制它——不需要这个脚本自己实现什么协议。

⚠️ 必须先把进程设成 Per-Monitor DPI aware：否则 125% 缩放下
`CreateWindowExW` 的坐标会被系统虚拟化，窗口落点跟请求的物理像素对不上，
测试就会"以为盖住了其实没盖住"。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32

CLASS_NAME = "DesktopNestDodgeProbe"
WINDOW_TITLE = "DesktopNestDodgeProbe"


def set_dpi_aware() -> None:
    """尽量设成 Per-Monitor V2；退路依次往下。"""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def main() -> int:
    if len(sys.argv) < 6:
        print("usage: _dodge_probe_window.py <x> <y> <w> <h> <ready_file>")
        return 2
    x, y, w, h = (int(v) for v in sys.argv[1:5])
    ready_file = sys.argv[5]

    set_dpi_aware()

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    def wndproc(hwnd, msg, wparam, lparam):
        if msg == 0x0010:                       # WM_CLOSE
            user32.DestroyWindow(hwnd)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = WNDPROC(wndproc)                     # 必须留引用

    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.style = 0x0002 | 0x0001                  # CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.hbrBackground = ctypes.cast(6, wintypes.HBRUSH)   # COLOR_WINDOW
    wc.lpszClassName = CLASS_NAME
    if not user32.RegisterClassW(ctypes.byref(wc)):
        err = ctypes.get_last_error()
        print(f"RegisterClassW failed: {err}")
        return 1

    WS_OVERLAPPEDWINDOW = 0x00CF0000
    hwnd = user32.CreateWindowExW(
        0, CLASS_NAME, WINDOW_TITLE, WS_OVERLAPPEDWINDOW,
        x, y, w, h, None, None, hinst, None)
    if not hwnd:
        print(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        return 1

    user32.ShowWindow(hwnd, 5)                  # SW_SHOW
    user32.UpdateWindow(hwnd)

    with open(ready_file, "w", encoding="utf-8") as f:
        f.write(f"READY {int(hwnd)}\n")

    msg = wintypes.MSG()
    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret <= 0:
            break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
