#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统托盘常驻程序
================
需求 2 / 4：程序后台运行，主窗口默认隐藏，只留任务栏右下角托盘图标；
托盘右键菜单包含：打开主面板、显示全部快捷方式与文件、刷新文件列表、
还原桌面、设置、退出；常用程序会作为顶层菜单项直接出现在托盘菜单里。
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
import ctypes
from ctypes import wintypes
from pathlib import Path

from qt_compat import (
    QAction, QApplication, QIcon, QMenu, QMessageBox, QSystemTrayIcon, Qt,
    QThread, QTimer, QWidget, Signal,
)

import config
import engine
import nest
import safety
import theme as theme_mod
from desktop_browser import DesktopBrowser
from dock import DockBar
from panel import MainPanel
from settings import SettingsDialog
from widgets import app_icon


class MONITORINFO(ctypes.Structure):
    """`GetMonitorInfoW` 需要的结构体。

    老老实实声明字段，别把缓冲区 cast 成 c_long[16]——那样索引很容易错位，
    工作区会读成 0（之前就踩过，直接除零崩了）。
    """

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# --------------------------------------------------------------------------
# 后台扫描：收纳目录 + 历史
# --------------------------------------------------------------------------
class ScanWorker(QThread):
    done = Signal(object, object, object, str)     # items, history, counts, error

    def __init__(self, desktop: Path, parent=None):
        super().__init__(parent)
        self.desktop = desktop

    def run(self) -> None:  # noqa: D102
        error = ""
        try:
            items = nest.list_nest_items()
            history = nest.read_journal(40)
            counts = {
                "desktop": nest.desktop_item_count(self.desktop),
                "nest": len(items),
                "folders": sum(1 for i in items if i.is_dir),
                "shortcuts": sum(1 for i in items if i.kind == "shortcut"),
            }
        except Exception as exc:
            config.log(f"扫描失败：{type(exc).__name__}: {exc}")
            items, history, counts = [], [], {"desktop": 0, "nest": 0,
                                              "folders": 0, "shortcuts": 0}
            error = f"{type(exc).__name__}: {exc}"
        self.done.emit(items, history, counts, error)


