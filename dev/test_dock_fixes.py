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
9. 菜单栏底板是**纯透明**的，而且只有一行（图标与控制按钮同一水平线）
10. 菜单栏图标按钮要装得下自己的文字（高 DPI 下别叠字）
11. 应用区里不该有"空白占位格"（入口和常用项之间不再插分隔线）
12. 整条菜单栏可以用鼠标拖动（空白处 + 图标上快速拖都行）
13. 点开软件之后，图标上的高光要跟着消失（不能一直亮着）
14. 长按鼠标左键可以拖动排序常用软件（有插入指示线，结果写回配置）
15. 菜单栏图标要用 256×256 的高清原图（旧路径只有 32×32）
16. Config.move_to：把任意一项挪到任意位置
17. 收纳面板的图标也走 256×256 高清（网格 + 常用启动行）
18. 图标裁掉透明边距让内容占满（修「有的图标看着特别小」）+ 网格图标调小

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

    # 面板现在只展示**收纳目录里**的内容（需求6 去掉了系统位置），
    # 而这个用例把 auto_take_on_start 关着，所以要先手动收一次，
    # 否则面板是空的、"从列表里选一个加为常用"就没得选。
    taken = nest.take_from_desktop(cfg.desktop)
    print(f"  [准备] 把测试桌面收进收纳目录：{taken.summary()}")
    tray.refresh()
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)

    print()
    print("── 2. 加点一个常用软件，图标要能认出来 ──")
    check("面板里有条目可选", len(tray.nest_items) > 0, str(len(tray.nest_items)))
    before = len(cfg.quick_items)
    # 模拟"从列表里选一个加为常用"
    picked = next((i for i in tray.nest_items if i.kind == "shortcut"), None)
    check("面板里有可作为常用的条目", picked is not None,
          str([i.kind for i in tray.nest_items][:6]))
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
    print("── 3. 选中态：一直留着，直到把它打开 ──")
    target = tray.nest_items[0]
    tray.desktop_browser.select_item(target)
    app.processEvents()
    highlighted_now = sum(1 for t in tray.desktop_browser._tiles if t.selected)
    check("点击后立刻有高亮", highlighted_now == 1, str(highlighted_now))

    # ⚠️ 这里**故意**从"1.2 秒后自动清掉高亮"改成"选中态要留着"。
    # 右下角那三个按钮（打开 / 加为常用 / 还原到桌面）是照着**当前选中项**
    # 干活的。以前单击 1.2 秒后就把选中态一起清掉、按钮跟着变灰，
    # 用户还没来得及把鼠标从卡片挪到按钮上就点不动了——那也是一种
    # "加为常用点了没反应"。现在高亮只在**把条目打开**之后才消失
    # （见 `DesktopBrowser._open()`），选中态则由"选别的 / 翻页 / 重建"来换。
    deadline = time.time() + 2.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    still = sum(1 for t in tray.desktop_browser._tiles if t.selected)
    check("等 2 秒后高亮仍然在（不然按钮来不及点）", still == 1, f"{still} 个亮着")
    check("选中状态也还在", tray.desktop_browser._selected is not None)

    print()
    print("── 3b. 但「打开」之后高亮要自己消失 ──")
    import engine as engine_mod

    real_launch = engine_mod.launch
    engine_mod.launch = lambda *a, **k: (True, "")   # 别真的去开程序
    try:
        tray.desktop_browser._open(target)
    finally:
        engine_mod.launch = real_launch
    deadline = time.time() + 3.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
        if not any(t.selected for t in tray.desktop_browser._tiles):
            break
    still = sum(1 for t in tray.desktop_browser._tiles if t.selected)
    check("打开之后高亮自己消失了", still == 0, f"还有 {still} 个亮着")
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
    check("菜单栏只留「桌面整理」入口 + 常用软件",
          hasattr(dock, "desktop_btn") and dock._control_buttons == [])
    check("＋ / － / ⚙ / ✕ 四个控制按钮已全部删除",
          not any(hasattr(dock, name) for name in
                  ("add_btn", "del_btn", "settings_btn", "btn_hide_dock")),
          str([a for a in ("add_btn", "del_btn", "settings_btn",
                           "btn_hide_dock") if hasattr(dock, a)]))
    check("窗口尺寸贴近内容（不留空白）",
          abs(dock.height() - dock.sizeHint().height()) <= 24,
          f"height={dock.height()} sizeHint={dock.sizeHint().height()}")
    check("收纳内容仍保留为添加常用软件的候选",
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
        #
        # ⚠️ 曾经这里复算的是"窗口矩形盖住了菜单栏那一带 → 让开"，
        # 那是**更早版本**的判据；实现后来把它删掉了（普通窗口拖到屏幕底部、
        # 窗口打开动画的中间帧都会短暂满足它，结果菜单栏疯狂闪烁），
        # 换成了"宽度也得占够"。测试没跟着改，于是前台窗口占比落在
        # 40%~80% 且恰好压住菜单栏时，这条用例必然误报失败。
        coverage = (win_w * win_h) / float(work_w * work_h) if work_w and work_h else 0
        expected = False
        if win_w >= mon_w * 0.96 and win_h >= mon_h * 0.96:
            expected = True                       # 规则 1：真全屏，铺满整块显示器
        elif coverage >= 0.80 and win_h >= work_h * 0.90:
            expected = True                       # 规则 2：最大化（按面积占比）
        elif win_w >= mon_w * 0.98 and win_h >= work_h * 0.94:
            expected = True                       # 规则 3：接近满宽的窗口
        if tray._foreground_is_self():            # 自己的窗口不算
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

    # ==================================================================
    # 第二轮：菜单栏拖动 / ＋ 左边空隙 / 高光残留 / 长按排序 / 图标清晰度
    # ==================================================================
    from qt_compat import QEvent, QMouseEvent, QPoint, QPointF, Qt as _Q

    def send_mouse(widget, kind, local: "QPoint", glob: "QPoint",
                   buttons=_Q.MouseButton.LeftButton) -> "QMouseEvent":
        """往控件发一个鼠标事件（用来模拟真实点击 / 拖动）。"""
        event = QMouseEvent(kind, QPointF(local), QPointF(glob),
                            _Q.MouseButton.LeftButton, buttons,
                            _Q.KeyboardModifier.NoModifier)
        app.sendEvent(widget, event)
        app.processEvents()
        return event

    def press(widget):
        local = widget.rect().center()
        return local, widget.mapToGlobal(local)

    def wait_until(predicate, seconds: float = 2.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
            if predicate():
                return True
        return bool(predicate())

    def rebuild_dock() -> None:
        """重建菜单栏并等它"落定"。

        `rebuild()` 之后菜单栏会起一个 60ms 的短定时器（`DockBar._settle`），
        在**布局真正稳定之后**再校正一次尺寸——刚建出来的控制按钮还没被
        布局量过，这一刻的 `sizeHint()` 是偏小的。不等这一步就量几何，
        会量到一个还没定型的中间态。
        """
        dock.rebuild()
        wait_until(lambda: not dock._settle_timer.isActive(), 1.5)
        app.processEvents()

    dock.show_bar()
    app.processEvents()
    # 菜单栏有个 60ms 的"布局稳定后校正位置"定时器（见 DockBar._settle）。
    # 不等它跑完就自己 move()，会被它按 dock_x 拉回去，测试就假失败了。
    wait_until(lambda: not dock._settle_timer.isActive(), 1.0)

    def park_dock_at_left_edge() -> int:
        """把菜单栏摆到屏幕最左边，返回它的 x。

        摆到最左是为了让"+80px"这个位移一定不会被屏幕边界夹掉——
        测试要断言精确位移，就不能让夹取逻辑插手。
        """
        wait_until(lambda: not dock._settle_timer.isActive(), 1.0)
        dock.move(dock.screen().availableGeometry().left() + 4, dock.y())
        app.processEvents()
        return dock.x()

    print()
    print("── 11. 还没加常用软件时，菜单栏上不该多出任何东西 ──")
    # 先清空常用项，回到"刚装好、一个都没加"的状态
    while cfg.quick_items:
        cfg.remove_quick(cfg.quick_items[0]["path"])
    rebuild_dock()
    check("应用区只剩「桌面整理」一项（没有多余的分隔线）",
          dock.apps_flow.item_count() == 1, str(dock.apps_flow.item_count()))
    # 需求："主菜单栏就保留第一个控件和常用软件"。
    # 主行里应当只有两样东西：应用区本身 + 一个弹性占位项（把图标顶到左边）。
    # 以前 ＋ / － / ⚙ / ✕ 四个按钮也在这行里，所以这里逐个点名字断言它们不在。
    row_kinds = []
    for index in range(dock.main_row.count()):
        entry = dock.main_row.itemAt(index)
        if entry is None:
            continue
        if entry.widget() is dock.apps_flow:
            row_kinds.append("apps")
        elif entry.spacerItem() is not None:
            row_kinds.append("stretch")
        else:
            row_kinds.append(type(entry.widget()).__name__)
    check(f"主行里只有应用区 + 一个弹性占位项（{row_kinds}）",
          row_kinds == ["apps", "stretch"], str(row_kinds))
    desktop_pos = dock.desktop_btn.mapTo(dock, QPoint(0, 0))
    right_edge = desktop_pos.x() + dock.desktop_btn.width()
    # 空栏时，入口右边到窗口可用区右边界之间不该夹着别的控件
    check("空栏时入口右边没有别的控件",
          dock.apps_flow.item_count() == 1 and dock._control_buttons == [],
          f"items={dock.apps_flow.item_count()} "
          f"controls={len(dock._control_buttons)} 入口右边界={right_edge}")

    # 加了常用项之后**依然没有分隔线**：应用区里只有「桌面整理」+ 常用项。
    # 根因是应用区按**等宽网格**排（`unit_size()` 取所有条目里最大的那个），
    # 那根 1px 的竖线也会占满一整格（≈ 一个图标的宽度），看上去就是一块
    # "空白占位格子"——用户圈出来要删的正是它。
    quick_sources = [i for i in tray.nest_items if i.kind == "shortcut"][:4]
    check("有足够的快捷方式来做常用项（≥3 个）", len(quick_sources) >= 3,
          str(len(quick_sources)))
    for source_item in quick_sources:
        cfg.add_quick(source_item.path, source_item.name)
    rebuild_dock()
    wait_until(lambda: len(dock._app_buttons) == len(quick_sources), 5)
    check("加了常用项之后也没有多出占位格（入口 + 常用项，一个不多）",
          dock.apps_flow.item_count() == len(quick_sources) + 1,
          f"{dock.apps_flow.item_count()} vs {len(quick_sources) + 1}")
    # 关键：入口和第一个常用项之间只隔"一点点"，绝不能是一整格的宽度
    # （一整格 ≈ 一个图标宽，那正是"空白占位格子"的样子）。
    first_app = dock._app_buttons[0]
    entry_right = (dock.desktop_btn.mapTo(dock, QPoint(0, 0)).x()
                   + dock.desktop_btn.width())
    first_left = first_app.mapTo(dock, QPoint(0, 0)).x()
    entry_gap = first_left - entry_right
    unit_w = dock.apps_flow.unit_size().width()
    check(f"入口与第一个常用项之间只有一点间距（{entry_gap}px，远小于一格 {unit_w}px）",
          0 <= entry_gap < unit_w * 0.5,
          f"{entry_gap}px vs unit {unit_w}px")
    check("主行里的弹性占位项没有越积越多（重建会清掉旧的）",
          sum(1 for i in range(dock.main_row.count())
              if dock.main_row.itemAt(i).spacerItem() is not None) == 1,
          str(dock.main_row.count()))

    print()
    print("── 12. 整条菜单栏可以用鼠标拖动 ──")
    # 底板 / 应用区必须"不吃"鼠标按下，否则按下不会冒泡到菜单栏，
    # 整条栏就没有能下手拖动的地方（原来就是这个原因拖不动）。
    #
    # 注意 `QApplication.sendEvent()` 是直接投递给指定控件的，但 Qt 在
    # 收到**被忽略**的鼠标按下时，会沿父链往上冒泡，直到有控件 accept 为止
    # （`QWidget::mousePressEvent` 的默认实现就是 `event->ignore()`）。
    # 所以"把按下发给 surface，看菜单栏有没有进入拖动模式"能真实反映
    # 用户按在空白处时的行为。
    for name, widget in (("底板 #DockSurface", dock.surface),
                         ("应用区 FlowRow", dock.apps_flow)):
        dock._mode = ""
        dock._press_icon = None
        local = QPoint(3, 3)
        glob = widget.mapToGlobal(local)
        event = send_mouse(widget, QEvent.Type.MouseButtonPress, local, glob)
        check(f"按在{name}上会冒泡给菜单栏（能开始拖动）",
              dock._mode == "window" and event.isAccepted(),
              f"mode={dock._mode!r} accepted={event.isAccepted()}")
        send_mouse(widget, QEvent.Type.MouseButtonRelease, local, glob)
        check(f"松手后{name}上的拖动状态复位", dock._mode == "", repr(dock._mode))

    # 1) 从空白处拖
    x_before = park_dock_at_left_edge()
    local = QPoint(4, dock.height() // 2)
    glob = dock.mapToGlobal(local)
    send_mouse(dock, QEvent.Type.MouseButtonPress, local, glob)
    check("按下空白处立刻进入「拖整条菜单栏」模式", dock._mode == "window",
          repr(dock._mode))
    send_mouse(dock, QEvent.Type.MouseMove, local, glob + QPoint(80, 0))
    moved_from_blank = dock.x()
    send_mouse(dock, QEvent.Type.MouseButtonRelease, local, glob + QPoint(80, 0))
    check(f"空白处拖动有效（{x_before} → {moved_from_blank}）",
          moved_from_blank == x_before + 80, f"位移 {moved_from_blank - x_before}px")
    check("拖动后位置写进了配置", int(cfg.get("dock_x") or 0) == moved_from_blank,
          f"dock_x={cfg.get('dock_x')} x={dock.x()}")

    # 2) 从图标上快速拖（纯透明菜单栏上图标铺满了整条，必须也能拖）
    x_before = park_dock_at_left_edge()
    button = dock._app_buttons[0]
    local, glob = press(button)
    send_mouse(button, QEvent.Type.MouseButtonPress, local, glob)
    for step in range(1, 5):
        send_mouse(button, QEvent.Type.MouseMove, local, glob + QPoint(step * 20, 0))
    send_mouse(button, QEvent.Type.MouseButtonRelease, local, glob + QPoint(80, 0))
    check(f"按住图标快速拖也能拖动整条（{x_before} → {dock.x()}）",
          dock.x() == x_before + 80, f"位移 {dock.x() - x_before}px")
    check("拖完之后模式复位", dock._mode == "", repr(dock._mode))
    check("拖动时不会纵向乱跑（仍然贴底）",
          dock.y() + dock.height() <= dock.screen().availableGeometry().bottom(),
          f"底边 {dock.y() + dock.height()}")

    print()
    print("── 13. 点开软件之后高光要跟着消失 ──")
    import engine as engine_mod

    real_launch = engine_mod.launch
    launched: "list[str]" = []
    engine_mod.launch = lambda p: (launched.append(str(p)), (True, ""))[1]
    try:
        button = dock._app_buttons[0]
        # 模拟"鼠标还停在图标上"的状态
        button.setAttribute(_Q.WidgetAttribute.WA_UnderMouse, True)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()
        app.processEvents()
        hovered = button.grab().toImage()

        local, glob = press(button)
        send_mouse(button, QEvent.Type.MouseButtonPress, local, glob)
        send_mouse(button, QEvent.Type.MouseButtonRelease, local, glob)
        app.processEvents()
        check("点一下确实启动了", len(launched) == 1, str(launched))
        check("启动之后 WA_UnderMouse 被清掉",
              not button.testAttribute(_Q.WidgetAttribute.WA_UnderMouse))
        plain = button.grab().toImage()
        check("画面真的变了（不只是改了个标记位）", hovered != plain)

        # 按下后拖走再松 → 不该启动
        launched.clear()
        button = dock._app_buttons[1]
        local, glob = press(button)
        send_mouse(button, QEvent.Type.MouseButtonPress, local, glob)
        for step in range(1, 4):
            send_mouse(button, QEvent.Type.MouseMove, local, glob + QPoint(step * 15, 0))
        send_mouse(button, QEvent.Type.MouseButtonRelease, local, glob + QPoint(45, 0))
        app.processEvents()
        check("拖动过之后松手不算点击（不会误启动）", not launched, str(launched))

        print()
        print("── 14. 长按左键拖动排序常用软件 ──")
        names_before = [Path(str(b._payload)).name for b in dock._app_buttons]
        source = dock._app_buttons[0]
        local, glob = press(source)
        send_mouse(source, QEvent.Type.MouseButtonPress, local, glob)
        entered = wait_until(lambda: dock._mode == "reorder", 2)
        check("长按之后进入排序模式", entered and dock._mode == "reorder",
              repr(dock._mode))
        check("按住的图标呈「抓起」状态（isDown）", source.isDown())

        target = dock._app_buttons[2]
        target_glob = target.mapToGlobal(target.rect().center())
        send_mouse(source, QEvent.Type.MouseMove, local, target_glob)
        check("按光标位置算出了目标槽位", dock._reorder_to == 2,
              str(dock._reorder_to))
        line = dock._drop_line
        check("插入指示线显示出来了", line is not None and line.isVisible())
        if line is not None and line.isVisible():
            check("指示线画在目标槽的右边缘（往右移）",
                  line.geometry().x() > target.mapTo(dock.surface, QPoint(0, 0)).x(),
                  f"线 x={line.geometry().x()}")

        send_mouse(source, QEvent.Type.MouseButtonRelease, local, target_glob)
        wait_until(lambda: len(dock._app_buttons) == len(names_before), 5)
        names_after = [Path(str(b._payload)).name for b in dock._app_buttons]
        expected = [names_before[1], names_before[2], names_before[0]] + names_before[3:]
        check("顺序按拖动结果重排了", names_after == expected,
              f"{names_after} vs {expected}")
        check("配置里的顺序也同步了",
              [Path(e["path"]).name for e in cfg.quick_items] == expected,
              str([Path(e["path"]).name for e in cfg.quick_items]))
        check("UI 顺序与配置顺序一致（没有不同步）",
              names_after == [Path(e["path"]).name for e in cfg.quick_items])
        check("松手后指示线收起来了",
              dock._drop_line is None or not dock._drop_line.isVisible())
        check("排序过程中没有顺手把软件启动了", not launched, str(launched))
    finally:
        engine_mod.launch = real_launch

    print()
    print("── 15. 图标清晰度：菜单栏要拿 256×256 的原图 ──")
    import icons as icons_mod

    for button in dock._app_buttons:
        sizes = [s.width() for s in button.icon().availableSizes()]
        # 阈值给 192 而不是 256：jumbo 档现在会**裁掉透明边距**，
        # 成品尺寸本来就可能不到 256（系统文件夹实测是 256×224）。
        # 旧路径只有 32，192 已经足够区分"确实走了高清档"。
        check(f"{Path(str(button._payload)).name} 用的是高清原图（{max(sizes)}px）",
              max(sizes) >= 192, str(sizes))
    glyph_sizes = [s.width() for s in dock.desktop_btn.icon().availableSizes()]
    check(f"「桌面整理」矢量图标有多档尺寸（{len(glyph_sizes)} 档）",
          len(glyph_sizes) >= 5 and max(glyph_sizes) >= 192, str(glyph_sizes))

    link = Path(cfg.quick_items[0]["path"])
    best = icons_mod.get_icon_best(link, 44)
    check("get_icon_best() 对 .lnk 能取到高清原图（最长边 ≥192）",
          best is not None and max(best.width, best.height) >= 192,
          f"{best.width}x{best.height}" if best else "None")
    # 高清档必须**裁掉多余透明边距**（内容太小的"看着特别小"，要裁掉四周空白），
    # 同时**必须留出抗锯齿余量**——贴着内容裁会把边缘那圈淡投影切掉，
    # 而且缩到 40px 时重采样没有外侧像素可采，圆形/圆角边缘就像被削掉一圈
    # （用户报的"图标显示不完整、会少一部分"）。所以这里不再要求"覆盖 90%"，
    # 改成两个方向都卡：内容够大（不是一张大画布贴个小图）、四周有余量。
    if best is not None:
        box = icons_mod.content_box(best)
        if box is None:
            covered = 1.0
            gap = -1
        else:
            covered = min((box[2] - box[0]) / best.width,
                          (box[3] - box[1]) / best.height)
            gap = min(box[0], box[1],
                      best.width - box[2], best.height - box[3])
        check(f"高清档内容够大（覆盖 {covered:.0%}，不是大画布贴小图）",
              covered >= 0.70, f"box={box} size={best.width}x{best.height}")
        check(f"高清档四周留了抗锯齿余量（最小 {gap}px）",
              gap >= 1, f"box={box} size={best.width}x{best.height}")
    # 老路径只有 32×32 —— 这正是"图标清晰度太低"的根因，钉住它别再退回去
    plain_icon = icons_mod.get_icon(link, 44)
    check("旧路径（SHGetFileInfoW）确实只有 32×32（所以必须走 jumbo）",
          plain_icon is not None and plain_icon.width <= 48,
          f"{plain_icon.width}x{plain_icon.height}" if plain_icon else "None")

    from widgets import IconLoader

    loader = IconLoader(per_tick=0)          # 不真去取，只看排队记录
    loader.request("probe", link, None, 44, "x", hi_res=True)
    # 队列项：(key, path, hint, size, fallback, hi_res, stamp)
    check("菜单栏的取图请求带上了高清标记",
          bool(loader._queue) and loader._queue[0][5] is True,
          str(loader._queue[0][5] if loader._queue else None))
    check("队列项末尾带的是「文件指纹」（缓存靠它判断要不要重取）",
          bool(loader._queue) and isinstance(loader._queue[0][6], str)
          and loader._queue[0][6] == loader._stamp(link, 44),
          str(loader._queue[0][6] if loader._queue else None))
    loader._timer.stop()
    loader.deleteLater()

    print()
    print("── 16. Config.move_to：把任意一项挪到任意位置 ──")
    letters = "ABCD"
    cfg.set("quick_items", [{"path": c, "name": c} for c in letters])
    cfg.move_to(0, 2)
    check("[A,B,C,D] move_to(0,2) → [B,C,A,D]",
          [e["name"] for e in cfg.quick_items] == ["B", "C", "A", "D"],
          str([e["name"] for e in cfg.quick_items]))
    cfg.set("quick_items", [{"path": c, "name": c} for c in letters])
    cfg.move_to(3, 1)
    check("[A,B,C,D] move_to(3,1) → [A,D,B,C]",
          [e["name"] for e in cfg.quick_items] == ["A", "D", "B", "C"],
          str([e["name"] for e in cfg.quick_items]))
    check("原地不动返回 False（不白写一次盘）", cfg.move_to(1, 1) is False)
    check("越界下标被夹住，不抛异常",
          cfg.move_to(0, 99) is True
          and [e["name"] for e in cfg.quick_items] == ["D", "B", "C", "A"],
          str([e["name"] for e in cfg.quick_items]))
    check("非法来源下标返回 False", cfg.move_to(9, 0) is False)

    print()
    print("── 17. 收纳面板的图标也走 256×256 高清 ──")
    browser = tray.desktop_browser
    # 第 16 节把常用项换成了 A/B/C/D 这种假路径，先装回真实的
    cfg.set("quick_items", [{"path": str(i.path), "name": i.name}
                            for i in quick_sources])
    # 清掉 loader 的缓存与队列，逼它把取图请求**重新排一遍**，
    # 这样才看得到"请求里到底带没带高清标记"（命中缓存时会直接跳过）。
    browser.loader._timer.stop()
    browser.loader._queue.clear()
    browser.loader._cache.clear()
    browser.set_items(tray.nest_items)
    queued = list(browser.loader._queue)
    check("收纳面板重新取图时确实排了活", len(queued) > 0, str(len(queued)))
    check("收纳面板的取图请求**全部**带高清标记（网格 + 常用启动行）",
          bool(queued) and all(item[5] is True for item in queued),
          f"hi_res 标记集合：{sorted({item[5] for item in queued})}")
    # 网格图标要显示 48px、常用启动行 34px，都超过旧路径的 32×32 上限，
    # 所以两处都必须走 get_icon_best()，钉住别再退回 32px 档。
    check("收纳面板请求的尺寸确实超过旧路径上限（>32）",
          all(item[3] > 32 for item in queued),
          str(sorted({item[3] for item in queued})))
    browser.loader._timer.stop()
    browser.loader._queue.clear()

    print()
    print("── 18. 图标裁剪：让内容占满画布（修「有的图标看着特别小」） ──")
    import desktop_browser as db_mod

    check(f"收纳面板网格图标调小了（GRID_ICON={db_mod.GRID_ICON}，原来 48）",
          db_mod.GRID_ICON <= 44, str(db_mod.GRID_ICON))

    def _solid(edge: int, inset: int) -> "icons_mod.RawIcon":
        """造一张 edge×edge 的图，只有中间（去掉 inset 边距）是不透明的。"""
        rows = []
        for y in range(edge):
            row = bytearray()
            for x in range(edge):
                inside = (inset <= x < edge - inset and inset <= y < edge - inset)
                row += bytes((0, 0, 0, 255 if inside else 0))
            rows.append(bytes(row))
        return icons_mod.RawIcon(edge, edge, b"".join(rows), "probe")

    # 64×64 画布、内容只在中间 16×16 —— 就是"大画布 + 小内容"那类图标
    small = _solid(64, 24)
    box = icons_mod.content_box(small)
    check("content_box 能框出「大画布 + 中间小内容」",
          box == (24, 24, 40, 40), str(box))

    cropped = icons_mod.crop_raw(small, box)
    check("crop_raw 裁完只剩内容（64×64 → 16×16）",
          (cropped.width, cropped.height) == (16, 16),
          f"{cropped.width}x{cropped.height}")
    check("裁完之后再量一次：内容已经占满（不会再被裁）",
          icons_mod.content_box(cropped) == (0, 0, 16, 16),
          str(icons_mod.content_box(cropped)))

    full_raw = _solid(64, 0)
    full_box = icons_mod.content_box(full_raw)
    check("本来就占满的图，外接框就是整张图",
          full_box == (0, 0, 64, 64), str(full_box))
    check("crop_raw 对「已经占满」的图原样返回（不白拷一遍）",
          icons_mod.crop_raw(full_raw, full_box) is full_raw)
    check("全透明的图返回 None（不裁，交给上层兜底）",
          icons_mod.content_box(_solid(64, 32)) is None)

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
