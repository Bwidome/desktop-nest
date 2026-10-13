#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索匹配工具
============
模糊搜索用的小函数，独立成模块，避免界面模块之间互相 import。
"""

from __future__ import annotations


# 分数分段：连续命中永远排在顺序命中之前
SCORE_SUBSTRING_BASE = 0          # 连续子串：0 ~ 几百
SCORE_SUBSEQUENCE_BASE = 10000    # 顺序命中：10000 起


def fuzzy_match(query: str, text: str) -> "tuple[bool, list[int], int]":
    """模糊匹配并返回命中位置。

    两段式策略：

    1. **连续子串**（含前缀）：最符合直觉。要从所有出现位置里挑最靠前的一次，
       否则 "文件0" 会因为先撞上 "文件20" 里的 0 而把 "文件00" 排到后面。
       分数按出现位置加权，开头命中的排最前。

    2. **按顺序出现的字符**（如 `gch` → `Google Chrome`）：作为补充手段，
       分数基数给得很大，保证永远排在连续命中之后——这样它只是"还能找到"，
       不会把真正的精确匹配挤下去。

    返回 (是否命中, 命中字符下标列表, 分数)；分数越小排得越靠前。
    """
    if not query:
        return True, [], 0
    haystack = (text or "").lower()
    needle = query.lower()
    if not haystack:
        return False, [], 0

    # ---- 1. 连续子串 ----
    position = haystack.find(needle)
    if position >= 0:
        return True, list(range(position, position + len(needle))), position * 2

    # ---- 2. 顺序命中 ----
    indices: "list[int]" = []
    cursor = 0
    for ch in needle:
        found = haystack.find(ch, cursor)
        if found < 0:
            return False, [], 0
        indices.append(found)
        cursor = found + 1

    gaps = (indices[-1] - indices[0] + 1) - len(indices)
    # 只过滤明显的噪声：命中起点太靠后（>8）、或者中间空缺过大
    if indices[0] > 8 or gaps > 16:
        return False, [], 0
    return True, indices, SCORE_SUBSEQUENCE_BASE + gaps * 30 + indices[0]


def highlight_ranges(indices: "list[int]") -> "list[tuple[int, int]]":
    """把离散下标合并成连续区间，便于一次性填充高亮底色。"""
    if not indices:
        return []
    out: "list[tuple[int, int]]" = []
    start = prev = indices[0]
    for value in indices[1:]:
        if value == prev + 1:
            prev = value
            continue
        out.append((start, prev + 1))
        start = prev = value
    out.append((start, prev + 1))
    return out
