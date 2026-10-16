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
    │  ⏮ ‹ 1/2 › ⏭  共 38 项   [打开][加为常用][还原到桌面] │
    └──────────────────────────────────────────────────────┘

* **图标 + 下方名称**的显示方式
* 分页（默认 7 × 4 = 28 个/页）；Ctrl+滚轮也能翻页
* 实时模糊搜索，结果自动收拢
* 文件夹整体显示，双击在资源管理器里打开
* 系统位置（此电脑 / 回收站）也在这里，双击直接打开

底部那三个按钮是**跟着选中项变的**：选中一个还没加过常用的，中间那个写
「加为常用」；选中一个已经在常用里的，它就变成「移出常用」。
右键单个条目还能「删除（移到回收站）」——进回收站、可还原，不是永久删除。

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

import config
import engine
import nest
import recycle
import theme as theme_mod
from textutil import fuzzy_match
from widgets import (GlassCardMixin, IconLoader, PLACEHOLDER_COLORS, app_icon,
                     icon_hint_for, letter_pixmap, multi_pick, pixmap_for)

GRID_ICON = 40                 # 网格里的图标显示尺寸（原来 48，偏大）
ICON_REQUEST = 64              # 向 Windows 要更大的图标再缩，清晰得多
CELL_W = 116
CELL_H = 110
DEFAULT_PER_PAGE = 28          # 7 列 × 4 行
PAGE_SIZE_CHOICES = [14, 21, 28, 35, 42]
APP_ICON = 34
# 从网格卡片拖到「常用软件」那一排时携带的 MIME 类型（需求5）
DND_MIME = "application/x-desktop-nest-item"
# 贴底时默认给底部菜单栏让开的高度。主程序会用 Dock 的**真实高度**覆盖它
# （见 `set_bottom_reserve`）——写死一个值的话，菜单栏一变高，面板就会压在它身上。
DEFAULT_BOTTOM_RESERVE = 84

# 管理模式里贴在卡片角上的「＋ / －」小圆钮
BADGE_SIZE = 20


class ManageBadge(QToolButton):
    """管理模式下贴在卡片角上的「＋ / －」小圆钮。

    需求：「收纳面板里的添加和删除控件整合成一个管理控件，点击后，
    如果是常用软件的话左上角有个减号，如果不是的话右上角有个加号」。

    做成**卡片的子控件**而不是自绘：子控件会自己吃掉鼠标事件，
    点角上的加号不会顺带把卡片本身点开（那是"打开程序"，误触代价太大）。
    """

    def __init__(self, parent, *, remove: bool, tooltip: str, slot,
                 corner: str):
        super().__init__(parent)
        # 减号（移出常用）用暖色、加号（加进常用）用主色，一眼能分清
        self.setObjectName("BadgeRemove" if remove else "BadgeAdd")
        self._corner = corner
        self.setText("－" if remove else "＋")
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(BADGE_SIZE, BADGE_SIZE)
        self.clicked.connect(slot)
        self.hide()

    def place(self) -> None:
        """贴到父控件的角上（父控件尺寸是固定的，建好就能摆）。"""
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - BADGE_SIZE - 2
             if self._corner == "top-right" else 2)
        self.move(max(0, x), 2)
        self.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.place()


