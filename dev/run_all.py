#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键自检
========
把 `dev/` 下所有 `test_*.py` 依次跑一遍并汇总结果。

用法
----
    python dev/run_all.py                      # 自动挑一个能加载 PyQt6 的解释器
    python dev/run_all.py --python <解释器>     # 手动指定
    python dev/run_all.py --list               # 只列出会跑哪些用例，不执行
    python dev/run_all.py --shots              # 额外让 test_nest 把界面截图存到 shots\
    python dev/run_all.py test_core test_nest  # 只跑指定的几套（按名字过滤）

为什么要"挑解释器"
------------------
`libs/` 里自带的 PyQt6 是 CPython **3.12** 的 ABI（`sip.cp312-win_amd64.pyd`）。
换成别的版本（比如 3.13）跑，就会
`ModuleNotFoundError: No module named 'PyQt6.sip'`。
所以这里会先探测候选解释器，挑第一个能 `import PyQt6.QtWidgets` 的来用，
避免"明明代码没问题，却因为解释器选错而满屏报错"。

退出码：全部通过为 0，只要有一套失败就是 1（方便挂到 CI 或批处理里）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # dev/
ROOT = HERE.parent                              # 项目根

# test_*.py 的汇总行固定格式，见各用例文件末尾
SUMMARY_RE = re.compile(r"通过\s*(\d+)\s*项[，,]\s*失败\s*(\d+)\s*项")


# --------------------------------------------------------------------------
# 解释器探测
# --------------------------------------------------------------------------
def _candidates() -> "list[str]":
    """按优先级列出可能的解释器路径（去重）。"""
    seen: "list[str]" = []

    def add(path: "str | None") -> None:
        if not path:
            return
        p = str(path)
        if p not in seen:
            seen.append(p)

    add(os.environ.get("NEST_PYTHON"))          # 显式覆盖
    add(sys.executable)                         # 当前解释器

    # uv 管理的 CPython（本机自检常用的那个）
    appdata = os.environ.get("APPDATA")
    if appdata:
        uv_dir = Path(appdata) / "uv" / "python"
        if uv_dir.is_dir():
            for p in sorted(uv_dir.glob("cpython-*/python.exe"), reverse=True):
                add(p)

    # 常规安装位置
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for ver in ("313", "312", "311", "310"):
            add(Path(local) / "Programs" / "Python" / f"Python{ver}" / "python.exe")
    add(r"D:\python\python.exe")

    # py 启动器枚举出的所有解释器
    try:
        out = subprocess.run(["py", "-0p"], capture_output=True, text=True,
                             timeout=15).stdout
        for line in out.splitlines():
            m = re.search(r"([A-Za-z]:\\[^\s]*python\.exe)", line)
            if m:
                add(m.group(1))
    except Exception:
        pass

    return [p for p in seen if Path(p).is_file()]


def _can_load_qt(python: str) -> bool:
    """这个解释器能不能 import PyQt6（含 sip 扩展）？"""
    try:
        proc = subprocess.run(
            [python, "-c", "import PyQt6.QtWidgets, PyQt6.sip"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        return proc.returncode == 0
    except Exception:
        return False


def pick_python(explicit: "str | None") -> "tuple[str, bool]":
    """返回 (解释器路径, Qt 是否可用)。"""
    if explicit:
        return explicit, _can_load_qt(explicit)
    for cand in _candidates():
        if _can_load_qt(cand):
            return cand, True
    return sys.executable, False


# --------------------------------------------------------------------------
# 用例发现与执行
# --------------------------------------------------------------------------
def discover(patterns: "list[str]") -> "list[Path]":
    files = sorted(HERE.glob("test_*.py"))
    if patterns:
        files = [f for f in files
                 if any(p.lower() in f.stem.lower() for p in patterns)]
    return files


def run_one(python: str, path: Path, *, shots: bool) -> "tuple[int, int, str, bool]":
    """跑一套用例，返回 (通过数, 失败数, 原始输出, 进程是否成功)。"""
    cmd = [python, str(path)]
    if shots and path.stem == "test_nest":
        cmd.append("--shots")

    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")   # 无显示器也能跑 GUI 用例
    env.setdefault("PYTHONIOENCODING", "utf-8")      # 中文输出别乱码
    env.setdefault("PYTHONUTF8", "1")

    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    out = (proc.stdout or "") + (proc.stderr or "")

    matches = SUMMARY_RE.findall(out)
    if matches:
        passed, failed = (int(x) for x in matches[-1])
    else:
        passed, failed = 0, 0
    return passed, failed, out, proc.returncode == 0


def main(argv: "list[str]") -> int:
    explicit = None
    shots = False
    listing = False
    filters: "list[str]" = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--python" and i + 1 < len(argv):
            explicit = argv[i + 1]
            i += 2
            continue
        if arg == "--shots":
            shots = True
        elif arg in ("--list", "-l"):
            listing = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        elif arg.startswith("-"):
            print(f"未知参数：{arg}（用 --help 看用法）", file=sys.stderr)
            return 2
        else:
            filters.append(arg)
        i += 1

    files = discover(filters)
    if not files:
        print("没找到任何 test_*.py 用例。", file=sys.stderr)
        return 1

    if listing:
        print("会执行以下用例：")
        for f in files:
            print(f"  · {f.relative_to(ROOT)}")
        return 0

    python, qt_ok = pick_python(explicit)
    print("=" * 68)
    print("桌面收纳 · 一键自检")
    print(f"解释器：{python}")
    print(f"PyQt6 ：{'可用' if qt_ok else '不可用（界面用例会失败，请用 --python 指定）'}")
    print("=" * 68)

    results = []
    for f in files:
        print(f"\n>>> {f.relative_to(ROOT)}")
        passed, failed, out, ok = run_one(python, f, shots=shots)
        print(out.rstrip())
        if not SUMMARY_RE.search(out):
            # 用例没跑到汇总行——通常是 import 就炸了，原样报出来
            print(f"  !! 未输出汇总行（退出码{'正常' if ok else '异常'}）")
        results.append((f, passed, failed, ok))

    total_pass = sum(r[1] for r in results)
    total_fail = sum(r[2] for r in results)
    bad = [r for r in results if r[2] or not r[3]]

    print("\n" + "=" * 68)
    print(f"{'用例':<28}{'通过':>6}{'失败':>6}   结果")
    print("-" * 68)
    for f, passed, failed, ok in results:
        flag = "OK" if (ok and not failed) else "FAILED"
        print(f"{f.stem:<28}{passed:>6}{failed:>6}   {flag}")
    print("-" * 68)
    print(f"{'合计':<28}{total_pass:>6}{total_fail:>6}   "
          f"{'全部通过' if not bad else f'{len(bad)} 套未通过'}")
    print("=" * 68)

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
