#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键出发行包
============

用法（在项目根目录执行）：

    py -3.14 dev\\make_release.py                    :: 默认 v1.0
    py -3.14 dev\\make_release.py --version v1.1     :: 指定版本号
    py -3.14 dev\\make_release.py --no-build         :: 跳过打包，只重新压缩
    py -3.14 dev\\make_release.py --python <解释器>  :: 手动指定装了 PyInstaller 的解释器

做完这三步：

1. **打包** —— 用 `桌面收纳.spec`（onedir）跑 PyInstaller，
   产物落在 `.tmp\\release-build\\dist\\桌面收纳\\`。
2. **改名 + 补说明** —— 把 `桌面收纳.exe` 改名成 `DesktopNest.exe`，
   再把 `release\\使用说明.txt` 拷进去。
   （改名而不是另写一份：exe 的图标 / 清单 / 版本资源都是内嵌的，
   改名不会丢；用户那边已经建好的快捷方式也还能用。）
3. **压缩** —— 把产物目录**里面的内容**（不是这个目录本身）打进
   `desktop-nest-release-v<版本>.zip`，
   所以解压后根目录直接就是 `DesktopNest.exe` + `_internal` + `使用说明.txt`，
   双击即可用，不需要再进一层目录。

为什么构建到 `.tmp\\` 而不是 `dist\\`
------------------------------------
`dist\\` 里可能躺着上一次的产物，而 PyInstaller 的 `--noconfirm` 会**先把它删掉**。
本机跑在带"安全删除"拦截的环境里时，这种批量删除会被拦下来（要求人工确认），
构建就卡住了。所以这里改成：**从不删除任何东西** ——
每次构建到一个全新目录；如果目标目录已存在，就把它**改名让位**
（`.old1` / `.old2` …），构建完再写进新目录。
`.tmp\\` 整个目录随时可以手动删掉，不影响任何东西。

为什么是 onedir 而不是 onefile：见 `release.spec` 的文件头 ——
本机的 onefile 引导器在受限环境里起不来（进程停在 11 MB 不动），
onedir 则完全正常。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "桌面收纳.spec"
BUILD_ROOT = ROOT / ".tmp" / "release-build"
DIST_ROOT = BUILD_ROOT / "dist"
WORK_ROOT = BUILD_ROOT / "work"
COLLECT_DIR = DIST_ROOT / "桌面收纳"
README_SRC = ROOT / "release" / "使用说明.txt"

EXE_FROM = "桌面收纳.exe"
EXE_TO = "DesktopNest.exe"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(title: str) -> None:
    say()
    say("=" * 66)
    say(f"  {title}")
    say("=" * 66)


# --------------------------------------------------------------------------
# 不删除的"腾地方"：把已存在的目录改名让位
# --------------------------------------------------------------------------
def make_room(target: Path) -> None:
    """确保 target 是一个**全新的空目录**，且全程不删除任何文件。

    已存在就改名成 `target.old1` / `.old2` …（同盘 rename，瞬间完成）。
    """
    if not target.exists():
        target.mkdir(parents=True)
        return
    index = 1
    while True:
        aside = target.with_name(f"{target.name}.old{index}")
        if not aside.exists():
            break
        index += 1
    target.rename(aside)
    say(f"  · 旧目录改名让位：{target.name} → {aside.name}")
    target.mkdir(parents=True)