class ItemTile(QFrame):
    """网格里的一个卡片：**图标在上、名称在下**。"""

    activated = Signal(object)
    double_clicked = Signal(object)
    context_requested = Signal(object, object)

    # 长按多久算"我要拖它"（毫秒）。太短会误触发，太长又显得迟钝。
    HOLD_MS = 350
    # 长按之后还要移动这么多像素才真的开始拖（防手抖）
    DRAG_SLOP = 8

    def __init__(self, item: "engine.RepoItem", palette: dict,
                 show_extensions: bool = False, parent=None):
        super().__init__(parent)
        self.item = item
        self.p = palette
        self.selected = False
        # 管理模式下贴在角上的「＋ / －」；由面板在需要时挂上来（见 _attach_badge）
        self.badge: "ManageBadge | None" = None
        self.setObjectName("FileTile")
        self.setFixedSize(CELL_W - 8, CELL_H - 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # 长按计时器：到点后允许把手势升级成"拖到常用软件那一排"（需求5）
        self._press_pos: "QPoint | None" = None
        self._drag_ready = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self.HOLD_MS)
        self._hold_timer.timeout.connect(self._begin_drag)

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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.badge is not None:
            self.badge.place()

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
            # 记下按下位置：长按之后要拖去"常用软件"那一排（需求5）
            self._press_pos = event.position().toPoint()
            self._drag_ready = False
            self._hold_timer.start()
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(self.item,
                                        self.mapToGlobal(event.position().toPoint()))
        super().mousePressEvent(event)

    # ---- 长按拖到「常用软件」那一排（需求5）--------------------------
    # 为什么要长按而不是直接拖：卡片单击就是"打开"，直接拖会和它抢手势，
    # 手一抖就把程序打开了。长按（默认 0.35 秒）之后才算"我要拖它"。
    def _begin_drag(self) -> None:
        """长按到点：把手势切成拖拽。"""
        self._drag_ready = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (self._drag_ready and self._press_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            # 位移太小就再等等，免得手抖也触发一次拖拽
            moved = (event.position().toPoint() - self._press_pos)
            if moved.manhattanLength() < self.DRAG_SLOP:
                return
            try:
                self._start_drag()
            finally:
                self._drag_ready = False
                self._hold_timer.stop()
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        super().mouseMoveEvent(event)

    def _start_drag(self) -> None:
        """真的发起一次 Qt 拖拽，MIME 里带着条目路径。"""
        from qt_compat import QDrag, QMimeData

        payload = QMimeData()
        payload.setData(DND_MIME, str(self.item.path).encode("utf-8"))
        payload.setText(str(self.item.path))          # 顺带支持拖到别处
        drag = QDrag(self)
        drag.setMimeData(payload)
        pixmap = self.icon_label.pixmap()
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._hold_timer.stop()
        self._drag_ready = False
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._hold_timer.stop()
        self._drag_ready = False
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.item)
        super().mouseDoubleClickEvent(event)


