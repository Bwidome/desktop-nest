#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户报告的「底部悬停乱弹菜单栏」+「右键没有隐藏菜单栏」—— 回归测试
================================================================

**问题 1：鼠标指向屏幕底部时菜单栏自己弹出来，全屏下也弹。**

根因在 `dock_dodge._check_edge()`：它只判断"菜单栏那一带被别的窗口占着"
（`_occluded`），然后只要鼠标落进菜单栏原来那块矩形就 `peek()` 唤回来。
于是全屏看视频、把鼠标甩到屏幕底部去够播放控制条的时候，菜单栏就被叫出来
盖在视频上——用户看到的正是这个。

`_check_edge()` 是**轮询**驱动的（120ms），不是靠"用户点了什么"，
所以这个误触发几乎必然发生，而且很难解释成"手滑"。

修法：`_check_edge()` 开头加 `_on_desktop()` 闸门。两个条件都满足才允许唤回：

1. 菜单栏那一带没被占（`_fullscreen` / `_covered` 都是 False）；
2. 前台窗口**就是桌面本身**（`Progman` / `WorkerW` / `SHELLDLL_DefView`）。

顺带修了同一类毛病的另一半：`_desired_visible()` 里"唤回保持期"原来
**无条件**返回 True，压过了遮挡判定。结果"在桌面唤回 → 立刻切全屏"时，
菜单栏会赖在屏幕上最多 2.5 秒。现在保持期只在 `not self._occluded` 时才算数。

**问题 2：右键菜单栏应该有个「隐藏菜单栏」。**

原来空白处的菜单里有一条「暂时隐藏菜单栏」，但它只做了
`cfg.set("dock_visible", False) + hide_bar()`，**没有** `emit hide_requested`，
所以托盘菜单的勾选状态、`dock_hidden_by_user` 标记、气泡提示全都没跟上；
而且菜单栏上几乎没有空白可点，用户多半是**对着图标**右键，
那个菜单里压根没有这一项。

修法：两个菜单都加「隐藏菜单栏」，统一走 `DockBar.hide_self()`
（✕ 按钮用的就是它），保证状态广播一致。

