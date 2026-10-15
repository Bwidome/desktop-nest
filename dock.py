#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部菜单栏（Dock）
==================
贴屏幕底部正中一条仿 macOS 的常驻悬浮栏：

    ┌──────────────────────────────────────────────────┐
    │ [▣ 桌面整理]  [微][S][E]…（常用启动，图标 + 名称） │
    └──────────────────────────────────────────────────┘

* **第一个控件就是"桌面整理"**，点它打开完整的收纳面板（分页 + 搜索）；
  再点一次收起。分页浏览收纳内容**全部在收纳面板里完成**，
  菜单栏本身不再放那排分页条目（那一行已经删掉）。
* 后面全是常用启动项，图标 + 名称
* **没有别的控件了**——需求："主菜单栏就保留第一个控件和常用软件"。
  ＋ / － / ⚙ / ✕ 四个按钮已删除，那四件事分别挪到：
  收纳面板的「管理」控件（加/减常用软件）、图标右键菜单、托盘菜单。
* **全部挤在同一行**：底板已经透明，分两行会显得很散
* 空白处右键出菜单栏设置

鼠标怎么用
----------
    · 点图标                → 启动
    · 按住任意位置**拖**    → 整条菜单栏沿屏幕底边左右移动（位置记在 dock_x）
    · 在常用软件上**长按**再拖 → 手动排序（有插入指示线，松手即生效）
    · 右键                  → 菜单栏设置

外观：**纯透明的浮层**——没有底板，只有「桌面整理」控件和常用软件的图标
浮在桌面上，见 theme 里的 `#DockSurface`。

图标清晰度：常用软件走 `icons.get_icon_best()`，两条高清来源都试
（Shell 的 256×256 jumbo / 直接从 exe 资源段按 256 抽），再让 Qt 平滑缩到
显示尺寸——原来只拿得到 32×32，拉到 44/52 显示就是放大糊图。
「桌面整理」那个矢量图标同理，预先画好 16~256 各档供 Qt 挑。
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
import nest
import safety
import theme as theme_mod
from widgets import (IconLoader, PLACEHOLDER_COLORS, app_icon, clear_hover,
                     letter_pixmap, multi_pick)

DOCK_ICON_SIZES = [36, 44, 52, 60]
DEFAULT_ICON_SIZE = 44
MIN_MARGIN = 8

# 「桌面整理」这个矢量图标要预先画成多少档位，供 Qt 按需挑
GLYPH_SIZES = (16, 24, 32, 48, 64, 96, 128, 192, 256)


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


