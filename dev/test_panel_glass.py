#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
悬浮磨砂玻璃卡片 —— 回归测试
============================
覆盖**主面板**和**收纳面板（Dock 第一个控件点开的上拉浮层）**——
两者共用 `widgets.GlassCardMixin` 的同一套外观。

盯住四类**只有真机上才看得见、单元测试很容易漏掉**的问题：

1. **高 DPI 裁剪**：`SetWindowRgn` 收物理像素，Qt 报的是逻辑像素。
   漏乘 `devicePixelRatio` 就会把窗口裁小一圈——右下角连按钮都不显示。
   （dpr=1 的机器上完全正常，所以必须靠纯函数把换算钉死。）
2. **标签栏顶上那道白线**：`QTabWidget.setDocumentMode(True)` 会让
   QTabBar 用**主题位图**画一条"基线"，既不吃 QSS 也不吃调色板。
   浅色主题下看不出来，深色玻璃上就是一道刺眼的白。
3. **顶层窗口不能自己画底**：画了就把 DWM 的磨砂整块盖住。
4. **弹出类控件必须不透明**：它们会继承玻璃样式表，底色一透就"看不见"。

用法：python dev/test_panel_glass.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
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


def fonts_available() -> bool:
    """当前环境到底有没有可用字体。

    **为什么需要这个**：无头 / 精简环境里 Qt 常常一个字体都没有
    （stderr 会打 `QFontDatabase: Cannot find font directory …`）。
    那种情况下所有文字都会退化成"实心方块"，像素扫描会把整行文字误判成
    "横贯的不透明浅色线"——测出来的是一条永远存在的假白线，和样式无关。

    所以像素级的观感断言必须在"有字体"的前提下跑，否则要么恒假阳性、
    要么逼着人去调阈值把真问题也一起放过。
    """
    try:
        from qt_compat import QFontDatabase

        families = QFontDatabase.families()
        return bool(families)
    except Exception:
        return False


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-panel-glass-test"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)

    import json

    import acrylic
    import config as config_mod
    import engine
    import theme as theme_mod
    from qt_compat import QApplication, QFrame, QPalette, Qt, QToolButton

    # ------------------------------------------------------------------
    print("1. 窗口区域换算（高 DPI 裁剪的根因）")
    # ------------------------------------------------------------------
    check("dpr=1.00 时尺寸原样", acrylic.region_metrics(940, 680, 22, 1.0)
          == (940, 680, 44),
          repr(acrylic.region_metrics(940, 680, 22, 1.0)))
    check("dpr=1.25 时尺寸乘 1.25（漏乘就会裁小一圈）",
          acrylic.region_metrics(940, 680, 22, 1.25) == (1175, 850, 56),
          repr(acrylic.region_metrics(940, 680, 22, 1.25)))
    check("dpr=2.00 时尺寸乘 2",
          acrylic.region_metrics(940, 680, 22, 2.0) == (1880, 1360, 88),
          repr(acrylic.region_metrics(940, 680, 22, 2.0)))
    w, h, d = acrylic.region_metrics(940, 680, 22, 1.25)
    check("圆角直径也跟着缩放（否则高 DPI 下圆角会变小）", d == 56, str(d))
    check("尺寸至少为 1，不会传 0 给 CreateRoundRectRgn",
          acrylic.region_metrics(0, 0, 0, 1.0)[0] >= 1
          and acrylic.region_metrics(0, 0, 0, 1.0)[2] >= 2)

    # ------------------------------------------------------------------
    print("2. DWM 着色字节序")
    # ------------------------------------------------------------------
    # #181A20 -> R=0x18 G=0x1A B=0x20；ABGR 排列后是 0x80 20 1A 18
    check("#181A20 + alpha 128 -> 0x80201A18（0xAABBGGRR，字节序是反的）",
          acrylic._abgr("#181A20", 128) == 0x80201A18,
          hex(acrylic._abgr("#181A20", 128)))
    check("三位简写 #fff 能展开", acrylic._abgr("#fff", 255) == 0xFFFFFFFF,
          hex(acrylic._abgr("#fff", 255)))
    check("颜色串写错时退回默认色，不抛异常",
          acrylic._abgr("nonsense", 128) == acrylic._abgr("#1A1C22", 128))
    check("describe() 是一句话，不抛异常", isinstance(acrylic.describe(), str))
    check("非 Windows 时 enable_blur 返回空串（调用方据此回退）",
          acrylic.IS_WINDOWS or acrylic.enable_blur(None) == "")

    # ------------------------------------------------------------------
    print("3. 玻璃样式表")
    # ------------------------------------------------------------------
    glass = theme_mod.stylesheet(False, glass=True)
    normal = theme_mod.stylesheet(False, glass=False)
    check("顶层窗口自己不画底（画了就把磨砂盖住）",
          "#MainPanel, #BrowserRoot { background: transparent; }" in glass)
    check("深色半透明画在子控件卡片上（#MainCard / #Popup）",
          "#MainCard, #Popup {" in glass and theme_mod.GLASS["card"] in glass)
    check("收纳面板（#Popup）和主面板共用同一套玻璃卡片",
          "#Popup" in glass
          and f"border-radius: {theme_mod.GLASS_RADIUS}px;" in glass)
    check("卡片用大圆角", f"border-radius: {theme_mod.GLASS_RADIUS}px;" in glass,
          str(theme_mod.GLASS_RADIUS))
    check("圆角半径是大圆角（>= 18px）", theme_mod.GLASS_RADIUS >= 18)
    check("卡片底色是半透明深色，不是纯白",
          theme_mod.GLASS["card"].startswith("rgba(")
          and "#fff" not in theme_mod.GLASS["card"].lower())
    check("弹出类控件被单独改成不透明（否则菜单/提示看不见）",
          "QMenu, QMessageBox {" in glass and "QToolTip {" in glass)
    check("玻璃样式不污染普通主题", "#MainCard" not in normal
          and "#GlassClose" not in normal)
    check("玻璃规则块放在整份样式表**最后**"
          "（放中间会被后面的 #Popup / QMenu 等普通规则盖掉）",
          glass.rstrip().endswith("}")
          and glass.index("#MainCard, #Popup") > glass.index("#Popup {"))
    check("玻璃配色不跟随明暗主题（需求就是恒定深色）",
          theme_mod.GLASS["text"] == "#F3F5F9")

    roles = theme_mod.glass_palette_roles()
    check("调色板是深色的（兜住 QSS 没写到的控件）",
          roles["window"].lower() == "#181a20" and roles["text"].startswith("#F"))
    check("调色板含 Base/Button/Highlight 等关键角色",
          all(k in roles for k in ("window", "base", "alternate", "text", "sub",
                                   "button", "highlight", "highlight_text")))

    # ------------------------------------------------------------------
    print("4. 主面板窗口本身")
    # ------------------------------------------------------------------
    app = QApplication.instance() or QApplication([])
    (base / "config.json").write_text(
        json.dumps({"desktop": str(base)}), encoding="utf-8")
    cfg = config_mod.Config(str(base / "config.json"))

    from panel import MainPanel

    panel = MainPanel(cfg)
    flags = panel.windowFlags()
    check("无边框", bool(flags & Qt.WindowType.FramelessWindowHint))
    check("是独立窗口（不是 Tool/子窗口）",
          (flags & Qt.WindowType.WindowType_Mask) == Qt.WindowType.Window)
    check("窗口自身透明（磨砂才透得出来）",
          panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
    check("objectName 是 MainPanel（QSS 靠它选中）", panel.objectName() == "MainPanel")

    card = panel.findChild(QFrame, "MainCard")
    check("内部有 #MainCard 子控件承载卡片外观", card is not None)
    # 布局要跑一轮才有真实尺寸
    panel.resize(940, 680)
    panel.layout().activate()
    app.processEvents()
    check("卡片铺满整个窗口（这样圆角裁剪才和卡片对齐）",
          card is not None and card.size() == panel.size(),
          f"{card.size()} vs {panel.size()}" if card else "无卡片")

    # ------------------------------------------------------------------
    print("5. 标签栏顶上那道白线")
    # ------------------------------------------------------------------
    bar = panel.tabs.tabBar()
    check("关掉了 QTabBar 的「基线」绘制（否则深色玻璃上一条白）",
          bar.drawBase() is False)
    check("标签页有两个", panel.tabs.count() == 2)

    # 真的渲染一遍，确认那条线不存在了（不透明浅色横线）
    #
    # ⚠️ 这条断言只在**有字体**的环境里有效。没字体时文字会变成实心方块，
    # 一整行文字会被误判成"横贯的浅色线"——那是环境问题，不是样式问题
    # （已在上一版代码上复现过同样的 y=166，与本次改动无关）。
    if not fonts_available():
        print("  ⊘ 跳过（当前环境没有可用字体，像素扫描会把文字误判成白线）")
        print("     装上字体后重跑即可验证这一条；其余断言不受影响。")
    else:
        panel.resize(940, 680)
        panel.show()
        app.processEvents()
        img = panel.grab().toImage()
        worst = None
        for y in range(150, 320):
            n = 0
            op = 0
            for x in range(0, img.width(), 4):
                c = img.pixelColor(x, y)
                if c.alpha() >= 250:
                    op += 1
                    if (0.299 * c.red() + 0.587 * c.green()
                            + 0.114 * c.blue()) > 120:
                        n += 1
            if op and n / (img.width() / 4) > 0.5:
                worst = y
        check("渲染结果里没有横贯的不透明浅色线", worst is None, f"y={worst}")

    # ------------------------------------------------------------------
    print("6. 交互与回退")
    # ------------------------------------------------------------------
    close_btn = panel.findChild(QToolButton, "GlassClose")
    check("无边框窗口自带关闭按钮（不然没系统标题栏可点）",
          close_btn is not None)
    if close_btn is not None:
        panel.show()
        app.processEvents()
        close_btn.click()
        app.processEvents()
        check("点关闭是隐藏窗口，不是退出程序", not panel.isVisible())

    check("窗口初始就是深色玻璃尺寸（>= 820x600，够放内容）",
          panel.minimumWidth() >= 820 and panel.minimumHeight() >= 600)

    # 拿不到磨砂时，卡片底色要加浓（不然文字看不清）
    panel._glass_mode = ""
    panel._restyle()
    check("磨砂不可用时卡片底色加浓到 0.90（可读性兜底）",
          "rgba(24, 26, 32, 0.90)" in panel.styleSheet())
    panel._glass_mode = "acrylic"
    panel._restyle()
    check("磨砂可用时不加那层加浓底色",
          "rgba(24, 26, 32, 0.90)" not in panel.styleSheet())

    # 拖动：没有系统标题栏，按住空白处要能拖
    panel._drag_offset = None
    check("留了拖动用的状态位（无标题栏窗口靠它拖）",
          hasattr(panel, "_drag_offset") and hasattr(panel, "mouseMoveEvent"))
    check("Esc 能收起面板",
          hasattr(panel, "keyPressEvent") and hasattr(panel, "hide"))

    # 尺寸变化后要重新裁圆角（SetWindowRgn 不跟着缩放）
    calls = []
    original_region = acrylic.apply_round_region

    def spy(widget, radius):
        calls.append((widget.width(), widget.height(), radius))
        return False

    acrylic.apply_round_region = spy
    try:
        panel.show()
        panel.resize(900, 660)
        app.processEvents()
        panel.resize(940, 680)
        app.processEvents()
    finally:
        acrylic.apply_round_region = original_region
    check("尺寸一变就重新裁圆角（SetWindowRgn 不跟着缩放）",
          len(calls) >= 2, f"调了 {len(calls)} 次")
    check("裁圆角时用的是窗口当时的真实尺寸",
          bool(calls) and calls[-1][:2] == (panel.width(), panel.height()),
          str(calls[-1] if calls else None))
    check("圆角半径用的是 theme.GLASS_RADIUS（和 QSS 对齐）",
          bool(calls) and all(c[2] == theme_mod.GLASS_RADIUS for c in calls))

    panel.close()
    app.processEvents()

    # ------------------------------------------------------------------
    print("7. 收纳面板（Dock 第一个控件点开的上拉浮层）共用同一套玻璃外观")
    # ------------------------------------------------------------------
    from desktop_browser import DesktopBrowser
    from widgets import GlassCardMixin

    browser = DesktopBrowser(cfg)
    check("主面板用了共享的 GlassCardMixin", isinstance(panel, GlassCardMixin))
    check("收纳面板也用了共享的 GlassCardMixin",
          isinstance(browser, GlassCardMixin))
    check("收纳面板顶层 objectName 是 BrowserRoot（QSS 靠它选中）",
          browser.objectName() == "BrowserRoot")
    check("收纳面板的卡片子控件是 #Popup",
          browser.findChild(QFrame, "Popup") is not None)
    check("收纳面板固定深色玻璃（不跟应用明暗主题走）", browser.dark is True)
    check("收纳面板调色板也是深色（兜住 QSS 没写到的控件）",
          browser.palette().color(QPalette.ColorRole.Window).lightness() < 128,
          browser.palette().color(QPalette.ColorRole.Window).name())
    check("收纳面板的样式表里带着玻璃卡片规则",
          "#MainCard, #Popup {" in browser.styleSheet())
    check("两个窗口的磨砂状态位都由 mixin 提供",
          hasattr(panel, "_glass_mode") and hasattr(browser, "_glass_mode")
          and hasattr(panel, "_glass_ready") and hasattr(browser, "_glass_ready"))
    check("各自的重裁圆角走同一条路（resizeEvent 在 mixin 里）",
          GlassCardMixin.resizeEvent is not None
          and type(panel).resizeEvent is GlassCardMixin.resizeEvent
          and type(browser).resizeEvent is GlassCardMixin.resizeEvent)
    browser.close()
    app.processEvents()

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
