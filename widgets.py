#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共用界面零件
============
* IconLoader —— 分片取图标，界面不卡
* 图标占位色 —— 取不到真实图标时用的圆角色块
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap, QRect, Qt,
    QTimer, QWidget, Signal,
)

import engine
import icons
import theme

# 每种类型没有真实图标时的占位色
PLACEHOLDER_COLORS = {
    "shortcut": "#4F6BED", "program": "#5B6B8C", "image": "#E09A3E",
    "video": "#8B5CF6", "audio": "#E0559A", "document": "#4F6BED",
    "sheet": "#12A150", "slide": "#D9634F", "archive": "#0EA5E9",
    "code": "#14B8A6", "font": "#A855F7", "folder": "#E3B341", "other": "#94A3B8",
    "desktop": "#4F6BED",
}

# 品牌主色统一从主题取，避免同一串色值散落在多个文件里各写一遍
BRAND_ACCENT = theme.LIGHT["accent"]


def letter_pixmap(text: str, color: str, size: int) -> QPixmap:
    """圈一个圆角色块 + 首字，作为图标的兜底。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    radius = max(1.0, size * 0.26)
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.fillPath(path, QColor(color))
    painter.setPen(QColor("#FFFFFF"))
    font = QFont()
    font.setPixelSize(max(1, int(size * 0.46)))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size),
                     int(Qt.AlignmentFlag.AlignCenter),
                     (text or "?")[:1].upper())
    painter.end()
    return pixmap


def raw_to_qicon(raw) -> "QIcon | None":
    """把 icons.RawIcon 的原始像素转成 QIcon。

    关键点：`raw.bgra` 是 bytes 对象，**生命周期必须绑到 QImage 上**。
    QImage 不会拷贝这块内存，如果 bytes 被回收，后面 `pixmap()` 取到的就是
    脏数据。这里显式把 bytes 挂成 QImage 的属性，再用 copy() 拿到独立副本。
    """
    if raw is None or not getattr(raw, "is_valid", lambda: False)():
        return None
    width, height = raw.width, raw.height
    data = raw.bgra
    image = QImage(data, width, height, width * 4, QImage.Format.Format_ARGB32)
    if image.isNull():
        return None
    image._raw_ref = data                     # 防止 bytes 被提前回收
    return QIcon(QPixmap.fromImage(image.copy()))


def app_icon_pixmap(size: int = 256) -> QPixmap:
    """画程序自己的图标（抽屉造型），当作窗口图标和托盘图标。

    有个实体图标很重要：否则窗口左上角、任务栏缩略图那里都是一片空白，
    看起来像没写完的程序。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    radius = size * 0.22
    path.addRoundedRect(0.5, 0.5, size - 1, size - 1, radius, radius)
    painter.fillPath(path, QColor(BRAND_ACCENT))
    painter.setPen(Qt.PenStyle.NoPen)
    unit = size / 16.0
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(int(3.5 * unit), int(4 * unit),
                            int(9 * unit), int(2.6 * unit), unit, unit)
    painter.setBrush(QColor("#D8E0FF"))
    painter.drawRoundedRect(int(3.5 * unit), int(7.6 * unit),
                            int(9 * unit), int(2.6 * unit), unit, unit)
    painter.setBrush(QColor("#FFFFFF"))
    arrow = QPainterPath()
    arrow.moveTo(size / 2, int(13.4 * unit))
    arrow.lineTo(int(5 * unit), int(10.6 * unit))
    arrow.lineTo(int(11 * unit), int(10.6 * unit))
    arrow.closeSubpath()
    painter.fillPath(arrow, QColor("#FFFFFF"))
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """多尺寸的程序图标（小到 16px 都清晰）。托盘图标也直接复用它。"""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(size))
    return icon


