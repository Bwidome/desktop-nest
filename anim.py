#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微交互动画（Phase 6）
=====================
原则是「动画服务于交互，而不是装饰」，所以这里**只有三个动作**：

| 动作 | 用在哪 | 时长 |
| --- | --- | --- |
| `HoverVeil` | 悬停时的底色过渡（网格卡片 / 状态条明细行） | `DURATION["hover"]` = 160ms |
| `fade_in()` | 翻页时内容淡入（**不动位置**） | `DURATION["page"]` = 220ms |
| `fade_scale_window()` | 我们自己的对话框进场 | `DURATION["dialog"]` = 180ms |

为什么颜色过渡要盖一层控件，而不是直接动 QSS：QSS **没有** `transition`，
Qt 控件也**没有** `transform`。想在 160ms 里把底色从透明渐变到 hover 色，
只有两条路——

1. 每帧 `setStyleSheet()`：每次都让 Qt 重新匹配选择器、重排样式、重绘子树，
   正是需求九要避免的"重复 reflow / 重复 repaint"；
2. 盖一层**自绘的透明控件**，每帧只改它的 alpha 再 `update()`：只重绘这一层，
   不碰布局、不碰样式表。

这里用第 2 条。`HoverVeil` 必须**画在内容下面**：它 `lower()` 到兄弟控件的
最底层，父控件先画自己的底、再画这层、最后画文字 / 按钮——所以底色过渡
不会把字染灰（这一点用 `QGraphicsOpacityEffect` 做整控件淡入是做不到的）。

