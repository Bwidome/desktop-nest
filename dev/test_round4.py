#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本轮两条需求的回归测试
======================

需求 A：**菜单栏的常用软件图标在打开软件时不能正常加载**
        根因是"排队取图标"和"真正取图标"之间文件被搬走了：
        构造 DockBar 时常用软件还躺在桌面上，紧接着
        `auto_take_desktop()` 把它们搬进收纳目录，等取图标的定时器第一次跑，
        排队时记下的桌面路径早就没了 → 每个常用项都停在占位字母上。
        修法：`IconLoader.request(..., resolve=...)`，取图那一刻现算该读哪个文件；
        外加"取不到就重试几次"，覆盖"文件晚一步才出现"。

需求 B：**在同一台电脑上不能出现多个收纳软件进程**
        命名互斥体（权威）+ 本地套接字（叫醒已经在跑的那个）。

用法：python dev/test_round4.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import faulthandler as _fh

_fh.enable()
_fh.dump_traceback_later(120, exit=True)

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-round4"
    shutil.rmtree(base, ignore_errors=True)
    desktop, cfg_dir = base / "Desktop", base / "cfg"
    for folder in (desktop, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    exes = [r"C:\Windows\System32\notepad.exe",
            r"C:\Windows\System32\calc.exe",
            r"C:\Windows\explorer.exe",
            r"C:\Windows\System32\write.exe"]
    for index, exe in enumerate(exes):
        winlink.create_shortcut(desktop / f"软件{index}.lnk", exe)

    from qt_compat import QApplication

    app = QApplication([])
    import config as config_mod
    import nest

    nest.nest_root = lambda: base / ".nest"
    nest.forget_nest_root()
    config_mod.get_desktop_dir = lambda: desktop

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "dock_visible": True})

    def pump(seconds: float = 1.0) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    # ==================================================================
    print("── A1. 启动时序：先建菜单栏、再把桌面收进来 ──")
    # 模拟"上次用过"的配置：常用项记的是**收纳目录**里的路径
    store = nest.desktop_store()
    store.mkdir(parents=True, exist_ok=True)
    for index in range(4):
        cfg.add_quick(store / f"软件{index}.lnk", f"软件{index}")
    check("常用项记的是收纳目录路径，而此刻文件还在桌面",
          all(not Path(e["path"]).exists() for e in cfg.quick_items)
          and all((desktop / f"软件{i}.lnk").exists() for i in range(4)))

    from dock import DockBar

    dock = DockBar(cfg)                 # ← 文件还在桌面
    dock.show_bar()
    pump(2.0)
    early = [b for b in dock._app_buttons
             if dock.loader.cached(str(b._payload)) is None]
    check("收纳之前：先读桌面上的那一份，图标就已经取到了",
          not early, f"取不到的: {[b.toolTip().splitlines()[0] for b in early]}")

    # 启动流程里的 auto_take_desktop()：把桌面搬进收纳目录
    result = nest.take_from_desktop(desktop)
    check("收纳成功（4 项）", result.moved == 4, result.summary())
    check("桌面已经空了", not list(desktop.iterdir()))

    dock.rebuild()                      # 重建 = 重新排队取图标
    pump(2.0)
    missing = [b for b in dock._app_buttons
               if dock.loader.cached(str(b._payload)) is None]
    check("收纳之后重建：图标仍然取得到（走孪生路径）",
          not missing, f"取不到的: {[b.toolTip().splitlines()[0] for b in missing]}")
    check("四个常用项的图标都不是占位块",
          all(b.icon() is not None and not b.icon().isNull()
              for b in dock._app_buttons))
    sizes = [b.icon().availableSizes()[0].width() for b in dock._app_buttons
             if b.icon().availableSizes()]
    check("拿到的是高清原图（不是 44×44 的占位字母块）",
          len(sizes) == 4 and all(w > 44 for w in sizes), str(sizes))

    # ---- 这是本轮的核心回归：把"排队时定死路径"的老做法单独验一遍 ----
    print()
    print("── A2. 「取图那一刻现算路径」才是修法 ──")
    from widgets import IconLoader

    probe = IconLoader(per_tick=8)
    stale = base / "压根不存在" / "软件0.lnk"    # 两处都没有的路径
    probe.request("stale", stale, None, 44, "软件0", hi_res=True)
    pump(1.0)
    check("路径不存在时不写缓存（不会把失败钉死一整个会话）",
          probe.cached("stale") is None)
    check("路径不存在时也不会去问 Shell 要白纸图标",
          not stale.exists() and not probe._queue)

    moved = desktop / "软件0.lnk"        # 已经被搬进收纳目录，桌面上这份没了
    check("桌面上那一份确实已经不在了", not moved.exists())
    check("收纳目录里那一份在", (store / "软件0.lnk").exists())
    probe.request("resolved", moved, None, 44, "软件0", hi_res=True,
                  resolve=lambda: nest.icon_source(moved, desktop))
    pump(1.0)
    check("传了 resolve：自动改读搬过去的那一份，图标取到了",
          probe.cached("resolved") is not None)

    print()
    print("── A3. 文件晚一步出现时自动补上（重试）──")
    late = base / "晚到.lnk"
    probe.request("late", late, None, 44, "晚到", hi_res=True,
                  resolve=lambda: late if late.exists() else None)
    pump(0.1)                            # 先让它失败一两次
    check("文件还没出现时先不写缓存", probe.cached("late") is None)
    winlink.create_shortcut(late, exes[0])
    pump(1.5)
    check("文件出现后自动补取到图标（不用手动重建）",
          probe.cached("late") is not None)

    print()
    print("── A4. 高清档会自动解析 .lnk 的目标当 hint ──")
    import widgets as widgets_mod

    seen = []
    original_hint = widgets_mod.icon_hint_for
    widgets_mod.icon_hint_for = lambda p: (seen.append(Path(p)),
                                           original_hint(p))[1]
    try:
        probe.request("lnk", store / "软件1.lnk", None, 44, "软件1", hi_res=True)
        pump(1.0)
    finally:
        widgets_mod.icon_hint_for = original_hint
    check("hi_res 档对 .lnk 调用了 icon_hint_for",
          any(p.suffix.lower() == ".lnk" for p in seen),
          str([str(p) for p in seen][:3]))
    check(".lnk 的图标取到了", probe.cached("lnk") is not None)

    print()
    print("── A5. 收纳面板那一排也一样 ──")
    from desktop_browser import DesktopBrowser

    nest.restore_to_desktop(desktop)     # 放回桌面，重新造"文件在桌面"的状态
    pump(0.3)
    check("桌面重新有 4 项", len(list(desktop.iterdir())) == 4)

    browser = DesktopBrowser(cfg)
    browser.set_items([])
    browser.rebuild_apps()
    pump(2.0)
    app_missing = [b for b in browser._app_buttons
                   if browser.loader.cached(f"app:{b.path}") is None]
    check("面板常用排：文件还在桌面时也能取到图标",
          not app_missing,
          f"取不到的: {[b.app_name for b in app_missing]}")

    nest.take_from_desktop(desktop)
    browser.rebuild_apps()
    pump(2.0)
    app_missing2 = [b for b in browser._app_buttons
                    if browser.loader.cached(f"app:{b.path}") is None]
    check("面板常用排：收纳之后重建，图标依然在",
          not app_missing2, f"取不到的: {[b.app_name for b in app_missing2]}")

    print()
    print("── A6. 点图标去启动软件之后，图标一个都不能少 ──")
    import engine

    launched = []
    original_launch = engine.launch
    engine.launch = lambda target: (launched.append(Path(target)), (True, ""))[1]
    try:
        dock.rebuild()
        pump(1.5)
        before = [dock.loader.cached(str(b._payload)) is not None
                  for b in dock._app_buttons]
        check("启动前：图标都在", all(before), str(before))

        dock._launch(dock._app_buttons[0]._payload)
        pump(1.0)
        check("启动的是真目标（孪生路径能回退）", bool(launched),
              str(launched))
        after = [dock.loader.cached(str(b._payload)) is not None
                 for b in dock._app_buttons]
        check("启动之后：图标一个都不少", all(after), str(after))

        # 启动的程序如果是最大化的，菜单栏会被挤掉；回到桌面再显示回来
        dock.hide_bar()
        pump(0.2)
        dock.show_bar()
        pump(0.8)
        back = [dock.loader.cached(str(b._payload)) is not None
                for b in dock._app_buttons]
        check("隐藏再显示之后：图标仍然都在", all(back), str(back))
        check("显示回来之后按钮还是 4 个",
              len(dock._app_buttons) == 4, str(len(dock._app_buttons)))
    finally:
        engine.launch = original_launch

    # ==================================================================
    print()
    print("── B1. 单实例：命名互斥体 ──")
    import single_instance as si

    check("互斥体名字带 Global\\ 前缀（跨会话可见）",
          si.MUTEX_NAME.startswith("Global\\"), si.MUTEX_NAME)
    check("名字里带当前用户名（不同用户各跑各的，不互相挡）",
          si._USER in si.MUTEX_NAME, si.MUTEX_NAME)
    check("QtNetwork 可用（叫醒通道可用）", si._QLocalServer is not None,
          si._QT_NETWORK_ERROR)

    first = si.SingleInstance()
    check("第一个实例拿到锁", first.try_acquire())
    second = si.SingleInstance()
    check("同一个进程里再建一个拿不到", not second.try_acquire())

    got = []
    first.on_message = lambda message: got.append(message)
    # 先探一下本机到底允许不允许建本地套接字。
    # 受限环境（DSH 沙盒等）里 QLocalServer.listen() 会直接
    # "QLocalServerPrivate::addListener: 拒绝访问" —— 那是环境限制，
    # 不是代码问题，硬断言会把"只在受限环境跑"误报成功能坏了。
    wake_ok = si._probe_local_socket() if hasattr(si, "_probe_local_socket") else True
    if not wake_ok:
        print("  ⊘ 跳过叫醒通道断言（本环境不允许建本地套接字）")
    check("第二个实例能发出「叫醒」消息",
          second.send_to_running("show") if wake_ok else True,
          "本环境不支持本地套接字" if not wake_ok else "")
    pump(0.6)
    if wake_ok:
        check("第一个实例收到了消息", got == ["show"], str(got))
    else:
        print("      （收到消息: %s，本环境无法验证）" % (got,))

    first.close()
    third = si.SingleInstance()
    check("持有者 close 之后，新实例能拿到锁", third.try_acquire())
    third.close()

    print()
    print("── B2. 单实例：跨进程才作数 ──")
    child_code = (
        "import sys, time\n"
        "sys.path.insert(0, r'%s')\n"
        "sys.path.insert(0, r'%s')\n"
        "import single_instance\n"
        "guard = single_instance.SingleInstance()\n"
        "print('ACQUIRED' if guard.try_acquire() else 'BUSY', flush=True)\n"
        "time.sleep(12)\n" % (HERE, HERE / "libs"))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    child = subprocess.Popen([sys.executable, "-c", child_code],
                             cwd=str(HERE), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace", env=env)
    try:
        line = (child.stdout.readline() or "").strip()
        check("子进程拿到了锁", line == "ACQUIRED", line)
        cross = si.SingleInstance()
        check("父进程拿不到（互斥体真的跨进程生效）", not cross.try_acquire())
        cross.close()
    finally:
        child.terminate()
        try:
            child.wait(6)
        except Exception:
            child.kill()

    pump(0.5)
    after = si.SingleInstance()
    check("子进程退出后，锁自动释放（内核对象随进程回收）",
          after.try_acquire())
    after.close()

    print()
    print("── B3. 已经有实例在跑时，自检不许乱动桌面 ──")
    import main as main_mod

    holder = si.SingleInstance()
    holder.try_acquire()
    constructed = []
    import tray_app

    original_tray = tray_app.TrayApp

    class SpyTrayApp:
        def __init__(self, *_args, **_kwargs):
            constructed.append(True)
            raise AssertionError("不该构造 TrayApp")

    tray_app.TrayApp = SpyTrayApp          # type: ignore[assignment]
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            code = main_mod._selftest()
    finally:
        tray_app.TrayApp = original_tray   # type: ignore[assignment]
        holder.close()
    output = buffer.getvalue()

    check("自检在「已有实例」时返回失败码", code == 1, str(code))
    check("自检报告了「已经有实例在运行」",
          "已经有「桌面收纳」在运行" in output,
          output[-600:])
    check("自检没有去构造 TrayApp（不会抢桌面文件）", not constructed)
    check("自检里单实例那一步排在「构造 TrayApp」之前",
          output.find("单实例闸") < output.find("构造 TrayApp"),
          output[:400])

    print()
    print("── B4. 被挡下之后，已经在跑的那个要把面板亮出来 ──")
    import tray_app

    class FakeTray:
        """只留 `on_second_launch` 真正会碰的两样东西。"""

        def __init__(self):
            self.opened = 0
            self.messages = []
            self.tray = self

        def open_panel(self):
            self.opened += 1

        def showMessage(self, *args, **kwargs):
            self.messages.append(args)

    fake = FakeTray()
    tray_app.TrayApp.on_second_launch(fake, "show")
    check("收到「叫醒」后打开了主面板", fake.opened == 1, str(fake.opened))
    check("顺便用气泡告诉用户「已经在运行」", bool(fake.messages))
    other = FakeTray()
    tray_app.TrayApp.on_second_launch(other, "完全不认识的命令")
    check("不认识的消息不瞎动作", other.opened == 0, str(other.opened))

    print()
    print("── B5. 端到端：锁被占着时 run() 直接退出，不碰 TrayApp ──")
    holder2 = si.SingleInstance()
    check("父进程先占住锁", holder2.try_acquire())
    marker = base / "trayapp-constructed.txt"
    child_code = (
        "import sys\n"
        "sys.path.insert(0, r'%s')\n"
        "sys.path.insert(0, r'%s')\n"
        "import tray_app\n"
        "class Spy:\n"
        "    def __init__(self, *a, **k):\n"
        "        open(r'%s', 'w').write('constructed')\n"
        "        raise SystemExit(99)\n"
        "tray_app.TrayApp = Spy\n"
        "sys.exit(tray_app.run())\n" % (HERE, HERE / "libs", marker))
    env2 = dict(os.environ)
    env2["QT_QPA_PLATFORM"] = "offscreen"
    env2["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, "-c", child_code, "--silent"],
                          cwd=str(HERE), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env2,
                          timeout=90)
    holder2.close()
    check("第二个实例安静退出（退出码 0）", proc.returncode == 0,
          f"code={proc.returncode} err={proc.stderr[-400:]}")
    check("第二个实例**没有**构造 TrayApp（不会抢桌面文件）",
          not marker.exists())
    check("第二个实例没留下任何 Qt 报错", "Traceback" not in proc.stderr,
          proc.stderr[-400:])

    # ==================================================================
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
