#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
弹簧积分器（springs.py）的纯数学自检
====================================
Dock 的拖拽排序全靠这套积分器。它不依赖 Qt，所以可以脱开界面单独验：
阻尼比的手感、改目标时速度连不连续、大刚度 + 掉帧会不会数值发散。

用法：python dev/test_springs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "libs"))

import springs                                            # noqa: E402

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def run(point, seconds: float, fps: int = 60):
    """按固定帧率把弹簧推到 `seconds` 秒，返回走过的帧数（不够就提前结束）。"""
    dt = 1.0 / fps
    frames = 0
    for _ in range(int(seconds * fps)):
        frames += 1
        if not springs.advance([point], dt):
            break
    return frames


def main() -> int:
    print("── 1. 临界阻尼：到点即停，绝不过冲 ──")
    p = springs.SpringPoint(0.0, 0.0, stiffness=320.0, ratio=1.0)
    p.move_to(100.0, 0.0)
    peak = 0.0
    for _ in range(120):
        springs.advance([p], 1 / 60)
        peak = max(peak, p.x.value)
    check("临界阻尼不过冲（峰值 ≤ 100.5）", peak <= 100.5, f"peak={peak:.3f}")
    check("最终停在目标上", abs(p.x.value - 100.0) <= 0.4, f"{p.x.value:.3f}")

    print()
    print('── 2. 欠阻尼：会轻轻过冲一下（"弹一下"的手感） ──')
    p = springs.SpringPoint(0.0, 0.0, stiffness=340.0, ratio=0.80)
    p.move_to(100.0, 0.0)
    peak = 0.0
    for _ in range(180):
        springs.advance([p], 1 / 60)
        peak = max(peak, p.x.value)
    check("欠阻尼确实过冲（峰值 > 100）", peak > 100.0, f"peak={peak:.3f}")
    check('过冲幅度克制（峰值 < 115，不然就是"晃"）', peak < 115.0, f"peak={peak:.3f}")
    check("最终仍然收敛到目标", abs(p.x.value - 100.0) <= 0.4, f"{p.x.value:.3f}")

    print()
    print("── 3. 收敛速度：让位要在 ~0.3s 内到位 ──")
    p = springs.SpringPoint(0.0, 0.0, stiffness=340.0, ratio=0.80)
    p.move_to(100.0, 0.0)
    frames = run(p, 2.0)
    check(f"0.6 秒内彻底停下（实际 {frames} 帧 ≈ {frames / 60:.2f}s）",
          frames <= 36, str(frames))

    print()
    print("── 4. move_to 不重置速度（改目标时运动必须连续） ──")
    p = springs.SpringPoint(0.0, 0.0, stiffness=320.0, ratio=1.0)
    p.move_to(100.0, 0.0)
    springs.advance([p], 1 / 60)
    springs.advance([p], 1 / 60)
    v_before = p.x.velocity
    p.move_to(300.0, 0.0)          # 拖拽中目标一直在变，这是常态
    check("改目标后速度没有被清零", abs(p.x.velocity - v_before) < 1e-9,
          f"{p.x.velocity} vs {v_before}")
    check("速度确实不是 0（否则测不出东西）", abs(v_before) > 1e-6, str(v_before))

    print()
    print("── 5. snap：直接落地并停住 ──")
    p = springs.SpringPoint(0.0, 0.0)
    p.move_to(500.0, 500.0)
    springs.advance([p], 1 / 60)
    p.snap(12.0, 34.0)
    check("位置直接落到指定值", (p.x.value, p.y.value) == (12.0, 34.0),
          f"{p.x.value},{p.y.value}")
    check("速度被清零", p.x.velocity == 0.0 and p.y.velocity == 0.0)
    check("已经静止（resting）", p.resting())

    print()
    print("── 6. tune：只改刚度时按原阻尼比同步阻尼 ──")
    p = springs.SpringPoint(0.0, 0.0, stiffness=100.0, ratio=1.0)
    p.tune(stiffness=400.0)
    expected = springs.damping_for(400.0, 1.0)
    check("阻尼跟着刚度同步（仍保持临界阻尼）",
          abs(p.x.damping - expected) < 1e-6, f"{p.x.damping} vs {expected}")

    print()
    print("── 7. 大刚度 + 大 dt：不能数值发散 ──")
    # 被拖的图标刚度 2600，跟随延迟要短；掉帧时 dt 可能到 0.05
    p = springs.SpringPoint(0.0, 0.0, stiffness=2600.0, ratio=1.0)
    p.move_to(100.0, 0.0)
    peak = 0.0
    for _ in range(60):
        springs.advance([p], 0.05)          # 相当于 20fps
        peak = max(peak, p.x.value)
    check("20fps 下也没炸（峰值 < 130）", peak < 130.0, f"peak={peak:.3f}")
    check("20fps 下仍然收敛", abs(p.x.value - 100.0) <= 0.4, f"{p.x.value:.3f}")

    print()
    print("── 8. MAX_FRAME：一帧超长 dt 被夹住 ──")
    a = springs.SpringPoint(0.0, 0.0, stiffness=2600.0, ratio=1.0)
    b = springs.SpringPoint(0.0, 0.0, stiffness=2600.0, ratio=1.0)
    a.move_to(100.0, 0.0)
    b.move_to(100.0, 0.0)
    springs.advance([a], 5.0)               # 断点调试之后的一帧
    springs.advance([b], springs.MAX_FRAME)
    check("超长 dt 被夹到 MAX_FRAME（结果与 0.05 一致）",
          abs(a.x.value - b.x.value) < 1e-9, f"{a.x.value} vs {b.x.value}")

    print()
    print("── 9. advance 的返回值 ──")
    idle = springs.SpringPoint(5.0, 5.0)
    check("全部静止时返回 False", springs.advance([idle], 1 / 60) is False)
    check("空列表返回 False", springs.advance([], 1 / 60) is False)
    moving = springs.SpringPoint(0.0, 0.0, stiffness=320.0)
    moving.move_to(100.0, 0.0)
    check("有在动的就返回 True", springs.advance([moving], 1 / 60) is True)

    print()
    print("── 10. x / y 两轴独立（横向拖动不能污染纵向） ──")
    p = springs.SpringPoint(0.0, 7.0, stiffness=320.0)
    p.move_to(100.0, 7.0)                   # 只动 x
    for _ in range(10):
        springs.advance([p], 1 / 60)
    check("y 纹丝不动", p.y.value == 7.0 and p.y.velocity == 0.0,
          f"y={p.y.value} v={p.y.velocity}")
    check("x 已经在路上", p.x.value > 0.0, str(p.x.value))

    print()
    print('── 11. 刚度越大跟得越紧（"跟手"就是这么来的） ──')
    soft = springs.SpringPoint(0.0, 0.0, stiffness=340.0, ratio=1.0)
    hard = springs.SpringPoint(0.0, 0.0, stiffness=2600.0, ratio=1.0)
    soft.move_to(100.0, 0.0)
    hard.move_to(100.0, 0.0)
    for _ in range(4):                      # 4 帧 ≈ 67ms
        springs.advance([soft, hard], 1 / 60)
    check("硬弹簧 4 帧内走了大半（≥80%）", hard.x.value >= 80.0, f"{hard.x.value:.2f}")
    check("软弹簧同一时间明显落后", soft.x.value < hard.x.value - 20.0,
          f"{soft.x.value:.2f} vs {hard.x.value:.2f}")

    print()
    print("── 12. damping_for 公式 ──")
    check("c = 2·ratio·sqrt(k·m)", abs(springs.damping_for(400.0, 0.5, 2.0)
                                      - 2 * 0.5 * (400.0 * 2.0) ** 0.5) < 1e-9)

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
