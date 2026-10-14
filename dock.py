#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部菜单栏（Dock）
==================
贴屏幕底部正中一条仿 macOS 的常驻悬浮栏：

    ┌────────────────────────────────────────────────────────────┐
    │ [▣ 桌面整理] │ [微][S][E]…（常用启动，图标+名称）  ＋  ⚙  ✕ │
    └────────────────────────────────────────────────────────────┘

* **第一个控件就是"桌面整理"**，点它打开完整的收纳面板（分页 + 搜索）；
  再点一次收起。分页浏览收纳内容**全部在收纳面板里完成**，
  菜单栏本身不再放那排分页条目（那一行已经删掉）。
* 中间是常用启动项，同样是图标 + 名称
* 右边依次是 ＋ 添加、－ 移除、⚙ 设置、✕ 隐藏整条菜单栏
* **全部挤在同一行**：底板已经透明，分两行会显得很散
* 空白处右键出菜单栏设置；按住可左右拖动，位置会记住

外观：**纯透明的浮层**——没有底板，只有「桌面整理」控件和常用软件的图标
（外加 ＋ / － / ⚙ / ✕ 四个小按钮）浮在桌面上，见 theme 里的 `#DockSurface`。
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    popup_menu,
    QColor, QFontMetrics, QFrame, QGridLayout, QHBoxLayout, QIcon, QMenu,
    QPainter, QPainterPath, QPixmap, QPoint, QSize, QToolButton, QVBoxLayout,
    QMessageBox, QWidget, Qt, QTimer, Signal,
)

import engine
import safety
import theme as theme_mod
from widgets import (IconLoader, PLACEHOLDER_COLORS, app_icon, letter_pixmap,
                     multi_pick)

DOCK_ICON_SIZES = [36, 44, 52, 60]
DEFAULT_ICON_SIZE = 44
MIN_MARGIN = 8


