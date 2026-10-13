#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搬运安全性自检
==============
专门验证 ``nest._move`` 的两条路径与回滚逻辑，这些是"绝不丢文件 / 绝不重复"
的最后一道防线，值得单独测：

* 同分区：os.replace 原子改名
* 跨分区（这里用"强制走复制路径"来模拟）：复制 → 校验 → 删源
* 校验不通过：清掉半成品，源文件原地不动
* 删源失败：回滚复制出来的那份，**不留下重复文件**

用法：python dev/test_move.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import nest  # noqa: E402

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}" + (f"  [{detail}]" if detail and not condition else ""))


class BlockReplace:
    """上下文管理器：让 os.replace 失败，强制走"复制 + 校验 + 删源"路径。"""

    def __enter__(self):
        self.original = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(
            OSError(18, "模拟跨分区"))
        nest.os.replace = os.replace
        return self

    def __exit__(self, *exc):
        os.replace = self.original
        nest.os.replace = self.original
        return False


class BlockUnlink:
    """上下文管理器：让源文件的删除失败，验证回滚。"""

    def __init__(self, target_name: str):
        self.target_name = target_name
        self.original = None

    def __enter__(self):
        self.original = Path.unlink

        def patched(self, *a, **k):
            if self.name == self.target_name or self.name.startswith(self.target_name):
                raise PermissionError(5, "模拟被占用")
            return self.original(self, *a, **k)

        Path.unlink = patched
        return self

    def __exit__(self, *exc):
        Path.unlink = self.original
        return False


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-move-test"
    shutil.rmtree(base, ignore_errors=True)
    (base / "src").mkdir(parents=True)
    (base / "dst").mkdir(parents=True)
    src_dir, dst_dir = base / "src", base / "dst"

    print("── 1. 同分区：原子改名 ──")
    file_a = src_dir / "a.txt"
    file_a.write_text("AAA" * 100, encoding="utf-8")
    final = nest._move(file_a, dst_dir / "a.txt")
    check("文件已移动", final.exists() and not file_a.exists())
    check("内容完好", final.read_text(encoding="utf-8") == "AAA" * 100)
    check("落在预期位置", final.name == "a.txt", str(final))

    print()
    print("── 2. 跨分区：复制 → 校验 → 删源 ──")
    file_b = src_dir / "b.txt"
    file_b.write_text("BBB" * 50, encoding="utf-8")
    with BlockReplace():
        final_b = nest._move(file_b, dst_dir / "b.txt")
    check("复制路径下文件也移动成功", final_b.exists() and not file_b.exists())
    check("复制路径下内容完好", final_b.read_text(encoding="utf-8") == "BBB" * 50)

    folder = src_dir / "资料夹"
    folder.mkdir()
    (folder / "内层.txt").write_text("inner", encoding="utf-8")
    (folder / "子").mkdir()
    (folder / "子" / "深.txt").write_text("deep", encoding="utf-8")
    with BlockReplace():
        final_dir = nest._move(folder, dst_dir / "资料夹")
    check("文件夹也走复制路径成功", final_dir.is_dir() and not folder.exists())
    check("嵌套内容完整",
          (final_dir / "子" / "深.txt").read_text(encoding="utf-8") == "deep")

    print()
    print("── 3. 重名不覆盖 ──")
    (src_dir / "同名.txt").write_text("new", encoding="utf-8")
    (dst_dir / "同名.txt").write_text("old", encoding="utf-8")
    final_c = nest._move(src_dir / "同名.txt", dst_dir / "同名.txt")
    check("重名自动加序号", final_c.name == "同名 (1).txt", final_c.name)
    check("原文件未被覆盖",
          (dst_dir / "同名.txt").read_text(encoding="utf-8") == "old")
    check("新文件内容正确", final_c.read_text(encoding="utf-8") == "new")

    print()
    print("── 4. 删源失败时回滚（不产生重复）──")
    file_d = src_dir / "locked.txt"
    file_d.write_text("LOCKED" * 30, encoding="utf-8")
    target_d = dst_dir / "locked.txt"
    rolled_back = False
    try:
        self_original = Path.unlink

        def patched_unlink(self, *a, **k):
            if Path(self).name == "locked.txt" and Path(self).parent == src_dir:
                raise PermissionError(5, "模拟被占用")
            return self_original(self, *a, **k)

        Path.unlink = patched_unlink
        with BlockReplace():
            try:
                nest._move(file_d, target_d)
            except OSError as exc:
                rolled_back = "回滚" in str(exc) or "无法删除" in str(exc)
    finally:
        Path.unlink = self_original

    check("删源失败会抛错（不谎报成功）", rolled_back)
    check("源文件仍在原地", file_d.exists())
    check("复制出来的那份已被回滚（没有重复）", not target_d.exists())

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
