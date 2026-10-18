#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 5 预览图
==============
把主面板在「正在收纳 / 部分失败 / 全部成功」三种状态下的样子渲染成 PNG：
进度条、失败明细、[重试][跳过]、Toast 的 ✓ / ⚠ / ×。

只读：沙盒里造几个文件，**不移动任何真实文件**。

⚠️ 不能用 offscreen：离屏平台拿不到系统中文字形，图里会全是"□□□□"。
   所以这里显式把 QT_QPA_PLATFORM 清掉，走原生平台。

用法：python dev/preview_phase5.py
输出：%TEMP%/desktop-nest-preview/phase5-*.png
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))
os.environ.pop("QT_QPA_PLATFORM", None)

from qt_compat import (  # noqa: E402
    QApplication, QColor, QEventLoop, QImage, QLinearGradient, QPainter, QTimer,
)

OUT = Path(tempfile.gettempdir()) / "desktop-nest-preview"


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shot(widget, name: str) -> None:
    """抓图并垫一层深色背景（卡片是半透明的，垫白底会整块发灰）。"""
    pix = widget.grab()
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
    print("  ", name, canvas.width(), "x", canvas.height())


class _Result:
    """和 `nest.MoveResult` 同形的假结果，只为渲染。"""

    def __init__(self, moved=0, failed=None, skipped=None):
        self.moved = moved
        self.failed = failed or []
        self.skipped = skipped or []
        self.cancelled = False
        self.duration = 0.0
        self.moves = []


def main() -> int:
    app = QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)

    base = Path(tempfile.gettempdir()) / "nest-preview-phase5"
    base.mkdir(parents=True, exist_ok=True)
    desktop, cfg_dir, data = base / "Desktop", base / "cfg", base / "data"
    for folder in (desktop, cfg_dir, data):
        folder.mkdir(parents=True, exist_ok=True)
    for index in range(8):
        (desktop / f"示例文件{index}.txt").write_text("x", encoding="utf-8")

    import config as config_mod

    config_mod._DATA_DIR = data
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "PublicDesktop"
    (base / "PublicDesktop").mkdir(parents=True, exist_ok=True)

    import nest

    nest.nest_root = lambda: base / ".nest"
    nest.ensure_dirs()

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop)})

    from panel import MainPanel

    panel = MainPanel(cfg)
    panel.resize(940, 700)
    panel.show()
    wait(500)

    # 1) 正在收纳：进度条 + 12 / 60
    panel.refresh_cards(nest_items=48, desktop_pending=12,
                        folders=3, shortcuts=9)
    panel.begin_operation("正在收纳…", 60)
    panel.update_progress(12, 60, "季度报告.docx")
    wait(200)
    shot(panel, "phase5-正在收纳.png")

    # 2) 部分失败：成功 58 · 失败 2 · 跳过 1，展开明细
    panel.begin_operation("正在还原…", 60)
    panel.update_progress(60, 60, "预算表.xlsx")
    wait(120)
    panel.finish_operation(_Result(
        moved=58,
        failed=[("Adobe Premiere Pro 2023.lnk", "被占用或无权限，请关闭正在使用它的程序"),
                ("预算表.xlsx", "权限不足")],
        skipped=[("旧稿.docx", "已跳过（桌面已有同名文件）")]), "restore")
    panel.banner.toggle_detail()
    wait(220)
    shot(panel, "phase5-部分失败.png")

    # 3) 全部成功：状态条收起，只剩一颗 Toast
    panel.clear_banner()
    panel.begin_operation("正在收纳…", 60)
    panel.update_progress(60, 60, "最后一个.txt")
    panel.finish_operation(_Result(moved=60), "take")
    wait(260)
    shot(panel, "phase5-已收纳.png")

    panel.hide()
    print("已保存到：", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
