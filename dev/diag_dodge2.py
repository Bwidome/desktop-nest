#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行为诊断：让程序真跑 6 秒，逐秒打印 dock 的可见性和自动显隐的状态。

目的：确认 `_auto_show_tick` 到底有没有在跑、判定成什么、有没有真的隐藏。

用法：python dev/diag_dodge2.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.pop("QT_QPA_PLATFORM", None)

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-diag2"
    base.mkdir(parents=True, exist_ok=True)
    desktop = base / "Desktop"
    desktop.mkdir(exist_ok=True)

    from qt_compat import QApplication

    app = QApplication([])

    import config as config_mod
    import nest

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False})
    nest.nest_root = lambda: base / ".nest"
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "Public"

    import tray_app

    tray = tray_app.TrayApp(cfg, silent=True)
    tray.dock.show_bar()

    # 记录每次 tick 的判定
    log = []
    original = tray._auto_show_tick

    def wrapped():
        try:
            avoid = tray._should_avoid_dock()
            in_use = tray._dock_in_use()
            log.append((round(time.monotonic(), 2), avoid, in_use,
                        tray.dock.isVisible(), tray._fs_streak))
        except Exception as exc:
            log.append(("err", repr(exc)))
        return original()

    tray._auto_show_tick = wrapped

    print("=" * 72)
    print("  跑 6 秒，每秒看一次状态")
    print("=" * 72)
    print(f"dock_visible       = {cfg.get('dock_visible')}")
    print(f"dock_auto_show     = {cfg.get('dock_auto_show')}")
    print(f"dock_hidden_by_user= {cfg.get('dock_hidden_by_user')}")
    print(f"dock_avoid_fullscreen = {cfg.get('dock_avoid_fullscreen')}")
    print()

    started = time.monotonic()
    while time.monotonic() - started < 6.0:
        app.processEvents()
        time.sleep(0.01)
        elapsed = time.monotonic() - started
        if abs(elapsed - round(elapsed)) < 0.01:
            print(f"  t={elapsed:4.1f}s  dock可见={tray.dock.isVisible()!s:5}  "
                  f"avoid={tray._should_avoid_dock()!s:5}  "
                  f"in_use={tray._dock_in_use()!s:5}  "
                  f"fs_streak={tray._fs_streak}")

    print()
    print("--- tick 调用记录（时间, avoid, in_use, 可见, streak）---")
    for row in log:
        print(f"  {row}")
    print(f"\n共 {len(log)} 次 tick")
    if len(log) <= 1:
        print("  !! tick 几乎没跑 —— 定时器链断了，这才是'没生效'的原因")

    print()
    print("--- 最终 ---")
    print(f"  dock 可见 : {tray.dock.isVisible()}")
    print(f"  fs_streak : {tray._fs_streak}")
    print(f"  hidden_for_fullscreen : {tray._dock_hidden_for_fullscreen}")

    try:
        tray.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
