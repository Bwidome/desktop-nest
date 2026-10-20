#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
菜单栏的窗口避让（Nexus 风格的 Window Dodge）
=============================================

要解决的问题
------------
菜单栏贴在屏幕底部。别的程序窗口一开大（最大化、全屏、或者用户手动拖到
底部），就把菜单栏那块地方占了。这时候菜单栏应该**让开**，等窗口挪走 /
缩小 / 关闭 / 最小化之后自己**回来**。

为什么单独一个文件
------------------
`tray_app.py` 已经一千多行，再塞一套窗口枚举 + 状态机 + 动画就彻底读不动了。
这里把「什么时候该显示」这件事**收拢到一个决策点**（`evaluate()`），
外面谁都不用自己算——这是需求里"不要多个监听器互相覆盖状态"的落地方式。

技术方案与限制（必须先说清楚）
------------------------------
1. **矩形层面**判定，不是像素级。
   做法是枚举所有可见顶层窗口的矩形，只要有一个和菜单栏矩形相交
   （横向压住 ≥24px、纵向压住 ≥6px）就算"菜单栏区域被占"。
   * 能覆盖：普通窗口、最大化、全屏、多显示器、任意 DPI（全是物理像素）。
   * **不能覆盖**：两个窗口互相叠成"只露出一个 L 形"这种像素级遮挡。
     那种要算区域差集，收益极低、误判风险高，不做。这一点不假装做到了。

2. **Z 序**用 `EnumWindows` 的返回顺序（系统就是按 Z 序从顶到底给的）。
   取"最上面那个盖住菜单栏的窗口"作为判定依据。
   注意：菜单栏自己是 `WindowStaysOnTopHint`（TOPMOST），普通窗口在 Z 序上
   永远在它下面——所以这里判断的是"**区域被占用**"，不是"被压在底下看不见"。
   这也是 Nexus 的做法：Window Dodge 看的是占位，不是可见性。
   需求里"避免把位于菜单栏下方的窗口误判为遮挡"在当前架构下不会发生：
   菜单栏是 TOPMOST，不存在"正常的普通窗口压在它上面"这种情况。

3. **事件驱动 + 兜底轮询**。
   `SetWinEventHook` 只挂三小段必需的事件（对象显示/隐藏/移动/销毁、
   前台切换、最小化），**不挂 EVENT_MIN~EVENT_MAX 全量**——全量会把
   光标、菜单、选区等等事件也全接进来，在别的程序里打字都在唤醒我们。
   回调里只置一个脏标记（不碰 Qt 控件），由 60ms 的短定时器合并后去算。
   另外保留 120ms 的兜底轮询，防止 hook 在某些环境下失效导致状态卡死。

4. **"隐形窗口"必须排除**。UWP 应用被挂起、窗口被移到另一个虚拟桌面时，
   `IsWindowVisible()` 依然返回 True，但 DWM 把它标记成 **cloaked**，
   它那个"记忆中的"矩形还盖着菜单栏。不查 `DWMWA_CLOAKED` 的话，
   表现为**菜单栏莫名其妙一直藏着不回来**。这里用 `DwmGetWindowAttribute`
   把它挑出来。

5. **不做鼠标钩子，而且边缘唤回只在桌面上生效**。
   边缘唤回只是读 `QCursor.pos()`，不安装 `SetWindowsHookEx`、不占用任何
   屏幕区域，所以绝不会拦截用户对底部其他窗口的点击。

   ⚠️ 但"读鼠标位置"本身不够：全屏播放器 / 浏览器里，用户把鼠标甩到屏幕
   底部是去够播放控制条、状态栏、标签栏的，这时候把菜单栏叫出来纯属添乱
   （表现就是"鼠标一碰屏幕底部菜单栏就自动弹出来，全屏下也弹"）。
   所以 `_check_edge()` 前面加了 `_on_desktop()` 闸门：**只有前台就是桌面、
   且没有任何窗口占着菜单栏那一带时**才允许唤回。其余情况一律不弹——
   要它回来请用托盘菜单。