缓动只有一条：`theme.EASING` 那串 cubic-bezier。`ease_curve()` 把同一组
控制点喂给 Qt 的 `QEasingCurve.BezierSpline`，所以"代码里的曲线"和
"设计稿上的曲线"是同一个东西，不会各写各的。
"""
from __future__ import annotations

import re

import theme as theme_mod
from qt_compat import (
    QColor, QEasingCurve, QEvent, QGraphicsOpacityEffect, QPainter,
    QPainterPath, QPointF, QRect, Qt, QVariantAnimation, QWidget,
)

#: 取不到 token 时的兜底时长（毫秒）
_FALLBACK = 160
#: CSS 的 `rgba(255, 255, 255, 0.10)` / `rgb(30, 32, 38)`
_RGBA_RE = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*"
    r"(?:,\s*([\d.]+)\s*)?\)", re.IGNORECASE)


def parse_color(value) -> "QColor":
    """把 Design Token 里的颜色字符串变成 `QColor`。

    token 有两种写法：`#RRGGBB`（light / dark 那两套）和 CSS 的
    `rgba(255, 255, 255, 0.10)`（**玻璃那套全是这种**）。
    `QColor` **不认后一种**——构造出来是 invalid，画出来是纯黑。
    Phase 6 第一版就栽在这上面：卡片悬停时直接变成一块黑底。
    """
    if isinstance(value, QColor):
        return QColor(value)
    text = str(value or "").strip()
    match = _RGBA_RE.search(text)
    if match:
        channels = []
        for index in (1, 2, 3):
            channels.append(max(0, min(255, int(round(float(match.group(index)))))))
        alpha = match.group(4)
        if alpha is None:
            a = 255
        else:
            raw = float(alpha)
            a = int(round(raw * 255)) if raw <= 1.0 else int(round(raw))
        return QColor(channels[0], channels[1], channels[2],
                      max(0, min(255, a)))
    color = QColor(text)
    return color


# ----------------------------------------------------------------------
# 时长 / 缓动
# ----------------------------------------------------------------------
def ms(name: str, fallback: int = _FALLBACK) -> int:
    """取 `theme.DURATION` 里的时长（毫秒）。"""
    try:
        return int(theme_mod.DURATION.get(name, fallback))
    except Exception:
        return int(fallback)


def ease_curve() -> "QEasingCurve":
    """把 `theme.EASING` 那条 cubic-bezier 原样搬到 Qt 里。

    CSS 的 `cubic-bezier(x1, y1, x2, y2)` 就是一条从 (0,0) 到 (1,1) 的三次
    贝塞尔，两个控制点就是那四个数——正好对上 Qt 的 `addCubicBezierSegment`。
    （`setCubicBezierSpline()` 在 Qt 6 里**没有**这个绑定，别照抄文档。）

    解析不出来就退回 `OutCubic`：两者观感几乎一样，但宁可退，不要抛。
    """
    try:
        numbers = [float(x) for x in
                   re.findall(r"-?\d+(?:\.\d+)?", str(theme_mod.EASING))]
    except Exception:
        numbers = []
    if len(numbers) == 4:
        try:
            curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
            curve.addCubicBezierSegment(QPointF(numbers[0], numbers[1]),
                                        QPointF(numbers[2], numbers[3]),
                                        QPointF(1.0, 1.0))
            return curve
        except Exception:
            pass
    return QEasingCurve(QEasingCurve.Type.OutCubic)


# ----------------------------------------------------------------------
# 悬停底色过渡
# ----------------------------------------------------------------------
class HoverVeil(QWidget):
    """盖在"父控件背景"之上、"内容"之下的悬停底色。

    用法（父控件必须自己管好几何，见 `_fit`）：

    >>> self.veil = HoverVeil(self, palette["hover"], radius=theme.RADIUS["lg"])
    >>> def enterEvent(self, e):  self.veil.enter();  super().enterEvent(e)
    >>> def leaveEvent(self, e):  self.veil.leave();  super().leaveEvent(e)

    父控件改尺寸时它自己跟上（事件过滤器），不需要父控件写 `resizeEvent`。
    """

    #: 按下时的加深倍数（需求三：press 用亮度变化，不做缩放）
    PRESS_GAIN = 1.35

    def __init__(self, parent: QWidget, color, *, radius: int = 0,
                 press_gain: float = PRESS_GAIN):
        super().__init__(parent)
        # 提示层不该抢鼠标：它盖在内容上面一格，抢了鼠标父控件就收不到 hover
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._color = parse_color(color)
        if not self._color.isValid():
            # 颜色写错了也别让卡片变黑：退回"一层很淡的白"
            self._color = QColor(255, 255, 255, 30)
        self._radius = float(max(0, int(radius)))
        self._gain = float(press_gain)
        self._t = 0.0
        self._pressed = False
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(ms("hover"))
        self._anim.setEasingCurve(ease_curve())
        self._anim.valueChanged.connect(self._on_value)
        self._fit(parent)
        # 画在所有兄弟控件**下面**：父控件先画底、再画这层、最后画字
        self.lower()
        # ⚠️ 父控件**已经显示**的时候新建的子控件不会自己出现，必须显式 show()。
        # 状态条里的明细行就是这种情况（条已经显示，行是后来才加的），
        # 少这一句的话悬停层永远不画 —— 看着像"这个控件没有 hover"。
        self.show()
        parent.installEventFilter(self)

    # ---- 事件 --------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._fit(obj)
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._t <= 0.001:
            return                       # 完全透明时连画笔都不用起
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        alpha = color.alpha() * self._t
        if self._pressed:
            alpha *= self._gain
        color.setAlpha(max(0, min(255, int(round(alpha)))))
        rect = self.rect().adjusted(0, 0, -1, -1)
        if self._radius > 0:
            path = QPainterPath()
            path.addRoundedRect(float(rect.x()), float(rect.y()),
                                float(rect.width()), float(rect.height()),
                                self._radius, self._radius)
            painter.fillPath(path, color)
        else:
            painter.fillRect(rect, color)
        painter.end()

    # ---- 对外 --------------------------------------------------------
    def enter(self) -> None:
        """悬停开始：160ms 淡到目标底色。"""
        self._to(1.0)

    def leave(self) -> None:
        """悬停结束：同样 160ms 淡回透明（不要"啪"一下消失）。"""
        self._pressed = False
        self._to(0.0)

    def press(self) -> None:
        """按下：立刻加深一点（亮度变化，不缩放、不加时长）。"""
        if self._pressed:
            return
        self._pressed = True
        self.update()

    def release(self) -> None:
        if not self._pressed:
            return
        self._pressed = False
        self.update()

    def snap(self, value: float) -> None:
        """直接跳到某个值（不走动画）——切页 / 重建时用，避免残留半透明。"""
        self._anim.stop()
        self._t = max(0.0, min(1.0, float(value)))
        self._pressed = False
        self.update()

    @property
    def value(self) -> float:
        """当前过渡值（0 = 透明，1 = 目标底色）。自检要看这个。"""
        return self._t

    # ---- 内部 --------------------------------------------------------
    def _to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(float(self._t))
        self._anim.setEndValue(float(target))
        self._anim.start()

    def _on_value(self, value) -> None:
        self._t = float(value)
        self.update()

    def _fit(self, parent: QWidget) -> None:
        self.setGeometry(parent.rect())


# ----------------------------------------------------------------------
# 出现类动画
# ----------------------------------------------------------------------
def fade_in(widget: QWidget, *, duration: int = 0, start: float = 0.0,
            rise: int = 0) -> "QVariantAnimation | None":
    """让一个**子控件**淡入（可带一点点上抬）。

    需求四：面板 / 标签切换 200~250ms，**不要出现明显位移**。所以 `rise`
    默认 0——翻页只淡入，位置一动不动。`rise` 只给"从下方浮上来"的提示用，
    而且必须是很小的值（8px 量级）。

    动画结束后会把 `QGraphicsOpacityEffect` 摘掉：留着的话，这个控件之后
    每一帧都要先渲染到离屏 pixmap 再合成，滚动时就白花性能（需求九）。
    """
    if widget is None:
        return None
    previous = getattr(widget, "_fade_anim", None)
    if previous is not None:
        try:
            previous.stop()
        except Exception:
            pass
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    effect.setOpacity(float(start))
    anim = QVariantAnimation(widget)
    anim.setStartValue(float(start))
    anim.setEndValue(1.0)
    anim.setDuration(int(duration or ms("page", 220)))
    anim.setEasingCurve(ease_curve())
    base = widget.pos()

    def on_value(value) -> None:
        effect.setOpacity(float(value))
        if rise:
            widget.move(base.x(),
                        base.y() + int(round((1.0 - float(value)) * rise)))

    def on_done() -> None:
        if rise:
            widget.move(base)
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass

    anim.valueChanged.connect(on_value)
    anim.finished.connect(on_done)
    widget._fade_anim = anim            # noqa: SLF001 - 防止被回收
    anim.start()
    return anim


def fade_scale_window(window, *, duration: int = 0,
                      from_scale: float = 0.96) -> "QVariantAnimation | None":
    """顶层窗口进场：淡入 + 从 0.96 轻轻放到 1.0（需求六）。

    只给**我们自己的** `QDialog` 用。系统对话框（`QMessageBox`）是平台自己
    画的窗口，动它反而会闪；而且它本来就居中弹出，不存在"从屏幕底部飞进来"。

    起点不是 0 而是 0.15：万一动画没跑起来（被系统挂起 / 窗口提前关闭），
    用户看到的也是一块正常的对话框，而不是一个隐形的窗。
    """
    if window is None or not window.isWindow():
        return None
    final = window.geometry()
    if final.width() <= 0 or final.height() <= 0:
        return None
    width = max(1, int(round(final.width() * float(from_scale))))
    height = max(1, int(round(final.height() * float(from_scale))))
    small = QRect(final.center().x() - width // 2,
                  final.center().y() - height // 2, width, height)
    anim = QVariantAnimation(window)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(int(duration or ms("dialog", 180)))
    anim.setEasingCurve(ease_curve())
    window.setWindowOpacity(0.15)
    window.setGeometry(small)

    def on_value(value) -> None:
        t = float(value)
        window.setWindowOpacity(0.15 + 0.85 * t)
        window.setGeometry(
            int(round(small.x() + (final.x() - small.x()) * t)),
            int(round(small.y() + (final.y() - small.y()) * t)),
            int(round(small.width() + (final.width() - small.width()) * t)),
            int(round(small.height() + (final.height() - small.height()) * t)))

    def on_done() -> None:
        window.setWindowOpacity(1.0)
        window.setGeometry(final)

    anim.valueChanged.connect(on_value)
    anim.finished.connect(on_done)
    window._intro_anim = anim           # noqa: SLF001 - 防止被回收
    anim.start()
    return anim
