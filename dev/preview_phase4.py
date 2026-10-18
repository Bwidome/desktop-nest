#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 4 预览图
==============
把底部菜单栏 / 常用启动那一排渲染成 PNG，看"打磨常用启动 + Dock"之后
的实际观感：图标间距、Hover 底色、阴影、拖入高亮、Toast 反馈。

只读：用沙盒里的快捷方式（真图标照取），**不移动任何文件**。
菜单栏是纯透明的顶层窗口，所以这里先垫一张"壁纸"再叠上去——
看的就是"浮在壁纸上的效果"，垫白底会看不出阴影。

用法：python dev/preview_phase4.py
输出：%TEMP%/desktop-nest-preview/phase4-*.png
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))
# 这里**不能**走 offscreen：offscreen 平台插件拿不到系统中文字体的字形，
# 图标下面那行名字会全变成方块（"□□□□"）。预览图看的就是观感，
# 必须用原生平台渲染。脚本跑完自己 hide，不会留在桌面上。
os.environ.pop("QT_QPA_PLATFORM", None)

from qt_compat import (  # noqa: E402
    QApplication, QColor, QEvent, QEventLoop, QImage, QLinearGradient,
    QPainter, QTimer, Qt,
)

OUT = Path(tempfile.gettempdir()) / "desktop-nest-preview"


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wallpaper(width: int, height: int, dark: bool = False) -> QImage:
    """垫一张渐变当壁纸。

    阴影是给**浅色壁纸**兜底用的，所以主图用浅色；深色壁纸再出一张，
    确认悬停底色和白字在两种壁纸上都站得住。
    """
    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    grad = QLinearGradient(0, 0, width, height)
    if dark:
        grad.setColorAt(0.0, QColor("#20262F"))
        grad.setColorAt(0.55, QColor("#2C2530"))
        grad.setColorAt(1.0, QColor("#171C24"))
    else:
        grad.setColorAt(0.0, QColor("#F2F5FA"))
        grad.setColorAt(0.5, QColor("#DFE6F0"))
        grad.setColorAt(1.0, QColor("#C9D3E2"))
    painter = QPainter(canvas)
    painter.fillRect(canvas.rect(), grad)
    painter.end()
    return canvas


def grab(widget) -> QImage:
    pix = widget.grab()
    pix.setDevicePixelRatio(1.0)      # 高分屏下不设这个，贴上去会缩着画 + 发虚
    return pix.toImage()


def compose(name: str, bar: QImage, *, extra_top: int = 0,
            dark: bool = False, toast: "QImage | None" = None) -> None:
    """把菜单栏（和可选的提示）叠到壁纸上。"""
    pad = 26
    width = bar.width() + pad * 2
    height = bar.height() + pad * 2 + extra_top
    canvas = wallpaper(width, height, dark)
    painter = QPainter(canvas)
    painter.drawImage(pad, height - pad - bar.height(), bar)
    if toast is not None:
        painter.drawImage((width - toast.width()) // 2,
                          height - pad - bar.height() - 10 - toast.height(),
                          toast)
    painter.end()
    canvas.save(str(OUT / name))


def main() -> int:
    app = QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)

    base = Path(tempfile.gettempdir()) / "nest-preview-phase4"
    base.mkdir(parents=True, exist_ok=True)
    desktop = base / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)

    # 用桌面上真实存在的快捷方式：图标才是真的（没有就退回 notepad）
    sources = []
    real_desktop = Path(os.path.expanduser("~")) / "Desktop"
    for name in ("Google Chrome.lnk", "Steam.lnk", "KOOK.lnk", "Apifox.lnk",
                 "Bandizip.lnk", "FlClash.lnk"):
        candidate = real_desktop / name
        if candidate.exists():
            sources.append(candidate)
    if not sources:
        import winlink

        for index in range(6):
            link = desktop / f"工具{index}.lnk"
            winlink.create_shortcut(link, r"C:\Windows\System32\notepad.exe")
            sources.append(link)

    import config as config_mod
    import nest

    nest.nest_root = lambda: base / ".nest"
    cfg = config_mod.Config(str(base))
    cfg.update({"desktop": str(desktop), "dock_visible": True,
                "quick_items": []})
    for path in sources:
        cfg.add_quick(path, path.stem)

    import dock as dock_mod

    dock = dock_mod.DockBar(cfg)
    dock.show_bar()
    wait(900)                                  # 等图标取完 + 字体生效 + 尺寸校正

    # 1) 常态：间距 + 阴影（浅色壁纸，最难的一档）
    compose("phase4-dock.png", grab(dock))

    # 2) 深色壁纸上的样子
    compose("phase4-dock-深色壁纸.png", grab(dock), dark=True)

    # 3) 悬停：第二个图标（`:hover` 靠 WA_UnderMouse，离屏下要自己打上）
    button = dock._app_buttons[1]
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    app.sendEvent(button, QEvent(QEvent.Type.Enter))     # 触发图标放大
    wait(240)
    compose("phase4-dock-悬停.png", grab(dock))
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    style.unpolish(button)
    style.polish(button)
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    wait(200)

    # 4) 拖入高亮（从收纳面板把条目拖到菜单栏上）
    dock._set_drop_active(True)                          # noqa: SLF001
    wait(120)
    compose("phase4-dock-拖入高亮.png", grab(dock))
    dock._set_drop_active(False)                         # noqa: SLF001
    wait(80)

    # 5) Toast：加为常用启动的反馈（独立小窗，单独抓了再叠上去）
    dock.show_toast("✓ 已加入常用启动")
    dock.toast.show_message("✓ 已加入常用启动", "ok", animate=False)
    wait(160)
    compose("phase4-dock-Toast.png", grab(dock), extra_top=76,
            toast=grab(dock.toast))
    dock.toast.hide_now()

    # 6) 常用启动那一排（收纳面板顶部）
    import engine
    from desktop_browser import DesktopBrowser

    items = [engine.RepoItem(p, p.stem, False, "shortcut",
                             p.stat().st_size, p.stat().st_mtime)
             for p in sources if p.exists()]
    browser = DesktopBrowser(cfg)
    browser.set_items(items)
    browser.resize(900, 620)
    browser.show()
    wait(900)
    browser.set_manage_mode(True)                        # 管理态：左上角减号
    wait(200)
    # 面板是半透明玻璃，垫浅色壁纸会把白字冲没——垫深色才接近实际观感
    compose("phase4-常用启动.png", grab(browser.toolbar), dark=True)
    browser.hide()

    dock.hide_bar()
    print("已保存到：", OUT)
    for path in sorted(OUT.glob("phase4-*.png")):
        print("  ", path.name, path.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
