#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户报告的问题 —— 回归测试
==========================
1. 启动崩溃：`'DesktopBrowser' object has no attribute 'loader'`
   （loader 在 `_build_ui()` 之后才创建，而 `_build_ui()` 末尾就会用到它）
2. 添加常用软件后图标识别失败
3. 点击常用软件后高亮不消失
4. 菜单栏上那排分页条目已整行移除，只剩主行
5. 回到桌面时菜单栏该自动出现（除非用户主动隐藏过）
6. 全屏应用（看视频等）时菜单栏要让开，不遮挡
7. 收纳面板不是普通应用窗口，而是贴底的**磨砂玻璃上拉浮层**
8. 打开 / 反复翻页收纳面板时，底部菜单栏不会无故消失

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
    print("── 4. 菜单栏上的分页行已整行移除，只剩主行 ──")
    dock = tray.dock
    dock.show_bar()
    app.processEvents()
    check("菜单栏上没有分页行 UI",
          not hasattr(dock, "strip_panel") and not hasattr(dock, "strip_row")
          and not hasattr(dock, "strip_page_label")
          and not hasattr(dock, "btn_toggle_strip"),
          str([a for a in ("strip_panel", "strip_row", "strip_page_label",
                           "btn_toggle_strip") if hasattr(dock, a)]))
    check("分页相关方法也删掉了",
          not hasattr(dock, "toggle_strip") and not hasattr(dock, "rebuild_strip")
          and not hasattr(dock, "strip_pages"))
    check("主行控件齐全：桌面整理 / ＋ / ⚙ / ✕",
          hasattr(dock, "desktop_btn") and hasattr(dock, "add_btn")
          and hasattr(dock, "settings_btn") and hasattr(dock, "btn_hide_dock"))
    check("窗口尺寸贴近内容（不留空白）",
          abs(dock.height() - dock.sizeHint().height()) <= 24,
          f"height={dock.height()} sizeHint={dock.sizeHint().height()}")
    check("收纳内容仍保留为「＋ 添加」的候选",
          len(dock._items) == len(tray.nest_items),
          f"{len(dock._items)} vs {len(tray.nest_items)}")
    check("配置里也不再有分页行开关",
          "dock_strip_visible" not in config_mod.DEFAULTS)

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
        mon_w = info.rcMonitor.right - info.rcMonitor.left
        mon_h = info.rcMonitor.bottom - info.rcMonitor.top
        work_w = info.rcWork.right - info.rcWork.left
        work_h = info.rcWork.bottom - info.rcWork.top

        # 这里必须**按实现里的三条规则复算期望值**，不能凭一个面积阈值猜。
        # 原来写的是 `coverage < 0.4`，跟实现的 `>= 0.80 且高度 >= 90% 工作区`
        # 不一致：前台窗口占比落在 40%~80% 时，测试必然误报失败。
        coverage = (win_w * win_h) / float(work_w * work_h) if work_w and work_h else 0
        expected = False
        if win_w >= mon_w * 0.96 and win_h >= mon_h * 0.96:
            expected = True                       # 规则 1：真全屏，铺满整块显示器
        elif coverage >= 0.80 and win_h >= work_h * 0.90:
            expected = True                       # 规则 2：最大化（按面积占比）
        elif tray.dock.isVisible():               # 规则 3：盖住菜单栏所在那一带
            dock_rect = tray.dock.geometry()
            if (rect.left <= dock_rect.left() and rect.right >= dock_rect.right()
                    and rect.bottom >= dock_rect.top()):
                expected = True
        if tray._foreground_is_self():            # 自己的窗口不算（新增的排除项）
            expected = False
        if tray._desktop_is_foreground():         # 桌面本身在前台不算
            expected = False

        check(f"让开判据与实际窗口几何一致（占 {coverage:.0%}，"
              f"{win_w}x{win_h} / 工作区 {work_w}x{work_h}）",
              result == expected, f"判据={result} 期望={expected}")

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
    print("── 8. 收纳面板是「上拉菜单窗口」而不是应用窗口 ──")
    # 需求：面板要能随时开关、背景透明、贴底弹出——不是弹一个应用窗口
    check("无边框（上拉菜单不该有标题栏）",
          bool(panel_flags & _Qt.WindowType.FramelessWindowHint))
    # 注意：Qt 里 Tool(0x0b) 的低位本身就含 Window(0x01) 那一位，
    # 所以不能拿 `flags & Window` 判断"是不是普通窗口"——
    # 必须把窗口类型字段整体取出来比较。
    check("窗口类型是 Tool（不占任务栏，不是独立应用窗口）",
          (panel_flags & _Qt.WindowType.WindowType_Mask) == _Qt.WindowType.Tool,
          hex(int(panel_flags & _Qt.WindowType.WindowType_Mask)))
    check("无系统投影（配合半透明背景才干净）",
          bool(panel_flags & _Qt.WindowType.NoDropShadowWindowHint))
    check("背景半透明（能透出后面的桌面）",
          browser.testAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground))

    # 开合语义：同一个入口再点一次要能收起
    browser.hide()
    app.processEvents()
    browser.toggle_window()
    app.processEvents()
    opened = browser.isVisible()
    browser.toggle_window()
    app.processEvents()
    check("toggle_window：第一次打开、第二次收起",
          opened and not browser.isVisible(),
          f"open={opened} after={browser.isVisible()}")

    # 位置：贴底居中，且给底部菜单栏留出空间
    browser.show_window()
    app.processEvents()
    screen = browser.screen().availableGeometry()
    delta = abs(browser.geometry().center().x() - screen.center().x())
    check("水平居中弹出", delta <= 4, f"偏差 {delta}px")
    check("底边让开底部菜单栏（不压住 Dock）",
          browser.y() + browser.height() <= screen.bottom() - 60,
          f"底边 {browser.y() + browser.height()} vs 屏幕底 {screen.bottom()}")
    check("整块面板不跑出屏幕",
          browser.x() >= screen.left()
          and browser.x() + browser.width() <= screen.right() + 1
          and browser.y() >= screen.top(),
          f"x={browser.x()} y={browser.y()} w={browser.width()} h={browser.height()}")
    browser.hide()
    app.processEvents()

    print()
    print("── 8b. 收纳面板是「磨砂玻璃浮层」，不是白色矩形弹窗 ──")
    from qt_compat import QPalette
    from widgets import GlassCardMixin

    check("用了共享的玻璃外观（GlassCardMixin）",
          isinstance(browser, GlassCardMixin))
    sheet = browser.styleSheet()
    check("顶层窗口自己不画底（画了就把磨砂盖住了）",
          "#BrowserRoot" in sheet and "background: transparent" in sheet)
    check("卡片 #Popup 是深色半透明底（不是纯白）",
          "#Popup" in sheet and "rgba(24, 26, 32" in sheet,
          "样式表里找不到 #Popup 的深色底")
    check("卡片是大圆角（22px，和主面板一致）",
          "border-radius: 22px" in sheet)
    check("卡片有 1px 亮边（玻璃质感）",
          "border: 1px solid" in sheet and "rgba(255, 255, 255" in sheet)
    check("窗口调色板也换成了深色（兜住 QSS 没写到的控件）",
          browser.palette().color(QPalette.ColorRole.Window).lightness() < 128,
          str(browser.palette().color(QPalette.ColorRole.Window).name()))

    print()
    print("── 9. 打开 / 反复翻页收纳面板时，菜单栏不会消失 ──")
    panel = tray.desktop_browser
    tray.cfg.set("dock_hidden_by_user", False)
    tray.cfg.set("dock_visible", True)
    tray.cfg.set("dock_auto_show", True)
    dock.show_bar()
    app.processEvents()
    check("Dock 初始可见", dock.isVisible())
    check("面板关着时 _dock_in_use 为假", tray._dock_in_use() is False)

    panel.show_window()
    app.processEvents()
    check("面板打开时 _dock_in_use 为真", tray._dock_in_use() is True)

    # 关键：把自己的窗口当成"前台窗口"，绝不能被判成"别的程序在遮挡菜单栏"
    real_hwnd = tray._foreground_hwnd
    try:
        tray._foreground_hwnd = lambda: int(panel.winId())
        check("识别出前台窗口是自己", tray._foreground_is_self() is True)
        check("自己的面板不算「全屏遮挡」",
              tray._foreground_is_fullscreen() is False)
        tray._foreground_hwnd = lambda: int(dock.winId())
        check("Dock 自己也不算「全屏遮挡」",
              tray._foreground_is_fullscreen() is False)
    finally:
        tray._foreground_hwnd = real_hwnd

    # 浮层位置：底边正好落在菜单栏顶边之上（不压住 Dock）
    dock_top = dock.geometry().top()
    panel_bottom = panel.geometry().bottom()
    check("面板底边让开菜单栏（贴在 Dock 上方，不压住它）",
          panel_bottom <= dock_top,
          f"面板底 {panel_bottom} vs Dock 顶 {dock_top}")

    survived = True
    for _round in range(3):
        for page in range(panel._page_count()):
            panel.goto_page(page)
            tray._auto_show_tick()
            app.processEvents()
            if not dock.isVisible():
                survived = False
        panel.set_per_page(21)
        app.processEvents()
        panel.set_per_page(14)
        app.processEvents()
        if not dock.isVisible():
            survived = False
    check("反复翻页 / 换每页数量后 Dock 依然稳定可见",
          survived and dock.isVisible())
    check("翻页没有篡改菜单栏「显示/隐藏」状态变量",
          bool(tray.cfg.get("dock_visible", True)) is True
          and bool(tray.cfg.get("dock_hidden_by_user", False)) is False,
          f"visible={tray.cfg.get('dock_visible')} "
          f"by_user={tray.cfg.get('dock_hidden_by_user')}")
    panel.hide()
    app.processEvents()

    print()
    print("── 10. Dock 图标按钮要装得下自己的文字（高 DPI 下别叠字）──")
    # 原来 DockIcon 写死 max(icon_size+20, 68)：字号用 pt 会跟着 DPI 放大，
    # 写死的宽度不会，于是 125% 缩放下「任务管理器」装不下、相邻两项文字叠在一起。
    from qt_compat import QFontMetrics
    from dock import DockIcon

    for label in ("任务管理器", "命令提示符", "字符映射表", "记事本"):
        icon = DockIcon(32, show_text=True)
        icon.setText(label)
        need = QFontMetrics(icon.font()).horizontalAdvance(label) + 14
        expected = max(32 + 20, need)
        check(f"「{label}」宽度按文字自适应（{icon.width()}px）",
              icon.width() == expected, f"w={icon.width()} 期望={expected}")

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
