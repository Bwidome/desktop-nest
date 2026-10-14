#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共用界面零件
============
* IconLoader —— 分片取图标，界面不卡
* 图标占位色 —— 取不到真实图标时用的圆角色块
* GlassCardMixin —— 「悬浮磨砂玻璃卡片」外观（主面板 / 收纳面板共用）
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    QCheckBox, QColor, QDialog, QFont, QHBoxLayout, QIcon, QImage, QLabel,
    QPainter, QPainterPath, QPalette, QPixmap, QPushButton, QRect,
    QScrollArea, Qt, QTimer, QVBoxLayout, QWidget, Signal,
)

import acrylic
import config
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


class GlassCardMixin:
    """「悬浮磨砂玻璃卡片」外观：主面板 / 收纳面板共用。

    做三件事：
    1. 把窗口调色板换成深色——QSS 只覆盖写到的控件，没写到的（QTabBar 的空白、
       表头间隙、滚动条槽…）会回落到**系统调色板**，那是浅色的，在深色玻璃上
       就是一块刺眼的白；
    2. 窗口第一次显示时调 `acrylic.enable_blur` 开 DWM 磨砂（真正把背后的桌面
       模糊掉这件事 Qt 做不到，只能交给 DWM）；
    3. 尺寸变化时按圆角重新裁一次窗口区域——`SetWindowRgn` 不跟着窗口缩放，
       不重裁的话模糊会糊到圆角外面，露出方角。

    子类的约定（见 `panel.MainPanel` / `desktop_browser.DesktopBrowser`）：
    * 顶层窗口设 `WA_TranslucentBackground`——窗口自身透明，深色只画在卡片子控件上
      （**不能**给顶层窗口设 QSS 背景，那会把磨砂整块盖住）；
    * `__init__` 里调一次 `self._glass_init()`；
    * 覆盖 `_glass_card_sel`（卡片子控件的 objectName 选择器），磨砂不可用时
      用它把底色加浓一档；
    * 需要 `self.dark`（明暗主题标志）——收纳面板固定深色玻璃，传 True 即可。
    """

    # 子类覆盖：磨砂不可用时加浓底色的选择器
    _glass_card_sel = "#MainCard"
    # 子类覆盖：日志里对这张卡片的称呼
    _glass_log_name = "玻璃卡片"

    def _glass_init(self) -> None:
        """初始化磨砂状态。子类 `__init__` 里调一次。"""
        self._glass_mode = ""
        self._glass_ready = False

    # ------------------------------------------------------------------
    # 调色板
    # ------------------------------------------------------------------
    def _apply_glass_palette(self) -> None:
        """把窗口调色板换成深色，兜住 QSS 没写到的控件。"""
        roles = theme.glass_palette_roles()
        pal = self.palette()
        mapping = {
            QPalette.ColorRole.Window: roles["window"],
            QPalette.ColorRole.WindowText: roles["text"],
            QPalette.ColorRole.Base: roles["base"],
            QPalette.ColorRole.AlternateBase: roles["alternate"],
            QPalette.ColorRole.Text: roles["text"],
            QPalette.ColorRole.Button: roles["button"],
            QPalette.ColorRole.ButtonText: roles["text"],
            QPalette.ColorRole.ToolTipBase: roles["button"],
            QPalette.ColorRole.ToolTipText: roles["text"],
            QPalette.ColorRole.Highlight: roles["highlight"],
            QPalette.ColorRole.HighlightedText: roles["highlight_text"],
            QPalette.ColorRole.PlaceholderText: roles["sub"],
        }
        for role, value in mapping.items():
            pal.setColor(role, QColor(value))
        self.setPalette(pal)

    # ------------------------------------------------------------------
    # 样式表
    # ------------------------------------------------------------------
    def _restyle(self) -> None:
        """套用玻璃卡片样式。

        拿不到磨砂（老系统 / 被策略挡住）时把卡片底色加浓一档——
        没有模糊还那么透，文字会看不清。
        """
        sheet = theme.stylesheet(bool(getattr(self, "dark", False)), glass=True)
        if not self._glass_mode:
            sheet += f"\n{self._glass_card_sel} {{ {theme.GLASS_FALLBACK} }}\n"
        self.setStyleSheet(sheet)

    # ------------------------------------------------------------------
    # DWM 磨砂 + 圆角裁剪
    # ------------------------------------------------------------------
    def _ensure_glass(self) -> None:
        """开磨砂（只在第一次显示时做一次）。"""
        if self._glass_ready:
            return
        self._glass_ready = True
        self._glass_mode = acrylic.enable_blur(
            self, radius=theme.GLASS_RADIUS,
            tint=theme.GLASS_TINT, opacity=theme.GLASS_TINT_ALPHA)
        config.log(f"{self._glass_log_name}磨砂："
                   f"{self._glass_mode or '不可用，退回纯半透明'}"
                   f"（{acrylic.describe()}）")
        self._restyle()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_glass()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # SetWindowRgn 不会跟着窗口缩放，尺寸一变就得重新裁一次
        if self._glass_mode:
            acrylic.apply_round_region(self, theme.GLASS_RADIUS)


