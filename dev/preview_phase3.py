#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 预览图
==============
把主面板渲染成 PNG，用来看"管理页面 + 操作历史"改完之后的实际观感：
状态色、路径降权、历史表五列、行距、底部按钮层级、撤销 Toast。

只读：用的都是桌面上真实存在的快捷方式（取图标），**不移动任何文件**。

用法：python dev/preview_phase3.py
输出：%TEMP%/desktop-nest-preview/phase3-*.png
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

from qt_compat import (  # noqa: E402
    QApplication, QColor, QEventLoop, QImage, QLinearGradient, QPainter, QTimer,
)

OUT = Path(tempfile.gettempdir()) / "desktop-nest-preview"


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shot(panel, name: str) -> None:
    """抓图并垫一层深色背景。

    卡片是**半透明**的（真机上透出来的是 DWM 磨砂），直接存 PNG 的话
    透明区域会被看图器垫成白色，整块面板看着像蒙了层灰——垫一张深色
    渐变才接近实际观感。
    """
    pix = panel.grab()
    # 高分屏下 grab() 的像素比不是 1，直接 drawPixmap 会按逻辑尺寸缩着画，
    # 看着像"面板只占了画布一角 + 整体发虚"。按物理像素 1:1 铺开。
    pix.setDevicePixelRatio(1.0)
    canvas = QImage(pix.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(canvas)
    grad = QLinearGradient(0, 0, canvas.width(), canvas.height())
    grad.setColorAt(0.0, QColor("#1C2430"))
    grad.setColorAt(0.45, QColor("#2B2333"))
    grad.setColorAt(1.0, QColor("#131A22"))
    painter.fillRect(canvas.rect(), grad)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    canvas.save(str(OUT / name))


def demo_items(base: Path):
    import engine

    names = ["Google Chrome.lnk", "Steam.lnk", "KOOK.lnk", "Apifox.lnk",
             "Bandizip.lnk", "FlClash.lnk", "MEGAsync.lnk"]
    desktop_dir = Path(os.path.expanduser("~")) / "Desktop"
    items = []
    for name in names:
        path = desktop_dir / name
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(engine.RepoItem(path, name, False, "shortcut",
                                     stat.st_size, stat.st_mtime))
    if items:
        return items
    for name, kind, size in (("季度报告.docx", "file", 240_000),
                             ("预算表.xlsx", "file", 88_000),
                             ("产品路线图.pptx", "file", 1_800_000),
                             ("截图.png", "file", 420_000)):
        items.append(engine.RepoItem(base / name, name, False, kind, size,
                                     1_760_000_000))
    return items


def demo_history(store: Path) -> "list[dict]":
    """三条像样的流水（时间倒序），说明列才有东西可显示。"""
    now = time.time()
    plans = [
        ("take", ["季度报告.docx", "预算表.xlsx", "产品路线图.pptx"], 0),
        ("restore", ["会议纪要.md", "截图.png"], 3600 * 5),
        ("take", ["资料夹A", "项目B", "简历.pdf", "单片机入门资料"], 3600 * 26),
    ]
    records = []
    for action, names, back in plans:
        moves = [[str(Path(r"C:\Users\me\Desktop") / n), str(store / n)]
                 for n in names]
        records.append({"time": now - back, "action": action,
                        "count": len(names), "moves": moves})
    return records


def main() -> int:
    app = QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)

    base = Path(tempfile.gettempdir()) / "nest-preview-phase3"
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.json").write_text(
        json.dumps({"desktop": str(Path(os.path.expanduser("~")) / "Desktop"),
                    "quick_items": []}),
        encoding="utf-8")

    import config as config_mod
    import nest
    from panel import MainPanel

    nest.nest_root = lambda: base / ".nest"
    (base / ".nest" / "desktop").mkdir(parents=True, exist_ok=True)

    cfg = config_mod.Config(str(base))
    items = demo_items(base)
    history = demo_history(base / ".nest" / "desktop")

    panel = MainPanel(cfg)
    panel.resize(940, 680)
    panel.update_overview(items=items, nest_items=18, desktop_pending=3,
                          folders=2, shortcuts=4, history=history)
    panel.show()
    wait(260)

    # 1) 面板内容 Tab（表格撑满 + 表头层级）
    panel.tabs.setCurrentIndex(0)
    wait(140)
    shot(panel, "phase3-面板内容.png")

    # 2) 操作历史 Tab + 选中一行（撤销按钮 enabled）
    panel.tabs.setCurrentIndex(1)
    wait(140)
    panel.history_tree.topLevelItem(0).setSelected(True)
    wait(80)
    shot(panel, "phase3-操作历史.png")

    # 3) 撤销成功的 Toast（关掉淡入，截图才抓得到实色）
    panel.show_toast("✓ 已撤销\n3 个项目已恢复到原来的位置", "ok")
    panel.toast.show_message("✓ 已撤销\n3 个项目已恢复到原来的位置", "ok",
                             animate=False)
    wait(120)
    shot(panel, "phase3-撤销Toast.png")

    # 4) 桌面待收纳 = 0 时的状态（「✓ 桌面已整理」）
    panel.tabs.setCurrentIndex(0)
    panel.refresh_cards(nest_items=18, desktop_pending=0,
                        folders=2, shortcuts=4)
    panel.toast.hide_now()
    wait(140)
    shot(panel, "phase3-已整理状态.png")

    panel.hide()
    print("已保存到：", OUT)
    for path in sorted(OUT.glob("phase3-*.png")):
        print("  ", path.name, path.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
