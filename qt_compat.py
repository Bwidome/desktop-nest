#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qt 加载器
=========
优先用程序自带 `libs/` 里的 PyQt6（这样换台机器、换个 Python 也能跑），
找不到就退回系统里安装的 PyQt6 / PySide6。

另外提供两个小工具：原始像素 → 图标、按宽度省略文字。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 自带依赖优先。必须放在 import PyQt6 之前。
_LIBS = HERE / "libs"
if _LIBS.is_dir() and str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))

# --------------------------------------------------------------------------
# 导入 Qt
# --------------------------------------------------------------------------
BACKEND = ""
_IMPORT_ERROR = ""

# 只导入各模块真正用到的名字——这份清单由「所有 `from qt_compat import ...`
# 的并集 + 本文件两个小工具的自身需要」推导而来，不再凭感觉堆一大串。
# 少一个名字会让某个模块 import 直接失败，所以增删请同步检查调用方。
try:
    from PyQt6.QtCore import (  # noqa: F401
        QEvent, QEventLoop, QEasingCurve, QLibraryInfo, QMimeData, QPoint,
        QPointF, QPropertyAnimation, QRect, QSize, Qt, QThread, QTimer,
        QVariantAnimation, pyqtSignal as Signal,
    )
    from PyQt6.QtGui import (  # noqa: F401
        QAction, QBrush, QColor, QCursor, QDrag, QDragEnterEvent,
        QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFont, QFontDatabase,
        QFontMetrics, QIcon, QImage, QLinearGradient, QMouseEvent, QPainter,
        QPainterPath, QPalette, QPen, QPixmap, QRadialGradient,
    )
    from PyQt6.QtWidgets import (  # noqa: F401
        QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
        QFileDialog, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
        QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
        QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar,
        QPushButton, QScrollArea, QSizePolicy, QSystemTrayIcon, QTabWidget,
        QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    )

    BACKEND = "PyQt6"
except ImportError as exc:  # pragma: no cover
    _IMPORT_ERROR = str(exc)
    try:
        # 与上面的 PyQt6 清单保持一一对应（此前 PySide6 分支漏了
        # QGridLayout / QInputDialog，一旦回退就会 NameError）。
        from PySide6.QtCore import (  # type: ignore  # noqa: F401
            QEvent, QEventLoop, QEasingCurve, QLibraryInfo, QMimeData, QPoint,
            QPointF, QPropertyAnimation, QRect, QSize, Qt, QThread, QTimer,
            QVariantAnimation, Signal,
        )
        from PySide6.QtGui import (  # type: ignore  # noqa: F401
            QAction, QBrush, QColor, QCursor, QDrag, QDragEnterEvent,
            QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFont, QFontDatabase,
            QFontMetrics, QIcon, QImage, QLinearGradient, QMouseEvent, QPainter,
            QPainterPath, QPalette, QPen, QPixmap, QRadialGradient,
        )
        from PySide6.QtWidgets import (  # type: ignore  # noqa: F401
            QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
            QFileDialog, QFrame, QGraphicsDropShadowEffect,
            QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QHeaderView,
            QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
            QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
            QSystemTrayIcon, QTabWidget, QToolButton, QTreeWidget,
            QTreeWidgetItem, QVBoxLayout, QWidget,
        )

        BACKEND = "PySide6"
    except ImportError:
        BACKEND = ""


MISSING_HELP = f"""
没有找到 Qt 界面库（{_IMPORT_ERROR}）。

本程序需要 PyQt6。请任选一种方式：

1) 直接在程序目录双击 `安装依赖.bat`（会自动下载配套的 PyQt6）；
2) 或者手动执行：
       python setup_libs.py
3) 或者用 pip 安装到系统里：
       python -m pip install PyQt6
"""


def require_qt() -> None:
    """没装 Qt 时给出清楚的提示，而不是丢一堆 traceback。"""
    if BACKEND:
        return
    message = MISSING_HELP
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("缺少 PyQt6", message)
        root.destroy()
    except Exception:
        pass
    print(message, file=sys.stderr)
    raise SystemExit(1)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def raw_to_icon(raw) -> "QIcon | None":
    """把 icons.RawIcon 的原始像素转成 QIcon。"""
    if raw is None or not getattr(raw, "is_valid", lambda: False)():
        return None
    image = QImage(raw.bgra, raw.width, raw.height,
                   raw.width * 4, QImage.Format.Format_ARGB32)
    if image.isNull():
        return None
    return QIcon(QPixmap.fromImage(image.copy()))


def elide(text: str, font: "QFont", width: int) -> str:
    metrics = QFontMetrics(font)
    return metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(10, width))


# --------------------------------------------------------------------------
# 弹出菜单（统一入口）
# --------------------------------------------------------------------------
def popup_menu(menu: "QMenu", pos) -> "QAction | None":
    """在指定的**全局坐标**弹出菜单并等待选择。

    为什么要有这个函数：菜单弹不出来 / 弹错位置是这块最容易出错的地方，
    集中一处处理可以避免每个调用点各写各的：

    * `pos` 允许传 QPoint、QPointF，或 None（None 时用鼠标当前位置）；
    * 位置先夹到屏幕内，否则贴屏幕边缘右键时菜单会跑到屏幕外面；
    * 统一 `menu.exec(pos)`，不要用 `menu.exec_()`（Qt6 已删）。
    """
    point = _as_global_point(pos)
    if point is not None:
        point = _clamp_to_screen(point)
    try:
        if point is None:
            return menu.exec()
        return menu.exec(point)
    except TypeError:
        # 极少数绑定版本对重载解析不同，退回到"先 popup 再拿返回值"的写法
        pass
    chosen = None
    if point is not None:
        menu.popup(point)
    else:
        menu.popup(QCursor.pos())
    loop = QEventLoop()
    menu.triggered.connect(lambda _a: loop.quit())
    menu.aboutToHide.connect(loop.quit)
    loop.exec()
    return menu.activeAction()


def _as_global_point(pos) -> "QPoint | None":
    """把各种"位置"入参统一成全局 QPoint。"""
    if pos is None:
        try:
            return QCursor.pos()
        except Exception:
            return None
    # QPoint 直接可用
    if isinstance(pos, QPoint):
        return QPoint(pos)
    # QPointF → QPoint
    if hasattr(pos, "toPoint"):
        try:
            return pos.toPoint()
        except Exception:
            pass
    # 事件对象（有些地方会直接把 event 传进来）
    for attr in ("globalPosition", "globalPos"):
        value = getattr(pos, attr, None)
        if value is None:
            continue
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if hasattr(value, "toPoint"):
            return value.toPoint()
        if isinstance(value, QPoint):
            return QPoint(value)
    try:
        return QPoint(int(pos.x()), int(pos.y()))
    except Exception:
        return None


def _clamp_to_screen(point: QPoint) -> QPoint:
    """把菜单左上角夹进鼠标所在屏幕的可用区域，避免菜单被挤出屏幕。"""
    try:
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is None:
            return point
        area = screen.availableGeometry()
        x = min(max(point.x(), area.left()), max(area.left(), area.right() - 40))
        y = min(max(point.y(), area.top()), max(area.top(), area.bottom() - 40))
        return QPoint(x, y)
    except Exception:
        return point
