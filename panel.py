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

这些事都收在 `widgets.GlassCardMixin` 里（收纳面板共用同一套），本文件只负责
把卡片搭出来。两个容易踩的点也由 mixin 统一处理：

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
    popup_menu,
    QAbstractItemView, QBrush, QCheckBox, QColor, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QSizePolicy, QTabWidget,
    QToolButton, QTreeWidget, QTreeWidgetItem, Qt, QVBoxLayout, QWidget, Signal,
)

import config
import engine
import nest
import theme as theme_mod
from widgets import (ElidedLabel, GlassCardMixin, IconLoader, OperationBanner,
                     Toast, app_icon)


class StatCard(QFrame):
    """一个统计小卡片：标题 / 大数字 / 一行状态。

    状态那行带 `state` 动态属性（`ok` / `warn` / `idle`），颜色由
    `theme.py` 的 `#StatState[state=...]` 决定——只染文字，不铺底色。
    """

    def __init__(self, title: str, value: str = "0", hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("StatLabel")
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        self.hint = QLabel(hint)
        self.hint.setObjectName("StatState")
        self.hint.setProperty("state", "idle")
        self.hint.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.hint)
        # 三张卡片等宽等高，状态行长短不一时靠这个把内容顶在上沿
        layout.addStretch(1)

    def update_values(self, value: str, hint: str, state: str = "idle") -> None:
        self.value.setText(value)
        self.hint.setText(hint)
        # 动态属性变了要重新 polish，否则样式表不会重算
        if self.hint.property("state") != state:
            self.hint.setProperty("state", state)
            style = self.hint.style()
            style.unpolish(self.hint)
            style.polish(self.hint)


