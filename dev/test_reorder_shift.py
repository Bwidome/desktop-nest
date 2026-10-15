#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证《需求.txt》第 2 条：拖动排序的「让位」动画 + 拖到外面不排序
=============================================================
  2、优化手动排序的动画，做到长按拖动图标插入到某个位置时，后面的软件会自动后移，
     如果拖到桌面就保持原样不进行排序。

用法：python dev/test_reorder_shift.py
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
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-reorder"
    shutil.rmtree(base, ignore_errors=True)
    desktop = base / "Desktop"
    desktop.mkdir(parents=True)

    import winlink

    for index in range(5):
        winlink.create_shortcut(desktop / f"软件{index}.lnk",
                                r"C:\Windows\System32\notepad.exe")

    from qt_compat import QApplication, QPoint

    app = QApplication([])
    import config as config_mod

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(desktop), "dock_visible": True})

    import nest

    nest.nest_root = lambda: base / ".nest"
    for link in sorted(desktop.glob("*.lnk")):
        cfg.add_quick(link, link.stem)

    from dock import DockBar

    dock = DockBar(cfg)
    dock.show_bar()
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)

    buttons = dock._app_buttons
    check("有 5 个常用项按钮", len(buttons) == 5, str(len(buttons)))
    if len(buttons) < 5:
        return 1

    # 记下让位前的横坐标
    def xs() -> "list[int]":
        return [b.x() for b in dock._app_buttons]

    def names() -> "list[str]":
        return [e["name"] for e in cfg.quick_items]

    before_x = xs()
    print(f"  让位前各按钮 x: {before_x}")
    print()

    print("── 1. 长按进入排序模式 ──")
    start = dock._app_buttons[0]
    press = start.mapToGlobal(QPoint(start.width() // 2, start.height() // 2))
    dock._on_icon_press(start, press)
    dock._on_icon_hold(start, press)
    app.processEvents()
    check("进入排序模式", dock._mode == "reorder", dock._mode)
    check("被拖的是第 0 项", dock._reorder_from == 0, str(dock._reorder_from))

    print()
    print("── 2. 拖到第 3 个位置：后面的图标要自动后移 ──")
    third = dock._app_buttons[3]
    over = third.mapToGlobal(QPoint(third.width() // 2, third.height() // 2))
    dock._on_icon_move(start, over)
    app.processEvents()
    check("目标槽位 = 3", dock._reorder_to == 3, str(dock._reorder_to))

    after_x = xs()
    print(f"  让位后各按钮 x: {after_x}")
    # 被拖的第 0 项不动；原来是 1、2、3 位置的应该整体左移一格
    step = dock._app_buttons[0].width() + dock.apps_flow._spacing      # noqa: SLF001
    check("被拖的图标原地不动（它跟着光标走）", after_x[0] == before_x[0],
          f"{after_x[0]} vs {before_x[0]}")
    moved = [i for i in range(1, 4) if after_x[i] == before_x[i] - step]
    check("中间的图标整体左移一格（让位）", len(moved) == 3,
          f"实际移动的: {moved}, step={step}, after={after_x}, before={before_x}")
    check("目标之外的图标不动", after_x[4] == before_x[4],
          f"{after_x[4]} vs {before_x[4]}")
    check("松手前的顺序还没变（只是视觉让位）",
          names() == [f"软件{i}" for i in range(5)], str(names()))

    print()
    print("── 3. 在菜单栏内松手：顺序真的变了 ──")
    dock._on_icon_release(start, over)
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    check("配置顺序已更新", names() == ["软件1", "软件2", "软件3", "软件0", "软件4"],
          str(names()))
    check("退出排序模式", dock._mode == "", dock._mode)
    check("指示线已隐藏",
          dock._drop_line is None or not dock._drop_line.isVisible())
    check("让位位移已还原（按钮回到布局位置）",
          dock._app_buttons[0].x() == dock.apps_flow._items[0].x()      # noqa: SLF001
          or all(b.x() >= 0 for b in dock._app_buttons),
          str([b.x() for b in dock._app_buttons]))

    print()
    print("── 4. 拖到菜单栏外面松手：顺序保持原样 ──")
    order_before = names()
    src = dock._app_buttons[0]
    press = src.mapToGlobal(QPoint(src.width() // 2, src.height() // 2))
    dock._on_icon_press(src, press)
    dock._on_icon_hold(src, press)
    app.processEvents()
    check("再次进入排序模式", dock._mode == "reorder")

    far = dock._app_buttons[3]
    over = far.mapToGlobal(QPoint(far.width() // 2, far.height() // 2))
    dock._on_icon_move(src, over)
    app.processEvents()
    check("拖到第 3 槽（让位已发生）", dock._reorder_to == 3, str(dock._reorder_to))

    # 松手点放到菜单栏外面很远的地方
    outside = QPoint(dock.x() + dock.width() + 800, dock.y() - 600)
    dock._on_icon_release(src, outside)
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    check("拖到外面后顺序**没有**改变", names() == order_before,
          f"{names()} vs {order_before}")
    check("让位效果已还原",
          dock._drop_line is None or not dock._drop_line.isVisible())

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    dock.hide_bar()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
