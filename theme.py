#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 外观主题
============================
需求 6：整体简约浅色、圆角控件、间距合理、轻量不花哨。

这里集中放两样东西：
* `PALETTE`：全套配色（浅色为主，深色可选）
* `stylesheet()`：一次性生成整份 QSS，所有控件共用，避免每个窗口各写一套
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 配色
# --------------------------------------------------------------------------
LIGHT = {
    "bg": "#F5F6F8",            # 窗口底
    "surface": "#FFFFFF",       # 卡片
    "surface_alt": "#FAFBFC",
    "hover": "#F1F3F7",
    "pressed": "#E7EAF0",
    "border": "#E6E8EC",
    "border_strong": "#D7DAE0",
    "text": "#1D2129",
    "text_sub": "#6B7280",
    "text_faint": "#9AA1AC",
    "accent": "#4F6BED",
    "accent_hover": "#6180F5",
    "accent_pressed": "#3F58D6",
    "accent_soft": "#EDF1FE",
    "success": "#12A150",
    "success_soft": "#E9F7EF",
    "warn": "#C77700",
    "warn_soft": "#FDF3E3",
    "danger": "#D93025",
    "danger_soft": "#FDECEA",
    "highlight": "#FFE9A8",     # 搜索命中底色
    "shadow": "#B9C0CC",
    # 上拉菜单（收纳面板）用半透明底色，让桌面微微透出来，观感更轻
    "popup": "rgba(255, 255, 255, 0.90)",
    "popup_alt": "rgba(247, 249, 252, 0.86)",
    "popup_border": "rgba(15, 23, 42, 0.10)",
}

DARK = {
    "bg": "#17191E",
    "surface": "#1F2228",
    "surface_alt": "#24272E",
    "hover": "#2A2E36",
    "pressed": "#31363F",
    "border": "#2E323A",
    "border_strong": "#3B414B",
    "text": "#E9EBEF",
    "text_sub": "#9CA3AF",
    "text_faint": "#6F7681",
    "accent": "#7089FF",
    "accent_hover": "#8399FF",
    "accent_pressed": "#5F76E6",
    "accent_soft": "#252B3D",
    "success": "#35C97E",
    "success_soft": "#1B2A22",
    "warn": "#E0A33F",
    "warn_soft": "#2B2418",
    "danger": "#F2685F",
    "danger_soft": "#2D1E1D",
    "highlight": "#7A6520",
    "shadow": "#0B0D10",
    # 上拉菜单（收纳面板）用半透明底色
    "popup": "rgba(31, 34, 40, 0.92)",
    "popup_alt": "rgba(38, 42, 50, 0.88)",
    "popup_border": "rgba(255, 255, 255, 0.12)",
}

RADIUS = 10
RADIUS_SMALL = 7
# 悬浮玻璃卡片用的大圆角（主面板 + 收纳面板共用）
GLASS_RADIUS = 22
FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'

# --------------------------------------------------------------------------
# 主面板：悬浮磨砂玻璃卡片
# --------------------------------------------------------------------------
# 单独一份，**不跟 LIGHT/DARK 走**：需求要的是"半透明深色 + 模糊"的悬浮卡片，
# 浅色主题下把它做成白底就把"磨砂玻璃"的味道丢掉了。
# 这里所有底色都带 alpha——留出透明度，好让 DWM 的磨砂（见 acrylic.py）
# 透上来；不透明的话磨砂就被自己的底色盖住了。
GLASS = {
    # 卡片底（配合磨砂）。注意它和 DWM 的着色是**两层**深色，都调浓就成了一块
    # 黑板：这里 0.58 + panel.GLASS_TINT_ALPHA 0.26 叠出来约等于 0.69 的观感，
    # 既能看清字，又明显透得出背后的东西。
    "card": "rgba(24, 26, 32, 0.58)",
    "card_border": "rgba(255, 255, 255, 0.12)",
    "surface": "rgba(255, 255, 255, 0.06)",    # 内部卡片 / 列表底
    "surface_alt": "rgba(255, 255, 255, 0.04)",
    "hover": "rgba(255, 255, 255, 0.10)",
    "pressed": "rgba(255, 255, 255, 0.16)",
    "border": "rgba(255, 255, 255, 0.10)",
    "border_strong": "rgba(255, 255, 255, 0.20)",
    "text": "#F3F5F9",
    "text_sub": "#C3CAD6",
    "text_faint": "#98A1B0",
    "accent": "#8CA2FF",
    "accent_hover": "#A0B2FF",
    "accent_pressed": "#7590F5",
    "accent_soft": "rgba(140, 162, 255, 0.22)",
    "success": "#4FD695",
    "success_soft": "rgba(79, 214, 149, 0.18)",
    "warn": "#F2BC6A",
    "warn_soft": "rgba(242, 188, 106, 0.16)",
    "danger": "#FF9088",
    "danger_soft": "rgba(255, 144, 136, 0.18)",
    "highlight": "rgba(255, 214, 102, 0.32)",
    "shadow": "rgba(0, 0, 0, 0.50)",
    "popup": "rgba(24, 26, 32, 0.72)",
    "popup_alt": "rgba(255, 255, 255, 0.06)",
    "popup_border": "rgba(255, 255, 255, 0.12)",
}

