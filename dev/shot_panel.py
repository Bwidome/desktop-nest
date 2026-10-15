#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给五张界面拍宣传图
=================
* `shots/panel-main.png`    —— 主面板（悬浮磨砂玻璃卡片）
* `shots/dock.png`          —— 底部菜单栏（只剩「桌面整理」入口 + 常用软件）
* `shots/dock-reorder.png`  —— 长按拖动排序时的插入指示线
* `shots/popup-glass.png`   —— 收纳面板（Dock 第一个控件点开的上拉磨砂浮层）+ 底部菜单栏
* `shots/popup-manage.png`  —— 收纳面板的**管理模式**：唯一的「管理」控件点亮后，
                               常用软件卡片左上角长「－」、其余卡片右上角长「＋」

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

from qt_compat import (QApplication, QColor, QEvent, QLabel, QLinearGradient,
                       QMouseEvent, QPainter, QPixmap, QPoint, QPointF,
                       QRadialGradient, QTimer, QWidget, Qt)

BACK_W, BACK_H = 1400, 860
PANEL_W, PANEL_H = 940, 680
MARGIN = 26
MARGIN_SMALL = 12
# 贴底的窗口（菜单栏 / 收纳面板）下面只留一点点：多留就会跑到屏幕外，
# 截出来要么是黑边、要么把任务栏一起截进来。
BOTTOM_MARGIN = 8


def force_top(widget: QWidget) -> None:
    """把演示窗口抬到最上层（**仅截图脚本用**）。

    本机可能同时开着全屏游戏之类的窗口，普通 Tool 窗口会被整个压在下面，
    截屏就只能截到游戏画面。截图时临时加一个 StaysOnTop 最省事；
    生产代码里绝对不加——收纳面板/菜单栏是故意要让到别的程序后面的。
    """
    widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)


