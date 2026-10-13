#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部菜单栏（Dock）
==================
贴屏幕底部正中一条仿 macOS 的常驻悬浮栏：

    ┌────────────────────────────────────────────────────────────┐
    │ ◀ │ 此电脑  回收站  资料夹  报告.docx  …（一页 7 个）│ ▶ │ ＋添加 │ ⚙ │   ← 分页行
    ├────────────────────────────────────────────────────────────┤
    │ [▣ 桌面整理] │ [微][S][E]…（常用启动，图标+名称）            │   ← 主行
    └────────────────────────────────────────────────────────────┘

* **第一个控件就是"桌面整理"**，点它打开完整的收纳面板（分页 + 搜索）
* **分页行直接嵌在菜单栏里**：每页 7 个，`◀ ▶` 翻页，
  每个都是**快捷方式图标 + 下方名称**，点一下直接打开
* 主行右边是常用启动项，同样是图标 + 名称
* 空白处右键出菜单栏设置；按住可左右拖动，位置会记住
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    QColor, QFrame, QGridLayout, QHBoxLayout, QIcon, QLabel, QMenu, QPainter,
    QPainterPath, QPixmap, QPoint, QSize, QToolButton, QVBoxLayout, QWidget, Qt,
    QTimer, Signal,
)

import engine
import nest
import safety
import theme as theme_mod
from widgets import (IconLoader, PLACEHOLDER_COLORS, app_icon, letter_pixmap,
                     pixmap_for)

DOCK_ICON_SIZES = [36, 44, 52, 60]
DEFAULT_ICON_SIZE = 44
STRIP_PAGE_SIZE = 7            # 分页行每页几个
STRIP_ICON = 30
MIN_MARGIN = 8


