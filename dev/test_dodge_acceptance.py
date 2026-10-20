#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
窗口避让 —— 验收清单**剩余项**的实机测试
=========================================

`dev/test_dodge_live.py` 覆盖了"遮挡 → 隐藏 → 移走 → 回来"这条主线。
这个文件补的是主线之外、但验收清单里点名要求的几条：

  A. DPI 缩放：物理像素（Win32）与逻辑像素（Qt）的换算必须自洽
     —— 本机是 125%，正好能验真实的非整数缩放
  B. 主面板 / 收纳面板 / 设置窗口 / 右键菜单 **不能**触发自我隐藏
     （它们和菜单栏同进程，按 PID 排除；但要有实测证据）
  C. 两个窗口互相覆盖时，不能因为其中一个失焦就错误显示
     （判据必须枚举**所有**窗口，而不是只看前台）
  D. 遮挡时鼠标碰屏幕底部**不许**把菜单栏弹出来（用户报的 bug），
     以及"窗口挪走之后同一位置真的能点到"（`WindowFromPoint` 命中测试）
  E. DWM cloaked（隐形窗口）过滤：被 cloaked 的窗口不该继续压着菜单栏
  F. 反复 stop / start 不会重复注册事件钩子

用法：python dev/test_dodge_acceptance.py
退出码：全部通过 0，否则 1。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.pop("QT_QPA_PLATFORM", None)       # 必须用真实平台

PASS, FAIL = [], []
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
SW_MINIMIZE = 6
SWP_NOACTIVATE = 0x0010
GA_ROOT = 2
DWMWA_CLOAK = 13

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def note(label: str, detail: str = "") -> None:
    print(f"  · {label}" + (f"  [{detail}]" if detail else ""))


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


