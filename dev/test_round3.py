#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二轮用户反馈 —— 回归测试
========================
1. 添加常用软件时图标消失
2. 添加后菜单栏跑到屏幕外面 / 显示大小不对
3. 主面板左上角图标没显示
4. 图标发虚（高分屏未按 DPI 取图）
5. 打开浏览器（最大化窗口）不自动隐藏菜单栏
6. 回到桌面不自动显示菜单栏

用法：python dev/test_round3.py
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
    base = Path(tempfile.gettempdir()) / "nest-round3"
    shutil.rmtree(base, ignore_errors=True)
    desktop, public, cfg_dir = base / "Desktop", base / "Public", base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    # 一批真实快捷方式，用来测"加常用 + 图标"
    exes = [
        r"C:\Windows\System32\notepad.exe",
        r"C:\Windows\System32\calc.exe",
        r"C:\Windows\explorer.exe",
        r"C:\Windows\System32\write.exe",
        r"C:\Windows\System32\mspaint.exe",
        r"C:\Windows\System32\Taskmgr.exe",
        r"C:\Windows\regedit.exe",
        r"C:\Windows\System32\cmd.exe",
    ]
    for index, exe in enumerate(exes):
        winlink.create_shortcut(desktop / f"软件{index}.lnk", exe)

    from qt_compat import QApplication, QMessageBox, Qt, QWidget

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

    import tray_app

    tray = tray_app.TrayApp(cfg, silent=True)
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)

    browser = tray.desktop_browser
    dock = tray.dock

    print("── 1. 添加常用软件：图标要能认出来 ──")
    added = 0
    for item in [i for i in tray.nest_items if i.kind == "shortcut"][:4]:
        before = len(cfg.quick_items)
        browser.select_item(item)
        app.processEvents()
        browser.add_selected_to_apps()
        app.processEvents()
        if len(cfg.quick_items) > before:
            added += 1
    check("成功加了几个常用软件", added >= 3, str(added))

    # 等图标全部进缓存
    keys = [f"app:{e['path']}" for e in cfg.quick_items]
    deadline = time.time() + 30
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if all(browser.loader.cached(k) is not None for k in keys):
            break
    app.processEvents()

    missing = [k for k in keys if browser.loader.cached(k) is None]
    check("所有常用软件都取到了图标", not missing, f"缺 {len(missing)} 个")

    # 关键：按钮上要真的贴上（不能只是缓存里有）
    empty_buttons = [b for b in browser._app_buttons
                     if b.icon() is None or b.icon().isNull()]
    check("常用按钮都贴上了图标（不再空白/字母块）", not empty_buttons,
          f"{len(empty_buttons)} 个空")

    print()
    print("── 2. 菜单栏不跑出屏幕 / 尺寸正确 ──")
    dock.show_bar()
    app.processEvents()

    def inside_map(widget) -> bool:
        """窗口是否完整落在当前屏幕可用区内。

        注意每次都要重新取 screen()：窗口重建之后 screen 对象可能已经不同，
        用早先缓存的几何会误判。
        """
        screen = widget.screen().availableGeometry()
        return (widget.x() >= screen.left()
                and widget.x() + widget.width() <= screen.right() + 1
                and widget.y() >= screen.top()
                and widget.y() + widget.height() <= screen.bottom() + 1)

    check("加完常用项后菜单栏仍在屏幕内", inside_map(dock),
          f"x={dock.x()} w={dock.width()} 屏幕右={dock.screen().availableGeometry().right()}")

    # 加到很多个，验证换行而不是被挤出屏幕
    for extra in range(14):
        cfg.add_quick(desktop / f"额外{extra}.txt", f"额外{extra}")
    dock.rebuild()
    app.processEvents()
    time.sleep(0.15)
    app.processEvents()
    check("加到 18+ 个常用项后依然在屏幕内", inside_map(dock),
          f"x={dock.x()} y={dock.y()} w={dock.width()} h={dock.height()} "
          f"屏幕={dock.screen().availableGeometry()}")
    squashed = [b for b in dock._buttons if b.width() < b.icon_size]
    check("图标没有被挤扁", not squashed, f"{len(squashed)} 个被压")

    print()
    print("── 3. 主面板 / 菜单栏的窗口图标 ──")
    for name, widget in (("主面板", browser), ("菜单栏", dock), ("托盘面板", tray.panel)):
        icon = widget.windowIcon()
        check(f"{name}设置了窗口图标", icon is not None and not icon.isNull())
        sizes = icon.availableSizes() if icon is not None else []
        check(f"{name}的图标有多个尺寸（小图标才清晰）", len(sizes) >= 4,
              str([s.width() for s in sizes]))

    print()
    print("── 4. 字体用点值（跟随系统 DPI）──")
    import theme as theme_mod

    sheet = theme_mod.stylesheet(False)
    check("样式里不再有 px 字号（改成 pt 才能跟着 DPI 缩放）",
          "font-size:" in sheet and "px;" not in sheet.split("font-size:")[1][:20],
          "")
    import re

    px_sizes = re.findall(r"font-size:\s*[\d.]+px", sheet)
    check("没有残留的 px 字号", not px_sizes, str(px_sizes[:4]))
    pt_sizes = re.findall(r"font-size:\s*([\d.]+)pt", sheet)
    check("字号都换成了 pt", len(pt_sizes) >= 10, str(len(pt_sizes)))

    print()
    print("── 5. 最大化窗口（如浏览器）要触发【让开】──")
    check("全屏/最大化判断能正常返回（不抛异常）",
          isinstance(tray._foreground_is_fullscreen(), bool))

    # 用受控几何真实验证判据阈值。
    # 背景：不能用 IsZoomed()——Chrome 这类自绘标题栏的程序不设 WS_MAXIMIZE，
    # 实测最大化后 IsZoomed 仍是 0，所以改成按面积占比判断。
    from ctypes import wintypes

    import ctypes as _ct

    user32 = _ct.windll.user32
    probe = QWidget()
    probe.resize(600, 400)
    probe.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    probe_hwnd = int(probe.winId())

    info = tray_app.MONITORINFO()
    info.cbSize = _ct.sizeof(tray_app.MONITORINFO)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(probe_hwnd, 2), _ct.byref(info))
    work_w = info.rcWork.right - info.rcWork.left
    work_h = info.rcWork.bottom - info.rcWork.top

    def verdict_for(width: int, height: int) -> "bool | None":
        user32.SetWindowPos(probe_hwnd, 0, 60, 60, width, height, 0x0040)
        for _ in range(30):
            app.processEvents()
            time.sleep(0.01)
        user32.SetForegroundWindow(probe_hwnd)
        for _ in range(40):
            app.processEvents()
            time.sleep(0.01)
        # 离屏平台下窗口不会真的成为前台窗口，这时判据没有意义，跳过这组检查
        if user32.GetForegroundWindow() != probe_hwnd:
            return None
        return bool(tray._foreground_is_fullscreen())

    small = verdict_for(600, 400)
    medium = verdict_for(min(1000, work_w - 200), min(700, work_h - 200))
    maximized = verdict_for(int(work_w * 0.84), int(work_h * 0.96))
    fullscreen = verdict_for(work_w, work_h)
    probe.close()
    app.processEvents()

    if small is None:
        print("  （离屏平台拿不到前台窗口，几何判据改由 --live 模式验证）")
        # 逻辑本身仍要能跑通、不抛异常
        check("判据在离屏环境下也能安全返回布尔值",
              isinstance(tray._foreground_is_fullscreen(), bool))
    else:
        check("小窗口不触发让开", not small)
        check("中等窗口不触发让开", not medium)
        check("最大化尺寸（84%x96% 占比）触发让开", maximized,
              f"工作区 {work_w}x{work_h}")
        check("真全屏触发让开", fullscreen)

    source = (HERE / "tray_app.py").read_text(encoding="utf-8")
    # 只检查"真的调用了 IsZoomed"，注释/文档里提到不算
    check("代码里没有真的调用 IsZoomed（那个对 Chrome 无效）",
          "user32.IsZoomed(" not in source)
    check("改用工作区面积占比判断", "coverage" in source)

    print()
    print("── 6. 回到桌面自动显示 ──")
    check("默认开启自动显示", bool(cfg.get("dock_auto_show", True)))
    # 模拟：用户没主动隐藏，菜单栏却是隐藏的 → tick 应该把它显示出来
    cfg.set("dock_hidden_by_user", False, save=False)
    dock.hide_bar()
    app.processEvents()
    check("先把菜单栏藏起来", not dock.isVisible())

    # 把"前台是桌面"这件事伪造出来，验证自动显示逻辑
    original = tray._desktop_is_foreground
    tray._desktop_is_foreground = lambda: True
    try:
        tray._auto_show_tick()
        app.processEvents()
        check("检测到回到桌面 → 菜单栏自动显示", dock.isVisible())
    finally:
        tray._desktop_is_foreground = original

    # 用户主动隐藏时不该自动弹
    dock.hide_self()
    app.processEvents()
    tray._desktop_is_foreground = lambda: True
    try:
        tray._auto_show_tick()
        app.processEvents()
        check("用户主动隐藏后，即使回到桌面也不弹", not dock.isVisible())
    finally:
        tray._desktop_is_foreground = original
        cfg.set("dock_hidden_by_user", False, save=False)

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
