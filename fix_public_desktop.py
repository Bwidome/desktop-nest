#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「公共桌面」的快捷方式移回去
============================
用途：这些快捷方式本属于 `C:\\Users\\Public\\Desktop`（所有用户都能看到），
如果它们现在躺在你的个人桌面上，用这个脚本送回去。

**需要管理员权限**：公共桌面受系统保护，普通账号写不进去。
右键 `修复公共桌面.bat` → 以管理员身份运行。

只做移动，不删除任何东西。
"""

from __future__ import annotations

import ctypes
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import config  # noqa: E402


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


PUBLIC_NAMES = [
    "Cpolar Web UI.lnk",
    "FlClash.lnk",
    "IntelliJ IDEA 2026.2.0.1.lnk",
    "Masm for Windows 集成实验环境 2015.lnk",
    "MegaDownloader.lnk",
    "QQ音乐.lnk",
    "中国移动云盘.lnk",
    "完美世界竞技平台.lnk",
    "慕讯公益加速器.lnk",
    "腾讯会议.lnk",
]


def unique(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    index = 1
    while True:
        candidate = target.parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def main() -> int:
    personal = config.get_desktop_dir()
    public = config.get_public_desktop_dir()

    print("=" * 62)
    print("  把公共桌面的快捷方式移回去")
    print("=" * 62)
    print(f"  个人桌面：{personal}")
    print(f"  公共桌面：{public}")
    print(f"  管理员权限：{'是' if is_admin() else '否'}")
    print()

    if not is_admin():
        print("  [!] 公共桌面受系统保护，需要管理员权限才能写入。")
        print("      请右键「修复公共桌面.bat」→ 以管理员身份运行。")
        print()
        print("      如果暂时不想弄，这些快捷方式留在个人桌面上也能正常用，")
        print("      只是别的用户看不到它们。")
        print()
        return 1

    moved = 0
    skipped = 0
    failed: "list[tuple[str, str]]" = []
    for name in PUBLIC_NAMES:
        source = personal / name
        if not source.exists():
            skipped += 1
            continue
        try:
            final = unique(public / name)
            shutil.move(str(source), str(final))
            moved += 1
            print(f"  ✓ {name}")
        except OSError as exc:
            failed.append((name, str(exc)))
            print(f"  ✗ {name} —— {exc}")

    print()
    print("-" * 62)
    print(f"  已移回公共桌面：{moved} 项")
    print(f"  个人桌面上没有找到：{skipped} 项（可能本来就不在）")
    if failed:
        print(f"  失败：{len(failed)} 项")
    print(f"  公共桌面现在：{len(list(public.iterdir()))} 项")
    print(f"  个人桌面现在：{len(list(personal.iterdir()))} 项")
    print()
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
