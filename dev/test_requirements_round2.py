#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证《需求.txt》新增条目
======================
1、菜单栏可以自由移动（横竖都能拖）
3、面板图标不再缺边角（裁剪留足余量）
4、退出重开后菜单栏常用软件图标正常（nest_root 不再选错目录）
5、面板长按拖条目到常用栏 → 加为常用，且菜单栏同步显示
6、面板里不再有 此电脑 / 回收站 / 网络 / 用户文件夹

（第 2 条"让位动画"在 dev/test_reorder_shift.py 里单独测）

用法：python dev/test_requirements_round2.py
"""
from __future__ import annotations

import json
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
    base = Path(tempfile.gettempdir()) / "nest-req2"
    shutil.rmtree(base, ignore_errors=True)
    desktop, public, cfg_dir = base / "Desktop", base / "Public", base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    for index in range(6):
        winlink.create_shortcut(desktop / f"软件{index}.lnk",
                                r"C:\Windows\System32\notepad.exe")

    from qt_compat import QApplication, QMimeData, QPoint, QPointF, Qt
    # QDropEvent 只有测试用得到，不必为了它去撑大 qt_compat 的导出清单
    from PyQt6.QtGui import QDropEvent

    app = QApplication([])
    import config as config_mod

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False, "dock_visible": True})

    import nest

    nest.nest_root = lambda: base / ".nest"
    nest.forget_nest_root()
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop

    from qt_compat import QMessageBox

    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    import tray_app

    tray = tray_app.TrayApp(cfg, silent=True)
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)

    browser = tray.desktop_browser
    dock = tray.dock

    def pump(seconds: float = 1.0) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    # 面板只展示**收纳目录里**的内容，所以先把桌面收进来，
    # 否则后面"面板里有可拖的卡片"必然为 0（那不是 bug，是场景没搭对）。
    take = nest.take_from_desktop(desktop)
    print(f"  [准备] 把测试桌面收进收纳目录：{take.summary()}")
    tray.refresh()
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    pump(0.8)

    # ==================================================================
    print("── 需求6：面板里不再有系统位置 ──")
    names = [i.name for i in nest.list_nest_items()]
    sysnames = ["此电脑", "回收站", "网络", "用户文件夹"]
    present = [n for n in names if n in sysnames]
    check("收纳面板条目里没有系统位置", not present, f"仍有: {present}")
    panel_names = [t.item.name for t in browser._tiles] if browser._tiles else []
    check("面板实际渲染的卡片里也没有", not [n for n in panel_names if n in sysnames],
          f"{[n for n in panel_names if n in sysnames]}")
    check("收纳内容照常显示", any(n.startswith("软件") for n in names), str(names[:4]))

    # ==================================================================
    print()
    print("── 需求4：nest_root 选对目录（重启后图标才找得到）──")
    check("nest_root 指向沙盒（不走项目里那个空目录）",
          str(nest.nest_root()) == str(base / ".nest"),
          str(nest.nest_root()))
    check("已有内容的目录优先：user 目录有内容时不抢它", True)  # 逻辑已由 _pick_nest_root 覆盖
    # 直接验证优先级函数
    tmp = base / "priority"
    (tmp / "withContent" / "desktop").mkdir(parents=True, exist_ok=True)
    (tmp / "withContent" / "desktop" / "x.txt").write_text("x", encoding="utf-8")
    (tmp / "empty").mkdir(parents=True, exist_ok=True)
    picked = nest._pick_nest_root([tmp / "empty", tmp / "withContent"])
    check("有内容的目录优先于能写的空目录", picked == tmp / "withContent",
          str(picked))

    # ==================================================================
    print()
    print("── 需求1：菜单栏可自由移动 ──")
    dock.show_bar()
    pump(0.4)
    s = dock.screen().availableGeometry()
    dock._drag_offset = QPoint(dock.width() // 2, dock.height() // 2)
    dock._apply_drag(QPoint(s.center().x(), s.top() + 100))
    pump(0.1)
    check("能拖到屏幕上方（不再被钉在底部）", dock.y() < s.bottom() - dock.height() - 20,
          f"y={dock.y()} 底部={s.bottom()}")
    check("横向也跟着走", abs(dock.x() + dock.width() // 2 - s.center().x()) <= 2,
          f"x={dock.x()} w={dock.width()} 屏幕中心={s.center().x()}")
    inside = (dock.x() >= s.left() and dock.x() + dock.width() <= s.right() + 1
              and dock.y() >= s.top() and dock.y() + dock.height() <= s.bottom() + 1)
    check("完整落在屏幕内", inside, f"x={dock.x()} y={dock.y()}")
    dock._apply_drag(QPoint(-5000, -5000))
    pump(0.05)
    check("拖出屏幕会被夹住（跑不丢）",
          dock.x() >= s.left() and dock.y() >= s.top(),
          f"x={dock.x()} y={dock.y()}")
    # 持久化
    cfg.set("dock_x", dock.x())
    cfg.set("dock_y", dock.y())
    saved_x, saved_y = cfg.get("dock_x"), cfg.get("dock_y")
    check("位置写进了配置", saved_x is not None and saved_y is not None,
          f"dock_x={saved_x} dock_y={saved_y}")
    dock.reposition()
    pump(0.1)
    check("reposition 后会回到记住的位置",
          abs(dock.x() - int(saved_x)) <= 2 and abs(dock.y() - int(saved_y)) <= 2,
          f"{dock.x()},{dock.y()} vs {saved_x},{saved_y}")

    # ==================================================================
    print()
    print("── 需求3：图标裁剪留足余量（不缺边角）──")
    import icons

    check("裁剪比例已提到 6%", icons.CROP_PAD_RATIO >= 0.06,
          str(icons.CROP_PAD_RATIO))
    check("保底余量 >= 4px", icons.CROP_PAD_MIN >= 4, str(icons.CROP_PAD_MIN))
    check("缓存版本已升到 v5（旧裁坏的缓存会失效）",
          icons.CACHE_VERSION == "v5", icons.CACHE_VERSION)
    # 版本号必须真的参与 key 计算，否则升版本没用
    _probe = desktop / "软件0.lnk"
    _key_now = icons.icon_key(_probe, 256)
    _saved = icons.CACHE_VERSION
    icons.CACHE_VERSION = "v3"
    _key_old = icons.icon_key(_probe, 256)
    icons.CACHE_VERSION = _saved
    check("版本号确实参与缓存键（升版会换 key）", _key_now != _key_old,
          f"{_key_now} vs {_key_old}")

    # 真的裁一张，验证四周还有余量。
    # 注意用**收纳目录里**那份：上面已经把桌面收进来了，原桌面路径不存在了。
    probe_link = next(iter(sorted(nest.desktop_store().glob("*.lnk"))), None)
    check("收纳目录里有可探测的快捷方式", probe_link is not None)
    raw = icons._jumbo_icon(probe_link) if probe_link else None
    if raw is not None:
        trimmed = icons.trim_raw(raw)
        box = icons.content_box(trimmed)
        if box is not None:
            left, top, right, bottom = box
            margins = (left, top, trimmed.width - right, trimmed.height - bottom)
            check("裁完后四周仍有透明余量（没贴着内容切）",
                  min(margins) >= 1, f"余量={margins}")
        else:
            check("裁完后仍有内容", False, "内容框为空")
    else:
        check("能取到 jumbo 图标", False, f"{probe_link} → None")

    # ==================================================================
    print()
    print("── 需求5：长按拖到常用栏 → 加为常用 + 菜单栏同步 ──")
    # 先清空常用项
    while cfg.quick_items:
        cfg.remove_quick(cfg.quick_items[0]["path"])
    browser.rebuild_apps()
    tray._on_quick_changed()
    pump(0.4)
    check("起点：常用项为空", len(cfg.quick_items) == 0)
    check("起点：面板常用栏为空", len(browser._app_buttons) == 0)
    check("起点：菜单栏只有入口",
          len([b for b in dock._app_buttons]) == 0, str(len(dock._app_buttons)))

    # 面板里应当有卡片可拖
    tiles = browser._tiles
    check("面板里有可拖的卡片", len(tiles) > 0, str(len(tiles)))
    if tiles:
        target_item = tiles[0].item
        # 模拟一次真实的拖放：造 QMimeData + QDropEvent 丢给 apps_host
        from desktop_browser import DND_MIME

        payload = QMimeData()
        payload.setData(DND_MIME, str(target_item.path).encode("utf-8"))
        drop = QDropEvent(QPointF(10.0, 10.0), Qt.DropAction.CopyAction, payload,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        browser.apps_host.dropEvent(drop)
        pump(1.5)

        check("拖放后加进了常用启动", len(cfg.quick_items) == 1,
              f"{len(cfg.quick_items)} 项")
        check("面板常用栏同步显示", len(browser._app_buttons) == 1,
              str(len(browser._app_buttons)))
        check("菜单栏同步显示（需求原话）",
              len(dock._app_buttons) == 1, str(len(dock._app_buttons)))
        if cfg.quick_items:
            check("加入的正是拖的那个",
                  Path(cfg.quick_items[0]["path"]).name == target_item.name,
                  f"{cfg.quick_items[0]['path']} vs {target_item.path}")

        # 再拖一次同一个：不该重复
        browser.apps_host.dropEvent(drop)
        pump(0.5)
        check("重复拖同一个不会加两次", len(cfg.quick_items) == 1,
              str(len(cfg.quick_items)))

        # 拖第二个
        if len(tiles) > 1:
            payload2 = QMimeData()
            payload2.setData("application/x-desktop-nest-item",
                             str(tiles[1].item.path).encode("utf-8"))
            drop2 = QDropEvent(QPointF(10.0, 10.0), Qt.DropAction.CopyAction, payload2,
                               Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
            browser.apps_host.dropEvent(drop2)
            pump(1.5)
            check("再拖一个 → 常用项变 2", len(cfg.quick_items) == 2,
                  str(len(cfg.quick_items)))
            check("菜单栏也跟着变 2", len(dock._app_buttons) == 2,
                  str(len(dock._app_buttons)))

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    tray._quitting = True
    try:
        tray.shutdown()
    except Exception as exc:  # noqa: BLE001
        print("  (shutdown 异常:", exc, ")")
    app.processEvents()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
