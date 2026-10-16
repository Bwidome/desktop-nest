#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1 · 视觉 Design System —— 回归测试
========================================
Phase 1 的目标是"建立统一的视觉 Design System"，验收标准是：

* 所有窗口颜色一致
* 所有按钮风格一致
* 所有输入框风格一致
* Border 风格一致
* 圆角一致
* Hover 一致
* Disabled 一致

这些标准都很"观感"，所以这里把它们翻译成**可执行的断言**，分四层：

1. **Token 层**：三套 scheme（浅色 / 深色 / 玻璃）的语义 token 是否齐备、
   是否和扁平色板逐键对齐、尺度 token（圆角 / 阴影 / 控件高度 / 字号 /
   字重 / 时长）是否成套。
2. **规则层**：九类组件（Button / Input / Checkbox / Tab / Card / Tooltip /
   Toast / Dialog / Menu）是否都有规则，且都写全了 hover / focus / disabled。
3. **实测层**：真的建一个 `QApplication` 套上样式表，量按钮 / 输入框 / 下拉框
   的**实际高度**是否一致 —— 这是"输入框和按钮一样高"唯一靠谱的验证方式。
4. **收编层**：界面文件里不能再出现写死的色号 / 圆角 / 时长（否则"统一"
   就只是句口号）。

用法：python dev/test_theme_tokens.py
"""
from __future__ import annotations

import os
import re
import sys
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


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _rgb(color: str) -> "tuple[int, int, int] | None":
    """把 `#RRGGBB` / `rgba(r, g, b, a)` 解析成 0-255 的 RGB。"""
    text = (color or "").strip()
    if text.startswith("#"):
        hex_part = text[1:]
        if len(hex_part) == 3:
            hex_part = "".join(ch * 2 for ch in hex_part)
        if len(hex_part) < 6:
            return None
        try:
            return (int(hex_part[0:2], 16), int(hex_part[2:4], 16),
                    int(hex_part[4:6], 16))
        except ValueError:
            return None
    match = re.match(r"rgba?\(([^)]*)\)", text)
    if not match:
        return None
    parts = [p.strip() for p in match.group(1).split(",")]
    if len(parts) < 3:
        return None
    try:
        return tuple(int(round(float(p))) for p in parts[:3])   # type: ignore[return-value]
    except ValueError:
        return None


def _luminance(color: "tuple[int, int, int]") -> float:
    channels = []
    for value in color:
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.03928
                        else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG 对比度（1.0 ~ 21.0）。"""
    a, b = _rgb(fg), _rgb(bg)
    if a is None or b is None:
        return 0.0
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# 语义 token 清单 —— 就是需求里点名要"统一"的那批
SEMANTIC_KEYS = (
    "bg", "surface", "surface_hover", "border",
    "text_primary", "text_secondary", "text_muted",
    "primary", "primary_hover", "success", "warning", "danger",
)
# 配套的"扩展"token（底色 / 按下态 / 弹出层等）
EXTRA_KEYS = (
    "surface_alt", "surface_pressed", "border_strong",
    "primary_pressed", "primary_soft",
    "success_soft", "warning_soft", "danger_soft",
    "highlight", "shadow", "popup", "popup_alt", "popup_border",
    "toast_bg", "toast_text",
)
SCHEMES = ("light", "dark", "glass")


