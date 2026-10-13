#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给主面板拍一张宣传图（存到 `shots/panel-main.png`）
=================================================
磨砂玻璃是 **DWM 在合成阶段做的**，Qt 自己 `grab()` 出来的图里没有模糊，
所以必须：摆一块高对比背景板 → 真把窗口显示出来 → **截整屏** → 裁掉多余部分。

用法：python dev/shot_panel.py

背景板用柔和的彩色渐变（比彩虹条纹更像真实桌面），这样截图既能看出"透"，
又能看出"糊"。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

from qt_compat import (QApplication, QColor, QLabel, QLinearGradient, QPainter,
                       QPixmap, QRadialGradient, QTimer, QWidget, Qt)

BACK_W, BACK_H = 1400, 860
PANEL_W, PANEL_H = 940, 680
MARGIN = 26


def build_backdrop() -> QWidget:
    """一块柔和的彩色背景板，用来衬托磨砂。"""
    win = QWidget()
    win.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    win.resize(BACK_W, BACK_H)
    win.move(60, 20)

    pm = QPixmap(BACK_W, BACK_H)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 背景要够亮、色块要够硬，否则看不出"透"也看不出"糊"
    base = QLinearGradient(0, 0, BACK_W, BACK_H)
    base.setColorAt(0.0, QColor("#3d6bff"))
    base.setColorAt(0.45, QColor("#b44cff"))
    base.setColorAt(1.0, QColor("#12c2c2"))
    p.fillRect(0, 0, BACK_W, BACK_H, base)

    # 几块高饱和色块 + 白条，模糊之后会明显"化开"
    for i, (color, fx, fy, fw, fh) in enumerate((
            ("#ff3d7f", 0.02, 0.10, 0.22, 0.34),
            ("#ffe14d", 0.30, 0.04, 0.26, 0.20),
            ("#39ff88", 0.62, 0.12, 0.30, 0.30),
            ("#ff9a3d", 0.10, 0.62, 0.28, 0.28),
            ("#5ce1ff", 0.48, 0.68, 0.34, 0.26),
            ("#dfe6f2", 0.78, 0.52, 0.18, 0.40))):
        p.fillRect(int(BACK_W * fx), int(BACK_H * fy),
                   int(BACK_W * fw), int(BACK_H * fh), QColor(color))
    for j in range(0, BACK_H, 90):
        p.fillRect(0, j, BACK_W, 10, QColor(255, 255, 255, 90))

    blobs = [("#ff5f8f", 0.16, 0.22, 420), ("#ffd166", 0.78, 0.18, 380),
             ("#4fd1c5", 0.30, 0.82, 460), ("#7c5cff", 0.86, 0.76, 400),
             ("#ff8a3d", 0.55, 0.45, 340)]
    for color, fx, fy, size in blobs:
        g = QRadialGradient(BACK_W * fx, BACK_H * fy, size)
        c = QColor(color)
        g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 150))
        g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.fillRect(0, 0, BACK_W, BACK_H, g)
    p.end()

    label = QLabel(win)
    label.setPixmap(pm)
    label.setGeometry(0, 0, BACK_W, BACK_H)
    win.show()
    return win


def main() -> int:
    app = QApplication([])
    backdrop = build_backdrop()

    base = Path(tempfile.gettempdir()) / "nest-shot-panel"
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.json").write_text(
        json.dumps({"desktop": str(base)}), encoding="utf-8")

    import config as config_mod
    import engine
    from panel import MainPanel

    cfg = config_mod.Config(str(base / "config.json"))
    items = []
    for name, kind, size in (("季度报告.docx", "file", 240_000),
                             ("预算表.xlsx", "file", 88_000),
                             ("单片机入门资料", "folder", 0),
                             ("产品路线图.pptx", "file", 1_800_000),
                             ("简历.pdf", "file", 610_000),
                             ("截图.png", "file", 420_000)):
        items.append(engine.RepoItem(base / name, Path(name).stem,
                                     kind == "folder", kind, size, 1_760_000_000))

    panel = MainPanel(cfg)
    panel.update_overview(items=items, nest_items=len(items), desktop_pending=3,
                          folders=1, shortcuts=0,
                          history=[{"time": 1_760_000_000, "action": "take",
                                    "count": 6, "moves": []}])
    panel.move(300, 130)

    def shoot():
        panel.show()
        app.processEvents()
        QTimer.singleShot(1500, capture)

    def capture():
        app.processEvents()
        dpr = panel.devicePixelRatio() or 1.0
        tl = panel.mapToGlobal(panel.rect().topLeft())
        x0 = int(tl.x() * dpr) - MARGIN
        y0 = int(tl.y() * dpr) - MARGIN
        w = int(round(panel.width() * dpr)) + MARGIN * 2
        h = int(round(panel.height() * dpr)) + MARGIN * 2
        img = app.primaryScreen().grabWindow(0).toImage()
        out = HERE / "shots"
        out.mkdir(parents=True, exist_ok=True)
        crop = img.copy(x0, y0, w, h)
        crop.save(str(out / "panel-main.png"))
        print("已保存 shots/panel-main.png  %dx%d" % (crop.width(), crop.height()))
        print("磨砂方案：%s（%s）" % (panel._glass_mode or "不可用", acrylic_describe()))
        app.quit()

    QTimer.singleShot(700, shoot)
    app.exec()
    return 0


def acrylic_describe() -> str:
    import acrylic
    return acrylic.describe()


if __name__ == "__main__":
    raise SystemExit(main())
