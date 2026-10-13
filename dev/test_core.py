#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底层组件自检
============
覆盖不再依赖界面的模块：

* winlink —— 快捷方式**创建**（COM 虚表下标是实测出来的，这里加回归）
* engine  —— 快捷方式**解析**（[MS-SHLLINK] 二进制）与类型判定
* nest    —— 系统位置快捷方式生成 + shell 位置清单
* safety  —— 系统项保护、占用检测、路径包含判定
* textutil —— 模糊搜索与高亮区间

用法：python dev/test_core.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import subprocess  # noqa: E402

import engine  # noqa: E402
import nest  # noqa: E402
import safety  # noqa: E402
import textutil  # noqa: E402
import winlink  # noqa: E402

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}" + (f"  [{detail}]" if detail and not condition else ""))


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-core-test"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    desktop = base / "Desktop"
    desktop.mkdir()

    print("── 1. 快捷方式：创建与解析 ──")
    # 写侧走 COM（虚表下标是实测出来的，见 dev/probe_vtable.py）
    ok, reason = winlink.create_shortcut(base / "记事本.lnk",
                                         r"C:\Windows\System32\notepad.exe")
    check("创建指向程序的快捷方式", ok, reason)
    # 读侧走 engine 的二进制解析（[MS-SHLLINK]）——那才是程序实际用的那条路
    check("解析回目标路径",
          engine.resolve_shortcut_target(base / "记事本.lnk")
          == Path(r"C:\Windows\System32\notepad.exe"),
          str(engine.resolve_shortcut_target(base / "记事本.lnk")))

    # 虚表下标回归：写参数不能污染其它属性（历史上 SetDescription 错位写进了参数）
    link_arg = base / "带参数.lnk"
    winlink.create_shortcut(link_arg, r"C:\Windows\System32\notepad.exe",
                            arguments="//test")
    check("写参数后目标依然正确",
          engine.resolve_shortcut_target(link_arg)
          == Path(r"C:\Windows\System32\notepad.exe"),
          str(engine.resolve_shortcut_target(link_arg)))
    # 参数写入是否正确，用 Windows 官方 COM（WScript.Shell）来判定，不靠自己读
    official = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(HERE / "dev" / "read_lnk.ps1"), "-Folder", str(base)],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    check("官方 COM 确认参数已正确写入",
          any("args=//test" in line for line in official.splitlines()), official.strip()[:200])

    # 系统位置快捷方式：由 nest 生成，并把「名称 → shell 位置」记进自己的清单
    nest.nest_root = lambda: base / ".nest"          # 指到沙盒，别碰真实用户目录
    links = nest.sync_system_links()
    check("批量创建系统位置快捷方式",
          len(links) == len(nest.default_system_links()), f"created={len(links)}")
    for name in ("此电脑", "回收站", "网络", "用户文件夹"):
        check(f"「{name}」链接存在", (nest.links_store() / f"{name}.lnk").exists())
    check("「此电脑」能查到 shell 位置",
          nest.shell_path_for(nest.links_store() / "此电脑.lnk")
          == f"::{winlink.CLSID_THIS_PC}",
          nest.shell_path_for(nest.links_store() / "此电脑.lnk"))
    check("指向程序的链接不会被当成系统位置",
          nest.shell_path_for(base / "记事本.lnk") == "")

    print()
    print("── 2. 安全校验 ──")
    for name in ("回收站", "此电脑", "desktop.ini", "desktop.INI", "网络"):
        check(f"保护系统项「{name}」", safety.is_protected_name(name))
    for name in ("报告.docx", "我的项目", "photo.JPG"):
        check(f"不误伤普通项「{name}」", not safety.is_protected_name(name))

    check("跳过 .crdownload 半成品", safety.is_blocked_suffix("半成品.crdownload"))
    check("跳过 ~$ 临时文件", safety.is_blocked_prefix("~$临时.docx"))
    check("正常文件不跳过", not safety.is_blocked_suffix("报告.docx"))

    probe = base / "probe.txt"
    probe.write_text("x", encoding="utf-8")
    check("普通文件可读", safety.safe_exists(probe))
    check("不存在的路径返回 False",
          not safety.safe_exists(base / "根本不存在" / "x.txt"))
    check("safe_exists 不抛异常（权限被拒时）",
          safety.safe_exists(Path("C:/Windows/System32/config/SAM")) is not None)

    readonly = base / "只读.txt"
    readonly.write_text("ro", encoding="utf-8")
    os.chmod(readonly, 0o444)
    check("只读文件不被误判为占用", not safety.is_locked(readonly))
    os.chmod(readonly, 0o666)

    check("子路径判定正确", safety.is_subpath(base / "a" / "b", base))
    check("同前缀不误判", not safety.is_subpath(base / "ab", base / "a"))
    check("自身算子路径", safety.is_subpath(base, base))
    check("桌面之外的目录不算子路径",
          not safety.is_subpath(base / "repo", desktop))

    print()
    print("── 3. 模糊搜索 ──")
    cases = [
        ("文件0", "文件00.txt", True),
        ("报告", "季度报告.docx", True),
        ("gch", "Google Chrome", True),
        ("xlsx", "预算表.xlsx", True),
        ("预", "预算表.xlsx", True),
        ("zzz", "文件01.txt", False),
        ("abcd", "ab.txt", False),
        ("", "任意", True),
    ]
    for query, text, want in cases:
        hit, _indices, _score = textutil.fuzzy_match(query, text)
        check(f"搜索「{query}」→「{text}」{'命中' if want else '不命中'}",
              hit == want, str(hit))

    score_prefix = textutil.fuzzy_match("文件0", "文件00.txt")[2]
    score_scattered = textutil.fuzzy_match("文件0", "文件20.txt")[2]
    check("连续命中排得比顺序命中靠前", score_prefix < score_scattered,
          f"{score_prefix} vs {score_scattered}")

    hit, indices, _score = textutil.fuzzy_match("报告", "季度报告.docx")
    check("命中位置可用于高亮", hit and indices == [2, 3], str(indices))
    check("高亮区间合并正确",
          textutil.highlight_ranges([2, 3, 7]) == [(2, 4), (7, 8)],
          str(textutil.highlight_ranges([2, 3, 7])))
    check("空下标返回空区间", textutil.highlight_ranges([]) == [])

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