用法：python dev/test_dock_edge.py
"""
from __future__ import annotations

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
    base = Path(tempfile.gettempdir()) / "nest-dock-edge"
    shutil.rmtree(base, ignore_errors=True)
    desktop = base / "Desktop"
    public = base / "Public"
    cfg_dir = base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    (desktop / "文件.txt").write_text("x" * 20, encoding="utf-8")

    from qt_compat import QApplication, QMessageBox, QPoint

    app = QApplication([])

    import config as config_mod
    import nest

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False, "page_size": 28})
    nest.nest_root = lambda: base / ".nest"
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop

    QMessageBox.information = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes)

    import tray_app

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
    pump(app, 0.4)

    dock = tray.dock
    dodge = tray.dodge

    # 打桩：判断已经全部收进 DockDodge，桩要打在它读的字段上。
    original_fs = tray._foreground_is_fullscreen
    original_covering = dodge.covering_windows
    original_desktop = tray._desktop_is_foreground
    original_edge = dodge._mouse_on_edge
    original_dwell = tray_app.dock_dodge.EDGE_DWELL

    FAKE = [(1, (0, 900, 1920, 1080), "FakeWindow", "假窗口")]

    def show_dock() -> None:
        if dock.isHidden():
            dock.show_bar()
        pump(app, 0.12)

    def reset_dodge() -> None:
        dodge._last_switch = 0.0
        dodge._peek_until = 0.0
        dodge._edge_since = 0.0
        dodge._animating = False

    # ==================================================================
    section("1. _on_desktop()：边缘唤回的闸门")
    # ==================================================================
    dodge.probe_enabled = False
    check("探测关掉时一律返回 False（离屏没有窗口管理器，不能瞎猜）",
          dodge._on_desktop() is False)

    dodge.probe_enabled = True
    tray._foreground_is_fullscreen = lambda: True
    dodge.covering_windows = lambda: []
    tray._desktop_is_foreground = lambda: True
    dodge._fullscreen, dodge._covered = True, False
    check("全屏中 → 不是「在桌面上」", dodge._on_desktop() is False)

    tray._foreground_is_fullscreen = lambda: False
    dodge.covering_windows = lambda: list(FAKE)
    dodge._fullscreen, dodge._covered = False, True
    check("普通窗口压着菜单栏 → 不是「在桌面上」", dodge._on_desktop() is False)

    dodge.covering_windows = lambda: []
    dodge._fullscreen, dodge._covered = False, False
    tray._desktop_is_foreground = lambda: False
    check("没人压着、但前台是别的窗口 → 仍然不算「在桌面上」",
          dodge._on_desktop() is False)

    tray._desktop_is_foreground = lambda: True
    check("没人压着、前台就是桌面 → 才算「在桌面上」",
          dodge._on_desktop() is True)

    # ==================================================================
    section("2. 用户报的 bug：全屏下鼠标碰到底部 → 菜单栏不许弹")
    # ==================================================================
    # 后面这几节要**手动**驱动 `_check_edge()` 数轮，必须先把兜底轮询停掉：
    # 它自己每 120ms 就会调一次 `_check_edge()`，跑起来会把"前置状态"
    # 当场推翻（第一次写这条用例就是这么假失败的——前置刚藏好，
    # 轮询立刻按"桌面上唤回"又给弹出来了）。
    dodge._poll.stop()
    dodge._coalesce.stop()

    cfg.set("dock_auto_show", True)
    cfg.set("dock_avoid_fullscreen", True)
    cfg.set("dock_avoid_overlap", True)
    cfg.set("dock_visible", True)
    cfg.set("dock_hidden_by_user", False)

    show_dock()
    tray._foreground_is_fullscreen = lambda: True
    dodge.covering_windows = lambda: []
    dodge._mouse_on_edge = lambda: True          # 鼠标正压在菜单栏那块矩形上
    tray_app.dock_dodge.EDGE_DWELL = 0.0         # 别为了等 0.15s 拖慢自检

    reset_dodge()
    dodge.evaluate()
    pump(app, 0.2)
    check("前置：全屏 → 菜单栏让开（隐藏）", dock.isHidden(),
          f"hidden={dock.isHidden()} occluded={dodge._occluded}")

    reset_dodge()
    for _ in range(12):                          # 模拟 12 个轮询周期
        dodge._check_edge()
        pump(app, 0.03)
    check("全屏下鼠标停在屏幕底部 → **不会**被唤回（这就是用户报的 bug）",
          dock.isHidden(), f"hidden={dock.isHidden()}")
    check("全屏下保持期压根没被设置", dodge._peek_until == 0.0,
          f"peek={dodge._peek_until}")

    # ==================================================================
    section("3. 普通窗口压着菜单栏时，同样不许被鼠标唤回")
    # ==================================================================
    tray._foreground_is_fullscreen = lambda: False
    dodge.covering_windows = lambda: list(FAKE)
    reset_dodge()
    dodge.evaluate()
    pump(app, 0.2)
    check("前置：窗口压上来 → 隐藏", dock.isHidden(), str(dock.isHidden()))

    reset_dodge()
    for _ in range(12):
        dodge._check_edge()
        pump(app, 0.03)
    check("鼠标停在底部也不弹（要它回来请用托盘菜单）",
          dock.isHidden(), f"hidden={dock.isHidden()}")

    # ==================================================================
    section("4. 真的在桌面上时，唤回仍然有效")
    # ==================================================================
    # 注意：把「回到桌面自动显示」关掉**不会**当场把菜单栏收起来
    # （`_desired_visible()` 第 7 条是"不主动放回来"，不是"主动藏起来"）。
    # 所以要唤回，得先手动把它收起来 —— 这正是这条通路存在的意义：
    # 菜单栏收着、用户又回到桌面想用，鼠标移到屏幕底部就该能叫出来。
    tray._foreground_is_fullscreen = lambda: False
    dodge.covering_windows = lambda: []
    tray._desktop_is_foreground = lambda: True
    cfg.set("dock_auto_show", False)
    reset_dodge()
    dock.hide_bar()
    # `_check_edge()` 读的是**已经算好**的 `_fullscreen` / `_covered`，
    # 不是现去枚举窗口。上一节把它们置成了"有遮挡"，这里必须让 evaluate()
    # 重算一遍，否则闸门永远关着（这条用例第一版就是这么假失败的）。
    dodge.evaluate()
    check("前置：菜单栏收着、自动显示关掉", dock.isHidden(),
          str(dock.isHidden()))

    reset_dodge()
    dodge._mouse_on_edge = lambda: True
    for _ in range(12):
        dodge._check_edge()
        pump(app, 0.03)
    check("桌面上鼠标停在底部 → 唤回菜单栏", dock.isVisible(),
          f"visible={dock.isVisible()} peek={dodge._peek_until:.2f}")
    check("唤回时给了一段保持期（够点到图标）",
          dodge._peek_until > time.monotonic(),
          f"peek={max(0.0, dodge._peek_until - time.monotonic()):.2f}s")

    cfg.set("dock_auto_show", True)
    show_dock()

    # ==================================================================
    section("5. 保持期不许压过遮挡判定")
    # ==================================================================
    # 目标场景：在桌面把菜单栏唤回来 → 马上切进全屏视频。
    # 以前保持期是无条件返回 True，菜单栏会在视频上赖 2.5 秒。
    dodge._peek_until = time.monotonic() + 10.0
    dodge._occluded, dodge._fullscreen, dodge._covered = True, True, False
    cfg.set("dock_avoid_fullscreen", True)
    check("保持期内切进全屏 → 仍然让开（保持期不能盖过遮挡）",
          dodge._desired_visible() is False)

    dodge._fullscreen, dodge._covered = False, True
    cfg.set("dock_avoid_overlap", True)
    check("保持期内有普通窗口压上来 → 也让开",
          dodge._desired_visible() is False)

    dodge._occluded, dodge._fullscreen, dodge._covered = False, False, False
    check("没有遮挡时保持期照常生效",
          dodge._desired_visible() is True)

    dodge._peek_until = 0.0

    # ==================================================================
    section("6. 右键菜单：「隐藏菜单栏」")
    # ==================================================================
    import dock as dock_mod

    original_popup = dock_mod.popup_menu
    captured = {}

    def fake_popup(menu, pos):
        captured["texts"] = [a.text() for a in menu.actions() if a.text()]
        for action in menu.actions():
            if action.text() == "隐藏菜单栏":
                return action
        return None

    # ---- 6.1 空白处右键（DockBar.contextMenuEvent） ----
    dock_mod.popup_menu = fake_popup
    try:
        show_dock()
        cfg.set("dock_visible", True)
        cfg.set("dock_hidden_by_user", False)
        dock.show_bar()
        pump(app, 0.15)

        dock.contextMenuEvent(None)
        pump(app, 0.2)
        texts = captured.get("texts", [])
        check("空白处右键的菜单里有「隐藏菜单栏」",
              "隐藏菜单栏" in texts, str(texts))
        check("点它之后菜单栏真的藏起来了", dock.isHidden(),
              str(dock.isHidden()))
        check("同时把 dock_visible 关掉（托盘菜单的勾选状态才对得上）",
              cfg.get("dock_visible") is False,
              str(cfg.get("dock_visible")))
        check("同时打上「用户主动隐藏」标记（不再被自动弹回来）",
              cfg.get("dock_hidden_by_user") is True,
              str(cfg.get("dock_hidden_by_user")))

        # ---- 6.2 图标右键（_quick_menu） ----
        tray.toggle_dock()                       # 先恢复显示
        pump(app, 0.2)
        check("前置：从托盘菜单能把它打开回来", dock.isVisible(),
              str(dock.isVisible()))

        entry = {"path": r"C:\Windows\System32\notepad.exe", "name": "记事本"}
        dock._quick_menu(None, entry, None)
        pump(app, 0.2)
        texts = captured.get("texts", [])
        check("图标右键的菜单里也有「隐藏菜单栏」",
              "隐藏菜单栏" in texts, str(texts))
        check("点它之后菜单栏也藏起来了", dock.isHidden(),
              str(dock.isHidden()))

        # ---- 6.3 「桌面整理」入口右键（它是 DockIcon，右键不会冒泡到 DockBar） ----
        tray.toggle_dock()
        pump(app, 0.2)
        captured.clear()
        dock.desktop_btn.context_requested.emit(dock.desktop_btn, QPoint(10, 10))
        pump(app, 0.2)
        texts = captured.get("texts", [])
        check("「桌面整理」入口右键也弹菜单栏菜单（而不是什么都不弹）",
              "隐藏菜单栏" in texts, str(texts))
        check("从这里点「隐藏菜单栏」同样生效", dock.isHidden(),
              str(dock.isHidden()))
    finally:
        dock_mod.popup_menu = original_popup

    # ==================================================================
    section("7. 源码层面：别再退回「只改配置不广播」的写法")
    # ==================================================================
    dock_source = (HERE / "dock.py").read_text(encoding="utf-8")
    check("旧的「暂时隐藏菜单栏」字样已经没有了",
          "暂时隐藏菜单栏" not in dock_source)
    check("两个菜单都挂到了 hide_self()（而不是自己 cfg.set + hide_bar）",
          dock_source.count("self.hide_self()") >= 2,
          str(dock_source.count("self.hide_self()")))
    # `hide_self()` 内部当然还是要写 `dock_visible=False`，所以只能要求
    # **只出现一次**——多出来就说明又有人在菜单里绕开它直接改配置了。
    check("cfg.set(\"dock_visible\", False) 只在 hide_self() 里出现一次",
          dock_source.count('self.cfg.set("dock_visible", False)') == 1,
          str(dock_source.count('self.cfg.set("dock_visible", False)')))

    dodge_source = (HERE / "dock_dodge.py").read_text(encoding="utf-8")
    check("_check_edge() 开头有 _on_desktop() 闸门",
          "if not self._on_desktop():" in dodge_source)
    check("保持期检查带上了遮挡条件",
          "time.monotonic() < self._peek_until and not self._occluded"
          in dodge_source)

    # ==================================================================
    # 收尾
    # ==================================================================
    tray_app.dock_dodge.EDGE_DWELL = original_dwell
    dodge._mouse_on_edge = original_edge
    dodge.covering_windows = original_covering
    tray._foreground_is_fullscreen = original_fs
    tray._desktop_is_foreground = original_desktop
    dodge.probe_enabled = False
    dodge._peek_until = 0.0
    dodge._occluded = False
    cfg.set("dock_auto_show", True)
    cfg.set("dock_visible", True)
    cfg.set("dock_hidden_by_user", False)

    try:
        tray.shutdown()
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
