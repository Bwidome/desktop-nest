#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本轮需求的回归测试：**收纳面板图标显示不完整（会少一部分）**
============================================================

用户报的现象：收纳面板里的图标边缘被削掉一块，看起来"少一部分"。

根因（靠 `.tmp/probe*.py` 那组探针定位出来的）：

1. 有些图标**内容严丝合缝顶到画布四边** —— 实测 Discord / Apifox / MuMu
   的 256×256 原图，**最外两行两列就有 alpha=255 的像素**，一点透明余量都没有。
2. `trim_raw()` 的 `pad`（6% + 保底 4px）在这种图上**完全失效**：
   `left - pad` 被 `max(0, ...)` 夹回 0、`right + pad` 被 `min(width, ...)`
   夹回 width，裁剪窗口就等于整张画布 —— 结果是"什么也没做"。
3. 于是缩放到 40px 显示时，重采样滤波器在边界处**没有外侧像素可采**，
   边缘那圈抗锯齿过渡被直接丢弃 —— 圆形 / 圆角 / 异形轮廓的边缘
   看起来就像被削掉一圈。

修法：`trim_raw()` 裁完之后**回头检查四边余量**，不够就用新增的
`expand_raw()` **向外补一圈全透明像素**（扩张画布，而不是只裁剪）。

用法：python dev/test_round5.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import faulthandler as _fh

_fh.enable()
_fh.dump_traceback_later(180, exit=True)

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n── {title} ──")


# --------------------------------------------------------------------------
# 造图工具（不依赖真实 Shell，回归才稳）
# --------------------------------------------------------------------------
def make_circle(size: int = 256, fill_ratio: float = 1.0) -> "object":
    """画一张（半径可调的）实心圆，用来模拟"内容贴边"的图标。

    fill_ratio=1.0 → 圆的直径 = 画布边长，内容**顶到四边**（Discord 那种）。
    fill_ratio=0.5 → 圆只占中间，四周一片透明（Cpolar 那种）。
    """
    import icons

    w = h = int(size)
    data = bytearray(w * h * 4)
    radius = (w / 2.0) * float(fill_ratio)
    cx = cy = w / 2.0
    for y in range(h):
        for x in range(w):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            if dx * dx + dy * dy <= radius * radius:
                i = (y * w + x) * 4
                data[i + 0], data[i + 1], data[i + 2], data[i + 3] = 242, 101, 88, 255
    return icons.RawIcon(w, h, bytes(data), "probe")


