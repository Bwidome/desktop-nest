#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻页后图标消失 —— 回归测试
=========================
用户报告的现象：**第一次能正常显示图标，翻到第 2 页再翻回第 1 页，
第 1 页的图标就没了。**

根因：翻页时调用了 `IconLoader.clear()`，它把"已取到的图标"内存缓存一并清空，
于是返回上一页要重新去 Windows Shell 取一遍；只要那次取失败，图标就空着。

这里用真实快捷方式复现整条链路，并断言：
1. 第一页图标全部就绪
2. 翻到第 2 页后，第 1 页用过的图标**仍在缓存里**
3. 翻回第 1 页，图标**立刻就是好的**（不需要重新取）

用法：python dev/test_icons_page.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}" + (f"  [{detail}]" if detail and not condition else ""))


ICON_REQUEST = 64


def build_links(folder: Path, count: int) -> "list[Path]":
    import winlink

    exes = [
        r"C:\Windows\System32\notepad.exe",
        r"C:\Windows\System32\calc.exe",
        r"C:\Windows\explorer.exe",
        r"C:\Windows\System32\write.exe",
        r"C:\Windows\System32\Taskmgr.exe",
        r"C:\Windows\regedit.exe",
        r"C:\Windows\System32\cmd.exe",
        r"C:\Windows\System32\conhost.exe",
        r"C:\Windows\System32\mspaint.exe",
        r"C:\Windows\System32\dllhost.exe",
    ]
    links = []
    for index in range(count):
        link = folder / f"程序{index:02d}.lnk"
        winlink.create_shortcut(link, exes[index % len(exes)])
        links.append(link)
    return links



def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-icon-page"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    links = build_links(base, 40)          # 40 个 > 一页 28 个

    from qt_compat import QApplication

    app = QApplication([])
    import config as config_mod

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(base), "page_size": 28})

    import engine
    from desktop_browser import DesktopBrowser

    # 用真实快捷方式构造条目
    items = []
    for link in links:
        items.append(engine.RepoItem(link, link.stem, False, "shortcut",
                                     link.stat().st_size, link.stat().st_mtime))

    browser = DesktopBrowser(cfg)
    browser.resize(900, 620)
    browser.set_items(items)
    app.processEvents()

    print("── 1. 第一页图标加载 ──")
    first_keys = [str(t.item.path) for t in browser._tiles]
    # 判据用"是否进了内存缓存"：占位图也是非空 pixmap，拿 pixmap 判断会误判
    deadline = time.time() + 40
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if all(browser.loader.cached(k) is not None for k in first_keys):
            break
    app.processEvents()

    first_ready = sum(1 for k in first_keys if browser.loader.cached(k) is not None)
    check("第一页 28 个图标全部取到", first_ready == 28, f"{first_ready}/28")
    check("每页 28 个", len(browser._tiles) == 28, str(len(browser._tiles)))
    check("第一页卡片都贴上了图",
          all(t.icon_label.pixmap() is not None
              and not t.icon_label.pixmap().isNull() for t in browser._tiles))
    cached_before = browser.loader.cached_count()
    check("图标进了内存缓存", cached_before >= 28, str(cached_before))

    print()
    print("── 2. 翻到第 2 页 ──")
    browser.goto_page(1)
    app.processEvents()
    second_keys = [str(t.item.path) for t in browser._tiles]
    deadline = time.time() + 40
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if all(browser.loader.cached(k) is not None for k in second_keys):
            break
    app.processEvents()
    second_ready = sum(1 for k in second_keys if browser.loader.cached(k) is not None)
    check("第 2 页 12 个图标全部取到", second_ready == 12, f"{second_ready}/12")
    check("页码为 2/2", browser.page_label.text() == "2 / 2", browser.page_label.text())

    # 关键断言：第 1 页用过的图标不能被清掉
    still_cached = [k for k in first_keys if browser.loader.cached(k) is not None]
    check("翻页后第 1 页的图标仍在内存缓存里（这就是 bug 点）",
          len(still_cached) == len(first_keys),
          f"{len(still_cached)}/{len(first_keys)} 还在")

    print()
    print("── 3. 翻回第 1 页（bug 现场）──")
    browser.goto_page(0)
    # 只跑一帧：修复后图标应直接从缓存贴上，不需要重新去 Shell 取
    app.processEvents()
    ready_now = sum(1 for t in browser._tiles
                    if t.icon_label.pixmap() is not None
                    and not t.icon_label.pixmap().isNull())
    check("翻回第 1 页后图标立刻可用（不需要重新提取）", ready_now == 28,
          f"{ready_now}/28")

    print()
    print("── 4. 反复翻页不应该把图标翻没 ──")
    for round_index in range(3):
        browser.goto_page(1)
        app.processEvents()
        browser.goto_page(0)
        app.processEvents()
    ready_after = sum(1 for t in browser._tiles
                      if t.icon_label.pixmap() is not None
                      and not t.icon_label.pixmap().isNull())
    check("来回翻 3 轮后第 1 页图标依然齐全", ready_after == 28,
          f"{ready_after}/28")

    print()
    print("── 5. 搜索过滤后再回来也要有图标 ──")
    browser.search.setText("程序1")
    browser._rebuild()
    app.processEvents()
    search_keys = [str(t.item.path) for t in browser._tiles]
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if all(browser.loader.cached(k) is not None for k in search_keys):
            break
    filtered_ready = sum(1 for k in search_keys if browser.loader.cached(k) is not None)
    check("搜索结果的图标也能加载", filtered_ready == len(browser._tiles),
          f"{filtered_ready}/{len(browser._tiles)}")
    browser.clear_search()
    app.processEvents()          # 同样只跑一帧
    back_ready = sum(1 for t in browser._tiles
                     if t.icon_label.pixmap() is not None
                     and not t.icon_label.pixmap().isNull())
    check("清空搜索后图标立刻恢复", back_ready == 28, f"{back_ready}/28")

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
