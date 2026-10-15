#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证「常用软件」这几件事：图标能否加载、增删后 UI 是否同步、删除后是否留空白
=====================================================================
* 1~6 节：收纳面板里那排「常用启动」
* 7~8 节：**底部菜单栏（Dock）** —— 加新项后旧图标不能消失、删项后尺寸要缩回去
* 9 节：  菜单栏底板是**纯透明**的，只留图标浮在桌面上

用法：python dev/test_quick_apps.py
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
    base = Path(tempfile.gettempdir()) / "nest-quick-apps"
    shutil.rmtree(base, ignore_errors=True)
    desktop, public, cfg_dir = base / "Desktop", base / "Public", base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    exes = [
        r"C:\Windows\System32\notepad.exe",
        r"C:\Windows\System32\calc.exe",
        r"C:\Windows\explorer.exe",
        r"C:\Windows\System32\write.exe",
        r"C:\Windows\System32\mspaint.exe",
    ]
    links = []
    for index, exe in enumerate(exes):
        link = desktop / f"软件{index}.lnk"
        winlink.create_shortcut(link, exe)
        links.append(link)

    from qt_compat import QApplication, QMenu, QMessageBox

    app = QApplication([])
    import config as config_mod

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False})

    import nest

    nest.nest_root = lambda: base / ".nest"
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    import engine

    items = [engine.RepoItem(p, p.stem, False, "shortcut",
                             p.stat().st_size, p.stat().st_mtime) for p in links]

    from desktop_browser import DesktopBrowser

    browser = DesktopBrowser(cfg)
    browser.set_items(items)
    browser.resize(900, 620)
    browser.show()
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)

    def pump(seconds: float = 2.0) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)

    def app_buttons():
        return list(browser._app_buttons)

    def icon_of(button) -> bool:
        icon = button.icon() if hasattr(button, "icon") else None
        return icon is not None and not icon.isNull()

    print("── 1. 一开始没有常用项 ──")
    check("按钮数为 0", len(app_buttons()) == 0, str(len(app_buttons())))

    print()
    print("── 2. 逐个添加 5 个常用软件，图标都要出来 ──")
    for index, item in enumerate(items):
        cfg.add_quick(item.path, item.path.stem)
        browser._rebuild_apps()
        pump(0.6)
    pump(3)
    check("配置 5 项", len(cfg.quick_items) == 5, str(len(cfg.quick_items)))
    check("UI 5 个按钮", len(app_buttons()) == 5, str(len(app_buttons())))
    empty = [b.app_name for b in app_buttons() if not icon_of(b)]
    check("5 个按钮图标都加载出来了", not empty, f"空的: {empty}")
    names_ui = [b.app_name for b in app_buttons()]
    names_cfg = [e["name"] for e in cfg.quick_items]
    check("按钮顺序与配置一致", names_ui == names_cfg, f"{names_ui} vs {names_cfg}")

    print()
    print("── 3. 再加一个新项，旧项的图标不能消失 ──")
    extra = desktop / "新软件.lnk"
    winlink.create_shortcut(extra, r"C:\Windows\System32\cmd.exe")
    cfg.add_quick(extra, "新软件")
    browser._rebuild_apps()
    pump(3)
    empty2 = [b.app_name for b in app_buttons() if not icon_of(b)]
    check("加新项后所有按钮仍有图标（含旧的）", not empty2, f"空的: {empty2}")
    check("按钮数 6", len(app_buttons()) == 6, str(len(app_buttons())))

    print()
    print("── 4. 删除中间一项，后面要自动前移、不留空白 ──")
    victim = cfg.quick_items[2]
    cfg.remove_quick(victim["path"])
    browser._rebuild_apps()
    pump(1)
    names_ui = [b.app_name for b in app_buttons()]
    names_cfg = [e["name"] for e in cfg.quick_items]
    check("按钮数减到 5", len(names_ui) == 5, str(len(names_ui)))
    check("配置与 UI 完全一致（顺序也对）", names_ui == names_cfg,
          f"{names_ui} vs {names_cfg}")
    check("被删项确实不在了", victim["name"] not in names_ui, victim["name"])
    check("删完没有空按钮", all(b.text() for b in app_buttons()))

    # apps_row 里不应该还残留被删按钮的 widget
    widgets = []
    for i in range(browser.apps_row.count()):
        w = browser.apps_row.itemAt(i).widget()
        if w is not None:
            widgets.append(w)
    from desktop_browser import AppButton

    live_apps = [w for w in widgets if isinstance(w, AppButton)]
    check("布局里没有残留的旧按钮 widget", len(live_apps) == 5,
          f"布局里 {len(live_apps)} 个")

    print()
    print("── 5. 删到空，不能报错 ──")
    while cfg.quick_items:
        cfg.remove_quick(cfg.quick_items[0]["path"])
    browser._rebuild_apps()
    pump(0.6)
    check("删空后按钮数 0", len(app_buttons()) == 0, str(len(app_buttons())))
    # 需求：增删两个控件合并成一个「管理」控件，所以这里盯的是它
    check("删空后仍有「管理」控件", browser.btn_manage is not None)
    check("删空后管理控件没被禁用（还能进去加回来）",
          browser.btn_manage.isEnabled())

    print()
    print("── 6. 数据持久化：重新读配置应当还在 ──")
    cfg.add_quick(links[0], "软件0")
    cfg.add_quick(links[1], "软件1")
    cfg.save()
    cfg2 = config_mod.Config(cfg_dir)
    check("重载后仍是 2 项", len(cfg2.quick_items) == 2, str(len(cfg2.quick_items)))
    check("重载后名字正确",
          [e["name"] for e in cfg2.quick_items] == ["软件0", "软件1"],
          str([e["name"] for e in cfg2.quick_items]))

    # ==================================================================
    # 下面三节针对**底部菜单栏（Dock）**，不是收纳面板。
    # 面板那边早就做了「命中缓存直接贴图标」，菜单栏漏了同样的处理，
    # 所以"加个新常用软件，旧的图标全没了"这个 BUG 只出在菜单栏上。
    # ==================================================================
    print()
    print("── 7. 菜单栏：加新常用项后，旧的图标不能消失 ──")
    from dock import DockBar

    dock = DockBar(cfg)
    dock.show_bar()
    pump(0.6)

    while cfg.quick_items:
        cfg.remove_quick(cfg.quick_items[0]["path"])
    for item in items:                          # items = 5 个快捷方式
        cfg.add_quick(item.path, item.path.stem)
    dock.rebuild()
    pump(3)

    def dock_buttons():
        return [b for b in dock._buttons
                if getattr(b, "_payload", None) is not None]

    def real_icon(button) -> bool:
        """按钮上贴的是不是**真图标**（而不是占位字母块）。

        这就是"加新常用项后旧图标消失"的判据：IconLoader 命中缓存时
        `request()` 会直接 return、**不再发 ready 信号**，光靠排队的话
        重建出来的按钮会一直停在 `letter_pixmap` 的占位字母上。
        """
        cached = dock.loader.cached(str(button._payload))
        if cached is None:
            return False
        return (button.icon().pixmap(44, 44).toImage()
                == cached.pixmap(44, 44).toImage())

    check("Dock 上 5 个常用项按钮", len(dock_buttons()) == 5, str(len(dock_buttons())))
    bad = [Path(str(b._payload)).name for b in dock_buttons() if not real_icon(b)]
    check("Dock 5 个按钮贴的都是真图标", not bad, f"占位: {bad}")

    width_5 = dock.width()
    extra2 = desktop / "新软件2.lnk"
    winlink.create_shortcut(extra2, r"C:\Windows\System32\notepad.exe")
    cfg.add_quick(extra2, "新软件2")
    dock.rebuild()
    pump(3)
    bad2 = [Path(str(b._payload)).name for b in dock_buttons() if not real_icon(b)]
    check("Dock 加新项后旧项图标仍在（回归）", not bad2, f"占位: {bad2}")
    check("Dock 加新项后按钮数 6", len(dock_buttons()) == 6, str(len(dock_buttons())))
    width_6 = dock.width()
    check("Dock 加新项后变宽", width_6 > width_5, f"{width_5} -> {width_6}")

    print()
    print("── 8. 菜单栏：删掉常用项后，尺寸要自动缩回去 ──")
    cfg.remove_quick(extra2)
    dock.rebuild()
    pump(1.5)
    check("Dock 删项后按钮数回到 5", len(dock_buttons()) == 5,
          str(len(dock_buttons())))
    check("Dock 删项后宽度自动变小", dock.width() < width_6,
          f"{width_6} -> {dock.width()}")
    check("Dock 删项后宽度回到 5 项时的尺寸", abs(dock.width() - width_5) <= 2,
          f"5项={width_5} 删后={dock.width()}")
    check("Dock 尺寸与 sizeHint 一致（不留空白）",
          abs(dock.width() - dock.sizeHint().width()) <= 2
          and abs(dock.height() - dock.sizeHint().height()) <= 2,
          f"{dock.width()}x{dock.height()} vs "
          f"{dock.sizeHint().width()}x{dock.sizeHint().height()}")

    # 把根因直接钉死：FlowRow 的行列数必须**自己记**，不能读 QGridLayout。
    # QGridLayout 在 takeAt() 之后不会把 columnCount() 收回去（实测删一项后
    # 网格仍报 6 列），sizeHint() 一直按旧列数算，菜单栏就永远缩不回来。
    from dock import FlowRow
    from qt_compat import QToolButton

    flow = FlowRow(spacing=3)
    for _ in range(6):
        box = QToolButton()
        box.setFixedSize(60, 60)
        flow.add_item(box)
    flow.relayout(10_000)
    check("FlowRow 6 项排成 1 行 6 列",
          flow._columns == 6 and flow._rows == 1,
          f"{flow._rows} 行 x {flow._columns} 列")
    # 注意：`setFixedSize()` 只改 min/max，**不改 `sizeHint()`**，
    # 所以期望值要从 FlowRow 自己算出的单格尺寸来推，不能假设 60。
    unit = flow.unit_size().width()
    wide = flow.sizeHint().width()
    check("FlowRow 6 项宽度 = 6*单格 + 5*间距", wide == unit * 6 + 5 * 3,
          f"{wide} vs {unit * 6 + 5 * 3}")
    flow.clear_items()
    for _ in range(4):
        box = QToolButton()
        box.setFixedSize(60, 60)
        flow.add_item(box)
    flow.relayout(10_000)
    narrow = flow.sizeHint().width()
    check("FlowRow 减到 4 项后 sizeHint 跟着缩小（回归根因）",
          narrow == unit * 4 + 3 * 3 and narrow < wide,
          f"{narrow} vs {unit * 4 + 3 * 3}（6 项时 {wide}）")
    check("FlowRow 的最小尺寸也跟着缩（否则 adjustSize 收不回去）",
          flow.minimumSizeHint().width() == narrow,
          str(flow.minimumSizeHint().width()))

    print()
    print("── 9. 菜单栏底板纯透明：只留图标浮在桌面上 ──")
    from qt_compat import Qt

    sheet = dock.styleSheet()
    check("样式表里 #DockSurface 背景透明",
          "#DockSurface" in sheet and "background: transparent" in sheet)
    check("旧的深色圆角底板已移除", "rgba(28, 30, 36, 235)" not in sheet)
    check("Dock 窗口开了半透明背景（能透出桌面）",
          dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
    check("Dock 仍是置顶的常驻工具条",
          bool(dock.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
    check("「桌面整理」控件还在（第一个控件）",
          hasattr(dock, "desktop_btn") and dock.desktop_btn.icon() is not None
          and not dock.desktop_btn.icon().isNull())

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