6. 坐标口径：
   * 窗口矩形（`GetWindowRect`）→ Win32 **物理像素**。两个矩形都来自同一个
     API，所以在任意 DPI 缩放下互相比较都是对的（本机实测 125% 缩放，
     物理 123×109 对逻辑 98×87，两边各自自洽）。
   * 鼠标位置（`QCursor.pos()` vs `frameGeometry()`）→ Qt **逻辑像素**。
     两边都来自 Qt，同样自洽。
   两种口径**绝不混用**，这是这块最容易写错的地方。
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

from qt_compat import (QApplication, QCursor, QEasingCurve, QObject, QTimer,
                       QVariantAnimation)

# --------------------------------------------------------------------------
# 可调参数
# --------------------------------------------------------------------------
# "压住"的最小重叠量。只擦一条边、角上碰一下都不算——否则拖窗口经过
# 菜单栏时它会神经质地闪。
DOCK_HIT_MIN_X = 24
DOCK_HIT_MIN_Y = 6

# 兜底轮询。120ms 一次枚举（几十个窗口，约 0.2~0.5ms），开销可以忽略。
POLL_INTERVAL = 120

# WinEvent 触发后的合并窗口：窗口拖动时 LOCATIONCHANGE 每帧都来，
# 攒 60ms 再算一次，既跟手又不会把 CPU 烧了。
EVENT_COALESCE = 60

# 鼠标在边缘停留多久才唤回。防止"快速划过屏幕底部"就闪出来。
EDGE_DWELL = 0.15

# 唤回之后保持多久不自动隐藏（用户要能点到图标）。
PEEK_HOLD = 2.5

# 淡入淡出 + 上下滑动的时长（需求给的区间是 180~260ms）。
ANIM_MS = 200

# 两次显隐之间至少隔这么久。
# 为什么需要：事件驱动 + 120ms 轮询已经把响应做到"跟手"了，但如果窗口
# 正好在菜单栏边缘来回抖（拖动、贴边吸附、窗口动画），状态会在几帧内
# 反复翻转，菜单栏就会闪。给一个下限既能防闪，又不影响第一次的即时响应
# （第一次切换不受这个限制）。
MIN_SWITCH_GAP = 0.30

# --------------------------------------------------------------------------
# 需要排除的窗口类名
# --------------------------------------------------------------------------
# 这些窗口要么"永远铺满全屏"、要么是系统覆盖层，算进去会让菜单栏永远藏着。
EXCLUDED_CLASSES = {
    "Progman",                      # 桌面（传统）
    "WorkerW",                      # 桌面（Win10/11 壁纸层）
    "SHELLDLL_DefView",             # 桌面图标层
    "Shell_TrayWnd",                # 任务栏
    "Shell_SecondaryTrayWnd",       # 副屏任务栏
    "Windows.UI.Core.CoreWindow",   # UWP 壳 / "Windows 输入体验"
    "CEF-OSC-WIDGET",               # NVIDIA GeForce Overlay 之类
    "MultitaskingViewFrame",        # 任务视图
    "XamlExplorerHostIslandWindow", # 任务视图 / 开始菜单宿主
    "ForegroundStaging",            # 前台切换时的过渡宿主
    "ApplicationManager_DesktopShellWindow",  # 新版任务栏宿主
}

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020      # 命中测试穿透（"点我等于点下面那层"）
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

DWMWA_CLOAKED = 14

# 监听的事件（只挂必需的三段，见模块文档第 3 条）
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017

EVENT_RANGES = (
    (EVENT_OBJECT_DESTROY, EVENT_OBJECT_LOCATIONCHANGE),   # 显示/隐藏/移动/销毁
    (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),    # 前台切换
    (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),# 最小化 / 还原
)

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)


