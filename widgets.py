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

# 每种类型没有真实图标时的占位色。
# 色值本体已经收进 `theme.FILE_TYPE_COLORS`（和品牌主色同一份 Design Token），
# 这里只是转出来给调用方用，不再在界面文件里各写一遍色号。
PLACEHOLDER_COLORS = theme.FILE_TYPE_COLORS
# 取不到类型时的兜底色
FALLBACK_TILE_COLOR = theme.FALLBACK_TILE_COLOR

# 品牌主色统一从主题取，避免同一串色值散落在多个文件里各写一遍
BRAND_ACCENT = theme.BRAND_ACCENT


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


def clear_hover(widget) -> None:
    """强制清掉控件当前的 `:hover` 高亮。

    需求："打开软件后菜单栏的高光应该随之消失，而不是一直保持高亮"。
    点完图标，鼠标**还停在原位**，Qt 不会自己补一个 leave 事件，
    `WA_UnderMouse` 就一直为真，样式表里 `:hover` 那层底色也就一直亮着——
    看起来像"卡住了"。

    这里手动把标记清掉，再 unpolish/polish 一遍让样式表重算，
    高亮立刻消失。鼠标之后移出再移回来，Qt 会重新发 Enter，
    高亮照常恢复，不影响正常悬停反馈。
    """
    try:
        if not widget.testAttribute(Qt.WidgetAttribute.WA_UnderMouse):
            return
        widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
    except Exception:
        pass


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

    但缓存**不能只看 key**：同一个 key（路径）背后的文件是会变的——
    最典型的就是本程序自己的启动流程：面板/菜单栏**先建好**（这时常用软件
    还躺在桌面上、配置里记的收纳目录路径根本不存在），随后才把桌面收进来。
    如果按 key 缓存，第一次取到的"通用白纸图标"就会被钉死一整个会话，
    用户看到的就是"有些快捷方式的图标变成白纸，怎么刷新都不变"。

    所以缓存里存的是 `(stamp, icon)`，`stamp` 由 `icons.icon_key()` 算出来
    （路径 + 修改时间 + 大小）。文件一出现 / 一变化，stamp 就变，
    下一次 `request()` 会真的重新取；取失败（返回 None）**不写缓存**，
    调用方保留占位块，等下一次重建时再试。
    """

    ready = Signal(str, object)          # (key, QIcon)

    # 取不到图标时最多重试几次（见 `_drain`）。
    # 每次重试都排到队尾、**并且至少等到下一个 tick**（见 `_drain` 里的
    # `budget`），所以 6 次 ≈ 6 个 tick（默认 50ms 一个）≈ 300ms。
    # 足够跨过"文件正在被搬动 / 刚落到磁盘上"这个窗口期，
    # 又不会在文件真的没了时白转半天。
    MAX_TRIES = 6

    def __init__(self, parent=None, interval: int = 50, per_tick: int = 6):
        super().__init__(parent)
        self._per_tick = per_tick
        self._timer = QTimer(self)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._drain)
        self._cache: "dict[str, tuple[str, QIcon]]" = {}
        # (key, path, exe_hint, size, fallback_text, hi_res, stamp, resolve, tries)
        self._queue: "list[tuple]" = []

    @staticmethod
    def _stamp(path: Path, size: int) -> str:
        """这个文件"当前长什么样"的指纹；文件不存在时是 `...|missing|...`。"""
        try:
            return icons.icon_key(Path(path), size)
        except Exception:
            return ""

    @staticmethod
    def _resolve_now(resolve, fallback: Path) -> Path:
        """问一下 resolver"现在该读哪个文件"。没有 resolver 就用原样。"""
        if resolve is None:
            return fallback
        try:
            fresh = resolve()
        except Exception:
            return fallback
        return Path(fresh) if fresh is not None else fallback

    def cached(self, key: str) -> "QIcon | None":
        entry = self._cache.get(key)
        return entry[1] if entry else None

    def request(self, key: str, path: Path, exe_hint: "Path | None", size: int,
                fallback_text: str = "", hi_res: bool = False,
                resolve=None) -> None:
        """排一个取图标的活。

        `hi_res=True` 走 `icons.get_icon_best()`——两条高清来源都试，
        再由 Qt 缩到 `size`。菜单栏 / 收纳面板这种"图标要比 32px 大"的地方
        必须开，否则就是把 32×32 硬拉大（"图标清晰度太低"的根因）。
        主面板那种一次几百个 16px 小图标的列表保持默认，省内存也省时间。

        `key` 是调用方的身份（路径 / `app:<路径>`），`path` 是**真正去取图标的
        那个文件**——两者可以不同：常用软件记的是收纳目录里的路径，
        而程序刚启动时那个文件还没被收进来，这时调用方会把桌面上的"孪生"
        路径传进来取图，身份仍然是原来那个。

        `resolve`（可选）是一个"现算该读哪个文件"的回调，返回 `Path | None`。
        **这是"菜单栏常用软件图标在启动时不能正常加载"的根因修复**：
        调用方排队的那一刻文件在哪，和真正轮到它取图时文件在哪，**可能不是
        同一个地方**——本程序启动流程正是如此：

            构造 DockBar（排队取图标，这时常用软件还躺在桌面上）
              → auto_take_desktop()（把它们搬进收纳目录）
              → app.exec()（取图标的定时器这时才第一次跑）

        搬完之后，排队时记下的那个桌面路径已经不存在了，`icons` 会直接
        返回 None，于是每个常用项都停在占位字母上。传了 `resolve` 之后，
        每次取图前都**重新问一遍**，就自然读到搬过去的那一份了。
        """
        path = self._resolve_now(resolve, Path(path))
        stamp = self._stamp(path, size)
        entry = self._cache.get(key)
        if entry is not None and entry[0] == stamp:
            return                       # 同一份文件、同一个尺寸，已经有了
        for existing in self._queue:
            if existing[0] == key and existing[6] == stamp:
                return
        self._queue.append((key, path, exe_hint, size, fallback_text, hi_res,
                            stamp, resolve, 0))
        if not self._timer.isActive():
            self._timer.start()

    def forget(self, key: str) -> None:
        """丢掉某个 key 的缓存，让下一次 `request()` 真的重取。"""
        self._cache.pop(key, None)

    def _drain(self) -> None:
        # ⚠️ 这一轮**只处理开始时就已经在队里的那些**。
        # 不能写成 `for _ in range(self._per_tick)`：取失败会把请求排回队尾，
        # 那个循环会立刻把它再弹出来——几次重试在**同一个 tick 里**就烧光了，
        # 等于没有重试（"文件晚一步出现"照样补不回来）。
        budget = min(self._per_tick, len(self._queue))
        for _ in range(budget):
            if not self._queue:
                break
            item = self._queue.pop(0)
            key, path, hint, size, fallback, hi_res, stamp, resolve, tries = item

            # 排队到真正取图之间，文件可能已经被搬到别处了（见 `request()`
            # 的说明）。所以取图之前**重新问一遍**该读哪个文件，而不是
            # 用排队那一刻的快照。
            fresh = self._resolve_now(resolve, path)
            if fresh != path:
                path = fresh
                stamp = self._stamp(path, size)
                # 目标文件变了，原来算的 hint（.lnk 指向的 exe）也可能不对了
                hint = None

            entry = self._cache.get(key)
            if entry is not None and entry[0] == stamp:
                continue

            if hi_res and hint is None:
                # 高清档才顺手解析 .lnk 的目标：这两处（菜单栏、收纳面板常用排）
                # 总共就几十项，多读一次小文件换一张清晰得多的图标是值的。
                # 主面板那种一次几百个 16px 小图标的列表不走这一步，省时间。
                hint = icon_hint_for(path)

            icon = self._load(path, hint, size, hi_res)
            if icon is not None:
                self._cache[key] = (stamp, icon)
                self.ready.emit(key, icon)
                continue

            # 取不到：**不写缓存**，调用方继续用它的占位块。
            # 写进去的话，"文件还没到位"这一刻的失败就会被钉死一整个会话
            # （"加了常用软件之后图标一直是白纸"就是这么来的）。
            #
            # 但光"不写缓存"不够——没人会再调 `request()` 了，占位块就永远
            # 留在那儿。所以自己排到队尾再试几次：文件正在被搬动 / 还没落盘
            # 这种短暂状态，几个 tick 之后就正常了。
            if tries + 1 < self.MAX_TRIES:
                self._queue.append((key, path, hint, size, fallback, hi_res,
                                    stamp, resolve, tries + 1))
                if not self._timer.isActive():
                    self._timer.start()

        # 队空了就把定时器停掉（重试会把请求排回队里，所以这里要重新看一次，
        # 不能像以前那样在循环里 `return`）。
        if not self._queue:
            self._timer.stop()

    def _load(self, path: Path, hint: "Path | None", size: int, hi_res: bool):
        """真正去取一张图标，转成 QIcon；取不到返回 None。"""
        try:
            if hi_res:
                raw = icons.get_icon_best(path, size, exe_hint=hint)
            else:
                raw = icons.get_icon(path, size, exe_hint=hint)
        except Exception:
            return None
        if raw is None or not getattr(raw, "is_valid", lambda: False)():
            return None
        try:
            return raw_to_qicon(raw)
        except Exception:
            return None

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
