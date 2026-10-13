#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面还原工具（应急用）
====================
把收纳目录里的东西**全部搬回桌面**，公共桌面的快捷方式送回公共桌面。

什么时候用：
* 程序崩溃 / 被强制结束，桌面空着，想立刻恢复
* 不放心"程序还会不会自己还原"，想手动来一次

安全保证：
* **只移动，绝不删除**
* 重名自动加 (1)(2) 序号，不覆盖任何东西
* 还原完成后会打印一份清单，方便你核对
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_LIBS = HERE / "libs"
if _LIBS.is_dir() and str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))

import config  # noqa: E402
import nest  # noqa: E402


def find_nest_with_content() -> "Path | None":
    """找到真正存着东西的那个收纳目录。

    程序正常会用 `~/.desktop-nest`；如果那里不可写就会退到程序目录。
    两个都看一眼，挑有内容的那个。
    """
    candidates = []
    try:
        candidates.append(Path.home() / nest.NEST_DIR_NAME)
    except RuntimeError:
        pass
    candidates.append(HERE / nest.NEST_DIR_NAME)
    for candidate in candidates:
        store = candidate / "desktop"
        try:
            if store.is_dir() and any(store.iterdir()):
                return candidate
        except OSError:
            continue
    return None


def main() -> int:
    user_desktop = config.get_desktop_dir()
    public_desktop = config.get_public_desktop_dir()

    print("=" * 62)
    print("  桌面还原工具")
    print("=" * 62)
    print(f"  个人桌面：{user_desktop}")
    print(f"  公共桌面：{public_desktop}")
    print()

    root = find_nest_with_content()
    if root is None:
        print("  没有找到需要还原的内容 —— 桌面应该已经是完整的。")
        print()
        return 0

    print(f"  收纳目录：{root}")
    nest.nest_root = lambda: root          # 明确指向这一份
    store = nest.desktop_store()
    items = sorted(p.name for p in store.iterdir())
    sources = nest.read_sources()
    public_count = sum(1 for name in items if sources.get(name) == "public")
    print(f"  待还原：{len(items)} 项"
          f"（其中 {public_count} 项属于公共桌面）")
    print()

    result = nest.restore_to_desktop(user_desktop)

    print("-" * 62)
    print(f"  完成：{result.summary()}")
    if result.skipped:
        print()
        print("  说明：")
        for name, reason in result.skipped[:15]:
            print(f"    · {name}：{reason}")
    if result.failed:
        print()
        print("  未能还原（文件仍在收纳目录里，没有丢）：")
        for name, reason in result.failed[:15]:
            print(f"    · {name}：{reason}")
        print()
        print("  若提示权限问题，请用管理员身份重新运行本脚本。")

    left = len(list(store.iterdir())) if store.exists() else 0
    print()
    print(f"  收纳目录剩余：{left} 项")
    print(f"  个人桌面现有：{len(list(user_desktop.iterdir()))} 项")
    try:
        print(f"  公共桌面现有：{len(list(public_desktop.iterdir()))} 项")
    except OSError:
        pass
    print()
    return 0 if not result.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
