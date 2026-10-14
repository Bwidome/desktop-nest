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

外观：**贴底上滑的磨砂玻璃浮层**
--------------------------------
不是普通应用窗口，也不是白色矩形弹窗——它是从底部菜单栏上方"拉"出来的一块
**半透明深色磨砂玻璃**浮层（大圆角），和主面板共用同一套外观：

* 顶层窗口设 `WA_TranslucentBackground`，深色只画在内部的 `#Popup` 上；
* 真正的模糊由 DWM 提供（见 `acrylic.py`），窗口再按圆角裁一刀；
* 磨砂 + 圆角 + 深色调色板的公共逻辑在 `widgets.GlassCardMixin` 里。

关闭方式：`Esc`、点 ✕、再点一次 Dock 的「桌面整理」或托盘左键。
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    popup_menu,
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QPoint, QPushButton, QScrollArea, QSize, QToolButton,
    QVBoxLayout, QWidget, Qt, QTimer, Signal,
)

import engine
import nest
import theme as theme_mod
from textutil import fuzzy_match
from widgets import (GlassCardMixin, IconLoader, PLACEHOLDER_COLORS, app_icon,
                     icon_hint_for, letter_pixmap, multi_pick, pixmap_for)

GRID_ICON = 48
ICON_REQUEST = 64              # 向 Windows 要更大的图标再缩，清晰得多
CELL_W = 116
CELL_H = 110
DEFAULT_PER_PAGE = 28          # 7 列 × 4 行
PAGE_SIZE_CHOICES = [14, 21, 28, 35, 42]
APP_ICON = 34
# 贴底时默认给底部菜单栏让开的高度。主程序会用 Dock 的**真实高度**覆盖它
# （见 `set_bottom_reserve`）——写死一个值的话，菜单栏一变高，面板就会压在它身上。
DEFAULT_BOTTOM_RESERVE = 84


