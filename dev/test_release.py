#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发行版打包的自检：**冻结（frozen）环境下哪些地方必须换写法**
============================================================

背景：这个项目平时是 `python main.py` 跑起来的，但发行版是 PyInstaller
打出来的 exe —— 两者有几处**必须不一样**，写错了不会崩，而是"静默失效"：

| 位置 | 脚本版 | 冻结版 | 写错的后果 |
| --- | --- | --- | --- |
| `config.autostart_command()` | `pythonw.exe main.py --silent` | `DesktopNest.exe --silent` | 开机自启打开了但**开机后什么也没发生**（exe 目录里没有 main.py） |
| `config.default_project_dir()` | `__file__` 所在目录 | **exe 所在目录** | 配置/图标缓存每次启动从零开始，还在 %TEMP% 里堆 _MEI 目录 |

所以这套用例做两件事：

1. 把 `sys.frozen` / `sys.executable` 换掉，验证两种环境下**各自**产出正确的
   自启命令与程序目录；
2. 把 `桌面收纳.spec` 当 AST 读一遍，钉住几条"改了就出问题"的打包设置
   （`hiddenimports` 里的 `PyQt6.QtNetwork`、`upx=False`、`console=False`、
   `datas` 不塞 `libs/`）。

用法：python dev/test_release.py
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n── {title} ──")


# --------------------------------------------------------------------------
# 冻结环境的开关
# --------------------------------------------------------------------------
class Frozen:
    """临时把当前进程伪装成 PyInstaller 打出来的 exe。"""

    def __init__(self, exe: Path):
        self.exe = exe
        self._had = hasattr(sys, "frozen")
        self._old_frozen = getattr(sys, "frozen", None)
        self._old_exe = sys.executable

    def __enter__(self):
        sys.frozen = True                      # type: ignore[attr-defined]
        sys.executable = str(self.exe)
        return self

    def __exit__(self, *exc):
        if self._had:
            sys.frozen = self._old_frozen      # type: ignore[attr-defined]
        else:
            try:
                del sys.frozen                 # type: ignore[attr-defined]
            except AttributeError:
                pass
        sys.executable = self._old_exe
        return False


def spec_calls() -> "dict[str, ast.Call]":
    """把 桌面收纳.spec 里的 Analysis / EXE / COLLECT 调用抽出来。"""
    tree = ast.parse((HERE / "桌面收纳.spec").read_text(encoding="utf-8"))
    found: "dict[str, ast.Call]" = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("Analysis", "EXE", "COLLECT", "PYZ"):
                found[node.func.id] = node
    return found