# DWM 磨砂的着色。要和 GLASS['card'] 对齐着看：
# 这两层**都**是深色，都调浓就会叠成一块黑板。
# 0.58（卡片底）+ 0.26（DWM 着色）叠出来约等于 0.69 的观感：
# 既看得清字，又明显透得出背后的东西。
GLASS_TINT = "#181A20"
GLASS_TINT_ALPHA = 0.26

# 拿不到磨砂（老系统 / 被策略挡住）时，卡片底色加浓一档——
# 没有模糊还那么透，文字会看不清。
GLASS_FALLBACK = ("background: rgba(24, 26, 32, 0.90);"
                  " border-color: rgba(255, 255, 255, 0.14);")


def palette(dark: bool = False) -> dict:
    return dict(DARK if dark else LIGHT)


def glass_palette() -> dict:
    """玻璃卡片**内部控件**用的配色（深色 + GLASS 覆盖）。

    和 `palette(dark)` 的区别：玻璃卡片恒定深色，不跟明暗主题走，
    所以里面的卡片文字/高亮不能拿浅色调色板，否则深底配深字。
    """
    c = dict(DARK)
    c.update(GLASS)
    return c


def glass_palette_roles() -> dict:
    """玻璃卡片要用的 `QPalette` 颜色。

    光有 QSS 不够：QSS 只覆盖写到的控件，没写到的（QTabBar 的空白、
    表头间隙、滚动条槽…）会回落到**系统调色板**——那是浅色的，
    在深色玻璃上就是一块刺眼的白。所以调色板也要跟着换深色。
    """
    return {
        "window": "#181A20",
        "base": "#181A20",
        "alternate": "#1E2128",
        "text": GLASS["text"],
        "sub": GLASS["text_faint"],
        "button": "#22252C",
        "highlight": GLASS["accent"],
        "highlight_text": "#FFFFFF",
    }