class MultiPickDialog(QDialog):
    """带**复选框**的多选列表弹窗（批量加 / 批量删常用软件共用）。

    需求原话是「按下从下面列表中选择按钮后，下方软件列表增加复选框，
    支持多选批量添加」——所以这里不走"按住 Ctrl 点选"那套，而是每行一个
    复选框，点一下就是勾选/取消，多选零门槛。

    设计要点：
    * 每行一个 `QCheckBox`，直接摆进滚动区，而不是用 QListWidget 的
      `setCheckState`——后者在部分主题下复选框会被样式表吃掉，看不见。
    * 顶部有「全选 / 全不选」，底部实时显示"已选 N 项"并据此启用确认按钮。
    * `chosen` 返回被勾选条目的 `key` 列表；取消返回空列表。
    """

    def __init__(self, title: str, hint: str, entries: "list[tuple[str, str]]",
                 confirm_text: str = "确定", parent=None):
        """entries 是 `[(key, 显示文本), ...]`。"""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 560)
        self._boxes: "list[tuple[str, QCheckBox]]" = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QLabel(hint)
        head.setWordWrap(True)
        root.addWidget(head)

        # ---- 全选 / 全不选 ----
        tools = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        tools.addWidget(btn_all)
        tools.addWidget(btn_none)
        tools.addStretch(1)
        self.count_label = QLabel("")
        tools.addWidget(self.count_label)
        root.addLayout(tools)

        # ---- 复选框列表（滚动）----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(2)
        for key, text in entries:
            check = QCheckBox(text)
            check.stateChanged.connect(lambda _s: self._update_count())
            box.addWidget(check)
            self._boxes.append((key, check))
        if not entries:
            empty = QLabel("没有可选的条目。")
            box.addWidget(empty)
        box.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        # ---- 底部按钮 ----
        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton(confirm_text)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        footer.addWidget(btn_cancel)
        footer.addWidget(self.btn_ok)
        root.addLayout(footer)

        self._update_count()

    def _set_all(self, value: bool) -> None:
        for _key, check in self._boxes:
            check.setChecked(value)

    def _update_count(self) -> None:
        chosen = self.chosen()
        self.count_label.setText(f"已选 {len(chosen)} 项")
        self.btn_ok.setEnabled(bool(chosen))

    def chosen(self) -> "list[str]":
        """被勾选条目的 key 列表（保持列表里的原顺序）。"""
        return [key for key, check in self._boxes if check.isChecked()]

    def check_keys(self) -> "list[str]":
        """测试用：当前所有可选项的 key。"""
        return [key for key, _check in self._boxes]


def multi_pick(title: str, hint: str, entries: "list[tuple[str, str]]",
               confirm_text: str = "确定", parent=None) -> "list[str]":
    """弹出多选列表，返回被勾选的 key（取消或没选返回空列表）。

    这个函数刻意做成"永不抛异常"：界面上的批量操作不该因为弹窗出问题而崩，
    真出问题就当作"用户什么都没选"。
    """
    try:
        dialog = MultiPickDialog(title, hint, entries, confirm_text, parent)
        if dialog.exec():
            return dialog.chosen()
    except Exception as exc:  # noqa: BLE001
        try:
            config.log(f"多选弹窗失败：{type(exc).__name__}: {exc}")
        except Exception:
            pass
    return []
