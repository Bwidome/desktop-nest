#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
确定 IShellLinkW 的虚表索引
==========================
COM 虚表顺序不能靠记忆猜——猜错不会报错，只会静默写到别的属性上，
最后生成一堆"参数里写着中文说明"的怪快捷方式。

做法：对每个候选索引写入独一无二的标记值，再用 Windows 官方的
`WScript.Shell` COM（PowerShell 脚本）读回来，看标记落在哪个属性上。

用法：python dev/probe_vtable.py
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import winlink  # noqa: E402

BASE = Path(tempfile.gettempdir()) / "nest-vtbl"
PS_SCRIPT = HERE / "dev" / "read_lnk.ps1"

# 每个 (索引, 参数类型) 组合写一个独特标记
CANDIDATES = [
    (5, "str", "MARK5"),
    (6, "str", "MARK6"),
    (7, "str", "MARK7"),
    (8, "str", "MARK8"),
    (9, "str", "MARK9"),
    (10, "str", "MARK10"),
    (11, "str", "MARK11"),
    (12, "str", "MARK12"),
    (13, "int", 7),
    (14, "twoint", (5, 9)),
]


def write_marker(index: int, kind: str, value) -> str:
    link = BASE / f"idx{index:02d}.lnk"
    if link.exists():
        link.unlink()
    try:
        shell_link = winlink._ShellLink()
        if kind == "str":
            shell_link._method(index, wintypes.LPCWSTR)(shell_link.ptr, value)
        elif kind == "int":
            shell_link._method(index, ctypes.c_int)(shell_link.ptr, value)
        elif kind == "twoint":
            shell_link._method(index, ctypes.c_int, ctypes.c_int)(
                shell_link.ptr, value[0], value[1])
        shell_link.set_path(r"C:\Windows\System32\notepad.exe")
        if not shell_link.save(link):
            return "保存失败"
        return "ok"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def read_back() -> "dict[str, str]":
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(PS_SCRIPT), "-Folder", str(BASE)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = {}
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if "|" in line:
            name = line.split("|", 1)[0]
            out[name] = line
    if not out and result.stderr:
        print("PowerShell 出错：", result.stderr[:400])
    return out


def main() -> int:
    if BASE.exists():
        for stale in BASE.glob("*.lnk"):
            stale.unlink()
    BASE.mkdir(parents=True, exist_ok=True)

    print("写入标记值…")
    status = {}
    for index, kind, value in CANDIDATES:
        status[index] = write_marker(index, kind, value)
        print(f"  index {index:>2} ({kind:5}) -> {status[index]}")

    print()
    print("用官方 COM 读回：")
    rows = read_back()
    for name, line in sorted(rows.items()):
        print("  " + line)

    print()
    print("对照分析（哪个索引写到了哪个属性）：")
    for index, kind, value in CANDIDATES:
        if status[index] != "ok":
            continue
        marker = str(value) if kind != "twoint" else f"{value[0]},{value[1]}"
        name = f"idx{index:02d}.lnk"
        line = rows.get(name, "")
        fields = dict(part.split("=", 1) for part in line.split("|")[1:] if "=" in part)
        hits = [key for key, text in fields.items() if marker in (text or "")]
        print(f"  index {index:>2} 标记 {marker:<6} -> {hits or '（没写进任何可读属性）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