def build_backdrop() -> QWidget:
    """一块柔和的彩色背景板，用来衬托磨砂。"""
    win = QWidget()
    win.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                       | Qt.WindowType.WindowStaysOnTopHint)
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
    from desktop_browser import DesktopBrowser
    from dock import DockBar
    from panel import MainPanel

    # 注意这里传的是**目录**：Config 自己会拼 `config.json`。
    # 传成 `.../config.json` 的话它会当成目录再拼一层，配置就永远写不出去。
    cfg = config_mod.Config(str(base))

    # 演示数据：用**桌面上真实存在的快捷方式**（只读，不移动任何文件）。
    # 特意挑了几个"图标画布占比差得很远"的：Cpolar / Masm / SQL Server
    # 原来在 256×256 画布里只占 12%~18%，缩到 40px 后内容只剩几个像素；
    # 而 Apifox / Chrome / KOOK 是占满整张画布的。放在一起才看得出
    # "裁掉透明边距之后大小统一了"。
    items = []
    desktop_dir = Path(os.path.expanduser("~")) / "Desktop"
    demo = ["Cpolar Web UI.lnk", "Masm for Windows 集成实验环境 2015.lnk",
            "Microsoft SQL Server Management Studio 18.lnk", "Apifox.lnk",
            "Google Chrome.lnk", "Steam.lnk", "KOOK.lnk", "Discord.lnk",
            "Bandizip.lnk", "FlClash.lnk", "Adobe Premiere Pro 2023.lnk",
            "IntelliJ IDEA 2026.2.0.1.lnk", "MEGAsync.lnk", "MuMu模拟器.lnk"]
    for name in demo:
        path = desktop_dir / name
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(engine.RepoItem(path, name, False, "shortcut",
                                     stat.st_size, stat.st_mtime))
    if not items:                       # 桌面上没有就退回一组假文件
        for name, kind, size in (("季度报告.docx", "file", 240_000),
                                 ("预算表.xlsx", "file", 88_000),
                                 ("单片机入门资料", "folder", 0),
                                 ("产品路线图.pptx", "file", 1_800_000),
                                 ("简历.pdf", "file", 610_000),
                                 ("截图.png", "file", 420_000)):
            items.append(engine.RepoItem(base / name, name,
                                         kind == "folder", kind, size,
                                         1_760_000_000))
    print(f"收纳面板演示项：{len(items)} 个")

    # 菜单栏上摆几个常用启动，好让"纯透明底板 + 图标浮在桌面上"看得出来。
    # 用**桌面上的真实快捷方式**（和用户实际"右键 → 加为常用"得到的东西一样）：
    # 面板里那张卡片的名字直接取文件名，塞裸 exe 的话会显示成 "notepad" 这种。
    quick = [{"path": str(item.path), "name": item.name} for item in items[:4]]
    # 其中第 1 个本来就在收纳面板里 → 那张卡片显示左上角「－」，
    # 其余卡片显示右上角「＋」—— 一张图就能同时看到两种角标。
    cfg.update({"quick_items": quick})
    print(f"菜单栏常用启动：{[e['name'] for e in quick]}")

    panel = MainPanel(cfg)
    panel.update_overview(items=items, nest_items=len(items), desktop_pending=3,
                          folders=1, shortcuts=0,
                          history=[{"time": 1_760_000_000, "action": "take",
                                    "count": 6, "moves": []}])
    panel.move(300, 130)

    dock = DockBar(cfg)
    browser = DesktopBrowser(cfg)
    browser.set_items(items)
    browser.set_bottom_reserve(lambda: dock.height() + 14)

    # 三个演示窗口都要抬到最上层，否则会被前台的全屏程序（本机当时开着游戏）
    # 盖住，截出来全是游戏画面。背景板先 show、这三个后 show，
    # 同为 topmost 时后显示的在上层，正好是我们要的层次。
    for demo_window in (panel, dock, browser):
        force_top(demo_window)

    def grab_region(x0, y0, x1, y1, name: str) -> None:
        img = app.primaryScreen().grabWindow(0).toImage()
        # 夹进屏幕范围：贴底窗口再加一圈边距就会超出屏幕（截出黑边或带上任务栏）
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))
        x1 = min(img.width(), int(x1))
        y1 = min(img.height(), int(y1))
        out = HERE / "shots"
        out.mkdir(parents=True, exist_ok=True)
        crop = img.copy(x0, y0, max(1, x1 - x0), max(1, y1 - y0))
        crop.save(str(out / name))
        print(f"已保存 shots/{name}  {crop.width()}x{crop.height()}")

    # ---- 第一张：主面板 ----
    def shoot_panel():
        panel.show()
        app.processEvents()
        QTimer.singleShot(1500, capture_panel)

    def capture_panel():
        app.processEvents()
        dpr = panel.devicePixelRatio() or 1.0
        tl = panel.mapToGlobal(panel.rect().topLeft())
        grab_region(tl.x() * dpr - MARGIN, tl.y() * dpr - MARGIN,
                    (tl.x() + panel.width()) * dpr + MARGIN,
                    (tl.y() + panel.height()) * dpr + MARGIN, "panel-main.png")
        print("磨砂方案：%s（%s）" % (panel._glass_mode or "不可用", acrylic_describe()))
        panel.hide()
        app.processEvents()
        QTimer.singleShot(400, shoot_dock)

    # ---- 第二张：底部菜单栏（只剩「桌面整理」入口 + 常用软件）----
    def shoot_dock():
        dock.show_bar()
        app.processEvents()
        QTimer.singleShot(900, capture_dock)

    def capture_dock():
        app.processEvents()
        dpr = dock.devicePixelRatio() or 1.0
        tl = dock.mapToGlobal(dock.rect().topLeft())
        # 菜单栏本身很矮，边距收紧一点，免得把背景里别的东西一起框进来
        grab_region(tl.x() * dpr - MARGIN_SMALL, tl.y() * dpr - MARGIN_SMALL,
                    (tl.x() + dock.width()) * dpr + MARGIN_SMALL,
                    (tl.y() + dock.height()) * dpr + BOTTOM_MARGIN, "dock.png")
        QTimer.singleShot(250, begin_reorder_shot)

    # ---- 第三张：长按拖动排序时的插入指示线 ----
    def send_mouse(widget, kind, local: "QPoint", glob: "QPoint") -> None:
        event = QMouseEvent(kind, QPointF(local), QPointF(glob),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        app.sendEvent(widget, event)
        app.processEvents()

    def begin_reorder_shot():
        """按住第一个常用图标，等长按计时器到点，再把光标挪到第三个图标上。"""
        if len(dock._app_buttons) < 3:
            QTimer.singleShot(100, shoot_popup)
            return
        source = dock._app_buttons[0]
        local = source.rect().center()
        glob = source.mapToGlobal(local)
        send_mouse(source, QEvent.Type.MouseButtonPress, local, glob)
        # 等长按（DockIcon.HOLD_MS = 320ms）之后再拖
        QTimer.singleShot(600, lambda: drag_for_shot(source, local, glob))

    def drag_for_shot(source, local, glob):
        target = dock._app_buttons[2]
        send_mouse(source, QEvent.Type.MouseMove, local,
                   target.mapToGlobal(target.rect().center()))
        QTimer.singleShot(250, capture_reorder)

    def capture_reorder():
        app.processEvents()
        dpr = dock.devicePixelRatio() or 1.0
        tl = dock.mapToGlobal(dock.rect().topLeft())
        grab_region(tl.x() * dpr - MARGIN_SMALL, tl.y() * dpr - MARGIN_SMALL,
                    (tl.x() + dock.width()) * dpr + MARGIN_SMALL,
                    (tl.y() + dock.height()) * dpr + BOTTOM_MARGIN,
                    "dock-reorder.png")
        # 收尾：把光标挪回原处再松手 → 目标槽位 == 原槽位，顺序不变，
        # 这样后面的 popup 截图还是原来的图标顺序。
        source = dock._app_buttons[0]
        local = source.rect().center()
        glob = source.mapToGlobal(local)
        send_mouse(source, QEvent.Type.MouseMove, local, glob)
        send_mouse(source, QEvent.Type.MouseButtonRelease, local, glob)
        QTimer.singleShot(300, shoot_popup)

    # ---- 第四张：收纳面板（上拉磨砂浮层）+ 底部菜单栏 ----
    def shoot_popup():
        # 不用 show_window()：它会先 refresh_from_disk()，把上面精心挑的
        # 演示项覆盖成真实收纳目录的内容。这里手动走一遍它该做的事。
        browser.set_items(items)
        browser.reposition()
        browser.show()
        browser.raise_()
        app.processEvents()
        QTimer.singleShot(1500, capture_popup)

    def capture_popup():
        app.processEvents()
        dpr = browser.devicePixelRatio() or 1.0
        p_tl = browser.mapToGlobal(browser.rect().topLeft())
        d_tl = dock.mapToGlobal(dock.rect().topLeft())
        x0 = min(p_tl.x(), d_tl.x()) * dpr - MARGIN
        y0 = min(p_tl.y(), d_tl.y()) * dpr - MARGIN
        x1 = max(p_tl.x() + browser.width(), d_tl.x() + dock.width()) * dpr + MARGIN
        y1 = max(p_tl.y() + browser.height(), d_tl.y() + dock.height()) * dpr + BOTTOM_MARGIN
        grab_region(x0, y0, x1, y1, "popup-glass.png")
        print("磨砂方案：%s（%s）" % (browser._glass_mode or "不可用", acrylic_describe()))
        QTimer.singleShot(400, shoot_manage)

    # ---- 第五张：管理模式（唯一的「管理」控件点亮后的角标）----
    def shoot_manage():
        browser.set_manage_mode(True)
        app.processEvents()
        QTimer.singleShot(900, capture_manage)

    def capture_manage():
        app.processEvents()
        dpr = browser.devicePixelRatio() or 1.0
        p_tl = browser.mapToGlobal(browser.rect().topLeft())
        d_tl = dock.mapToGlobal(dock.rect().topLeft())
        x0 = min(p_tl.x(), d_tl.x()) * dpr - MARGIN
        y0 = min(p_tl.y(), d_tl.y()) * dpr - MARGIN
        x1 = max(p_tl.x() + browser.width(), d_tl.x() + dock.width()) * dpr + MARGIN
        y1 = max(p_tl.y() + browser.height(), d_tl.y() + dock.height()) * dpr + BOTTOM_MARGIN
        grab_region(x0, y0, x1, y1, "popup-manage.png")
        minus = sum(1 for t in browser._tiles
                    if t.badge is not None and t.badge.text() == "－")
        plus = sum(1 for t in browser._tiles
                   if t.badge is not None and t.badge.text() == "＋")
        print(f"管理模式角标：卡片区 左上角「－」{minus} 个、右上角「＋」{plus} 个；"
              f"常用排 {len(browser._app_buttons)} 个全带「－」")
        browser.set_manage_mode(False)
        app.quit()

    QTimer.singleShot(700, shoot_panel)
    app.exec()
    return 0


def acrylic_describe() -> str:
    import acrylic
    return acrylic.describe()


if __name__ == "__main__":
    raise SystemExit(main())
