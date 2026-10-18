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
    · 在常用软件上**长按**再拖 → 手动排序（图标跟手 + 别的图标弹开让位）
    · 右键                  → 菜单栏设置

手动排序是**弹簧动画**的（见 `springs.py`）：
按住不动 0.32 秒进入排序模式，被拖的那个图标脱离槽位、跟着光标走，
其余图标用弹簧朝各自的新槽位弹过去（略微过冲，像被挤开的）；松手后
被拖的图标自己弹回最终槽位，然后才把控制权交回布局。
细节与踩过的坑见 `_update_reorder` / `_finish_settle` 的注释。

外观：**纯透明的浮层**——没有底板，只有「桌面整理」控件和常用软件的图标
浮在桌面上，见 theme 里的 `#DockSurface`。

图标清晰度：常用软件走 `icons.get_icon_best()`，两条高清来源都试
（Shell 的 256×256 jumbo / 直接从 exe 资源段按 256 抽），再让 Qt 平滑缩到
显示尺寸——原来只拿得到 32×32，拉到 44/52 显示就是放大糊图。
「桌面整理」那个矢量图标同理，预先画好 16~256 各档供 Qt 挑。
"""

from __future__ import annotations

import time
from pathlib import Path

from qt_compat import (
    popup_menu,
    QColor, QFontMetrics, QFrame, QGridLayout, QHBoxLayout, QIcon, QMenu,
    QPainter, QPainterPath, QPen, QPixmap, QPoint, QSize, QToolButton,
    QVBoxLayout, QMessageBox, QWidget, Qt, QTimer, Signal,
)

import engine
import nest
import safety
import springs
import theme as theme_mod
from widgets import (DND_MIME, FALLBACK_TILE_COLOR, IconLoader,
                     PLACEHOLDER_COLORS, Toast, app_icon, clear_hover,
                     letter_pixmap, multi_pick)

DOCK_ICON_SIZES = [36, 44, 52, 60]
DEFAULT_ICON_SIZE = 44
MIN_MARGIN = 8

#: 图标之间的间距（3 → 6）。原来是"挨着"，一排十几个图标会连成一片，
#: 读起来是一堵墙；留出 6px 之后每个图标才是独立的一项。
#: ⚠️ `FlowRow` 的 spacing 与主行的 spacing 必须**用同一个值**：
#: 换行之后行内间距和行间间距不一样的话，第二行会看着比第一行挤。
DOCK_GAP = 6

#: 菜单栏**不画底板、不画阴影**：底板纯透明，图标直接浮在桌面上。
#: （Phase 4 试过在 `paintEvent` 里垫一层很淡的同心圆角矩形当"影子"，
#:  但浅色壁纸上看就是一块半透明板子——用户明确要求回到纯透明的观感，
#:  所以这里不再有任何绘制。要加回来请先确认壁纸是深色的。）

# --------------------------------------------------------------------------
# 排序让位的弹簧手感（积分器在 springs.py）
# --------------------------------------------------------------------------
#: 让位的那些图标：略欠阻尼 —— 会轻轻过冲一点点再停住，就是"被挤开"的观感。
#: 刚度 340 → ω≈18.4 rad/s，settle 时间 ≈ 4/(0.8·18.4) ≈ 0.27s，干脆利落。
REORDER_SPRING = {"stiffness": 340.0, "ratio": 0.80}

#: 被拖的那个图标：临界阻尼 + 大刚度 —— 紧紧跟手，但**绝不过冲**，
#: 否则拖拽时图标会在光标前后晃，看起来就是"抖"。
#: 刚度 2600 → ω≈51 rad/s，跟随延迟 ≈ 60ms，肉眼几乎察觉不到。
DRAGGED_SPRING = {"stiffness": 2600.0, "ratio": 1.0}

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

    def reorder(self, ordered: "list[QWidget]") -> bool:
        """按 `ordered` 给出的顺序重排**已有**条目（不销毁、不新建控件）。

        拖动排序提交后要立刻把视觉顺序固定下来，但**不能重建控件**——
        重建会让所有图标消失一帧再出现，回弹动画也白做了。
        所以这里只改 `_items` 的顺序，等动画停下来 `relayout()` 一跑，
        布局自然就按新顺序摆。返回是否真的改了。

        ⚠️ 只接受"现有条目的一个排列"：数量或成员对不上就整个拒绝，
        免得把布局搞成半新半旧的状态。
        """
        ordered = list(ordered)
        if len(ordered) != len(self._items):
            return False
        if sorted(map(id, ordered)) != sorted(map(id, self._items)):
            return False
        if ordered == self._items:
            return False
        self._items = ordered
        return True

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


class DockToast(Toast):
    """菜单栏专用的轻提示：浮在菜单栏**正上方**的独立小窗。

    为什么不直接 `Toast(dock)`：`Toast` 是**子控件**，会被父窗口裁掉，
    而菜单栏窗口正好只有图标那么高，塞不下一条提示（塞进去就会压住图标）。

    做成顶层小窗还要多处理一件事：**顶层 widget 的 QSS 背景不会绘制**
    （实测 `#ToastOk` 那层底透明得干干净净，只剩一行字浮在壁纸上），
    连 `WA_StyledBackground` 也救不回来 —— 那是 `WA_TranslucentBackground`
    打开之后 Qt 不再走"画控件底"那条路。所以药丸底自己画（见 `paintEvent`），
    文字颜色仍然交给 QSS（`#ToastOk` 的 `color` 是生效的）。
    """

    #: 离菜单栏顶边的距离
    GAP = 10

    def __init__(self, anchor: QWidget):
        super().__init__(None, duration=1800)
        self._anchor = anchor
        # ToolTip 类型：不抢焦点、不进任务栏，和气泡提示一个待遇
        self.setWindowFlags(Qt.WindowType.ToolTip
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        """自己画药丸底，再把文字交给 QLabel 去画。

        颜色一律取自 Design Token（深色那套），不写死色号：
        菜单栏是深色浮层，提示跟着它走，浅壁纸上也压得住。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = float(theme_mod.RADIUS["md"])
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1.0, self.height() - 1.0,
                            radius, radius)
        fill = QColor(theme_mod.DARK["toast_bg"])
        fill.setAlpha(238)                     # 留一点透，看着不像一块实心贴纸
        painter.fillPath(path, fill)
        painter.setPen(QPen(QColor(theme_mod.DARK["border_strong"]), 1.0))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)              # 文字（颜色来自 QSS）

    def place(self) -> None:  # noqa: D102 - 覆写，见下
        """贴在菜单栏上方居中。

        菜单栏被拖到屏幕顶边时改放到它**下面**——不然提示会跑到屏幕外面，
        用户只看到一闪而过的半条边。
        """
        anchor = self._anchor
        self.adjustSize()
        screen = anchor.screen().availableGeometry()
        x = anchor.x() + (anchor.width() - self.width()) // 2
        y = anchor.y() - self.height() - self.GAP
        if y < screen.top() + 4:
            y = anchor.y() + anchor.height() + self.GAP
        x = max(screen.left() + 4,
                min(x, max(screen.left() + 4,
                           screen.right() - self.width() - 4)))
        # 走 `_settle_position` 而不是直接 `move`：基类进场时会从下方抬 8px，
        # 这里不认 base 的话，那 8px 会把它摆回原位，动画等于没做。
        self._settle_position(x, y)


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

        # ---- 弹簧让位动画（见文件头「手动排序是弹簧动画的」） ----
        # 每个按钮一个 SpringPoint；位置**由弹簧驱动**，不再由布局驱动。
        self._springs: "dict[DockIcon, springs.SpringPoint]" = {}
        # 拖拽开始时冻结下来的槽位坐标 `[(x, y), ...]`（apps_flow 坐标系）。
        # **整个拖拽过程都不变** —— 这是"不抖"的关键，理由见 _update_reorder。
        self._slots: "list[tuple[float, float]]" = []
        self._reorder_button: "DockIcon | None" = None
        # 按下时光标在按钮内部的相对位置，拖动时用它让图标"跟着手"而不是跳到光标中心
        self._grab_offset = QPoint(0, 0)
        # 松手之后是否还在回弹。为真时**不许**重排布局，否则会把动画打断
        self._settling = False
        # 排序改了顺序，但**通知外部要等回弹结束**。理由见 `_commit_reorder`。
        self._pending_quick_notify = False
        self._anim_last = 0.0
        self._anim_timer = QTimer(self)
        # PreciseTimer：默认的 CoarseTimer 在 Windows 上精度只有 ~15ms，
        # 60fps 的节拍会被拖成忽快忽慢，弹簧看起来就"顿顿的"。
        self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._anim_timer.setInterval(theme_mod.DURATION["tick"])   # ≈60fps
        self._anim_timer.timeout.connect(self._on_anim_tick)

        # 布局稳定后校正位置用的短定时器（见 _settle）
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(theme_mod.DURATION["settle"])
        self._settle_timer.timeout.connect(self._settle)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("桌面收纳 · 底部菜单栏")
        self.setWindowIcon(app_icon())
        self.setMouseTracking(True)
        # 从收纳面板把卡片拖过来 = 加为常用启动。
        # 这条路和"长按拖动排序"是**两套机制**：排序走的是
        # `mousePressEvent` / `hold_notify` / `move_notify` 那条鼠标链路，
        # 这里接的是 Qt 自己的拖放（QDrag / dropEvent），互不干扰。
        self.setAcceptDrops(True)
        self._drop_active = False

        self.loader = IconLoader(self, per_tick=3)
        self.loader.ready.connect(self._on_icon_ready)

        self._build_ui()
        # 轻提示（加 / 移出常用启动的反馈）。必须是顶层小窗，见 DockToast。
        self.toast = DockToast(self)
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
        self.main_row.setSpacing(DOCK_GAP)

        # 应用区：会自动换行，加再多也不会把菜单栏撑出屏幕
        self.apps_flow = FlowRow(self.surface, spacing=DOCK_GAP)
        self.main_row.addWidget(self.apps_flow)

        column.addLayout(self.main_row)

        # 兼容旧代码里对 self.control_row / self.row 的引用
        self.control_row = self.main_row
        self.row = self.main_row
        # 控制按钮单独记一份：清空时只能摘掉它们，
        # **不能**顺手把 apps_flow 也从布局里拿掉（那样应用区就整个没了）
        self._control_buttons: "list[QWidget]" = []

    # ------------------------------------------------------------------
    # 底板：纯透明，**什么都不画**
    # ------------------------------------------------------------------
    # 这里刻意没有 `paintEvent`。菜单栏是一层纯透明浮层（`#DockSurface` 是
    # `background: transparent`，见 theme 第 15 节），图标和名字直接浮在桌面上。
    #
    # Phase 4 曾在这里垫过一层很淡的同心圆角矩形当"影子"，想给浅壁纸兜底；
    # 实际观感是"图标底下多了一块半透明板子"，反而回到了要删掉的那种底板。
    # 现在一律不画：要浮着的感觉，靠图标本身和间距就够了。

    def _set_drop_active(self, active: bool) -> None:
        """拖拽悬停时给菜单栏描一圈虚线（动态属性 + 重新 polish，见 theme）。"""
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        for widget in (self.surface, self):
            widget.setProperty("dropActive", active)
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()

    @staticmethod
    def _set_icon_active(button: DockIcon, active: bool) -> None:
        """给"被抓起来排序"的那个图标打/摘 `active` 标记。

        样式走动态属性（`#DockIcon[active="true"]`）而不是内联样式表：
        内联样式表的特异性更高，会把 `#DockIcon:hover` 整条盖掉。
        """
        button.setProperty("active", bool(active))
        try:
            style = button.style()
            style.unpolish(button)
            style.polish(button)
            button.update()
        except RuntimeError:            # 按钮已经被销毁（极端时序），不用管
            pass

    # ------------------------------------------------------------------
    # 轻提示（加 / 移出常用启动的反馈，需求五）
    # ------------------------------------------------------------------
    def show_toast(self, text: str, kind: str = "ok") -> None:
        """在菜单栏上方弹一条自动消失的提示（不用 Dialog）。"""
        toast = getattr(self, "toast", None)
        if toast is None:                    # 极端时序：还没建好
            return
        if self.isHidden():
            return                           # 菜单栏收起来了，弹出来也没人看
        toast.show_message(text, kind)

    def _clear_row(self) -> None:
        """清空应用区与控制按钮。"""
        # 先停弹簧动画：下面这些按钮马上就被销毁了，
        # 定时器里还留着它们的引用就会去 move() 已删除的对象。
        self._abort_reorder_anim()
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
                tooltip=self._quick_tooltip(name, path, exists),
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
        #
        # ⚠️ 拖拽排序期间**绝对不许** relayout：它会把每个按钮按网格重新摆一遍，
        #    正在进行的弹簧动画会瞬间被"位置重置"（就是用户说的"拖到一半跳回去"）。
        if not self._reorder_locked():
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
        # 拖拽 / 回弹期间让路：这个定时器是**异步**的，很容易正好在拖动中途
        # 触发，然后把按钮全部按网格重摆一遍 —— 动画就此被打断。
        if self._reorder_locked():
            return
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
                fallback_text,
                PLACEHOLDER_COLORS.get(fallback_kind, FALLBACK_TILE_COLOR),
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
            # 以前是把原因塞进 `setToolTip`——菜单栏是透明浮层，鼠标得停在
            # 空白处才会弹，基本等于没提示。改成一条轻提示，直接看得见。
            self.show_toast(f"{path.name}：{reason}", "warn")

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
            self.show_toast("✓ 已移出常用启动")
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
                self.add_quick_from_path(Path(path))

    def add_quick_from_path(self, path: Path) -> bool:
        """把一个路径加为常用启动。

        拖放进来的、右键「添加常用软件…」里挑的、批量勾选的那些，
        最终都汇到这一个入口 —— 成功之后统一"写配置 → 通知外面 → 重建
        → 弹提示"，免得三处各写一遍顺序还不一样。
        """
        path = Path(path)
        if self.cfg.is_quick(path):
            self.show_toast("已经在常用启动里了", "warn")
            return False
        if not self.cfg.add_quick(path, self._quick_display_name(path)):
            self.show_toast("加入常用启动失败", "warn")
            return False
        self.quick_changed.emit()
        self.rebuild()
        self.show_toast("✓ 已加入常用启动")
        return True

    # ------------------------------------------------------------------
    # 常用启动：批量添加 / 批量删除
    # ------------------------------------------------------------------
    def _quick_tooltip(self, name: str, path: Path, exists: bool = True) -> str:
        """常用启动图标的 Tooltip：**完整名称** + 完整路径 + 一句能干什么。

        按钮上那行名字是省略过的（`DockIcon.elide` 只留 6 个字），
        长名字必须能在 Tooltip 里看到全的 —— 需求一里明确要求。
        """
        lines = [name, str(path)]
        if not exists:
            lines.append("（已失效：桌面和收纳目录里都找不到它）")
        lines.append("")
        lines.append("单击打开 · 右键更多 · 按住拖动排序")
        return "\n".join(lines)

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
            self.show_toast(f"✓ 已加入常用启动（{added} 项）")

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
            self.show_toast(f"✓ 已移出常用启动（{removed} 项）")

    # ------------------------------------------------------------------
    # 主题 / 尺寸
    # ------------------------------------------------------------------
    def apply_theme(self, dark: bool = True) -> None:
        # Dock 固定深色（macOS 那种观感），不受应用主题影响
        sheet = theme_mod.stylesheet(True)
        self.setStyleSheet(sheet)
        # 轻提示是**独立的顶层小窗**，不会从菜单栏继承样式表，
        # 得单独喂一份，否则 `#ToastOk` 那层淡底和圆角全都不生效。
        toast = getattr(self, "toast", None)
        if toast is not None:
            toast.setStyleSheet(sheet)
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
        # 提示是独立小窗，不跟着菜单栏一起隐藏就会孤零零挂在桌面上
        toast = getattr(self, "toast", None)
        if toast is not None:
            toast.hide_now()
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
        """长按到点：如果按的是常用软件，就进入排序模式。

        进入的这一刻要把"基准"一次性固定下来（要求 9：只动排序相关的代码，
        但基准必须干净）：
          * `_snapshot_slots()` 冻结每个槽位的坐标，整场拖拽都不再变；
          * `_ensure_springs()` 给每个按钮配一个弹簧；
          * 被拖的那个**脱离槽位**（换成"跟手"的硬弹簧），之后只跟光标；
          * 记下光标在按钮内部的相对位置，图标才是"跟着手"而不是跳到光标中心。
        """
        if self._press_icon is not button or self._mode:
            return
        if self._app_index(button) < 0:
            return                      # 「桌面整理」入口不参与排序
        self._mode = "reorder"
        self._reorder_button = button
        button.set_dragging(True)
        button.setDown(True)            # 按住的样子，提示"已经抓起来了"
        self._set_icon_active(button, True)
        button.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._reorder_from = self._app_index(button)
        self._reorder_to = self._reorder_from
        self._settling = False

        self._snapshot_slots()
        self._ensure_springs()
        # 被拖的那个：脱离槽位、贴到它现在实际所在的位置，之后只跟光标走。
        # 刚度拉到 2600 + 临界阻尼 → 紧紧跟手，且**绝不过冲**（过冲就是"抖"）。
        spring = self._springs[button]
        spring.tune(**DRAGGED_SPRING)
        spring.snap(*self._slots[self._reorder_from])
        self._grab_offset = global_pos - button.mapToGlobal(QPoint(0, 0))
        # 抓到最上层：不然它会从相邻图标下面穿过去
        button.raise_()
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
            self._set_icon_active(button, False)
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

    # ------------------------------------------------------------------
    # 弹簧让位动画（核心，见文件头「手动排序是弹簧动画的」）
    #
    # 老实现是"瞬移"：`_apply_reorder_shift()` 里直接 `button.move(x + offset, y)`，
    # 一帧到位；松手再 `rebuild()` 把按钮全销毁重建。三个问题：
    #   1. 让位没有过渡，看着像闪一下；
    #   2. rebuild() 让所有图标消失一帧；
    #   3. 松手前的视觉顺序和松手后的布局是两套东西，对不齐。
    # 现在改成：位置**由弹簧驱动**（springs.py），布局只负责提供"槽位坐标"，
    # 等动画停下来再一次性把控制权交回布局。
    # ------------------------------------------------------------------
    def _reorder_locked(self) -> bool:
        """排序动画期间为 True：这段时间**禁止**重排布局。

        为什么必须有个闸门：`relayout()` 会把每个按钮按网格重新摆一遍。
        拖动过程中一旦被它插一脚，弹簧刚算好的位置就被"位置重置"了 ——
        用户看到的就是"拖到一半跳回去 / 抖一下"。
        有两条路径会走到那儿：
          * `_resize_to_content()`（由 `refit()` 和 `_settle()` 调）；
          * `_settle_timer`（60ms 后异步触发，很容易正好落在拖动中间）。
        """
        return self._mode == "reorder" or self._settling

    def _start_anim(self) -> None:
        """起 60fps 的推进定时器。

        ⚠️ 已经在跑时**绝不能**重置 `_anim_last`。`pointermove` 的频率可能
        比 16ms 高得多（高回报率鼠标可以到 125~1000Hz），每次都重置的话，
        每一拍算出来的 `dt` 只有一两毫秒，弹簧被推进得奇慢 ——
        表现就是"拖起来黏黏的、像慢动作"。时间基准只归定时器自己管。
        """
        if self._anim_timer.isActive():
            return
        self._anim_last = time.monotonic()
        self._anim_timer.start()

    def _abort_reorder_anim(self) -> None:
        """立刻丢掉整场排序动画（清空按钮 / 重建时调）。

        ⚠️ 顺序很重要：**先清弹簧表再让按钮被销毁**。定时器回调里攥着
        按钮引用，晚一步清的话下一拍就会去 `move()` 一个已经被
        `deleteLater()` 的对象。
        """
        self._anim_timer.stop()
        self._springs.clear()
        self._slots = []
        if self._reorder_button is not None:
            # 别把 `active` 高亮留在图标上：重建之后这批按钮就没了，
            # 但"半路被打断"的那条路径里它们还活着（比如只是取消排序）。
            self._set_icon_active(self._reorder_button, False)
        self._reorder_button = None
        self._settling = False
        if self._mode == "reorder":
            self._mode = ""
        if self._pending_quick_notify:
            # 回弹被别的事情打断了（多半是别处触发了一次 rebuild）。
            # 顺序早就写进配置了，但"常用软件变了"这个消息还没发出去；
            # 挪到下一个事件循环再发，免得在别人的 rebuild 调用栈里再套一层。
            self._pending_quick_notify = False
            QTimer.singleShot(0, self.quick_changed.emit)

    def _ensure_springs(self) -> None:
        """保证每个常用项按钮都有一个 SpringPoint，且不多不少。

        每个按钮一个**二维**弹簧（x / y 各自独立积分），位置由它驱动、
        不再由布局驱动 —— 这就是"让位是弹过去的、不是瞬移"的来源。
        """
        live = {id(b) for b in self._app_buttons}
        for button in list(self._springs):
            if id(button) not in live:
                del self._springs[button]
        for button in self._app_buttons:
            point = self._springs.get(button)
            if point is None:
                point = springs.SpringPoint(float(button.x()), float(button.y()))
                self._springs[button] = point
            # 让位的那些统一用略欠阻尼的手感：会轻轻过冲一点点再停住
            point.tune(**REORDER_SPRING)

    def _snapshot_slots(self) -> None:
        """把当前每个常用项按钮的位置**冻结**成"槽位"，整场拖拽都不再变。

        这是"不抖"最关键的一步。让位的目标必须来自一份**不动的**基准：
        如果拿按钮的实时位置去算（旧实现就是 `button.x() + offset`），
        按钮被弹簧推着走 → 下一拍算出的基准也跟着变 → 目标又变 →
        整个界面自己跟自己较劲，表现就是抖动 / 漂移。
        冻结之后 `_slots[i]` 永远是"第 i 个槽位在哪"，与此刻谁坐在上面无关。
        """
        self._slots = [(float(b.x()), float(b.y())) for b in self._app_buttons]

    def _slot_centers(self) -> "list[int]":
        """各槽位中心的**屏幕横坐标**（用冻结的槽位算，不用按钮当前位置）。"""
        origin = self.apps_flow.mapToGlobal(QPoint(0, 0)).x()
        return [origin + int(slot[0]) + self._app_buttons[index].width() // 2
                for index, slot in enumerate(self._slots)]

    def _target_index(self, cursor_x: int) -> int:
        """光标落在哪个槽位 —— 判据是"离哪个槽位中心最近"。

        等价于"跨过相邻图标的中心线就换位"（要求 3）。
        每次都用**光标的绝对位置**重新算，而不是"相对上次挪了几格"：
        快速拖动时一个事件可能跨过好几个图标，增量式算法会漏掉中间状态，
        这里不会有这个问题（要求 8）。
        """
        centers = self._slot_centers()
        if not centers:
            return 0
        return min(range(len(centers)), key=lambda i: abs(cursor_x - centers[i]))

    def _order_after_reorder(self) -> "list[int]":
        """把 `src → dst` 摊成"槽位 → 原下标"的映射。

        语义与 `Config.move_to()` **完全一致**（`items.insert(dst, items.pop(src))`），
        所以视觉顺序和写回配置的顺序不可能对不上。
        `order[p]` = "第 p 个槽位由原来的第几个图标来坐"。
        """
        count = len(self._app_buttons)
        order = list(range(count))
        if 0 <= self._reorder_from < count:
            order.insert(self._reorder_to, order.pop(self._reorder_from))
        return order

    def _settle_targets(self) -> "dict[DockIcon, int]":
        """当前排列下，每个按钮该去哪个槽位（槽位下标）。"""
        order = self._order_after_reorder()
        return {button: order.index(index)
                for index, button in enumerate(self._app_buttons)}

    def _on_anim_tick(self) -> None:
        """每帧推进所有弹簧，并把结果落到控件上（≈60fps）。

        高频 `pointermove` 只负责**改目标**（`move_to`），真正的位置计算
        全挤在这一个定时器里 —— 一次事件风暴不会变成一次布局风暴。
        这就是要求 5 里"用 rAF 优化高频 pointermove"的 Qt 版本。
        """
        now = time.monotonic()
        dt = now - self._anim_last
        self._anim_last = now
        if dt <= 0.0:
            return
        try:
            alive = [(b, p) for b, p in self._springs.items() if b.parent() is not None]
        except RuntimeError:      # 按钮已经被销毁（极端时序），直接收摊
            self._abort_reorder_anim()
            return
        moving = springs.advance([p for _b, p in alive], dt)
        for button, point in alive:
            # 要求 4 的 Qt 版：`transform: translate3d()` → `QWidget.move()`。
            # **只在这一处取整**（唯一的位置来源），避免"取整"和"弹簧"来回打架。
            button.move(int(round(point.x.value)), int(round(point.y.value)))
        if not moving:
            # 全部到位：停表省 CPU。下一次 move_to 会重新起表。
            self._anim_timer.stop()
            if self._settling:
                self._finish_settle()

    def _finish_settle(self) -> None:
        """回弹结束：把控制权交回布局，并**零位移**地收尾。

        交接顺序是精心排过的：
          1. 先把顺序固定进 `apps_flow`（只改 `_items`，不销毁控件）；
          2. 再 `relayout()` 一次，让布局按新顺序摆 —— 因为所有图标此刻
             正好停在各自的槽位上，这一步算出来的坐标跟当前坐标**一样**，
             所以肉眼看不到任何跳动；
          3. 把弹簧的值 `snap()` 到布局的真实坐标上，然后整张弹簧表丢掉。
             这样万一有 1px 的取整误差，也已经被"对齐"掉了，不会在
             下一次 relayout 时突然抖一下；
          4. **最后**才发 `quick_changed`。它会让 `tray_app` 调 `rebuild()`，
             把图标全销毁重建 —— 但那会儿顺序和位置已经和配置一模一样，
             重建只是换了批控件、落在同一批坐标上，看不出来。
             反过来先发就会把正在回弹的按钮当场删掉（见 `_commit_reorder`）。
        """
        self._anim_timer.stop()
        self._settling = False
        self._reorder_button = None
        # 顺序真的变了才重排；没变的话 relayout 纯属白干（还可能引入误差）
        if self.apps_flow.reorder([self.desktop_btn] + list(self._app_buttons)):
            self.apps_flow.relayout(self._reorder_span_width())
            layout = self.apps_flow.layout()
            if layout is not None:
                layout.activate()
        for button, point in self._springs.items():
            point.snap(float(button.x()), float(button.y()))
        self._springs.clear()
        self._slots = []
        self._resize_to_content()
        self.reposition()
        if self._pending_quick_notify:
            self._pending_quick_notify = False
            self.quick_changed.emit()

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

    def _dragged_target(self, global_pos: QPoint) -> QPoint:
        """被拖图标该去哪（`apps_flow` 坐标系）。

        直接取"光标位置 − 抓取偏移"，图标就是**跟着手**走，而不是跳到光标中心。
        最后夹在应用区矩形内：Qt 的子控件一律被父控件裁剪，放任它跑出去
        就会缺一角（和之前修的"图标显示不完整"是同一类毛病）。
        """
        button = self._reorder_button
        local = self.apps_flow.mapFromGlobal(global_pos - self._grab_offset)
        if button is None:
            return local
        area = self.apps_flow.rect()
        max_x = max(area.left(), area.right() + 1 - button.width())
        max_y = max(area.top(), area.bottom() + 1 - button.height())
        return QPoint(min(max(local.x(), area.left()), max_x),
                      min(max(local.y(), area.top()), max_y))

    def _update_reorder(self, global_pos: QPoint) -> None:
        """按光标位置**实时**算目标槽位，并让其他图标弹开让位。

        需求 2：「长按拖动图标插入到某个位置时，后面的软件会自动后移」。

        和旧实现的三点区别：
          * 目标槽位用**冻结的槽位中心**判（旧实现用的是按钮实时中心，
            按钮一动中心就动，判据自己跟自己较劲）；
          * 让位只改弹簧目标，真实位置由 60fps 的 `_on_anim_tick()` 推 ——
            平滑、有弹性，不再是"一帧瞬移"；
          * 被拖的那个和让位的那些用**两套弹簧参数**，动画互相独立（要求 6）。
        """
        buttons = self._app_buttons
        if len(buttons) < 2 or not self._slots:
            self.hide_drop_line()
            return
        # 要求 2：targetIndex 在 drag move 阶段就实时算出来，不等 mouseup
        self._reorder_to = self._target_index(global_pos.x())
        self._apply_reorder_shift()
        # 被拖的那个：目标每次跟着光标改，但**不重置速度**，所以运动是连续的
        dragged = self._reorder_button
        if dragged is not None:
            point = self._springs.get(dragged)
            if point is not None:
                target = self._dragged_target(global_pos)
                point.move_to(float(target.x()), float(target.y()))
        self._start_anim()
        self._update_drop_line()

    def _update_drop_line(self) -> None:
        """把插入指示线画到"松手后它会落到哪"。

        位置取**冻结的槽位**而不是按钮当前位置：按钮正被弹簧推着走，
        拿它当基准的话这根线会跟着晃。
        """
        target = self._reorder_to
        if target == self._reorder_from or not self._slots \
                or target >= len(self._slots):
            self.hide_drop_line()
            return
        line = self._drop_line_widget()
        origin = self.apps_flow.mapTo(self.surface, QPoint(0, 0))
        slot = self._slots[target]
        button = self._app_buttons[target]
        # 往左移就画在目标槽的左边缘，往右移就画在右边缘
        offset = -4 if target < self._reorder_from else button.width() + 1
        line.setGeometry(origin.x() + int(slot[0]) + offset,
                         origin.y() + int(slot[1]) + 3,
                         4, max(8, button.height() - 6))
        line.raise_()
        line.show()

    def _apply_reorder_shift(self) -> None:
        """把"让位"变成弹簧目标（纯视觉，不改配置）。

        做法是"预留空位"：按 `_order_after_reorder()` 算出最终排列，
        每个让位的图标把弹簧目标改成**它在新排列里该坐的槽位**，
        于是它自己弹过去 —— 视觉上就是"别的图标主动向两边让开"。

        目标位置是**绝对坐标**（不是 `x + offset` 那种累加），所以同一个
        状态重复调用多少次结果都一样，高频 `pointermove` 下不会漂移，
        也不会因为"一次事件跨过好几个图标"而错位（要求 8）。
        """
        if not self._slots:
            return
        for button, slot_index in self._settle_targets().items():
            if button is self._reorder_button:
                continue                    # 被拖的自己跟光标走
            if slot_index >= len(self._slots):
                continue
            point = self._springs.get(button)
            if point is None:
                continue
            slot = self._slots[slot_index]
            point.move_to(slot[0], slot[1])

    def _reorder_span_width(self) -> int:
        """给 `relayout` 用的可用宽度（和 `_resize_to_content` 里同一套算法）。"""
        return max(160, self._max_width() - (MIN_MARGIN * 2) - 20
                   - self._controls_width())

    def _commit_reorder(self) -> None:
        """松手：把顺序写回配置，然后让所有图标**弹簧回最终槽位**。

        需求 2 的后半句：「如果拖到桌面就保持原样不进行排序」。
        所以松手位置**在菜单栏之外**时直接放弃本次排序，顺序一点不动
        （但被拖的图标照样弹回去，不会僵在半路上）。

        ⚠️ 这里**不再 `rebuild()`**：重建会把所有图标销毁重来，视觉上
        消失一帧，回弹动画也就白做了。改成只把顺序同步过来，
        等回弹结束由 `_finish_settle()` 一次性交接给布局。

        ⚠️⚠️ `quick_changed` **也必须等回弹结束再发**。它不是个"通知一下"
        那么简单：`tray_app._on_quick_changed()` 收到之后会调 `dock.rebuild()`，
        而 `rebuild()` 会 `deleteLater()` 掉所有图标 —— 在这一刻发出去，
        我们正在动画的那些按钮当场被销毁，`_app_buttons` 也会被换成
        一批"已销毁对象"，整个 Dock 直接废掉。
        所以这里只挂一个待发标记，交给 `_finish_settle()` 收尾时再发；
        那时顺序和位置都已经和配置一致，重建出来的按钮落在同样的地方，
        肉眼看不出来（见 `_finish_settle` 的注释）。
        """
        inside = (self.rect().contains(self.mapFromGlobal(self._release_pos))
                  if self._release_pos is not None else True)
        self.hide_drop_line()
        buttons = list(self._app_buttons)
        count = len(buttons)
        src, dst = self._reorder_from, self._reorder_to
        identity = list(range(count))
        order = identity
        if inside and src != dst and 0 <= src < count and 0 <= dst < count:
            candidate = list(identity)
            candidate.insert(dst, candidate.pop(src))
            if self.cfg.move_to(src, dst):
                order = candidate
        # 每个按钮的最终槽位 —— 必须用**旧下标**算，下面就会打乱 _app_buttons
        final_slot = {button: order.index(index)
                      for index, button in enumerate(buttons)}
        if order != identity:
            # 逻辑顺序跟着配置走，之后 `_app_index()` 之类才不会指错
            self._app_buttons = [buttons[index] for index in order]
            self._pending_quick_notify = True
        self._reorder_from = self._reorder_to = 0
        if self._slots:
            # 所有图标（含被拖的那个）一起朝最终槽位弹过去。
            # 被拖的那个从"跟手"的硬弹簧换回普通手感，回弹才不会像被弹弓抽回去。
            for button in buttons:
                point = self._springs.get(button)
                if point is None:
                    continue
                slot = self._slots[final_slot[button]]
                point.tune(**REORDER_SPRING)
                point.move_to(slot[0], slot[1])
        # 交给回弹流程：动画停下来时 `_on_anim_tick()` 会调 `_finish_settle()`
        self._settling = True
        self._start_anim()

    # ------------------------------------------------------------------
    # 拖入添加：从收纳面板把条目拖到菜单栏上（需求四）
    #
    # 这条路和"长按拖动排序"**互不干扰**：排序走的是 `mousePressEvent` /
    # `hold_notify` / `move_notify` 那条鼠标链路（图标跟着光标走、别的图标让位），
    # 这里接的是 Qt 自己的拖放（QDrag / dropEvent）。两套机制各自独立，
    # 所以给菜单栏加"能收拖放"不需要动排序系统一个字节。
    # ------------------------------------------------------------------
    def _payload_from(self, event) -> str:
        """从拖放事件里取出条目路径（不是我们自己的包就返回空串）。"""
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
            self._set_drop_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._payload_from(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        raw = self._payload_from(event)
        self._set_drop_active(False)
        if not raw:
            event.ignore()
            return
        event.acceptProposedAction()
        try:
            path = Path(raw)
        except (TypeError, ValueError):
            return
        self.add_quick_from_path(path)

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
