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
}

RADIUS = 10
RADIUS_SMALL = 7
FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'


def palette(dark: bool = False) -> dict:
    return dict(DARK if dark else LIGHT)


def stylesheet(dark: bool = False) -> str:
    """生成整份 QSS。"""
    c = palette(dark)
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
#Popup {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS + 2}px;
}}
#Toolbar {{
    background: {c['surface_alt']};
    border-bottom: 1px solid {c['border']};
    border-top-left-radius: {RADIUS + 1}px;
    border-top-right-radius: {RADIUS + 1}px;
}}
#FooterBar {{
    background: {c['surface_alt']};
    border-top: 1px solid {c['border']};
    border-bottom-left-radius: {RADIUS + 1}px;
    border-bottom-right-radius: {RADIUS + 1}px;
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
#DockSurface {{
    background: rgba(28, 30, 36, 235);
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 18px;
}}
#DockIcon {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 0px;
}}
#DockIcon:hover {{
    background: rgba(255, 255, 255, 34);
    border-color: rgba(255, 255, 255, 48);
}}
#DockIcon:pressed {{
    background: rgba(255, 255, 255, 60);
}}
#DockNav {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #E9EBEF;
    font-size: 9pt;
}}
#DockNav:hover {{ background: rgba(255, 255, 255, 40); }}
#DockNav:disabled {{ color: rgba(233, 235, 239, 70); }}
#DockPage {{
    color: rgba(233, 235, 239, 170);
    font-size: 8.25pt;
}}
#DockEmpty {{
    color: rgba(233, 235, 239, 120);
    font-size: 8.25pt;
    padding-left: 10px;
}}
#DockDivider {{
    background: rgba(255, 255, 255, 48);
    border: none;
    margin-top: 8px;
    margin-bottom: 8px;
    margin-left: 5px;
    margin-right: 5px;
}}
#DockAdd {{
    background: rgba(255, 255, 255, 26);
    border: 1px dashed rgba(255, 255, 255, 80);
    border-radius: 10px;
    color: #E9EBEF;
    font-size: 11.25pt;
    font-weight: 600;
}}
#DockAdd:hover {{
    background: rgba(255, 255, 255, 52);
    border-color: rgba(255, 255, 255, 130);
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
#AppAdd {{
    background: transparent;
    border: 1px dashed {c['border_strong']};
    border-radius: 10px;
    color: {c['text_sub']};
    font-size: 8.25pt;
}}
#AppAdd:hover {{
    background: {c['hover']};
    border-color: {c['accent']};
    color: {c['accent']};
}}
#TileName {{ font-size: 9pt; }}
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
"""
