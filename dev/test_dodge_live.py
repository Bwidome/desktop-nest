#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
窗口避让 —— **真实窗口**集成测试
=================================

为什么单独一个文件
------------------
`dev/test_fixes_dock.py` 跑在 `QT_QPA_PLATFORM=offscreen` 下，只能验证
"状态机 + 打桩矩形"那部分逻辑。需求明确要求：**不能只靠静态检查就声称
真实遮挡场景已经通过**。所以这里在真实桌面上：

* 真起一个 `TrayApp`（用临时目录当桌面，绝不碰用户的真实桌面）；
* 真起一个**独立进程**的普通窗口当"别的应用"（同进程会被按 PID 排除，
  那样永远测不出遮挡）；
* 用 `SetWindowPos` / `ShowWindow` / `WM_CLOSE` 真正地移动、最小化、关闭它；
* 每一步都等菜单栏的**动画真正结束**再断言，不靠 sleep 蒙。

⚠️ 环境噪声隔离（必读）
----------------------
开跑前这台机器上已经有一个最大化的 Chrome 窗口把菜单栏区域整个盖住。
它导致两件事：
  * 菜单栏在测试起点就应该是"藏着"的（这是**正确行为**，我们先验证了）；
  * 于是没法验证"窗口移走 → 菜单栏自己回来"——因为 Chrome 还盖着。

本来最干净的做法是把那些真实窗口临时最小化，但这台机器上的 DSH 沙箱
**不允许跨进程操作窗口**（实测 `ShowWindow` / `SetWindowPos` 都返回 False，
`PostMessage` 被 UIPI 拦下），所以改成：

  **把"开跑前就存在的窗口"的类名临时加进 `EXCLUDED_CLASSES`，
  并让前台全屏判定忽略这些窗口**，测试结束原样还原。

这只屏蔽**环境噪声**，产品逻辑一行没改：窗口枚举、矩形相交、WinEvent
合并、状态机、滑动动画全都照常真跑，唯一变量是测试自己起的探针窗口
（类名 `DesktopNestDodgeProbe`，不受影响）。

覆盖的验收场景
--------------
  1 真实桌面上最大化窗口盖住菜单栏 → 自动隐藏（开跑即验证）
  2 小窗口不压菜单栏              → 保持显示
  3 把窗口压到菜单栏上方          → 隐藏
  4 把窗口移走                    → 重新显示
  5 最小化遮挡窗口                → 重新显示
  6 关闭遮挡窗口                  → 重新显示
  7 遮挡时鼠标碰屏幕底部          → **不弹出来**（用户报的 bug）
  8 反复显隐之后位置不漂移
  9 关掉新开关后 → 恢复"只有全屏才让开"

用法：python dev/test_dodge_live.py
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

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
SW_MINIMIZE = 6
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


def note(label: str, detail: str = "") -> None:
    print(f"  · {label}" + (f"  [{detail}]" if detail else ""))


