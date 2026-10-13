#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性把 theme.py 里的 `font-size: NNpx` 换成点值
=================================================
原因：QSS 里的像素字号**不随系统 DPI 缩放**。在 125% / 150% 的屏幕上，
别的东西都变大了，只有文字还是那么小，看起来就是"显示大小有问题 + 发虚"。
换成 `pt`（点）之后 Qt 会跟着 DPI 一起缩放，和系统其它程序一致。

用法：python dev/fix_font_units.py
"""
from __future__ import annotations

import re
from pathlib import Path

THEME = Path(__file__).resolve().parent.parent / "theme.py"

# 像素 → 点 的换算：按 96dpi 下 1pt ≈ 1.333px，同时整体略微放大，
# 让正文字号落在 Windows 常见的 9~10pt 区间。
def px_to_pt(px: int) -> str:
    pt = px * 0.75
    if pt < 7:
        return f"{pt:.1f}".rstrip("0").rstrip(".")
    return f"{pt:g}"


def main() -> int:
    text = THEME.read_text(encoding="utf-8")
    found = re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", text)
    if not found:
        print("没有找到 px 字号，可能已经改过了")
        return 0

    def replace(match: re.Match) -> str:
        value = float(match.group(1))
        return f"font-size: {px_to_pt(value)}pt"

    text = re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", replace, text)

    # 顺便把 ::indicator 之类的固定像素尺寸也按比例说明一下（保留 px 是刻意的：
    # 复选框那种小方块跟着 DPI 变大会显得笨重，但这里先统一成 pt 保证一致观感）
    THEME.write_text(text, encoding="utf-8")
    print(f"已替换 {len(found)} 处 px 字号")
    for old in sorted(set(found)):
        print(f"  {old}px -> {px_to_pt(float(old))}pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