class ItemTile(QFrame):
    """网格里的一个卡片：**图标在上、名称在下**。"""

    activated = Signal(object)
    double_clicked = Signal(object)
    context_requested = Signal(object, object)

    def __init__(self, item: "engine.RepoItem", palette: dict,
                 show_extensions: bool = False, parent=None):
        super().__init__(parent)
        self.item = item
        self.p = palette
        self.selected = False
        self.setObjectName("FileTile")
        self.setFixedSize(CELL_W - 8, CELL_H - 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        display = engine.display_name(item.name, item.is_dir, show_extensions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 9, 6, 7)
        layout.setSpacing(6)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedHeight(GRID_ICON + 4)
        self.icon_label.setPixmap(
            letter_pixmap(display, PLACEHOLDER_COLORS.get(item.kind, "#94A3B8"),
                          GRID_ICON))
        layout.addWidget(self.icon_label)

        self.name_label = QLabel(display)
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

    def __init__(self, name: str, path: Path, palette: dict, parent=None,
                 show_extensions: bool = False):
        super().__init__(parent)
        self.app_name = name
        self.path = path
        self.setObjectName("AppButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(APP_ICON, APP_ICON))
        self.setFixedSize(78, 66)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 显示名统一按"真实文件名 + 后缀开关"算，配置里存的 name 可能是不带后缀的
        display = engine.display_name(path.name or name, False, show_extensions)
        self.setToolTip(f"{display}\n{path}")
        self.setText(self._elide(display))
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


class DesktopBrowser(GlassCardMixin, QWidget):
    """桌面收纳面板。"""

    request_refresh = Signal()
    request_quick_changed = Signal()
    request_settings = Signal()
    request_restore_all = Signal()

    # 悬浮磨砂玻璃浮层：磨砂 + 圆角裁剪 + 深色调色板都在 GlassCardMixin 里。
    # 收纳面板**固定深色**（不管应用主题），所以 self.dark 恒为 True。
    _glass_card_sel = "#Popup"
    _glass_log_name = "收纳面板"

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.dark = True
        self.p = theme_mod.glass_palette()

        self._items: "list[engine.RepoItem]" = []
        self._matches: "list[engine.RepoItem]" = []
        self._tiles: "list[ItemTile]" = []
        self._app_buttons: "list[AppButton]" = []
        self._page = 0
        self._per_page = int(cfg.get("page_size", DEFAULT_PER_PAGE) or DEFAULT_PER_PAGE)
        self._selected: "engine.RepoItem | None" = None
        # 贴底时给底部菜单栏让开多少高度（由主程序注入 Dock 的真实高度）
        self._reserve_provider = None

        # 这是一个**上拉菜单**，不是应用窗口：
        # * Tool —— 不进任务栏、不进 Alt+Tab，和弹出菜单一个待遇
        # * 不加 WindowStaysOnTopHint —— 点别的程序它会正常让到后面，不挡事
        # * 半透明背景 + 大圆角，贴在屏幕底部、菜单栏上方，像从底下拉出来的一块面板
        # 随时可以从底部菜单栏的「桌面整理」、托盘图标或托盘菜单再叫出来 / 收起来。
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("BrowserRoot")     # 顶层窗口自己不画底，见 theme.glass_block
        self.setWindowTitle("桌面收纳 · 收纳面板")
        self.setWindowIcon(app_icon())          # 左上角/任务栏要有个像样的图标
        self.setMinimumSize(560, 360)
        self._glass_init()

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
        self._apply_glass_palette()
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

    def apply_theme(self, dark: bool = True) -> None:
        # 收纳面板固定深色磨砂玻璃（需求如此），不受应用明暗主题影响；
        # 保留参数是为了和调用方（tray_app）的接口保持一致。
        self.dark = True
        self.p = theme_mod.glass_palette()
        self._restyle()
        for tile in self._tiles:
            tile.p = self.p
            tile._apply_style()
        self._rebuild_apps()
        if self._tiles:
            self._render_page()

    # ------------------------------------------------------------------
    # 显示文件后缀名
    # ------------------------------------------------------------------
    def show_extensions(self) -> bool:
        """当前是否显示文件后缀名（默认关闭）。"""
        return bool(self.cfg.get("show_extensions", False))

    def apply_extensions(self) -> None:
        """后缀开关变了：重画常用启动 + 当前页。

        只改显示文本；`ItemTile.item` / `AppButton.path` 指向的真实文件不动。
        """
        self._rebuild_apps()
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
            button = AppButton(name, path, self.p, self.apps_host,
                               show_extensions=self.show_extensions())
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
        self.btn_add_app.setToolTip("把程序或文件加到常用启动（可多选批量添加）")
        self.btn_add_app.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_app.setFixedSize(78, 66)
        self.btn_add_app.clicked.connect(self._show_add_menu)
        self.apps_row.addWidget(self.btn_add_app)

        # ---- 删除按钮：紧挨着「＋添加」，批量移除常用启动 ----
        self.btn_del_app = QToolButton(self.apps_host)
        self.btn_del_app.setObjectName("AppDel")
        self.btn_del_app.setText("－\n删除")
        self.btn_del_app.setToolTip("从常用启动里批量移除（可多选）")
        self.btn_del_app.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_app.setFixedSize(78, 66)
        self.btn_del_app.clicked.connect(self.remove_quick_dialog)
        # 一个都没有时没什么可删的，直接禁用，别让用户点了个空弹窗
        self.btn_del_app.setEnabled(bool(self._app_buttons))
        self.apps_row.addWidget(self.btn_del_app)

        self.apps_row.addStretch(1)
        # 没有任何常用项时「删除」没有意义，直接禁用（重建时也要重新判一次，
        # 否则删空之后按钮还亮着，点了只弹一个空弹窗）
        if hasattr(self, "btn_del_app"):
            self.btn_del_app.setEnabled(bool(self._app_buttons))
        # 增删之后行数/宽度会变，重新排一次版，避免留下空白
        self.apps_host.updateGeometry()

    def rebuild_apps(self) -> None:
        """公开的"重建常用启动这一排"入口（供主程序信号回调调用）。"""
        self._rebuild_apps()

    # ------------------------------------------------------------------
    # 常用启动：批量添加 / 批量删除
    # ------------------------------------------------------------------
    def _quick_name(self, path: Path) -> str:
        """给常用项取显示名：优先用"不带后缀"的名字，和别处保持一致。"""
        return engine.display_name(path.name, False, self.show_extensions())

    def _ask_multi(self, title: str, hint: str,
                   entries: "list[tuple[str, str]]", confirm_text: str):
        """弹多选列表。

        单独抽成一个方法是为了**可测试**：自动化测试里把它换成"直接返回
        指定 key"，就能在没有真人点复选框的情况下验证整条增删链路。
        直接打补丁改 `widgets.multi_pick` 是没用的——本模块是
        `from widgets import multi_pick` 按值导入的，改源头不影响这里。
        """
        return multi_pick(title, hint, entries, confirm_text, self)

    def add_quick_dialog(self) -> None:
        """从**下面的列表**里勾选多项，批量加入常用启动。

        需求：「按下从下面列表中选择按钮后，下方软件列表增加复选框，
        支持多选批量添加」。所以这里弹的是复选框列表，不是单选下拉。
        """
        if not self._items:
            QMessageBox.information(self, "加为常用启动",
                                    "收纳面板里还没有内容。\n先收纳桌面，或点「浏览文件…」挑一个程序。")
            return
        # 已经是常用的就不再列出来，避免勾了没反应
        candidates = [i for i in self._items if not self.cfg.is_quick(i.path)]
        if not candidates:
            QMessageBox.information(self, "加为常用启动",
                                    "下面列表里的项目都已经在常用启动里了。")
            return
        entries = [(str(i.path), self._quick_name(i.path)) for i in candidates]
        chosen = self._ask_multi(
            "批量加为常用启动",
            f"勾选要固定到「常用启动」的项目（共 {len(entries)} 项可选）：",
            entries, "加入")
        if not chosen:
            return
        by_key = {str(i.path): i for i in candidates}
        added = self.cfg.add_quick_many(
            [(p, self._quick_name(by_key[p].path)) for p in chosen if p in by_key])
        self.rebuild_apps()
        self.request_quick_changed.emit()
        self.hint.setText(f"已把 {added} 项加入常用启动" if added else "这些项目已经在常用启动里了")

    def remove_quick_dialog(self) -> None:
        """勾选多项，批量从常用启动移除。"""
        items = self.cfg.quick_items
        if not items:
            QMessageBox.information(self, "移除常用启动", "常用启动里还没有项目。")
            return
        entries = [(e["path"], e["name"] or Path(e["path"]).name) for e in items]
        chosen = self._ask_multi(
            "批量移除常用启动",
            f"勾选要移出「常用启动」的项目（共 {len(entries)} 项）：\n"
            "只影响这一排快捷方式，不会动桌面上的文件。",
            entries, "移除")
        if not chosen:
            return
        removed = self.cfg.remove_quick_many(chosen)
        # 先重建 UI 再通知外面：保证"配置—UI"两边的顺序、数量完全一致
        self.rebuild_apps()
        self.request_quick_changed.emit()
        self.hint.setText(f"已移除 {removed} 项")

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
        chosen = popup_menu(menu, pos)
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
        from qt_compat import QFileDialog

        menu = QMenu(self)
        action_here = menu.addAction("从下面的列表里选…（可多选）")
        action_file = menu.addAction("浏览文件…")
        chosen = popup_menu(menu, self.btn_add_app.mapToGlobal(
            QPoint(0, self.btn_add_app.height())))
        if chosen is None:
            return
        if chosen is action_here:
            # 多选批量添加
            self.add_quick_dialog()
            return
        if chosen is action_file:
            path, _filter = QFileDialog.getOpenFileName(
                self, "选择程序或文件", str(Path.home()),
                "程序 (*.exe *.lnk *.bat *.cmd);;所有文件 (*.*)")
            if path:
                target = Path(path)
                if self.cfg.add_quick(target, target.stem):
                    self.rebuild_apps()
                    self.request_quick_changed.emit()
            return

    # ---- 过滤 / 分页 ----
    def _filtered(self) -> "list[engine.RepoItem]":
        query = self.search.text().strip()
        if not query:
            return list(self._items)
        query_low = query.lower()
        out = []
        for item in self._items:
            hit, _index, _score = fuzzy_match(query, item.name)
            if not hit:
                # 不带后缀的名字也要能命中：搜「报告」要能找到「报告.docx」。
                # 两种写法都试一遍，跟界面上显示不显示后缀无关。
                hit, _index, _score = fuzzy_match(
                    query, engine.display_name(item.name, item.is_dir, False))
            if not hit and item.suffix and query_low in item.suffix:
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
        # 只丢弃"上一页那些卡片"的排队请求；常用启动那一排的请求要留着，
        # 否则翻页会把它们还没取到图标的请求一起清掉，那排就永远是占位色块。
        self.loader.discard_pending(keep=lambda key: key.startswith("app:"))

        start = self._page * self._per_page
        page_items = self._matches[start:start + self._per_page]
        columns = max(1, self._per_page // 4)

        for index, item in enumerate(page_items):
            tile = ItemTile(item, self.p, self.show_extensions(), self.grid_host)
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

        chosen = popup_menu(menu, pos)
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
        chosen = popup_menu(menu, self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height())))
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
        self.reposition()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def toggle_window(self) -> None:
        """打开 / 收起面板。

        Dock 上的「桌面整理」和托盘左键都走这里——再点一次就收起来，
        符合"上拉菜单"的直觉（而不是弹出一个只能点 ✕ 关掉的应用窗口）。
        """
        if self.isVisible():
            self.hide()
        else:
            self.show_window()

    def set_bottom_reserve(self, provider) -> None:
        """注册一个回调，返回"贴底时要让开的高度"。

        面板是"坐在"底部菜单栏上方向下滑出来的浮层，所以底边必须正好落在
        菜单栏顶边之上。菜单栏高度会变（图标大小、常用项换行…），写死一个数字
        迟早会被压住，所以交给主程序实时提供。
        """
        self._reserve_provider = provider

    def _bottom_reserve(self) -> int:
        if self._reserve_provider is not None:
            try:
                return max(0, int(self._reserve_provider()))
            except Exception:
                pass
        return DEFAULT_BOTTOM_RESERVE

    def reposition(self) -> None:
        """贴到屏幕底部正中、底部菜单栏上方。

        上拉菜单的观感：底边对齐、水平居中；同时保证整块面板不会跑到屏幕外
        （屏幕小或面板大时先压缩尺寸，再夹住坐标）。
        """
        screen = self.screen().availableGeometry()
        reserve = self._bottom_reserve()
        max_width = max(560, screen.width() - 60)
        max_height = max(320, screen.height() - reserve - 40)
        width = min(self.width(), max_width)
        height = min(self.height(), max_height)
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)

        x = screen.center().x() - width // 2
        x = max(screen.left() + 12, min(x, screen.right() - width - 12))
        # 给底部菜单栏留出空间，面板正好"坐在"它上面
        y = screen.bottom() - height - reserve
        y = max(screen.top() + 12, y)
        self.move(x, y)

    def _restore_geometry(self) -> None:
        """只恢复**大小**；位置永远由 reposition() 贴底决定。"""
        raw = str(self.cfg.get("panel_geometry") or "")
        width = height = 0
        if raw:
            parts = raw.split(",")
            if len(parts) == 4:
                try:
                    _x, _y, width, height = (int(p) for p in parts)
                except ValueError:
                    width = height = 0
        if width <= 0 or height <= 0:
            screen = self.screen().availableGeometry()
            width = min(880, max(560, screen.width() - 120))
            height = 460
        self.resize(max(560, width), max(360, height))
        self.reposition()

    def _save_geometry(self) -> None:
        self.cfg.set("panel_geometry",
                     f"{self.x()},{self.y()},{self.width()},{self.height()}")

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

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Ctrl + 滚轮翻页；普通滚轮留给滚动条。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.goto_page(self._page + (-1 if event.angleDelta().y() > 0 else 1))
            return
        super().wheelEvent(event)