def kw(call: ast.Call, name: str):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def as_list(node) -> list:
    """把 AST 里的 list / tuple 字面量取成 python list（取不出来返回空）。"""
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for item in node.elts:
            try:
                out.append(ast.literal_eval(item))
            except Exception:
                out.append(None)
        return out
    return []


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-release"
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)

    import config

    fake_exe = base / "DesktopNest.exe"
    fake_exe.write_bytes(b"MZ")            # 只需要"存在"这个事实

    # ------------------------------------------------------------------
    section("A. 冻结版：开机自启要直接跑 exe，不能再写「解释器 + main.py」")

    with Frozen(fake_exe):
        target, prefix = config.autostart_target()
        check("autostart_target 给的是 exe 自己",
              Path(target) == fake_exe, target)
        check("冻结版没有附加参数前缀（不需要再传脚本路径）",
              prefix == "", repr(prefix))

        cmd = config.autostart_command()
        check("自启命令 = exe + --silent",
              cmd == f'"{fake_exe}" --silent', cmd)
        check("命令里**不出现** main.py（发行版目录里根本没有这个文件）",
              "main.py" not in cmd, cmd)
        check("命令里**不出现** pythonw.exe / python.exe",
              "python" not in cmd.lower(), cmd)
        check("命令以 --silent 收尾（开机自启不弹窗）",
              cmd.endswith("--silent"), cmd)

    # ------------------------------------------------------------------
    section("B. 脚本版：行为必须和以前一模一样（别把开发环境改坏）")

    target, prefix = config.autostart_target()
    cmd = config.autostart_command()
    check("autostart_target 给的还是解释器（不是 exe 自身）",
          Path(target) != fake_exe, target)
    check("解释器名里带 python（pythonw 优先）",
          "python" in Path(target).name.lower(), target)
    check("附加参数里带 main.py 的绝对路径",
          "main.py" in prefix, prefix)
    check("完整命令仍以 --silent 收尾",
          cmd.endswith("--silent"), cmd)
    check("脚本版命令里出现 main.py",
          "main.py" in cmd, cmd)

    # ------------------------------------------------------------------
    section("C. 冻结版：写「启动」文件夹快捷方式时也要指向 exe")

    recorded: "dict[str, str]" = {}

    def fake_create(link, target, arguments="", icon_path="", working_dir=""):
        recorded.update(link=str(link), target=str(target),
                        arguments=arguments, icon=icon_path,
                        cwd=str(working_dir))
        Path(link).parent.mkdir(parents=True, exist_ok=True)
        Path(link).write_bytes(b"")       # 让它 exists() 为真
        return True, ""

    real_create = config.winlink.create_shortcut
    real_link = config._startup_shortcut
    config.winlink.create_shortcut = fake_create
    config._startup_shortcut = lambda: base / "Startup" / "桌面收纳.lnk"
    try:
        with Frozen(fake_exe):
            ok = config._write_startup_shortcut()
        check("写快捷方式返回成功", bool(ok), str(ok))
        check("快捷方式指向 exe 自己",
              Path(recorded.get("target", "")) == fake_exe, recorded.get("target"))
        check("参数只有 --silent（没有多余的脚本路径）",
              recorded.get("arguments") == "--silent", recorded.get("arguments"))
        check("图标取自同一个 exe",
              Path(recorded.get("icon", "")) == fake_exe, recorded.get("icon"))
        check("工作目录 = exe 所在目录",
              Path(recorded.get("cwd", "")) == fake_exe.parent, recorded.get("cwd"))
    finally:
        config.winlink.create_shortcut = real_create
        config._startup_shortcut = real_link

    # ------------------------------------------------------------------
    section("D. 程序目录：冻结时必须是 exe 所在目录（不是 %TEMP%\\_MEIxxxx）")

    with Frozen(fake_exe):
        check("default_project_dir() = exe 的父目录",
              config.default_project_dir() == fake_exe.parent.resolve(),
              str(config.default_project_dir()))

    check("非冻结时 = 源码所在目录（也就是项目根）",
          config.default_project_dir() == HERE, str(config.default_project_dir()))

    # ------------------------------------------------------------------
    section("E. 打包设置：改了就出问题的那几条（直接读 spec 的 AST）")

    calls = spec_calls()
    check("spec 里能找到 Analysis / EXE / COLLECT",
          {"Analysis", "EXE", "COLLECT"} <= set(calls), str(sorted(calls)))

    analysis = calls.get("Analysis")
    exe = calls.get("EXE")

    hidden = as_list(kw(analysis, "hiddenimports")) if analysis else []
    check("hiddenimports 里有 PyQt6.QtNetwork",
          "PyQt6.QtNetwork" in hidden, str(hidden))
    check("datas 是空的（不塞 libs/，否则成品多一整套重复 Qt6）",
          as_list(kw(analysis, "datas")) == [],
          str(kw(analysis, "datas")))
    excludes = as_list(kw(analysis, "excludes"))
    check("excludes 剔掉了 tkinter",
          "tkinter" in excludes, str(excludes[:6]))
    check("excludes 剔掉了 WebEngine 这类大件",
          "PyQt6.QtWebEngineCore" in excludes, str(excludes[:6]))

    if exe is not None:
        check("upx=False（压缩过的 Qt DLL 容易被杀软误报）",
              kw(exe, "upx") is not None
              and ast.literal_eval(kw(exe, "upx")) is False)
        check("console=False（发行版不弹黑窗口）",
              kw(exe, "console") is not None
              and ast.literal_eval(kw(exe, "console")) is False)
        check("exclude_binaries=True（onedir 而不是 onefile）",
              kw(exe, "exclude_binaries") is not None
              and ast.literal_eval(kw(exe, "exclude_binaries")) is True)
    else:
        check("spec 里能找到 EXE 调用", False)

    # ------------------------------------------------------------------
    section("E2. 新增顶层模块必须能被 PyInstaller 静态分析到")

    # PyInstaller 是从 main.py 出发做**静态** import 分析的：放在
    # `try/except ImportError` 里、或者用 importlib 动态导入的模块会被漏掉，
    # 打包出来运行到那一步才 `ModuleNotFoundError`（而且只在发行版复现）。
    # `springs.py` 是 Dock 拖拽排序用的弹簧积分器，必须走最普通的模块级 import。
    def module_level_imports(path: "Path") -> "set[str]":
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: "set[str]" = set()
        for node in tree.body:                 # 只看模块级语句，不递归进函数
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
        return found

    dock_imports = module_level_imports(HERE / "dock.py")
    check("dock.py 在**模块级**导入了 springs（不是藏在 try/except 里）",
          "springs" in dock_imports, str(sorted(dock_imports)))
    check("springs.py 在项目根目录（和 dock.py 同级，静态分析找得到）",
          (HERE / "springs.py").is_file())
    spring_imports = module_level_imports(HERE / "springs.py")
    check("springs.py 只依赖标准库（冻结时不用额外 hook / 隐藏导入）",
          spring_imports <= {"math", "__future__"}, str(sorted(spring_imports)))

    # ------------------------------------------------------------------
    section("F. 发行说明模板")

    readme = HERE / "release" / "使用说明.txt"
    check("release/使用说明.txt 存在", readme.is_file(), str(readme))
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        check("写的是 v0.3", "v0.3" in text, "")
        check("讲清了「别只拖 exe，要带上 _internal」",
              "_internal" in text)
        check("讲清了删除是删到回收站、可还原",
              "回收站" in text and "还原" in text)
        check("讲清了底部按钮随选中项变（加为常用 / 移出常用）",
              "加为常用" in text and "移出常用" in text)
        check("讲清了长按拖动排序（弹簧让位）",
              "排序" in text and "让位" in text)
        check("给了 --selftest 与 --restore 两条应急命令",
              "--selftest" in text and "--restore" in text)

    # ------------------------------------------------------------------
    section("G. 打包脚本")

    script = HERE / "dev" / "make_release.py"
    check("dev/make_release.py 存在", script.is_file(), str(script))
    if script.is_file():
        src = script.read_text(encoding="utf-8")
        check("发行版 exe 统一叫 DesktopNest.exe",
              'EXE_TO = "DesktopNest.exe"' in src)
        check("压缩时用的是「目录内相对路径」（解压即用，不多一层目录）",
              "relative_to(COLLECT_DIR)" in src, "")
        check("构建输出到 .tmp\\（不碰 dist\\，也就不会触发批量删除）",
              '"release-build"' in src and "make_room" in src)
        check("会把 使用说明.txt 一起放进压缩包",
              "README_SRC" in src and "shutil.copy2" in src)

        # 构建目录靠"改名让位"腾地方，全程不删东西 ——
        # 否则在带"安全删除"拦截的环境里会被卡住（踩过）。
        banned = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("rmtree", "remove", "unlink", "rmdir"):
                    banned.append(node.func.attr)
        check("打包脚本里一个删除调用都没有（只改名、不删除）",
              not banned, str(sorted(set(banned))))

    # ------------------------------------------------------------------
    section("H. 已生成的压缩包结构（没有就跳过）")

    zips = sorted(HERE.glob("desktop-nest-release-*.zip"))
    if not zips:
        print("  (还没生成压缩包，跳过 H 节)")
    else:
        import zipfile

        newest = max(zips, key=lambda p: p.stat().st_mtime)
        with zipfile.ZipFile(newest) as zf:
            names = zf.namelist()
        tops = {n.split("/")[0] for n in names}
        check(f"{newest.name}：根目录就是 DesktopNest.exe（没有多一层文件夹）",
              "DesktopNest.exe" in tops, str(sorted(tops)[:5]))
        check(f"{newest.name}：带上了 _internal/",
              "_internal" in tops, str(sorted(tops)[:5]))
        check(f"{newest.name}：带上了 使用说明.txt",
              "使用说明.txt" in tops, str(sorted(tops)[:5]))
        check(f"{newest.name}：没有把源码 / 测试 / 缓存打进去",
              not any(n.startswith(("dev/", "release/", ".data/", ".tmp/"))
                      for n in names),
              str([n for n in names
                   if n.startswith(("dev/", "release/", ".data/", ".tmp/"))][:5]))
        check(f"{newest.name}：条目数在合理范围（>50）",
              len(names) > 50, str(len(names)))

    total = len(PASS) + len(FAIL)
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项（共 {total}）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