def make_desktop_glyph(size: int, accent: str = theme_mod.LIGHT["accent"]) -> QPixmap:
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

    ⚠️ **行列数必须自己记，不能问 QGridLayout。**
    这是"删掉一个常用软件，菜单栏的宽度却不缩回去"的根因：
    `QGridLayout` 在 `takeAt()` 之后**不会**把 `rowCount()/columnCount()` 收回
    （实测删掉一项后 `_items` 只剩 5 个，网格仍报 6 列），
    于是 `sizeHint()` 一直按旧列数算，菜单栏就永远维持着删之前的大小。
    所以 `relayout()` 把算好的 `(columns, rows)` 存进 `self._columns/_rows`，
    `sizeHint()` 只认这两个数，跟网格内部状态彻底解耦。
    """

    def __init__(self, parent=None, spacing: int = 3):
        super().__init__(parent)
        self._spacing = spacing
        self._items: "list[QWidget]" = []
        # 由 relayout() 写入；0 表示"还没排过版"，此时退化成"一行摆完"
        self._columns = 0
        self._rows = 0
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
        self._columns = 0
        self._rows = 0
        self.updateGeometry()

    def add_item(self, widget: QWidget) -> None:
        self._items.append(widget)

    def item_count(self) -> int:
        return len(self._items)

    def _effective_size(self, widget: QWidget) -> "QSize":
        """控件在布局里**实际**会占的尺寸。

        不能直接用 `sizeHint()`：`setFixedSize()` 只改 min/max，**不动
        `sizeHint()`**。像 `DockIcon` 这种把尺寸定死的按钮，`sizeHint()` 报的
        还是样式算出来的默认值（实测比实际窄 20 多像素），照它排版，
        菜单栏会比内容窄一截、最后一个图标被裁掉。
        这里按 `QWidgetItem` 的口径夹一次：sizeHint 先抬到 minimumSize、
        再压到 maximumSize。
        """
        hint = widget.sizeHint()
        minimum = widget.minimumSize()
        maximum = widget.maximumSize()
        width = min(max(hint.width(), minimum.width()), maximum.width())
        height = min(max(hint.height(), minimum.height()), maximum.height())
        return QSize(width, height)

    def unit_size(self) -> "QSize":
        """一个格子占多大（取所有条目里最大的那个）。"""
        if not self._items:
            return QSize(0, 0)
        sizes = [self._effective_size(w) for w in self._items]
        return QSize(max(s.width() for s in sizes),
                     max(s.height() for s in sizes))

    def natural_width(self) -> int:
        """内容排成一行时需要多宽。"""
        if not self._items:
            return 0
        unit = self.unit_size().width()
        return unit * len(self._items) + self._spacing * (len(self._items) - 1)

    def relayout(self, max_width: int) -> None:
        """按最大宽度决定每行放几个，重新摆一遍。"""
        while self._grid.count():
            self._grid.takeAt(0)
        if not self._items:
            self._columns = 0
            self._rows = 0
            self.updateGeometry()
            return

        unit = self.unit_size()
        unit_width = unit.width() + self._spacing
        columns = max(1, int(max_width // max(1, unit_width)))
        columns = min(columns, len(self._items))      # 别留空列，否则尺寸算大
        rows = (len(self._items) + columns - 1) // columns
        self._columns = columns
        self._rows = rows

        for index, widget in enumerate(self._items):
            widget.setParent(self)
            self._grid.addWidget(widget, index // columns, index % columns,
                                 Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        # 让每个格子只占它需要的大小，不要被拉伸（拉长了按钮会变形、图标会糊）
        for index in range(columns):
            self._grid.setColumnStretch(index, 0)
        for index in range(rows):
            self._grid.setRowStretch(index, 0)
        self._grid.invalidate()
        self.updateGeometry()

    def sizeHint(self):  # noqa: N802
        """内容按当前排列所需的尺寸（只认自己记的行列数）。"""
        if not self._items:
            return QSize(0, 0)
        unit = self.unit_size()
        columns = self._columns or len(self._items)
        rows = self._rows or 1
        width = unit.width() * columns + self._spacing * max(0, columns - 1)
        height = unit.height() * rows + self._spacing * max(0, rows - 1)
        return QSize(width, height)

    def minimumSizeHint(self):  # noqa: N802
        """最小尺寸同样只认自己的行列数。

        不覆盖的话会落到 QGridLayout 上，而它那个"删了不缩"的旧列数
        会把菜单栏的最小宽度顶住，`adjustSize()` 就再也收不回去了。
        """
        return self.sizeHint()


class DockIcon(QToolButton):
    """Dock 上的一个图标按钮（图标 + 可选的下方名称）。"""

    activated = Signal(object)
    context_requested = Signal(object, object)

    def __init__(self, icon_size: int, *, show_text: bool = False, parent=None):
        super().__init__(parent)
        self.icon_size = icon_size
        self._show_text = show_text
        self.setObjectName("DockIcon")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if show_text
                                else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._refit()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self, self.mapToGlobal(pos)))

    def _refit(self) -> None:
        """按图标 + **当前文字的实际宽度**定尺寸。

        以前这里写死 `max(icon_size + 20, 68)`。问题在于字号用的是 pt（会跟着
        系统 DPI 缩放），而写死的宽度不会：在 125% / 150% 缩放下，
        「任务管理器」这种名字根本装不下，相邻两项的文字会叠在一起。
        所以改成用 QFontMetrics 实测文字宽度。

        开头必须先 `ensurePolished()`：样式表里的字体要 polish 之后才生效，
        不先抛一次的话这里量到的是默认字体，算出来的宽度偏窄，
        等窗口显示出来又会变宽，菜单栏就会"长出来一截"。
        """
        self.ensurePolished()
        if not self._show_text:
            self.setFixedSize(self.icon_size + 14, self.icon_size + 14)
            return
        text_width = QFontMetrics(self.font()).horizontalAdvance(self.text() or "")
        self.setFixedSize(max(self.icon_size + 20, text_width + 14), self.icon_size + 26)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self._refit()

    def showEvent(self, event) -> None:  # noqa: N802
        # 样式表里的字体是 polish 之后才生效的，所以显示时再量一次。
        # _refit 是幂等的：字体稳定后重复调用不会改变尺寸。
        super().showEvent(event)
        self._refit()

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

    open_desktop_files = Signal()      # 打开收纳面板（菜单项：一定"打开"）
    toggle_desktop_files = Signal()    # 开关收纳面板（第一个控件：再点一次收起）
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
        # 收纳目录内容：不再显示在菜单栏上，只作为「＋ → 从收纳内容里选…」的候选
        self._items: "list[engine.RepoItem]" = []

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

        # ---- 整条菜单栏就是**一行**：应用区（会自动换行）+ 控制按钮 ----
        # 底板改成纯透明之后，只有一行才好看：以前是"应用一行、＋⚙✕ 另起一行"，
        # 有深色底板兜着还像一整条；底板一去，就变成上下两撮图标各自浮着，很散。
        # 所以「桌面整理 / 常用启动」和「＋ － ⚙ ✕」放进同一个 QHBoxLayout。
        self.main_row = QHBoxLayout()
        self.main_row.setSpacing(3)

        # 应用区：会自动换行，加再多也不会把菜单栏撑出屏幕
        self.apps_flow = FlowRow(self.surface, spacing=3)
        self.main_row.addWidget(self.apps_flow)

        column.addLayout(self.main_row)

        # 兼容旧代码里对 self.control_row / self.row 的引用
        self.control_row = self.main_row
        self.row = self.main_row
        # 控制按钮单独记一份：清空时只能摘掉它们，
        # **不能**顺手把 apps_flow 也从布局里拿掉（那样应用区就整个没了）
        self._control_buttons: "list[QWidget]" = []

    def _clear_row(self) -> None:
        """清空应用区与控制按钮。"""
        self.apps_flow.clear_items()
        for button in self._control_buttons:
            self.main_row.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._control_buttons = []
        self._buttons = []

    def _add_control(self, widget: QWidget) -> None:
        """把控制按钮摆进主行并登记（供 _clear_row 精确摘除）。"""
        self.main_row.addWidget(widget)
        self._control_buttons.append(widget)

    def _controls_width(self) -> int:
        """控制按钮那一串占的宽度（含间距）。

        图标和控制按钮现在同处一行，算换行时要先把这段宽度扣掉，
        否则应用区会按"整行都归我"来排，把控制按钮挤到屏幕外面去。
        """
        if not self._control_buttons:
            return 0
        gap = self.main_row.spacing()
        return (sum(b.width() for b in self._control_buttons)
                + gap * (len(self._control_buttons) + 1))

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
            tooltip="桌面整理：点开分页面板（搜索 / 打开 / 还原到桌面）；再点一次收起",
            fallback_text="桌",
            fallback_kind="desktop",
            on_click=lambda _btn: self.toggle_desktop_files.emit(),
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
            # 已经取过的图标**直接贴上**。
            # 这是"加了个新常用软件，旧的图标全没了"的根因：`IconLoader.request()`
            # 命中缓存时会直接 return、**不再发 ready 信号**，光靠 `_queue_icons()`
            # 的话，重建后这些按钮会永远停在占位字母上（只有这次新加的那个
            # 还没进缓存，才拿得到真图标）。desktop_browser 那边早就这么做了，
            # 菜单栏这边漏了。
            cached_icon = self.loader.cached(str(path))
            if cached_icon is not None:
                button.setIcon(cached_icon)
            button.context_requested.connect(
                lambda _btn, pos, e=entry, b=button: self._quick_menu(b, e, pos))
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
        self.add_btn.setToolTip("把程序或文件加到菜单栏（可多选批量添加）")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedSize(self._icon_size - 6, self._icon_size - 4)
        self.add_btn.clicked.connect(self._show_add_menu)
        self._add_control(self.add_btn)

        # ---- 删除按钮：紧挨在「＋」右边，批量移除常用启动 ----
        self.del_btn = QToolButton(self.surface)
        self.del_btn.setObjectName("DockDel")
        self.del_btn.setText("－")
        self.del_btn.setToolTip("从菜单栏批量移除常用启动（可多选）")
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.setFixedSize(self._icon_size - 6, self._icon_size - 4)
        self.del_btn.clicked.connect(self.remove_quick_dialog)
        # 没有常用项时禁用，避免点了弹空窗
        self.del_btn.setEnabled(bool(self.cfg.quick_items))
        self._add_control(self.del_btn)

        self.settings_btn = QToolButton(self.surface)
        self.settings_btn.setObjectName("DockNav")
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setFixedSize(self._icon_size - 10, self._icon_size - 6)
        self.settings_btn.clicked.connect(lambda: self.open_settings.emit())
        self._add_control(self.settings_btn)

        # ---- 隐藏整条菜单栏 ----
        self.btn_hide_dock = QToolButton(self.surface)
        self.btn_hide_dock.setObjectName("DockNav")
        self.btn_hide_dock.setText("✕")
        self.btn_hide_dock.setToolTip(
            "隐藏整条菜单栏\n（之后可从托盘菜单「显示底部菜单栏」重新打开）")
        self.btn_hide_dock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hide_dock.setFixedSize(self._icon_size - 10, self._icon_size - 6)
        self.btn_hide_dock.clicked.connect(self.hide_self)
        self._add_control(self.btn_hide_dock)

        self.main_row.addStretch(1)
        # 重建后重新判断「删除」是否可用（删空之后要变灰，否则点了弹空窗）
        if hasattr(self, "del_btn"):
            self.del_btn.setEnabled(bool(self.cfg.quick_items))
        self._queue_icons()
        self.refit()

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
        self._resize_to_content()
        self.reposition()
        self._settle_timer.start()

    def _resize_to_content(self) -> None:
        """按内容算出该多大并应用（`refit` 与 `_settle` 共用）。"""
        max_width = self._max_width()
        # 先让应用区按可用宽度决定每行放几个（放不下就换行，而不是被挤扁）。
        # 控制按钮现在和图标同处一行，所以要把它们占的宽度先扣掉，
        # 否则应用区会按"整行都归我"来排，把 ＋ ⚙ ✕ 挤出屏幕外面。
        inner = max_width - (MIN_MARGIN * 2) - 20 - self._controls_width()
        self.apps_flow.relayout(max(160, inner))

        self.adjustSize()
        width = min(self.sizeHint().width(), max_width)
        height = self.sizeHint().height()
        self.setMinimumWidth(min(width, max_width))
        self.setMaximumWidth(max_width)
        self.resize(width, height)

    def _settle(self) -> None:
        """布局稳定后再校正一次尺寸与位置。

        两个原因：
        * 窗口显示出来之后，样式表里的字体才真正生效，`DockIcon` 会在它的
          `showEvent` 里按**真实字宽**重算固定尺寸——也就是说 rebuild 当下算的
          宽度可能偏小，不再校一次，最后一个图标就会被裁掉一截；
        * 窗口显示后 Qt 还会按布局再调一次尺寸；不在这之后贴底，
          菜单栏就会有一部分探到屏幕下面去（之前"加完常用项跑到桌面外"的原因）。
        """
        self._resize_to_content()
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

    def _on_icon_ready(self, key: str, icon) -> None:
        for button in self._buttons:
            payload = getattr(button, "_payload", None)
            if payload is not None and str(payload) == key:
                button.setIcon(icon)

    # ------------------------------------------------------------------
    # 收纳内容（不再显示，只作为「＋ → 从收纳内容里选…」的候选）
    # ------------------------------------------------------------------
    def set_items(self, items: "list[engine.RepoItem]") -> None:
        """记下收纳目录里的内容，供「＋ 添加」时挑选。

        菜单栏上**不再**渲染这排分页条目——分页浏览全部在收纳面板里完成。
        """
        self._items = list(items)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _launch(self, path: Path) -> None:
        ok, reason = engine.launch(path)
        if not ok:
            self.setToolTip(f"{path.name}：{reason}")
            QTimer.singleShot(4000, lambda: self.setToolTip(""))

    def _quick_menu(self, button, entry: dict, pos=None) -> None:
        """常用启动图标的右键菜单。

        ⚠️ 这里**必须接收 pos**。`DockIcon.context_requested` 的签名是
        `(self, globalPos)`，而连接处写的是 `lambda _btn, e=entry, b=button:
        self._quick_menu(b, e)`（把 pos 丢掉了）。结果 Qt 只传两个参数时
        还能跑，一旦信号真带位置就会 `TypeError`——右键常用软件崩的就是这里。
        pos 现在既可以从信号来，也可以缺省（缺省时用鼠标当前位置）。
        """
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
        chosen = popup_menu(menu, pos)
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
        from qt_compat import QFileDialog

        menu = QMenu(self)
        action_from_list = menu.addAction("从收纳内容里选…（可多选）")
        action_file = menu.addAction("浏览文件…")
        chosen = popup_menu(menu, self.add_btn.mapToGlobal(QPoint(0, -6)))
        if chosen is None:
            return
        if chosen is action_from_list:
            self.add_quick_dialog()
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

    # ------------------------------------------------------------------
    # 常用启动：批量添加 / 批量删除
    # ------------------------------------------------------------------
    def _quick_display_name(self, path: Path) -> str:
        show_ext = bool(self.cfg.get("show_extensions", False))
        return engine.display_name(path.name, False, show_ext)

    def _ask_multi(self, title: str, hint: str,
                   entries: "list[tuple[str, str]]", confirm_text: str):
        """弹多选列表。

        单独抽成方法是为了测试时可注入（原因见 desktop_browser 的同名方法：
        `from widgets import multi_pick` 是按值导入的，改源头不生效）。
        """
        return multi_pick(title, hint, entries, confirm_text, self)

    def add_quick_dialog(self) -> None:
        """从收纳内容里勾选多项，批量加到菜单栏。"""
        items = self._items
        if not items:
            QMessageBox.information(
                self, "加为常用启动",
                "还不知道收纳目录里有什么。\n等扫描完成，或先用「浏览文件…」挑一个程序。")
            return
        candidates = [i for i in items if not self.cfg.is_quick(i.path)]
        if not candidates:
            QMessageBox.information(self, "加为常用启动",
                                    "收纳内容里的项目都已经在菜单栏上了。")
            return
        entries = [(str(i.path), self._quick_display_name(i.path))
                   for i in candidates]
        chosen = self._ask_multi(
            "批量加到菜单栏",
            f"勾选要固定到菜单栏的项目（共 {len(entries)} 项可选）：",
            entries, "加入")
        if not chosen:
            return
        by_key = {str(i.path): i for i in candidates}
        added = self.cfg.add_quick_many(
            [(p, self._quick_display_name(by_key[p].path))
             for p in chosen if p in by_key])
        self.quick_changed.emit()
        self.rebuild()
        if added:
            self.setToolTip(f"已加入 {added} 项")

    def remove_quick_dialog(self) -> None:
        """勾选多项，批量从菜单栏移除。"""
        entries_cfg = self.cfg.quick_items
        if not entries_cfg:
            QMessageBox.information(self, "移除常用启动", "菜单栏上还没有常用启动项。")
            return
        entries = [(e["path"], e["name"] or Path(e["path"]).name)
                   for e in entries_cfg]
        chosen = self._ask_multi(
            "批量移除常用启动",
            f"勾选要从菜单栏移出的项目（共 {len(entries)} 项）：\n"
            "只影响菜单栏这一排，不会动到文件本身。",
            entries, "移除")
        if not chosen:
            return
        removed = self.cfg.remove_quick_many(chosen)
        # 先自己重建，再发信号让主程序同步其它界面——顺序反了会读到中间态
        self.rebuild()
        self.quick_changed.emit()
        if removed:
            self.setToolTip(f"已移除 {removed} 项")

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

        chosen = popup_menu(menu, event)
        if chosen is None:
            return
        if chosen is action_files:
            self.open_desktop_files.emit()
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
