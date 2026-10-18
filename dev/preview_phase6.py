#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6 预览图
==============
把三个"过渡的中间状态"定格下来，确认动画的方向和幅度是对的：

* `phase6-悬停过渡.png` —— 同一排三张卡片，悬停值分别是 0 / 35% / 100%
  （hover 底色本身就是 10% 白，所以过渡本来就很轻——这是刻意的）
* `phase6-提示进场.png` —— Toast 抬到一半、淡到一半时的样子
* `phase6-翻页淡入.png` —— 翻页淡入到 45% 的样子（位置不动）

⚠️ 不能用 offscreen：离屏平台拿不到系统中文字形，图里会全是"□□□□"。

用法：python dev/preview_phase6.py
输出：%TEMP%/desktop-nest-preview/phase6-*.png
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


def main() -> int:
    app = QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)

    base = Path(tempfile.gettempdir()) / "nest-preview-phase6"
    base.mkdir(parents=True, exist_ok=True)
    desktop = base / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    for name in ("季度报告.docx", "预算表.xlsx", "产品原型.sketch",
                 "会议纪要.md", "截图.png", "演示稿.pptx", "资料.zip",
                 "音乐.mp3"):
        (desktop / name).write_text("x", encoding="utf-8")

    import config as config_mod

    config_mod._DATA_DIR = base / "data"
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "PublicDesktop"
    (base / "PublicDesktop").mkdir(parents=True, exist_ok=True)

    import engine
    import nest

    nest.nest_root = lambda: base / ".nest"
    nest.ensure_dirs()

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(desktop), "page_size": 14})

    import desktop_browser as db_mod

    items = [engine.RepoItem(desktop / n, n, False, "document", 1024, 0.0)
             for n in sorted(p.name for p in desktop.iterdir())]
    browser = db_mod.DesktopBrowser(cfg)
    browser.resize(940, 620)
    browser.set_items(items)
    browser.show()
    wait(600)

    # 1) 悬停过渡：三张卡片分别停在 0 / 0.35 / 1.0
    tiles = browser._tiles[:3]
    for tile, value in zip(tiles, (0.0, 0.35, 1.0)):
        tile.veil.snap(value)
    wait(200)
    shot(browser, "phase6-悬停过渡.png")

    # 2) Toast 进场中途：抬到 4px、淡到 55%
    for tile in tiles:
        tile.veil.snap(0.0)
    browser.toast.show_message("✓ 已收纳\n8 个项目", "ok", animate=False)
    browser.toast._effect.setOpacity(0.55)
    browser.toast._rise = browser.toast.ENTER_RISE / 2.0
    browser.toast.place()
    wait(150)
    shot(browser, "phase6-提示进场.png")
    browser.toast.hide_now()

    # 3) 翻页淡入到 45%（先把每页数量调小，才有第二页）
    browser.set_per_page(4)
    wait(150)
    if browser._page_count() > 1:
        browser.goto_page(1)
        wait(30)
        effect = browser.grid_host.graphicsEffect()
        if effect is not None:
            browser.grid_host._fade_anim.stop()
            effect.setOpacity(0.45)
        wait(120)
        shot(browser, "phase6-翻页淡入.png")

    browser.hide()
    print("已保存到：", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
