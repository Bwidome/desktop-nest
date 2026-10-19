#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断：为什么"菜单栏按重叠自动隐藏"没生效。

在**真实 Windows 平台**（不是 offscreen）上跑，打印：
1. dock 窗口的 HWND、GetWindowRect 是否成功
2. 前台窗口的 HWND / 矩形
3. 枚举所有可见顶层窗口，看有几个真的和 dock 矩形相交
4. 对照 `_foreground_hits_dock()` 的返回值

用法：python dev/diag_dodge.py
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

os.environ.pop("QT_QPA_PLATFORM", None)      # 必须原生平台

user32 = ctypes.windll.user32

# 关键：先把签名声明清楚，否则 64 位下 HWND 会被当 32 位截断
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def rect_of(hwnd):
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def enum_windows():
    found = []

    def callback(hwnd, _lparam):
        found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-diag"
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
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)

    dock = tray.dock
    hwnd = int(dock.winId())
    print("=" * 70)
    print("  窗口避让诊断")
    print("=" * 70)
    print(f"平台            : {app.platformName()}")
    print(f"dock.winId()    : {hwnd}  (0x{hwnd:X})")
    print(f"  超过 32 位？  : {'是 ← 会被截断！' if hwnd > 0xFFFFFFFF else '否'}")
    print(f"dock.geometry() : {dock.geometry()}   (Qt 逻辑坐标)")
    print(f"dock DPR        : {dock.devicePixelRatioF()}")

    dr = rect_of(hwnd)
    print(f"GetWindowRect   : {dr}   (Win32 物理像素)")
    if dr is None:
        print("  !! 拿不到 dock 的矩形 —— 这就是没生效的直接原因")
    else:
        print(f"  宽×高         : {dr[2] - dr[0]} × {dr[3] - dr[1]}")

    fg = user32.GetForegroundWindow()
    print(f"\n前台 HWND       : {fg}")
    print(f"前台矩形        : {rect_of(fg)}")
    print(f"前台是本进程？  : {tray._foreground_is_self()}")
    print(f"前台是桌面？    : {tray._desktop_is_foreground()}")

    print(f"\n_foreground_is_fullscreen() : {tray._foreground_is_fullscreen()}")
    print(f"_foreground_hits_dock()     : {tray._foreground_hits_dock()}")
    print(f"_dock_in_use()              : {tray._dock_in_use()}")

    print("\n--- 枚举所有可见顶层窗口，看谁和 dock 相交 ---")
    if dr is not None:
        for h in enum_windows():
            if not user32.IsWindowVisible(h):
                continue
            if user32.IsIconic(h):
                continue
            r = rect_of(h)
            if r is None:
                continue
            overlap_x = min(r[2], dr[2]) - max(r[0], dr[0])
            overlap_y = min(r[3], dr[3]) - max(r[1], dr[1])
            if overlap_x > 0 and overlap_y > 0:
                buf = ctypes.create_unicode_buffer(120)
                user32.GetWindowTextW(h, buf, 120)
                cls = ctypes.create_unicode_buffer(120)
                user32.GetClassNameW(h, cls, 120)
                pid = ctypes.c_ulong(0)
                user32.GetWindowThreadProcessId(
                    ctypes.c_void_p(h), ctypes.byref(pid))
                mine = int(pid.value) == os.getpid()
                print(f"  {h}  交叠 {overlap_x}x{overlap_y}  "
                      f"{'[自己]' if mine else '[别的程序]'}  "
                      f"cls={cls.value}  title={buf.value[:40]!r}")

    print("\n结论：")
    print("  · 如果 dock 矩形拿不到 → HWND 传递有问题（argtypes 没声明）")
    print("  · 如果只查前台窗口，那么'前台窗口没盖住但别的窗口盖住了'就漏判")
    print("  · 正确做法：枚举**所有**可见顶层窗口，任何一个与 dock 相交即视为遮挡")

    try:
        tray.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
