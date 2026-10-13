#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主面板
======
托盘菜单「打开主面板」打开的窗口，用来"看全局 + 做决定"：

    ┌──────────────────────────────────────────────────────┐
    │ 桌面收纳                              [桌面已清空]    │
    │ 桌面：C:\\Users\\…\\Desktop                            │
    ├──────────────────────────────────────────────────────┤
    │ [ 收纳中 38 ] [ 桌面待收纳 0 ] [ 常用启动 4 ]          │
    ├──────────────────────────────────────────────────────┤
    │ 收纳位置  C:\\Users\\…\\.desktop-nest     [打开][换位置]│
    ├──────────────────────────────────────────────────────┤
    │ [ 面板内容 ] [ 操作历史 ]                             │
    ├──────────────────────────────────────────────────────┤
    │ [收纳桌面] [打开面板] … [还原桌面]                     │
    └──────────────────────────────────────────────────────┘

* 收纳位置是程序自己的隐藏目录，不需要用户管理（没有"仓库"这个概念了）
* 启动自动收纳、退出自动还原，都在设置里可以关掉

外观：**悬浮的磨砂玻璃卡片**
----------------------------
无边框 + 窗口自身透明，深色半透明只画在内部的 `#MainCard` 上；
真正的"把背后桌面模糊掉"由 DWM 提供（见 `acrylic.py`），
窗口再按圆角裁一刀，免得模糊糊到圆角外面。

两个容易踩的点：

1. **不能给顶层窗口设 QSS 背景**——那会把磨砂整块盖住，看起来就是一块
   不透明的板子。卡片外观一律交给子控件。
2. **必须同时换 QPalette**。QSS 只覆盖写到的控件，没写到的（QTabBar 的空白、
   表头间隙…）会回落到系统调色板，那是浅色的，在深色玻璃上就是一道刺眼的白。