def edge_gap(raw) -> int:
    """内容离四边最近的距离（像素）。0 = 贴边。"""
    import icons

    box = icons.content_box(raw)
    if box is None:
        return -1
    left, top, right, bottom = box
    return min(left, top, raw.width - right, raw.height - bottom)


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-round5"
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)

    # 把图标缓存引到沙盒，别污染真实缓存
    import config as config_mod

    cfg_dir = base / "cfg"
    cfg_dir.mkdir(parents=True)
    cfg = config_mod.Config(str(cfg_dir))

    import icons

    section("A. 先确认「内容贴边」这个前提是真的（不然修法没意义）")
    tight = make_circle(256, 1.0)
    check("造出来的圆形内容确实顶到画布边界",
          edge_gap(tight) == 0, f"edge_gap={edge_gap(tight)}")
    check("它的 content_box 就是整张画布",
          icons.content_box(tight) == (0, 0, 256, 256),
          str(icons.content_box(tight)))

    section("B. 旧的裁剪写法在这种图上会失效（回归的动机）")
    # 复刻旧逻辑：只做 max(0,..)/min(..) 夹取
    pad = max(icons.CROP_PAD_MIN,
              int(round(256 * icons.CROP_PAD_RATIO)))
    left, top, right, bottom = icons.content_box(tight)
    old_left = max(0, left - pad)
    old_right = min(256, right + pad)
    check("旧写法下裁剪窗口等于整张画布（pad 被夹没了）",
          (old_left, old_right) == (0, 256),
          f"{(old_left, old_right)}")
    check("也就是说旧写法「什么也没做」——留不出任何余量",
          old_left == 0 and old_right == 256)

    section("C. 修完之后：贴边的图会被向外补透明余量")
    fixed = icons.trim_raw(tight)
    check("画布被向外扩张了（不是原样返回）",
          fixed.width > 256 and fixed.height > 256,
          f"{fixed.width}x{fixed.height}")
    check("四周真的留出了余量",
          edge_gap(fixed) >= pad, f"edge_gap={edge_gap(fixed)} pad={pad}")
    check("扩张是**四边等量**的（内容仍在正中）",
          icons.content_box(fixed) == (pad, pad, 256 + pad, 256 + pad),
          str(icons.content_box(fixed)))
    check("扩张出去的部分是全透明的",
          fixed.bgra[:pad * 4] == b"\x00" * (pad * 4)
          and fixed.bgra[3] == 0)

    section("D. 内容本来就居中的图：照旧裁剪，不做无谓扩张")
    loose = make_circle(256, 0.5)
    check("造出来的图确实四周透明（前提成立）",
          edge_gap(loose) > 40, f"edge_gap={edge_gap(loose)}")
    trimmed = icons.trim_raw(loose)
    check("被裁小了（裁掉多余透明边距）",
          trimmed.width < 256 and trimmed.height < 256,
          f"{trimmed.width}x{trimmed.height}")
    # pad 按**内容**尺寸算（不是画布），这样重复调用才幂等 —— 见 icons.trim_raw。
    content_side = 128
    want_pad = max(icons.CROP_PAD_MIN,
                   int(round(content_side * icons.CROP_PAD_RATIO)))
    check("裁完也留出了余量",
          edge_gap(trimmed) >= want_pad,
          f"edge_gap={edge_gap(trimmed)} want>={want_pad}")
    check("裁完的尺寸 ≈ 内容 + 2×pad",
          abs(trimmed.width - (content_side + 2 * want_pad)) <= 2,
          f"{trimmed.width} vs {content_side + 2 * want_pad}")

    section("E. 幂等：对同一个结果再裁一次不会继续长大")
    again = icons.trim_raw(fixed)
    check("第二次 trim 没有让画布继续膨胀",
          abs(again.width - fixed.width) <= 1,
          f"{fixed.width} -> {again.width}")
    check("余量仍然够",
          edge_gap(again) >= pad, f"edge_gap={edge_gap(again)}")

    section("F. 缩到显示尺寸之后，四边仍然有采样空间（这才是用户看到的指标）")
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPixmap
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    def to_pixmap(raw):
        img = QImage(raw.bgra, raw.width, raw.height, raw.width * 4,
                     QImage.Format.Format_ARGB32)
        img._ref = raw.bgra
        return QPixmap.fromImage(img)

    for display in (40, 34):
        pm = to_pixmap(fixed).scaled(
            display, display, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        data = bytes(ptr)
        stride = img.bytesPerLine()
        w, h = img.width(), img.height()
        gaps = []
        for y in range(h):
            row = data[y * stride:y * stride + w * 4]
            xs = [x for x in range(w) if row[x * 4 + 3] > 8]
            if xs:
                gaps.append(min(xs))
                gaps.append(w - 1 - max(xs))
        gap = min(gaps) if gaps else -1
        check(f"{display}px 显示下内容没贴到边缘（有抗锯齿余量）",
              gap >= 1, f"gap={gap}")

    section("G. 真实快捷方式：拿机器上现成的 .lnk 验一遍")
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    nest = Path(os.path.expanduser("~")) / ".desktop-nest" / "desktop"
    checked = 0
    for folder in (nest, desktop):
        if checked >= 3:
            break
        if not folder.exists():
            continue
        for link in sorted(folder.glob("*.lnk")):
            raw = icons.get_icon_best(link, 64)
            if raw is None:
                continue
            checked += 1
            gap = edge_gap(raw)
            check(f"{link.name[:28]}：高清档四边有余量（gap={gap}）", gap >= 1)
            if checked >= 3:
                break
    if checked == 0:
        print("  (这台机器上没找到可验证的 .lnk，跳过 G 节)")

    section("H. 缓存版本已提升（否则升级后还是旧图）")
    check("CACHE_VERSION 已到 v5", icons.CACHE_VERSION == "v5",
          icons.CACHE_VERSION)
    a = icons.icon_key(Path("C:/x/a.lnk"), 64)
    b = icons.icon_key(Path("C:/x/b.lnk"), 64)
    check("不同路径的缓存键不同", a != b)
    check("缓存键长度稳定", len(a) == 20, str(len(a)))

    total = len(PASS) + len(FAIL)
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项" + f"（共 {total}）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
