#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证发行包：解压到干净沙盒 → 跑 --selftest → 看 8 个环节是不是都 OK。

要点（踩过的坑都在这）：
· 必须把 USERPROFILE / LOCALAPPDATA / APPDATA 一起指向沙盒，否则 --selftest
  会去动真实的 %LOCALAPPDATA%\\DesktopNest。
· 给 Windows 程序传路径要用**反斜杠原生路径**，不能传 /c/... 那种
  （会被解析成 <当前盘>:\\c\\...）。
· 全程不删除沙盒里的任何东西，只往新建目录里解压。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT / "desktop-nest-release-v1.0.zip"
SANDBOX = Path(tempfile.gettempdir()) / "nest-release-check"
APP = SANDBOX / "app"


def main() -> int:
    if not ZIP.is_file():
        print(f"没找到压缩包：{ZIP}")
        return 1

    # 每次换一个全新的沙盒目录（改名让位，不删东西）
    if SANDBOX.exists():
        index = 1
        while True:
            aside = SANDBOX.with_name(f"{SANDBOX.name}.old{index}")
            if not aside.exists():
                break
            index += 1
        SANDBOX.rename(aside)
        print(f"旧沙盒改名让位：{SANDBOX.name} -> {aside.name}")
    APP.mkdir(parents=True)

    print(f"解压 {ZIP.name} -> {APP}")
    with zipfile.ZipFile(ZIP) as zf:
        names = zf.namelist()
        zf.extractall(APP)
    print(f"  解压出 {len(names)} 个条目")

    tops = sorted({n.split("/")[0] for n in names})
    print(f"  根目录：{tops}")

    exe = APP / "DesktopNest.exe"
    if not exe.is_file():
        print("!! 根目录没有 DesktopNest.exe")
        return 1
    print(f"  exe 大小：{exe.stat().st_size / 1024 / 1024:.1f} MB")

    # 隔离环境：让程序以为自己是全新机器
    home = SANDBOX / "home"
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    for path in (home, local, roaming):
        path.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["USERPROFILE"] = str(home)
    env["LOCALAPPDATA"] = str(local)
    env["APPDATA"] = str(roaming)
    # ⚠️ USERNAME 也必须换掉：单实例互斥体的名字是
    # `Global\DesktopNest.SingleInstance.v1.<用户名>`，而 `_user_slug()` 读的是
    # `os.environ["USERNAME"]`。不换的话，只要本机**正开着**一个桌面收纳，
    # 沙盒里的自检就会在第 5 步被判成"已经有实例在运行"，验证直接失败——
    # 那是隔离没做全，不是发行包有问题。
    env["USERNAME"] = "NestSandbox"
    env["QT_QPA_PLATFORM"] = "offscreen"     # 无头环境下别真开窗
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    print()
    print("=" * 60)
    print("  DesktopNest.exe --selftest")
    print("=" * 60)
    proc = subprocess.run([str(exe), "--selftest"], cwd=str(APP), env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out.strip())
    print("-" * 60)
    print(f"退出码：{proc.returncode}")

    ok = proc.returncode == 0 and "失败" not in out.split("通过")[-1][:20] \
        if "通过" in out else proc.returncode == 0

    # 日志落在沙盒里（说明隔离生效了，没写真实 %LOCALAPPDATA%）
    log_dir = local / "DesktopNest"
    if log_dir.is_dir():
        print(f"日志目录：{log_dir}（{len(list(log_dir.iterdir()))} 个文件）")
    else:
        print(f"⚠️ 没在沙盒里看到日志目录 {log_dir}")

    print()
    print("结果：", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
