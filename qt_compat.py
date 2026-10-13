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
        QLibraryInfo, QPoint, QRect, QSize,
        Qt, QThread, QTimer, pyqtSignal as Signal,
    )
    from PyQt6.QtGui import (  # noqa: F401
        QAction, QColor, QFont, QFontMetrics, QIcon, QImage, QPainter,
        QPainterPath, QPixmap,
    )
    from PyQt6.QtWidgets import (  # noqa: F401
        QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
        QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
        QMessageBox, QPushButton, QScrollArea, QSystemTrayIcon, QTabWidget,
        QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    )

    BACKEND = "PyQt6"
except ImportError as exc:  # pragma: no cover
    _IMPORT_ERROR = str(exc)
    try:
        # 与上面的 PyQt6 清单保持一一对应（此前 PySide6 分支漏了
        # QGridLayout / QInputDialog，一旦回退就会 NameError）。
        from PySide6.QtCore import (  # type: ignore  # noqa: F401
            QLibraryInfo, QPoint, QRect, QSize,
            Qt, QThread, QTimer, Signal,
        )
        from PySide6.QtGui import (  # type: ignore  # noqa: F401
            QAction, QColor, QFont, QFontMetrics, QIcon, QImage, QPainter,
            QPainterPath, QPixmap,
        )
        from PySide6.QtWidgets import (  # type: ignore  # noqa: F401
            QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
            QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
            QMessageBox, QPushButton, QScrollArea, QSystemTrayIcon, QTabWidget,
            QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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