def desktop_glyph_icon(size: int) -> QIcon:
    """「桌面整理」入口的多尺寸图标。

    这个图标是**画出来的**（不是从 Shell 取的），所以清晰度完全取决于
    我们画了几档。只画一张 48px 的话，换大图标或高 DPI 屏上就会被拉大变糊；
    这里把常用的几档都画进去，Qt 会按实际需要的尺寸挑最合适的那张，
    跟 `icons.get_icon_best()` 的 256×256 原图是同一个思路。
    """
    icon = QIcon()
    for edge in sorted(set(GLYPH_SIZES) | {max(1, int(size))}):
        icon.addPixmap(make_desktop_glyph(edge))
    return icon


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
    """Dock 上的一个图标按钮（图标 + 可选的下方名称）。

    除了"点一下启动"，它还要把三种鼠标意图分清楚并**上报给 DockBar**：

    * 原地按下再松开        → 点击（自己发 `activated`）
    * 按下后**很快**就拖动  → 拖整条菜单栏（DockBar 接管窗口移动）
    * 按下后**长按**住再拖  → 对常用软件排序（DockBar 接管）

    为什么长按判定放在这里、而"长按之后干什么"放在 DockBar：
    排序要改配置里的顺序、还要动布局、还要画插入指示线，那是菜单栏的事。
    按钮只负责"上报按下 / 移动 / 松开 + 一个长按计时器"，保持自己是哑的。

    ⚠️ `mouseReleaseEvent` 里**没有**调 `super()`：QToolButton 默认会在松开时
    自己发 `clicked`。这里要的是"拖过就不算点击"，所以自己判断、
    只发 `activated`，并顺手 `setDown(False)` 把按下态收掉。
    """

    HOLD_MS = 320          # 长按多久算"要排序"（比常规单击长，避免误触）
    DRAG_SLOP = 6          # 位移超过这么多像素就不算点击了

    activated = Signal(object)
    context_requested = Signal(object, object)
    press_notify = Signal(object, object)      # (self, 全局坐标)
    move_notify = Signal(object, object)
    release_notify = Signal(object, object)
    hold_notify = Signal(object, object)       # 长按到点了

    def __init__(self, icon_size: int, *, show_text: bool = False, parent=None):
        super().__init__(parent)
        self.icon_size = icon_size
        self._show_text = show_text
        # 由 DockBar 抬高，用来跟同一行里的按钮对齐（见 set_min_width）。
        self._min_width = 0
        self.setObjectName("DockIcon")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if show_text
                                else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._refit()
        # ---- 拖动 / 长按排序用的状态 ----
        self._pressed = False
        self._dragging = False            # 由 DockBar 置位：这次按下已升级成拖动
        self._last_global = QPoint(0, 0)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self.HOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self, self.mapToGlobal(pos)))

    # ------------------------------------------------------------------
    # 拖动状态（给 DockBar 用）
    # ------------------------------------------------------------------
    def set_dragging(self, value: bool) -> None:
        """标记"这次按下已经升级成拖动"，松开时就不再当成点击。"""
        self._dragging = bool(value)

    def _on_hold(self) -> None:
        if self._pressed and not self._dragging:
            self.hold_notify.emit(self, self._last_global)

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
            self.setFixedSize(max(self.icon_size + 14, self._min_width),
                              self.icon_size + 14)
            return
        text_width = QFontMetrics(self.font()).horizontalAdvance(self.text() or "")
        self.setFixedSize(max(self.icon_size + 20, text_width + 14, self._min_width),
                          self.icon_size + 26)

    def set_min_width(self, width: int) -> None:
        """把"最小宽度"抬高，用来和同一行里的其他按钮对齐。

        应用区是**等宽网格**（`FlowLayout.unit_size()` 取所有条目里最大的那个
        当格子宽）。「桌面整理」入口没有文字、比常用项按钮窄，不抬的话
        它右边就会空出一截——看上去正好是一块"空白占位格子"。
        抬到和常用项一样宽之后，两者之间就只剩布局自身的一个 spacing。
        """
        self._min_width = max(0, int(width))
        self._refit()

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

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._last_global = event.globalPosition().toPoint()
            self.press_notify.emit(self, self._last_global)
            # 长按计时器照常起：到底算不算"排序"由 DockBar 决定
            # （「桌面整理」入口也能拖动整条菜单栏，只是不能排序）。
            self._hold_timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pressed:
            self._last_global = event.globalPosition().toPoint()
            self.move_notify.emit(self, self._last_global)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self._hold_timer.stop()
            self._last_global = event.globalPosition().toPoint()
            # 先上报，让 DockBar 有机会把 _dragging 置位（同线程直连，是同步的）
            self.release_notify.emit(self, self._last_global)
            dragged = self._dragging
            self._dragging = False
            self.setDown(False)
            if not dragged and self.rect().contains(event.position().toPoint()):
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
        # 常用启动的按钮，**顺序与 cfg.quick_items 一一对应**（不含「桌面整理」入口）。
        # 拖动排序全靠它算目标槽位。
        self._app_buttons: "list[DockIcon]" = []
        # 收纳目录内容：不再显示在菜单栏上，只作为「＋ → 从收纳内容里选…」的候选
        self._items: "list[engine.RepoItem]" = []

        # ---- 拖动 / 长按排序的状态机 ----
        #   ""        没有拖动（按下还没超出阈值，也可能是点击）
        #   "window"  正在拖整条菜单栏
        #   "reorder" 正在给常用软件排序
        self._mode = ""
        self._press_icon: "DockIcon | None" = None
        self._press_global = QPoint(0, 0)
        self._press_in_window = QPoint(0, 0)
        self._reorder_from = 0
        self._reorder_to = 0
        # 松手时的全局坐标：用来判断"是不是拖到菜单栏外面了"（需求2）
        self._release_pos: "QPoint | None" = None
        self._drop_line: "QFrame | None" = None

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
        self.hide_drop_line()
        self.apps_flow.clear_items()
        for button in self._control_buttons:
            self.main_row.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._control_buttons = []
        self._buttons = []
        self._app_buttons = []
        self._clear_stretches()

    def _clear_stretches(self) -> None:
        """摘掉主行里之前加的弹性占位项。

        `rebuild()` 每次都会 `addStretch(1)`，但清场时只摘控制按钮——
        弹性占位项会**越积越多**。每个占位项都要占一份 spacing，
        重建几十次之后菜单栏就会莫名其妙地变宽（而且找不到原因）。
        """
        index = self.main_row.count() - 1
        while index >= 0:
            entry = self.main_row.itemAt(index)
            if entry is not None and entry.spacerItem() is not None:
                self.main_row.takeAt(index)
            index -= 1

    def _add_control(self, widget: QWidget) -> None:
        """把控制按钮摆进主行并登记（供 _clear_row 精确摘除）。"""
        self.main_row.addWidget(widget)
        self._control_buttons.append(widget)

    def _wire_control(self, button: QToolButton, slot) -> None:
        """接上控制按钮的点击：**先清掉 hover 高光**，再执行动作。

        跟图标按钮是同一个毛病：点完 ＋/⚙/✕ 之后鼠标还停在按钮上，
        Qt 不会补 leave 事件，`:hover` 那层底色就一直亮着。
        """
        def _run(*_args) -> None:
            clear_hover(button)
            slot()
        button.clicked.connect(_run)

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

    def _build_apps(self) -> None:
        """把「桌面整理」入口和常用启动图标填进可换行的应用区。"""
        # ---- 第一个控件：桌面整理 ----
        self.desktop_btn = self._make_button(
            icon_size=self._icon_size + 4,
            tooltip="桌面整理：点开分页面板（搜索 / 打开 / 还原到桌面）；再点一次收起",
            fallback_text="桌",
            fallback_kind="desktop",
            on_click=lambda _btn: self.toggle_desktop_files.emit(),
            force_icon=desktop_glyph_icon(self._icon_size + 4),
        )
        self.apps_flow.add_item(self.desktop_btn)

        # ⚠️ 这里**不再插分隔线**。
        # 应用区是等宽网格（`FlowLayout.unit_size()` 取所有条目里最大的那个），
        # 所以那根 1px 的竖线也会**占满一整格**（≈ 一个图标的宽度），
        # 「桌面整理」入口和第一个常用软件之间就凭空多出一块空白格——
        # 用户圈出来要删的"空白占位格子"正是它。
        # 现在两类图标只隔布局自身的一个 spacing，没有多余的空档。

        # ---- 常用启动 ----
        for entry in self.cfg.quick_items:
            path = Path(entry["path"])
            name = entry["name"] or path.name
            # "还在不在"要看本体 + 孪生路径：常用软件记的是上次它在的位置，
            # 桌面上那份和收纳目录里那份，只要有一份在就算有效。
            source = nest.icon_source(path, self.cfg.desktop)
            exists = source is not None
            button = self._make_button(
                icon_size=self._icon_size,
                tooltip=f"{name}\n{path}"
                        + ("" if exists else "\n（已失效）")
                        + "\n（按住可拖动排序）",
                fallback_text=name,
                fallback_kind=engine.kind_of(source or path) if exists else "other",
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
            self._app_buttons.append(button)

        # 初次对齐。字体在窗口显示出来之后才真正生效、按钮宽度会变，
        # 所以 `_resize_to_content()` 每次还会再校一次（见 `_align_desktop_button`）。
        self._align_desktop_button()

    def _align_desktop_button(self) -> None:
        """把「桌面整理」入口抬到和常用项按钮一样宽。

        应用区是**等宽网格**：入口没有文字、比常用项按钮窄，不抬的话
        它右边会空出一截（用户圈出来要删的"空白占位格子"的一半原因）。
        抬齐之后，入口和第一个常用项之间就只剩布局自身的一个 spacing，
        两边的图标也正好左右对齐。
        """
        if not self._app_buttons or getattr(self, "desktop_btn", None) is None:
            return
        widest = max(self.apps_flow._effective_size(b).width()      # noqa: SLF001
                     for b in self._app_buttons)
        self.desktop_btn.set_min_width(widest)

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

        # ---- 不再有任何控制按钮 ----
        # 需求：「主菜单栏就保留第一个控件和常用软件，其他的控件加号减号齿轮×删除」。
        # 所以 ＋ / － / ⚙ / ✕ 四个按钮全部去掉，菜单栏上只剩
        # 「桌面整理」入口 + 常用软件图标。
        #
        # 原来那四件事现在都在别处：
        #   ＋ 加常用 → 收纳面板的「管理」控件（卡片右上角的加号）/ 图标右键菜单
        #   － 删常用 → 收纳面板的「管理」控件（左上角减号）/ 图标右键菜单
        #   ⚙ 设置   → 托盘菜单「设置」
        #   ✕ 隐藏   → 托盘菜单「显示底部菜单栏」开关
        self.main_row.addStretch(1)
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
        # 入口要和常用项按钮一样宽。字体是窗口显示之后才真正生效的，
        # 按钮宽度会跟着变，所以每次重算尺寸前都再对齐一次（幂等）。
        self._align_desktop_button()
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
                     force_icon: "QPixmap | QIcon | None" = None,
                     show_text: bool = False) -> DockIcon:
        button = DockIcon(icon_size, show_text=show_text, parent=self.surface)
        button.setToolTip(tooltip)
        button._payload = payload                      # noqa: SLF001
        if force_icon is None:
            icon = QIcon(letter_pixmap(
                fallback_text, PLACEHOLDER_COLORS.get(fallback_kind, "#94A3B8"),
                icon_size))
        elif isinstance(force_icon, QIcon):
            icon = force_icon
        else:
            icon = QIcon(force_icon)
        button.setIcon(icon)
        button.activated.connect(lambda btn: self._on_icon_clicked(btn, on_click))
        # 拖动 / 长按排序：按钮只上报，怎么处理由菜单栏决定
        button.press_notify.connect(self._on_icon_press)
        button.move_notify.connect(self._on_icon_move)
        button.release_notify.connect(self._on_icon_release)
        button.hold_notify.connect(self._on_icon_hold)
        self._buttons.append(button)
        return button

    def _on_icon_clicked(self, button: DockIcon, on_click) -> None:
        """一次"干净的点击"：先把高光清掉，再执行动作。

        需求："打开软件后菜单栏的高光应该随之消失"。点完之后鼠标还停在
        图标上，Qt 不会自己发 leave 事件，`:hover` 那层底色就会一直亮着。
        """
        clear_hover(button)
        on_click(button)

    def _queue_icons(self) -> None:
        for entry in self.cfg.quick_items:
            path = Path(entry["path"])
            # 传给 loader 的是**身份路径**（配置里记着的那个）；真正该读哪个
            # 文件交给 `resolve` 在**取图那一刻**现算——见 IconLoader.request()。
            #
            # 这里以前是在排队时就把 `nest.icon_source()` 算死，结果是程序
            # 启动时全部取不到图：菜单栏先建好（常用软件还躺在桌面上），
            # 紧接着 `auto_take_desktop()` 把它们搬进收纳目录，
            # 等取图标的定时器第一次跑起来，排队时记的桌面路径早就没了。
            # 表现就是"打开软件后菜单栏的常用软件图标不能正常加载"。
            #
            # hi_res=True：菜单栏图标要放大显示，必须拿 256×256 的原图再缩，
            # 否则就是把 32×32 硬拉大（"图标清晰度太低"的根因）。
            self.loader.request(
                str(path), path, None, self._icon_size,
                entry["name"] or path.name, hi_res=True,
                resolve=lambda p=path: nest.icon_source(p, self.cfg.desktop))

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
        # 启动之后鼠标还停在图标上，先把高光清掉——
        # 不然那条 `:hover` 底色会一直亮着（用户说的"一直保持高亮"）。
        self.clear_hover()
        # 本体不在就启动孪生路径那一份：常用软件记的是上次运行时的位置，
        # 而桌面/收纳目录之间的搬动是程序自己的正常行为，不该让它失效。
        target = path if safety.safe_exists(path) else (
            nest.twin_path(path, self.cfg.desktop) or path)
        ok, reason = engine.launch(target)
        if not ok:
            self.setToolTip(f"{path.name}：{reason}")
            QTimer.singleShot(4000, lambda: self.setToolTip(""))

    def clear_hover(self) -> None:
        """清掉整条菜单栏上所有按钮的 hover 高光。"""
        for widget in list(self._buttons) + list(self._control_buttons):
            clear_hover(widget)

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
        # 菜单栏上已经没有「＋」按钮了，菜单就弹在菜单栏自己的正中间上方
        chosen = popup_menu(menu, self.mapToGlobal(QPoint(self.width() // 2, 0)))
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
    def _saved_pos(self) -> "tuple[int | None, int | None]":
        """上次记下的位置 `(x, y)`；没记过或值坏了就返回 `(None, None)`。"""
        def _read(key: str) -> "int | None":
            raw = self.cfg.get(key)
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
        return _read("dock_x"), _read("dock_y")

    def reposition(self) -> None:
        """按记住的位置摆放菜单栏，并保证它完整落在屏幕内。

        需求：「菜单栏应该可以自由移动而不是只能在底下移动」。
        所以横向、纵向都听 `dock_x` / `dock_y` 的；**从来没拖过**时才贴底居中
        （保持开箱即用的默认观感）。
        """
        screen = self.screen().availableGeometry()
        width, height = self.width(), self.height()
        # 兜底：万一比屏幕还大，先压缩到屏幕内，别让内容跑到屏幕外
        if width > screen.width():
            width = screen.width() - 20
        if height > screen.height():
            height = screen.height() - 20
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)

        saved_x, saved_y = self._saved_pos()
        if saved_x is None:
            x = screen.center().x() - width // 2
        else:
            x = saved_x
        if saved_y is None:
            y = screen.bottom() - height - 2      # 默认贴底
        else:
            y = saved_y

        # 关键：上限必须不小于下限，否则 min/max 会互相顶掉，
        # 结果是窗口直接被推到屏幕外面去。
        left_limit = screen.left() + 4
        right_limit = max(left_limit, screen.right() - width - 4)
        top_limit = screen.top() + 4
        bottom_limit = max(top_limit, screen.bottom() - height - 4)
        x = max(left_limit, min(x, right_limit))
        y = max(top_limit, min(y, bottom_limit))
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
    # 拖动整条菜单栏 / 长按排序常用软件
    # ------------------------------------------------------------------
    # 三种意图的判定（需求："这个菜单栏要可以拖动的" +
    # "菜单栏可以长按鼠标左键对软件进行手动排序"）：
    #
    #   按下空白处              → 直接拖整条菜单栏
    #   按下图标后**很快**移动  → 也是在拖整条菜单栏（不用非得找空白处下手）
    #   按下图标后**长按**再动  → 给常用软件排序
    #   按下图标原地松开        → 点击启动
    #
    # 为什么"按下图标快速移动"要归到拖整条菜单栏：菜单栏是**纯透明**的，
    # 视觉上整条都是"空白"，可实际上图标把能点的位置几乎铺满了——
    # 只留 8px 外边距能拖的话，用户根本找不到下手的地方。
    def _begin_window_drag(self) -> None:
        """进入"拖整条菜单栏"模式。"""
        self._mode = "window"
        self._drag_offset = self._press_in_window
        if self._press_icon is not None:
            self._press_icon.set_dragging(True)
            self._press_icon.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _apply_drag(self, global_pos: QPoint) -> None:
        """拖动中：**横竖都跟着鼠标走**。

        需求：「菜单栏应该可以自由移动而不是只能在底下移动」。
        早先这里只改 x、纵坐标交给 `reposition()` 贴底，理由是"贴底工具条"；
        现在改成自由摆放，所以 y 也要跟着动，并同样夹在屏幕可用区里，
        避免拖到屏幕外面找不回来。
        """
        if self._drag_offset is None:
            return
        screen = self.screen().availableGeometry()
        x = global_pos.x() - self._drag_offset.x()
        y = global_pos.y() - self._drag_offset.y()
        left_limit = screen.left() + 4
        right_limit = max(left_limit, screen.right() - self.width() - 4)
        top_limit = screen.top() + 4
        bottom_limit = max(top_limit, screen.bottom() - self.height() - 4)
        self.move(max(left_limit, min(x, right_limit)),
                  max(top_limit, min(y, bottom_limit)))

    def _on_icon_press(self, button: DockIcon, global_pos: QPoint) -> None:
        self._mode = ""
        self._press_icon = button
        self._press_global = QPoint(global_pos)
        self._press_in_window = global_pos - self.frameGeometry().topLeft()
        # 记下按下时在窗口里的相对位置，拖动时用它算窗口该挪到哪
        self._drag_offset = None

    def _on_icon_hold(self, button: DockIcon, global_pos: QPoint) -> None:
        """长按到点：如果按的是常用软件，就进入排序模式。"""
        if self._press_icon is not button or self._mode:
            return
        if self._app_index(button) < 0:
            return                      # 「桌面整理」入口不参与排序
        self._mode = "reorder"
        button.set_dragging(True)
        button.setDown(True)            # 按住的样子，提示"已经抓起来了"
        button.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._reorder_from = self._app_index(button)
        self._reorder_to = self._reorder_from
        self._drop_line_widget()

    def _on_icon_move(self, button: DockIcon, global_pos: QPoint) -> None:
        if self._press_icon is not button:
            return
        if self._mode == "reorder":
            self._update_reorder(global_pos)
            return
        if self._mode == "window":
            self._apply_drag(global_pos)
            return
        # 还没定模式：位移够大就算"在拖整条菜单栏"，不够就还是点击
        if (global_pos - self._press_global).manhattanLength() <= DockIcon.DRAG_SLOP:
            return
        self._begin_window_drag()
        self._apply_drag(global_pos)

    def _on_icon_release(self, button: DockIcon, global_pos: QPoint) -> None:
        mode = self._mode
        self._mode = ""
        self._press_icon = None
        # 记下松手位置：排序时用它判断有没有拖到菜单栏外面（需求2）
        self._release_pos = QPoint(global_pos)
        if mode == "reorder":
            button.setDown(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._commit_reorder()
        elif mode == "window":
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._drag_offset = None
            # 横竖都记：下次启动回到你放的位置（需求1：自由移动）
            self.cfg.set("dock_x", self.x())
            self.cfg.set("dock_y", self.y())
            self.reposition()
        # mode == "" → 什么都没发生，按钮自己会按"点击"处理

    def _app_index(self, button: DockIcon) -> int:
        """按钮在**常用软件**里的下标（不含「桌面整理」入口）；不在里面返回 -1。"""
        try:
            return self._app_buttons.index(button)
        except ValueError:
            return -1

    # ---- 排序指示线 --------------------------------------------------
    def _drop_line_widget(self) -> QFrame:
        """插入位置的那根竖线（懒创建，挂在 surface 上浮着）。"""
        if self._drop_line is None:
            line = QFrame(self.surface)
            line.setObjectName("DockDropLine")
            # 宽度要够：QSS 的 1px 白边是**画在控件内部**的，取 2px 的话
            # 左右两条边就把整条占满、中间的蓝色一点都看不见，只剩一根白棍。
            line.setFixedWidth(4)
            line.hide()
            self._drop_line = line
        return self._drop_line

    def hide_drop_line(self) -> None:
        if self._drop_line is not None:
            self._drop_line.hide()

    def _update_reorder(self, global_pos: QPoint) -> None:
        """按光标位置算出目标槽位，把指示线画到那儿，并**让位**。

        需求 2：「长按拖动图标插入到某个位置时，后面的软件会自动后移」。

        做法是"预留空位"：被拖的那个图标留在原位不动，其余图标按
        「目标槽位」重新排 —— 视觉上就等于别的图标主动向两边让开，
        松手后拖动的那个正好落进空出来的位置。
        """
        buttons = self._app_buttons
        if len(buttons) < 2:
            self.hide_drop_line()
            return
        cursor_x = global_pos.x()
        centers = [b.mapToGlobal(QPoint(b.width() // 2, 0)).x() for b in buttons]
        target = min(range(len(buttons)), key=lambda i: abs(cursor_x - centers[i]))
        self._reorder_to = target

        # 先让位（不管指示线画不画，位置都要跟着更新）
        self._apply_reorder_shift()

        if target == self._reorder_from:
            self.hide_drop_line()
            return

        line = self._drop_line_widget()
        button = buttons[target]
        corner = button.mapTo(self.surface, QPoint(0, 0))
        # 往左移就画在目标槽的左边缘，往右移就画在右边缘——
        # 这样线的位置就是"松手后它会落到哪"。
        offset = -4 if target < self._reorder_from else button.width() + 1
        line.setGeometry(corner.x() + offset, corner.y() + 3,
                         4, max(8, button.height() - 6))
        line.raise_()
        line.show()

    def _apply_reorder_shift(self) -> None:
        """把"让位"效果真的摆到界面上（纯视觉，不改配置）。

        网格是按行铺的，但图标宽度一致，所以用**横向位移**模拟插入最直观：

        * 被拖的那个：不动（它自己会跟着光标走）；
        * 夹在「原位置」和「目标位置」之间的那些：整体往反方向挪一格。

        这样松手前就已经能看出"它会插到这里"，而不是只有一根指示线。
        """
        buttons = self._app_buttons
        src, dst = self._reorder_from, self._reorder_to
        if not buttons or src == dst:
            self._reset_reorder_shift()
            return
        step = buttons[0].width() + self.apps_flow._spacing          # noqa: SLF001
        if dst > src:
            span = range(src + 1, dst + 1)
            offset = -step
        else:
            span = range(dst, src)
            offset = step
        for index, button in enumerate(buttons):
            if index == src:
                continue                    # 被拖的自己走
            button.move(button.x() + (offset if index in span else 0), button.y())

    def _reset_reorder_shift(self) -> None:
        """把让位造成的位移还原（松手 / 取消时调）。"""
        try:
            self.apps_flow.relayout(self._reorder_span_width())
        except Exception:
            pass

    def _reorder_span_width(self) -> int:
        """给 `relayout` 用的可用宽度（和 `_resize_to_content` 里同一套算法）。"""
        return max(160, self._max_width() - (MIN_MARGIN * 2) - 20
                   - self._controls_width())

    def _commit_reorder(self) -> None:
        """松手：把顺序写回配置并重建。

        需求 2 的后半句：「如果拖到桌面就保持原样不进行排序」。
        所以松手位置**在菜单栏之外**时直接放弃本次排序，顺序一点不动。
        """
        inside = self.rect().contains(self.mapFromGlobal(self._release_pos)) \
            if self._release_pos is not None else True
        self.hide_drop_line()
        self._reset_reorder_shift()
        src, dst = self._reorder_from, self._reorder_to
        if not inside:
            return                          # 拖到菜单栏外面 = 用户想取消
        if src == dst:
            return
        if self.cfg.move_to(src, dst):
            self.quick_changed.emit()
            self.rebuild()

    # ------------------------------------------------------------------
    # 拖动 / 右键
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # 按在菜单栏自己的空白处（图标之间的缝、四周留白）→ 直接拖整条
            self._press_icon = None
            self._press_global = event.globalPosition().toPoint()
            self._press_in_window = self._press_global - self.frameGeometry().topLeft()
            self._begin_window_drag()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (self._mode == "window" and self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self._apply_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._mode == "window" and self._press_icon is None:
            self._mode = ""
            self._drag_offset = None
            # 横竖都记（需求1：自由移动）
            self.cfg.set("dock_x", self.x())
            self.cfg.set("dock_y", self.y())
            self.reposition()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        action_files = menu.addAction("打开桌面收纳面板")
        action_restore_all = menu.addAction("全部还原到桌面")
        menu.addSeparator()
        # 菜单栏上原来的「＋」按钮已经删掉了，但"加常用软件"这件事还得有个入口：
        # 面板里挑不到的程序（不在收纳目录里），就从这里直接选文件。
        action_add_quick = menu.addAction("添加常用软件…")
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
        elif chosen is action_add_quick:
            self._show_add_menu()
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