def stylesheet(dark: bool = False, *, glass: bool = False) -> str:
    """生成整份 QSS。

    glass=True 时把配色换成 `GLASS`（半透明深色），并额外加上两张悬浮卡片的
    规则——磨砂玻璃外观靠它 + `acrylic.py` 的 DWM 模糊一起实现。

    两张卡片：
    * `#MainCard` —— 主面板
    * `#Popup`    —— 收纳面板（Dock 第一个控件点开的那个上拉浮层）

    ⚠️ 玻璃规则块必须放在**整份样式表的最后**。放在中间的话，后面那些
    `#Popup { background: ... }` 之类的普通规则会把玻璃规则盖掉——
    玻璃看起来"没生效"，其实是被后写的规则赢了。
    """
    c = palette(dark)
    if glass:
        c.update(GLASS)

    glass_block = ""
    if glass:
        glass_block = f"""
/* ========== 悬浮磨砂玻璃卡片（主面板 + 收纳面板） ========== */
/* 顶层窗口自己不画底（画了就把磨砂盖住了），深色半透明只画在这两张卡片上 */
#MainPanel, #BrowserRoot {{ background: transparent; }}
#MainCard, #Popup {{
    background: {c['card']};
    border: 1px solid {c['card_border']};
    border-radius: {GLASS_RADIUS}px;
}}
/* 卡片里的顶栏/底栏是**内嵌**的，圆角要比卡片小 1px（卡片有 1px 边框），
   否则它们的直角会戳到卡片圆角外面去 */
#Toolbar {{
    border-top-left-radius: {GLASS_RADIUS - 1}px;
    border-top-right-radius: {GLASS_RADIUS - 1}px;
}}
#FooterBar {{
    border-bottom-left-radius: {GLASS_RADIUS - 1}px;
    border-bottom-right-radius: {GLASS_RADIUS - 1}px;
}}
/* 玻璃卡片里的树 / 网格：底色必须透，否则会在卡片上糊一块不透明的白 */
QTreeWidget {{
    background: transparent;
    border: none;
    alternate-background-color: transparent;
}}
QTreeWidget::item {{ border-radius: 6px; padding: 3px 4px; }}
QTreeWidget::item:hover {{ background: {c['hover']}; }}
QTreeWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: {c['surface_alt']};
    color: {c['text_faint']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 6px 8px;
}}
QTabWidget::pane {{ background: {c['surface']}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
/* ---------- 弹出类控件必须**不透明** ---------- */
/* 它们会继承这张玻璃样式表：底色一旦跟着半透明，右键菜单、消息框、
   提示气泡就会"看不见"。所以这里单独给一层不透明的深色底。 */
QMenu, QMessageBox {{
    background: #22252C;
    border: 1px solid {c['card_border']};
}}
QMenu::item {{ color: {c['text']}; }}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QMenu::separator {{ background: {c['border']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QToolTip {{
    background: #2C3038;
    color: {c['text']};
    border: 1px solid {c['card_border']};
}}
/* 无边框窗口没有系统标题栏，关闭按钮自己画一个 */
#GlassClose {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: {c['text_sub']};
    font-size: 11.25pt;
    padding: 1px 9px;
}}
#GlassClose:hover {{ background: rgba(255, 118, 108, 0.85); color: #FFFFFF; }}
#GlassClose:pressed {{ background: rgba(214, 84, 76, 0.95); color: #FFFFFF; }}
"""

    return f"""
/* ---------- 全局 ---------- */
* {{
    font-family: {FONT_FAMILY};
    font-size: 9.75pt;
    outline: none;
}}
QWidget {{
    color: {c['text']};
}}
QDialog, QMainWindow {{
    background: {c['bg']};
}}

/* ---------- 卡片容器 ---------- */
#Card, #Panel {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
}}

/* ---------- 上拉菜单（收纳面板）---------- */
#Popup {{
    background: {c['popup']};
    border: 1px solid {c['popup_border']};
    border-radius: {RADIUS + 6}px;
}}
#Toolbar {{
    background: {c['popup_alt']};
    border-bottom: 1px solid {c['popup_border']};
    border-top-left-radius: {RADIUS + 5}px;
    border-top-right-radius: {RADIUS + 5}px;
}}
#FooterBar {{
    background: {c['popup_alt']};
    border-top: 1px solid {c['popup_border']};
    border-bottom-left-radius: {RADIUS + 5}px;
    border-bottom-right-radius: {RADIUS + 5}px;
}}

/* ---------- 文字层级 ---------- */
#Title {{ font-size: 12.75pt; font-weight: 600; }}
#Subtitle, #Hint {{ color: {c['text_faint']}; font-size: 9pt; }}
#SectionTitle {{ font-size: 9.75pt; font-weight: 600; }}
#Muted {{ color: {c['text_sub']}; }}
#StatValue {{ font-size: 16.5pt; font-weight: 600; color: {c['text']}; }}
#StatLabel {{ font-size: 9pt; color: {c['text_faint']}; }}
#AccentText {{ color: {c['accent']}; font-weight: 600; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: {RADIUS_SMALL}px;
    padding: 7px 15px;
    color: {c['text']};
}}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; background: {c['surface_alt']}; }}

QPushButton#Primary {{
    background: {c['accent']};
    border: 1px solid {c['accent']};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton#Primary:pressed {{ background: {c['accent_pressed']}; }}
QPushButton#Primary:disabled {{ background: {c['border_strong']}; border-color: {c['border_strong']}; color: {c['surface']}; }}

QPushButton#Danger {{
    background: {c['danger_soft']};
    border: 1px solid {c['danger_soft']};
    color: {c['danger']};
    font-weight: 600;
}}
QPushButton#Danger:hover {{ background: {c['danger']}; border-color: {c['danger']}; color: #FFFFFF; }}

QPushButton#Soft {{
    background: {c['accent_soft']};
    border: 1px solid {c['accent_soft']};
    color: {c['accent']};
    font-weight: 600;
}}
QPushButton#Soft:hover {{ background: {c['accent']}; border-color: {c['accent']}; color: #FFFFFF; }}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {c['text_sub']};
    padding: 6px 10px;
}}
QPushButton#Ghost:hover {{ background: {c['hover']}; color: {c['text']}; }}

/* 图标按钮（视图切换） */
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_SMALL}px;
    padding: 5px;
    color: {c['text_sub']};
}}
QToolButton:hover {{ background: {c['hover']}; color: {c['text']}; }}
QToolButton:checked {{
    background: {c['accent_soft']};
    border-color: {c['accent_soft']};
    color: {c['accent']};
}}

/* ---------- 输入框 ---------- */
QLineEdit {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: {RADIUS_SMALL}px;
    padding: 7px 11px;
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
}}
QLineEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit#Search {{
    background: {c['surface']};
    padding-left: 30px;
    border-radius: {RADIUS_SMALL + 4}px;
}}

/* ---------- 复选框 ---------- */
QCheckBox {{ spacing: 8px; color: {c['text']}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {c['border_strong']};
    border-radius: 4px;
    background: {c['surface']};
}}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    image: none;
}}

/* ---------- 列表 / 图标网格 ---------- */
QListWidget {{
    background: {c['surface']};
    border: none;
    border-radius: {RADIUS}px;
    padding: 6px;
}}
QListWidget::item {{
    border-radius: {RADIUS_SMALL}px;
    color: {c['text']};
}}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{
    background: {c['accent_soft']};
    color: {c['text']};
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['border_strong']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['text_faint']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border_strong']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------- 菜单 ---------- */
QMenu {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS_SMALL}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px;
    border-radius: 5px;
    color: {c['text']};
}}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QMenu::item:disabled {{ color: {c['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* ---------- 工具提示 ---------- */
QToolTip {{
    background: {c['text']};
    color: {c['surface']};
    border: none;
    border-radius: 5px;
    padding: 5px 8px;
}}

/* ---------- 消息框 ---------- */
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}

/* ---------- 滚动区域 ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---------- 分隔线 ---------- */
#Divider {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
#VerticalDivider {{ background: {c['border']}; max-width: 1px; min-width: 1px; border: none; }}

/* ---------- 底部菜单栏（Dock） ---------- */
/* 需求：菜单栏做成**纯透明**——只留「桌面整理」控件和常用软件的图标浮在桌面上，
   不要那条深色圆角底板。窗口本身已经开了 `WA_TranslucentBackground`，
   所以这里把底和边框都去掉，透出来的就是真实的桌面。
   代价：图标底下没有暗色托着，浅色壁纸上的浅色元素会看不见。所以
   悬停底色 / 控制按钮统一改用**中性半透明灰**（对浅色和深色壁纸都辨得出来），
   而不是纯白（浅壁纸上消失）或纯黑（深壁纸上消失）。 */
#DockSurface {{
    background: transparent;
    border: none;
    border-radius: 18px;
}}
#DockIcon {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 0px;
    /* 底板透明之后，图标下面的名字要自己扛住可读性。
       绝大多数桌面壁纸是中到深的，所以用浅色字；再深就靠 tooltip。 */
    color: #EAF0FA;
}}
#DockIcon:hover {{
    background: rgba(84, 90, 104, 0.42);
    border-color: rgba(255, 255, 255, 60);
}}
#DockIcon:pressed {{
    background: rgba(84, 90, 104, 0.62);
}}
/* 长按拖动排序时，插在目标位置的那根指示线。
   底板是纯透明的，所以颜色必须自己够亮——用品牌蓝打底 + 一圈白边，
   浅色壁纸和深色壁纸上都看得见。
   ⚠️ 控件宽度要给够（dock.py 里设的 4px）：QSS 的 border 画在控件**内部**，
   只给 2px 的话左右白边就把中间占满了，蓝色一点都露不出来。 */
#DockDropLine {{
    background: {c['accent']};
    border: 1px solid rgba(255, 255, 255, 190);
    border-radius: 2px;
}}
#DockNav {{
    background: rgba(52, 56, 66, 0.34);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 9px;
    color: #F2F4F8;
    font-size: 9pt;
}}
#DockNav:hover {{ background: rgba(52, 56, 66, 0.62); border-color: rgba(255, 255, 255, 90); }}
#DockNav:disabled {{ color: rgba(242, 244, 248, 90); background: rgba(52, 56, 66, 0.16); }}
#DockAdd, #DockDel {{
    background: rgba(52, 56, 66, 0.34);
    border: 1px dashed rgba(255, 255, 255, 90);
    border-radius: 10px;
    color: #F2F4F8;
    font-size: 11.25pt;
    font-weight: 600;
}}
#DockAdd:hover, #DockDel:hover {{
    background: rgba(52, 56, 66, 0.62);
    border-color: rgba(255, 255, 255, 150);
}}
#DockAdd:disabled, #DockDel:disabled {{
    color: rgba(242, 244, 248, 90);
    background: rgba(52, 56, 66, 0.16);
    border-color: rgba(255, 255, 255, 40);
}}

/* ---------- 常用启动小快捷方式（图标+名称） ---------- */
#AppButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    color: {c['text']};
    font-size: 8.25pt;
    padding: 2px;
}}
#AppButton:hover {{
    background: {c['hover']};
    border-color: {c['border']};
}}
#AppButton:pressed {{
    background: {c['pressed']};
}}
/* 唯一的控制按钮：管理（原来是「＋添加」+「－删除」两个） */
#AppManage {{
    background: transparent;
    border: 1px dashed {c['border_strong']};
    border-radius: 10px;
    color: {c['text_sub']};
    font-size: 8.25pt;
}}
#AppManage:hover {{
    background: {c['hover']};
    border-color: {c['accent']};
    color: {c['accent']};
}}
#AppManage:checked {{
    background: {c['accent_soft']};
    border: 1px solid {c['accent']};
    color: {c['accent']};
}}
#TileName {{ font-size: 9pt; }}

/* ---------- 管理模式下卡片角上的「＋ / －」 ---------- */
/* 20×20 的小圆钮。给足对比度：它压在图标上，底色太淡就分不清是按钮还是图标的一部分。 */
#BadgeAdd, #BadgeRemove {{
    border-radius: 10px;
    font-size: 11pt;
    font-weight: 700;
    padding: 0px;
}}
#BadgeAdd {{
    background: {c['accent']};
    color: #FFFFFF;
    border: 1px solid rgba(255, 255, 255, 190);
}}
#BadgeRemove {{
    background: {c['danger']};
    color: #2A1310;
    border: 1px solid rgba(255, 255, 255, 190);
}}
#BadgeAdd:hover, #BadgeRemove:hover {{
    border: 2px solid #FFFFFF;
}}
/* ---------- 文件网格卡片 ---------- */
#FileTile {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}}
#FileTile:hover {{
    background: {c['hover']};
}}

/* ---------- 提示条 ---------- */
#Notice {{
    background: {c['warn_soft']};
    color: {c['warn']};
    border: 1px solid {c['warn_soft']};
    border-radius: {RADIUS_SMALL}px;
    padding: 9px 13px;
    font-size: 9pt;
}}

/* ---------- 徽标 ---------- */
#Badge {{
    background: {c['accent_soft']};
    color: {c['accent']};
    border-radius: 9px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}}
#BadgeOk {{ background: {c['success_soft']}; color: {c['success']}; border-radius: 9px; padding: 3px 10px; font-size: 9pt; font-weight: 600; }}
#BadgeWarn {{ background: {c['warn_soft']}; color: {c['warn']}; border-radius: 9px; padding: 3px 10px; font-size: 9pt; font-weight: 600; }}
#BadgeDanger {{ background: {c['danger_soft']}; color: {c['danger']}; border-radius: 9px; padding: 3px 10px; font-size: 9pt; font-weight: 600; }}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background: {c['border']};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}

/* ---------- 标签页（设置窗用） ---------- */
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: {RADIUS}px; background: {c['surface']}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {c['text_sub']};
    padding: 8px 16px;
    margin-right: 4px;
    border-radius: {RADIUS_SMALL}px;
}}
QTabBar::tab:hover {{ background: {c['hover']}; }}
QTabBar::tab:selected {{ background: {c['accent_soft']}; color: {c['accent']}; font-weight: 600; }}

/* ---------- 下拉框 ---------- */
QComboBox {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: {RADIUS_SMALL}px;
    padding: 6px 10px;
}}
QComboBox:hover {{ border-color: {c['accent']}; }}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS_SMALL}px;
    selection-background-color: {c['accent_soft']};
    selection-color: {c['accent']};
    padding: 4px;
}}
{glass_block}"""