class MainPanel(GlassCardMixin, QWidget):
    """主面板窗口。"""

    request_refresh = Signal()
    request_take = Signal()
    request_restore = Signal()
    request_browse = Signal()
    request_settings = Signal()
    request_quit = Signal()
    quick_changed = Signal()
    extensions_changed = Signal()      # 「显示文件后缀名」开关变了，通知别处刷新
    # Phase 5：状态条上那两条「重试 / 跳过」的出口，由主程序接住
    retry_item = Signal(str)           # 重试某一项（名称）
    skip_item = Signal(str)            # 这一项先不管（从明细里划掉）

    # 悬浮玻璃卡片：磨砂 + 圆角裁剪 + 深色调色板都在 GlassCardMixin 里
    _glass_card_sel = "#MainCard"
    _glass_log_name = "主面板"

    def __init__(self, cfg: config.Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.dark = bool(cfg.get("dark"))
        self._items: "list" = []
        self._history: "list[dict]" = []
        self._row_by_key: "dict[str, QTreeWidgetItem]" = {}
        self._drag_offset = None
        # 正在批量搬运时置真：按钮要灰掉，免得同一次操作被点两遍
        self._busy = False
        self._glass_init()

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

        # 操作状态条：收纳 / 还原的进度与失败明细（Phase 5）
        # 放在统计卡片**上面**——正在搬文件的时候，最该被看见的是"进行到哪了"，
        # 而不是三个静态数字。
        self.banner = OperationBanner()
        self.banner.retry_requested.connect(self.retry_item.emit)
        self.banner.skip_requested.connect(self.skip_item.emit)
        root.addWidget(self.banner)

        cards = QHBoxLayout()
        cards.setSpacing(11)
        self.card_nest = StatCard("收纳面板里", "—", "")
        self.card_desktop = StatCard("桌面待收纳", "—", "")
        self.card_quick = StatCard("常用启动", "0", "右键面板内容即可添加")
        for card in (self.card_nest, self.card_desktop, self.card_quick):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        # 收纳位置（隐藏目录，只读展示）
        # 需求：路径是"备查"信息，不该和上面的统计数字抢注意力——
        # 小一号、淡一档，长了从中间省略，鼠标悬停看完整路径。
        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        label = QLabel("收纳位置")
        label.setObjectName("SectionLabel")
        path_row.addWidget(label)
        self.path_label = ElidedLabel(
            str(nest.nest_root()), 1,
            mode=Qt.TextElideMode.ElideMiddle,
            align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.path_label.setObjectName("PathText")
        self.path_label.setToolTip(str(nest.nest_root()))
        # 宽度交给布局分配，文本自己按当前宽度省略（别让长路径把窗口撑开）
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        path_row.addWidget(self.path_label, 1)
        self.btn_open_nest = QPushButton("在文件夹中打开")
        self.btn_open_nest.setObjectName("Ghost")
        self.btn_open_nest.setToolTip("在资源管理器里打开收纳目录（可以自己看看文件在不在）")
        self.btn_open_nest.clicked.connect(
            lambda _checked=False: engine.open_in_explorer(nest.desktop_store()))
        path_row.addWidget(self.btn_open_nest)
        root.addLayout(path_row)

        # ---- 显示开关：是否显示文件后缀名 ----
        # 需求：默认**不**显示后缀（`报告.docx` 显示成 `报告`）。
        # 这里只改界面上的文字，磁盘上的文件名一个字都不会动。
        display_row = QHBoxLayout()
        display_row.setSpacing(8)
        self.chk_extensions = QCheckBox("显示文件后缀名")
        self.chk_extensions.setToolTip(
            "打开后文件名带后缀显示（报告.docx）；\n"
            "关闭时只显示主名（报告）。\n"
            "无论开关如何，磁盘上的真实文件名都不会改变。")
        self.chk_extensions.toggled.connect(self._on_extensions_toggled)
        self.chk_extensions.blockSignals(True)
        self.chk_extensions.setChecked(self.extensions_visible())
        self.chk_extensions.blockSignals(False)
        display_row.addWidget(self.chk_extensions)
        display_row.addStretch(1)
        root.addLayout(display_row)

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

        self.btn_browse = QPushButton("打开收纳面板")
        self.btn_browse.setObjectName("Soft")
        self.btn_browse.setToolTip("打开分页浏览的收纳面板，可搜索、可拖拽")
        self.btn_browse.clicked.connect(self.request_browse.emit)
        actions.addWidget(self.btn_browse)
        actions.addStretch(1)

        self.btn_take = QPushButton("收纳桌面")
        self.btn_take.setToolTip("把桌面上的东西收进收纳目录（只移动，不删除）")
        self.btn_take.clicked.connect(self.request_take.emit)
        actions.addWidget(self.btn_take)

        self.btn_restore = QPushButton("还原桌面")
        self.btn_restore.setObjectName("Primary")
        self.btn_restore.setToolTip("把收纳目录里的东西全部放回桌面（只移动，不删除）")
        self.btn_restore.clicked.connect(self.request_restore.emit)
        actions.addWidget(self.btn_restore)
        root.addLayout(actions)

        # 需求：按钮跟着状态灰掉——"桌面待收纳 = 0"时「收纳桌面」不可点，
        # "收纳项目 = 0"时「还原桌面」不可点。
        # 这里先把初始态设成"没有东西可动"，等 `refresh_cards()` 拿到真实
        # 数量再打开；否则面板刚弹出来那一瞬间两个按钮都是亮的，
        # 点下去只会得到一句"没有可收纳的项"。
        self.btn_take.setEnabled(False)
        self.btn_restore.setEnabled(False)

        # 轻提示：撤销成功之类"做完了"的反馈不该弹窗打断操作，
        # 在卡片底部浮一颗药丸，两秒多后自己淡出（见 widgets.Toast）
        self.toast = Toast(self.card)

    def _build_items_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.items_tree = QTreeWidget()
        self.items_tree.setObjectName("ItemsTree")
        self.items_tree.setColumnCount(4)
        self.items_tree.setHeaderLabels(["名称", "类型", "大小", "修改时间"])
        self.items_tree.setRootIsDecorated(False)
        self.items_tree.setUniformRowHeights(True)
        self.items_tree.setWordWrap(False)
        self.items_tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.items_tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection)
        self.items_tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.items_tree.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.items_tree.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
        self.items_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_tree.customContextMenuRequested.connect(self._context_menu)
        self.items_tree.itemDoubleClicked.connect(self._open_item)
        header = self.items_tree.header()
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        for index, width in enumerate((300, 90, 90)):
            self.items_tree.setColumnWidth(index, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.items_tree, 1)

        # 提示放在表格下面：表格从标签栏正下方开始铺满，中间不留空档
        self.items_hint = QLabel("")
        self.items_hint.setObjectName("Hint")
        self.items_hint.setWordWrap(True)
        layout.addWidget(self.items_hint)
        return widget

    def _build_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.history_tree = QTreeWidget()
        self.history_tree.setObjectName("HistoryTree")
        # 需求给的五列：时间 / 动作 / 条目数 / 说明 / 操作
        self.history_tree.setColumnCount(5)
        self.history_tree.setHeaderLabels(
            ["时间", "动作", "条目数", "说明", "操作"])
        self.history_tree.setRootIsDecorated(False)
        self.history_tree.setUniformRowHeights(True)
        self.history_tree.setWordWrap(False)
        self.history_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.history_tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection)
        self.history_tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        # 逐像素滚动：40 行时滚一格跳三行会很难定位
        self.history_tree.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.history_tree.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Expanding)
        header = self.history_tree.header()
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        for index, width in enumerate((136, 64, 64)):
            self.history_tree.setColumnWidth(index, width)
        # 「说明」吃掉多余宽度（列表才不会缩在左边留一大片空白），
        # 「操作」固定窄列，位置稳定
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.history_tree.setColumnWidth(4, 58)
        self.history_tree.itemSelectionChanged.connect(
            self._update_history_buttons)
        # 「操作」列是文字链（见 refresh_history），点它就撤销这一条
        self.history_tree.itemClicked.connect(self._on_history_clicked)
        layout.addWidget(self.history_tree, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.history_hint = QLabel("")
        self.history_hint.setObjectName("Hint")
        self.history_hint.setWordWrap(True)
        footer.addWidget(self.history_hint, 1)

        self.btn_undo = QPushButton("撤销选中操作")
        self.btn_undo.setToolTip(
            "把选中的那次操作整体搬回原来的位置（只移动，不删除）")
        self.btn_undo.clicked.connect(lambda _checked=False: self._undo_selected())
        self.btn_undo.setEnabled(False)
        footer.addWidget(self.btn_undo)
        self.btn_clear_history = QPushButton("清空历史")
        self.btn_clear_history.setObjectName("Ghost")
        self.btn_clear_history.setToolTip("只删操作记录，不动任何文件")
        self.btn_clear_history.clicked.connect(
            lambda _checked=False: self._clear_history())
        footer.addWidget(self.btn_clear_history)
        layout.addLayout(footer)
        return widget

    def apply_theme(self, dark: bool) -> None:
        # 主面板固定用深色磨砂玻璃（需求如此），所以 dark 只影响别处的窗口；
        # 这里保留参数是为了和调用方（tray_app）的接口保持一致。
        self.dark = dark
        self._restyle()
        # 路径标签是自己画的（要在中间省略），颜色得显式喂一份——
        # 自绘控件读的是 palette，QSS 的 color 不保证传进来
        if hasattr(self, "path_label"):
            self.path_label.set_text_color(
                theme_mod.glass_palette()["text_muted"])

    # ------------------------------------------------------------------
    # 显示文件后缀名
    # ------------------------------------------------------------------
    def extensions_visible(self) -> bool:
        """当前是否显示文件后缀名（默认关闭）。"""
        return bool(self.cfg.get("show_extensions", False))

    def _on_extensions_toggled(self, checked: bool) -> None:
        # 只落配置 + 重画列表：磁盘上的文件名完全不动
        self.cfg.set("show_extensions", bool(checked))
        self.refresh_items()
        self.extensions_changed.emit()

    def sync_extensions(self) -> None:
        """把开关同步成配置里的值（设置窗口改过之后由主程序调用）。"""
        want = self.extensions_visible()
        if self.chk_extensions.isChecked() != want:
            self.chk_extensions.blockSignals(True)
            self.chk_extensions.setChecked(want)
            self.chk_extensions.blockSignals(False)
        self.refresh_items()

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

    def show_toast(self, text: str, kind: str = "ok") -> None:
        """在卡片底部浮一条轻提示（不打断操作，两秒多后自己淡出）。"""
        toast = getattr(self, "toast", None)
        if toast is not None:
            toast.show_message(text, kind)

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
        if nest_items:
            self.card_nest.update_values(
                str(nest_items),
                f"快捷方式 {shortcuts} · 文件夹 {folders} · 文件 {files}")
        else:
            self.card_nest.update_values("0", "收纳面板里还没有东西")

        # 需求：状态用一句话说清楚，并且只给**这句话**上状态色
        # （0 项 = ✓ 绿，有积压 = ⚠ 暖黄），不铺底色、不用大红大绿。
        if desktop_pending == 0:
            self.card_desktop.update_values("0", "✓ 桌面已整理", "ok")
        else:
            self.card_desktop.update_values(
                str(desktop_pending),
                f"⚠ 还有 {desktop_pending} 项未整理", "warn")

        quick = self.cfg.quick_items
        self.card_quick.update_values(
            str(len(quick)),
            "、".join(i["name"] for i in quick[:3]) + ("…" if len(quick) > 3 else "")
            if quick else "右键面板内容即可添加")

        self.path_label.setText(str(nest.nest_root()))
        self.path_label.setToolTip(str(nest.nest_root()))
        self.subtitle.setText(f"桌面：{self.cfg.desktop}")

        # 右上角那颗徽标是"数字"，不是状态的复读机——
        # 状态已经由「桌面待收纳」那张卡片说清楚了，这里再写一遍就是重复。
        if desktop_pending:
            self.badge_state.setObjectName("Badge")
            self.badge_state.setText(f"{desktop_pending} 项待收纳")
        elif nest_items:
            self.badge_state.setObjectName("BadgeOk")
            self.badge_state.setText(f"{nest_items} 项已收纳")
        else:
            self.badge_state.setObjectName("Badge")
            self.badge_state.setText("准备就绪")
        self.badge_state.style().unpolish(self.badge_state)
        self.badge_state.style().polish(self.badge_state)

        self.btn_take.setEnabled(bool(desktop_pending) and not self._busy)
        self.btn_restore.setEnabled(bool(nest_items) and not self._busy)

    # ------------------------------------------------------------------
    # 操作状态（Phase 5）：进度 / 失败明细 / 重试跳过
    # ------------------------------------------------------------------
    def begin_operation(self, text: str, total: int) -> None:
        """开始一次批量搬运：状态条进入"正在做"，两个按钮先灰掉。"""
        self._busy = True
        # 旧的提示条先收起来，别和进度条抢同一块地方
        self.notice.setVisible(False)
        self.banner.begin(text, total)
        self.btn_take.setEnabled(False)
        self.btn_restore.setEnabled(False)

    def update_progress(self, index: int, total: int, name: str = "") -> None:
        """搬运到第几项了（可以直接当 `nest` 的 progress 回调）。"""
        if self._busy:
            self.banner.set_progress(index, total, name)

    def finish_operation(self, result, kind: str = "take") -> None:
        """一次批量搬运结束：成功只留一颗 Toast，有失败就把明细列在状态条里。

        `kind` 取 `take` / `restore`，只影响文案（"已收纳" / "已还原"）。
        """
        self._busy = False
        word = "已收纳" if kind == "take" else "已还原"
        failed = list(getattr(result, "failed", []) or [])
        skipped = list(getattr(result, "skipped", []) or [])
        moved = int(getattr(result, "moved", 0) or 0)

        if failed:
            # 需求二：不要让整个操作无提示地结束 —— 明细留在状态条里，
            # 每一条都带 [重试] [跳过]，不用弹窗打断。
            title = "部分项目处理失败" if moved else "处理失败"
            self.banner.show_failure(title, moved, failed, skipped)
            self.show_toast(f"成功 {moved} 项，失败 {len(failed)} 项", "warn")
            return

        self.banner.hide_banner()
        if moved:
            # 需求一：完成态是「✓ 已收纳 / 60 个项目」两行，短、清楚
            self.show_toast(f"{word}\n{moved} 个项目", "ok")
        elif skipped:
            self.show_toast(f"没有需要{word[1:]}的项目", "warn")
        else:
            self.show_toast("没有需要处理的条目", "warn")

    def fail_operation(self, message: str) -> None:
        """整个操作没法开始（配置不对、目录不可写……）：用状态条说清楚。"""
        self._busy = False
        self.banner.show_failure(message, 0, [])
        self.show_toast(message, "danger")

    def show_conflict(self, name: str, count: int = 1) -> None:
        """还原时发现桌面已有同名文件——把这件事记在状态条上（不作为弹窗）。"""
        extra = f"（另有 {count - 1} 个同名项）" if count > 1 else ""
        self.notice.setText(f"提示：桌面已有同名文件「{name}」{extra}，已按原规则自动改名")
        self.notice.setVisible(True)

    def drop_failed_row(self, name: str) -> None:
        """把某一项从失败明细里划掉（用户点了「跳过」）。"""
        self.banner.drop_row(name)

    def clear_banner(self) -> None:
        self._busy = False
        self.banner.hide_banner()

    def refresh_items(self) -> None:
        self.items_tree.clear()
        self._row_by_key.clear()
        show_ext = self.extensions_visible()
        for item in self._items:
            # 显示名可能剥掉了后缀，但真实路径挂在 UserRole 上，操作不受影响
            node = QTreeWidgetItem([
                engine.display_name(item.name, item.is_dir, show_ext),
                item.kind_label, item.size_text,
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

    #: 流水里的 action → 表格里显示的动作名 + 方向说明
    _ACTION_TEXT = {
        "take": ("收纳", "桌面 → 收纳面板"),
        "restore": ("还原", "收纳面板 → 桌面"),
    }

    @staticmethod
    def _record_names(record: "dict") -> "list[str]":
        """这次操作涉及的文件名（按流水顺序）。"""
        names: "list[str]" = []
        for move in record.get("moves") or []:
            if isinstance(move, (list, tuple)) and len(move) == 2:
                names.append(Path(move[1]).name)
        return names

    def _describe_record(self, record: "dict", direction: str) -> str:
        """「说明」列：方向 + 涉及哪几个文件（一行装不下会由表格省略）。"""
        names = self._record_names(record)
        if not names:
            return direction or "—"
        head = "、".join(names[:2])
        more = f" 等 {len(names)} 项" if len(names) > 2 else ""
        return f"{direction} · {head}{more}" if direction else f"{head}{more}"

    def _record_tooltip(self, record: "dict", direction: str) -> str:
        names = self._record_names(record)
        if not names:
            return direction
        shown = names[:12]
        lines = [direction, ""] + [f"· {name}" for name in shown]
        if len(names) > len(shown):
            lines.append(f"…… 还有 {len(names) - len(shown)} 项")
        return "\n".join(lines)

    def refresh_history(self, records: "list[dict]") -> None:
        self._history = list(records)
        # 重填之前记下"当前选的是哪一条"，刷新后还能选回去——
        # 撤销完一次刷新，用户往往接着撤下一次
        keep: "float | None" = None
        for node in self.history_tree.selectedItems():
            keep = node.data(0, int(Qt.ItemDataRole.UserRole))
        self.history_tree.clear()

        # 「操作」列是文字链，颜色跟主色走（表格里唯一可点的地方）
        link = QBrush(QColor(theme_mod.glass_palette()["accent"]))
        for record in records:
            stamp = float(record.get("time", 0) or 0)
            raw_action = str(record.get("action", "") or "")
            label, direction = self._ACTION_TEXT.get(
                raw_action, (raw_action or "—", ""))
            count = int(record.get("count", 0) or 0)
            node = QTreeWidgetItem([
                engine.time_text(stamp), label, str(count),
                self._describe_record(record, direction), "撤销",
            ])
            # 把时间戳挂在行上，撤销时据此找回原始流水（含完整 moves 列表）
            node.setData(0, int(Qt.ItemDataRole.UserRole), stamp)
            node.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
            node.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
            node.setForeground(4, link)
            node.setToolTip(3, self._record_tooltip(record, direction))
            node.setToolTip(4, "点这里把这次操作整体搬回原来的位置")
            self.history_tree.addTopLevelItem(node)
            if keep is not None and abs(stamp - float(keep)) < 0.0005:
                node.setSelected(True)

        if records:
            self.history_hint.setText(
                f"最近 {len(records)} 次操作 · 选中一行点「撤销」，"
                "或直接点行尾的「撤销」")
        else:
            self.history_hint.setText(
                "还没有操作记录。收纳或还原桌面后，这里会出现可撤销的记录。")
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(bool(self.history_tree.selectedItems()))

    def _on_history_clicked(self, node: QTreeWidgetItem, column: int) -> None:
        """点「操作」列 = 撤销这一条（选中态会由 QTreeWidget 自己处理）。"""
        if column != 4 or node is None:
            return
        self._undo_record(self._record_for_node(node))

    def _record_for_node(self, node: "QTreeWidgetItem | None") -> "dict | None":
        if node is None:
            return None
        stamp = node.data(0, int(Qt.ItemDataRole.UserRole))
        if stamp is None:
            return None
        for record in self._history:
            if abs(float(record.get("time", -1)) - float(stamp)) < 0.0005:
                return record
        return None

    def _selected_record(self) -> "dict | None":
        nodes = self.history_tree.selectedItems()
        if not nodes:
            return None
        return self._record_for_node(nodes[0])

    def _undo_selected(self) -> None:
        self._undo_record(self._selected_record())

    def _undo_record(self, record: "dict | None") -> None:
        """按流水整体撤回一次操作。

        不再弹「确定吗」：撤销本身就是可逆的（再收纳一次就回去了），
        而连续撤销时每撤一次都要点一下弹窗，比误点更让人烦。
        """
        if record is None:
            return
        result = nest.undo_record(record)
        if result.moved and not result.failed:
            # 全部搬回才删流水，避免"撤了一半"之后记录丢失
            nest.drop_journal_record(record.get("time", 0))
        self.request_refresh.emit()

        if result.failed:
            message = f"已撤销 {result.moved} 项，{len(result.failed)} 项没能搬回去：\n" + \
                "\n".join(f"· {n}：{r}" for n, r in result.failed[:6])
            QMessageBox.warning(self, "撤销操作", message)
            self.show_toast(
                f"⚠ 撤销了 {result.moved} 项，{len(result.failed)} 项没搬回去",
                "warn")
        elif result.moved:
            self.show_toast(
                f"✓ 已撤销\n{result.moved} 个项目已恢复到原来的位置", "ok")
        else:
            self.show_toast("⚠ 这次操作已经没有可撤销的条目了", "warn")

    def _confirm_clear_history(self) -> bool:
        """清空历史前的确认。

        危险操作的按钮写清楚做什么（「清空」），别用「确定」——
        用户点之前应该知道自己在点什么。
        """
        box = QMessageBox(self)
        box.setWindowTitle("清空操作历史")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("清空操作历史？")
        box.setInformativeText("此操作不会影响已经收纳的文件。")
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        clear = box.addButton("清空", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is clear

    def _clear_history(self) -> None:
        if not self._history:
            return
        if not self._confirm_clear_history():
            return
        if not nest.clear_journal():
            self.show_toast("⚠ 清空失败，记录可能正被占用，稍后再试", "warn")
            return
        self.request_refresh.emit()
        self.show_toast("✓ 已清空操作历史", "ok")

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
        chosen = popup_menu(menu, self.items_tree.viewport().mapToGlobal(pos))
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