def pixmap_for(icon: "QIcon", logical_size: int, widget=None) -> "QPixmap":
    """按控件的实际设备像素比取图标，避免高分屏上发虚。

    直接 `icon.pixmap(48, 48)` 在 150% 缩放下会被拉大导致模糊；
    这里显式按 devicePixelRatio 请求物理像素，再由 Qt 缩回逻辑尺寸。
    """
    ratio = 1.0
    try:
        if widget is not None:
            window = widget.window()
            handle = window.windowHandle() if window is not None else None
            if handle is not None:
                ratio = float(handle.devicePixelRatio())
        if ratio <= 0:
            ratio = 1.0
    except Exception:
        ratio = 1.0
    physical = max(1, int(round(logical_size * ratio)))
    pixmap = icon.pixmap(physical, physical)
    if pixmap.isNull():
        pixmap = icon.pixmap(logical_size, logical_size)
    try:
        pixmap.setDevicePixelRatio(ratio)
    except Exception:
        pass
    return pixmap


def icon_hint_for(path: Path, kind: str = "") -> "Path | None":
    """给 `.lnk` 找出它指向的程序，作为取图标的 hint。

    这一步很关键：只把 `.lnk` 丢给 Shell，拿到的往往不理想；
    把**目标 exe** 一起给它，才能取到清晰的程序图标。
    解析不出来（指向商店应用、或指向虚拟位置）就返回 None，
    调用方会退回类型图标，不会报错。
    """
    try:
        if Path(path).suffix.lower() != ".lnk":
            return None
        return engine.resolve_shortcut_target(Path(path))
    except Exception:
        return None


class IconLoader(QWidget):
    """分片取图标：每个 tick 只处理几个，界面始终不卡。

    没有另开线程是有意的——图标提取要调用 Windows Shell，而 Qt 的图片对象
    在主线程里创建最省心。用定时器切片处理，几百个文件也不会掉帧。

    **已取到的图标会一直留在内存里**（`_cache`），翻页回来时直接复用。
    这一点很关键：如果翻页把缓存也丢掉，返回上一页就得重新去 Shell 取一遍，
    一旦那次取失败（Shell 偶发失败、文件被占用等），图标就会变成空白。
    """

    ready = Signal(str, object)          # (key, QIcon)

    def __init__(self, parent=None, interval: int = 50, per_tick: int = 6):
        super().__init__(parent)
        self._per_tick = per_tick
        self._timer = QTimer(self)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._drain)
        self._cache: "dict[str, QIcon]" = {}
        self._queue: "list[tuple[str, Path, Path | None, int, str]]" = []

    def cached(self, key: str) -> "QIcon | None":
        return self._cache.get(key)

    def request(self, key: str, path: Path, exe_hint: "Path | None", size: int,
                fallback_text: str = "") -> None:
        if key in self._cache:
            return
        for existing in self._queue:
            if existing[0] == key:
                return
        self._queue.append((key, path, exe_hint, size, fallback_text))
        if not self._timer.isActive():
            self._timer.start()

    def _drain(self) -> None:
        for _ in range(self._per_tick):
            if not self._queue:
                self._timer.stop()
                return
            key, path, hint, size, fallback = self._queue.pop(0)
            if key in self._cache:
                continue
            icon = None
            raw = icons.get_icon(path, size, exe_hint=hint)
            if raw is not None and getattr(raw, "is_valid", lambda: False)():
                icon = raw_to_qicon(raw)
            if icon is None:
                # 真图标取不到才用占位（圆角色块 + 首字）
                color = PLACEHOLDER_COLORS.get("other", "#94A3B8")
                icon = QIcon(letter_pixmap(fallback or Path(key).name, color, size))
            self._cache[key] = icon
            self.ready.emit(key, icon)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    def discard_pending(self, keep=None) -> None:
        """丢掉**还没处理**的排队请求，保留已取到的图标。

        翻页 / 切换筛选时用这个：正准备取的那批已经不需要了，
        但已经取到的图标必须留着，否则回到上一页就会一片空白。

        keep：可选的断言，返回 True 的请求会被保留。面板翻页时用它保住
        "常用启动"那一排的请求（它们的 key 以 ``app:`` 开头），
        否则翻页会把还没取到图标的常用项请求一起丢掉，那排就永远是占位色块。
        """
        if keep is None:
            self._queue.clear()
        else:
            self._queue = [item for item in self._queue if keep(item[0])]
        if not self._queue:
            self._timer.stop()

    def clear(self) -> None:
        """连内存缓存一起清掉（只在明确要释放内存时用）。"""
        self.discard_pending()
        self._cache.clear()

    def cached_count(self) -> int:
        return len(self._cache)