def class_of(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-dodge-live"
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
        """等动画真正播完，别在半路断言。"""
        wait_for(lambda: not dodge._animating, timeout, "动画结束")
        pump(0.12)

    def ex_style() -> int:
        try:
            return user32.GetWindowLongPtrW(int(dock.winId()), GWL_EXSTYLE)
        except Exception:
            return 0

    probes: "list[subprocess.Popen]" = []
    old_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old_cursor))

    saved_excluded = None
    original_fs = None

    def spawn_probe(x: int, y: int, w: int, h: int):
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
        section("0. 开跑即验证：真实桌面的最大化浏览器会让菜单栏躲开")
        # ==================================================================
        dock.show_bar()
        pump(0.8)
        settle()
        if dodge._occluded:
            check("真实桌面上本来就有窗口压住菜单栏 → 菜单栏自动隐藏",
                  dock.isHidden())
        else:
            print("  · 真实桌面当前没有窗口压住菜单栏，这一条不适用（不计失败）")

        # ------------------------------------------------------------------
        section("准备：隔离环境噪声，建立可复现的基线")
        # ------------------------------------------------------------------
        noise = list(dodge.covering_windows())
        noise_classes = {item[2] for item in noise}
        for h, box, cls, title in noise:
            print(f"  噪声窗口 {h}  {cls}  {title[:36]!r}  {box}")
        fg = tray._foreground_hwnd()
        if fg:
            noise_classes.add(class_of(fg))
        noise_classes.discard("")
        noise_classes.discard("DesktopNestDodgeProbe")

        saved_excluded = set(dock_dodge.EXCLUDED_CLASSES)
        dock_dodge.EXCLUDED_CLASSES |= noise_classes
        original_fs = tray._foreground_is_fullscreen
        print(f"  测试期间临时排除的类名: {sorted(noise_classes)}")

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
        check("隔离噪声后：没有任何窗口遮挡，菜单栏可见",
              dock.isVisible() and not dodge.is_occluded(),
              f"visible={dock.isVisible()} occluded={dodge._occluded}")

        dock_rect = dodge._live_dock_rect()
        check("能拿到菜单栏的物理像素矩形", dock_rect is not None, str(dock_rect))
        if dock_rect is None:
            return 1
        home_pos = dock.pos()
        print(f"  菜单栏物理矩形 = {dock_rect}")
        print(f"  菜单栏逻辑位置 = ({home_pos.x()}, {home_pos.y()})")

        # ------------------------------------------------------------------
        section("准备：起一个独立进程的「别的应用」窗口（放在左上角）")
        # ------------------------------------------------------------------
        probe, hwnd = spawn_probe(60, 60, 420, 300)
        if not hwnd:
            return 1
        print(f"  探针窗口 hwnd = {hwnd} (pid={probe.pid})")

        def move_probe(x: int, y: int, w: int, h: int) -> None:
            user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h),
                                SWP_NOZORDER | SWP_NOACTIVATE)
            pump(0.05)

        def probe_covers_dock() -> None:
            left, top, right, bottom = dock_rect
            move_probe(max(0, left - 120), max(0, top - 220),
                       (right - left) + 260, (bottom - top) + 300)

        pump(0.5)
        check("探针窗口能被检测到、但它的矩形没压到菜单栏",
              not dodge.covering_windows())

        # ------------------------------------------------------------------
        section("1. 小窗口不压菜单栏 → 菜单栏保持显示")
        # ------------------------------------------------------------------
        pump(0.5)
        check("窗口在别处时菜单栏不动", dock.isVisible())

        # ------------------------------------------------------------------
        section("2. 窗口压到菜单栏上 → 自动隐藏")
        # ------------------------------------------------------------------
        probe_covers_dock()
        # 顺便采样动画过程中的位置/不透明度，证明它是"往下滑出去"而不是直接消失
        hide_ys, hide_ops, saw_hide_anim = [], [], False
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            app.processEvents()
            if dodge._animating:
                saw_hide_anim = True
            hide_ys.append(dock.pos().y())
            try:
                hide_ops.append(dock.windowOpacity())
            except Exception:
                hide_ops.append(1.0)
            time.sleep(0.008)
        ok = not dock.isVisible()
        check("窗口压住菜单栏 → 菜单栏隐藏", ok)
        settle()
        check("隐藏过程真的播了动画（不是直接消失）", saw_hide_anim)
        check("隐藏是「向屏幕下方滑出」：过程中出现过比原位更靠下的位置",
              max(hide_ys) > home_pos.y() + 4,
              f"maxY={max(hide_ys)} home={home_pos.y()}")
        check("滑出过程配合了淡出（不透明度降到过 0.5 以下）",
              min(hide_ops) < 0.5, f"minOpacity={min(hide_ops):.2f}")
        check("隐藏走的是「避让」这条路径",
              dodge._last_action == "hide" and dodge._hidden_by_me is True,
              f"{dodge._last_action}/{dodge._hidden_by_me}")
        check("隐藏结束后没有留下点击穿透",
              (ex_style() & WS_EX_TRANSPARENT) == 0, hex(ex_style()))
        check("隐藏后菜单栏位置没有漂移", dock.pos() == home_pos,
              f"{dock.pos()} vs {home_pos}")

        # ------------------------------------------------------------------
        section("3. 窗口移走 → 自动重新显示")
        # ------------------------------------------------------------------
        move_probe(60, 60, 420, 300)
        show_ys, show_ops, saw_show_anim = [], [], False
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            app.processEvents()
            if dodge._animating:
                saw_show_anim = True
            show_ys.append(dock.pos().y())
            try:
                show_ops.append(dock.windowOpacity())
            except Exception:
                show_ops.append(1.0)
            time.sleep(0.008)
        ok = dock.isVisible()
        check("窗口离开菜单栏区域 → 菜单栏自己回来", ok)
        settle()
        check("显示过程真的播了动画（不是直接蹦出来）", saw_show_anim)
        check("显示是「从屏幕下方滑入」：过程中出现过比终点更靠下的位置",
              max(show_ys) > home_pos.y() + 4,
              f"maxY={max(show_ys)} home={home_pos.y()}")
        check("滑入过程配合了淡入（不透明度从低于 0.9 爬上来）",
              min(show_ops) < 0.9, f"minOpacity={min(show_ops):.2f}")
        check("重新显示后位置没有漂移", dock.pos() == home_pos,
              f"{dock.pos()} vs {home_pos}")
        check("重新显示后不透明度复位成 1",
              abs(dock.windowOpacity() - 1.0) < 0.01, str(dock.windowOpacity()))

        # ------------------------------------------------------------------
        section("4. 铺满屏幕的窗口（等价最大化）→ 隐藏")
        # ------------------------------------------------------------------
        move_probe(-8, -8, dock_rect[2] + 900, dock_rect[3] + 900)
        ok = wait_for(lambda: not dock.isVisible(), 3.0, "全屏窗口隐藏")
        check("铺满屏幕的窗口 → 菜单栏隐藏", ok)
        settle()

        # ------------------------------------------------------------------
        section("5. 最小化遮挡窗口 → 重新显示")
        # ------------------------------------------------------------------
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        ok = wait_for(lambda: dock.isVisible(), 3.0, "最小化后显示")
        check("最小化遮挡窗口 → 菜单栏回来", ok)
        settle()

        # ------------------------------------------------------------------
        section("6. 遮挡时鼠标碰屏幕底部 → 不许弹出来（用户报的 bug）")
        # ------------------------------------------------------------------
        # 旧行为：鼠标落进菜单栏那块矩形就唤回来。全屏看视频时鼠标往下一甩
        # 就冒出来盖在视频上。现在只在前台**就是桌面**时才允许唤回。
        user32.ShowWindow(hwnd, SW_RESTORE)
        pump(0.15)
        probe_covers_dock()
        ok = wait_for(lambda: not dock.isVisible(), 3.0, "再次遮挡隐藏")
        check("前置：再次被遮挡并隐藏", ok)
        settle()

        old_dwell, old_hold = dock_dodge.EDGE_DWELL, dock_dodge.PEEK_HOLD
        dock_dodge.EDGE_DWELL = 0.05
        dock_dodge.PEEK_HOLD = 0.9
        try:
            cx = (dock_rect[0] + dock_rect[2]) // 2
            cy = (dock_rect[1] + dock_rect[3]) // 2
            # ⚠️ 这个环境里 SetCursorPos 会间歇性被拒（沙箱限制），
            #    单次失败不代表功能有问题，重试到真的停在菜单栏那条上为止。
            moved = False
            for _ in range(15):
                try:
                    user32.SetCursorPos(cx, cy)
                except Exception:
                    pass
                pump(0.06)
                if dodge._mouse_on_edge():
                    moved = True
                    break
            if not moved:
                note("本环境的沙箱拒绝了移动光标（SetCursorPos 反复失败），"
                     "「遮挡时鼠标碰底部不弹」无法验证",
                     f"QCursor={dock_dodge.QCursor.pos()} 目标物理=({cx},{cy})")
            else:
                pump(1.2)                    # 远超 EDGE_DWELL
                settle()
                check("窗口压着菜单栏时，鼠标停在屏幕底部 → 菜单栏不弹",
                      not dock.isVisible(),
                      f"visible={dock.isVisible()}  "
                      f"peek={max(0.0, dodge._peek_until - time.monotonic()):.2f}  "
                      f"onDesktop={dodge._on_desktop()}  "
                      f"occluded={dodge._occluded}")
                check("没有留下唤回保持期", dodge._peek_until == 0.0,
                      f"peek={dodge._peek_until}")
                check("菜单栏没被弹出来，也就不该有残留的点击穿透位",
                      (ex_style() & WS_EX_TRANSPARENT) == 0, hex(ex_style()))
        finally:
            dock_dodge.EDGE_DWELL, dock_dodge.PEEK_HOLD = old_dwell, old_hold
            try:
                user32.SetCursorPos(old_cursor.x, old_cursor.y)
            except Exception:
                pass

        # ------------------------------------------------------------------
        section("7. 关掉遮挡窗口 → 菜单栏自己回来（不需要鼠标去唤）")
        # ------------------------------------------------------------------
        user32.PostMessageW(hwnd, 0x0010, 0, 0)       # WM_CLOSE
        ok = wait_for(lambda: dock.isVisible(), 4.0, "关闭后显示")
        check("关掉遮挡的窗口 → 菜单栏回来", ok)
        settle()
        check("反复显隐之后位置依然没有漂移", dock.pos() == home_pos,
              f"{dock.pos()} vs {home_pos}")

        try:
            probe.wait(timeout=6)
        except Exception:
            kill_probe(probe)
        check("探针进程已经退出", probe.poll() is not None)

        # ------------------------------------------------------------------
        section("8. 关掉新开关 → 恢复「只有全屏才让开」")
        # ------------------------------------------------------------------
        cfg.set("dock_avoid_overlap", False)
        probe2, hwnd2 = spawn_probe(60, 60, 420, 300)
        if hwnd2:
            left, top, right, bottom = dock_rect
            user32.SetWindowPos(hwnd2, 0, left - 120, top - 220,
                                (right - left) + 260, (bottom - top) + 300,
                                SWP_NOZORDER | SWP_NOACTIVATE)
            pump(1.4)
            settle()
            check("关掉「窗口遮挡时自动隐藏」后，普通窗口压上来菜单栏不再躲",
                  dock.isVisible())
            check("但「遮挡中」这个事实仍然被正确识别",
                  dodge._occluded is True)
            user32.PostMessageW(hwnd2, 0x0010, 0, 0)
        kill_probe(probe2)
        cfg.set("dock_avoid_overlap", True)

    finally:
        # 收尾：还原环境噪声隔离、关掉探针、还原光标
        if original_fs is not None:
            tray._foreground_is_fullscreen = original_fs
        if saved_excluded is not None:
            dock_dodge.EXCLUDED_CLASSES = saved_excluded
        for proc in probes:
            kill_probe(proc)
        try:
            user32.SetCursorPos(old_cursor.x, old_cursor.y)
        except Exception:
            pass
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
