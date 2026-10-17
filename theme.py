#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 视觉设计系统（Design System）
================================================

把散落在各处的颜色 / 圆角 / 字号 / 时长收敛成**一套** Design Token，
再由这一份 Token 统一生成整份 QSS。主面板、收纳面板、设置窗、Dock、
右键菜单共用同一份样式表 —— 不再各写一套，也不会出现"这里圆角 9px、
那里 10px、按钮又比输入框矮 2px"这种事。

三层结构
--------
1. **语义色彩 Token**（`COLOR_TOKENS`）—— 颜色只按"用途"命名，
   浅色 / 深色 / 玻璃各给一套值：
   `bg / surface / surface_hover / border / text_primary / text_secondary /
    text_muted / primary / primary_hover / success / warning / danger …`
   想换配色只动这一张表。

2. **尺度 Token** —— 圆角 `RADIUS`、阴影 `SHADOW`、控件高度 `CONTROL`、
   字号 `FONT_SIZE`、字重 `FONT_WEIGHT`、动画时长 `DURATION`、缓动 `EASING`。

3. **扁平调色板**（`LIGHT` / `DARK` / `GLASS`）—— 由第 1 层展开而来，
   同时保留历史键名（`accent` / `text_sub` / `hover` …），老调用点无需改动。

`stylesheet()` 是唯一的 QSS 出口。