def make_desktop_glyph(size: int, accent: str = "#4F6BED") -> QPixmap:
    """画一个"桌面 + 网格"的小图标，代表"桌面整理"入口。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    radius = size * 0.24
    path.addRoundedRect(0.5, 0.5, size - 1, size - 1, radius, radius)
    painter.fillPath(path, QColor(accent))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    unit = size / 16.0
    for row in range(2):
        for column in range(2):
            painter.drawRoundedRect(
                int((4 + column * 4.6) * unit), int((4 + row * 4.6) * unit),
                int(3.4 * unit), int(3.4 * unit), unit * 0.8, unit * 0.8)
    painter.end()
    return pixmap


class FlowRow(QWidget):
    """会自动换行的横向排布容器。

    常用启动加多了之后，一行放不下就会把图标挤扁、或者把菜单栏撑到屏幕外面。
    这里按可用宽度算出每行能放几个，多出来的换到下一行——
    菜单栏只会变高变宽到屏幕能容纳的程度，永远不会跑出屏幕。
    """

    def __init__(self, parent=None, spacing: int = 3):
        super().__init__(parent)
        self._spacing = spacing
        self._items: "list[QWidget]" = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def clear_items(self) -> None:
        while self._grid.count():
            entry = self._grid.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._items = []

    def add_item(self, widget: QWidget) -> None:
        self._items.append(widget)

    def item_count(self) -> int:
        return len(self._items)

    def natural_width(self) -> int:
        """内容排成一行时需要多宽。"""
        if not self._items:
            return 0
        unit = max(w.sizeHint().width() for w in self._items)
        return unit * len(self._items) + self._spacing * (len(self._items) - 1)

    def relayout(self, max_width: int) -> None:
        """按最大宽度决定每行放几个，重新摆一遍。"""
        while self._grid.count():
            self._grid.takeAt(0)
        if not self._items:
            return
        # 让每个格子只占它需要的大小，不要被拉伸（拉长了按钮会变形、图标会糊）
        for index in range(self._grid.columnCount()):
            self._grid.setColumnStretch(index, 0)
        for index in range(self._grid.rowCount()):
            self._grid.setRowStretch(index, 0)

        unit_width = max(w.sizeHint().width() for w in self._items) + self._spacing
        columns = max(1, int(max_width // max(1, unit_width)))
        for index, widget in enumerate(self._items):
            widget.setParent(self)
            self._grid.addWidget(widget, index // columns, index % columns,
                                 Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        self.updateGeometry()

    def sizeHint(self):  # noqa: N802
        """内容按当前排列所需的尺寸。"""
        from qt_compat import QSize

        if not self._items or not self._grid.count():
            return QSize(0, 0)
        rows = self._grid.rowCount()
        columns = self._grid.columnCount()
        unit_w = max(w.sizeHint().width() for w in self._items)
        unit_h = max(w.sizeHint().height() for w in self._items)
        width = unit_w * columns + self._spacing * max(0, columns - 1)
        height = unit_h * rows + self._spacing * max(0, rows - 1)
        return QSize(width, height)


class DockIcon(QToolButton):
    """Dock 上的一个图标按钮（图标 + 可选的下方名称）。"""

    activated = Signal(object)
    context_requested = Signal(object, object)

    def __init__(self, icon_size: int, *, show_text: bool = False, parent=None):
        super().__init__(parent)
        self.icon_size = icon_size
        self.setObjectName("DockIcon")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        if show_text:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            self.setFixedSize(max(icon_size + 20, 68), icon_size + 26)
        else:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.setFixedSize(icon_size + 14, icon_size + 14)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self, self.mapToGlobal(pos)))

    @staticmethod
    def elide(text: str, limit: int = 6) -> str:
        text = text or ""
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.activated.emit(self)
            return
        super().mouseReleaseEvent(event)


class DockBar(QWidget):
    """贴底的悬浮菜单栏。"""

    open_desktop_files = Signal()      # 打开完整收纳面板
    open_repository = Signal()         # 兼容旧接口：打开收纳目录
    open_panel = Signal()
    open_settings = Signal()
    quit_app = Signal()
    quick_changed = Signal()
    request_refresh = Signal()
    hide_requested = Signal()          # 请求隐藏整条菜单栏

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.dark = True                       # Dock 一律深色，和 macOS 观感一致
        self.p = theme_mod.palette(self.dark)
        self._icon_size = int(cfg.get("dock_icon_size", DEFAULT_ICON_SIZE)
                              or DEFAULT_ICON_SIZE)
        self._drag_offset = None
        self._buttons: "list[DockIcon]" = []
        self._strip_buttons: "list[DockIcon]" = []
        self._strip_page = 0
        self._strip_items: "list[engine.RepoItem]" = []

        # 布局稳定后校正位置用的短定时器（见 _settle）
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(60)
        self._settle_timer.timeout.connect(self._settle)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("桌面收纳 · 底部菜单栏")
        self.setWindowIcon(app_icon())
        self.setMouseTracking(True)

        self.loader = IconLoader(self, per_tick=3)
        self.loader.ready.connect(self._on_icon_ready)

        self._build_ui()
        self.apply_theme(self.dark)
        self.rebuild()
        self.reposition()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(MIN_MARGIN, 6, MIN_MARGIN, 6)

        self.surface = QFrame(self)
        self.surface.setObjectName("DockSurface")
        outer.addWidget(self.surface)

        column = QVBoxLayout(self.surface)
        column.setContentsMargins(10, 6, 10, 7)
        column.setSpacing(3)

        # ---- 分页行：快捷方式图标 + 名称 ----
        # 整行放一个容器里，方便一键隐藏/展开
        self.strip_panel = QWidget(self.surface)
        strip = QHBoxLayout(self.strip_panel)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(2)

        self.btn_strip_prev = QToolButton(self.strip_panel)
        self.btn_strip_prev.setObjectName("DockNav")
        self.btn_strip_prev.setText("◀")
        self.btn_strip_prev.setToolTip("上一页")
        self.btn_strip_prev.setFixedSize(22, 48)
        self.btn_strip_prev.clicked.connect(lambda: self.goto_strip_page(self._strip_page - 1))

        self.strip_host = QWidget(self.strip_panel)
        self.strip_row = QHBoxLayout(self.strip_host)
        self.strip_row.setContentsMargins(0, 0, 0, 0)
        self.strip_row.setSpacing(2)

        self.btn_strip_next = QToolButton(self.strip_panel)
        self.btn_strip_next.setObjectName("DockNav")
        self.btn_strip_next.setText("▶")
        self.btn_strip_next.setToolTip("下一页")
        self.btn_strip_next.setFixedSize(22, 48)
        self.btn_strip_next.clicked.connect(lambda: self.goto_strip_page(self._strip_page + 1))

        self.strip_page_label = QLabel("1/1", self.strip_panel)
        self.strip_page_label.setObjectName("DockPage")
        self.strip_page_label.setFixedWidth(34)
        self.strip_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        strip.addWidget(self.btn_strip_prev)
        strip.addWidget(self.strip_host, 1)
        strip.addWidget(self.btn_strip_next)
        strip.addWidget(self.strip_page_label)
        column.addWidget(self.strip_panel)

        self.strip_divider = QFrame(self.surface)
        self.strip_divider.setObjectName("DockDivider")
        self.strip_divider.setFixedHeight(1)
        column.addWidget(self.strip_divider)

        # ---- 应用区：会自动换行，加再多也不会把菜单栏撑出屏幕 ----
        self.apps_flow = FlowRow(self.surface, spacing=3)
        column.addWidget(self.apps_flow)

        # ---- 控制行：添加 / 收起 / 设置 / 隐藏，固定不换行 ----
        self.control_row = QHBoxLayout()
        self.control_row.setSpacing(3)
        column.addLayout(self.control_row)

        # 兼容旧代码里对 self.row 的引用
        self.row = self.control_row

    def _clear_strip(self) -> None:
        while self.strip_row.count():
            entry = self.strip_row.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        self._strip_buttons = []

    def _clear_row(self) -> None:
        """清空应用区与控制行。"""
        self.apps_flow.clear_items()
        while self.control_row.count():
            entry = self.control_row.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._buttons = []

    def _divider(self) -> QFrame:
        line = QFrame(self.surface)
        line.setObjectName("DockDivider")
        line.setFixedWidth(1)
        return line

    def _build_apps(self) -> None:
        """把「桌面整理」入口和常用启动图标填进可换行的应用区。"""
        # ---- 第一个控件：桌面整理 ----
        self.desktop_btn = self._make_button(
            icon_size=self._icon_size + 4,
            tooltip="桌面整理：打开分页面板，搜索 / 打开 / 还原桌面上的内容",
            fallback_text="桌",
            fallback_kind="desktop",
            on_click=lambda _btn: self.open_desktop_files.emit(),
            force_icon=make_desktop_glyph(self._icon_size + 4),
        )
        self.apps_flow.add_item(self.desktop_btn)

        separator = self._divider()
        separator.setFixedHeight(self._icon_size + 10)
        self.apps_flow.add_item(separator)

        # ---- 常用启动 ----
        for entry in self.cfg.quick_items:
            path = Path(entry["path"])
            name = entry["name"] or path.name
            exists = safety.safe_exists(path)
            button = self._make_button(
                icon_size=self._icon_size,
                tooltip=f"{name}\n{path}" + ("" if exists else "\n（已失效）"),
                fallback_text=name,
                fallback_kind=engine.kind_of(path) if exists else "other",
                on_click=lambda _btn, p=path: self._launch(p),
                payload=path,
                show_text=True,
            )
            button.setText(DockIcon.elide(name))
            button.context_requested.connect(
                lambda _btn, e=entry, b=button: self._quick_menu(b, e))
            self.apps_flow.add_item(button)

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------
    def rebuild(self) -> None:
        self._clear_row()
        self.loader.discard_pending()

        # 先把应用区排好，再让 refit() 统一算尺寸——
        # 反过来的话，刚加进去的按钮还没参与布局，算出来的尺寸是旧的
        # （之前"加完常用项菜单栏跑出屏幕"就是这个顺序问题）。
        self._build_apps()

        self.add_btn = QToolButton(self.surface)
        self.add_btn.setObjectName("DockAdd")
        self.add_btn.setText("＋")
        self.add_btn.setToolTip("把程序或文件加到菜单栏")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedSize(self._icon_size - 6, self._icon_size - 4)
        self.add_btn.clicked.connect(self._show_add_menu)
        self.row.addWidget(self.add_btn)

        # ---- 收起 / 展开上面那排分页 ----
        self.btn_toggle_strip = QToolButton(self.surface)
        self.btn_toggle_strip.setObjectName("DockNav")
        self.btn_toggle_strip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_strip.setFixedSize(self._icon_size - 10, self._icon_size - 6)
        self.btn_toggle_strip.clicked.connect(self.toggle_strip)
        self.row.addWidget(self.btn_toggle_strip)

        self.settings_btn = QToolButton(self.surface)
        self.settings_btn.setObjectName("DockNav")
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setFixedSize(self._icon_size - 10, self._icon_size - 6)
        self.settings_btn.clicked.connect(lambda: self.open_settings.emit())
        self.row.addWidget(self.settings_btn)

        # ---- 隐藏整条菜单栏 ----
        self.btn_hide_dock = QToolButton(self.surface)
        self.btn_hide_dock.setObjectName("DockNav")
        self.btn_hide_dock.setText("✕")
        self.btn_hide_dock.setToolTip(
            "隐藏整条菜单栏\n（之后可从托盘菜单「显示底部菜单栏」重新打开）")
        self.btn_hide_dock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hide_dock.setFixedSize(self._icon_size - 10, self._icon_size - 6)
        self.btn_hide_dock.clicked.connect(self.hide_self)
        self.row.addWidget(self.btn_hide_dock)

        self.control_row.addStretch(1)
        self._apply_strip_visibility()
        self._queue_icons()
        self.refit()

    # ------------------------------------------------------------------
    # 分页行 显示/隐藏
    # ------------------------------------------------------------------
    def strip_visible(self) -> bool:
        return bool(self.cfg.get("dock_strip_visible", True))

    def toggle_strip(self) -> None:
        """收起 / 展开上面那排分页，并**立刻把窗口尺寸改成新高度**。

        只切 setVisible 是不够的：顶层窗口不会自动跟着变大小，
        结果就是收起之后下面留一块空白。这里显式重新计算尺寸再贴回去。
        """
        self.cfg.set("dock_strip_visible", not self.strip_visible())
        self._apply_strip_visibility()
        self.refit()

    def _apply_strip_visibility(self) -> None:
        visible = self.strip_visible()
        self.strip_panel.setVisible(visible)
        self.strip_divider.setVisible(visible)
        if hasattr(self, "btn_toggle_strip"):
            self.btn_toggle_strip.setText("▼" if visible else "▲")
            self.btn_toggle_strip.setToolTip(
                "收起上面那排分页" if visible else "展开上面那排分页")

    def _max_width(self) -> int:
        """菜单栏允许的最大宽度：屏幕可用宽度留点边距。"""
        screen = self.screen().availableGeometry()
        return max(320, screen.width() - 40)

    def refit(self) -> None:
        """按当前内容重新计算并应用窗口大小（收起/展开、增删图标后都要调）。

        只切 setVisible 不够：顶层窗口不会自动跟着变大小，收起之后会留一块空白。
        而且**必须限制最大宽度**——常用启动加多了之后，如果不限制，
        窗口会比屏幕还宽，贴底时就会被挤出屏幕外面（之前就是这个毛病）。
        """
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        if self.surface.layout() is not None:
            self.surface.layout().activate()
        if self.layout() is not None:
            self.layout().activate()

        max_width = self._max_width()
        # 先让应用区按可用宽度决定每行放几个（放不下就换行，而不是被挤扁）
        inner = max_width - (MIN_MARGIN * 2) - 20
        self.apps_flow.relayout(inner)

        self.adjustSize()
        width = min(self.sizeHint().width(), max_width)
        height = self.sizeHint().height()
        self.setMinimumWidth(min(width, max_width))
        self.setMaximumWidth(max_width)
        self.resize(width, height)

        # 布局可能把窗口撑高（换行之后行数变了），所以按**实际**高度再贴一次底，
        # 保证底边永远不会掉到屏幕外。
        self.reposition()
        self._settle_timer.start()

    def _settle(self) -> None:
        """布局稳定后再校正一次位置。

        窗口显示出来之后 Qt 还有可能按布局调整一次尺寸；如果不在那之后再贴底，
        菜单栏就会有一部分探到屏幕下面去（之前"加完常用项跑到桌面外"的原因）。
        """
        self.reposition()

    def hide_self(self) -> None:
        """隐藏整条菜单栏，并广播出去（好让托盘菜单同步勾选状态）。"""
        self.cfg.set("dock_visible", False)
        self.hide_bar()
        self.hide_requested.emit()

    def _make_button(self, *, icon_size: int, tooltip: str, fallback_text: str,
                     fallback_kind: str, on_click, payload=None,
                     force_icon: "QPixmap | None" = None,
                     show_text: bool = False) -> DockIcon:
        button = DockIcon(icon_size, show_text=show_text, parent=self.surface)
        button.setToolTip(tooltip)
        button._payload = payload                      # noqa: SLF001
        pixmap = force_icon or letter_pixmap(
            fallback_text, PLACEHOLDER_COLORS.get(fallback_kind, "#94A3B8"), icon_size)
        button.setIcon(QIcon(pixmap))
        button.activated.connect(lambda btn: on_click(btn))
        self._buttons.append(button)
        return button

    def _queue_icons(self) -> None:
        for entry in self.cfg.quick_items:
            path = Path(entry["path"])
            if not safety.safe_exists(path):
                continue
            hint = (engine.resolve_shortcut_target(path)
                    if path.suffix.lower() == ".lnk" else None)
            self.loader.request(str(path), path, hint, self._icon_size,
                                entry["name"] or path.name)
        for item in self._strip_items:
            hint = (engine.resolve_shortcut_target(item.path)
                    if item.kind == "shortcut" else None)
            self.loader.request(str(item.path), item.path, hint, STRIP_ICON,
                                item.name)

    def _on_icon_ready(self, key: str, icon) -> None:
        for button in self._buttons + self._strip_buttons:
            payload = getattr(button, "_payload", None)
            if payload is not None and str(payload) == key:
                button.setIcon(icon)

    # ------------------------------------------------------------------
    # 分页行
    # ------------------------------------------------------------------
    def set_items(self, items: "list[engine.RepoItem]") -> None:
        """设置分页行要显示的内容（收纳目录内容 + 系统位置）。"""
        self._strip_items = list(items)
        if self._strip_page >= self.strip_pages():
            self._strip_page = max(0, self.strip_pages() - 1)
        self.rebuild_strip()

    def strip_pages(self) -> int:
        total = len(self._strip_items)
        return max(1, (total + STRIP_PAGE_SIZE - 1) // STRIP_PAGE_SIZE)

    def goto_strip_page(self, index: int) -> None:
        index = max(0, min(index, self.strip_pages() - 1))
        if index != self._strip_page:
            self._strip_page = index
            self.rebuild_strip()

    def rebuild_strip(self) -> None:
        self._clear_strip()
        start = self._strip_page * STRIP_PAGE_SIZE
        page = self._strip_items[start:start + STRIP_PAGE_SIZE]

        for item in page:
            button = DockIcon(STRIP_ICON, show_text=True, parent=self.strip_host)
            button.setText(DockIcon.elide(item.name))
            button.setToolTip(f"{item.name}\n{item.path}")
            button._payload = item.path                # noqa: SLF001
            # 缓存里有就直接用；没有才贴占位、排队去取。
            # 这样来回翻页时图标不会因为"重新去取但失败"而变空。
            cached_icon = self.loader.cached(str(item.path))
            if cached_icon is not None:
                button.setIcon(cached_icon)
            else:
                button.setIcon(QIcon(letter_pixmap(
                    item.name, PLACEHOLDER_COLORS.get(item.kind, "#94A3B8"),
                    STRIP_ICON)))
            button.activated.connect(lambda btn, it=item: self._open_item(it))
            button.context_requested.connect(
                lambda _btn, it=item: self._strip_menu(it))
            self.strip_row.addWidget(button)
            self._strip_buttons.append(button)

        if not page:
            placeholder = QLabel("这里还空着 —— 点左边「桌面整理」看看", self.strip_host)
            placeholder.setObjectName("DockEmpty")
            self.strip_row.addWidget(placeholder)
        self.strip_row.addStretch(1)

        pages = self.strip_pages()
        self.strip_page_label.setText(f"{self._strip_page + 1}/{pages}")
        self.btn_strip_prev.setEnabled(self._strip_page > 0)
        self.btn_strip_next.setEnabled(self._strip_page < pages - 1)
        self._queue_icons()
        self.refit()

    def _open_item(self, item: "engine.RepoItem") -> None:
        if item.kind == "shortcut" and nest.shell_path_for(item.path):
            ok, reason = nest.open_system_link(item.path)
        else:
            ok, reason = engine.launch(item.path)
        if not ok:
            self.setToolTip(f"{item.name}：{reason}")
            QTimer.singleShot(4000, lambda: self.setToolTip(""))

    def _strip_menu(self, item: "engine.RepoItem") -> None:
        menu = QMenu(self)
        action_open = menu.addAction("打开")
        action_add = menu.addAction("从常用启动移除"
                                    if self.cfg.is_quick(item.path) else "加为常用启动")
        action_restore = menu.addAction("还原到桌面")
        menu.addSeparator()
        action_panel = menu.addAction("在面板里查看")
        chosen = menu.exec(self.cursor().pos())
        if chosen is None:
            return
        if chosen is action_open:
            self._open_item(item)
        elif chosen is action_add:
            if self.cfg.is_quick(item.path):
                self.cfg.remove_quick(item.path)
            else:
                self.cfg.add_quick(item.path,
                                   item.path.stem if item.path.suffix else item.name)
            self.quick_changed.emit()
            self.rebuild()
        elif chosen is action_restore:
            ok, reason = nest.restore_item_to_desktop(self.cfg.desktop, item)
            if ok:
                self.request_refresh.emit()
            else:
                self.setToolTip(f"还原失败：{reason}")
        elif chosen is action_panel:
            self.open_desktop_files.emit()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _launch(self, path: Path) -> None:
        ok, reason = engine.launch(path)
        if not ok:
            self.setToolTip(f"{path.name}：{reason}")
            QTimer.singleShot(4000, lambda: self.setToolTip(""))

    def _quick_menu(self, button, entry: dict) -> None:
        path = Path(entry["path"])
        menu = QMenu(self)
        action_open = menu.addAction("打开")
        action_open.setEnabled(safety.safe_exists(path))
        action_reveal = menu.addAction("打开文件所在位置")
        menu.addSeparator()
        action_up = menu.addAction("左移")
        action_down = menu.addAction("右移")
        menu.addSeparator()
        action_remove = menu.addAction("从菜单栏移除")
        chosen = menu.exec(self.cursor().pos())
        if chosen is None:
            return
        if chosen is action_open:
            self._launch(path)
        elif chosen is action_reveal:
            engine.open_in_explorer(path)
        elif chosen is action_remove:
            self.cfg.remove_quick(path)
            self.quick_changed.emit()
            self.rebuild()
        elif chosen in (action_up, action_down):
            for index, candidate in enumerate(self.cfg.quick_items):
                if candidate["path"] == entry["path"]:
                    if self.cfg.move_quick(index, -1 if chosen is action_up else 1):
                        self.quick_changed.emit()
                        self.rebuild()
                    break

    def _show_add_menu(self) -> None:
        from qt_compat import QFileDialog, QInputDialog

        menu = QMenu(self)
        action_from_list = menu.addAction("从收纳内容里选…")
        action_file = menu.addAction("浏览文件…")
        chosen = menu.exec(self.add_btn.mapToGlobal(QPoint(0, -6)))
        if chosen is None:
            return
        if chosen is action_file:
            path, _filter = QFileDialog.getOpenFileName(
                self, "选择要加入菜单栏的程序或文件", str(Path.home()),
                "程序 (*.exe *.lnk *.bat *.cmd);;所有文件 (*.*)")
            if path:
                target = Path(path)
                if self.cfg.add_quick(target, target.stem):
                    self.quick_changed.emit()
                    self.rebuild()
            return
        if chosen is action_from_list:
            items = self._strip_items
            if not items:
                return
            names = [i.name for i in items]
            name, ok = QInputDialog.getItem(self, "加为常用", "选择要固定的项目：",
                                            names, 0, False)
            if ok and name:
                item = items[names.index(name)]
                if self.cfg.add_quick(item.path,
                                      item.path.stem if item.path.suffix else item.name):
                    self.quick_changed.emit()
                    self.rebuild()

    # ------------------------------------------------------------------
    # 主题 / 尺寸
    # ------------------------------------------------------------------
    def apply_theme(self, dark: bool = True) -> None:
        # Dock 固定深色（macOS 那种观感），不受应用主题影响
        self.setStyleSheet(theme_mod.stylesheet(True))
        self.setWindowOpacity(float(self.cfg.get("dock_opacity", 0.97) or 0.97))

    def set_icon_size(self, size: int) -> None:
        self._icon_size = max(28, min(80, int(size)))
        self.cfg.set("dock_icon_size", self._icon_size)
        self.rebuild()
        self.refit()

    def set_desktop_count(self, count: int) -> None:
        """兼容旧接口：只更新提示，不影响分页内容。"""
        if hasattr(self, "desktop_btn"):
            self.desktop_btn.setToolTip(
                f"桌面整理：收纳目录里现有 {count} 项\n搜索 / 打开 / 还原")

    # ------------------------------------------------------------------
    # 位置
    # ------------------------------------------------------------------
    def reposition(self) -> None:
        """贴到屏幕底部居中（或恢复上次水平位置），并保证完整落在屏幕内。"""
        screen = self.screen().availableGeometry()
        width, height = self.width(), self.height()
        # 兜底：万一还是比屏幕宽，先压缩到屏幕内，别让内容跑到屏幕外
        if width > screen.width():
            width = screen.width() - 20
            self.resize(width, height)

        saved = self.cfg.get("dock_x")
        if saved is None:
            x = screen.center().x() - width // 2
        else:
            try:
                x = int(saved)
            except (TypeError, ValueError):
                x = screen.center().x() - width // 2

        # 关键：上限必须不小于下限，否则 min/max 会互相顶掉，
        # 结果是窗口直接被推到屏幕外面去。
        left_limit = screen.left() + 4
        right_limit = max(left_limit, screen.right() - width - 4)
        x = max(left_limit, min(x, right_limit))
        y = screen.bottom() - height - 2
        self.move(x, y)

    def showEvent(self, event) -> None:  # noqa: N802
        """显示之后再贴一次底。

        Qt 在窗口显示后会按布局再调整一次尺寸；如果不在那之后重新定位，
        底边就可能探到屏幕外面（换行变高时尤其明显）。
        """
        super().showEvent(event)
        self.reposition()
        self._settle_timer.start()

    def show_bar(self) -> None:
        self.refit()
        self.show()
        self.raise_()
        if self.cfg.get("dock_always_on_top", True):
            self.raise_()

    def hide_bar(self) -> None:
        self.hide()

    # ------------------------------------------------------------------
    # 拖动 / 右键
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self.cfg.set("dock_x", self.x())
            self.reposition()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        action_files = menu.addAction("打开桌面收纳面板")
        action_restore_all = menu.addAction("全部还原到桌面")
        menu.addSeparator()

        action_strip = menu.addAction("收起分页行" if self.strip_visible() else "展开分页行")
        menu.addSeparator()

        size_menu = menu.addMenu("图标大小")
        for size in DOCK_ICON_SIZES:
            action = size_menu.addAction(f"{size} 像素")
            action.setCheckable(True)
            action.setChecked(size == self._icon_size)
            action.triggered.connect(lambda _c=False, s=size: self.set_icon_size(s))

        action_top = menu.addAction("总在最前")
        action_top.setCheckable(True)
        action_top.setChecked(bool(self.cfg.get("dock_always_on_top", True)))
        action_top.triggered.connect(self._toggle_on_top)

        menu.addSeparator()
        action_panel = menu.addAction("打开主面板")
        action_settings = menu.addAction("设置…")
        menu.addSeparator()
        action_hide = menu.addAction("暂时隐藏菜单栏")
        action_quit = menu.addAction("退出程序（并还原桌面）")

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is action_files:
            self.open_desktop_files.emit()
        elif chosen is action_strip:
            self.toggle_strip()
        elif chosen is action_restore_all:
            self.request_refresh.emit()
        elif chosen is action_panel:
            self.open_panel.emit()
        elif chosen is action_settings:
            self.open_settings.emit()
        elif chosen is action_hide:
            self.cfg.set("dock_visible", False)
            self.hide_bar()
        elif chosen is action_quit:
            self.quit_app.emit()

    def _toggle_on_top(self, checked: bool) -> None:
        self.cfg.set("dock_always_on_top", bool(checked))
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show_bar()