def _prepare_user32():
    """把要用的 Win32 函数签名声明好，返回 user32（失败返回 None）。

    ⚠️ 必须显式声明 `argtypes` / `restype`：64 位下 HWND 是 8 字节指针，
    不声明的话 ctypes 默认按 `c_int` 传，句柄一旦超过 32 位就被截断，
    `GetWindowRect` 直接返回 0 —— 表现就是"检测永远不成立"。
    本机实测句柄值不大、侥幸没炸，但这是**必须**写对的。
    """
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [wintypes.HWND,
                                         ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                         ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.SetWinEventHook.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
            WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        user32.UnhookWinEvent.restype = wintypes.BOOL
        return user32
    except Exception:
        return None


def _prepare_dwm():
    """DWM 句柄（只为了查 cloaked；拿不到就退化成不查）。"""
    try:
        dwm = ctypes.windll.dwmapi
        dwm.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        return dwm
    except Exception:
        return None


def rects_overlap(a, b, min_x: int = 1, min_y: int = 1) -> bool:
    """两个屏幕矩形有没有真的相交。

    矩形用 `(left, top, right, bottom)`（Win32 物理像素口径）。
    **两个方向**的重叠量都要超过阈值才算数。

    抽成纯函数是为了能直接喂假矩形做自检，不用真开一个窗口去挡。
    """
    try:
        left = max(int(a[0]), int(b[0]))
        top = max(int(a[1]), int(b[1]))
        right = min(int(a[2]), int(b[2]))
        bottom = min(int(a[3]), int(b[3]))
        return (right - left) > min_x and (bottom - top) > min_y
    except (TypeError, IndexError, ValueError):
        return False


class DockDodge(QObject):
    """菜单栏的避让状态机。

    状态（故意分开存，不揉成一个布尔）
    ----------------------------------
    `_occluded`     当前是否有别的窗口占据菜单栏区域
    `_fullscreen`   遮挡里属于"全屏 / 最大化"的那部分
    `_covered`      遮挡里属于"普通窗口压上来"的那部分
    `_peek_until`   用户唤回后的保持期截止时刻（monotonic）
    `_animating`    是否正在播显隐动画
    `_hidden_by_me` 当前这次隐藏**是不是我干的**（决定要不要我负责恢复）
    `_last_action`  上一次真正执行的动作，用来避免重复 show/hide
    `_click_through`当前是否把菜单栏设成了"点击穿透"（滑出过程中）

    配置（都在 cfg 里，跟现有设置系统共用）
    --------------------------------------
    `dock_avoid_overlap`    窗口遮挡时自动隐藏（本次新增，默认开）
    `dock_avoid_fullscreen` 全屏 / 最大化时让开（原有）
    `dock_auto_show`        回到桌面自动显示（原有；关掉后**仍会**因遮挡让开，
                            但不再自动恢复，需要用户自己唤回）
    `dock_visible`          用户是否允许显示（原有）
    `dock_hidden_by_user`   用户主动隐藏过（原有，优先级最高）
    """

    def __init__(self, tray, dock, cfg, parent=None):
        super().__init__(parent)
        self.tray = tray
        self.dock = dock
        self.cfg = cfg

        self._occluded = False
        self._fullscreen = False
        self._covered = False
        self._peek_until = 0.0
        self._animating = False
        self._hidden_by_me = False
        self._last_action = "show"
        self._edge_since = 0.0
        self._dirty = False
        self._started = False
        self._last_switch = 0.0
        self._click_through = False
        self._home_pos = None          # 动画的终点位置（Qt 逻辑坐标）
        self._anim_home_rect = None    # 动画期间的"名义矩形"（Win32 物理像素）

        # 离屏平台没有窗口管理器：`GetForegroundWindow` 拿到的是**真实桌面**上
        # 那个窗口，跟自检环境毫无关系，判定必然失真（实测会把 dock 一直藏起来）。
        # 所以离屏下直接关掉探测，自检要验判定逻辑时把它打开即可。
        try:
            self.probe_enabled = QApplication.platformName() != "offscreen"
        except Exception:
            self.probe_enabled = False

        self._user32 = _prepare_user32() if os.name == "nt" else None
        self._dwm = _prepare_dwm() if os.name == "nt" else None
        self._hooks = []
        self._hook_procs = []          # ⚠️ 必须留引用，否则被 GC → 崩溃

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL)
        self._poll.timeout.connect(self._on_poll)

        self._coalesce = QTimer(self)
        self._coalesce.setSingleShot(True)
        self._coalesce.setInterval(EVENT_COALESCE)
        self._coalesce.timeout.connect(self._on_poll)

        self._anim = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._install_hooks()
        self._poll.start()
        self.evaluate()

    def stop(self) -> None:
        """程序退出时收尾：拆 hook、停定时器、停动画、清点击穿透。

        必须做——`SetWinEventHook` 的回调是系统在消息循环里调的，
        进程退出前不摘掉，运气不好会在解释器拆栈之后被回调进来。

        ⚠️ 还必须保证 `_animating` 归位、点击穿透被清掉：退出路径上任何
        一项漏了，下次（同一个实例）再 start 就会"永远不显隐"或者
        "菜单栏点不动"。
        """
        self._started = False
        try:
            self._poll.stop()
            self._coalesce.stop()
        except Exception:
            pass
        if self._anim is not None:
            try:
                self._anim.stop()
            except Exception:
                pass
            self._anim = None
        self._animating = False
        self._anim_home_rect = None
        self._home_pos = None
        self._set_click_through(False)
        try:
            self.dock.end_slide()
        except Exception:
            pass
        self._remove_hooks()

    # ------------------------------------------------------------------
    # WinEvent 钩子
    # ------------------------------------------------------------------
    def _on_winevent(self, _hook, _event, _hwnd, _id_object, _id_child,
                     _thread, _time):
        # ⚠️ 这里**只置标记**，绝不做检测、更不碰 Qt 控件：
        # 这是系统在消息循环里回调进来的，重入代价太大。
        if not self._started:
            return
        self._dirty = True
        if not self._coalesce.isActive():
            self._coalesce.start()

    def _install_hooks(self) -> None:
        """装 WinEvent 监听（拿不到就静默退化成纯轮询）。"""
        if self._user32 is None or self._hooks:
            return
        for low, high in EVENT_RANGES:
            try:
                proc = WINEVENTPROC(self._on_winevent)
                hook = self._user32.SetWinEventHook(
                    low, high, None, proc, 0, 0,
                    WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
                if hook:
                    self._hooks.append(hook)
                    self._hook_procs.append(proc)
            except Exception:
                continue

    def _remove_hooks(self) -> None:
        for hook in self._hooks:
            try:
                self._user32.UnhookWinEvent(hook)
            except Exception:
                pass
        self._hooks = []
        self._hook_procs = []

    def notify_changed(self) -> None:
        """外部（比如菜单栏刚被拖动 / 图标换行 / 设置改过）通知"该重算了"。"""
        self._dirty = True
        if not self._coalesce.isActive():
            self._coalesce.start()

    # ------------------------------------------------------------------
    # Win32 探测
    # ------------------------------------------------------------------
    def _live_dock_rect(self):
        """菜单栏**此刻真实的**屏幕矩形（Win32 物理像素）。"""
        if self._user32 is None:
            return None
        try:
            hwnd = int(self.dock.winId())
            if not hwnd:
                return None
            rect = wintypes.RECT()
            if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            if rect.right <= rect.left or rect.bottom <= rect.top:
                return None
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return None

    def dock_rect(self):
        """菜单栏的屏幕矩形（Win32 物理像素）。拿不到返回 None。

        动画期间返回**动画开始前的名义矩形**：那 200ms 里窗口本身在往下滑，
        如果按滑动中的实时矩形去判定，遮挡关系会跟着动画一起抖动，
        刚藏到一半就被判成"没遮挡了"，白白多切一次状态。
        """
        if self._anim_home_rect is not None:
            return self._anim_home_rect
        return self._live_dock_rect()

    def _is_cloaked(self, hwnd) -> bool:
        """DWM 是否把这个窗口标成 cloaked（隐形）。

        UWP 挂起、窗口在别的虚拟桌面、应用被"冻结"时都会是这种状态：
        `IsWindowVisible()` 仍然 True，但用户根本看不见它。
        """
        if self._dwm is None:
            return False
        try:
            value = ctypes.c_int(0)
            hr = self._dwm.DwmGetWindowAttribute(
                hwnd, DWMWA_CLOAKED, ctypes.byref(value),
                ctypes.sizeof(value))
            return hr == 0 and value.value != 0
        except Exception:
            return False

    def covering_windows(self):
        """所有"真的压住菜单栏"的窗口，按 Z 序从顶到底。

        过滤链（顺序就是执行顺序，越便宜越靠前）：
        1. 可见、非最小化
        2. 不是本进程（菜单栏 / 面板 / 设置 / 气泡都算自己人）
        3. 不是 DWM 隐形窗口（cloaked）
        4. 类名不在黑名单（桌面、任务栏、各种 overlay）
        5. 不是 `WS_EX_TOOLWINDOW` / `WS_EX_NOACTIVATE`（工具窗、浮动提示）
        6. 有标题（没标题的绝大多数是隐形宿主窗口）
        7. 矩形和菜单栏相交，且两个方向都压够了
        """
        if self._user32 is None:
            return []
        dock_rect = self.dock_rect()
        if dock_rect is None:
            return []

        user32 = self._user32
        my_pid = os.getpid()
        found = []

        def _callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.IsIconic(hwnd):
                    return True

                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) == my_pid:
                    return True

                if self._is_cloaked(hwnd):
                    return True

                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                if cls.value in EXCLUDED_CLASSES:
                    return True

                ex_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                if ex_style & WS_EX_TOOLWINDOW:
                    return True
                if ex_style & WS_EX_NOACTIVATE:
                    return True

                if user32.GetWindowTextLengthW(hwnd) <= 0:
                    return True

                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                box = (rect.left, rect.top, rect.right, rect.bottom)
                if not rects_overlap(box, dock_rect,
                                     DOCK_HIT_MIN_X, DOCK_HIT_MIN_Y):
                    return True

                title = ctypes.create_unicode_buffer(120)
                user32.GetWindowTextW(hwnd, title, 120)
                found.append((int(hwnd), box, cls.value, title.value))
                # EnumWindows 是**从顶到底**给的，所以第一个命中的就是最上层那个
                return len(found) < 8
            except Exception:
                return True

        try:
            user32.EnumWindows(WNDENUMPROC(_callback), 0)
        except Exception:
            return found
        return found

    def is_occluded(self) -> bool:
        """现在有没有窗口占据菜单栏区域（顺带记下是哪一类）。

        分成两类存，因为它们的**开关是分开的**：
        * `_fullscreen` —— 全屏 / 最大化（老开关 `dock_avoid_fullscreen`）
        * `_covered`    —— 普通窗口的矩形压上来（新开关 `dock_avoid_overlap`）

        全屏也走一遍 `covering_windows()`：有些全屏窗口标题为空会被过滤掉，
        但 `_foreground_is_fullscreen()` 按面积占比能兜住。
        """
        self._covered = False
        self._fullscreen = False
        if not self.probe_enabled:
            return False
        try:
            if self.tray is not None:
                self._fullscreen = bool(self.tray._foreground_is_fullscreen())
        except Exception:
            self._fullscreen = False
        try:
            self._covered = bool(self.covering_windows())
        except Exception:
            self._covered = False
        return self._fullscreen or self._covered

    # ------------------------------------------------------------------
    # 决策：唯一的入口
    # ------------------------------------------------------------------
    def evaluate(self) -> None:
        """算出现在该显示还是隐藏，然后交给 `_apply()`。

        所有事件、定时器、配置变更最后都汇到这里——**不要在别处直接
        show/hide 菜单栏**，否则状态一定打架。
        """
        if not self._started:
            return
        try:
            self._occluded = self.is_occluded()
            want = self._desired_visible()
            self._apply(want)
        except Exception as exc:                      # noqa: BLE001
            # 检测失败**绝不能**让菜单栏永久隐藏：兜底成"显示"
            import config
            config.log(f"窗口避让检测失败：{type(exc).__name__}: {exc}")
            self._occluded = False
            self._apply(True)

    def _desired_visible(self) -> bool:
        """按优先级算出"该不该显示"。顺序就是优先级，先命中先返回。

        优先级（从高到低）：
        1. 用户主动隐藏 —— 谁都不能自动弹回来
        2. 「显示底部菜单栏」被关掉
        3. 用户刚把鼠标挪到边缘唤回来的 —— 给他一点时间点图标
        4. 正在拖菜单栏 / 长按排序 —— 这时候藏起来就太坑了
        5. **有窗口占着这块地方 → 让开**（全屏和普通遮挡各有各的开关）

           ⚠️ 这一条必须排在"收纳面板开着"前面。面板只是我们自己的浮层，
           它开着的时候用户完全可能切到浏览器去；那时候菜单栏照样得让开，
           不能因为"面板还开着"就赖着不走。
           （我们自己的窗口本来就被 `covering_windows` 按 PID 排除了，
           所以"面板盖住菜单栏"不会被误判成遮挡。）

           ⚠️ 第 3 条（保持期）**不许压过这一条**：以前它是无条件返回 True，
           结果"在桌面唤回菜单栏 → 立刻切进全屏视频"时菜单栏会赖在屏幕上
           最多 2.5 秒。现在只有 `not self._occluded` 时才认保持期。

        6. 回到桌面自动显示（原有行为）
        7. 自动显示关掉 → 不让它自动恢复（保持现状）
        """
        # 1. 用户主动隐藏 —— 最高优先级，谁都不能自动弹回来
        if bool(self.cfg.get("dock_hidden_by_user", False)):
            return False
        # 2. 用户把"显示底部菜单栏"关了
        if not bool(self.cfg.get("dock_visible", True)):
            return False
        # 3. 用户刚把鼠标挪到边缘唤回来的 —— 给他一点时间点图标。
        #    只在"没有任何窗口占着这块地方"时才算数，否则遮挡一发生就该让开。
        if time.monotonic() < self._peek_until and not self._occluded:
            return True
        # 4. 正在拖菜单栏 / 长按排序
        if self._is_interacting():
            return True
        # 5. 有窗口占着这块地方 → 让开。全屏和普通遮挡各有各的开关，
        #    这样关掉新开关就能回到"只有全屏才让开"的老行为（需求第 13 条）。
        if self._occluded:
            if self._fullscreen and bool(self.cfg.get("dock_avoid_fullscreen", True)):
                return False
            if self._covered and bool(self.cfg.get("dock_avoid_overlap", True)):
                return False
        # 6. 回到桌面自动显示
        if bool(self.cfg.get("dock_auto_show", True)):
            return True
        # 7. 自动显示被关掉 → 不主动把它放回来。
        #    ⚠️ 注意这里**不是**"什么都不做"：上面第 5 条已经让它在遮挡时让开了，
        #    只是现在不再自动恢复。要它回来得靠边缘唤回或托盘菜单。
        #    （这正是"回到桌面自动显示"关掉时该有的样子：不自己冒出来。）
        return not self.dock.isHidden()

    def _is_interacting(self) -> bool:
        """菜单栏是不是正在被鼠标操作（拖动整条 / 长按排序）。"""
        try:
            return getattr(self.dock, "_mode", "") not in ("", None)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 执行：显隐 + 动画
    # ------------------------------------------------------------------
    def _apply(self, want_visible: bool) -> None:
        if self._animating:
            # 动画期间状态又变了：让它播完再纠正（`_finish_*` 里会重算一次），
            # 硬插一脚会导致同一个窗口正在滑到一半又被反向拽回去。
            return
        visible = not self.dock.isHidden()
        if want_visible == visible:
            return
        # 防抖：两次切换之间至少隔 MIN_SWITCH_GAP，避免贴边抖动时来回闪。
        # 第一次切换不受影响（_last_switch 初始是 0）。
        if time.monotonic() - self._last_switch < MIN_SWITCH_GAP:
            return
        self._last_switch = time.monotonic()
        if want_visible:
            self._show()
        else:
            self._hide()

    def _anim_supported(self) -> bool:
        """离屏平台设不了窗口不透明度、也没法真的挪窗口，直接同步显隐。"""
        try:
            return QApplication.platformName() != "offscreen"
        except Exception:
            return False

    def _show(self) -> None:
        self._hidden_by_me = False
        self._last_action = "show"
        dock = self.dock
        # 一露头就必须能点。
        self._set_click_through(False)
        if not self._anim_supported():
            dock.show_bar()
            return
        # 先设成全透明再 show：否则 show 的那一帧会以"整条不透明、还在原位"
        # 闪一下，然后才开始滑上来。
        try:
            dock.setWindowOpacity(0.0)
        except Exception:
            pass
        dock.show_bar()                     # 这一步把尺寸和落位算准
        home = dock.pos()
        self._anim_home_rect = self._live_dock_rect()
        dock.begin_slide()                  # 位置交给动画，别让 _settle 抢
        self._animate(0.0, 1.0, home, self._finish_show)

    def _hide(self) -> None:
        self._hidden_by_me = True
        self._last_action = "hide"
        dock = self.dock
        if not self._anim_supported():
            self._set_click_through(False)
            dock.hide_bar()
            return
        home = dock.pos()
        self._anim_home_rect = self._live_dock_rect()
        dock.begin_slide()
        # 往下滑出去的这 200ms 里，菜单栏不该再吃掉用户对底部窗口的点击。
        self._set_click_through(True)
        self._animate(1.0, 0.0, home, self._finish_hide)

    def _animate(self, p_from: float, p_to: float, home, on_done) -> None:
        """`p` 是"露出来的程度"：1 = 完全在位，0 = 完全滑到屏幕下方。

        位置和透明度用同一条曲线驱动，所以不会出现"位置到了透明度没到"。
        """
        dock = self.dock
        try:
            height = max(1, int(dock.height()))
        except Exception:
            height = 1
        self._home_pos = home

        anim = QVariantAnimation(self)
        anim.setStartValue(float(p_from))
        anim.setEndValue(float(p_to))
        anim.setDuration(ANIM_MS)
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if p_to > p_from
            else QEasingCurve.Type.InCubic)

        def on_value(value) -> None:
            p = float(value)
            p = 0.0 if p < 0.0 else (1.0 if p > 1.0 else p)
            try:
                dock.setWindowOpacity(p)
                dock.move(home.x(), home.y() + int(round((1.0 - p) * height)))
            except Exception:
                pass

        anim.valueChanged.connect(on_value)
        anim.finished.connect(on_done)
        self._anim = anim
        self._animating = True
        on_value(p_from)
        try:
            anim.start()
        except Exception:
            self._animating = False
            self._anim = None
            on_done()

    def _finish_show(self) -> None:
        self._animating = False
        self._anim = None
        self._anim_home_rect = None
        dock = self.dock
        try:
            dock.setWindowOpacity(1.0)
            if self._home_pos is not None:
                dock.move(self._home_pos)   # 收尾必须精确归位，不能差 1px
        except Exception:
            pass
        try:
            dock.end_slide()                # 先解锁，后面 reposition 才生效
            dock.reposition()
            dock.raise_()
        except Exception:
            pass
        self._home_pos = None
        self._set_click_through(False)
        self._recheck_soon()

    def _finish_hide(self) -> None:
        self._animating = False
        self._anim = None
        self._anim_home_rect = None
        dock = self.dock
        try:
            if self._home_pos is not None:
                # 隐藏前先归位：之后 `GetWindowRect` 拿到的就是"菜单栏本该在
                # 哪儿"，边缘唤回和下一轮判定都靠它。
                dock.move(self._home_pos)
        except Exception:
            pass
        try:
            dock.hide_bar()
            dock.setWindowOpacity(1.0)      # 复位，否则下次显示是全透明的
        except Exception:
            pass
        try:
            dock.end_slide()
        except Exception:
            pass
        self._home_pos = None
        self._set_click_through(False)
        self._recheck_soon()

    def _recheck_soon(self) -> None:
        """动画刚结束，把动画期间攒下的状态变化补算一次。

        不用 `evaluate()` 直接调用：这里可能正处在动画 `finished` 的发射栈里，
        同步再起一个动画会踩到 `_anim` 的赋值顺序。丢给事件循环的下一拍最稳。
        """
        try:
            QTimer.singleShot(0, self._recheck)
        except Exception:
            pass

    def _recheck(self) -> None:
        if not self._started:
            return
        self.evaluate()

    # ------------------------------------------------------------------
    # 点击穿透（滑出去的路上别挡着用户点下面那层）
    # ------------------------------------------------------------------
    def _set_click_through(self, on: bool) -> None:
        """把菜单栏窗口设成 / 取消"点击穿透"（`WS_EX_TRANSPARENT`）。

        只在**滑出动画**期间打开，动画结束立刻关掉——这个位留着不放，
        菜单栏就永远点不动了，是比"多挡 200ms"严重得多的故障。
        所以 `_show` / `_finish_show` / `_finish_hide` / `stop` 都会清一次。
        """
        on = bool(on) and self._anim_supported()
        if on == self._click_through:
            return
        if self._user32 is None or os.name != "nt":
            return
        try:
            hwnd = int(self.dock.winId())
            if not hwnd:
                return
            style = self._user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            new = (style | WS_EX_TRANSPARENT) if on else (
                style & ~WS_EX_TRANSPARENT)
            if new != style:
                self._user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
            self._click_through = on
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 边缘唤回
    # ------------------------------------------------------------------
    def peek(self) -> None:
        """把菜单栏唤回来，并给一段"别急着再藏"的保持期。

        只由 `_check_edge()` 在"确认用户就在桌面上"之后调用。
        保持期**不压过遮挡判定**（见 `_desired_visible` 第 3 条）：
        保持期内一旦有窗口压上来，菜单栏照样立刻让开。
        """
        self._peek_until = time.monotonic() + PEEK_HOLD
        self._edge_since = 0.0
        self.evaluate()

    def _mouse_on_edge(self) -> bool:
        """鼠标是不是停在"菜单栏本该在的那条"上。

        两边都用 **Qt 的逻辑坐标**（`frameGeometry()` 和 `QCursor.pos()`），
        天然同一个坐标系，多显示器 / 高 DPI 下都不用自己换算。
        窗口隐藏后 `frameGeometry()` 依然是上次的位置——`hide()` 不动几何。

        这里只是**读**鼠标位置：不装钩子、不占区域，所以绝不会拦截
        用户对底部其他窗口的点击（需求第六节最后一条）。
        """
        try:
            geo = self.dock.frameGeometry()
            if geo.width() <= 0 or geo.height() <= 0:
                return False
            return geo.contains(QCursor.pos())
        except Exception:
            return False

    def _on_desktop(self) -> bool:
        """现在是不是"就停在桌面上"——没有任何别的窗口占着前台。

        边缘唤回**只在这里生效**。判据两条，都满足才算：

        1. 菜单栏那一带没被占（`_fullscreen` / `_covered` 都是 False）；
        2. 前台窗口就是桌面本身（`Progman` / `WorkerW` / `SHELLDLL_DefView`）。

        为什么第 2 条不能省：只看"有没有窗口压住菜单栏"是不够的。
        全屏播放器把鼠标甩到底部、浏览器窗口没压住菜单栏但用户正在里面打字，
        这两种情况下鼠标都可能正好划过菜单栏那块矩形——只看矩形的话，
        菜单栏就会莫名其妙弹出来。加上"前台必须是桌面"之后，
        **只有用户真的在桌面上找菜单栏时才会弹**。

        探测关掉时（离屏自检）一律返回 False：没有窗口管理器，
        `GetForegroundWindow` 拿到的是真实桌面上的窗口，判定必然失真。
        """
        if not self.probe_enabled:
            return False
        try:
            if self._fullscreen or self._covered:
                return False
            if self.tray is not None and not self.tray._desktop_is_foreground():
                return False
        except Exception:
            return False
        return True

    def _check_edge(self) -> None:
        """鼠标在菜单栏那一带停久了就唤回来；已经唤回来且还压在上面就续期。

        ⚠️ 开头那道 `_on_desktop()` 闸门是**必需的**，不是保险：
        没有它的时候，全屏看视频把鼠标移到屏幕底部找播放控制条，
        菜单栏就会"自己弹出来"盖在视频上——这正是用户报的那个 bug。
        """
        if not self._on_desktop():
            self._edge_since = 0.0
            return

        now = time.monotonic()
        hidden = self.dock.isHidden()

        if not hidden:
            # 已经显示着：鼠标还压在菜单栏上就一直续期，
            # 让用户能从容地挪到图标上点下去，不会点一半又滑走。
            if now < self._peek_until and self._mouse_on_edge():
                self._peek_until = now + PEEK_HOLD
            else:
                self._edge_since = 0.0
            return

        if not self._mouse_on_edge():
            self._edge_since = 0.0
            return
        if self._edge_since == 0.0:
            self._edge_since = now
            return
        if now - self._edge_since >= EDGE_DWELL:
            self.peek()

    # ------------------------------------------------------------------
    # 定时器回调
    # ------------------------------------------------------------------
    def _on_poll(self) -> None:
        self._dirty = False
        self.evaluate()
        self._check_edge()

    # ------------------------------------------------------------------
    # 供自检用的探针
    # ------------------------------------------------------------------
    def debug_state(self) -> "dict[str, object]":
        return {
            "occluded": self._occluded,
            "fullscreen": self._fullscreen,
            "covered": self._covered,
            "on_desktop": self._on_desktop(),
            "peek": max(0.0, self._peek_until - time.monotonic()),
            "animating": self._animating,
            "click_through": self._click_through,
            "hidden_by_me": self._hidden_by_me,
            "last_action": self._last_action,
            "hooks": len(self._hooks),
            "covering": len(self.covering_windows()),
        }