设计方向（不要改）
------------------
深色 / 半透明 / 圆角 / 蓝紫强调。「现代 Windows 桌面工具」——克制、高级、安静。
不做赛博朋克、不做游戏 UI、不铺霓虹、不过度玻璃与渐变。
"""

from __future__ import annotations

# ==========================================================================
# 一、语义色彩 Token
# ==========================================================================
# 命名规则：只描述"这块颜色是干什么用的"，不带明暗、不带控件名。
# 三套 scheme 用同一组键，`stylesheet()` 才能只换 token 不换规则。
#
# ⚠️ `glass` 是**恒定深色**的一套，不跟明暗主题走：需求要的就是
#    "半透明深色 + 磨砂"的悬浮卡片，浅色主题下把它做成白底就没味道了。
COLOR_TOKENS = {
    # ---------------- 浅色 ----------------
    "light": {
        # 底与面
        "bg": "#F5F6F8",                  # 窗口底（Background）
        "surface": "#FFFFFF",             # 卡片 / 控件底（Surface）
        "surface_alt": "#FAFBFC",         # 次级面（表头 / 斑马纹）
        "surface_hover": "#F1F3F7",       # 悬停（Surface Hover）
        "surface_pressed": "#E7EAF0",     # 按下
        "border": "#E6E8EC",              # 常规描边（Border）
        "border_strong": "#D7DAE0",       # 控件描边（输入框 / 按钮）
        # 文字
        "text_primary": "#1D2129",        # 正文（Text Primary）
        "text_secondary": "#6B7280",      # 次要（Text Secondary）
        "text_muted": "#9AA1AC",          # 弱化 / 占位（Text Muted）
        # 主色
        "primary": "#4F6BED",             # 品牌蓝紫（Primary）
        "primary_hover": "#6180F5",       # 悬停（Primary Hover）
        "primary_pressed": "#3F58D6",
        "primary_soft": "#EDF1FE",        # 主色淡底（选中态）
        # 语义色
        "success": "#12A150",
        "success_soft": "#E9F7EF",
        "warning": "#C77700",
        "warning_soft": "#FDF3E3",
        "danger": "#D93025",
        "danger_soft": "#FDECEA",
        # 其它
        "highlight": "#FFE9A8",           # 搜索命中底色
        "shadow": "#B9C0CC",
        "popup": "rgba(255, 255, 255, 0.90)",
        "popup_alt": "rgba(247, 249, 252, 0.86)",
        "popup_border": "rgba(15, 23, 42, 0.10)",
        # Tooltip / Toast 共用（"反色药丸"：深底浅字）
        "toast_bg": "#1D2129",
        "toast_text": "#F5F6F8",
    },
    # ---------------- 深色 ----------------
    "dark": {
        "bg": "#17191E",
        "surface": "#1F2228",
        "surface_alt": "#24272E",
        "surface_hover": "#2A2E36",
        "surface_pressed": "#31363F",
        "border": "#2E323A",
        "border_strong": "#3B414B",
        "text_primary": "#E9EBEF",
        "text_secondary": "#9CA3AF",
        "text_muted": "#6F7681",
        "primary": "#7089FF",
        "primary_hover": "#8399FF",
        "primary_pressed": "#5F76E6",
        "primary_soft": "#252B3D",
        "success": "#35C97E",
        "success_soft": "#1B2A22",
        "warning": "#E0A33F",
        "warning_soft": "#2B2418",
        "danger": "#F2685F",
        "danger_soft": "#2D1E1D",
        "highlight": "#7A6520",
        "shadow": "#0B0D10",
        "popup": "rgba(31, 34, 40, 0.92)",
        "popup_alt": "rgba(38, 42, 50, 0.88)",
        "popup_border": "rgba(255, 255, 255, 0.12)",
        "toast_bg": "#31363F",
        "toast_text": "#E9EBEF",
    },
    # ---------------- 玻璃卡片（恒定深色）----------------
    "glass": {
        # 卡片底（配合磨砂）。注意它和 DWM 的着色是**两层**深色，都调浓就成
        # 了一块黑板：这里 0.58 + panel.GLASS_TINT_ALPHA 0.26 叠出来约等于
        # 0.69 的观感，既能看清字，又明显透得出背后的东西。
        "card": "rgba(24, 26, 32, 0.58)",
        "card_border": "rgba(255, 255, 255, 0.12)",
        "bg": "#181A20",
        "surface": "rgba(255, 255, 255, 0.06)",    # 内部卡片 / 列表底
        "surface_alt": "rgba(255, 255, 255, 0.04)",
        "surface_hover": "rgba(255, 255, 255, 0.10)",
        "surface_pressed": "rgba(255, 255, 255, 0.16)",
        "border": "rgba(255, 255, 255, 0.10)",
        "border_strong": "rgba(255, 255, 255, 0.20)",
        "text_primary": "#F3F5F9",
        "text_secondary": "#C3CAD6",
        "text_muted": "#98A1B0",
        "primary": "#8CA2FF",
        "primary_hover": "#A0B2FF",
        "primary_pressed": "#7590F5",
        "primary_soft": "rgba(140, 162, 255, 0.22)",
        "success": "#4FD695",
        "success_soft": "rgba(79, 214, 149, 0.18)",
        "warning": "#F2BC6A",
        "warning_soft": "rgba(242, 188, 106, 0.16)",
        "danger": "#FF9088",
        "danger_soft": "rgba(255, 144, 136, 0.18)",
        "highlight": "rgba(255, 214, 102, 0.32)",
        "shadow": "rgba(0, 0, 0, 0.50)",
        "popup": "rgba(24, 26, 32, 0.72)",
        "popup_alt": "rgba(255, 255, 255, 0.06)",
        "popup_border": "rgba(255, 255, 255, 0.12)",
        "toast_bg": "#2C3038",
        "toast_text": "#F3F5F9",
    },
}

# 语义 token → 历史扁平键名。老代码（widgets / dock / panel / …）读的是
# `accent` / `text_sub` / `hover` 这些短名，这里做一次映射，两边同时可用：
# 新代码写语义名，老代码不用动。
_LEGACY_KEYS = {
    "surface_hover": "hover",
    "surface_pressed": "pressed",
    "text_primary": "text",
    "text_secondary": "text_sub",
    "text_muted": "text_faint",
    "primary": "accent",
    "primary_hover": "accent_hover",
    "primary_pressed": "accent_pressed",
    "primary_soft": "accent_soft",
    "warning": "warn",
    "warning_soft": "warn_soft",
}


def _flatten(scheme: dict) -> dict:
    """把一套语义 token 展开成扁平调色板（含历史键名）。"""
    flat = dict(scheme)
    for semantic, legacy in _LEGACY_KEYS.items():
        if semantic in scheme:
            flat[legacy] = scheme[semantic]
    return flat


# ==========================================================================
# 二、尺度 Token
# ==========================================================================
# 圆角：从最小的复选框到最大的玻璃卡片，全部从这一把尺子上取。
# 键名带语义（用在哪），不写死数值，改一处全局生效。
RADIUS = {
    "xs": 4,             # 复选框指示器
    "sm": 6,             # 菜单项 / 提示气泡 / 树行 / 滚动条滑块
    "md": 7,             # 按钮 / 输入框 / 下拉框 / 关闭按钮
    "lg": 10,            # 卡片 / 列表 / 图标钮 / 徽标 / 拖放高亮
    "xl": 12,            # Dock 图标
    "popup": 16,         # 上拉收纳面板
    "popup_inner": 15,   # 面板里的顶栏 / 底栏（比面板小 1px，免得直角戳出去）
    "dock": 18,          # Dock 底板
    "card": 22,          # 悬浮磨砂玻璃卡片（主面板 + 收纳面板）
}

# 历史别名：`RADIUS_SMALL` 原来是 7，`RADIUS` 原来是 10（int）。
RADIUS_SMALL = RADIUS["md"]
RADIUS_MD = RADIUS["lg"]

# 阴影：QSS **不支持** box-shadow，所以这里是给 QGraphicsDropShadowEffect 用的
# 参数（`drop_shadow()` 消费）。分三档，避免每个窗口自己拍脑袋写模糊半径。
SHADOW = {
    "sm": {"blur": 14, "dx": 0, "dy": 3, "alpha": 46},
    "md": {"blur": 28, "dx": 0, "dy": 8, "alpha": 62},
    "lg": {"blur": 48, "dx": 0, "dy": 16, "alpha": 82},
}

# 控件高度：按钮 / 输入框 / 下拉框共用一个 min-height，加上各自的
# padding + 边框，三种控件的**自然高度完全相同**（= CONTROL['height']）。
CONTROL = {
    "height": 36,        # 目标自然高度（min_height + padding + 边框）
    "min_height": 20,    # QSS 里的 min-height（20 + 7*2 + 1*2 = 36）
    "icon_size": 18,     # 控件内小图标
    "focus_ring": 1,     # 聚焦描边宽度
}

# 字号：全部用 pt（跟随系统 DPI 缩放），单位换算见 dev/fix_font_units.py。
FONT_SIZE = {
    "xs": 8.25,      # 紧凑标签（常用软件名 / 管理钮）
    "sm": 9.0,       # 辅助 / 提示 / 徽标
    "base": 9.75,    # 正文（全局默认）
    "md": 11.0,      # 角标（＋ / －）
    "close": 11.25,  # 关闭按钮 / 大号加号
    "lg": 12.75,     # 标题
    "xl": 16.5,      # 统计数字
}
FONT_WEIGHT = {
    "regular": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
}

# 动画时长（毫秒）。Qt 的 QSS 没有 transition，这些值给代码里的
# QTimer / 弹簧动画用；弹簧本身的手感在 springs.py 里。
DURATION = {
    "fast": 120,        # 悬停 / 聚焦反馈
    "normal": 180,      # 面板显隐
    "slow": 260,        # 较大的位移
    "settle": 60,       # Dock 尺寸重算的防抖
    "tick": 16,         # 弹簧动画帧间隔（≈60fps）
    "highlight": 1200,  # 选中高亮停留
}
# 标准缓动曲线（Qt 端由 springs.py 的弹簧实现，这里只作记录 / 给未来用）
EASING = "cubic-bezier(0.22, 0.80, 0.20, 1.00)"

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'

# 文件类型占位色：取不到真实图标时，用这个颜色画一个"首字色块"兜底。
# 放在主题里是为了和 `primary` 同源——不再两个文件各写一遍 #4F6BED。
FILE_TYPE_COLORS = {
    "shortcut": "#4F6BED", "program": "#5B6B8C", "image": "#E09A3E",
    "video": "#8B5CF6", "audio": "#E0559A", "document": "#4F6BED",
    "sheet": "#12A150", "slide": "#D9634F", "archive": "#0EA5E9",
    "code": "#14B8A6", "font": "#A855F7", "folder": "#E3B341", "other": "#94A3B8",
    "desktop": "#4F6BED",
}
# 取不到类型时的兜底色（和 FILE_TYPE_COLORS['other'] 同源）
FALLBACK_TILE_COLOR = FILE_TYPE_COLORS["other"]

# ==========================================================================
# 三、扁平调色板（由语义 token 展开，保留历史键名）
# ==========================================================================
LIGHT = _flatten(COLOR_TOKENS["light"])
DARK = _flatten(COLOR_TOKENS["dark"])
GLASS = _flatten(COLOR_TOKENS["glass"])

# 品牌主色（供绘图类代码取用，别的地方不要再写死色值）
BRAND_ACCENT = LIGHT["accent"]

# DWM 磨砂的着色。要和 GLASS['card'] 对齐着看：
# 这两层**都**是深色，都调浓就会叠成一块黑板。
GLASS_TINT = "#181A20"
GLASS_TINT_ALPHA = 0.26
GLASS_RADIUS = RADIUS["card"]

# 拿不到磨砂（老系统 / 被策略挡住）时，卡片底色加浓一档——
# 没有模糊还那么透，文字会看不清。
GLASS_FALLBACK = ("background: rgba(24, 26, 32, 0.90);"
                  " border-color: rgba(255, 255, 255, 0.14);")


def palette(dark: bool = False) -> dict:
    """取扁平调色板（浅色 / 深色）。"""
    return dict(DARK if dark else LIGHT)


def tokens(scheme: str = "light") -> dict:
    """取**语义** token（`light` / `dark` / `glass`）。

    和 `palette()` 的区别：这里只有语义键（`text_primary` / `surface_hover` …），
    不带历史短名，适合新代码用。
    """
    return dict(COLOR_TOKENS[scheme])


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


def drop_shadow(widget, level: str = "md", *, color: "str | None" = None):
    """给控件挂一档统一阴影（`sm` / `md` / `lg`）。

    QSS 没有 box-shadow，阴影只能走 `QGraphicsDropShadowEffect`。这里把
    参数收在 `SHADOW` 里，避免每个窗口自己拍一个模糊半径。返回 effect
    本身，方便调用方再改；不可用时返回 None（不抛异常）。
    """
    spec = SHADOW.get(level) or SHADOW["md"]
    try:
        from qt_compat import QColor, QGraphicsDropShadowEffect
    except Exception:                       # 没有 Qt 环境（纯逻辑测试）
        return None
    try:
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(spec["blur"])
        effect.setOffset(spec["dx"], spec["dy"])
        effect.setColor(QColor(color or LIGHT["shadow"], spec["alpha"]))
        widget.setGraphicsEffect(effect)
        return effect
    except Exception:
        return None


def token_table() -> "list[tuple[str, str, str, str]]":
    """把三套色彩 token 摊平成表格，供文档 / 自检用。

    返回 `[(token 名, 浅色, 深色, 玻璃), ...]`，顺序按浅色表的定义顺序。
    """
    rows = []
    for name, light in COLOR_TOKENS["light"].items():
        rows.append((name, light,
                     COLOR_TOKENS["dark"].get(name, ""),
                     COLOR_TOKENS["glass"].get(name, "")))
    for name in ("card", "card_border"):     # 玻璃专属的两个键
        rows.append((name, "", "", COLOR_TOKENS["glass"].get(name, "")))
    return rows


# ==========================================================================
# 四、QSS 生成
# ==========================================================================
def stylesheet(dark: bool = False, *, glass: bool = False) -> str:
    """生成整份 QSS（唯一的样式出口）。

    `glass=True` 时把配色换成 `GLASS`（半透明深色），并额外加上两张悬浮卡片的
    规则——磨砂玻璃外观靠它 + `acrylic.py` 的 DWM 模糊一起实现。

    两张卡片：
    * `#MainCard` —— 主面板
    * `#Popup`    —— 收纳面板（Dock 第一个控件点开的那个上拉浮层）

    ⚠️ 玻璃规则块必须放在**整份样式表的最后**。放在中间的话，后面那些
    `#Popup { background: ... }` 之类的普通规则会把玻璃规则盖掉——
    玻璃看起来"没生效"，其实是被后写的规则赢了。

    规则按**组件**分节（Button / Input / Checkbox / Tab / Card / Tooltip /
    Toast / Dialog / Menu …），每个组件都写全 `hover` / `focus` / `disabled`
    三态，这样主面板、管理页面、Dock、右键菜单才是同一套视觉。
    """
    c = palette(dark)
    if glass:
        c.update(GLASS)

    R, F, W = RADIUS, FONT_SIZE, FONT_WEIGHT

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
QHeaderView {{ background: transparent; border: none; }}
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
    background: {c['toast_bg']};
    color: {c['toast_text']};
    border: 1px solid {c['card_border']};
}}
/* 无边框窗口没有系统标题栏，关闭按钮自己画一个 */
#GlassClose {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R['md']}px;
    color: {c['text_sub']};
    font-size: {F['close']}pt;
    padding: 1px 9px;
}}
#GlassClose:hover {{ background: rgba(255, 118, 108, 0.85); color: #FFFFFF; }}
#GlassClose:pressed {{ background: rgba(214, 84, 76, 0.95); color: #FFFFFF; }}
"""

    return f"""
/* ==================================================================
   桌面收纳 · 统一视觉系统（由 theme.py 的 Design Token 生成）
   浅色 / 深色 / 玻璃共用同一套规则，只换 token
   ================================================================== */

/* ---------- 1. 全局 ---------- */
* {{
    font-family: {FONT_FAMILY};
    font-size: {F['base']}pt;
    outline: none;
}}
QWidget {{
    color: {c['text']};
}}
QDialog, QMainWindow {{
    background: {c['bg']};
}}
QWidget:disabled {{
    color: {c['text_faint']};
}}

/* ---------- 2. 文字层级 ---------- */
/* 三级：标题（#Title）> 分节标签（#SectionLabel）> 提示（#Hint）。
   分节标签专门用来给"常用启动"这类区块起名——比正文小一号、颜色更淡，
   既点明了这块是什么，又不会和卡片名字抢注意力。 */
#Title {{ font-size: {F['lg']}pt; font-weight: {W['semibold']}; }}
#Subtitle, #Hint {{ color: {c['text_faint']}; font-size: {F['sm']}pt; }}
#SectionLabel {{
    color: {c['text_faint']};
    font-size: {F['xs']}pt;
    font-weight: {W['semibold']};
}}
#SectionTitle {{ font-size: {F['base']}pt; font-weight: {W['semibold']}; }}
#Muted {{ color: {c['text_sub']}; }}
#StatValue {{ font-size: {F['xl']}pt; font-weight: {W['semibold']}; color: {c['text']}; }}
#StatLabel {{ font-size: {F['sm']}pt; color: {c['text_faint']}; }}
#AccentText {{ color: {c['accent']}; font-weight: {W['semibold']}; }}

/* ---------- 3. 卡片容器（Card）---------- */
#Card, #Panel {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {R['lg']}px;
}}

/* ---------- 4. 按钮（Button）---------- */
/* 基础款 = 次级按钮（描边）；#Primary / #Soft / #Danger / #Ghost 是变体。
   高度由 min-height + padding 统一算出来，和输入框一样高。 */
QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: {R['md']}px;
    padding: 7px 15px;
    min-height: {CONTROL['min_height']}px;
    color: {c['text']};
}}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:focus {{ border-color: {c['accent']}; }}
QPushButton:disabled {{
    color: {c['text_faint']};
    background: {c['surface_alt']};
    border-color: {c['border']};
}}

QPushButton#Primary {{
    background: {c['accent']};
    border: 1px solid {c['accent']};
    color: #FFFFFF;
    font-weight: {W['semibold']};
}}
QPushButton#Primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton#Primary:pressed {{ background: {c['accent_pressed']}; }}
QPushButton#Primary:disabled {{
    background: {c['border_strong']};
    border-color: {c['border_strong']};
    color: {c['surface']};
}}

QPushButton#Danger {{
    background: {c['danger_soft']};
    border: 1px solid {c['danger_soft']};
    color: {c['danger']};
    font-weight: {W['semibold']};
}}
QPushButton#Danger:hover {{ background: {c['danger']}; border-color: {c['danger']}; color: #FFFFFF; }}
QPushButton#Danger:disabled {{ background: {c['surface_alt']}; border-color: {c['border']}; color: {c['text_faint']}; }}

/* 提醒款（暖色）：用于"还原到桌面"这类**会改变现状、但不算危险**的操作。
   比 #Primary 安静、比普通描边按钮醒目——正好卡在中间那一档。 */
QPushButton#Warning {{
    background: {c['warn_soft']};
    border: 1px solid {c['warn_soft']};
    color: {c['warn']};
    font-weight: {W['semibold']};
}}
QPushButton#Warning:hover {{ background: {c['warn']}; border-color: {c['warn']}; color: #FFFFFF; }}
QPushButton#Warning:disabled {{ background: {c['surface_alt']}; border-color: {c['border']}; color: {c['text_faint']}; }}

QPushButton#Soft {{
    background: {c['accent_soft']};
    border: 1px solid {c['accent_soft']};
    color: {c['accent']};
    font-weight: {W['semibold']};
}}
QPushButton#Soft:hover {{ background: {c['accent']}; border-color: {c['accent']}; color: #FFFFFF; }}
QPushButton#Soft:disabled {{ background: {c['surface_alt']}; border-color: {c['border']}; color: {c['text_faint']}; }}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {c['text_sub']};
    padding: 6px 10px;
}}
QPushButton#Ghost:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton#Ghost:disabled {{ color: {c['text_faint']}; background: transparent; }}

/* 图标按钮（视图切换 / 工具栏） */
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R['md']}px;
    padding: 5px;
    color: {c['text_sub']};
}}
QToolButton:hover {{ background: {c['hover']}; color: {c['text']}; }}
QToolButton:pressed {{ background: {c['pressed']}; }}
QToolButton:checked {{
    background: {c['accent_soft']};
    border-color: {c['accent_soft']};
    color: {c['accent']};
}}
QToolButton:disabled {{ color: {c['text_faint']}; background: transparent; }}

/* ---------- 5. 输入框（Input）---------- */
QLineEdit, QTextEdit {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: {R['md']}px;
    padding: 7px 11px;
    min-height: {CONTROL['min_height']}px;
    color: {c['text']};
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QTextEdit:disabled {{
    color: {c['text_faint']};
    background: {c['surface_alt']};
    border-color: {c['border']};
}}
/* 搜索框：左侧的放大镜由 `QLineEdit.addAction(LeadingPosition)` 画在框内，
   Qt 会自己把文字让开，所以这里**不能**再写死 `padding-left`——
   写了就会在图标和文字之间多留一段谁也看不见的空档。 */
QLineEdit#Search {{
    background: {c['surface']};
    border-radius: {R['lg'] + 1}px;
}}
/* 聚焦：描边换成主色 + 一层很淡的主色底。
   ⚠️ 只改颜色，不改 border 宽度 / padding —— 聚焦时尺寸一点都不变，
   下面的网格不会跟着抖一下。 */
QLineEdit#Search:focus {{
    border-color: {c['accent']};
    background: {c['accent_soft']};
}}
QLineEdit#Search:disabled {{
    color: {c['text_faint']};
    background: {c['surface_alt']};
    border-color: {c['border']};
}}

QComboBox {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: {R['md']}px;
    padding: 7px 11px;
    min-height: {CONTROL['min_height']}px;
    color: {c['text']};
}}
QComboBox:hover {{ border-color: {c['accent']}; }}
QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox:disabled {{
    color: {c['text_faint']};
    background: {c['surface_alt']};
    border-color: {c['border']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {R['md']}px;
    selection-background-color: {c['accent_soft']};
    selection-color: {c['accent']};
    padding: 4px;
}}

/* ---------- 6. 复选框（Checkbox）---------- */
QCheckBox {{ spacing: 8px; color: {c['text']}; }}
QCheckBox:disabled {{ color: {c['text_faint']}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {c['border_strong']};
    border-radius: {R['xs']}px;
    background: {c['surface']};
}}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    image: none;
}}
QCheckBox::indicator:disabled {{
    background: {c['surface_alt']};
    border-color: {c['border']};
}}
QCheckBox::indicator:checked:disabled {{
    background: {c['border_strong']};
    border-color: {c['border_strong']};
}}

/* ---------- 7. 标签页（Tab）---------- */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: {R['lg']}px;
    background: {c['surface']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {c['text_sub']};
    padding: 8px 16px;
    margin-right: 4px;
    border-radius: {R['md']}px;
}}
QTabBar::tab:hover {{ background: {c['hover']}; color: {c['text']}; }}
QTabBar::tab:selected {{
    background: {c['accent_soft']};
    color: {c['accent']};
    font-weight: {W['semibold']};
}}
QTabBar::tab:disabled {{ color: {c['text_faint']}; }}

/* ---------- 8. 列表 / 图标网格 ---------- */
QListWidget {{
    background: {c['surface']};
    border: none;
    border-radius: {R['lg']}px;
    padding: 6px;
}}
QListWidget::item {{
    border-radius: {R['md']}px;
    color: {c['text']};
}}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{
    background: {c['accent_soft']};
    color: {c['text']};
}}
QListWidget::item:disabled {{ color: {c['text_faint']}; }}

QTreeWidget {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {R['lg']}px;
    alternate-background-color: {c['surface_alt']};
}}
QTreeWidget::item {{ border-radius: {R['sm']}px; padding: 3px 4px; color: {c['text']}; }}
QTreeWidget::item:hover {{ background: {c['hover']}; }}
QTreeWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QHeaderView::section {{
    background: {c['surface_alt']};
    color: {c['text_faint']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 6px 8px;
}}

/* ---------- 9. 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['border_strong']};
    border-radius: {R['sm']}px;
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
    border-radius: {R['sm']}px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c['text_faint']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------- 10. 菜单（Menu，含右键菜单）---------- */
QMenu {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {R['md']}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px;
    border-radius: {R['sm']}px;
    color: {c['text']};
}}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QMenu::item:disabled {{ color: {c['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* ---------- 11. 工具提示（Tooltip）+ 轻提示（Toast）---------- */
/* 两者共用一套"反色药丸"配色（toast_bg / toast_text）：
   浅色主题下是深底浅字，深色 / 玻璃下是深灰底浅字，都够醒目。 */
QToolTip {{
    background: {c['toast_bg']};
    color: {c['toast_text']};
    border: none;
    border-radius: {R['sm']}px;
    padding: 5px 8px;
}}
#Toast {{
    background: {c['toast_bg']};
    color: {c['toast_text']};
    border: none;
    border-radius: {R['md']}px;
    padding: 9px 14px;
    font-size: {F['sm']}pt;
}}
/* 成功 / 警告 / 危险三档和徽标（#BadgeOk …）用同一套"淡底 + 彩字"：
   整块铺满高饱和色在深色卡片上太吵，也违背"不要大面积用绿 / 红"。 */
#ToastOk {{
    background: {c['success_soft']};
    color: {c['success']};
    border: none;
    border-radius: {R['md']}px;
    padding: 9px 14px;
    font-size: {F['sm']}pt;
    font-weight: {W['semibold']};
}}
#ToastWarn {{
    background: {c['warn_soft']};
    color: {c['warn']};
    border: none;
    border-radius: {R['md']}px;
    padding: 9px 14px;
    font-size: {F['sm']}pt;
    font-weight: {W['semibold']};
}}
#ToastDanger {{
    background: {c['danger_soft']};
    color: {c['danger']};
    border: none;
    border-radius: {R['md']}px;
    padding: 9px 14px;
    font-size: {F['sm']}pt;
    font-weight: {W['semibold']};
}}

/* ---------- 12. 对话框（Dialog）---------- */
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QMessageBox QPushButton {{ min-width: 76px; }}

/* ---------- 13. 滚动区域 / 分隔线 ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
#Divider {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
#VerticalDivider {{ background: {c['border']}; max-width: 1px; min-width: 1px; border: none; }}

/* ---------- 14. 上拉菜单（收纳面板）---------- */
#Popup {{
    background: {c['popup']};
    border: 1px solid {c['popup_border']};
    border-radius: {R['popup']}px;
}}
#Toolbar {{
    background: {c['popup_alt']};
    border-bottom: 1px solid {c['popup_border']};
    border-top-left-radius: {R['popup_inner']}px;
    border-top-right-radius: {R['popup_inner']}px;
}}
#FooterBar {{
    background: {c['popup_alt']};
    border-top: 1px solid {c['popup_border']};
    border-bottom-left-radius: {R['popup_inner']}px;
    border-bottom-right-radius: {R['popup_inner']}px;
}}
/* ---- 顶栏图标钮（刷新 / 菜单 / 关闭）：次级操作，常态安静，悬停才浮出来 ----
   ⚠️ 这里必须用**子选择器** `>`，不能写成 `#Toolbar QToolButton`（后代选择器）。
   后者的特异性 (1,0,1) 高于 `#AppManage` (1,0,0)，会把"管理"控件的虚线描边
   整条盖掉；而"管理"控件挂在 apps_host 下面，不是 #Toolbar 的直接子控件，
   用 `>` 就天然把它排除在外了。 */
#Toolbar > QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R['md']}px;
    padding: 4px 10px;
    color: {c['text_sub']};
    font-size: {F['sm']}pt;
}}
#Toolbar > QToolButton:hover {{
    background: {c['hover']};
    border-color: {c['border']};
    color: {c['text']};
}}
#Toolbar > QToolButton:pressed {{ background: {c['pressed']}; }}
#Toolbar > QToolButton:disabled {{ color: {c['text_faint']}; background: transparent; }}
/* 关闭钮：悬停给一点"要关掉了"的提示色，和主面板那个关闭按钮呼应。
   写成复合选择器是为了让它的特异性压过上面那条通用规则。 */
#Toolbar > QToolButton#ToolbarClose:hover {{
    background: {c['danger']};
    border-color: {c['danger']};
    color: #FFFFFF;
}}
#Toolbar > QToolButton#ToolbarClose:pressed {{
    background: {c['danger']};
    border-color: {c['danger']};
    color: #FFFFFF;
}}

/* ---------- 15. 底部菜单栏（Dock）---------- */
/* 需求：菜单栏做成**纯透明**——只留「桌面整理」控件和常用软件的图标浮在桌面上，
   不要那条深色圆角底板。窗口本身已经开了 `WA_TranslucentBackground`，
   所以这里把底和边框都去掉，透出来的就是真实的桌面。
   代价：图标底下没有暗色托着，浅色壁纸上的浅色元素会看不见。所以
   悬停底色 / 控制按钮统一改用**中性半透明灰**（对浅色和深色壁纸都辨得出来），
   而不是纯白（浅壁纸上消失）或纯黑（深壁纸上消失）。 */
#DockSurface {{
    background: transparent;
    border: none;
    border-radius: {R['dock']}px;
}}
#DockIcon {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R['xl']}px;
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
/* 以下是 Dock 上控制按钮的历史样式（当前实现用 #AppManage / #AppButton，
   这两组保留下来，避免旧布局万一回来时没样式可套）。 */
#DockNav {{
    background: rgba(52, 56, 66, 0.34);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: {R['lg']}px;
    color: #F2F4F8;
    font-size: {F['sm']}pt;
}}
#DockNav:hover {{ background: rgba(52, 56, 66, 0.62); border-color: rgba(255, 255, 255, 90); }}
#DockNav:disabled {{ color: rgba(242, 244, 248, 90); background: rgba(52, 56, 66, 0.16); }}
#DockAdd, #DockDel {{
    background: rgba(52, 56, 66, 0.34);
    border: 1px dashed rgba(255, 255, 255, 90);
    border-radius: {R['lg']}px;
    color: #F2F4F8;
    font-size: {F['close']}pt;
    font-weight: {W['semibold']};
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

/* ---------- 16. 常用启动小快捷方式（图标 + 名称）---------- */
#AppButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R['lg']}px;
    color: {c['text']};
    font-size: {F['xs']}pt;
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
    border-radius: {R['lg']}px;
    color: {c['text_sub']};
    font-size: {F['xs']}pt;
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
/* 卡片名称：最多两行、超出省略号（省略逻辑在 widgets.ElidedLabel 里，
   因为 QSS 管不了"折行 + 末尾省略"这件事）。
   字号比正文小一档——网格里一屏几十个名字，跟着正文大小会太吵。 */
#TileName {{ font-size: {F['sm']}pt; color: {c['text']}; }}
#FileTile[selected="true"] #TileName {{ color: {c['accent']}; }}

/* ---------- 17. 管理模式下卡片角上的「＋ / －」 ---------- */
/* 20×20 的小圆钮。给足对比度：它压在图标上，底色太淡就分不清是按钮还是图标的一部分。 */
#BadgeAdd, #BadgeRemove {{
    border-radius: {R['lg']}px;
    font-size: {F['md']}pt;
    font-weight: {W['bold']};
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

/* ---------- 18. 文件网格卡片 ---------- */
/* 选中 / 悬停都由**动态属性**驱动（`setProperty("selected", True)` +
   `style().unpolish/polish`），不再往卡片上贴内联样式表——
   内联样式表的特异性高于全局规则，会把 `#FileTile:hover` 整条盖掉，
   于是"卡片悬停没反应"。 */
#FileTile {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R['lg']}px;
}}
/* 悬停只换一层很淡的底，**不动边框、不动尺寸** —— 整片网格不会跟着跳 */
#FileTile:hover {{
    background: {c['hover']};
}}
#FileTile[selected="true"] {{
    background: {c['accent_soft']};
    border-color: {c['accent']};
}}

/* ---------- 19. 提示条 ---------- */
#Notice {{
    background: {c['warn_soft']};
    color: {c['warn']};
    border: 1px solid {c['warn_soft']};
    border-radius: {R['md']}px;
    padding: 9px 13px;
    font-size: {F['sm']}pt;
}}

/* ---------- 20. 徽标 ---------- */
#Badge {{
    background: {c['accent_soft']};
    color: {c['accent']};
    border-radius: {R['lg']}px;
    padding: 3px 10px;
    font-size: {F['sm']}pt;
    font-weight: {W['semibold']};
}}
#BadgeOk {{ background: {c['success_soft']}; color: {c['success']}; border-radius: {R['lg']}px; padding: 3px 10px; font-size: {F['sm']}pt; font-weight: {W['semibold']}; }}
#BadgeWarn {{ background: {c['warn_soft']}; color: {c['warn']}; border-radius: {R['lg']}px; padding: 3px 10px; font-size: {F['sm']}pt; font-weight: {W['semibold']}; }}
#BadgeDanger {{ background: {c['danger_soft']}; color: {c['danger']}; border-radius: {R['lg']}px; padding: 3px 10px; font-size: {F['sm']}pt; font-weight: {W['semibold']}; }}

/* ---------- 21. 进度条 ---------- */
QProgressBar {{
    background: {c['border']};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}

/* ---------- 22. 管理页面（主面板）---------- */
/* 数量卡片底部那行状态：「✓ 桌面已整理 / ⚠ 还有 3 项未整理」。
   只给**文字**上色，不铺底色——三块彩色卡片并排会变成仪表盘，
   而这里只需要"一眼看出有没有待办"。 */
#StatState {{ font-size: {F['sm']}pt; }}
#StatState[state="ok"] {{ color: {c['success']}; }}
#StatState[state="warn"] {{ color: {c['warn']}; }}
#StatState[state="idle"] {{ color: {c['text_faint']}; }}

/* 收纳位置：路径是"备查"信息，不是主信息，压到最小一号、最淡一档 */
#PathText {{ color: {c['text_muted']}; font-size: {F['xs']}pt; }}

/* 两张表（面板内容 / 操作历史）共用一套行规格：
   行距从 3px 拉到 8px，表头去掉实心底、压成一条分隔线——
   表格里最该被看见的是数据，不是表头。悬停和选中都只换一层淡底。 */
QTreeWidget#ItemsTree, QTreeWidget#HistoryTree {{
    padding: 4px;
}}
QTreeWidget#ItemsTree::item, QTreeWidget#HistoryTree::item {{
    padding: 8px 6px;
    border-radius: {R['sm']}px;
}}
QTreeWidget#ItemsTree::item:hover, QTreeWidget#HistoryTree::item:hover {{
    background: {c['hover']};
}}
QTreeWidget#ItemsTree::item:selected, QTreeWidget#HistoryTree::item:selected {{
    background: {c['accent_soft']};
    color: {c['text']};
}}
QTreeWidget#ItemsTree QHeaderView::section,
QTreeWidget#HistoryTree QHeaderView::section {{
    background: transparent;
    color: {c['text_muted']};
    font-size: {F['xs']}pt;
    font-weight: {W['semibold']};
    padding: 4px 6px 8px 6px;
    border: none;
    border-bottom: 1px solid {c['border']};
}}
{glass_block}"""
