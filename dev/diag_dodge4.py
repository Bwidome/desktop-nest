#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 4：真实桌面上"到底是谁把菜单栏判成被遮挡"。
先把 covering_windows() 命中的真实窗口最小化，再看残留的遮挡判据是什么。

用法：python dev/diag_dodge4.py
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))
os.environ.pop("QT_QPA_PLATFORM", None)

user32 = ctypes.windll.user32
SW_MINIMIZE = 6


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-diag4"
    base.mkdir(parents=True, exist_ok=True)
    desktop = base / "Desktop"
    desktop.mkdir(exist_ok=True)

    from qt_compat import QApplication

    app = QApplication([])

    import config as config_mod
    import nest

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False, "dock_visible": True,
                "dock_hidden_by_user": False})
    nest.nest_root = lambda: base / ".nest"
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "Public"

    import tray_app

    tray = tray_app.TrayApp(cfg, silent=True)
    dock, dodge = tray.dock, tray.dodge
    dock.show_bar()

    def pump(sec: float) -> None:
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.004)

    pump(0.5)

    minimized = []
    for _ in range(10):
        if not dodge.is_occluded():
            break
        targets = [it[0] for it in dodge.covering_windows()]
        fresh = [h for h in targets if h and h not in minimized]
        if not fresh:
            break
        for h in fresh:
            user32.ShowWindow(h, SW_MINIMIZE)
            minimized.append(h)
        pump(0.4)

    pump(0.6)

    fg = tray._foreground_hwnd()
    fg_rect = None
    if fg:
        r = wintypes.RECT()
        if user32.GetWindowRect(fg, ctypes.byref(r)):
            fg_rect = (r.left, r.top, r.right, r.bottom)
    buf = ctypes.create_unicode_buffer(256)
    if fg:
        user32.GetClassNameW(fg, buf, 256)

    print("=" * 72)
    print("  基线诊断")
    print("=" * 72)
    print(f"临时最小化       : {minimized}")
    print(f"dock 可见        : {dock.isVisible()}")
    print(f"is_occluded()    : {dodge.is_occluded()}")
    print(f"  _fullscreen    : {dodge._fullscreen}")
    print(f"  _covered       : {dodge._covered}")
    print(f"covering_windows : {dodge.covering_windows()}")
    print()
    print(f"前台 hwnd        : {fg}  类名={buf.value!r}")
    print(f"前台矩形         : {fg_rect}")
    print(f"前台是本程序     : {tray._foreground_is_self()}")
    print(f"前台是桌面       : {tray._desktop_is_foreground()}")
    print(f"前台算全屏       : {tray._foreground_is_fullscreen()}")
    print()
    print(f"debug_state      : {dodge.debug_state()}")
    print(f"dock.pos()       : {dock.pos()}")
    print(f"dock.isHidden()  : {dock.isHidden()}")

    try:
        tray.shutdown()
    except Exception:
        pass
    for h in reversed(minimized):
        try:
            user32.ShowWindow(h, 9)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