拖动：没有系统标题栏，所以按住卡片空白处可以拖走（`mousePressEvent` 系列）。
"""

from __future__ import annotations

import time
from pathlib import Path

from qt_compat import (
    QColor, QFrame, QHBoxLayout, QLabel, QMessageBox, QPalette, QPushButton,
    QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, Qt, QVBoxLayout,
    QWidget, Signal,
)

import acrylic
import config
import engine
import nest
import theme as theme_mod
from widgets import IconLoader, app_icon

# 磨砂玻璃的着色。要和 theme.GLASS['card'] 对齐着看：
# DWM 的着色和卡片自己的底色是**两层**，都调浓就会叠成一块黑板。
GLASS_TINT = "#181A20"
GLASS_TINT_ALPHA = 0.26


class StatCard(QFrame):
    """一个统计小卡片。"""

    def __init__(self, title: str, value: str = "0", hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("StatLabel")
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        self.hint = QLabel(hint)
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.hint)

    def update_values(self, value: str, hint: str) -> None:
        self.value.setText(value)
        self.hint.setText(hint)


class MainPanel(QWidget):
    """主面板窗口。"""

    request_refresh = Signal()
    request_take = Signal()
    request_restore = Signal()
    request_browse = Signal()
    request_settings = Signal()
    request_quit = Signal()
    quick_changed = Signal()

    def __init__(self, cfg: config.Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.dark = bool(cfg.get("dark"))
        self._items: "list" = []
        self._history: "list[dict]" = []
        self._row_by_key: "dict[str, QTreeWidgetItem]" = {}
        self._drag_offset = None
        self._glass_mode = ""
        self._glass_ready = False

        # 悬浮卡片：无边框 + 窗口自身透明，深色半透明只画在里面的 #MainCard 上。
        # 注意**不能**给顶层窗口设 QSS 背景——那会把 DWM 的磨砂整块盖住，
        # 卡片外观一律交给子控件（和收纳面板的 #Popup 一个套路）。
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("MainPanel")
        self.setWindowTitle("桌面收纳 · 主面板")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(820, 600)
        self.resize(940, 680)
        self._build_ui()
        self._apply_glass_palette()
        self.apply_theme(self.dark)

        self.loader = IconLoader(self, per_tick=4)
        self.loader.ready.connect(self._on_icon_ready)

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 外层留 0 边距：卡片就是整块窗口，这样 DWM 的圆角裁剪和卡片圆角能对齐
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.card = QFrame(self)
        self.card.setObjectName("MainCard")
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(13)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel("桌面收纳")
        self.title.setObjectName("Title")
        self.subtitle = QLabel("启动时自动收纳桌面，退出时自动还原")
        self.subtitle.setObjectName("Hint")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.badge_state = QLabel("准备就绪")
        self.badge_state.setObjectName("Badge")
        header.addWidget(self.badge_state, 0, Qt.AlignmentFlag.AlignTop)

        # 无边框窗口没有系统标题栏，关闭按钮得自己给一个
        self.btn_close = QToolButton()
        self.btn_close.setObjectName("GlassClose")
        self.btn_close.setText("✕")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("关闭面板（程序继续驻留托盘）")
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.notice = QLabel("")
        self.notice.setObjectName("Notice")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        root.addWidget(self.notice)

        cards = QHBoxLayout()
        cards.setSpacing(11)
        self.card_nest = StatCard("收纳面板里", "—", "")
        self.card_desktop = StatCard("桌面待收纳", "—", "")
        self.card_quick = StatCard("常用启动", "0", "右键面板内容即可添加")
        for card in (self.card_nest, self.card_desktop, self.card_quick):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        # 收纳位置（隐藏目录，只读展示）
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        label = QLabel("收纳位置")
        label.setObjectName("Hint")
        path_row.addWidget(label)
        self.path_label = QLabel(str(nest.nest_root()))
        self.path_label.setObjectName("Hint")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        path_row.addWidget(self.path_label, 1)
        self.btn_open_nest = QPushButton("打开收纳目录")
        self.btn_open_nest.clicked.connect(
            lambda: engine.open_in_explorer(nest.desktop_store()))
        path_row.addWidget(self.btn_open_nest)
        root.addLayout(path_row)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # documentMode 下 QTabBar 会在顶边画一条"基线"——原生样式用**主题位图**
        # 画的，既不吃 QSS 也不吃调色板（浅色主题下看不出来，深色玻璃上就是
        # 一道刺眼的白）。关掉它，标签的观感全靠 QSS，反而更整齐。
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(self._build_items_tab(), "面板内容")
        self.tabs.addTab(self._build_history_tab(), "操作历史")
        root.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.request_refresh.emit)
        actions.addWidget(self.btn_refresh)

        self.btn_browse = QPushButton("打开收纳面板（分页）")
        self.btn_browse.setObjectName("Soft")
        self.btn_browse.clicked.connect(self.request_browse.emit)
        actions.addWidget(self.btn_browse)
        actions.addStretch(1)

        self.btn_take = QPushButton("收纳桌面")
        self.btn_take.clicked.connect(self.request_take.emit)
        actions.addWidget(self.btn_take)

        self.btn_restore = QPushButton("还原桌面")
        self.btn_restore.setObjectName("Primary")
        self.btn_restore.clicked.connect(self.request_restore.emit)
        actions.addWidget(self.btn_restore)
        root.addLayout(actions)

    def _build_items_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.items_hint = QLabel("")
        self.items_hint.setObjectName("Hint")
        self.items_hint.setWordWrap(True)
        layout.addWidget(self.items_hint)

        self.items_tree = QTreeWidget()
        self.items_tree.setColumnCount(4)
        self.items_tree.setHeaderLabels(["名称", "类型", "大小", "修改时间"])
        self.items_tree.setRootIsDecorated(False)
        self.items_tree.setUniformRowHeights(True)
        self.items_tree.setWordWrap(False)
        self.items_tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.items_tree.header().setStretchLastSection(True)
        self.items_tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection)
        self.items_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_tree.customContextMenuRequested.connect(self._context_menu)
        self.items_tree.itemDoubleClicked.connect(self._open_item)
        for index, width in enumerate((300, 90, 90)):
            self.items_tree.setColumnWidth(index, width)
        layout.addWidget(self.items_tree, 1)
        return widget

    def _build_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.history_hint = QLabel("")
        self.history_hint.setObjectName("Hint")
        self.history_hint.setWordWrap(True)
        layout.addWidget(self.history_hint)

        self.history_tree = QTreeWidget()
        self.history_tree.setColumnCount(4)
        self.history_tree.setHeaderLabels(["时间", "动作", "条目数", "说明"])
        self.history_tree.setRootIsDecorated(False)
        self.history_tree.setUniformRowHeights(True)
        self.history_tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection)
        self.history_tree.itemSelectionChanged.connect(self._update_history_buttons)
        for index, width in enumerate((150, 80, 70)):
            self.history_tree.setColumnWidth(index, width)
        layout.addWidget(self.history_tree, 1)

        history_actions = QHBoxLayout()
        history_actions.setSpacing(8)
        self.btn_undo = QPushButton("撤销选中操作")
        self.btn_undo.clicked.connect(self._undo_selected)
        self.btn_undo.setEnabled(False)
        history_actions.addWidget(self.btn_undo)
        self.btn_clear_history = QPushButton("清空历史")
        self.btn_clear_history.setObjectName("Ghost")
        self.btn_clear_history.clicked.connect(self._clear_history)
        history_actions.addWidget(self.btn_clear_history)
        history_actions.addStretch(1)
        layout.addLayout(history_actions)
        return widget

    def _apply_glass_palette(self) -> None:
        """把窗口调色板换成深色，兜住 QSS 没写到的控件。"""
        roles = theme_mod.glass_palette_roles()
        pal = self.palette()
        mapping = {
            QPalette.ColorRole.Window: roles["window"],
            QPalette.ColorRole.WindowText: roles["text"],
            QPalette.ColorRole.Base: roles["base"],
            QPalette.ColorRole.AlternateBase: roles["alternate"],
            QPalette.ColorRole.Text: roles["text"],
            QPalette.ColorRole.Button: roles["button"],
            QPalette.ColorRole.ButtonText: roles["text"],
            QPalette.ColorRole.ToolTipBase: roles["button"],
            QPalette.ColorRole.ToolTipText: roles["text"],
            QPalette.ColorRole.Highlight: roles["highlight"],
            QPalette.ColorRole.HighlightedText: roles["highlight_text"],
            QPalette.ColorRole.PlaceholderText: roles["sub"],
        }
        for role, value in mapping.items():
            pal.setColor(role, QColor(value))
        self.setPalette(pal)

    def apply_theme(self, dark: bool) -> None:
        # 主面板固定用深色磨砂玻璃（需求如此），所以 dark 只影响别处的窗口；
        # 这里保留参数是为了和调用方（tray_app）的接口保持一致。
        self.dark = dark
        self._restyle()

    def _restyle(self) -> None:
        """套用玻璃卡片样式。

        拿不到磨砂（老系统 / 被策略挡住）时把卡片底色加浓一档——
        没有模糊还那么透，文字会看不清。
        """
        sheet = theme_mod.stylesheet(self.dark, glass=True)
        if not self._glass_mode:
            sheet += ("\n#MainCard { background: rgba(24, 26, 32, 0.90);"
                      " border-color: rgba(255, 255, 255, 0.14); }\n")
        self.setStyleSheet(sheet)

    # ------------------------------------------------------------------
    # 悬浮玻璃卡片：DWM 磨砂 + 圆角裁剪
    # ------------------------------------------------------------------
    def _ensure_glass(self) -> None:
        """开磨砂（只在第一次显示时做一次）。"""
        if self._glass_ready:
            return
        self._glass_ready = True
        self._glass_mode = acrylic.enable_blur(
            self, radius=theme_mod.GLASS_RADIUS,
            tint=GLASS_TINT, opacity=GLASS_TINT_ALPHA)
        config.log(f"主面板磨砂：{self._glass_mode or '不可用，退回纯半透明'}"
                   f"（{acrylic.describe()}）")
        self._restyle()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_glass()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # SetWindowRgn 不会跟着窗口缩放，尺寸一变就得重新裁一次
        if self._glass_mode:
            acrylic.apply_round_region(self, theme_mod.GLASS_RADIUS)

    # ------------------------------------------------------------------
    # 拖动 / 快捷键
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        """无边框窗口没有标题栏，按住卡片空白处就能把它拖走。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def show_notice(self, text: str) -> None:
        if not text:
            self.notice.setVisible(False)
            return
        self.notice.setText(f"提示：{text}")
        self.notice.setVisible(True)

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def update_overview(self, *, items, nest_items: int, desktop_pending: int,
                        folders: int, shortcuts: int, history: "list[dict]") -> None:
        """由主程序在扫描完成后调用。

        items 直接复用后台扫描线程已经算好的结果——在主线程再扫一遍目录
        既慢又会卡住界面（这正是之前大桌面下开面板会顿一下的原因）。
        """
        self._items = items
        self.refresh_items()
        self.refresh_history(history)
        self.refresh_cards(nest_items, desktop_pending, folders, shortcuts)

    def refresh_cards(self, nest_items: int = 0, desktop_pending: int = 0,
                      folders: int = 0, shortcuts: int = 0) -> None:
        files = max(0, nest_items - folders - shortcuts)
        self.card_nest.update_values(
            str(nest_items),
            f"快捷方式 {shortcuts} · 文件夹 {folders} · 文件 {files}")
        self.card_desktop.update_values(
            str(desktop_pending),
            "桌面已经清空 🎉" if desktop_pending == 0 else "点「收纳桌面」收进来")

        quick = self.cfg.quick_items
        self.card_quick.update_values(
            str(len(quick)),
            "、".join(i["name"] for i in quick[:3]) + ("…" if len(quick) > 3 else "")
            if quick else "右键面板内容即可添加")

        self.path_label.setText(str(nest.nest_root()))
        self.subtitle.setText(f"桌面：{self.cfg.desktop}")

        if desktop_pending == 0 and nest_items:
            self.badge_state.setObjectName("BadgeOk")
            self.badge_state.setText("桌面已清空")
        elif desktop_pending:
            self.badge_state.setObjectName("Badge")
            self.badge_state.setText(f"{desktop_pending} 项待收纳")
        else:
            self.badge_state.setObjectName("Badge")
            self.badge_state.setText("准备就绪")
        self.badge_state.style().unpolish(self.badge_state)
        self.badge_state.style().polish(self.badge_state)

        self.btn_take.setEnabled(bool(desktop_pending))
        self.btn_restore.setEnabled(bool(nest_items))

    def refresh_items(self) -> None:
        self.items_tree.clear()
        self._row_by_key.clear()
        for item in self._items:
            node = QTreeWidgetItem([
                item.name, item.kind_label, item.size_text,
                engine.time_text(item.mtime),
            ])
            node.setData(0, int(Qt.ItemDataRole.UserRole), str(item.path))
            self.items_tree.addTopLevelItem(node)
            self._row_by_key[str(item.path)] = node
            if not item.is_dir:
                self.loader.request(str(item.path), item.path, None, 16, item.name)

        if self._items:
            self.items_hint.setText(
                f"收纳面板里共 {len(self._items)} 项。双击打开，右键可加为常用启动"
                "或还原到桌面。")
        else:
            self.items_hint.setText(
                "收纳面板还是空的。程序会在启动时自动把桌面上的东西收进来。")

    def _on_icon_ready(self, key: str, icon) -> None:
        node = self._row_by_key.get(key)
        if node is not None:
            node.setIcon(0, icon)

    def refresh_history(self, records: "list[dict]") -> None:
        self._history = list(records)
        self.history_tree.clear()
        action_labels = {"take": "收纳", "restore": "还原"}
        for record in records:
            action = action_labels.get(record.get("action"), record.get("action", ""))
            count = int(record.get("count", 0) or 0)
            node = QTreeWidgetItem([
                engine.time_text(record.get("time", 0)), action,
                str(count), f"{count} 项，可整体撤销",
            ])
            # 把时间戳挂在行上，撤销时据此找回原始流水（含完整 moves 列表）
            node.setData(0, int(Qt.ItemDataRole.UserRole), float(record.get("time", 0)))
            self.history_tree.addTopLevelItem(node)
        if records:
            self.history_hint.setText(
                f"最近 {len(records)} 次操作。选中一条点「撤销选中操作」，"
                "就能把它们整体搬回原来的位置。")
        else:
            self.history_hint.setText(
                "还没有操作记录。收纳或还原桌面后，这里会出现可撤销的记录。")
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(bool(self.history_tree.selectedItems()))

    def _selected_record(self) -> "dict | None":
        nodes = self.history_tree.selectedItems()
        if not nodes:
            return None
        stamp = nodes[0].data(0, int(Qt.ItemDataRole.UserRole))
        for record in self._history:
            if abs(float(record.get("time", -1)) - float(stamp)) < 0.0005:
                return record
        return None

    def _undo_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        count = int(record.get("count", 0) or 0)
        if QMessageBox.question(
                self, "撤销操作",
                f"把这次操作的 {count} 个条目搬回原来的位置？\n\n"
                "文件只是移动，不会被删除；目标已存在同名文件时自动加序号。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        result = nest.undo_record(record)
        if result.moved and not result.failed:
            # 全部搬回才删流水，避免"撤了一半"之后记录丢失
            nest.drop_journal_record(record.get("time", 0))
        self.request_refresh.emit()
        message = f"已撤销 {result.moved} 项"
        if result.failed:
            message += "\n\n未能撤销：\n" + "\n".join(
                f"· {n}：{r}" for n, r in result.failed[:6])
            QMessageBox.warning(self, "撤销操作", message)
        else:
            QMessageBox.information(self, "撤销操作", message)

    def _clear_history(self) -> None:
        if not self._history:
            return
        if QMessageBox.question(
                self, "清空历史",
                "清空全部操作记录？\n\n只清记录，不会动任何文件。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        nest.clear_journal()
        self.request_refresh.emit()

    # ------------------------------------------------------------------
    # 条目操作
    # ------------------------------------------------------------------
    def _selected_items(self) -> "list":
        wanted = set()
        for node in self.items_tree.selectedItems():
            raw = node.data(0, int(Qt.ItemDataRole.UserRole))
            if raw:
                wanted.add(raw)
        return [i for i in self._items if str(i.path) in wanted]

    def _open_item(self, node: QTreeWidgetItem, _column: int = 0) -> None:
        raw = node.data(0, int(Qt.ItemDataRole.UserRole))
        if not raw:
            return
        path = Path(raw)
        if path.suffix.lower() == ".lnk" and nest.shell_path_for(path):
            ok, reason = nest.open_system_link(path)
        else:
            ok, reason = engine.launch(path)
        if not ok:
            QMessageBox.warning(self, "打不开", f"{path.name}\n\n{reason}")

    def _context_menu(self, pos) -> None:
        from qt_compat import QMenu

        node = self.items_tree.itemAt(pos)
        if node is None:
            return
        if not node.isSelected():
            self.items_tree.clearSelection()
            node.setSelected(True)
        items = self._selected_items()
        if not items:
            return
        primary = items[0]
        is_quick = self.cfg.is_quick(primary.path)

        menu = QMenu(self)
        action_open = menu.addAction("打开")
        action_reveal = menu.addAction("打开文件所在位置")
        menu.addSeparator()
        action_quick = menu.addAction("从常用启动移除" if is_quick else "加为常用启动")
        action_restore = menu.addAction("还原到桌面")
        action_copy = menu.addAction("复制完整路径")
        chosen = menu.exec(self.items_tree.viewport().mapToGlobal(pos))
        if chosen is action_open:
            self._open_item(node)
        elif chosen is action_reveal:
            for item in items[:3]:
                engine.open_in_explorer(item.path)
        elif chosen is action_quick:
            if is_quick:
                for item in items:
                    self.cfg.remove_quick(item.path)
            else:
                for item in items:
                    self.cfg.add_quick(item.path,
                                       item.path.stem if item.path.suffix else item.name)
            self.quick_changed.emit()
        elif chosen is action_restore:
            done = 0
            for item in items:
                ok, _reason = nest.restore_item_to_desktop(self.cfg.desktop, item)
                done += 1 if ok else 0
            self.request_refresh.emit()
            self.items_hint.setText(f"已把 {done} 项放回桌面。")
        elif chosen is action_copy:
            from qt_compat import QApplication

            QApplication.clipboard().setText("\n".join(str(i.path) for i in items))

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        """关窗口不等于退出程序——仍然驻留托盘。"""
        event.ignore()
        self.hide()
