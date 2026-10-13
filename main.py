#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 入口
========================
直接运行：python main.py

默认后台驻留系统托盘；加 --silent 则不弹任何窗口（开机自启用）。
加 --selftest 只做启动自检、立刻退出（用来排查"双击没反应"）。
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _enable_crash_log() -> None:
    """把原生崩溃也记下来。

    Qt / Windows 有时不是"抛 Python 异常"，而是直接让进程 abort
    （现象就是双击后毫无反应，什么提示都没有）。这种崩溃 Python 的
    try/except 抓不到，必须用 faulthandler 才能把调用栈落到文件里。
    """
    try:
        import faulthandler

        target = None
        try:
            import config

            target = Path(config.log_path()).with_name("crash.log")
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            target = HERE / "crash.log"
        handle = open(target, "a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=handle, all_threads=True)
        handle.write(f"\n=== 启动 {__import__('datetime').datetime.now()} ===\n")
        handle.flush()
    except Exception:
        pass


def _selftest() -> int:
    """启动自检：把关键环节逐个跑一遍并打印结果，最后立刻退出。

    用途：打包成 exe 后如果"双击没反应"，用
        `桌面收纳.exe --selftest`
    就能看到究竟卡在哪一步，而不用猜。
    """
    import os

    # Windows 控制台默认是 GBK，直接打印 ✓ 这类字符会抛 UnicodeEncodeError
    # ——自检反而自己崩了就没意义了。这里把输出流切成 UTF-8，
    # 并且允许无法编码的字符降级显示。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 60)
    print("  桌面收纳 · 启动自检")
    print("=" * 60)
    print(f"  解释器   : {sys.version.split()[0]}")
    print(f"  冻结打包 : {getattr(sys, 'frozen', False)}")
    print(f"  可执行   : {sys.executable}")
    print(f"  工作目录 : {os.getcwd()}")
    print()

    steps = []
    # QApplication 必须一直持有引用：局部变量一被回收，Qt 就会在后续
    # 创建 QPixmap 时报 "Must construct a QGuiApplication before a QPixmap"
    # 然后直接 abort（自检脚本自己反而成了崩溃现场）。
    keepalive = {}

    def step(label):
        def wrapper(fn):
            print(f"  · {label} ... ", end="", flush=True)
            try:
                value = fn()
                print("OK" + (f"  ({value})" if value else ""))
                steps.append((label, True, ""))
            except BaseException as exc:  # noqa: BLE001
                print(f"失败: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                steps.append((label, False, f"{type(exc).__name__}: {exc}"))
            return fn
        return wrapper

    @step("导入 config")
    def _1():
        import config
        return f"日志 {config.log_path()}"

    @step("导入 qt_compat")
    def _2():
        import qt_compat
        return f"后端 {qt_compat.BACKEND or '（没找到 Qt！）'}"

    @step("创建 QApplication")
    def _3():
        from qt_compat import QApplication, QLibraryInfo

        app = QApplication.instance() or QApplication([])
        keepalive["app"] = app          # 关键：别让它被回收
        return (f"平台 {app.platformName()} · "
                f"插件目录 {QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)}")

    @step("导入 tray_app")
    def _4():
        import tray_app  # noqa: F401
        return ""

    @step("构造 Palette / 图标")
    def _5():
        from widgets import app_icon

        icon = app_icon()
        return f"{len(icon.availableSizes())} 种尺寸"

    @step("构造 TrayApp")
    def _6():
        import config
        import tray_app

        window = tray_app.TrayApp(config.Config(), silent=True)
        keepalive["window"] = window
        # 等扫描线程收尾，然后按正常流程关掉。
        # 直接让带 QThread 的对象被回收会触发 "QThread: Destroyed while thread
        # is still running" 而 abort——自检自己先崩了就没意义了。
        deadline = time.time() + 20
        scan = getattr(window, "_scan", None)
        while scan is not None and scan.isRunning() and time.time() < deadline:
            keepalive["app"].processEvents()
            time.sleep(0.05)
        window._quitting = True
        window.shutdown()
        for _ in range(20):
            keepalive["app"].processEvents()
            time.sleep(0.02)
        return "已构造并正常关闭"

    @step("收纳目录可写")
    def _7():
        import nest

        nest.ensure_dirs()
        return str(nest.desktop_store())

    print()
    failed = [s for s in steps if not s[1]]
    if failed:
        print(f"  ✗ {len(failed)} 个环节失败：")
        for label, _ok, reason in failed:
            print(f"      {label} —— {reason}")
        print()
        print("  请把上面这段输出发给我，就能定位问题。")
        return 1
    print("  ✓ 全部环节通过。如果双击仍然没反应，")
    print("    多半是被杀毒软件拦了，或缺少 _internal 目录。")
    return 0


def main() -> int:
    _enable_crash_log()

    if "--selftest" in sys.argv:
        return _selftest()

    try:
        import tray_app

        return tray_app.run()
    except SystemExit:
        raise
    except Exception:
        # 出问题也要留下线索，并且给用户一个能看懂的提示
        detail = traceback.format_exc()
        try:
            import config

            config.log("启动失败：\n" + detail)
        except Exception:
            pass
        print(detail, file=sys.stderr)
        try:
            from qt_compat import require_qt

            require_qt()
            from qt_compat import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "桌面收纳 启动失败",
                                 f"程序启动时出错：\n\n{detail.strip().splitlines()[-1]}\n\n"
                                 f"详细信息已写入日志：\n{config.log_path()}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
