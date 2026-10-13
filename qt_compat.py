#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qt 加载器
=========
优先用程序自带 `libs/` 里的 PyQt6（这样换台机器、换个 Python 也能跑），
找不到就退回系统里安装的 PyQt6 / PySide6。

另外提供两个小工具：原始像素 → 图标、圆角图形。
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

try:
    from PyQt6.QtCore import (  # noqa: F401
        QByteArray, QEvent, QLibraryInfo, QMimeData, QObject, QPoint, QRect, QSize,
        Qt, QThread, QTimer, QUrl, pyqtSignal as Signal, pyqtSlot as Slot,
    )
    from PyQt6.QtGui import (  # noqa: F401
        QAction, QBrush, QColor, QCursor, QDesktopServices, QFont, QFontMetrics,
        QGuiApplication, QIcon, QImage, QKeySequence, QLinearGradient, QPainter,
        QPainterPath, QPen, QPixmap, QShortcut, QTextOption,
    )
    from PyQt6.QtWidgets import (  # noqa: F401
        QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
        QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea,
        QSizeGrip, QSizePolicy, QSpacerItem, QStackedWidget, QStyle,
        QStyledItemDelegate, QStyleOptionViewItem, QSystemTrayIcon, QTabWidget,
        QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    )

    BACKEND = "PyQt6"
except ImportError as exc:  # pragma: no cover
    _IMPORT_ERROR = str(exc)
    try:
        from PySide6.QtCore import (  # type: ignore  # noqa: F401
            QByteArray, QEvent, QLibraryInfo, QMimeData, QObject, QPoint, QRect, QSize,
            Qt, QThread, QTimer, QUrl, Signal, Slot,
        )
        from PySide6.QtGui import (  # type: ignore  # noqa: F401
            QAction, QBrush, QColor, QCursor, QDesktopServices, QFont, QFontMetrics,
            QGuiApplication, QIcon, QImage, QKeySequence, QLinearGradient, QPainter,
            QPainterPath, QPen, QPixmap, QShortcut, QTextOption,
        )
        from PySide6.QtWidgets import (  # type: ignore  # noqa: F401
            QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
            QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
            QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizeGrip,
            QSizePolicy, QSpacerItem, QStackedWidget, QStyle, QStyledItemDelegate,
            QStyleOptionViewItem, QSystemTrayIcon, QTabWidget, QToolButton,
            QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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


def raw_to_pixmap(raw, size: int = 0) -> "QPixmap | None":
    if raw is None or not getattr(raw, "is_valid", lambda: False)():
        return None
    image = QImage(raw.bgra, raw.width, raw.height,
                   raw.width * 4, QImage.Format.Format_ARGB32)
    if image.isNull():
        return None
    pixmap = QPixmap.fromImage(image.copy())
    if size and size > 0 and pixmap.width() != size:
        pixmap = pixmap.scaled(size, size,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
    return pixmap


def letter_icon(letter: str, color: str, size: int = 48) -> "QPixmap":
    """生成一个带首字母的圆角占位图标（取不到真实图标时用）。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, size * 0.24, size * 0.24)
    painter.fillPath(path, QColor(color))
    painter.setPen(QColor("#FFFFFF"))
    font = QFont()
    font.setPixelSize(max(1, int(size * 0.46)))      # 负数或 0 会让 Qt 报错
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), letter[:1].upper())
    painter.end()
    return pixmap


def elide(text: str, font: "QFont", width: int) -> str:
    metrics = QFontMetrics(font)
    return metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(10, width))
