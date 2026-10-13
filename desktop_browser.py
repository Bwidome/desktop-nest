#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳面板（Dock 第一个控件点开的那个窗口）
==========================================
一屏解决"桌面上的东西去哪了、我要怎么用"：

    ┌──────────────────────────────────────────────────────┐
    │ 桌面收纳                              [刷新] [≡] [×]  │
    │ [ 常用启动：小快捷方式 图标+名称  …  ＋添加 ]          │   ← 顶部快捷方式行
    │ [🔍 搜索……………………………]                              │
    ├──────────────────────────────────────────────────────┤
    │   ▣ 此电脑    ▣ 回收站    📁 资料夹   📄 报告.docx …   │   ← 分页网格
    │   此电脑      回收站      资料夹      报告.docx        │      图标 + 下方名称
    ├──────────────────────────────────────────────────────┤
    │  ⏮ ‹ 1/2 › ⏭  共 38 项    [打开][加为常用][还原到桌面] │
    └──────────────────────────────────────────────────────┘

* **图标 + 下方名称**的显示方式
* 分页（默认 7 × 4 = 28 个/页）；Ctrl+滚轮也能翻页
* 实时模糊搜索，结果自动收拢
* 文件夹整体显示，双击在资源管理器里打开
* 系统位置（此电脑 / 回收站）也在这里，双击直接打开
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QPoint, QPushButton, QScrollArea, QSize, QToolButton,
    QVBoxLayout, QWidget, Qt, QTimer, Signal,
)

import engine
import nest
import theme as theme_mod
from textutil import fuzzy_match
from widgets import (IconLoader, PLACEHOLDER_COLORS, app_icon, icon_hint_for,
                      letter_pixmap, pixmap_for, set_widget_icon)

GRID_ICON = 48
ICON_REQUEST = 64              # 向 Windows 要更大的图标再缩，清晰得多
CELL_W = 116
CELL_H = 110
DEFAULT_PER_PAGE = 28          # 7 列 × 4 行
PAGE_SIZE_CHOICES = [14, 21, 28, 35, 42]
APP_ICON = 34


class ItemTile(QFrame):
    """网格里的一个卡片：**图标在上、名称在下**。"""

    activated = Signal(object)
    double_clicked = Signal(object)
    context_requested = Signal(object, object)

    def __init__(self, item: "engine.RepoItem", palette: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.p = palette
        self.selected = False
        self.setObjectName("FileTile")
        self.setFixedSize(CELL_W - 8, CELL_H - 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 9, 6, 7)
        layout.setSpacing(6)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedHeight(GRID_ICON + 4)
        self.icon_label.setPixmap(
            letter_pixmap(item.name, PLACEHOLDER_COLORS.get(item.kind, "#94A3B8"),
                          GRID_ICON))
        layout.addWidget(self.icon_label)

        self.name_label = QLabel(item.name)
        self.name_label.setObjectName("TileName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter |
                                     Qt.AlignmentFlag.AlignTop)
        self.name_label.setWordWrap(True)
        self.name_label.setFixedHeight(32)
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        self._apply_style()

    def set_icon(self, icon) -> None:
        if icon is not None and not icon.isNull():
            self.icon_label.setPixmap(pixmap_for(icon, GRID_ICON, self.icon_label))

    def set_selected(self, value: bool) -> None:
        if self.selected != value:
            self.selected = value
            self._apply_style()

    def _apply_style(self) -> None:
        c = self.p
        bg = c["accent_soft"] if self.selected else "transparent"
        border = c["accent"] if self.selected else "transparent"
        self.setStyleSheet(
            f"#FileTile {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 10px; }}")
        self.name_label.setStyleSheet(
            f"color: {c['accent'] if self.selected else c['text']};")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.item)
            # 双击打开程序后，高亮由窗口的定时器负责取消（见 select_item）
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(self.item,
                                        self.mapToGlobal(event.position().toPoint()))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.item)
        super().mouseDoubleClickEvent(event)


