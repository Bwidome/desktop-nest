#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建桌面快捷方式（以"像 exe 一样"的方式启动）
===========================================
程序本身是 Python 写的，要真正做到单文件 .exe 得用 PyInstaller 打包。

在那之前，这个脚本给你一个**体验上等价**的东西：
在桌面和开始菜单放一个带图标、带名字的快捷方式，双击即启动，
**不弹黑窗口**（走 pythonw.exe），和普通软件没区别。

用法：python create_shortcut.py
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import config  # noqa: E402
import winlink  # noqa: E402

SHORTCUT_NAME = "桌面收纳"
ICON_CACHE_NAME = "app.ico"


def find_pythonw() -> Path:
    """找一个 pythonw.exe（无控制台窗口）。"""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    return exe


def make_app_icon() -> "Path | None":
    """生成一个 .ico 作为快捷方式图标，尽量贴近程序自己的视觉。"""
    target = HERE / ICON_CACHE_NAME
    if target.exists():
        return target
    try:
        from PIL import Image, ImageDraw

        size = 256
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        accent = (79, 107, 237, 255)          # 和界面主色一致
        draw.rounded_rectangle([8, 8, size - 8, size - 8], radius=58, fill=accent)
        # 抽屉：两层 + 下方箭头（和托盘图标同一套造型）
        draw.rounded_rectangle([56, 64, 200, 106], radius=10, fill=(255, 255, 255, 255))
        draw.rounded_rectangle([56, 122, 200, 164], radius=10,
                               fill=(216, 224, 255, 255))
        draw.polygon([(128, 214), (80, 170), (176, 170)],
                     fill=(255, 255, 255, 255))
        image.save(target, format="ICO",
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
        return target
    except Exception as exc:                       # noqa: BLE001
        print(f"  （生成图标失败，将使用默认图标：{exc}）")
        return None


def startup_folder() -> Path:
    import os

    return (Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs")


def create_link(link: Path, pythonw: Path, icon: "Path | None",
                start_menu: bool = False) -> "tuple[bool, str]":
    """创建一个指向本程序的快捷方式。"""
    arguments = f'"{HERE / "main.py"}"'
    return winlink.create_shortcut(
        link,
        str(pythonw),
        arguments=arguments,
        icon_path=str(icon) if icon else str(pythonw),
        working_dir=str(HERE),
    )


def main() -> int:
    print("=" * 62)
    print("  创建「桌面收纳」快捷方式")
    print("=" * 62)
    pythonw = find_pythonw()
    print(f"  解释器：{pythonw}")
    print(f"  程序：{HERE / 'main.py'}")
    print()

    icon = make_app_icon()
    print(f"  图标：{icon or '（默认）'}")
    print()

    created: "list[Path]" = []
    failed: "list[tuple[str, str]]" = []

    # 1) 桌面
    desktop_link = config.get_desktop_dir() / f"{SHORTCUT_NAME}.lnk"
    ok, reason = create_link(desktop_link, pythonw, icon)
    if ok:
        created.append(desktop_link)
    else:
        failed.append((str(desktop_link), reason))

    # 2) 开始菜单（方便搜索和固定到任务栏）
    start_link = startup_folder() / f"{SHORTCUT_NAME}.lnk"
    ok, reason = create_link(start_link, pythonw, icon, start_menu=True)
    if ok:
        created.append(start_link)
    else:
        failed.append((str(start_link), reason))

    for link in created:
        print(f"  ✓ 已创建：{link}")
    for path, reason in failed:
        print(f"  ✗ 创建失败：{path} —— {reason}")

    print()
    if created:
        print("  以后双击桌面上的「桌面收纳」就能启动，不会有黑窗口。")
        print("  想固定到任务栏：在开始菜单里搜「桌面收纳」→ 右键 → 固定到任务栏。")
    print()
    return 0 if created else 1


if __name__ == "__main__":
    raise SystemExit(main())
