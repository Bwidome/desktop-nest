#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户报告的两个问题 —— 回归测试
==============================

**问题 1：托盘「管理常用启动…」点一下就崩溃。**

根因：`rebuild_tray_menu()` 里连的是 `lambda: self.open_browse()`，
而 `TrayApp` **根本没有 `open_browse` 这个方法**。PyQt6 里槽函数抛出的异常
不会打 traceback，而是直接 abort 进程 —— 所以表现成"点一下闪退"，
日志里连一行都没有，极难查。

修法：换成真实存在的 `open_manage_apps()`，并且它要做两件事
（这也是需求要的）：**打开收纳面板 + 自动进入管理模式**。

**问题 2：新窗口压在菜单栏上时，菜单栏要让开。**

原来只有"全屏 / 最大化"才让开（`_foreground_is_fullscreen()` 按面积占比判）。
需求改成：**只要窗口和菜单栏真的重叠就隐藏，不重叠就正常显示**。

新增 `_foreground_hits_dock()`：直接量两块矩形相不相交。为了不和
"拖动窗口经过菜单栏"这种瞬时状态打架，配上 `AUTO_SHOW_INTERVAL`（400ms）
+ 连续两次确认的防抖。

用法：python dev/test_fixes_dock.py
"""
from __future__ import annotations

import ast
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


def pump(app, seconds: float = 0.2) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-fixes-dock"
    shutil.rmtree(base, ignore_errors=True)
    desktop = base / "Desktop"
    public = base / "Public"
    cfg_dir = base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    for index, target in enumerate([
        r"C:\Windows\System32\notepad.exe",
        r"C:\Windows\System32\calc.exe",
        r"C:\Windows\explorer.exe",
    ]):
        winlink.create_shortcut(desktop / f"程序{index}.lnk", target)
    for index in range(4):
        (desktop / f"文件{index}.txt").write_text("x" * 40, encoding="utf-8")

    from qt_compat import QApplication, QMessageBox

    app = QApplication([])

    import config as config_mod
    import nest

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False, "page_size": 28})
    nest.nest_root = lambda: base / ".nest"
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop

    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

    import tray_app
    from tray_app import AUTO_SHOW_INTERVAL, rects_overlap

    tray = None
    crashed = ""
    try:
        tray = tray_app.TrayApp(cfg, silent=True)
    except Exception:
        crashed = traceback.format_exc()
    check("整个程序能启动", tray is not None, crashed[-400:])
    if tray is None:
        print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        return 1

    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)

    # ==================================================================
    section("1. 托盘菜单的每个槽都指向**真实存在**的方法")
    # ==================================================================
    # 这次的崩溃就是"槽指向不存在的方法"。PyQt6 不会报错，直接 abort，
    # 所以只能靠静态扫描把它挡在提交前。
    source = (HERE / "tray_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    tray_cls = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.ClassDef) and node.name == "TrayApp"),
                    None)
    check("能找到 TrayApp 类", tray_cls is not None)

    defined = set()
    for node in ast.walk(tray_cls) if tray_cls else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    defined.add(target.attr)

    # 只扫 rebuild_tray_menu 里 `self.xxx` 形式的**方法调用**引用
    menu_fn = next((node for node in ast.walk(tray_cls)
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "rebuild_tray_menu"), None) if tray_cls else None
    check("能找到 rebuild_tray_menu", menu_fn is not None)

    referenced = set()
    for node in ast.walk(menu_fn) if menu_fn else []:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "self":
            referenced.add(node.attr)
    # 过滤掉 Qt 基类给的 / 外部注入的成员，只看本类自己该有的
    from qt_compat import QSystemTrayIcon

    inherited = {name for name in dir(QSystemTrayIcon)}
    inherited |= {"menu", "tray", "cfg", "panel", "dock", "desktop_browser",
                  "nest_items", "history", "_scan"}
    missing = sorted(name for name in referenced
                     if name not in defined and name not in inherited)
    check("托盘菜单里引用的 self.xxx 都有定义（不会点出 AttributeError）",
          not missing, str(missing))
    # 注释里还留着"这里原来写的是 self.open_browse()"的说明，所以查的是
    # **整份源码里所有 `self.xxx` 属性访问**，不是简单字符串包含。
    self_attrs = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)
                  and isinstance(node.value, ast.Name)
                  and node.value.id == "self"}
    check("原来那个不存在的 open_browse 已经不再被调用",
          "open_browse" not in self_attrs, str(sorted(self_attrs & {"open_browse"})))
    check("「管理常用启动…」连的是 open_manage_apps",
          "manage.triggered.connect(self.open_manage_apps)" in source)

    # ==================================================================
    section("2. 点「管理常用启动…」：打开收纳面板 + 进管理模式")
    # ==================================================================
    browser = tray.desktop_browser
    # 面板只展示**收纳目录**里的内容，所以先把桌面收进来，否则是空的、
    # 也就没有卡片可以长角标（这几条断言就白测了）。
    taken = nest.take_from_desktop(desktop)
    check("前置：桌面内容已收进收纳目录", taken.moved > 0, str(taken.moved))
    # 先确保是"关着 + 非管理模式"的初始状态
    browser.hide()
    browser.set_manage_mode(False)
    pump(app, 0.2)
    check("前置：面板是关着的", browser.isHidden())
    check("前置：不在管理模式", browser._manage_mode is False)

    ok = True
    error = ""
    try:
        tray.open_manage_apps()
    except Exception:
        ok = False
        error = traceback.format_exc()
    pump(app, 0.35)
    check("点击不再抛异常（原来会直接 abort 进程）", ok, error[-300:])
    check("自动打开了收纳面板", not browser.isHidden())
    check("自动进入了管理模式", browser._manage_mode is True)
    check("「管理」控件同步成选中态（文案变成完成）",
          browser.btn_manage.isChecked() and "完成" in browser.btn_manage.text(),
          browser.btn_manage.text().replace("\n", "|"))
    check("提示行说清了怎么用",
          "管理模式" in browser.hint.text(), browser.hint.text())

    # 卡片角标要真的长出来（不是只改了个标志位）
    badges = [tile for tile in browser._tiles if tile.badge is not None]
    check("卡片上有角标对象", bool(badges), str(len(browser._tiles)))
    check("角标是可见的",
          all(tile.badge.isHidden() is False for tile in badges) if badges else False,
          str([tile.badge.isHidden() for tile in badges]))

    # 再点一次要能退出（不卡在管理模式）
    browser.toggle_manage_mode()
    pump(app, 0.2)
    check("能正常退出管理模式", browser._manage_mode is False)
    check("退出后角标藏起来",
          all(tile.badge.isHidden() for tile in browser._tiles
              if tile.badge is not None))
    browser.hide()
    pump(app, 0.1)

    # ==================================================================
    section("3. 矩形相交判据（纯算术，喂假矩形）")
    # ==================================================================
    dock = (100, 1000, 900, 1060)          # 一条贴着屏幕底部的横条
    check("完全盖住 → 算重叠", rects_overlap((0, 0, 1920, 1080), dock, 24, 6))
    check("整块压在下面 → 算重叠", rects_overlap((50, 900, 950, 1080), dock, 24, 6))
    check("只在上面、完全没碰到 → 不算",
          not rects_overlap((100, 200, 900, 980), dock, 24, 6))
    check("底边正好贴着菜单栏顶边 → 不算（严格不等）",
          not rects_overlap((100, 500, 900, 1000), dock, 24, 6))
    check("只压住 3 像素 → 不算（太像擦边）",
          not rects_overlap((100, 500, 900, 1003), dock, 24, 6))
    check("压住 20 像素 → 算重叠",
          rects_overlap((100, 500, 900, 1020), dock, 24, 6))
    check("横向只压住 10 像素（窗口在屏幕左边） → 不算",
          not rects_overlap((10, 900, 110, 1080), dock, 24, 6))
    check("横向压住 200 像素 → 算",
          rects_overlap((10, 900, 300, 1080), dock, 24, 6))
    check("左右完全错开 → 不算",
          not rects_overlap((1000, 900, 1200, 1080), dock, 24, 6))
    check("参数是脏的也不抛异常", rects_overlap(None, dock) is False)
    check("空元组也不抛异常", rects_overlap((), dock) is False)

    # ==================================================================
    section("4. 该不该让开：全屏 或 压住菜单栏")
    # ==================================================================
    original_fs = tray._foreground_is_fullscreen
    original_hit = tray._foreground_hits_dock

    tray._foreground_is_fullscreen = lambda: True
    tray._foreground_hits_dock = lambda: False
    check("全屏 → 让开", tray._should_avoid_dock() is True)

    tray._foreground_is_fullscreen = lambda: False
    tray._foreground_hits_dock = lambda: True
    check("窗口不大、但压在菜单栏上 → 也让开", tray._should_avoid_dock() is True)

    tray._foreground_is_fullscreen = lambda: False
    tray._foreground_hits_dock = lambda: False
    check("都不成立 → 正常显示", tray._should_avoid_dock() is False)

    tray._foreground_is_fullscreen = original_fs
    tray._foreground_hits_dock = original_hit

    # ==================================================================
    section("5. 自动显隐的编排（打桩判据，验节奏）")
    # ==================================================================
    dock_widget = tray.dock
    tray._foreground_is_fullscreen = lambda: False
    tray._foreground_hits_dock = lambda: True
    tray._fs_streak = 0
    tray._normal_streak = 0
    if not dock_widget.isVisible():
        dock_widget.show_bar()
        pump(app, 0.2)

    tray._auto_show_tick()
    check("第一次 tick 只累计、不立刻隐藏（防抖）",
          dock_widget.isVisible() and tray._fs_streak == 1,
          f"visible={dock_widget.isVisible()} streak={tray._fs_streak}")
    tray._auto_show_tick()
    check("连续两次确认 → 菜单栏让开", not dock_widget.isVisible())
    check("记住了「是因为让开才藏的」", tray._dock_hidden_for_fullscreen is True)

    # 窗口不再重叠 → 两次确认后回来
    tray._foreground_hits_dock = lambda: False
    tray._normal_streak = 0
    tray._auto_show_tick()
    tray._auto_show_tick()
    check("不再重叠后 → 菜单栏自己回来", dock_widget.isVisible())
    check("清掉了「让开」标记", tray._dock_hidden_for_fullscreen is False)

    # 用户主动隐藏的优先级最高
    dock_widget.hide_self()
    pump(app, 0.1)
    tray._foreground_hits_dock = lambda: True
    tray._fs_streak = 0
    for _ in range(3):
        tray._auto_show_tick()
    check("用户主动隐藏时，重叠也不弹回来", not dock_widget.isVisible())
    tray.toggle_dock()                      # 还原，别影响后面的用例
    pump(app, 0.2)

    # 收纳面板开着的时候：菜单栏平时要稳住（翻页 / 搜索时不能闪没），
    # 但如果用户切到了别的窗口、而那个窗口压住了菜单栏，仍然要让开。
    browser.show_window()
    pump(app, 0.35)
    if not dock_widget.isVisible():
        dock_widget.show_bar()
        pump(app, 0.15)
    tray._foreground_is_fullscreen = lambda: False
    tray._foreground_hits_dock = lambda: True
    tray._fs_streak = 0
    tray._normal_streak = 0
    tray._auto_show_tick()
    tray._auto_show_tick()
    check("面板开着、但别的窗口压上来 → 菜单栏仍要让开",
          not dock_widget.isVisible())

    tray._foreground_hits_dock = lambda: False
    tray._normal_streak = 0
    tray._auto_show_tick()
    tray._auto_show_tick()
    check("面板开着、没别的窗口压上来 → 菜单栏稳住显示",
          dock_widget.isVisible())
    browser.hide()
    pump(app, 0.15)

    tray._foreground_is_fullscreen = original_fs
    tray._foreground_hits_dock = original_hit
    tray._fs_streak = 0
    tray._normal_streak = 0

    # ==================================================================
    section("6. 平台闸门与节奏")
    # ==================================================================
    check("离屏平台不做真实窗口探测（返回 False 而不是瞎猜）",
          tray._foreground_hits_dock() is False)
    check(f"检查间隔够快（{AUTO_SHOW_INTERVAL}ms ≤ 500ms），打开窗口能及时让开",
          AUTO_SHOW_INTERVAL <= 500, str(AUTO_SHOW_INTERVAL))
    check("间隔是个具名常量，不是散落的魔法数字",
          "QTimer.singleShot(AUTO_SHOW_INTERVAL" in source)
    check("源码里不再有写死的 1200 定时（原来那样要等 2.4 秒）",
          "singleShot(1200, self._auto_show_tick)" not in source)
    check("探测方法名与语义对得上（hits_dock）",
          hasattr(tray, "_foreground_hits_dock")
          and hasattr(tray, "_should_avoid_dock"))

    # 收尾
    try:
        tray.shutdown() if hasattr(tray, "shutdown") else None
    except Exception:
        pass

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for item in FAIL:
            print(f"  ✗ {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