class AppButton(QToolButton):
    """顶部"常用启动"里的一个小快捷方式：图标 + 名称。"""

    activated = Signal(object)
    context_requested = Signal(object, object)

    def __init__(self, name: str, path: Path, palette: dict, parent=None):
        super().__init__(parent)
        self.app_name = name
        self.path = path
        self.setObjectName("AppButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(APP_ICON, APP_ICON))
        self.setFixedSize(78, 66)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name}\n{path}")
        self.setText(self._elide(name))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self, self.mapToGlobal(pos)))

    @staticmethod
    def _elide(text: str, limit: int = 5) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.activated.emit(self)
            return
        super().mouseReleaseEvent(event)


class DesktopBrowser(QWidget):
    """桌面收纳面板。"""

    request_refresh = Signal()
    request_quick_changed = Signal()
    request_settings = Signal()
    request_restore_all = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.dark = bool(cfg.get("dark"))
        self.p = theme_mod.palette(self.dark)

        self._items: "list[engine.RepoItem]" = []
        self._matches: "list[engine.RepoItem]" = []
        self._tiles: "list[ItemTile]" = []
        self._app_buttons: "list[AppButton]" = []
        self._page = 0
        self._per_page = int(cfg.get("page_size", DEFAULT_PER_PAGE) or DEFAULT_PER_PAGE)
        self._selected: "engine.RepoItem | None" = None
        self._drag_offset = None

        # 注意：这里**故意不加 WindowStaysOnTopHint**。
        # 面板是"用到才开"的窗口；如果永远压在别的程序上面，会挡住你正在做的事。
        # 不加这个标志后，点别的窗口它会正常让到后面，需要时用托盘图标或
        # Dock 上的按钮叫回来即可。（Dock 那条菜单栏是常驻工具，它才需要置顶。）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("桌面收纳 · 主面板")
        self.setWindowIcon(app_icon())          # 左上角/任务栏要有个像样的图标
        self.setMinimumSize(600, 420)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._rebuild)

        # 单击高亮后自动取消（1.2 秒），避免界面上一直留着一块亮色
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.setInterval(1200)
        self._highlight_timer.timeout.connect(self.clear_selection)

        # 图标加载器必须在 _build_ui() **之前**建好：
        # _build_ui() 末尾会走 apply_theme() → _rebuild_apps()，那里会查图标缓存。
        # 之前放在后面，导致一启动就 AttributeError: 'DesktopBrowser' object
        # has no attribute 'loader'。
        self.loader = IconLoader(self, per_tick=4)
        self.loader.ready.connect(self._on_icon_ready)

        self._build_ui()
        self._restore_geometry()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.surface = QFrame(self)
        self.surface.setObjectName("Popup")
        outer.addWidget(self.surface)

        root = QVBoxLayout(self.surface)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = QFrame(self.surface)
        self.toolbar.setObjectName("Toolbar")
        bar = QVBoxLayout(self.toolbar)
        bar.setContentsMargins(14, 10, 12, 10)
        bar.setSpacing(9)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel("桌面收纳")
        self.title.setObjectName("Title")
        title_row.addWidget(self.title)
        self.badge = QLabel("0 项")
        self.badge.setObjectName("Badge")
        title_row.addWidget(self.badge)
        title_row.addStretch(1)

        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("刷新")
        self.btn_refresh.setToolTip("重新读取收纳目录")
        self.btn_refresh.clicked.connect(lambda: self.request_refresh.emit())

        self.btn_more = QToolButton()
        self.btn_more.setText("≡")
        self.btn_more.setToolTip("更多")
        self.btn_more.clicked.connect(self._show_more_menu)

        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("关闭")
        self.btn_close.clicked.connect(self.hide)

        for button in (self.btn_refresh, self.btn_more, self.btn_close):
            title_row.addWidget(button)
        bar.addLayout(title_row)

        # 常用启动：图标 + 名称的小快捷方式
        self.apps_host = QWidget(self.surface)
        self.apps_row = QHBoxLayout(self.apps_host)
        self.apps_row.setContentsMargins(0, 0, 0, 0)
        self.apps_row.setSpacing(4)
        bar.addWidget(self.apps_host)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索这里的文件和快捷方式…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        search_row.addWidget(self.search, 1)
        self.btn_clear = QToolButton()
        self.btn_clear.setText("清空")
        self.btn_clear.clicked.connect(self.clear_search)
        search_row.addWidget(self.btn_clear)
        bar.addLayout(search_row)
        root.addWidget(self.toolbar)

        self.scroll = QScrollArea(self.surface)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.grid.setSpacing(2)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("Hint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        root.addWidget(self.empty_label)

        self.footer = QFrame(self.surface)
        self.footer.setObjectName("FooterBar")
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(14, 9, 12, 9)
        foot.setSpacing(6)

        self.btn_first = QToolButton(); self.btn_first.setText("⏮")
        self.btn_first.setToolTip("第一页")
        self.btn_first.clicked.connect(lambda: self.goto_page(0))
        self.btn_prev = QToolButton(); self.btn_prev.setText("‹")
        self.btn_prev.setToolTip("上一页")
        self.btn_prev.clicked.connect(lambda: self.goto_page(self._page - 1))
        self.page_label = QLabel("1 / 1")
        self.page_label.setObjectName("Muted")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(66)
        self.btn_next = QToolButton(); self.btn_next.setText("›")
        self.btn_next.setToolTip("下一页")
        self.btn_next.clicked.connect(lambda: self.goto_page(self._page + 1))
        self.btn_last = QToolButton(); self.btn_last.setText("⏭")
        self.btn_last.setToolTip("最后一页")
        self.btn_last.clicked.connect(lambda: self.goto_page(10 ** 6))
        for button in (self.btn_first, self.btn_prev, self.page_label,
                       self.btn_next, self.btn_last):
            foot.addWidget(button)

        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        foot.addWidget(self.hint)
        foot.addStretch(1)

        self.btn_open = QPushButton("打开")
        self.btn_open.setObjectName("Soft")
        self.btn_open.clicked.connect(self.open_selected)
        self.btn_add = QPushButton("加为常用")
        self.btn_add.clicked.connect(self.add_selected_to_apps)
        self.btn_restore = QPushButton("还原到桌面")
        self.btn_restore.clicked.connect(self.restore_selected)
        for button in (self.btn_open, self.btn_add, self.btn_restore):
            foot.addWidget(button)
        root.addWidget(self.footer)

        self.apply_theme(self.dark)

    def apply_theme(self, dark: bool) -> None:
        self.dark = dark
        self.p = theme_mod.palette(dark)
        self.setStyleSheet(theme_mod.stylesheet(dark))
        for tile in self._tiles:
            tile.p = self.p
            tile._apply_style()
        self._rebuild_apps()
        if self._tiles:
            self._render_page()

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def set_items(self, items: "list[engine.RepoItem]") -> None:
        self._items = items
        self._page = 0
        self._rebuild_apps()
        self._rebuild()

    def refresh_from_disk(self) -> None:
        """直接从磁盘重读。"""
        self.set_items(nest.list_nest_items())

    # ---- 顶部常用启动 ----
    def _rebuild_apps(self) -> None:
        while self.apps_row.count():
            entry = self.apps_row.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        self._app_buttons = []

        for entry in self.cfg.quick_items:
            path = Path(entry["path"])
            name = entry["name"] or path.name
            button = AppButton(name, path, self.p, self.apps_host)
            button.activated.connect(self._launch_app)
            button.context_requested.connect(self._app_menu)
            self.apps_row.addWidget(button)
            self._app_buttons.append(button)
            key = f"app:{path}"
            # 已经取过的图标直接贴上——不要依赖排队再发信号，
            # 否则每翻一页那排常用启动都会闪一下空白。
            cached_icon = self.loader.cached(key)
            if cached_icon is not None:
                button.setIcon(cached_icon)
            else:
                self.loader.request(key, path, icon_hint_for(path),
                                     ICON_REQUEST, name)

        self.btn_add_app = QToolButton(self.apps_host)
        self.btn_add_app.setObjectName("AppAdd")
        self.btn_add_app.setText("＋\n添加")
        self.btn_add_app.setToolTip("把程序或文件加到常用启动")
        self.btn_add_app.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_app.setFixedSize(78, 66)
        self.btn_add_app.clicked.connect(self._show_add_menu)
        self.apps_row.addWidget(self.btn_add_app)
        self.apps_row.addStretch(1)

    def _launch_app(self, button: AppButton) -> None:
        ok, reason = engine.launch(button.path)
        if not ok:
            QMessageBox.warning(self, "打不开", f"{button.app_name}\n\n{reason}")

    def _app_menu(self, button: AppButton, pos) -> None:
        menu = QMenu(self)
        action_open = menu.addAction("打开")
        action_reveal = menu.addAction("打开文件所在位置")
        menu.addSeparator()
        action_remove = menu.addAction("从常用启动移除")
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is action_open:
            self._launch_app(button)
        elif chosen is action_reveal:
            engine.open_in_explorer(button.path)
        elif chosen is action_remove:
            self.cfg.remove_quick(button.path)
            self._rebuild_apps()
            self.request_quick_changed.emit()

    def _show_add_menu(self) -> None:
        from qt_compat import QFileDialog, QInputDialog

        menu = QMenu(self)
        action_here = menu.addAction("从下面的列表里选…")
        action_file = menu.addAction("浏览文件…")
        chosen = menu.exec(self.btn_add_app.mapToGlobal(
            QPoint(0, self.btn_add_app.height())))
        if chosen is None:
            return
        if chosen is action_file:
            path, _filter = QFileDialog.getOpenFileName(
                self, "选择程序或文件", str(Path.home()),
                "程序 (*.exe *.lnk *.bat *.cmd);;所有文件 (*.*)")
            if path:
                target = Path(path)
                if self.cfg.add_quick(target, target.stem):
                    self._rebuild_apps()
                    self.request_quick_changed.emit()
            return
        if chosen is action_here:
            if not self._items:
                return
            names = [i.name for i in self._items]
            name, ok = QInputDialog.getItem(self, "加为常用", "选择要固定的项目：",
                                            names, 0, False)
            if ok and name:
                item = self._items[names.index(name)]
                if self.cfg.add_quick(item.path,
                                      item.path.stem if item.path.suffix else item.name):
                    self._rebuild_apps()
                    self.request_quick_changed.emit()

    # ---- 过滤 / 分页 ----
    def _filtered(self) -> "list[engine.RepoItem]":
        query = self.search.text().strip()
        if not query:
            return list(self._items)
        out = []
        for item in self._items:
            hit, _index, _score = fuzzy_match(query, item.name)
            if not hit and item.suffix and query.lower() in item.suffix:
                hit = True
            if hit:
                out.append(item)
        return out

    def _page_count(self) -> int:
        total = len(self._matches)
        return max(1, (total + self._per_page - 1) // self._per_page)

    def goto_page(self, index: int) -> None:
        index = max(0, min(index, self._page_count() - 1))
        if index != self._page:
            self._page = index
            self._render_page()
            self.scroll.verticalScrollBar().setValue(0)

    def _rebuild(self) -> None:
        self._matches = self._filtered()
        if self._page >= self._page_count():
            self._page = self._page_count() - 1
        self._render_page()

    def _render_page(self) -> None:
        while self.grid.count():
            entry = self.grid.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        self._tiles = []
        self.loader.discard_pending()
        self._rebuild_apps()

        start = self._page * self._per_page
        page_items = self._matches[start:start + self._per_page]
        columns = max(1, self._per_page // 4)

        for index, item in enumerate(page_items):
            tile = ItemTile(item, self.p, self.grid_host)
            tile.activated.connect(self.select_item)
            tile.double_clicked.connect(self._on_double_click)
            tile.context_requested.connect(self._show_tile_menu)
            self.grid.addWidget(tile, index // columns, index % columns)
            self._tiles.append(tile)
            key = str(item.path)
            hint = icon_hint_for(item.path, item.kind)
            # 缓存里已经有就直接贴上。只调 request() 是不够的——它在命中缓存时
            # 会直接返回、不再发信号，新卡片就永远等不到图标（翻页回来一片空白的原因）。
            cached_icon = self.loader.cached(key)
            if cached_icon is not None:
                tile.set_icon(cached_icon)
            else:
                self.loader.request(key, item.path, hint, ICON_REQUEST, item.name)

        total_cells = ((len(page_items) + columns - 1) // columns) * columns
        for index in range(len(page_items), total_cells):
            spacer = QWidget(self.grid_host)
            spacer.setFixedSize(CELL_W - 8, CELL_H - 8)
            self.grid.addWidget(spacer, index // columns, index % columns)

        self.empty_label.setVisible(not page_items)
        if not page_items:
            if self.search.text().strip():
                self.empty_label.setText("没有匹配的文件或快捷方式")
            else:
                self.empty_label.setText(
                    "这里还是空的\n\n程序启动时会自动把桌面上的东西收进来；\n"
                    "退出程序时会再把它们放回桌面。")

        pages = self._page_count()
        self.page_label.setText(f"{self._page + 1} / {pages}")
        self.btn_first.setEnabled(self._page > 0)
        self.btn_prev.setEnabled(self._page > 0)
        self.btn_next.setEnabled(self._page < pages - 1)
        self.btn_last.setEnabled(self._page < pages - 1)

        folders = sum(1 for i in self._items if i.is_dir)
        shortcuts = sum(1 for i in self._items if i.kind == "shortcut")
        files = len(self._items) - folders - shortcuts
        self.badge.setText(f"{len(self._matches)} 项")
        if self.search.text().strip():
            self.hint.setText(f"命中 {len(self._matches)} 项")
        else:
            self.hint.setText(
                f"共 {len(self._items)} 项（快捷方式 {shortcuts} · 文件夹 {folders}"
                f" · 文件 {files}）　每页 {self._per_page}")
        self._update_buttons()

    def _on_icon_ready(self, key: str, icon) -> None:
        for tile in self._tiles:
            if str(tile.item.path) == key:
                tile.set_icon(icon)
        for button in self._app_buttons:
            if f"app:{button.path}" == key:
                button.setIcon(icon)

    # ------------------------------------------------------------------
    # 选中 / 打开
    # ------------------------------------------------------------------
    def select_item(self, item: "engine.RepoItem", *, auto_clear: bool = True) -> None:
        """选中一个条目。

        单击会高亮，但高亮**不等同于"选中状态要一直留着"**：
        点开程序之后高亮应该自己消失，否则界面上总有一块亮着，
        看起来像没点成功。所以这里起一个短定时器自动取消高亮。
        键盘操作 / 需要保持选中时传 auto_clear=False。
        """
        self._selected = item
        for tile in self._tiles:
            tile.set_selected(tile.item is item)
        self._update_buttons()
        if auto_clear:
            self._highlight_timer.start()

    def clear_selection(self) -> None:
        """取消高亮与选中态。"""
        self._highlight_timer.stop()
        self._selected = None
        for tile in self._tiles:
            tile.set_selected(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self._selected is not None
        self.btn_open.setEnabled(has)
        self.btn_add.setEnabled(has)
        self.btn_restore.setEnabled(has)

    def open_selected(self) -> None:
        if self._selected is not None:
            self._open(self._selected)

    def _on_double_click(self, item: "engine.RepoItem") -> None:
        self._open(item)

    def _open(self, item: "engine.RepoItem") -> None:
        # 此电脑 / 回收站这类系统位置要走 explorer.exe
        if item.kind == "shortcut" and nest.shell_path_for(item.path):
            ok, reason = nest.open_system_link(item.path)
        else:
            ok, reason = engine.launch(item.path)
        if not ok:
            QMessageBox.warning(self, "打不开", f"{item.name}\n\n{reason}")

    def add_selected_to_apps(self) -> None:
        if self._selected is None:
            return
        item = self._selected
        name = item.path.stem if item.path.suffix else item.name
        if self.cfg.add_quick(item.path, name):
            self._rebuild_apps()
            self.request_quick_changed.emit()
            self.hint.setText(f"已把「{item.name}」加到常用启动")
        else:
            self.hint.setText(f"「{item.name}」已经在常用启动里了")

    def restore_selected(self) -> None:
        if self._selected is None:
            return
        item = self._selected
        if QMessageBox.question(
                self, "还原到桌面",
                f"把「{item.name}」放回桌面？\n\n文件只是移动，不会被删除。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        ok, reason = nest.restore_item_to_desktop(self.cfg.desktop, item)
        if ok:
            self.hint.setText(f"已把「{item.name}」放回桌面")
            self.request_refresh.emit()
        else:
            QMessageBox.warning(self, "还原失败", f"{item.name}\n\n{reason}")

    def clear_search(self) -> None:
        self.search.clear()
        self._rebuild()
        self.search.setFocus()

    # ------------------------------------------------------------------
    # 右键
    # ------------------------------------------------------------------
    def _show_tile_menu(self, item: "engine.RepoItem", pos) -> None:
        self.select_item(item)
        is_system = (item.kind == "shortcut"
                     and bool(nest.shell_path_for(item.path)))
        menu = QMenu(self)
        action_open = menu.addAction("打开")
        action_reveal = None if is_system else menu.addAction("打开文件所在位置")
        menu.addSeparator()
        action_add = menu.addAction("从常用启动移除"
                                    if self.cfg.is_quick(item.path) else "加为常用启动")
        action_restore = menu.addAction("还原到桌面")
        action_copy = menu.addAction("复制完整路径")
        action_size = menu.addAction("查看文件夹大小") if item.is_dir else None

        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is action_open:
            self._open(item)
        elif action_reveal is not None and chosen is action_reveal:
            engine.open_in_explorer(item.path)
        elif chosen is action_add:
            if self.cfg.is_quick(item.path):
                self.cfg.remove_quick(item.path)
                self._rebuild_apps()
                self.request_quick_changed.emit()
            else:
                self.add_selected_to_apps()
        elif chosen is action_restore:
            self.restore_selected()
        elif chosen is action_copy:
            QApplication.clipboard().setText(str(item.path))
            self.hint.setText("路径已复制")
        elif action_size is not None and chosen is action_size:
            files, folders = engine.folder_summary(item.path)
            QMessageBox.information(self, item.name,
                                    f"「{item.name}」里大约有：\n\n文件 {files} 个\n"
                                    f"子文件夹 {folders} 个")

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        size_menu = menu.addMenu("每页显示数量")
        for size in PAGE_SIZE_CHOICES:
            action = size_menu.addAction(f"{size} 个")
            action.setCheckable(True)
            action.setChecked(size == self._per_page)
            action.triggered.connect(lambda _checked=False, s=size: self.set_per_page(s))
        menu.addSeparator()
        action_restore_all = menu.addAction("全部还原到桌面")
        action_settings = menu.addAction("设置…")
        action_hide = menu.addAction("隐藏")
        chosen = menu.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height())))
        if chosen is action_restore_all:
            self.request_restore_all.emit()
        elif chosen is action_settings:
            self.request_settings.emit()
        elif chosen is action_hide:
            self.hide()

    def set_per_page(self, size: int) -> None:
        self._per_page = max(7, int(size))
        self.cfg.set("page_size", self._per_page)
        self._page = 0
        self._rebuild()

    # ------------------------------------------------------------------
    # 显示 / 位置
    # ------------------------------------------------------------------
    def show_window(self) -> None:
        self.refresh_from_disk()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def _restore_geometry(self) -> None:
        raw = str(self.cfg.get("panel_geometry") or "")
        if raw:
            parts = raw.split(",")
            if len(parts) == 4:
                try:
                    x, y, w, h = (int(p) for p in parts)
                    self.setGeometry(x, y, max(600, w), max(420, h))
                    return
                except ValueError:
                    pass
        screen = self.screen().availableGeometry()
        width, height = min(920, screen.width() - 80), min(600, screen.height() - 160)
        self.resize(width, height)
        self.move(screen.center().x() - width // 2,
                  screen.top() + max(50, (screen.height() - height) // 3))

    def _save_geometry(self) -> None:
        geometry = self.geometry()
        self.cfg.set("panel_geometry",
                     f"{geometry.x()},{geometry.y()},{geometry.width()},{geometry.height()}")

    def hideEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self.search.text():
                self.clear_search()
            else:
                self.hide()
            return
        if event.key() == Qt.Key.Key_PageDown:
            self.goto_page(self._page + 1)
            return
        if event.key() == Qt.Key.Key_PageUp:
            self.goto_page(self._page - 1)
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self._tiles:
            current = next((i for i, t in enumerate(self._tiles)
                            if t.item is self._selected), -1)
            step = -1 if event.key() == Qt.Key.Key_Left else 1
            target = current + step
            if 0 <= target < len(self._tiles):
                self.select_item(self._tiles[target].item)
            elif step > 0:
                self.goto_page(self._page + 1)
            else:
                self.goto_page(self._page - 1)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_selected()
            return
        if event.matches(Qt.KeySequence.StandardKey.Find):
            self.search.setFocus()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if pos.y() <= self.toolbar.height() + 4:
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_geometry()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Ctrl + 滚轮翻页；普通滚轮留给滚动条。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.goto_page(self._page + (-1 if event.angleDelta().y() > 0 else 1))
            return
        super().wheelEvent(event)
