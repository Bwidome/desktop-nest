#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户报告的 6 个问题 —— 回归测试
==============================
1. 启动崩溃：`'DesktopBrowser' object has no attribute 'loader'`
   （loader 在 `_build_ui()` 之后才创建，而 `_build_ui()` 末尾就会用到它）
2. 添加常用软件后图标识别失败
3. 点击常用软件后高亮不消失
4. 收起分页行时菜单栏大小不跟着变
5. 回到桌面时菜单栏该自动出现（除非用户主动隐藏过）
6. 全屏应用（看视频等）时菜单栏要让开，不遮挡

用法：python dev/test_dock_fixes.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}" + (f"  [{detail}]" if detail and not condition else ""))


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-fixes"
    shutil.rmtree(base, ignore_errors=True)
    desktop = base / "Desktop"
    public = base / "Public"
    cfg_dir = base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    # 造点真实快捷方式（用户桌面）
    for index, target in enumerate([
        r"C:\Windows\System32\notepad.exe",
        r"C:\Windows\System32\calc.exe",
        r"C:\Windows\explorer.exe",
        r"C:\Windows\System32\write.exe",
    ]):
        winlink.create_shortcut(desktop / f"程序{index}.lnk", target)
    # 一个还没被收纳的，用来测"添加常用软件"
    pending_link = desktop / "新软件.lnk"
    winlink.create_shortcut(pending_link, r"C:\Windows\System32\Taskmgr.exe")
    for index in range(6):
        (desktop / f"文件{index}.txt").write_text("x" * 50, encoding="utf-8")

    from qt_compat import QApplication, QMessageBox

    app = QApplication([])
    import config as config_mod

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False, "page_size": 28})

    import nest

    nest.nest_root = lambda: base / ".nest"
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop

    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

    print("── 1. 启动不再崩溃（原来 AttributeError: loader）──")
    import traceback

    from desktop_browser import DesktopBrowser

    crashed = ""
    browser = None
    try:
        browser = DesktopBrowser(cfg)
    except Exception:
        crashed = traceback.format_exc()
    check("DesktopBrowser 能正常构造", browser is not None, crashed[-300:])
    check("构造后就有 loader",
          browser is not None and hasattr(browser, "loader"))
    check("构造后高亮定时器也在",
          browser is not None and hasattr(browser, "_highlight_timer"))

    # 整个程序（托盘 + Dock + 面板）一起构造——之前就是这一步崩
    import tray_app

    tray = None
    crashed2 = ""
    try:
        tray = tray_app.TrayApp(cfg, silent=True)
    except Exception:
        crashed2 = traceback.format_exc()
    check("整个程序能启动", tray is not None, crashed2[-400:])

    if tray is None:
        print()
        print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        for item in FAIL:
            print("  ·", item)
        return 1

    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)

    print()
    print("── 2. 加点一个常用软件，图标要能认出来 ──")
    before = len(cfg.quick_items)
    # 模拟"从列表里选一个加为常用"
    picked = next((i for i in tray.nest_items if i.kind == "shortcut"), None)
    check("面板里有可作为常用的条目", picked is not None)
    if picked is not None:
        tray.desktop_browser.select_item(picked)
        app.processEvents()
        tray.desktop_browser.add_selected_to_apps()
        app.processEvents()
        check("常用启动数量 +1", len(cfg.quick_items) == before + 1,
              f"{before} -> {len(cfg.quick_items)}")

        # 等图标进缓存
        key = f"app:{picked.path}"
        deadline = time.time() + 25
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
            if tray.desktop_browser.loader.cached(key) is not None:
                break
        icon = tray.desktop_browser.loader.cached(key)
        check("新加的常用软件取到了图标", icon is not None and not icon.isNull())
        buttons = [b for b in tray.desktop_browser._app_buttons
                   if str(b.path) == str(picked.path)]
        check("按钮上也真的贴了图标",
              buttons and buttons[0].icon() is not None
              and not buttons[0].icon().isNull())

    print()
    print("── 3. 点击后高亮要会自己消失 ──")
    target = tray.nest_items[0]
    tray.desktop_browser.select_item(target)
    app.processEvents()
    highlighted_now = sum(1 for t in tray.desktop_browser._tiles if t.selected)
    check("点击后立刻有高亮", highlighted_now == 1, str(highlighted_now))

    # 等定时器（1.2 秒）触发
    deadline = time.time() + 5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
        if not any(t.selected for t in tray.desktop_browser._tiles):
            break
    still = sum(1 for t in tray.desktop_browser._tiles if t.selected)
    check("高亮会自动消失（不再一直亮着）", still == 0, f"还有 {still} 个亮着")
    check("选中状态也清掉了", tray.desktop_browser._selected is None)

    print()
    print("── 4. 收起分页行时菜单栏高度要变小 ──")
    dock = tray.dock
    dock.show_bar()
    app.processEvents()
    height_open = dock.height()
    dock.toggle_strip()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    height_closed = dock.height()
    check("收起后高度确实变小了", height_closed < height_open,
          f"{height_open} -> {height_closed}")
    check("收起后分页行不可见", not dock.strip_panel.isVisible())
    check("收起后窗口尺寸贴近内容（不留空白）",
          abs(height_closed - dock.sizeHint().height()) <= 24,
          f"height={height_closed} sizeHint={dock.sizeHint().height()}")

    dock.toggle_strip()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    check("再展开高度变回去", dock.height() > height_closed,
          f"{height_closed} -> {dock.height()}")

    print()
    print("── 5. 回到桌面自动显示 / 用户隐藏后不自动弹 ──")
    check("默认开启「回到桌面自动显示」",
          bool(cfg.get("dock_auto_show", True)))
    check("启动时不在「用户主动隐藏」状态",
          not bool(cfg.get("dock_hidden_by_user", False)))

    # 模拟用户点隐藏
    dock.hide_self()
    app.processEvents()
    check("点隐藏后记录为用户主动隐藏", bool(cfg.get("dock_hidden_by_user")))
    check("点隐藏后菜单栏不可见", not dock.isVisible())

    # 跑一次自动显隐：因为是用户主动隐藏的，不该弹出来
    tray._auto_show_tick()
    app.processEvents()
    check("用户主动隐藏后，自动逻辑不弹回来", not dock.isVisible())

    # 从托盘菜单勾选显示 → 清掉标记
    tray.toggle_dock()
    app.processEvents()
    check("托盘菜单勾选后重新显示", dock.isVisible())
    check("并且清掉了「用户主动隐藏」标记",
          not bool(cfg.get("dock_hidden_by_user")))

    print()
    print("── 6. 全屏 / 最大化应用时让开 ──")
    check("有「全屏时让开」的配置", "dock_avoid_fullscreen" in cfg.data)
    result = tray._foreground_is_fullscreen()
    check("全屏/最大化判断能安全返回布尔值", isinstance(result, bool))

    # 判据要跟"当前前台窗口的实际尺寸"一致，不能无脑断言 False：
    # 跑测试时前台可能真的是最大化窗口，那种情况下判 True 才是对的。
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        info = tray_app.MONITORINFO()
        info.cbSize = ctypes.sizeof(tray_app.MONITORINFO)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
        work_w = info.rcWork.right - info.rcWork.left
        work_h = info.rcWork.bottom - info.rcWork.top
        coverage = (win_w * win_h) / float(work_w * work_h) if work_w and work_h else 0
        if coverage < 0.4:
            check(f"前台窗口只占 {coverage:.0%}，不该判为让开", not result,
                  f"窗口 {win_w}x{win_h} 工作区 {work_w}x{work_h}")
        else:
            check(f"前台窗口占 {coverage:.0%}，判为让开是合理的", result,
                  f"窗口 {win_w}x{win_h} 工作区 {work_w}x{work_h}")

    print()
    print("── 7. 面板不置顶，不遮挡其他程序 ──")
    from qt_compat import Qt as _Qt

    panel_flags = browser.windowFlags()
    check("面板没有 WindowStaysOnTopHint（不会永远压在别的窗口上）",
          not bool(panel_flags & _Qt.WindowType.WindowStaysOnTopHint))
    dock_flags = tray.dock.windowFlags()
    check("Dock 仍然保持置顶（它是常驻工具条）",
          bool(dock_flags & _Qt.WindowType.WindowStaysOnTopHint))

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)

    tray._quitting = True
    tray.shutdown()
    app.processEvents()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