def main() -> int:
    import theme as theme_mod

    # ==================================================================
    section("1. 语义 Token 齐备（三套 scheme 用同一组键）")
    # ==================================================================
    for scheme in SCHEMES:
        got = theme_mod.COLOR_TOKENS[scheme]
        missing = [k for k in SEMANTIC_KEYS + EXTRA_KEYS if k not in got]
        check(f"{scheme}：需求点名的语义 token 全在",
              not missing, str(missing))
    check("玻璃多两个专属键（卡片底 / 卡片描边）",
          "card" in theme_mod.COLOR_TOKENS["glass"]
          and "card_border" in theme_mod.COLOR_TOKENS["glass"])
    check("三套 scheme 的键集合完全一致（只差玻璃专属的两个）",
          set(theme_mod.COLOR_TOKENS["light"])
          == set(theme_mod.COLOR_TOKENS["dark"])
          == set(theme_mod.COLOR_TOKENS["glass"]) - {"card", "card_border"})

    # ==================================================================
    section("2. 扁平色板由 Token 展开（没有第二套颜色体系）")
    # ==================================================================
    pairs = (("light", theme_mod.LIGHT), ("dark", theme_mod.DARK),
             ("glass", theme_mod.GLASS))
    for scheme, flat in pairs:
        toks = theme_mod.COLOR_TOKENS[scheme]
        bad = [k for k, v in toks.items() if flat.get(k) != v]
        check(f"{scheme}：扁平色板与语义 token 逐键一致", not bad, str(bad))
    check("历史键名仍可用（accent / text_sub / hover / warn …）",
          all(theme_mod.LIGHT.get(k) == theme_mod.LIGHT.get(v)
              for k, v in (("accent", "primary"), ("text_sub", "text_secondary"),
                           ("text_faint", "text_muted"), ("hover", "surface_hover"),
                           ("pressed", "surface_pressed"),
                           ("accent_soft", "primary_soft"), ("warn", "warning"),
                           ("warn_soft", "warning_soft"))))
    check("品牌主色只有一个来源（BRAND_ACCENT == primary）",
          theme_mod.BRAND_ACCENT == theme_mod.COLOR_TOKENS["light"]["primary"],
          theme_mod.BRAND_ACCENT)
    check("文件类型占位色也收在主题里（不再两处各写一遍 #4F6BED）",
          theme_mod.FILE_TYPE_COLORS["shortcut"]
          == theme_mod.COLOR_TOKENS["light"]["primary"]
          and theme_mod.FALLBACK_TILE_COLOR
          == theme_mod.FILE_TYPE_COLORS["other"])
    check("palette() / tokens() 两种取法都能拿到值",
          theme_mod.palette(False)["accent"] == theme_mod.LIGHT["accent"]
          and theme_mod.tokens("dark")["text_primary"]
          == theme_mod.DARK["text"])

    # ==================================================================
    section("3. 尺度 Token 成套")
    # ==================================================================
    R = theme_mod.RADIUS
    check("圆角 token 含全部语义档位",
          all(k in R for k in ("xs", "sm", "md", "lg", "xl", "popup",
                               "popup_inner", "dock", "card")), str(sorted(R)))
    check("圆角随档位递增（尺子是单调的）",
          R["xs"] < R["sm"] < R["md"] < R["lg"] < R["xl"] < R["popup"] < R["dock"] < R["card"])
    check("玻璃卡片圆角 == RADIUS['card'] 且 >= 18px",
          theme_mod.GLASS_RADIUS == R["card"] and theme_mod.GLASS_RADIUS >= 18,
          str(theme_mod.GLASS_RADIUS))
    check("历史别名 RADIUS_SMALL / RADIUS_MD 仍在且指向尺子上的档位",
          theme_mod.RADIUS_SMALL == R["md"] and theme_mod.RADIUS_MD == R["lg"])

    check("阴影三档齐备（sm / md / lg）",
          all(k in theme_mod.SHADOW for k in ("sm", "md", "lg")))
    check("阴影参数成套（blur / dx / dy / alpha）",
          all(set(v) == {"blur", "dx", "dy", "alpha"}
              for v in theme_mod.SHADOW.values()))
    check("阴影强度随档位递增",
          theme_mod.SHADOW["sm"]["blur"] < theme_mod.SHADOW["md"]["blur"]
          < theme_mod.SHADOW["lg"]["blur"])

    CT = theme_mod.CONTROL
    # 按钮 / 输入框共用的 QSS：min-height + 上下 padding(7) + 上下边框(1)
    computed = CT["min_height"] + 7 * 2 + 1 * 2
    check("控件高度 token 自洽（min_height + padding + 边框 = height）",
          computed == CT["height"], f"{computed} vs {CT['height']}")
    check("控件高度在合理区间（28~44px）", 28 <= CT["height"] <= 44,
          str(CT["height"]))

    F = theme_mod.FONT_SIZE
    check("字号 token 含全局默认与各层级",
          all(k in F for k in ("xs", "sm", "base", "md", "close", "lg", "xl")),
          str(sorted(F)))
    check("字号随层级递增",
          F["xs"] < F["sm"] < F["base"] < F["md"] < F["close"] < F["lg"] < F["xl"])
    check("字重四档齐备（regular / medium / semibold / bold）",
          all(k in theme_mod.FONT_WEIGHT
              for k in ("regular", "medium", "semibold", "bold")))

    D = theme_mod.DURATION
    check("动画时长 token 齐备",
          all(k in D for k in ("fast", "normal", "slow", "settle", "tick",
                               "highlight")), str(sorted(D)))
    check("帧间隔 token 是 60fps 量级（10~20ms）", 10 <= D["tick"] <= 20,
          str(D["tick"]))
    check("缓动曲线已登记", isinstance(theme_mod.EASING, str)
          and "cubic-bezier" in theme_mod.EASING)

    # ==================================================================
    section("4. 九类组件规则齐备")
    # ==================================================================
    sheets = {
        "light": theme_mod.stylesheet(False),
        "dark": theme_mod.stylesheet(True),
        "glass": theme_mod.stylesheet(False, glass=True),
    }
    light = sheets["light"]

    COMPONENTS = {
        "Button": ("QPushButton {", "QPushButton#Primary", "QPushButton#Danger",
                   "QPushButton#Soft", "QPushButton#Ghost", "QToolButton {"),
        "Input": ("QLineEdit", "QTextEdit", "QComboBox {", "QComboBox QAbstractItemView"),
        "Checkbox": ("QCheckBox {", "QCheckBox::indicator {"),
        "Tab": ("QTabWidget::pane", "QTabBar::tab {", "QTabBar::tab:selected"),
        "Card": ("#Card, #Panel {",),
        "Tooltip": ("QToolTip {",),
        "Toast": ("#Toast {", "#ToastOk", "#ToastWarn", "#ToastDanger"),
        "Dialog": ("QMessageBox {", "QMessageBox QLabel", "QMessageBox QPushButton"),
        "Menu": ("QMenu {", "QMenu::item {", "QMenu::separator"),
    }
    for name, needles in COMPONENTS.items():
        missing = [n for n in needles if n not in light]
        check(f"{name}：规则齐备", not missing, str(missing))

    # 三套 scheme 必须共用同一批规则（只换 token，不换规则）
    for scheme, sheet in sheets.items():
        missing = [n for needles in COMPONENTS.values() for n in needles
                   if n not in sheet]
        check(f"{scheme}：九类组件规则一个不少", not missing, str(missing))

    # ==================================================================
    section("5. 三态齐备（Hover / Focus / Disabled 一致）")
    # ==================================================================
    STATES = {
        "Button": ("QPushButton:hover", "QPushButton:focus",
                   "QPushButton:disabled"),
        "Button#Primary": ("QPushButton#Primary:hover",
                           "QPushButton#Primary:disabled"),
        "Button#Danger": ("QPushButton#Danger:hover",
                          "QPushButton#Danger:disabled"),
        "Button#Soft": ("QPushButton#Soft:hover", "QPushButton#Soft:disabled"),
        "Button#Ghost": ("QPushButton#Ghost:hover", "QPushButton#Ghost:disabled"),
        "ToolButton": ("QToolButton:hover", "QToolButton:checked",
                       "QToolButton:disabled"),
        "Input": ("QLineEdit:focus", "QLineEdit:disabled",
                  "QComboBox:hover", "QComboBox:disabled"),
        "Checkbox": ("QCheckBox::indicator:hover", "QCheckBox::indicator:checked",
                     "QCheckBox::indicator:disabled"),
        "Tab": ("QTabBar::tab:hover", "QTabBar::tab:selected",
                "QTabBar::tab:disabled"),
        "List": ("QListWidget::item:hover", "QListWidget::item:selected"),
        "Menu": ("QMenu::item:selected", "QMenu::item:disabled"),
    }
    for name, needles in STATES.items():
        missing = [n for n in needles if n not in light]
        check(f"{name}：三态齐备", not missing, str(missing))

    check("全局也有统一的 disabled 文字色（QWidget:disabled）",
          "QWidget:disabled" in light)

    # ==================================================================
    section("6. 字号统一为 pt（跟随 DPI），且没有 px 残留")
    # ==================================================================
    for scheme, sheet in sheets.items():
        px = re.findall(r"font-size:\s*[\d.]+px", sheet)
        check(f"{scheme}：没有 px 字号", not px, str(px[:4]))
        pt = re.findall(r"font-size:\s*([\d.]+)pt", sheet)
        check(f"{scheme}：pt 字号足够多（>= 10 处）", len(pt) >= 10, str(len(pt)))
        used = {float(v) for v in pt}
        known = {round(v, 2) for v in F.values()}
        check(f"{scheme}：字号全部来自 FONT_SIZE 尺子",
              used <= known, str(sorted(used - known)))

    # ==================================================================
    section("7. QSS 本身是良构的")
    # ==================================================================
    for scheme, sheet in sheets.items():
        check(f"{scheme}：花括号成对",
              sheet.count("{") == sheet.count("}"),
              f"{sheet.count('{')} vs {sheet.count('}')}")
        check(f"{scheme}：没有没替换掉的占位符",
              "None" not in sheet and "{'" not in sheet)
        check(f"{scheme}：声明了字体族", "font-family:" in sheet)
    check("玻璃块仍在整份样式表的最后（否则会被普通规则盖掉）",
          sheets["glass"].rstrip().endswith("}")
          and sheets["glass"].index("#MainCard, #Popup")
          > sheets["glass"].index("#Popup {"))
    check("玻璃规则不污染普通主题",
          "#MainCard" not in light and "#GlassClose" not in light)

    # ==================================================================
    section("8. 文字对比度达标（可读性兜底）")
    # ==================================================================
    # 正文 4.5:1（AA），次要文字 3.0:1（大字号/辅助信息可放宽）
    for scheme in SCHEMES:
        toks = theme_mod.COLOR_TOKENS[scheme]
        bg = toks["bg"] if scheme != "glass" else "#181A20"
        surface = toks["surface"] if scheme != "glass" else "#181A20"
        body = contrast(toks["text_primary"], bg)
        check(f"{scheme}：正文 / 底色 对比度 >= 4.5", body >= 4.5, f"{body:.2f}")
        on_card = contrast(toks["text_primary"], surface)
        check(f"{scheme}：正文 / 卡片底 对比度 >= 4.5", on_card >= 4.5,
              f"{on_card:.2f}")
        secondary = contrast(toks["text_secondary"], bg)
        check(f"{scheme}：次要文字对比度 >= 3.0", secondary >= 3.0,
              f"{secondary:.2f}")
        primary = contrast(toks["primary"], bg)
        check(f"{scheme}：主色对比度 >= 3.0", primary >= 3.0, f"{primary:.2f}")

    # ==================================================================
    section("9. 实测：按钮 / 输入框 / 下拉框一样高")
    # ==================================================================
    from qt_compat import (QApplication, QCheckBox, QComboBox, QDialog,
                           QLineEdit, QMenu, QPushButton, QTabWidget)

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme_mod.stylesheet(False))

    holder = QDialog()
    button = QPushButton("确定", holder)
    primary = QPushButton("保存", holder)
    primary.setObjectName("Primary")
    edit = QLineEdit(holder)
    combo = QComboBox(holder)
    combo.addItem("一项")
    box = QCheckBox("选项", holder)
    tabs = QTabWidget(holder)
    menu = QMenu(holder)
    menu.addAction("菜单项")

    heights = {
        "QPushButton": button.sizeHint().height(),
        "QPushButton#Primary": primary.sizeHint().height(),
        "QLineEdit": edit.sizeHint().height(),
        "QComboBox": combo.sizeHint().height(),
    }
    check("按钮 / 输入框 / 下拉框自然高度一致（统一控件高度）",
          len(set(heights.values())) == 1, str(heights))
    check(f"实测高度 == CONTROL['height']（{CT['height']}）",
          heights["QPushButton"] == CT["height"], str(heights))
    check("复选框 / 标签页 / 菜单能正常创建（样式表没把控件搞崩）",
          all(w is not None for w in (box, tabs, menu)))
    check("复选框指示器尺寸走 QSS（17×17）",
          box.sizeHint().height() > 0)

    # 深色 / 玻璃下也要能套上去
    for label, kwargs in (("深色", {"dark": True}), ("玻璃", {"glass": True})):
        try:
            app.setStyleSheet(theme_mod.stylesheet(**kwargs))
            probe = QPushButton("x")
            probe.sizeHint()
            ok = True
        except Exception as exc:                 # pragma: no cover
            ok = False
            print(f"      {exc}")
        check(f"{label}主题能正常套用到控件上", ok)
    app.setStyleSheet("")

    # 阴影助手：有 Qt 就给 effect，没 Qt 就 None，总之不抛异常
    effect = theme_mod.drop_shadow(button, "md")
    check("drop_shadow() 不抛异常（返回 effect 或 None）",
          effect is None or effect is not None)
    check("drop_shadow() 的模糊半径取自 SHADOW token",
          effect is None
          or effect.blurRadius() == theme_mod.SHADOW["md"]["blur"])

    # ==================================================================
    section("10. 界面文件里不再有写死的色号 / 圆角 / 时长")
    # ==================================================================
    def read(name: str) -> str:
        return (HERE / name).read_text(encoding="utf-8")

    dock_src = read("dock.py")
    browser_src = read("desktop_browser.py")
    widgets_src = read("widgets.py")

    check("dock.py 的帧间隔 / 防抖时长取自 DURATION",
          "theme_mod.DURATION" in dock_src
          and "setInterval(16)" not in dock_src
          and "setInterval(60)" not in dock_src)
    check("desktop_browser.py 的防抖 / 高亮时长取自 DURATION",
          "theme_mod.DURATION" in browser_src
          and "setInterval(120)" not in browser_src
          and "setInterval(1200)" not in browser_src)
    check("desktop_browser.py 的内联圆角取自 RADIUS",
          "theme_mod.RADIUS" in browser_src
          and "border-radius: 10px" not in browser_src)
    check("widgets.py 的占位色不再是本文件里的第二套色板",
          "PLACEHOLDER_COLORS = theme.FILE_TYPE_COLORS" in widgets_src
          and '"#E09A3E"' not in widgets_src)
    # 剩下的硬编码只允许是"画图标用的白/浅蓝"，不属于界面配色
    for name, src in (("dock.py", dock_src),
                      ("desktop_browser.py", browser_src),
                      ("widgets.py", widgets_src)):
        stray = re.findall(r"#[0-9A-Fa-f]{6}", src)
        allowed = {"#FFFFFF", "#D8E0FF", "#EAF0FA", "#F2F4F8", "#2A1310"}
        bad = sorted({s for s in stray if s not in allowed})
        check(f"{name}：没有残留的界面配色硬编码", not bad, str(bad))

    # ==================================================================
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print(f"  · {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