def class_of(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def root_of(hwnd: int) -> int:
    """拿到最外层窗口（命中测试可能落在子窗口上）。"""
    if not hwnd:
        return 0
    try:
        root = user32.GetAncestor(hwnd, GA_ROOT)
        return int(root or hwnd)
    except Exception:
        return int(hwnd)


def window_at(x: int, y: int) -> int:
    """物理像素坐标处，最上层的那个窗口（含子窗口）。"""
    try:
        pt = wintypes.POINT(int(x), int(y))
        return root_of(int(user32.WindowFromPoint(pt) or 0))
    except Exception:
        return 0


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-dodge-accept"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    desktop = base / "Desktop"
    desktop.mkdir(exist_ok=True)

    from qt_compat import QApplication

    app = QApplication([])

    import config as config_mod
    import nest
    import dock_dodge

    cfg = config_mod.Config(base / "cfg")
    cfg.update({
        "desktop": str(desktop),
        "panel_on_start": "never",
        "auto_take_on_start": False,
        "dock_visible": True,
        "dock_hidden_by_user": False,
        "dock_auto_show": True,
        "dock_avoid_fullscreen": True,
        "dock_avoid_overlap": True,
        "dock_x": None,
        "dock_y": None,
    })
    nest.nest_root = lambda: base / ".nest"
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "Public"

    import tray_app

    tray = tray_app.TrayApp(cfg, silent=True)
    dock = tray.dock
    dodge = tray.dodge

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.004)

    def wait_for(pred, timeout: float, label: str) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if pred():
                return True
            time.sleep(0.008)
        print(f"      (等待超时: {label})")
        return False

    def settle(timeout: float = 3.0) -> None:
        wait_for(lambda: not dodge._animating, timeout, "动画结束")
        pump(0.12)

    def move_cursor_onto_dock(cx: int, cy: int, tries: int = 15) -> bool:
        """把光标移到菜单栏那条上。

        ⚠️ 这个环境里 `SetCursorPos` 会**间歇性**返回 False（沙箱限制），
        单次失败不代表功能有问题，所以重试到 `_mouse_on_edge()` 为真为止。
        """
        for _ in range(tries):
            try:
                user32.SetCursorPos(int(cx), int(cy))
            except Exception:
                pass
            pump(0.06)
            if dodge._mouse_on_edge():
                return True
        return False

    probes: "list[subprocess.Popen]" = []
    saved_excluded = None
    original_fs = None

    def spawn_probe(x, y, w, h):
        ready = base / f"probe-{len(probes)}.ready"
        if ready.exists():
            ready.unlink()
        proc = subprocess.Popen(
            [sys.executable, str(HERE / "dev" / "_dodge_probe_window.py"),
             str(int(x)), str(int(y)), str(int(w)), str(int(h)), str(ready)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        probes.append(proc)
        if not wait_for(ready.exists, 15.0, "探针窗口就绪"):
            return proc, 0
        return proc, int(ready.read_text(encoding="utf-8").split()[1])

    def kill_probe(proc) -> None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    try:
        # ==================================================================
        section("准备：隔离环境噪声，建立基线")
        # ==================================================================
        dock.show_bar()
        pump(0.6)
        settle()
        noise_classes = {item[2] for item in dodge.covering_windows()}
        fg = tray._foreground_hwnd()
        if fg:
            noise_classes.add(class_of(fg))
        noise_classes.discard("")
        noise_classes.discard("DesktopNestDodgeProbe")

        saved_excluded = set(dock_dodge.EXCLUDED_CLASSES)
        dock_dodge.EXCLUDED_CLASSES |= noise_classes
        original_fs = tray._foreground_is_fullscreen

        def _fs_isolated() -> bool:
            f = tray._foreground_hwnd()
            if f and class_of(f) in noise_classes:
                return False
            return original_fs()

        tray._foreground_is_fullscreen = _fs_isolated
        dodge.notify_changed()
        dock.show_bar()
        pump(0.8)
        settle()
        check("基线：无遮挡，菜单栏可见",
              dock.isVisible() and not dodge.is_occluded(),
              f"visible={dock.isVisible()} occluded={dodge._occluded}")

        dock_rect = dodge._live_dock_rect()
        if dock_rect is None:
            note("拿不到菜单栏矩形，无法继续")
            return 1
        home_pos = dock.pos()

        # ==================================================================
        section("A. DPI 缩放：物理像素与逻辑像素换算自洽")
        # ==================================================================
        dpr = float(dock.devicePixelRatioF())
        geo = dock.frameGeometry()
        phys_w = dock_rect[2] - dock_rect[0]
        phys_h = dock_rect[3] - dock_rect[1]
        print(f"  devicePixelRatio = {dpr}")
        print(f"  逻辑 {geo.width()}x{geo.height()}  →  物理 {phys_w}x{phys_h}")
        check("宽度换算自洽（物理 ≈ 逻辑 × DPR，误差 ≤ 2px）",
              abs(phys_w - geo.width() * dpr) <= 2,
              f"{phys_w} vs {geo.width() * dpr:.1f}")
        check("高度换算自洽（物理 ≈ 逻辑 × DPR，误差 ≤ 2px）",
              abs(phys_h - geo.height() * dpr) <= 2,
              f"{phys_h} vs {geo.height() * dpr:.1f}")
        check("非 100% 缩放时物理与逻辑确实不同（说明这个检查有意义）",
              dpr == 1.0 or phys_w != geo.width(),
              f"dpr={dpr} phys={phys_w} logical={geo.width()}")
        # 坐标原点也要对得上
        check("左上角 x 换算自洽",
              abs(dock_rect[0] - geo.x() * dpr) <= 2,
              f"{dock_rect[0]} vs {geo.x() * dpr:.1f}")
        check("左上角 y 换算自洽",
              abs(dock_rect[1] - geo.y() * dpr) <= 2,
              f"{dock_rect[1]} vs {geo.y() * dpr:.1f}")

        # ==================================================================
        section("B. 自己的窗口不能触发自我隐藏")
        # ==================================================================
        # B1 收纳面板（贴着菜单栏正上方、宽度盖得住 —— 最容易被误判的那个）
        tray.desktop_browser.show_window()
        pump(0.9)
        settle()
        check("收纳面板开着 → 菜单栏不被自己人藏起来",
              dock.isVisible() and not dodge._occluded,
              f"visible={dock.isVisible()} occluded={dodge._occluded}")
        tray.desktop_browser.hide()
        pump(0.3)

        # B2 主面板
        tray.open_panel()
        pump(0.9)
        settle()
        check("主面板开着 → 菜单栏不被自己人藏起来",
              dock.isVisible() and not dodge._occluded,
              f"visible={dock.isVisible()} occluded={dodge._occluded}")
        try:
            tray.panel.hide()
        except Exception:
            pass
        pump(0.3)

        # B3 设置窗口（open_settings() 是 exec() 会阻塞，这里直接 show 一个）
        dlg = None
        try:
            from settings import SettingsDialog
            dlg = SettingsDialog(cfg, tray, dark=bool(cfg.get("dark")))
            dlg.show()
            pump(0.9)
            settle()
            check("设置窗口开着 → 菜单栏不被自己人藏起来",
                  dock.isVisible() and not dodge._occluded,
                  f"visible={dock.isVisible()} occluded={dodge._occluded}")
        except Exception as exc:
            note("设置窗口没能打开，跳过", f"{type(exc).__name__}: {exc}")
        finally:
            if dlg is not None:
                try:
                    dlg.close()
                    dlg.deleteLater()
                except Exception:
                    pass
                pump(0.3)

        # B4 托盘右键菜单
        try:
            tray.rebuild_tray_menu()
            tray.menu.popup(dock.mapToGlobal(dock.rect().center()))
            pump(0.7)
            check("右键菜单弹出时 → 菜单栏不被自己人藏起来",
                  dock.isVisible() and not dodge._occluded,
                  f"visible={dock.isVisible()} occluded={dodge._occluded}")
        except Exception as exc:
            note("右键菜单没能弹出，跳过", f"{type(exc).__name__}: {exc}")
        finally:
            try:
                tray.menu.close()
            except Exception:
                pass
            pump(0.3)

        # ==================================================================
        section("C. 两个窗口互相覆盖：不能因为失焦就错误显示")
        # ==================================================================
        left, top, right, bottom = dock_rect
        probe_a, hwnd_a = spawn_probe(60, 60, 420, 300)
        probe_b, hwnd_b = spawn_probe(80, 90, 300, 220)
        if not (hwnd_a and hwnd_b):
            note("探针没起来，跳过 C / D / E")
        else:
            # A 压住菜单栏 → 应该隐藏
            user32.SetWindowPos(hwnd_a, 0, left - 120, top - 220,
                                (right - left) + 260, (bottom - top) + 300,
                                SWP_NOACTIVATE)   # 不带 NOZORDER → 顺带置顶
            ok = wait_for(lambda: not dock.isVisible(), 3.0, "A 遮挡隐藏")
            check("前置：A 压住菜单栏 → 隐藏", ok)
            settle()

            # B 盖在 A 上面、但自己没压住菜单栏；此时 B 是前台、A 失焦
            user32.SetWindowPos(hwnd_b, 0, left - 100, top - 400, 320, 240,
                                SWP_NOACTIVATE)   # 置顶 + 只盖 A 的上半部分
            pump(0.9)
            settle()
            check("B 盖住 A 且成为前台、B 自己没压菜单栏 → 仍然保持隐藏"
                  "（说明没有只看前台窗口）",
                  not dock.isVisible(),
                  f"visible={dock.isVisible()} occluded={dodge._occluded}")
            check("此刻 A 依然被枚举到（它只是被 B 盖住、并没有消失）",
                  any(item[0] == hwnd_a for item in dodge.covering_windows()),
                  str([item[0] for item in dodge.covering_windows()]))

            # 把 A 移走 → B 不压菜单栏 → 应该显示
            user32.SetWindowPos(hwnd_a, 0, 60, 60, 420, 300, SWP_NOACTIVATE)
            ok = wait_for(lambda: dock.isVisible(), 3.0, "A 移走后显示")
            check("A 移走后（B 还在）→ 菜单栏回来", ok)
            settle()

            # ==============================================================
            section("D. 遮挡时鼠标碰屏幕底部 → **不许**弹出来（用户报的 bug）")
            # ==============================================================
            # 旧行为是"鼠标停在菜单栏那块就唤回来"。结果全屏看视频时，
            # 鼠标往下一甩（去够播放控制条）菜单栏就冒出来盖在视频上。
            # 现在的规则：只有**前台就是桌面**、且没人占着菜单栏那块时才唤回。
            user32.SetWindowPos(hwnd_a, 0, left - 120, top - 220,
                                (right - left) + 260, (bottom - top) + 300,
                                SWP_NOACTIVATE)
            ok = wait_for(lambda: not dock.isVisible(), 3.0, "再次遮挡隐藏")
            check("前置：再次被遮挡并隐藏", ok)
            settle()

            cx = (dock_rect[0] + dock_rect[2]) // 2
            cy = (dock_rect[1] + dock_rect[3]) // 2
            hit_hidden = window_at(cx, cy)
            check("隐藏后，菜单栏那块位置**不属于**菜单栏（不会继续拦点击）",
                  hit_hidden != int(dock.winId()),
                  f"命中 hwnd={hit_hidden} dock={int(dock.winId())}")

            old_dwell, old_hold = dock_dodge.EDGE_DWELL, dock_dodge.PEEK_HOLD
            old_cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(old_cursor))
            dock_dodge.EDGE_DWELL = 0.05
            dock_dodge.PEEK_HOLD = 1.5
            try:
                moved = move_cursor_onto_dock(cx, cy)
                if not moved:
                    note("本环境的沙箱拒绝了移动光标（SetCursorPos 反复失败），"
                         "「遮挡时鼠标碰底部不弹」这一条无法验证",
                         f"QCursor={dock_dodge.QCursor.pos()} 目标物理=({cx},{cy})")
                else:
                    # 光标停在菜单栏那块上，等足 1.2 秒（远超 EDGE_DWELL）
                    pump(1.2)
                    settle()
                    check("窗口压着菜单栏时，鼠标停在屏幕底部 → 菜单栏**不弹**"
                          "（这正是用户报的 bug）",
                          not dock.isVisible(),
                          f"visible={dock.isVisible()} "
                          f"peek={max(0.0, dodge._peek_until - time.monotonic()):.2f} "
                          f"onDesktop={dodge._on_desktop()} "
                          f"occluded={dodge._occluded}")
                    check("没有留下「唤回保持期」（否则切回桌面还会赖一会儿）",
                          dodge._peek_until == 0.0,
                          f"peek={dodge._peek_until}")
            finally:
                dock_dodge.EDGE_DWELL, dock_dodge.PEEK_HOLD = old_dwell, old_hold
                try:
                    user32.SetCursorPos(old_cursor.x, old_cursor.y)
                except Exception:
                    pass

            # 把窗口挪走 → 它自己回来，然后验命中测试（证明真的能点到）
            user32.SetWindowPos(hwnd_a, 0, 60, 60, 420, 300, SWP_NOACTIVATE)
            ok = wait_for(lambda: dock.isVisible(), 3.0, "挪走后显示")
            check("遮挡窗口挪走 → 菜单栏自己回来（不用鼠标去唤）", ok)
            settle()
            hit_shown = window_at(cx, cy)
            check("回来后同一位置命中的就是菜单栏（图标可以点了）",
                  hit_shown == int(dock.winId()),
                  f"命中 hwnd={hit_shown} dock={int(dock.winId())} "
                  f"class={class_of(hit_shown)!r}")
            check("没有残留的点击穿透位",
                  (user32.GetWindowLongPtrW(int(dock.winId()), GWL_EXSTYLE)
                   & WS_EX_TRANSPARENT) == 0)

            # ==============================================================
            section("E. DWM cloaked（隐形窗口）过滤")
            # ==============================================================
            # 目标场景：UWP 挂起 / 窗口被移到别的虚拟桌面。
            # IsWindowVisible 仍为 True、矩形还压着菜单栏，但用户根本看不见它。
            # 不排除的话，菜单栏会莫名其妙一直藏着不回来。
            #
            # 本环境不允许 `DwmSetWindowAttribute(DWMWA_CLOAK)`（返回
            # E_ACCESSDENIED），没法自己造一个 cloaked 窗口出来。所以拆成两段验：
            #   E1 查询本身有效 —— 拿本机**真实存在**的 cloaked 窗口做样本；
            #   E2 过滤链路有效 —— 把探针"当成" cloaked，看菜单栏是否回来。
            real = []

            def _scan(h, _):
                try:
                    if user32.IsWindowVisible(h) and dodge._is_cloaked(h):
                        t = ctypes.create_unicode_buffer(120)
                        user32.GetWindowTextW(h, t, 120)
                        if t.value:
                            real.append((int(h), t.value))
                except Exception:
                    pass
                return True

            user32.EnumWindows(WNDENUMPROC(_scan), 0)
            if real:
                check(f"DWM 能识别本机真实存在的 cloaked 窗口（找到 {len(real)} 个带标题的）",
                      True)
                for h, t in real[:3]:
                    print(f"      例：hwnd={h} 标题={t!r}")
            else:
                note("本机当前没有「可见且有标题」的 cloaked 窗口，E1 无法实测")

            check("普通窗口不会被误判成 cloaked", not dodge._is_cloaked(hwnd_a))

            # 前置：让 A 重新压住菜单栏并等它藏好（顺手结束上次唤回的保持期）
            dodge._peek_until = 0.0
            user32.SetWindowPos(hwnd_a, 0, left - 120, top - 220,
                                (right - left) + 260, (bottom - top) + 300,
                                SWP_NOACTIVATE)
            ok = wait_for(lambda: not dock.isVisible(), 3.0, "E 前置：遮挡隐藏")
            check("前置：探针压住菜单栏 → 隐藏", ok)
            settle()

            orig_cloaked = dodge._is_cloaked
            try:
                dodge._is_cloaked = (
                    lambda h: True if int(h) == hwnd_a else orig_cloaked(h))
                ok = wait_for(lambda: dock.isVisible(), 3.0, "cloaked 后显示")
                check("被 cloaked 的窗口不再算遮挡 → 菜单栏回来", ok)
                settle()
                check("cloaked 期间它确实从 covering_windows 里消失了",
                      not any(item[0] == hwnd_a
                              for item in dodge.covering_windows()),
                      str([item[0] for item in dodge.covering_windows()]))
            finally:
                dodge._is_cloaked = orig_cloaked
            ok = wait_for(lambda: not dock.isVisible(), 3.0, "恢复后重新隐藏")
            check("去掉 cloaked 之后遮挡重新成立 → 菜单栏又让开", ok)
            settle()

            # ==============================================================
            section("F. 反复 stop / start 不会重复注册事件钩子")
            # ==============================================================
            n0 = len(dodge._hooks)
            check("初始钩子数量受控（≤3）", 0 < n0 <= 3, str(n0))
            dodge.stop()
            check("stop() 后钩子清零", len(dodge._hooks) == 0,
                  str(len(dodge._hooks)))
            dodge.start()
            n1 = len(dodge._hooks)
            check("再 start() 只装回同样数量，没有翻倍",
                  n1 == n0, f"{n0} → {n1}")
            dodge.stop()
            dodge.start()
            n2 = len(dodge._hooks)
            check("第二轮 stop/start 依然不累加", n2 == n0, f"{n0} → {n2}")
            check("回调引用数量与钩子一致（没有悬空引用）",
                  len(dodge._hook_procs) == len(dodge._hooks),
                  f"{len(dodge._hook_procs)} vs {len(dodge._hooks)}")

            for proc, hwnd in ((probe_a, hwnd_a), (probe_b, hwnd_b)):
                try:
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                except Exception:
                    pass
            pump(0.4)

    finally:
        if original_fs is not None:
            tray._foreground_is_fullscreen = original_fs
        if saved_excluded is not None:
            dock_dodge.EXCLUDED_CLASSES = saved_excluded
        for proc in probes:
            kill_probe(proc)
        try:
            tray.shutdown()
        except Exception:
            pass

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for item in FAIL:
            print(f"  ✗ {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