# --------------------------------------------------------------------------
# 主程序
# --------------------------------------------------------------------------
class TrayApp(QWidget):
    """托盘常驻的应用主体。"""

    def __init__(self, cfg: config.Config, silent: bool = False):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("桌面收纳")
        self.hide()                              # 自己从不显示，只是个事件宿主

        self.nest_items: "list" = []
        self.history: "list[dict]" = []
        self.counts: "dict[str, int]" = {}
        self._scan: "ScanWorker | None" = None
        self._quitting = False
        self._repository_note = ""
        self._dock_hidden_for_fullscreen = False
        # 崩溃兜底：应急还原只跑一次
        self._emergency_done = False
        self._original_excepthook = None
        # 全屏让开的防抖计数（连续两次才动作，见 _auto_show_tick）
        self._fs_streak = 0
        self._normal_streak = 0

        # ---- 子窗口 ----
        self.panel = MainPanel(cfg)
        self.panel.request_refresh.connect(self.refresh)
        self.panel.request_take.connect(self.take_desktop_now)
        self.panel.request_restore.connect(self.restore_desktop)
        self.panel.request_browse.connect(self.show_desktop_files)
        self.panel.request_settings.connect(self.open_settings)
        self.panel.request_quit.connect(self.quit_app)
        self.panel.quick_changed.connect(self._on_quick_changed)
        self.panel.extensions_changed.connect(self._on_extensions_changed)

        # ---- 收纳面板（Dock 左边第一个控件）----
        self.desktop_browser = DesktopBrowser(cfg)
        self.desktop_browser.request_refresh.connect(self.refresh)
        self.desktop_browser.request_quick_changed.connect(self._on_quick_changed)
        self.desktop_browser.request_settings.connect(self.open_settings)
        self.desktop_browser.request_restore_all.connect(self.restore_desktop)

        # ---- 底部菜单栏 ----
        self.dock = DockBar(cfg)
        self.dock.open_desktop_files.connect(self.show_desktop_files)
        self.dock.toggle_desktop_files.connect(self.desktop_browser.toggle_window)
        self.dock.open_panel.connect(self.open_panel)
        self.dock.open_settings.connect(self.open_settings)
        self.dock.quit_app.connect(self.quit_app)
        self.dock.quick_changed.connect(self._on_quick_changed)
        self.dock.request_refresh.connect(self.refresh)
        self.dock.hide_requested.connect(self._on_dock_hidden)
        # 收纳面板是"坐在"菜单栏上方的浮层：把 Dock 的真实高度交给它，
        # 底边才会正好落在菜单栏顶边之上（菜单栏变高也不会被压住）。
        self.desktop_browser.set_bottom_reserve(self._dock_reserve)

        # ---- 托盘 ----
        # 托盘图标直接复用程序图标（同一套"抽屉"造型，见 widgets.app_icon）
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"{config.APP_NAME_FULL} · 正在运行")
        self.tray.activated.connect(self._on_tray_activated)
        self.menu = QMenu()
        self.rebuild_tray_menu()
        self.tray.setContextMenu(self.menu)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            config.log("系统托盘不可用，改为直接显示主面板")

        # ---- 启动流程 ----
        cfg.save()          # 尽早落一次盘，确认配置可写、也方便排查启动问题
        nest.ensure_dirs()
        nest.sync_system_links()
        # 上次没退干净（崩溃 / 被强杀）时收纳目录里会残留东西。
        # 先把残留的还原回桌面，再做这次收纳——避免"两边各一份"。
        self.recover_leftovers()
        # 启动即收纳：把桌面上的东西（含此电脑、回收站这些系统图标）收进收纳目录，
        # 并隐藏桌面图标，做到"桌面完全空白"。
        if not silent or bool(cfg.get("auto_take_on_start", True)):
            self.auto_take_desktop()
        self.refresh()
        # 底部菜单栏：默认显示，桌面清空后它就是随手可点的入口
        if bool(cfg.get("dock_visible", True)):
            QTimer.singleShot(200, self.dock.show_bar)
        QTimer.singleShot(600, self._startup_prompt)
        # 回到桌面时自动把菜单栏显示回来（用户主动隐藏过就不再弹）
        QTimer.singleShot(1500, self._auto_show_tick)
        # 纯托盘程序如果一点提示都没有，用户会不知道装到哪去了。
        # 所以：首次运行（或没有托盘可用时）主动把主面板露出来；
        # 开机自启走 --silent，不打扰。
        #
        # 注意：这里**不能直接 open_panel()**。扫描线程（ScanWorker）这时正在跑，
        # 在"后台线程读目录 + 主线程创建窗口"同时发生时，打包成 exe 的版本会在
        # panel.show() 里原生 abort（0xC0000409 / ucrtbase），连 Python 异常都没有。
        # 改成先记个标记，等扫描结束、事件循环稳定后再显示。
        self._panel_pending = (not silent) and self._should_show_panel_on_start()
        if self._panel_pending:
            QTimer.singleShot(800, self._open_pending_panel)

    def _should_show_panel_on_start(self) -> bool:
        """开机时要不要把主面板显示出来。

        需求 2 要求"主窗口默认隐藏，仅驻留托盘"。这里把选择权交给用户：
        first = 只在第一次运行时露个面（默认，避免用户找不到程序在哪）
        always = 每次启动都显示
        never  = 永远静默驻留托盘
        """
        mode = str(self.cfg.get("panel_on_start", "first"))
        if mode == "always":
            return True
        if mode == "never":
            return False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return True                        # 没有托盘就只能靠窗口
        return not bool(self.cfg.get("first_run_done"))

    def mark_first_run_done(self) -> None:
        self.cfg.set("first_run_done", True)

    # ------------------------------------------------------------------
    # 托盘菜单
    # ------------------------------------------------------------------
    def rebuild_tray_menu(self) -> None:
        """重建托盘菜单：顶层就是常用启动项（需求 4）。"""
        self.menu.clear()

        quick = self.cfg.quick_items
        if quick:
            header = self.menu.addAction("常用启动")
            header.setEnabled(False)
            for index, entry in enumerate(quick):
                path = Path(entry["path"])
                action = QAction(entry["name"] or path.name, self.menu)
                icon = self._quick_icon(path)
                if not icon.isNull():
                    action.setIcon(icon)
                exists = safety.safe_exists(path)
                if not exists:
                    action.setText(f"{action.text()}（已失效）")
                action.setEnabled(exists)
                action.triggered.connect(
                    lambda _checked=False, p=path: self.launch_quick(p))
                self.menu.addAction(action)
            self.menu.addSeparator()
            manage = self.menu.addAction("管理常用启动…")
            manage.triggered.connect(lambda: self.open_browse())
            self.menu.addSeparator()
        else:
            hint = self.menu.addAction("（右键仓库里的项目可加入常用启动）")
            hint.setEnabled(False)
            self.menu.addSeparator()

        action_panel = self.menu.addAction("打开主面板")
        action_panel.triggered.connect(self.open_panel)

        action_desktop = self.menu.addAction("打开收纳面板（分页浏览）")
        action_desktop.triggered.connect(self.show_desktop_files)

        dock_visible = bool(self.cfg.get("dock_visible", True))
        action_dock = self.menu.addAction("显示底部菜单栏")
        action_dock.setCheckable(True)
        action_dock.setChecked(dock_visible)
        action_dock.triggered.connect(lambda _checked: self.toggle_dock())

        action_auto = self.menu.addAction("回到桌面自动显示菜单栏")
        action_auto.setCheckable(True)
        action_auto.setChecked(bool(self.cfg.get("dock_auto_show", True)))
        action_auto.triggered.connect(lambda _checked: self._toggle_auto_show())

        self.menu.addSeparator()

        action_refresh = self.menu.addAction("刷新")
        action_refresh.triggered.connect(self.refresh)

        action_take = self.menu.addAction("收纳桌面")
        action_take.triggered.connect(self.take_desktop_now)

        action_restore = self.menu.addAction("还原桌面")
        action_restore.triggered.connect(self.restore_desktop)
        action_restore.setEnabled(bool(self.nest_items))

        self.menu.addSeparator()

        action_settings = self.menu.addAction("设置")
        action_settings.triggered.connect(self.open_settings)

        autostart = self.menu.addAction("开机自启")
        autostart.setCheckable(True)
        status = config.autostart_status()
        autostart.setChecked(bool(status) if status is not None
                             else bool(self.cfg.get("autostart")))
        autostart.triggered.connect(lambda checked: self.toggle_autostart(checked))

        self.menu.addSeparator()

        action_quit = self.menu.addAction("退出程序")
        action_quit.triggered.connect(self.quit_app)

        self._update_tooltip()

    def _quick_icon(self, path: Path) -> QIcon:
        try:
            import icons
            from qt_compat import raw_to_icon

            hint = engine.resolve_shortcut_target(path) if path.suffix.lower() == ".lnk" else None
            raw = icons.get_icon(path, 16, exe_hint=hint)
            icon = raw_to_icon(raw)
            return icon if icon is not None else QIcon()
        except Exception:
            return QIcon()

    def _update_tooltip(self) -> None:
        pending = self.counts.get("desktop", 0)
        self.tray.setToolTip(
            f"{config.APP_NAME_FULL}\n"
            f"桌面待收纳：{pending} 项\n"
            f"收纳面板里：{len(self.nest_items)} 项\n"
            f"常用启动：{len(self.cfg.quick_items)} 项")

    # ------------------------------------------------------------------
    # 扫描 / 刷新
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self._scan is not None and self._scan.isRunning():
            return
        nest.ensure_dirs()
        nest.sync_system_links()
        worker = ScanWorker(self.cfg.desktop, self)
        worker.done.connect(self._on_scan_done)
        self._scan = worker
        worker.start()

    def _on_scan_done(self, items, history, counts, error: str) -> None:
        self.nest_items, self.history, self.counts = items, history, counts
        self._scan = None
        if error:
            config.log(f"扫描出错：{error}")
        self.desktop_browser.set_items(items)
        self.dock.set_items(items)
        self.dock.set_desktop_count(len(items))
        self.panel.update_overview(
            items=items,
            nest_items=len(items),
            desktop_pending=counts.get("desktop", 0),
            folders=counts.get("folders", 0),
            shortcuts=counts.get("shortcuts", 0),
            history=history,
        )
        self.rebuild_tray_menu()
        if self._repository_note:
            self.panel.show_notice(self._repository_note)
        if self._quitting:
            return

    def _on_quick_changed(self) -> None:
        """常用启动列表变了：托盘菜单、Dock、面板都要重建。"""
        self.rebuild_tray_menu()
        if hasattr(self, "dock"):
            self.dock.rebuild()
        if hasattr(self, "desktop_browser"):
            self.desktop_browser._rebuild_apps()

    def _on_settings_changed(self) -> None:
        self.rebuild_tray_menu()
        dark = bool(self.cfg.get("dark"))
        self.panel.apply_theme(dark)
        self.desktop_browser.apply_theme(dark)
        self.dock.apply_theme(True)
        self.dock.rebuild()
        # 设置窗口里也能改「显示文件后缀名」，回来要把两处界面同步一遍
        self.panel.sync_extensions()
        self.desktop_browser.apply_extensions()
        self.refresh()

    # ------------------------------------------------------------------
    # 桌面收纳：启动收纳 / 退出还原
    # ------------------------------------------------------------------
    def show_desktop_files(self) -> None:
        """打开收纳面板（上拉菜单）。再点一次会收起，见 toggle_desktop_files。"""
        self.desktop_browser.show_window()

    def _dock_reserve(self) -> int:
        """收纳面板贴底时要给底部菜单栏让开的高度（含一点间隙）。"""
        try:
            if self.dock.isVisible():
                return int(self.dock.height()) + 14
        except Exception:
            pass
        return 44

    def recover_leftovers(self) -> None:
        """恢复上次没收干净的内容。

        如果上一次是崩溃 / 被强杀退出的，收纳目录里会留下东西，而桌面可能
        还缺着。这里先把它们放回桌面，保证"桌面永远是完整的"，
        之后本次的收纳才是从一个干净状态开始的。
        """
        if not nest.nest_has_content():
            return
        # 桌面上的东西都还在（比如上次是复制成功但没删源），先把重复的清理掉
        store = nest.desktop_store()
        duplicates = 0
        try:
            for entry in store.iterdir():
                if safety.safe_exists(self.cfg.desktop / entry.name):
                    nest._remove_quietly(entry)
                    duplicates += 1
        except OSError:
            pass
        if duplicates:
            config.log(f"启动清理：收纳目录里有 {duplicates} 个与桌面重复的条目，已清理")

        if not nest.nest_has_content():
            return
        result = nest.restore_to_desktop(self.cfg.desktop)
        config.log(f"启动恢复上次残留：{result.summary()}")
        self.cfg.set("nest_active", False)

    def auto_take_desktop(self) -> None:
        """启动时自动把桌面上的东西收进收纳目录。"""
        if not bool(self.cfg.get("auto_take_on_start", True)):
            return
        desktop = self.cfg.desktop
        if not safety.safe_exists(desktop):
            return
        pending = nest.desktop_item_count(desktop)
        if pending == 0:
            # 桌面本来就干净，但图标可能还露着，按设置处理
            self._apply_icon_visibility()
            return
        config.log(f"启动自动收纳：桌面有 {pending} 项待处理")
        result = nest.take_from_desktop(desktop)
        config.log(f"自动收纳结果：{result.summary()}")
        self.cfg.set("nest_active", result.moved > 0)
        self._apply_icon_visibility()
        if result.failed:
            self.panel.show_notice(
                "有 " + str(len(result.failed)) + " 项没能收纳："
                + "、".join(n for n, _ in result.failed[:3]))
        self.refresh()

    def _apply_icon_visibility(self) -> None:
        """按设置隐藏 / 显示桌面图标，做到"桌面完全空白"。"""
        want_hidden = bool(self.cfg.get("hide_desktop_icons", True))
        if not want_hidden:
            return
        state = nest.icons_visible()
        if state is False:
            return                       # 已经是隐藏的
        ok, reason = nest.set_icons_visible(False)
        if not ok:
            config.log(f"隐藏桌面图标失败：{reason}")

    def restore_desktop_on_exit(self) -> None:
        """退出时把收纳目录里的东西全部放回桌面。"""
        if not bool(self.cfg.get("restore_on_exit", True)):
            return
        if not nest.nest_has_content():
            self._show_desktop_icons()
            return
        result = nest.restore_to_desktop(self.cfg.desktop)
        config.log(f"退出还原结果：{result.summary()}")
        self._show_desktop_icons()
        self.cfg.set("nest_active", False)

    def _show_desktop_icons(self) -> None:
        if not bool(self.cfg.get("hide_desktop_icons", True)):
            return
        state = nest.icons_visible()
        if state is True:
            return
        nest.set_icons_visible(True)

    def toggle_dock(self) -> None:
        """显示 / 隐藏底部菜单栏（从托盘菜单操作）。"""
        visible = bool(self.cfg.get("dock_visible", True))
        self.cfg.set("dock_visible", not visible)
        if visible:
            self.dock.hide_bar()
            self.cfg.set("dock_hidden_by_user", True)      # 记住是用户主动关的
        else:
            self.cfg.set("dock_hidden_by_user", False)     # 手动打开 → 恢复自动显示
            self.dock.show_bar()
        self.rebuild_tray_menu()

    def _toggle_auto_show(self) -> None:
        """开关「回到桌面自动显示菜单栏」。"""
        enabled = not bool(self.cfg.get("dock_auto_show", True))
        self.cfg.set("dock_auto_show", enabled)
        if enabled:
            self.cfg.set("dock_hidden_by_user", False)
            self.dock.show_bar()
        self.rebuild_tray_menu()

    def _on_dock_hidden(self) -> None:
        """菜单栏上的「隐藏」按钮点了之后：记住是用户主动隐藏的。"""
        self.cfg.set("dock_hidden_by_user", True)
        self.rebuild_tray_menu()
        self.tray.showMessage(
            config.APP_NAME_FULL,
            "菜单栏已隐藏。\n右键托盘图标 → 勾选「显示底部菜单栏」可以再打开。",
            QSystemTrayIcon.MessageIcon.Information, 5000)

    def _on_extensions_changed(self) -> None:
        """「显示文件后缀名」开关变了：收纳面板 + 主面板列表一起重画。

        只改界面文字，磁盘上的文件名一个字都不动。
        """
        self.desktop_browser.apply_extensions()
        self.panel.refresh_items()

    # ------------------------------------------------------------------
    # 回到桌面时自动显示菜单栏
    # ------------------------------------------------------------------
    def _desktop_is_foreground(self) -> bool:
        """当前活动窗口是不是桌面本身。

        桌面可能是 Progman（传统）或 WorkerW（Win10/11 壁纸层），按类名判断，
        比看标题可靠（标题会随语言变）。
        """
        return self._foreground_class() in ("Progman", "WorkerW", "SHELLDLL_DefView")

    @staticmethod
    def _foreground_class() -> str:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buffer, 256)
            return buffer.value
        except Exception:
            return ""

    @staticmethod
    def _foreground_hwnd() -> int:
        try:
            import ctypes

            return int(ctypes.windll.user32.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def _foreground_is_self(self) -> bool:
        """前台窗口是不是本程序自己的窗口。

        **这是"翻页时菜单栏时不时消失"的根因修复。**
        收纳面板就贴在菜单栏正上方、宽度也盖得住菜单栏那一带；不把自己人排除掉的话，
        下面 `_foreground_is_fullscreen()` 的第 3 条（"窗口盖住了菜单栏所在区域"）
        就会把**我们自己刚打开的收纳面板**当成"挡住菜单栏的别的程序"，
        于是自动避让逻辑立刻把菜单栏收起来——表现就是点开面板 / 翻页时菜单栏闪没。

        先比窗口句柄（最准，也不依赖 PID），再比进程号兜住菜单、气泡这些临时窗口。
        """
        hwnd = self._foreground_hwnd()
        if not hwnd:
            return False
        for widget in (getattr(self, "panel", None),
                       getattr(self, "desktop_browser", None),
                       getattr(self, "dock", None)):
            try:
                if widget is not None and int(widget.winId()) == hwnd:
                    return True
            except Exception:
                continue
        try:
            import ctypes

            pid = ctypes.c_ulong(0)
            ctypes.windll.user32.GetWindowThreadProcessId(
                ctypes.c_void_p(hwnd), ctypes.byref(pid))
            return bool(pid.value) and int(pid.value) == os.getpid()
        except Exception:
            return False

    def _dock_in_use(self) -> bool:
        """菜单栏此刻是不是"正在被用"——收纳面板开着（翻页 / 搜索）就算。

        避让逻辑只该响应**别的**程序的前台窗口状态；收纳面板是自己人开的浮层，
        它开着的时候菜单栏必须稳稳留着，绝不能因为我们自己弹了个面板就把菜单栏藏了。
        """
        browser = getattr(self, "desktop_browser", None)
        return bool(browser is not None and browser.isVisible())

    def _foreground_is_fullscreen(self) -> bool:
        """前台窗口是不是"占满屏幕"、会挡住菜单栏的类型。

        判据（任一成立就让开）：
        * 真全屏：铺满整块显示器；
        * **最大化**：窗口外框基本铺满工作区（工作区 = 显示器减去任务栏）；
        * 窗口矩形盖住了菜单栏那一带。

        注意：**不能用 `IsZoomed()` 判断最大化**。实测 Chrome 这类自绘标题栏的
        程序不设置 `WS_MAXIMIZE` 风格位，`IsZoomed` 一直返回 0，
        于是"打开浏览器菜单栏不让开"就修不好。量外框尺寸才准。

        另外：**本程序自己的窗口一律不算**（见 `_foreground_is_self`）——
        收纳面板盖住菜单栏那一条是设计如此，不是"别的程序在遮挡"。
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            if self._foreground_is_self():         # 自己的窗口不算
                return False
            if self._desktop_is_foreground():      # 桌面自己不算
                return False
            if user32.IsIconic(hwnd):              # 最小化不算
                return False
            if not user32.IsWindowVisible(hwnd):
                return False

            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return False

            monitor = user32.MonitorFromWindow(hwnd, 2)     # NEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return False
            mon_width = info.rcMonitor.right - info.rcMonitor.left
            mon_height = info.rcMonitor.bottom - info.rcMonitor.top
            work_width = info.rcWork.right - info.rcWork.left
            work_height = info.rcWork.bottom - info.rcWork.top
            if mon_width <= 0 or work_width <= 0:
                return False

            # 1) 真全屏：铺满整块显示器
            if width >= mon_width * 0.96 and height >= mon_height * 0.96:
                return True
            # 2) 最大化：按**面积占比**判断。
            #    不能要求"宽高都接近 100%"——实测 1920x1080 上最大化的窗口是
            #    1619x1036（宽度只占 84%），按边长判会漏掉。
            #    但也不能只看"盖住了菜单栏那块区域"——普通窗口拖到屏幕底部、
            #    窗口打开动画的中间帧都会短暂满足那个条件，结果就是菜单栏
            #    疯狂闪现（"打开非全屏软件菜单栏频繁闪烁"就是这么来的）。
            #    所以这里只认"够大"的窗口：宽度也得占够，否则一律不让开。
            coverage = (width * height) / float(work_width * work_height)
            if coverage >= 0.80 and height >= work_height * 0.90:
                return True
            if width >= mon_width * 0.98 and height >= work_height * 0.94:
                return True
            return False
        except Exception:
            return False

    def _auto_show_tick(self) -> None:
        """定时检查菜单栏该不该露面。

        两条规则：
        * 人回到桌面 → 自动显示（除非用户主动点过隐藏）；
        * 有人在全屏看视频 / 演示 → 自动让开，不遮挡内容；
          全屏结束后再自己回来。

        ⚠️ 这里**只动窗口的可见性**（`show_bar` / `hide_bar`），
        绝不改 `dock_visible` / `dock_hidden_by_user` 这些状态变量——
        否则"打开收纳面板"会被误当成"用户把菜单栏关了"，之后再也不自动弹回来。

        **防闪烁**：只有当"要让开"这个状态**连续两次 tick（约 2.4 秒）都成立**
        才真的隐藏；恢复则要求"不需要让开"连续两次成立。这样：
        * 切换程序、窗口动画、拖动窗口这些瞬时状态不会引起显隐抖动；
        * 用户真的最大化/全屏时，最多 2.4 秒后让开，感知上依然是"立刻"。
        """
        try:
            if bool(self.cfg.get("dock_hidden_by_user", False)):
                # 用户手动关的：保持隐藏，绝不自动恢复
                self._fs_streak = 0
                self._normal_streak = 0
                return
            if not bool(self.cfg.get("dock_auto_show", True)):
                self._fs_streak = 0
                self._normal_streak = 0
                return

            if self._dock_in_use():
                # 收纳面板开着（翻页 / 搜索）时菜单栏必须稳住：不让开，也不隐藏。
                self._dock_hidden_for_fullscreen = False
                self._fs_streak = 0
                self._normal_streak = 0
                if not self.dock.isVisible() and bool(self.cfg.get("dock_visible", True)):
                    self.dock.show_bar()
                    self.rebuild_tray_menu()
                return

            fullscreen = self._foreground_is_fullscreen()
            if fullscreen:
                self._normal_streak = 0
                self._fs_streak += 1
                # 连续两次确认才让开，避开窗口打开动画等瞬时状态
                if (self._fs_streak >= 2 and self.dock.isVisible()
                        and bool(self.cfg.get("dock_avoid_fullscreen", True))):
                    self.dock.hide_bar()
                    self._dock_hidden_for_fullscreen = True
                return

            self._fs_streak = 0
            if not self.dock.isVisible():
                # 该不该恢复：因为我们让开过，或者配置本来就是要显示的
                if self._dock_hidden_for_fullscreen \
                        or bool(self.cfg.get("dock_visible", True)):
                    self._normal_streak += 1
                    if self._normal_streak >= 2:
                        self._dock_hidden_for_fullscreen = False
                        self._normal_streak = 0
                        self.dock.show_bar()
                        self.rebuild_tray_menu()
            else:
                # 已经显示着，就别再调 show_bar——重复 show + raise 本身就会闪
                self._normal_streak = 0
        except Exception as exc:
            config.log(f"菜单栏自动显隐失败：{type(exc).__name__}: {exc}")
        finally:
            QTimer.singleShot(1200, self._auto_show_tick)

    # ------------------------------------------------------------------
    # 窗口
    # ------------------------------------------------------------------
    def open_panel(self) -> None:
        self.panel.apply_theme(bool(self.cfg.get("dark")))
        self.panel.show()
        self.panel.setWindowState(
            self.panel.windowState() & ~Qt.WindowState.WindowMinimized)
        self.panel.raise_()
        self.panel.activateWindow()

    def _open_pending_panel(self) -> None:
        """扫描线程结束后再显示主面板。

        直接把面板显示放在启动流程里，会在"扫描线程还在跑"的时候创建窗口，
        打包版会在 show() 里原生崩溃。所以等线程收工再显示；万一还没结束，
        就再等一会儿。
        """
        if not getattr(self, "_panel_pending", False):
            return
        if self._scan is not None and self._scan.isRunning():
            QTimer.singleShot(400, self._open_pending_panel)
            return
        self._panel_pending = False
        try:
            self.open_panel()
            self.mark_first_run_done()
        except Exception as exc:  # noqa: BLE001
            config.log(f"显示主面板失败：{type(exc).__name__}: {exc}")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg, self, dark=bool(self.cfg.get("dark")))
        if dialog.exec():
            self._on_settings_changed()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # 左键单击：开关收纳面板（上拉菜单，再点一次收起）
            self.desktop_browser.toggle_window()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_panel()

    # ------------------------------------------------------------------
    # 常用启动
    # ------------------------------------------------------------------
    def launch_quick(self, path: Path) -> None:
        ok, reason = engine.launch(path)
        if not ok:
            self.tray.showMessage("打不开", f"{path.name}\n{reason}",
                                  QSystemTrayIcon.MessageIcon.Warning, 4000)

    # ------------------------------------------------------------------
    # 还原
    # ------------------------------------------------------------------
    def emergency_restore(self, reason: str = "") -> bool:
        """**不做任何询问**，直接把收纳目录里的东西搬回桌面。

        这个方法是给"崩溃兜底"用的，必须满足几个苛刻条件：

        * **不能弹窗**——崩溃路径上再弹模态框就是二次事故；
        * **不能抛异常**——它自己崩了就没兜底了，所以整体 try/except 包住；
        * **可重入**——退出流程和异常钩子可能都调它，用标志位保证只跑一次；
        * **尊重用户设置**——用户明确关掉"退出自动还原"就不动（`force` 场景除外）。

        返回是否真的执行了还原。
        """
        if self._emergency_done:
            return False
        self._emergency_done = True
        try:
            if not bool(self.cfg.get("restore_on_exit", True)):
                return False
            if not nest.nest_has_content():
                # 桌面是干净的，但图标可能被我们藏起来了，也要恢复
                self._show_desktop_icons()
                return False
            result = nest.restore_to_desktop(self.cfg.desktop)
            self._show_desktop_icons()
            config.log(f"应急还原（{reason or '未知原因'}）：{result.summary()}")
            if result.failed:
                for name, why in result.failed[:8]:
                    config.log(f"  未能还原：{name} —— {why}")
            try:
                self.cfg.set("nest_active", False)
                self.cfg.save()
            except Exception:
                pass
            return True
        except Exception as exc:  # noqa: BLE001
            try:
                config.log(f"应急还原失败：{type(exc).__name__}: {exc}")
            except Exception:
                pass
            return False

    def install_crash_guards(self) -> None:
        """挂上全局异常钩子：**任何未捕获异常都要先把桌面还回去**。

        为什么必须有这个：程序把桌面文件暂存在收纳目录里，一旦崩在
        "收纳完成、还没还原"的窗口期，用户看到的就是**空桌面**——哪怕文件其实
        都还在。所以崩溃路径上第一件事必须是还原，绝不能让用户以为文件丢了。

        覆盖三条路径：
        1. 主线程未捕获异常（`sys.excepthook`）；
        2. 子线程未捕获异常（`threading.excepthook`，扫描线程就属于这类）；
        3. Qt 事件循环内部抛出的异常（`app.exec()` 那层 try/except）。
        """
        self._emergency_done = False
        original_hook = sys.excepthook

        def hook(exc_type, exc_value, exc_tb):
            try:
                detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                config.log("未捕获异常：\n" + detail)
            except Exception:
                pass
            self.emergency_restore(f"未捕获异常 {getattr(exc_type, '__name__', exc_type)}")
            if original_hook is not None and original_hook is not sys.__excepthook__:
                try:
                    original_hook(exc_type, exc_value, exc_tb)
                    return
                except Exception:
                    pass
            try:
                sys.__excepthook__(exc_type, exc_value, exc_tb)
            except Exception:
                pass

        sys.excepthook = hook
        self._original_excepthook = original_hook

        def thread_hook(args):
            try:
                detail = "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback))
                config.log(f"线程 {getattr(args.thread, 'name', '?')} 未捕获异常：\n{detail}")
            except Exception:
                pass
            self.emergency_restore(
                f"线程异常 {getattr(args.exc_type, '__name__', args.exc_type)}")

        try:
            threading.excepthook = thread_hook
        except Exception:
            pass

    def restore_desktop(self) -> None:
        """把收纳目录里的全部内容（含文件夹）还原回桌面。"""
        items = nest.list_nest_items()
        # shell 位置映射只读一次（逐条调 shell_path_for 会让每个条目读一遍 links.json）
        shell_names = nest.shell_path_map()
        content = [i for i in items if not shell_names.get(i.path.stem)]
        if not content:
            QMessageBox.information(self, "还原桌面", "收纳目录里没有可还原的内容。")
            return
        folders = [i for i in content if i.is_dir]
        files = [i for i in content if not i.is_dir]
        answer = QMessageBox.question(
            self, "还原桌面",
            f"把收纳的 {len(content)} 项全部搬回桌面？\n\n"
            f"目标：{self.cfg.desktop}\n"
            f"其中：文件 {len(files)} 个"
            + (f"，文件夹 {len(folders)} 个（连同里面的内容一起搬回）" if folders else "")
            + "\n\n文件只是移动，不会被删除；重名会自动加序号。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = nest.restore_to_desktop(self.cfg.desktop)
        self._show_desktop_icons()
        self.cfg.set("nest_active", False)
        self.refresh()
        message = result.summary()
        if result.failed:
            message += "\n\n未能还原：\n" + "\n".join(
                f"· {n}：{r}" for n, r in result.failed[:8])
            QMessageBox.warning(self, "还原桌面", message)
        else:
            QMessageBox.information(self, "还原桌面", message)

    def take_desktop_now(self) -> None:
        """手动把桌面上的东西收进收纳目录。"""
        pending = nest.desktop_item_count(self.cfg.desktop)
        if pending == 0:
            QMessageBox.information(self, "收纳桌面", "桌面上没有需要收纳的内容。")
            return
        result = nest.take_from_desktop(self.cfg.desktop)
        self._apply_icon_visibility()
        self.cfg.set("nest_active", result.moved > 0)
        self.refresh()
        message = result.summary()
        if result.failed:
            message += "\n\n未能收纳：\n" + "\n".join(
                f"· {n}：{r}" for n, r in result.failed[:8])
            QMessageBox.warning(self, "收纳桌面", message)
        else:
            QMessageBox.information(self, "收纳桌面", message)

    # ------------------------------------------------------------------
    # 开机自启 / 退出
    # ------------------------------------------------------------------
    def toggle_autostart(self, enabled: bool) -> None:
        if config.set_autostart(enabled):
            self.cfg.set("autostart", enabled)
        else:
            self.rebuild_tray_menu()
            QMessageBox.warning(
                self, "开机自启",
                "写入开机自启项失败。可以手动把本程序的快捷方式放进\n"
                "「开始菜单 → 启动」文件夹。")

    def quit_app(self) -> None:
        self._quitting = True
        self.shutdown()
        self.panel.hide()
        self.desktop_browser.hide()
        self.dock.hide_bar()
        self.tray.hide()
        QApplication.quit()

    def shutdown(self) -> None:
        """退出前：还原桌面 + 把后台线程收干净。"""
        worker = self._scan
        if worker is not None and worker.isRunning():
            worker.wait(4000)
        self._scan = None
        panel_worker = getattr(self.panel, "_worker", None)
        if panel_worker is not None and panel_worker.isRunning():
            panel_worker.wait(6000)
        # 退出即还原（需求：启动收纳、退出还原）
        try:
            self.restore_desktop_on_exit()
        except Exception as exc:
            config.log(f"退出还原失败：{type(exc).__name__}: {exc}")
            # 正常还原路径出问题，让应急还原再兜一次（它自带重入保护，
            # 成功过一次就不会重复跑）
            self.emergency_restore("退出还原失败")
        self.cfg.save()

    # ------------------------------------------------------------------
    def _startup_prompt(self) -> None:
        """启动后的一句提示：告诉用户东西收在哪、怎么找回来。"""
        if not self.nest_items:
            return
        if not self.panel.isVisible() and not self.desktop_browser.isVisible():
            self.tray.showMessage(
                f"{config.APP_NAME_FULL} 已把桌面收好了",
                f"收纳面板里有 {len(self.nest_items)} 项（含此电脑、回收站）。\n"
                "点底部菜单栏最左边的「桌面整理」，或双击托盘图标查看。\n"
                "退出程序时会自动把东西放回桌面。",
                QSystemTrayIcon.MessageIcon.Information, 6000)


# --------------------------------------------------------------------------
def run() -> int:
    from qt_compat import require_qt

    require_qt()

    silent = "--silent" in sys.argv
    # 注意：QApplication 必须在任何 setApplicationName / setStyleSheet 之前创建，
    # 否则 Qt 会直接抛错退出。
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.ORG_NAME)
    app.setApplicationDisplayName(config.APP_NAME_FULL)
    app.setQuitOnLastWindowClosed(False)         # 关掉窗口也要留在托盘

    cfg = config.Config()
    app.setStyleSheet(theme_mod.stylesheet(bool(cfg.get("dark"))))

    window = TrayApp(cfg, silent=silent)
    window._app = app
    # 挂上全局异常钩子：之后任何未捕获异常都会**先把桌面还原回去**再退出。
    # 必须在进入事件循环之前装好，否则启动阶段崩掉就没有兜底。
    window.install_crash_guards()

    try:
        return app.exec()
    except BaseException as exc:  # noqa: BLE001
        # Qt 事件循环里抛出来的异常也走这里兜底
        try:
            config.log(f"事件循环异常退出：{type(exc).__name__}: {exc}")
        except Exception:
            pass
        window.emergency_restore(f"事件循环异常 {type(exc).__name__}")
        raise
    finally:
        # 正常退出路径也保证还原一次（重入保护，不会重复搬）
        try:
            window.emergency_restore("事件循环结束")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(run())
