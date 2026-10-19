#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 3：验证 `DockDodge.covering_windows()` 的过滤链是否真的有效。

重点看：那些"永远铺满全屏"的幽灵窗口（桌面 WorkerW、输入体验、
NVIDIA Overlay、UWP 宿主）有没有被正确排除掉。
只要漏掉一个，菜单栏就会永远藏着不回来。

用法：python dev/diag_dodge3.py
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

import dock_dodge

user32 = ctypes.windll.user32


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-diag3"
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
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)

    dodge = tray.dodge
    print("=" * 72)
    print("  covering_windows() 过滤链验证")
    print("=" * 72)
    print(f"平台            : {app.platformName()}")
    print(f"WinEvent 钩子   : {'已装 %d 个' % len(dodge._hooks) if dodge._hooks else '没装上（退化成纯轮询）'}")
    print(f"dock_rect()     : {dodge.dock_rect()}   (Win32 物理像素)")
    print(f"dock.frameGeometry() : {tray.dock.frameGeometry()}   (Qt 逻辑坐标)")
    print()

    dock_rect = dodge.dock_rect()
    print("--- 所有可见顶层窗口的判定明细 ---")
    print(f"{'HWND':>10} {'判定':<8} {'类名':<34} 标题")
    print("-" * 100)

    rows = []
    if dock_rect:
        def cb(hwnd, _l):
            try:
                visible = bool(user32.IsWindowVisible(hwnd))
                iconic = bool(user32.IsIconic(hwnd))
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                mine = int(pid.value) == os.getpid()
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                title = ctypes.create_unicode_buffer(120)
                user32.GetWindowTextW(hwnd, title, 120)
                rect = wintypes.RECT()
                ok = bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
                box = (rect.left, rect.top, rect.right, rect.bottom) if ok else None
                hit = bool(box and dock_dodge.rects_overlap(
                    box, dock_rect, dock_dodge.DOCK_HIT_MIN_X,
                    dock_dodge.DOCK_HIT_MIN_Y))

                if not visible:
                    verdict = "不可见"
                elif iconic:
                    verdict = "最小化"
                elif mine:
                    verdict = "自己人"
                elif cls.value in dock_dodge.EXCLUDED_CLASSES:
                    verdict = "黑名单"
                elif user32.GetWindowLongPtrW(hwnd, -20) & 0x80:
                    verdict = "工具窗"
                elif user32.GetWindowTextLengthW(hwnd) <= 0:
                    verdict = "无标题"
                elif not hit:
                    verdict = "没压住"
                else:
                    verdict = "★遮挡"
                if verdict == "★遮挡" or (hit and verdict in ("黑名单", "无标题", "工具窗")):
                    rows.append((int(hwnd), verdict, cls.value, title.value[:34]))
                return True
            except Exception:
                return True

        user32.EnumWindows(dock_dodge.WNDENUMPROC(cb), 0)

    for hwnd, verdict, cls, title in rows:
        print(f"{hwnd:>10} {verdict:<8} {cls[:34]:<34} {title}")

    print()
    covering = dodge.covering_windows()
    print(f"covering_windows() 命中 {len(covering)} 个：")
    for hwnd, box, cls, title in covering:
        print(f"  {hwnd}  {box}  {cls}  {title[:40]!r}")

    print()
    print(f"is_occluded()  = {dodge.is_occluded()}")
    print(f"debug_state()  = {dodge.debug_state()}")

    print()
    print("--- 观察 5 秒，看 dock 是否跟随遮挡 ---")
    started = time.monotonic()
    last = None
    while time.monotonic() - started < 5.0:
        app.processEvents()
        time.sleep(0.02)
        now = (tray.dock.isHidden(), dodge._occluded)
        if now != last:
            print(f"  t={time.monotonic() - started:4.1f}s  "
                  f"dock隐藏={now[0]!s:5}  occluded={now[1]!s:5}")
            last = now

    print()
    print("判定要点：")
    print("  · 如果有'★遮挡'命中 → dock 应该隐藏（这就是需求要的行为）")
    print("  · 如果覆盖层（WorkerW / 输入体验 / Overlay）被误判成'★遮挡' → 会永远藏")
    print("  · 如果完全没命中，但屏幕上确实有大窗口 → 过滤太严，要放宽")

    try:
        tray.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
