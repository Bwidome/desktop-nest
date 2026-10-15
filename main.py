#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 入口
========================
直接运行：python main.py

默认后台驻留系统托盘；加 --silent 则不弹任何窗口（开机自启用）。
加 --selftest 只做启动自检、立刻退出（用来排查"双击没反应"）。
加 --restore  只做应急还原、立刻退出（把收纳内容搬回桌面，不留任何窗口）。
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

    @step("单实例闸可用")
    def _5b():
        import single_instance

        guard = single_instance.SingleInstance()
        if not guard.try_acquire():
            # 自检会构造一个 TrayApp 再关掉它，而 TrayApp 的构造 / 关闭
            # 会**把桌面收进来再放回去**。正在跑的那个实例干的是同一件事，
            # 两边一起动手就是抢文件——所以这里必须直接停下，
            # 而不是"带病继续跑完"。
            raise RuntimeError(
                "已经有「桌面收纳」在运行。\n"
                "        自检会构造并关闭一个实例（退出时会还原桌面），\n"
                "        和正在跑的那个抢同一批桌面文件，所以这里主动停下。\n"
                "        请先从托盘退出那个实例，再跑自检。")
        keepalive["guard"] = guard
        return single_instance.describe()

    @step("构造 TrayApp")
    def _6():
        # 上一步没拿到单实例锁就**别往下走**：`step` 会吞掉异常继续跑，
        # 而"构造 TrayApp"正是会动桌面文件的那一步。
        if keepalive.get("guard") is None:
            raise RuntimeError("单实例闸没通过，跳过（避免和正在运行的实例抢桌面文件）")
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


def _restore() -> int:
    """把所有收纳内容搬回桌面，然后用弹窗汇报结果。

    对应 `DesktopNest.exe --restore`。

    为什么要做成入口参数而不是给一个 .bat：这是**应急通道**。
    打包发行版的目标机器上不一定有 Python，一个依赖 python.exe 的
    `还原桌面.bat` 在最需要它的时候恰恰用不了。
    做进 exe 里就永远可用 —— 双击不了主程序时，命令行一条命令就能把
    桌面还回来。
    """
    import config

    try:
        from qt_compat import QApplication, QMessageBox
    except Exception:
        return 1

    app = QApplication.instance() or QApplication([sys.argv[0]])

    try:
        import nest
        import restore_desktop as rd

        user_desktop = config.get_desktop_dir()
        root = rd.find_nest_with_content()
        if root is None:
            QMessageBox.information(
                None, "桌面还原",
                "没有找到需要还原的内容 —— 桌面应该已经是完整的。")
            return 0
        # 明确指向真正存着东西的那一份（可能不是 nest_root() 选中的那个）
        nest.nest_root = lambda: root
        store = nest.desktop_store()
        items = sorted(p.name for p in store.iterdir())
        result = nest.restore_to_desktop(user_desktop)

        lines = [f"已还原 {result.moved} 项到桌面。", ""]
        if result.skipped:
            lines.append("说明：")
            lines += [f"· {n}：{r}" for n, r in result.skipped[:6]]
        if result.failed:
            lines.append("")
            lines.append("以下未能还原（文件仍在收纳目录里，没有丢）：")
            lines += [f"· {n}：{r}" for n, r in result.failed[:6]]
        lines.append("")
        lines.append(f"收纳目录：{root}")
        text = "\n".join(lines)
        if result.failed:
            QMessageBox.warning(None, "桌面还原", text)
        else:
            QMessageBox.information(None, "桌面还原", text)
        return 0 if not result.failed else 1
    except Exception:
        detail = traceback.format_exc()
        try:
            config.log("命令行还原失败：\n" + detail)
        except Exception:
            pass
        try:
            QMessageBox.critical(
                None, "桌面还原失败",
                f"还原时出错：\n\n{detail.strip().splitlines()[-1]}\n\n"
                f"文件仍在收纳目录里，没有丢。\n"
                f"详情见日志：\n{config.log_path()}")
        except Exception:
            pass
        return 1


def main() -> int:
    _enable_crash_log()

    argv = sys.argv[1:]
    if "--selftest" in argv:
        return _selftest()
    # 应急还原：不启动托盘、不碰桌面，直接把收纳内容搬回去
    if "--restore" in argv:
        return _restore()

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
