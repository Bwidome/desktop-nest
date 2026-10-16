#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证《需求.txt》第 2 条 + 「Nexus Dock 式拖拽排序动画」
======================================================
  2、优化手动排序的动画，做到长按拖动图标插入到某个位置时，后面的软件会自动后移，
     如果拖到桌面就保持原样不进行排序。

动画改成**弹簧驱动**（springs.py）之后，位置不再是一帧瞬移，所以这里的断言
分两类：
  * 「意图」类（目标槽位、配置顺序、模式切换）—— 事件一发生就能断言；
  * 「视觉」类（谁挪到了哪个槽位）—— 要 pump 若干帧等弹簧停下来再断言。

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


def pump_until_rest(app, dock, timeout: float = 3.0) -> bool:
    """跑到弹簧动画自己停下来（`_on_anim_tick` 会在全部到位后停表）。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if not dock._anim_timer.isActive():
            return True
        time.sleep(0.004)
    return False


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

    import dock as dock_mod
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

    def xs() -> "list[int]":
        return [b.x() for b in dock._app_buttons]

    def names() -> "list[str]":
        return [e["name"] for e in cfg.quick_items]

    def center_of(button) -> QPoint:
        return button.mapToGlobal(QPoint(button.width() // 2,
                                        button.height() // 2))

    def slot_center(index: int) -> QPoint:
        """第 index 个**槽位**中心的屏幕坐标。

        必须用冻结的 `_slots` 算，不能拿按钮当前位置 —— 让位一开始按钮就在动，
        拿它当光标基准会算出"上一个状态"的槽位（测试自己会飘）。
        """
        origin = dock.apps_flow.mapToGlobal(QPoint(0, 0))
        slot = dock._slots[index]
        button = dock._app_buttons[index]
        return QPoint(origin.x() + int(slot[0]) + button.width() // 2,
                      origin.y() + int(slot[1]) + button.height() // 2)

    before_x = xs()
    print(f"  让位前各按钮 x: {before_x}")
    print()

    print("── 1. 长按进入排序模式：冻结槽位 + 建弹簧 ──")
    start = dock._app_buttons[0]
    press = center_of(start)
    dock._on_icon_press(start, press)
    dock._on_icon_hold(start, press)
    app.processEvents()
    check("进入排序模式", dock._mode == "reorder", dock._mode)
    check("被拖的是第 0 项", dock._reorder_from == 0, str(dock._reorder_from))
    check("每个按钮都配了弹簧", len(dock._springs) == 5, str(len(dock._springs)))
    check("槽位已冻结（5 个）", len(dock._slots) == 5, str(len(dock._slots)))
    check("冻结的槽位就是当前布局位置",
          [int(s[0]) for s in dock._slots] == before_x,
          f"{[int(s[0]) for s in dock._slots]} vs {before_x}")
    dragged_spring = dock._springs[start]
    other_spring = dock._springs[dock._app_buttons[2]]
    check("被拖的图标用「跟手」的硬弹簧（刚度 %.0f）"
          % dock_mod.DRAGGED_SPRING["stiffness"],
          dragged_spring.x.stiffness == dock_mod.DRAGGED_SPRING["stiffness"])
    check("被拖的图标是临界阻尼（绝不过冲）",
          abs(dragged_spring.x.ratio() - 1.0) < 1e-9,
          str(dragged_spring.x.ratio()))
    check("让位的图标用另一套弹簧（要求 6：动画独立）",
          other_spring.x.stiffness == dock_mod.REORDER_SPRING["stiffness"]
          and other_spring.x.stiffness != dragged_spring.x.stiffness)
    check("让位的图标略欠阻尼（会轻轻过冲一下）",
          other_spring.x.ratio() < 1.0, str(other_spring.x.ratio()))

    print()
    print("── 2. 拖到第 3 个位置：targetIndex 实时算出 + 后面的图标弹开让位 ──")
    third = dock._app_buttons[3]
    over = slot_center(3)
    dock._on_icon_move(start, over)
    app.processEvents()
    # 「意图」类：不等动画，事件一到就该算出目标槽位（要求 1、2）
    check("目标槽位立刻 = 3（不等 mouseup）", dock._reorder_to == 3,
          str(dock._reorder_to))
    check("让位还没结束（弹簧是异步的）", dock._anim_timer.isActive())
    check("松手前的顺序还没变（只是视觉让位）",
          names() == [f"软件{i}" for i in range(5)], str(names()))

    rest = pump_until_rest(app, dock)
    check("让位动画在 3 秒内自然停下", rest)
    after_x = xs()
    print(f"  让位后各按钮 x: {after_x}")
    step = dock._app_buttons[0].width() + dock.apps_flow._spacing      # noqa: SLF001
    check("第 1/2/3 项整体左移一格（让位）",
          after_x[1] == before_x[0] and after_x[2] == before_x[1]
          and after_x[3] == before_x[2],
          f"after={after_x}, before={before_x}, step={step}")
    # 排列是 [1,2,3,0,4]：原第 1/2/3 项依次坐进槽位 0/1/2
    check("让位后位置**精确**落在槽位上（没有残留抖动）",
          after_x[1] == int(dock._slots[0][0])
          and after_x[2] == int(dock._slots[1][0])
          and after_x[3] == int(dock._slots[2][0]),
          f"{after_x} vs 槽位 {[int(s[0]) for s in dock._slots]}")
    check("目标之外的图标不动", after_x[4] == before_x[4],
          f"{after_x[4]} vs {before_x[4]}")
    check("被拖的图标跟着光标落到了第 3 槽",
          after_x[0] == int(dock._slots[3][0]),
          f"{after_x[0]} vs {int(dock._slots[3][0])}")

    print()
    print("── 3. 快速拖动：一次事件跨过多个图标也要算对（要求 8） ──")
    frozen = list(dock._slots)
    dock._on_icon_move(start, slot_center(4))
    app.processEvents()
    check("一步跨到第 4 槽，targetIndex 直接 = 4", dock._reorder_to == 4,
          str(dock._reorder_to))
    check("槽位表全程不变（冻结住了，才不会抖）", dock._slots == frozen)
    dock._on_icon_move(start, slot_center(3))
    app.processEvents()
    check("再退回第 3 槽也立刻跟上", dock._reorder_to == 3, str(dock._reorder_to))
    dock._on_icon_move(start, slot_center(1))
    app.processEvents()
    check("反向拖到第 1 槽同样立刻跟上", dock._reorder_to == 1,
          str(dock._reorder_to))
    dock._on_icon_move(start, slot_center(3))
    app.processEvents()
    check("回到第 3 槽（为下一节做准备）", dock._reorder_to == 3,
          str(dock._reorder_to))
    pump_until_rest(app, dock)

    print()
    print("── 4. 拖拽中布局不许插手（否则就是「位置重置」） ──")
    held = xs()
    dock._settle()                       # 模拟 60ms 的 settle 定时器正好在此刻触发
    dock._resize_to_content()
    app.processEvents()
    check("拖拽期间 `_reorder_locked()` 为真", dock._reorder_locked() is True)
    check("调了 _settle()/_resize_to_content() 也没把图标摆回布局位置",
          xs() == held, f"{xs()} vs {held}")
    check("视觉顺序也没被改动",
          dock.apps_flow._items[1] is dock._app_buttons[0],
          "apps_flow._items 前两项应为 [桌面整理, 软件0]")

    print()
    print("── 5. 在菜单栏内松手：顺序真的变了，然后弹簧回位 ──")
    dock._on_icon_release(start, over)
    app.processEvents()
    check("配置顺序已更新", names() == ["软件1", "软件2", "软件3", "软件0", "软件4"],
          str(names()))
    check("退出排序模式", dock._mode == "", dock._mode)
    check("进入回弹阶段（_settling）", dock._settling is True)
    check("指示线已隐藏",
          dock._drop_line is None or not dock._drop_line.isVisible())
    rest = pump_until_rest(app, dock)
    check("回弹动画在 3 秒内自然停下", rest)
    check("回弹结束、交回布局（_settling 归位）", dock._settling is False)
    check("弹簧表已清空（交接完成）", not dock._springs, str(len(dock._springs)))
    check("视觉顺序与配置一致（FlowRow 顺序 = _app_buttons 顺序）",
          dock.apps_flow._items[1:] == list(dock._app_buttons),
          f"{[b.text() for b in dock.apps_flow._items[1:]]}")
    check("按钮都回到了布局位置（逐个对齐）",
          all(b.x() == dock.apps_flow._items[i + 1].x()
              for i, b in enumerate(dock._app_buttons)),
          str(xs()))
    check("重新排好之后仍然只有一行、位置是递增的",
          all(xs()[i] < xs()[i + 1] for i in range(4)), str(xs()))

    print()
    print("── 6. 拖到菜单栏外面松手：顺序保持原样 ──")
    order_before = names()
    src = dock._app_buttons[0]
    press = center_of(src)
    dock._on_icon_press(src, press)
    dock._on_icon_hold(src, press)
    app.processEvents()
    check("再次进入排序模式", dock._mode == "reorder")

    far = dock._app_buttons[3]
    over = slot_center(3)
    dock._on_icon_move(src, over)
    app.processEvents()
    check("拖到第 3 槽（让位已发生）", dock._reorder_to == 3, str(dock._reorder_to))
    pump_until_rest(app, dock)

    # 松手点放到菜单栏外面很远的地方
    outside = QPoint(dock.x() + dock.width() + 800, dock.y() - 600)
    dock._on_icon_release(src, outside)
    app.processEvents()
    check("拖到外面后顺序**没有**改变", names() == order_before,
          f"{names()} vs {order_before}")
    rest = pump_until_rest(app, dock)
    check("取消之后图标照样弹回原位（不会僵在半路）", rest)
    check("取消之后视觉顺序也没变",
          dock.apps_flow._items[1:] == list(dock._app_buttons),
          f"{[b.text() for b in dock.apps_flow._items[1:]]}")
    check("取消之后指示线是收起的",
          dock._drop_line is None or not dock._drop_line.isVisible())

    print()
    print("── 7. 排序过程中不会顺手把软件启动了 ──")
    check("全程没有触发启动（按钮仍是 5 个）", len(dock._app_buttons) == 5)

    print()
    print("── 8. 接上真实链路 quick_changed → dock.rebuild()（防回归） ──")
    # `tray_app._on_quick_changed()` 收到 quick_changed 就会调 `dock.rebuild()`，
    # 而 rebuild() 会 deleteLater() 掉所有图标。所以这条通知**绝不能**在
    # 回弹还没结束时发 —— 一发出去，正在动画的按钮当场被销毁，
    # `_app_buttons` 会变成一批"已销毁对象"，整个 Dock 直接废掉。
    rebuilt: "list[int]" = []
    dock.quick_changed.connect(lambda: (rebuilt.append(1), dock.rebuild()))

    order_before = names()
    src = dock._app_buttons[0]
    press = center_of(src)
    dock._on_icon_press(src, press)
    dock._on_icon_hold(src, press)
    app.processEvents()
    over = slot_center(2)
    dock._on_icon_move(src, over)
    app.processEvents()
    check("目标槽位 = 2", dock._reorder_to == 2, str(dock._reorder_to))
    check("拖动途中没有提前通知外部（否则按钮会被提前销毁）", not rebuilt,
          str(len(rebuilt)))
    dock._on_icon_release(src, over)
    app.processEvents()
    check("松手当下也还没通知（要等回弹结束）", not rebuilt, str(len(rebuilt)))

    rest = pump_until_rest(app, dock)
    check("回弹结束", rest)
    check("回弹结束之后才发出 quick_changed（正好一次）", rebuilt == [1],
          str(rebuilt))

    alive = True
    for button in dock._app_buttons:
        try:
            button.icon()
        except RuntimeError:
            alive = False
    check("重建之后 _app_buttons 全是活的对象（没被销毁对象污染）", alive)
    expected = [order_before[1], order_before[2], order_before[0]] + order_before[3:]
    check("重建之后配置顺序仍然是拖动结果", names() == expected,
          f"{names()} vs {expected}")
    check("重建之后 UI 顺序与配置一致",
          [Path(str(b._payload)).stem for b in dock._app_buttons]
          == [Path(e["path"]).stem for e in cfg.quick_items],
          f"{[Path(str(b._payload)).stem for b in dock._app_buttons]}")

    print()
    print("── 9. 高频 pointermove 不能把动画拖成慢动作 ──")
    # 时间基准只归定时器自己管：`_start_anim()` 在定时器已经在跑时
    # **不能**重置 `_anim_last`，否则每一拍的 dt 只有一两毫秒，
    # 弹簧被推进得奇慢（高回报率鼠标下就是"黏黏的慢动作"）。
    dock._anim_timer.stop()
    dock._start_anim()
    check("定时器没跑时会设好时间基准", dock._anim_last > 0.0,
          str(dock._anim_last))
    check("并且把定时器起起来了", dock._anim_timer.isActive())
    stamp = dock._anim_last
    time.sleep(0.05)
    dock._start_anim()                      # 模拟一次 pointermove
    check("定时器已经在跑时**不动**时间基准",
          dock._anim_last == stamp, f"{dock._anim_last} vs {stamp}")
    dock._anim_timer.stop()

    # 端到端：按住之后用 ~200Hz 的频率灌 pointermove，让位仍要按时走完
    storm = dock._app_buttons[0]
    storm_press = center_of(storm)
    dock._on_icon_press(storm, storm_press)
    dock._on_icon_hold(storm, storm_press)
    app.processEvents()
    storm_target = slot_center(3)
    deadline = time.monotonic() + 0.25
    ticks = 0
    while time.monotonic() < deadline:
        dock._on_icon_move(storm, storm_target)
        app.processEvents()
        time.sleep(0.005)
        ticks += 1
    check(f"确实灌了一批高频事件（{ticks} 次）", ticks >= 20, str(ticks))
    rest = pump_until_rest(app, dock, 1.5)
    check("让位在 1.5 秒内仍然走完（没被拖成慢动作）", rest)
    check("被拖的图标落在了第 3 槽",
          storm.x() == int(dock._slots[3][0]),
          f"{storm.x()} vs {int(dock._slots[3][0])}")
    dock._on_icon_release(storm, storm_target)
    pump_until_rest(app, dock, 2.0)

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    dock.hide_bar()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
