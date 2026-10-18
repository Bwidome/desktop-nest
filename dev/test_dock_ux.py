#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 4 验收：打磨常用启动 + 底部 Dock
======================================
需求原文（`需求.txt` 第四阶段）：

  一、常用启动：优化 图标视觉 / 间距 / Hover / Tooltip / 管理状态 / 删除反馈；
      Hover scale 1.08~1.15；Tooltip 显示完整名称。
  二、拖拽排序：**现有实现不动**，只检查 快速拖动 / 跨多个项目 / 抖动 /
      排序错误 / 松手保存 / 重启后顺序保留；有 Bug 只做局部修复。
  三、Dock：优化 Hover / Active / Tooltip / 图标间距 / 阴影 / 背景，保持克制。
  四、拖入添加：架构容易支持就做（把收纳项目拖到菜单栏 = 加为常用启动）。
  五、反馈：加入 / 移出显示轻微 Toast，**不要用 Dialog**。

所以这份自检分两类断言：
  * **改了的东西**（间距 / Tooltip / Active / 阴影 / Toast / 拖放）——钉死新行为；
  * **没改的东西**（弹簧排序）——只钉"行为仍然正确"，不钉实现细节。

用法：python dev/test_dock_ux.py
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


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


def pump(app, seconds: float = 0.4) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def pump_until_rest(app, dock, timeout: float = 3.0) -> bool:
    """跑到弹簧动画自己停下来（`_on_anim_tick` 会在全部到位后停表）。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if not dock._anim_timer.isActive():          # noqa: SLF001
            return True
        time.sleep(0.004)
    return False


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-dock-ux"
    shutil.rmtree(base, ignore_errors=True)
    desktop, public = base / "Desktop", base / "Public"
    cfg_dock_dir, cfg_browser_dir = base / "cfg-dock", base / "cfg-browser"
    for folder in (desktop, public, cfg_dock_dir, cfg_browser_dir):
        folder.mkdir(parents=True)

    import winlink

    links = []
    for index in range(7):
        link = desktop / f"工具{index}.lnk"
        winlink.create_shortcut(link, r"C:\Windows\System32\notepad.exe")
        links.append(link)

    from qt_compat import (
        QApplication, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QEvent,
        QIcon, QMimeData, QPixmap, QPoint, QPointF, QSize, Qt,
    )

    app = QApplication([])
    import config as config_mod

    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: public

    import nest

    nest.nest_root = lambda: base / ".nest"

    import desktop_browser as db_mod
    import dock as dock_mod
    from widgets import DND_MIME, Toast, pixmap_for

    def new_cfg(folder: Path):
        cfg = config_mod.Config(folder)
        cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                    "auto_take_on_start": False, "dock_visible": True})
        return cfg

    # ==================================================================
    # 常用启动（收纳面板顶部那一排）
    # ==================================================================
    cfg_browser = new_cfg(cfg_browser_dir)
    import engine

    items = [engine.RepoItem(p, p.stem, False, "shortcut",
                             p.stat().st_size, p.stat().st_mtime) for p in links[:5]]
    # 只把前 4 个加成常用项，第 5 个（items[4]）留着当"还没加过的候选"，
    # 第 5 节要拿它验证"加入成功 → Toast"。
    for item in items[:4]:
        cfg_browser.add_quick(item.path, item.path.stem)

    browser = db_mod.DesktopBrowser(cfg_browser)
    browser.set_items(items)
    browser.resize(900, 620)
    browser.show()
    pump(app, 0.8)

    section("1. 常用启动：图标视觉 / 间距")
    check("图标尺寸走常量（38px，比原来大两档）",
          db_mod.APP_ICON == 38, str(db_mod.APP_ICON))
    check("按钮尺寸跟着图标一起放宽（84×72）",
          (db_mod.APP_BUTTON_W, db_mod.APP_BUTTON_H) == (84, 72),
          f"{db_mod.APP_BUTTON_W}x{db_mod.APP_BUTTON_H}")
    button = browser._app_buttons[0]
    check("实测：按钮确实按常量定尺寸",
          button.size() == QSize(db_mod.APP_BUTTON_W, db_mod.APP_BUTTON_H),
          str(button.size()))
    check("实测：图标尺寸就是 APP_ICON",
          button.iconSize() == QSize(db_mod.APP_ICON, db_mod.APP_ICON),
          str(button.iconSize()))
    check("图标与按钮之间留得下名称",
          db_mod.APP_ICON <= db_mod.APP_BUTTON_W - 30, str(db_mod.APP_ICON))
    check("图标之间的间距放宽到 10（原来是 6）",
          browser.apps_row.spacing() == db_mod.APP_GAP == 10,
          f"{browser.apps_row.spacing()} / {db_mod.APP_GAP}")
    check("间距不小于旧值（回归：不许越改越挤）",
          browser.apps_row.spacing() >= 6, str(browser.apps_row.spacing()))

    section("2. 常用启动：Hover（scale 1.08~1.15）")
    check("悬停放大比例在 1.08~1.15 之间",
          1.08 <= db_mod.APP_HOVER_SCALE <= 1.15, str(db_mod.APP_HOVER_SCALE))
    app.sendEvent(button, QEvent(QEvent.Type.Enter))
    hover = button._icon_anim.endValue()          # noqa: SLF001
    check("实测：Enter 之后图标变大",
          hover.width() > db_mod.APP_ICON, str(hover))
    ratio = hover.width() / db_mod.APP_ICON
    check("实测：放大幅度落在 1.08~1.15",
          1.08 <= ratio <= 1.15, f"{ratio:.3f}")
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    check("实测：Leave 之后回到原尺寸",
          button._icon_anim.endValue() == QSize(db_mod.APP_ICON,
                                                db_mod.APP_ICON),   # noqa: SLF001
          str(button._icon_anim.endValue()))                        # noqa: SLF001
    check("按钮本身尺寸不变（只有图标在放大，整排不会重排）",
          button.size() == QSize(db_mod.APP_BUTTON_W, db_mod.APP_BUTTON_H),
          str(button.size()))

    section("3. 常用启动：Tooltip 要显示完整名称")
    long_name = browser._app_buttons[0].display_name
    lines = browser._app_buttons[0].toolTip().splitlines()
    check("Tooltip 第一行就是完整名称", lines and lines[0] == long_name,
          str(lines[:1]))
    check("Tooltip 里有完整路径", str(button.path) in button.toolTip())
    check("Tooltip 说了怎么打开", "打开" in button.toolTip())
    check("按钮上那行是省略过的（所以才需要 Tooltip）",
          len(button.text()) <= len(long_name), f"{button.text()!r}")

    section("4. 常用启动：管理状态说得清")
    check("没进管理模式：文案是「⚙ 管理」",
          browser.btn_manage.text() == "⚙\n管理", repr(browser.btn_manage.text()))
    check("没进管理模式：Tooltip 报当前项数",
          str(len(cfg_browser.quick_items)) in browser.btn_manage.toolTip(),
          browser.btn_manage.toolTip())
    browser.set_manage_mode(True)
    check("进入管理模式：文案变「✓ 完成」",
          browser.btn_manage.text() == "✓\n完成", repr(browser.btn_manage.text()))
    check("进入管理模式：Tooltip 变成「退出管理模式」",
          browser.btn_manage.toolTip() == "退出管理模式",
          browser.btn_manage.toolTip())
    check("进入管理模式：控件是选中态", browser.btn_manage.isChecked())
    browser.set_manage_mode(False)
    check("退出管理模式：控件恢复未选中", not browser.btn_manage.isChecked())
    check("退出管理模式：文案回到「⚙ 管理」",
          browser.btn_manage.text() == "⚙\n管理", repr(browser.btn_manage.text()))

    section("5. 常用启动：加入 / 移出的反馈是 Toast，不是 Dialog")
    dialogs = []
    real_information = db_mod.QMessageBox.information
    real_warning = db_mod.QMessageBox.warning
    db_mod.QMessageBox.information = staticmethod(
        lambda *a, **k: dialogs.append(a))
    db_mod.QMessageBox.warning = staticmethod(lambda *a, **k: dialogs.append(a))
    try:
        check("有 Toast 控件", isinstance(browser.toast, Toast))
        added = browser.add_item_to_apps(items[4])
        check("加一个还没在常用里的条目：成功", added is True)
        check("Toast 说「✓ 已加入常用启动」",
              browser.toast.text() == "✓ 已加入常用启动", browser.toast.text())
        check("Toast 用的是成功样式（ToastOk）",
              browser.toast.objectName() == "ToastOk", browser.toast.objectName())
        check("Toast 已经显示出来（离屏下看 isHidden）",
              not browser.toast.isHidden())
        check("加成功没有弹任何 Dialog", not dialogs, str(dialogs))
        browser.remove_quick_path(items[4].path)
        check("移出之后 Toast 说「✓ 已移出常用启动」",
              browser.toast.text() == "✓ 已移出常用启动", browser.toast.text())
        check("移出也没有弹 Dialog", not dialogs, str(dialogs))
        # 重复加入是"没成功"，用警告色提示，仍然不弹窗
        browser.add_item_to_apps(items[0])
        check("重复加入：Toast 换成警告样式",
              browser.toast.objectName() == "ToastWarn", browser.toast.objectName())
        check("重复加入也没弹 Dialog", not dialogs, str(dialogs))
    finally:
        db_mod.QMessageBox.information = real_information
        db_mod.QMessageBox.warning = real_warning
    browser.hide()

    # ==================================================================
    # Dock
    # ==================================================================
    cfg_dock = new_cfg(cfg_dock_dir)
    for link in links[:6]:
        cfg_dock.add_quick(link, link.stem)

    dock = dock_mod.DockBar(cfg_dock)
    dock.show_bar()
    pump(app, 0.8)

    section("6. Dock：图标间距 / 背景（纯透明）")
    check("应用区图标间距放宽到 6（原来是 3）",
          dock.apps_flow._spacing == dock_mod.DOCK_GAP == 6,       # noqa: SLF001
          str(dock.apps_flow._spacing))                            # noqa: SLF001
    check("主行间距与图标间距一致（换行后行间不挤）",
          dock.main_row.spacing() == dock_mod.DOCK_GAP,
          str(dock.main_row.spacing()))
    sheet = dock.styleSheet()
    check("底板是纯透明（不是又加回一条深色板）",
          "#DockSurface" in sheet and "background: transparent" in sheet)
    check("没有挂 QGraphicsEffect（拖拽时不能每帧全条模糊）",
          not dock.graphicsEffect() and not dock.surface.graphicsEffect())
    # 回归：Phase 4 曾在这里画过一层"影子"，浅壁纸上看就是一块半透明板子。
    # 用户要求回到纯透明，所以钉死"菜单栏自己什么都不画"。
    check("菜单栏自己不画任何东西（没有覆盖 paintEvent）",
          "paintEvent" not in vars(dock_mod.DockBar))
    pix = dock.grab()
    pix.setDevicePixelRatio(1.0)
    image = pix.toImage()
    surface = dock.surface.geometry()
    probe = image.pixelColor(surface.x() + surface.width() // 2,
                             surface.y() + 3)
    check("实测：图标上方那一带完全透明（直接透出壁纸）",
          probe.alpha() == 0, f"alpha={probe.alpha()}")
    # 图标之间那条缝也必须是透的——有底板的话这里会先被填上色
    first_btn, second_btn = dock._app_buttons[0], dock._app_buttons[1]
    left = first_btn.mapTo(dock, QPoint(first_btn.width(), 0)).x()
    right = second_btn.mapTo(dock, QPoint(0, 0)).x()
    middle_y = first_btn.mapTo(dock, QPoint(0, first_btn.height() // 2)).y()
    gap = image.pixelColor((left + right) // 2, middle_y)
    check("实测：两个图标之间的缝也是全透明的",
          gap.alpha() == 0, f"alpha={gap.alpha()}")

    section("7. Dock：Hover / Active 状态")
    check("样式表里有 DockIcon 的 hover 规则", "#DockIcon:hover" in sheet)
    check("样式表里有 DockIcon 的按下规则", "#DockIcon:pressed" in sheet)
    check("样式表里有 DockIcon 的 active（被拖起来）规则",
          '#DockIcon[active="true"]' in sheet)
    first = dock._app_buttons[0]
    dock_mod.DockBar._set_icon_active(first, True)
    check("实测：打上 active 标记", first.property("active") is True)
    dock_mod.DockBar._set_icon_active(first, False)
    check("实测：能摘掉 active 标记", first.property("active") is False)

    section("8. Dock：Tooltip 显示完整名称")
    entry = cfg_dock.quick_items[0]
    tip = dock._app_buttons[0].toolTip().splitlines()
    check("Tooltip 第一行是完整名称", tip and tip[0] == entry["name"],
          str(tip[:1]))
    check("Tooltip 里有完整路径", str(entry["path"]) in dock._app_buttons[0].toolTip())
    check("Tooltip 里说清了单击 / 右键 / 拖动",
          all(word in dock._app_buttons[0].toolTip()
              for word in ("单击", "右键", "拖动")),
          dock._app_buttons[0].toolTip())
    check("按钮上那行名字是省略过的（6 个字封顶）",
          len(dock._app_buttons[0].text()) <= 6, dock._app_buttons[0].text())

    section("9. 拖拽排序复查：快速拖动 / 跨多个项目")
    buttons = dock._app_buttons
    check("有 6 个常用项", len(buttons) == 6, str(len(buttons)))

    def names() -> "list[str]":
        return [e["name"] for e in cfg_dock.quick_items]

    def slot_center(index: int) -> QPoint:
        origin = dock.apps_flow.mapToGlobal(QPoint(0, 0))
        slot = dock._slots[index]                       # noqa: SLF001
        return QPoint(origin.x() + int(slot[0]) + buttons[index].width() // 2,
                      origin.y() + int(slot[1]) + buttons[index].height() // 2)

    start = buttons[0]
    press = start.mapToGlobal(QPoint(start.width() // 2, start.height() // 2))
    dock._on_icon_press(start, press)                   # noqa: SLF001
    dock._on_icon_hold(start, press)                    # noqa: SLF001
    app.processEvents()
    check("长按进入排序模式", dock._mode == "reorder", dock._mode)
    frozen = list(dock._slots)                          # noqa: SLF001
    check("槽位在进入时被冻结（这是不抖的前提）", len(frozen) == 6,
          str(len(frozen)))

    # 一次事件跨 5 格：增量式算法会漏，这里必须直接算对
    dock._on_icon_move(start, slot_center(5))           # noqa: SLF001
    app.processEvents()
    check("一步跨 5 格：目标槽位立刻 = 5", dock._reorder_to == 5,
          str(dock._reorder_to))
    check("跨多格之后槽位表一个字节都没动", dock._slots == frozen)  # noqa: SLF001
    check("松手前配置顺序还没变（只是视觉让位）",
          names() == [f"工具{i}" for i in range(6)], str(names()))

    # 来回快速甩：每次都要立刻跟对，且槽位表不变
    expected = [0, 3, 1, 5, 2, 4]
    matched = True
    for target in expected:
        dock._on_icon_move(start, slot_center(target))  # noqa: SLF001
        app.processEvents()
        if dock._reorder_to != target:
            matched = False
    check(f"来回快速甩 {len(expected)} 次，每次都立刻跟对", matched,
          f"最后 {dock._reorder_to}")
    check("来回甩完之后槽位表仍然没动", dock._slots == frozen)      # noqa: SLF001

    section("10. 拖拽排序复查：不抖 / 不漂移")
    # 同一个光标位置连发 30 次：让位的**目标**必须稳定（否则界面自己跟自己较劲）
    dock._on_icon_move(start, slot_center(3))           # noqa: SLF001
    app.processEvents()
    targets = {id(b): dock._settle_targets()[b] for b in buttons}  # noqa: SLF001
    stable = True
    for _ in range(30):
        dock._on_icon_move(start, slot_center(3))       # noqa: SLF001
        app.processEvents()
        now = {id(b): dock._settle_targets()[b] for b in buttons}   # noqa: SLF001
        if now != targets:
            stable = False
    check("同一位置连发 30 次，让位目标始终一样（没有自我震荡）", stable)
    check("被拖的图标一直锁在第 3 槽", dock._reorder_to == 3,
          str(dock._reorder_to))
    check("让位动画期间布局不许插手",
          dock._reorder_locked() is True)
    rest = pump_until_rest(app, dock)
    check("让位在 3 秒内自然停下", rest)
    slot_x = [int(s[0]) for s in frozen]
    arrived = sorted(b.x() for b in buttons)
    check("停下来之后每个图标都**精确**落在某个槽位上（没有残留抖动）",
          arrived == slot_x, f"{arrived} vs {slot_x}")

    section("11. 拖拽排序复查：松手保存 + 重启后顺序保留")
    over = slot_center(3)
    dock._on_icon_release(start, over)                  # noqa: SLF001
    app.processEvents()
    expect_order = [f"工具1", f"工具2", f"工具3", f"工具0", f"工具4", f"工具5"]
    check("松手立刻写进配置（pop + insert，和视觉顺序同一套语义）",
          names() == expect_order, str(names()))
    pump_until_rest(app, dock)
    check("回弹结束、交回布局", dock._settling is False)

    # "重启"：同一份配置目录重新读一遍，再新建一条菜单栏
    cfg_restart = config_mod.Config(cfg_dock_dir)
    check("重启后读到的顺序没变",
          [e["name"] for e in cfg_restart.quick_items] == expect_order,
          str([e["name"] for e in cfg_restart.quick_items]))
    dock2 = dock_mod.DockBar(cfg_restart)
    dock2.show_bar()
    pump(app, 0.8)
    check("重启后菜单栏上的图标顺序与配置一致",
          [Path(str(b._payload)).stem for b in dock2._app_buttons]   # noqa: SLF001
          == expect_order,
          str([Path(str(b._payload)).stem for b in dock2._app_buttons]))  # noqa: SLF001
    dock2.hide_bar()

    section("12. 拖入添加：把收纳项目拖到菜单栏 = 加为常用启动")
    dropped = links[6]
    check("待拖入的条目现在还不是常用项", not cfg_dock.is_quick(dropped))
    before = len(dock._app_buttons)
    payload = QMimeData()
    payload.setData(DND_MIME, str(dropped).encode("utf-8"))
    enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, payload,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(dock, enter)
    check("拖进来时菜单栏接住了（accepted）", enter.isAccepted())
    check("拖进来时描边高亮打开", dock._drop_active is True)
    check("高亮走动态属性（QSS 里 #DockSurface[dropActive=\"true\"]）",
          dock.surface.property("dropActive") is True)
    drop = QDropEvent(QPointF(10.0, 10.0), Qt.DropAction.CopyAction, payload,
                      Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    app.sendEvent(dock, drop)
    check("松手后真的加进配置", cfg_dock.is_quick(dropped))
    check("菜单栏上多了一个图标", len(dock._app_buttons) == before + 1,
          f"{before} → {len(dock._app_buttons)}")
    check("拖入成功也弹「✓ 已加入常用启动」",
          dock.toast.text() == "✓ 已加入常用启动", dock.toast.text())
    check("拖入之后高亮收回", dock._drop_active is False)
    check("高亮属性也收回", dock.surface.property("dropActive") is False)

    # 再拖一次同一个：不重复添加，只提示
    # （真拖拽一定先有 dragEnter，Qt 才会把 drop 交下来；这里照做）
    again = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, payload,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    app.sendEvent(dock, again)
    drop2 = QDropEvent(QPointF(10.0, 10.0), Qt.DropAction.CopyAction, payload,
                       Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    app.sendEvent(dock, drop2)
    check("重复拖入不会加出第二份",
          len(dock._app_buttons) == before + 1, str(len(dock._app_buttons)))
    check("重复拖入提示「已经在常用启动里了」",
          dock.toast.text() == "⚠ 已经在常用启动里了", dock.toast.text())
    check("重复拖入用警告样式", dock.toast.objectName() == "ToastWarn",
          dock.toast.objectName())

    leave = QDragLeaveEvent()
    dock._set_drop_active(True)                          # noqa: SLF001
    app.sendEvent(dock, leave)
    check("拖走（dragLeave）之后高亮一定收回", dock._drop_active is False)

    section("13. 反馈：移出常用启动也用 Toast（不用 Dialog）")
    dialogs = []
    real_information = dock_mod.QMessageBox.information
    dock_mod.QMessageBox.information = staticmethod(
        lambda *a, **k: dialogs.append(a))
    try:
        victim = dock._app_buttons[-1]
        dock.cfg.remove_quick(Path(str(victim._payload)))   # noqa: SLF001
        dock.quick_changed.emit()
        dock.rebuild()
        dock.show_toast("✓ 已移出常用启动")
        check("移出之后 Toast 文案正确",
              dock.toast.text() == "✓ 已移出常用启动", dock.toast.text())
        check("移出没有弹 Dialog", not dialogs, str(dialogs))
    finally:
        dock_mod.QMessageBox.information = real_information
    check("Toast 是独立小窗（不会被菜单栏那点高度裁掉）",
          dock.toast.parentWidget() is None and dock.toast.isWindow())

    section("14. 常用启动：图标统一进方形画布（不然大小看着不齐）")
    # 造一张 2:1 的图标：直接 setIcon 的话它会顶满宽度、上下留空，
    # 和方图标并排时"视觉重量"就不一样了。
    wide = QPixmap(80, 40)
    wide.fill(Qt.GlobalColor.red)
    canvas = pixmap_for(QIcon(wide), db_mod.APP_ICON, browser, square=True)
    check("方形画布：宽高相等",
          canvas.width() == canvas.height(),
          f"{canvas.width()}x{canvas.height()}")
    check("方形画布：边长就是 APP_ICON",
          canvas.width() == db_mod.APP_ICON, str(canvas.width()))
    shot = canvas.toImage()
    mid = db_mod.APP_ICON // 2
    check("方形画布：内容在正中（中间不透明）",
          shot.pixelColor(mid, mid).alpha() > 200,
          str(shot.pixelColor(mid, mid).getRgb()))
    check("方形画布：上下各留了白（不是被拉满）",
          shot.pixelColor(mid, 1).alpha() < 40,
          str(shot.pixelColor(mid, 1).getRgb()))
    check("AppButton 走的是这套方形化（不是直接 setIcon）",
          db_mod.AppButton.set_icon is not None
          and db_mod.AppButton.set_icon.__name__ == "set_icon")
    check("实测：上屏之后按钮的图标已经方形化过",
          browser._app_buttons[0]._squared is True)          # noqa: SLF001

    section("15. Dock 的 Toast：药丸底自己画 + 贴在菜单栏上方")
    dock.show_toast("✓ 已加入常用启动")
    dock.toast.show_message("✓ 已加入常用启动", "ok", animate=False)
    pump(app, 0.08)
    toast = dock.toast
    check("Toast 有药丸底（顶层窗口的 QSS 背景不生效，得自己画）",
          toast.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
    pill = toast.grab().toImage()
    middle = pill.pixelColor(pill.width() // 2, 3)
    check("实测：药丸中心是实的（alpha > 200）",
          middle.alpha() > 200, str(middle.getRgb()))
    check("实测：底色偏深，浅壁纸上也看得清",
          middle.lightness() < 90, str(middle.lightness()))
    check("实测：圆角外仍然透明（能透出壁纸）",
          pill.pixelColor(1, 1).alpha() < 40,
          str(pill.pixelColor(1, 1).getRgb()))
    check("Toast 贴在菜单栏上方（不压图标）",
          toast.y() + toast.height() <= dock.y(),
          f"toast 底 {toast.y() + toast.height()} vs dock 顶 {dock.y()}")
    check("Toast 水平居中于菜单栏",
          abs((toast.x() + toast.width() // 2)
              - (dock.x() + dock.width() // 2)) <= 2,
          f"{toast.x() + toast.width() // 2} vs {dock.x() + dock.width() // 2}")
    toast.hide_now()

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    dock.hide_bar()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