# --------------------------------------------------------------------------
# 1. 打包
# --------------------------------------------------------------------------
def find_python(explicit: "str | None") -> str:
    """找一个同时装了 PyInstaller 和 PyQt6 的解释器。"""
    if explicit:
        return explicit
    candidates = [
        [sys.executable],
        ["py", "-3.14"],
        ["py", "-3.13"],
        ["py", "-3.12"],
        ["python"],
    ]
    for cmd in candidates:
        try:
            out = subprocess.run(
                cmd + ["-c", "import PyInstaller, PyQt6; print(PyInstaller.__version__)"],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0 and out.stdout.strip():
            return " ".join(cmd)
    raise SystemExit(
        "找不到同时装了 PyInstaller 和 PyQt6 的解释器。\n"
        "先执行：py -3.14 -m pip install pyinstaller PyQt6")


def build(python: str) -> None:
    step("1/3  打包（PyInstaller onedir）")
    make_room(DIST_ROOT)
    make_room(WORK_ROOT)

    cmd = python.split() + [
        "-m", "PyInstaller", str(SPEC),
        "--noconfirm",
        "--distpath", str(DIST_ROOT),
        "--workpath", str(WORK_ROOT),
    ]
    say("  $ " + " ".join(cmd))
    started = time.time()
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"打包失败（退出码 {result.returncode}）")
    say(f"  完成，用时 {time.time() - started:.1f}s")


# --------------------------------------------------------------------------
# 2. 改名 + 补说明
# --------------------------------------------------------------------------
def stage() -> None:
    step("2/3  整理产物（改名 + 补使用说明）")
    if not COLLECT_DIR.is_dir():
        raise SystemExit(f"没找到打包产物目录：{COLLECT_DIR}")

    old = COLLECT_DIR / EXE_FROM
    new = COLLECT_DIR / EXE_TO
    if old.exists():
        old.rename(new)
        say(f"  · {EXE_FROM} → {EXE_TO}")
    elif new.exists():
        say(f"  · {EXE_TO} 已经就位")
    else:
        raise SystemExit(f"产物目录里既没有 {EXE_FROM} 也没有 {EXE_TO}")

    if not README_SRC.is_file():
        raise SystemExit(f"缺少发行说明模板：{README_SRC}")
    shutil.copy2(README_SRC, COLLECT_DIR / README_SRC.name)
    say(f"  · 已放入 {README_SRC.name}")

    internal = COLLECT_DIR / "_internal"
    if not internal.is_dir():
        say("  ⚠️ 没看到 _internal 目录 —— 这个产物可能不是 onedir，请检查 spec")
    else:
        say(f"  · _internal 里有 {sum(1 for _ in internal.rglob('*'))} 个文件")


# --------------------------------------------------------------------------
# 3. 压缩
# --------------------------------------------------------------------------
def zip_up(version: str) -> Path:
    step("3/3  压缩")
    target = ROOT / f"desktop-nest-release-{version}.zip"

    files = sorted(p for p in COLLECT_DIR.rglob("*") if p.is_file())
    say(f"  打包 {len(files)} 个文件 → {target.name}")

    # 用 ZIP_DEFLATED；exe / dll 已经不好压，但 Qt 的 .py / .qm / 文本还能小一截。
    # mode="w" 直接截断重写，不需要先删旧文件。
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            # arcname 用「相对产物目录」的路径 → 解压后根目录直接是内容
            zf.write(path, path.relative_to(COLLECT_DIR).as_posix())

    size = target.stat().st_size
    say(f"  完成：{target}")
    say(f"  大小：{size / 1024 / 1024:.1f} MB（{len(files)} 条目）")
    return target


# --------------------------------------------------------------------------
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="出一份发行压缩包")
    ap.add_argument("--version", default="v1.0", help="版本号，默认 v1.0")
    ap.add_argument("--no-build", action="store_true",
                    help="跳过打包，直接压缩现有的 .tmp\\release-build 产物")
    ap.add_argument("--python", default=None,
                    help="指定解释器（默认自动探测）")
    args = ap.parse_args()

    say(f"项目目录：{ROOT}")
    say(f"版本号　：{args.version}")

    if not args.no_build:
        build(find_python(args.python))

    stage()
    target = zip_up(args.version)

    step("完成")
    say(f"  {target}")
    say()
    say("  解压后根目录就是 DesktopNest.exe + _internal + 使用说明.txt，")
    say("  双击 DesktopNest.exe 即可，不需要装 Python。")
    say()
    say(f"  构建中间产物在 {BUILD_ROOT}（约 200 MB），整个 .tmp\\ 可以随手删掉。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