class QuickDropHost(QWidget):
    """「常用软件」那一排的容器，同时是**拖拽落点**（需求5）。

    需求：「收纳面板中支持长按拖动软件图标到收纳面板的常用软件栏来添加常用软件，
    同时菜单栏也要同时显示出新添加的常用软件」。

    单独做成一个控件、而不是给 `DesktopBrowser` 挂 `dragEnterEvent` 之类的
    方法，是因为拖拽事件只会发给**光标正下方的那个控件**。面板里铺满了几百个
    卡片，事件根本传不到外层的窗口上；必须让这一排自己声明"我能接收拖放"。

    视觉上：拖着东西悬在上面时，给一条高亮描边，让人知道"松手就加到这里"。
    """

    dropped = Signal(str)          # 落下的条目路径

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.p = palette
        self._active = False
        self.setAcceptDrops(True)

    # ---- 拖拽进入 / 移动 / 离开 --------------------------------------
    def _payload_from(self, event) -> str:
        data = event.mimeData()
        if data is None or not data.hasFormat(DND_MIME):
            return ""
        try:
            return bytes(data.data(DND_MIME)).decode("utf-8", "replace")
        except Exception:
            return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._payload_from(event):
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._payload_from(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        path = self._payload_from(event)
        self._set_active(False)
        if path:
            event.acceptProposedAction()
            self.dropped.emit(path)
        else:
            event.ignore()

    def _set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        c = self.p
        if active:
            self.setStyleSheet(
                f"#QuickDropHost {{ border: 1px dashed {c['accent']};"
                f" border-radius: 10px; background: {c['accent_soft']}; }}")
        else:
            self.setStyleSheet("")
        self.update()


class AppButton(QToolButton):
    """顶部"常用启动"里的一个小快捷方式：图标 + 名称。"""

    activated = Signal(object)
    context_requested = Signal(object, object)

    def __init__(self, name: str, path: Path, palette: dict, parent=None,
                 show_extensions: bool = False):
        super().__init__(parent)
        self.app_name = name
        self.path = path
        # 管理模式下的「－」（常用软件 → 左上角减号）；由面板挂上来
        self.badge: "ManageBadge | None" = None
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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.badge is not None:
            self.badge.place()

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
        # 管理模式：卡片角上长出「＋ / －」角标（由唯一的「管理」控件开关）
        self._manage_mode = False
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

        # 把条目**打开**之后，延迟一小会儿把高亮清掉（不是"单击就清"）。
        # 详见 `select_item()` 的说明：选中态要一直留着，右下角那几个按钮
        # 才有得点。
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
        # 这一排同时是"长按拖进来就加为常用"的落点（需求5）
        self.apps_host = QuickDropHost(self.p, self.surface)
        self.apps_host.setObjectName("QuickDropHost")
        self.apps_host.dropped.connect(self._on_quick_dropped)
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

        # ⚠️ `clicked` 是 `clicked(bool checked = False)`——它会**真的**把这个
        # bool 传进槽函数。`open_selected(self)` 只吃 `self`，PyQt 会按形参
        # 个数截断，所以它没事；但下面两个槽带默认参数（`item=None`），
        # PyQt 会认为"它还能再收一个"，于是把 `False` 当成 `item` 塞进去
        # → `False.path` / `False.name` → AttributeError。
        #
        # 而 PyQt6 里**槽函数里逃出去的异常会直接 abort 整个进程**：
        # 没有 traceback、没有报错框，界面就是"点了完全没反应"。
        # 这就是"右下角的加为常用控件无法正常使用"的真正原因。
        # 所以这里统一用 lambda 把那个 bool 吃掉，不让它进到业务方法里。
        self.btn_open = QPushButton("打开")
        self.btn_open.setObjectName("Soft")
        self.btn_open.clicked.connect(lambda _checked=False: self.open_selected())
        # 文案由 `_update_buttons()` 按"选中项是不是常用"动态改，
        # 所以这里只给个初始值（需求：不要写死"加为常用"）。
        self.btn_add = QPushButton("加为常用")
        self.btn_add.clicked.connect(lambda _checked=False: self.toggle_selected_quick())
        self.btn_restore = QPushButton("还原到桌面")
        self.btn_restore.clicked.connect(lambda _checked=False: self.restore_selected())
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
            self._attach_quick_badge(button, path)
            self._request_icon(f"app:{path}", path, name, button.setIcon)

        # ---- 唯一的控制按钮：管理 ----
        # 需求：「添加和删除控件整合成一个管理控件，点击后，如果是常用软件
        # 的话左上角有个减号，如果不是的话右上角有个加号」。
        # 所以这里不再有「＋添加」「－删除」两个按钮，只有这一个开关：
        # 点一下进管理模式，每个卡片角上长出对应的角标；再点一下退出。
        self.btn_manage = QToolButton(self.apps_host)
        self.btn_manage.setObjectName("AppManage")
        self.btn_manage.setCheckable(True)
        self.btn_manage.setChecked(self._manage_mode)
        self.btn_manage.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manage.setFixedSize(78, 66)
        self._sync_manage_button()
        self.btn_manage.clicked.connect(self.toggle_manage_mode)
        self.apps_row.addWidget(self.btn_manage)

        self.apps_row.addStretch(1)
        # 增删之后行数/宽度会变，重新排一次版，避免留下空白
        self.apps_host.updateGeometry()

    def rebuild_apps(self) -> None:
        """公开的"重建常用启动这一排"入口（供主程序信号回调调用）。"""
        self._rebuild_apps()

    # ------------------------------------------------------------------
    # 需求5：从网格长按拖到「常用软件」那一排 = 加为常用
    # ------------------------------------------------------------------
    def _on_quick_dropped(self, raw_path: str) -> None:
        """把拖进来的条目加为常用启动。

        加完立刻重建这一排、并 `request_quick_changed` 通知主程序 ——
        主程序会同步**菜单栏**，所以"面板里拖一下就出现在菜单栏上"（需求原话）。
        """
        try:
            path = Path(raw_path)
        except (TypeError, ValueError):
            return
        if not raw_path or not str(path):
            return
        if self.cfg.is_quick(path):
            self.hint.setText("这个条目已经在常用启动了")
            return
        name = self._quick_name(path)
        if not self.cfg.add_quick(path, name):
            self.hint.setText("加入常用启动失败")
            return
        self.rebuild_apps()
        self.request_quick_changed.emit()
        self.hint.setText(f"已把「{name}」加入常用启动")

    # ------------------------------------------------------------------
    # 图标：统一走"孪生路径 + 自愈缓存"
    # ------------------------------------------------------------------
    def _request_icon(self, key: str, path: Path, name: str, setter) -> None:
        """给一个控件取图标；`setter(icon)` 负责把图标贴上去。

        （`AppButton` 是 `setIcon`、`ItemTile` 是 `set_icon`，所以传一个
        setter 进来，而不是硬编码某个方法名。）

        **本体不在就用孪生路径**。常用软件记的是"上次它在的位置"，
        程序刚启动、东西还没收进来时那个路径是不存在的；直接去取，
        Shell 会回一张"未知文件类型"的白纸图标。

        ⚠️ 这个"该读哪一份"的判断**不能在这里定死**：面板建好的那一刻
        和真正轮到取图的那一刻，文件可能已经在两个地方之间搬过一趟了
        （启动流程正是如此）。所以传一个 `resolve` 回调给 loader，
        让它每次取图前**现算**——见 `widgets.IconLoader.request()`。
        """
        cached_icon = self.loader.cached(key)
        if cached_icon is not None:
            setter(cached_icon)
        # hi_res=True：这一排要显示 APP_ICON(34px) 的图标，
        # 而 SHGetFileInfoW 顶天只给 32×32，硬拉到 34 就糊了。
        # 走 get_icon_best() 拿 256×256 原图再由 Qt 缩下来。
        # hint 传 None：loader 会在取图时按解析出来的那个路径去解析 .lnk 目标。
        self.loader.request(
            key, path, None, ICON_REQUEST, name, hi_res=True,
            resolve=lambda p=path: nest.icon_source(p, self.cfg.desktop))

    def _attach_quick_badge(self, button: AppButton, path: Path) -> None:
        """给"常用软件"挂上左上角的减号（只在管理模式里露出来）。"""
        if button.badge is not None:
            button.badge.deleteLater()
        badge = ManageBadge(
            button, remove=True, corner="top-left",
            tooltip=f"从常用启动移除「{path.stem or path.name}」\n（只移除这一排快捷方式，不动文件）",
            slot=lambda _checked=False, p=path: self.remove_quick_path(p))
        button.badge = badge
        badge.setVisible(self._manage_mode)

    def _attach_tile_badge(self, tile: ItemTile) -> None:
        """给网格卡片挂角标：常用软件是左上角减号，其余是右上角加号。"""
        if tile.badge is not None:
            tile.badge.deleteLater()
            tile.badge = None
        item = tile.item
        if self.cfg.is_quick(item.path):
            badge = ManageBadge(
                tile, remove=True, corner="top-left",
                tooltip=f"把「{item.name}」移出常用启动\n（不动文件）",
                slot=lambda _checked=False, i=item: self.remove_quick_path(i.path))
        else:
            badge = ManageBadge(
                tile, remove=False, corner="top-right",
                tooltip=f"把「{item.name}」加到常用启动",
                slot=lambda _checked=False, i=item: self.add_item_to_apps(i))
        tile.badge = badge
        badge.setVisible(self._manage_mode)

    # ------------------------------------------------------------------
    # 管理模式
    # ------------------------------------------------------------------
    def toggle_manage_mode(self) -> None:
        """开关管理模式（唯一的"管理"控件）。"""
        self.set_manage_mode(not self._manage_mode)

    def set_manage_mode(self, value: bool) -> None:
        """进入 / 退出管理模式：卡片角上长出「＋ / －」角标。

        退出时顺手把高亮也清掉——管理模式下用户点的是角标，
        卡片本身那块高亮留着只会让人以为还没操作完。
        """
        self._manage_mode = bool(value)
        for button in self._app_buttons:
            if button.badge is not None:
                button.badge.setVisible(self._manage_mode)
        for tile in self._tiles:
            if tile.badge is not None:
                tile.badge.setVisible(self._manage_mode)
        self._sync_manage_button()
        self._update_buttons()
        if self._manage_mode:
            self.hint.setText("管理模式：点卡片角上的 ＋ 加入常用，点 － 移出")
        else:
            self._refresh_hint()

    def _sync_manage_button(self) -> None:
        button = getattr(self, "btn_manage", None)
        if button is None:
            return
        button.setChecked(self._manage_mode)
        button.setText("✓\n完成" if self._manage_mode else "⚙\n管理")
        button.setToolTip("退出管理模式" if self._manage_mode
                          else "管理常用软件：加号加入、减号移出（也可右键单个软件）")

    def _refresh_hint(self) -> None:
        """把底部提示恢复成"这一页有多少东西"的那句话。"""
        folders = sum(1 for i in self._items if i.is_dir)
        shortcuts = sum(1 for i in self._items if i.kind == "shortcut")
        files = len(self._items) - folders - shortcuts
        if self.search.text().strip():
            self.hint.setText(f"命中 {len(self._matches)} 项")
        else:
            self.hint.setText(
                f"共 {len(self._items)} 项（快捷方式 {shortcuts} · 文件夹 {folders}"
                f" · 文件 {files}）　每页 {self._per_page}")

    # ------------------------------------------------------------------
    # 单个条目的增删（角标 / 右键菜单都走这里）
    # ------------------------------------------------------------------
    def add_item_to_apps(self, item: "engine.RepoItem") -> bool:
        """把**指定条目**加进常用启动。

        参数显式传进来，不再依赖 `self._selected`：右键菜单是**模态**的，
        菜单打开期间那个"单击 1.2 秒后自动取消高亮"的定时器会照常触发，
        `_selected` 被清成 None，于是 `add_selected_to_apps()` 直接 return，
        用户看着就是"点了没反应，得再点一次"（需求里的
        "有时要点击多次才能成功添加"）。
        """
        name = item.path.stem if item.path.suffix else item.name
        if self.cfg.add_quick(item.path, name):
            self._rebuild_apps()
            self._render_page()
            self.request_quick_changed.emit()
            self.hint.setText(f"已把「{item.name}」加到常用启动")
            return True
        self.hint.setText(f"「{item.name}」已经在常用启动里了")
        return False

    def remove_quick_path(self, path: Path) -> bool:
        """把某个路径移出常用启动（角标 / 右键菜单都走这里）。"""
        if not self.cfg.remove_quick(path):
            return False
        self._rebuild_apps()
        self._render_page()
        self.request_quick_changed.emit()
        self.hint.setText(f"已把「{Path(path).stem or Path(path).name}」移出常用启动")
        return True

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
        # 卡片角上的「＋ / －」是按"是不是常用"长出来的，增删之后必须重画，
        # 否则刚加进去的那张卡片还挂着加号、已经移除的还挂着减号。
        self._render_page()
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
        self._render_page()          # 角标跟着"是不是常用"变，要重画
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
        menu.addSeparator()
        action_delete = menu.addAction("删除文件（移到回收站）")
        chosen = popup_menu(menu, pos)
        if chosen is None:
            return
        if chosen is action_open:
            self._launch_app(button)
        elif chosen is action_reveal:
            engine.open_in_explorer(button.path)
        elif chosen is action_remove:
            self.remove_quick_path(button.path)
        elif chosen is action_delete:
            # 常用项记的是"上次它在的位置"，程序刚启动时本体可能还在桌面、
            # 收纳目录里那份不存在（反之亦然）。所以删除前先用孪生路径
            # 把"真正在的那个文件"找出来，不然会对着一份不存在的路径删。
            real = nest.icon_source(button.path, self.cfg.desktop)
            if real is None:
                QMessageBox.information(
                    self, "不能删除",
                    f"「{button.app_name}」\n\n文件已经不在原来的位置了。")
            else:
                self.delete_path(real, button.app_name)

    def _show_add_menu(self, anchor: "QWidget | None" = None) -> None:
        """「从文件添加常用软件」的入口。

        「管理」控件只负责"从这一页挑"（角上的加号），
        想加面板里没有的程序就走这里；`anchor` 决定菜单弹在哪个控件下面。
        """
        from qt_compat import QFileDialog

        anchor = anchor or self.btn_manage
        menu = QMenu(self)
        action_here = menu.addAction("从下面的列表里选…（可多选）")
        action_file = menu.addAction("浏览文件…")
        chosen = popup_menu(menu, anchor.mapToGlobal(
            QPoint(0, anchor.height())))
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
                    self._render_page()
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
            self._attach_tile_badge(tile)
            # 缓存里已经有就直接贴上。只调 request() 是不够的——它在命中缓存时
            # 会直接返回、不再发信号，新卡片就永远等不到图标（翻页回来一片空白的原因）。
            self._request_icon(str(item.path), item.path, item.name, tile.set_icon)

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

        self.badge.setText(f"{len(self._matches)} 项")
        if not self._manage_mode:
            # 管理模式下那句"点角上的 ＋ / －"要留着，不能被统计信息顶掉
            self._refresh_hint()

        # 重建之后把选中态"重新认领"回来。
        # 卡片都是新造的，`_selected` 还指着上一批那个对象；不重认的话
        # 高亮会消失，而按钮却还按老对象亮着，两边对不上。
        # 认领失败（条目被删了 / 翻到别的页了）就清掉选中态。
        if self._selected is not None:
            self._selected = next(
                (t.item for t in self._tiles
                 if t.item is self._selected
                 or str(t.item.path) == str(self._selected.path)), None)
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
        """选中一个条目（高亮 + 让右下角那一排按钮跟上）。

        ⚠️ 这里**不再**"单击后 1.2 秒自动取消高亮"了。
        右下角的「打开 / 加为常用 / 还原到桌面」是照着"当前选中项"干活的，
        高亮一闪就没的话，用户还没来得及把鼠标挪到按钮上，按钮就已经灰了
        ——那也是一种"加为常用点了没反应"。所以选中态改成**一直留着**，
        直到下面任意一件事发生：

        * 选了别的条目；
        * 翻页 / 搜索 / 刷新（列表重建，原来的条目可能已经不在这一页了）；
        * 把它**打开**了（见 `_open`，那时高亮自己消失）；
        * 按 Esc（`clear_selection`）。

        `auto_clear` 参数保留只是为了兼容老调用方（右键菜单会传 False），
        现在它只影响"要不要重启那个延迟清除的定时器"。
        """
        self._selected = item
        for tile in self._tiles:
            tile.set_selected(tile.item is item)
        self._update_buttons()
        self._highlight_timer.stop()
        if not auto_clear:
            return
        # 保持选中，但给一个"这一下点到了"的视觉反馈窗口；
        # 真正的清除交给 `_open`（打开之后才该消失）。

    def clear_selection(self) -> None:
        """取消高亮与选中态。"""
        self._highlight_timer.stop()
        self._selected = None
        for tile in self._tiles:
            tile.set_selected(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        """让底部那一排按钮跟上"当前选中了什么"。

        这里最关键的是 `btn_add`：它**不是一个固定的"加为常用"**，而是
        一个开关——选中的东西已经是常用软件，它就该写"移出常用"。
        （需求原话："不应该写死是加为常用，应该是根据选中软件后判断
        是否是常用，如果不是的话才是加为常用，是的话则是移出常用"。）
        """
        target = self._selected
        has = target is not None
        self.btn_open.setEnabled(has)
        self.btn_restore.setEnabled(has)
        self.btn_add.setEnabled(has)

        if not has:
            self.btn_add.setText("加为常用")
            self.btn_add.setToolTip("先在下面选中一个条目")
            return

        if self.cfg.is_quick(target.path):
            self.btn_add.setText("移出常用")
            self.btn_add.setToolTip(
                f"把「{target.name}」从常用启动里移除\n（只移除这一排快捷方式，不动文件）")
        else:
            self.btn_add.setText("加为常用")
            self.btn_add.setToolTip(f"把「{target.name}」加到常用启动")

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
            return
        # 打开之后高亮就该自己消失——否则界面上总有一块亮着，像没点成功。
        # （原来这条逻辑挂在"单击选中"上，1.2 秒就把选中态一起清掉了，
        #   右下角那几个按钮跟着灰掉，根本来不及点。现在挂在"打开"上。）
        self._highlight_timer.start()

    def toggle_selected_quick(self) -> None:
        """右下角那个按钮：按"选中项是不是常用"决定加还是移。

        需求：「不应该写死是加为常用，应该根据选中软件判断是否是常用，
        如果不是的话才是加为常用，是的话则是移出常用」。
        """
        target = self._selected
        if target is None:
            self.hint.setText("先在下面选中一个条目")
            return
        if self.cfg.is_quick(target.path):
            self.remove_quick_path(target.path)
        else:
            self.add_item_to_apps(target)

    def add_selected_to_apps(self, item: "engine.RepoItem | None" = None) -> None:
        """把条目加进常用启动。

        `item` 显式给定时用它，不给才退回当前选中项。右键菜单一定要显式给
        ——菜单是模态的，打开期间 `_selected` 可能已经被清掉，
        光靠 `self._selected` 会出现"点了没反应，得再点一次"。
        """
        target = item if item is not None else self._selected
        if target is None:
            return
        self.add_item_to_apps(target)

    def restore_selected(self, item: "engine.RepoItem | None" = None) -> None:
        target = item if item is not None else self._selected
        if target is None:
            return
        item = target
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

    # ------------------------------------------------------------------
    # 删除（右键 → 移到回收站）
    # ------------------------------------------------------------------
    def delete_item(self, item: "engine.RepoItem") -> bool:
        """把**指定条目**移到回收站。右键菜单走这里。

        参数显式传进来（理由和 `add_selected_to_apps` 一样：菜单是模态的，
        打开期间 `_selected` 可能已经变了）。
        """
        return self.delete_path(item.path, item.name)

    def delete_path(self, path: Path, name: str = "") -> bool:
        """把一个路径移到回收站（网格卡片和"常用那一排"共用这一条路）。

        ⚠️ 这是整个程序里**唯一**会让文件从原位置消失的操作，所以：

        * 只在用户右键 →「删除（移到回收站）」时才会被调用；
        * 弹确认框，默认按钮是「否」（回车不会误删）；
        * 真正动手的是 `recycle.recycle()`，走 Shell 的 `FOF_ALLOWUNDO`
          ——进回收站，不是永久删除，随时能还原；
        * `recycle.guard()` 会把系统项 / 盘符根 / 收纳目录本体挡在外面。
        """
        path = Path(path)
        label = name or path.name or str(path)

        allowed, why = recycle.guard(path)
        if not allowed:
            QMessageBox.information(self, "不能删除", f"「{label}」\n\n{why}")
            return False

        if QMessageBox.question(
                self, "删除到回收站",
                f"把「{label}」移到回收站？\n\n"
                "· 文件不会真的消失，随时可以从回收站还原\n"
                "· 如果它已经是常用软件，会同时从常用启动里移除",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False

        ok, reason = recycle.recycle(path)
        if not ok:
            QMessageBox.warning(self, "删除失败", f"{label}\n\n{reason}")
            return False

        # 删掉了就别再把它留在"常用软件"里——否则菜单栏上会挂一个死链，
        # 点一下只会弹"打不开"。
        was_quick = self.cfg.is_quick(path)
        if was_quick:
            self.cfg.remove_quick(path)
        # 来源清单里那条也要清掉：不清的话，将来桌面上再出现一个同名文件
        # 会被误当成"从公共桌面收进来的"，还原时送错地方。
        try:
            nest.forget_source(path.name)
        except Exception:
            pass

        if self._selected is not None and Path(self._selected.path) == path:
            self._highlight_timer.stop()
            self._selected = None
        # refresh_from_disk() 内部会重建"常用那一排"和网格
        self.refresh_from_disk()
        if was_quick:
            self.request_quick_changed.emit()   # 同步菜单栏 / Dock / 托盘菜单
        self.request_refresh.emit()             # 让主程序重新扫一遍
        config.log(f"删除到回收站：{path}")
        self.hint.setText(f"已把「{label}」移到回收站（可还原）")
        return True

    def clear_search(self) -> None:
        self.search.clear()
        self._rebuild()
        self.search.setFocus()

    # ------------------------------------------------------------------
    # 右键
    # ------------------------------------------------------------------
    def _show_tile_menu(self, item: "engine.RepoItem", pos) -> None:
        # ⚠️ `auto_clear=False` 是必须的。菜单是**模态**的，会跑一个嵌套事件
        # 循环；选中态要是被那个延迟清除的定时器清掉，菜单里的动作就没目标了
        # （老的"加为常用启动"就是），用户就得"点好几次才成功一次"。
        # 现在既关掉自动清除，动作也改成显式传 item，双保险。
        self.select_item(item, auto_clear=False)
        self._highlight_timer.stop()
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
        # 删除放在最后一行，并且和上面隔开——它是这一串里唯一"会动数据"的动作，
        # 别让手一滑就点到。
        menu.addSeparator()
        action_delete = None if is_system else menu.addAction("删除（移到回收站）")

        chosen = popup_menu(menu, pos)
        if chosen is None:
            return
        if chosen is action_open:
            self._open(item)
        elif action_reveal is not None and chosen is action_reveal:
            engine.open_in_explorer(item.path)
        elif chosen is action_add:
            # 显式把 item 传下去，不看 `_selected`（菜单是模态的，见上面的说明）
            if self.cfg.is_quick(item.path):
                self.remove_quick_path(item.path)
            else:
                self.add_item_to_apps(item)
        elif chosen is action_restore:
            self.restore_selected(item)
        elif chosen is action_copy:
            QApplication.clipboard().setText(str(item.path))
            self.hint.setText("路径已复制")
        elif action_size is not None and chosen is action_size:
            files, folders = engine.folder_summary(item.path)
            QMessageBox.information(self, item.name,
                                    f"「{item.name}」里大约有：\n\n文件 {files} 个\n"
                                    f"子文件夹 {folders} 个")
        elif action_delete is not None and chosen is action_delete:
            self.delete_item(item)

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        size_menu = menu.addMenu("每页显示数量")
        for size in PAGE_SIZE_CHOICES:
            action = size_menu.addAction(f"{size} 个")
            action.setCheckable(True)
            action.setChecked(size == self._per_page)
            action.triggered.connect(lambda _checked=False, s=size: self.set_per_page(s))
        menu.addSeparator()
        action_manage = menu.addAction("退出管理模式" if self._manage_mode
                                       else "管理常用软件")
        action_add_file = menu.addAction("从文件添加常用软件…")
        # 常用的东西一多，逐个点角上的减号很烦；批量移除的入口留在这儿
        action_remove_many = menu.addAction("批量移除常用软件…")
        action_restore_all = menu.addAction("全部还原到桌面")
        action_settings = menu.addAction("设置…")
        action_hide = menu.addAction("隐藏")
        chosen = popup_menu(menu, self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height())))
        if chosen is action_manage:
            self.toggle_manage_mode()
        elif chosen is action_add_file:
            # 「管理」控件只负责"从这一页挑"；想加面板里没有的程序，
            # 走这里（老的批量多选弹窗也仍然保留，见 add_quick_dialog）
            self._show_add_menu()
        elif chosen is action_remove_many:
            self.remove_quick_dialog()
        elif chosen is action_restore_all:
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
