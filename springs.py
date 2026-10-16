#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
弹簧动画（spring physics）
==========================

一个极小的、**完全不依赖 Qt** 的弹簧积分器，专门给 Dock 的拖拽排序用。
纯数学、可单独测，所以放在独立模块里。

为什么不用 `QPropertyAnimation`
-------------------------------
`QPropertyAnimation` 是**关键帧插值**：它只知道"从 A 到 B 用多久"，
不知道速度。放到拖拽排序这种场景就有三个硬伤：

1. **改目标必须重启**。拖动时目标位置一直在变，每次 `stop()+start()`
   都会把速度清零 —— 表现就是图标"顿一下再走"。
2. **没有惯性**。让位是匀速平移，看起来像瞬移，没有 Nexus / macOS Dock
   那种"被弹开"的重量感。
3. **一个属性只能有一个动画**。想同时控制 x 和 y 就得两个动画互相抢，
   这正是"避免 CSS transition 与 JS spring 同时控制同一个 transform"
   在 Qt 里的对应问题。

弹簧积分器每帧只做一件事：**朝目标加速，同时被阻尼拉住**。
改目标只要改一个数，速度天然连续，所以高频 pointermove 下也不会抖。

数值方法
--------
用 **semi-implicit Euler**（先更新速度，再用**新**速度更新位置）：

    a = (k * (target - x) - c * v) / m
    v += a * dt
    x += v * dt

它比显式 Euler 稳定得多（显式版在刚度大时会发散）。再配合子步长
（substep）把一帧切成几小步，帧率波动时也不会炸。

阻尼比 `ratio`
--------------
`c = 2 * ratio * sqrt(k * m)`，也就是临界阻尼的 `ratio` 倍：

* `ratio = 1.0` → 临界阻尼，最快到达且**不过冲**；
* `ratio = 0.75 ~ 0.9` → 略微过冲，就是"弹一下"的手感（让位的图标用这个）；
* `ratio < 0.5` → 会来回振荡好几下，做 UI 太吵。

用法::

    point = SpringPoint(0.0, 0.0, stiffness=320, ratio=0.82)
    point.move_to(120.0, 0.0)          # 拖拽中随时改目标
    while advance([point], 1 / 60):    # 每帧推进一次，返回"还在动吗"
        widget.move(round(point.x), round(point.y))
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------------
# 默认参数（Dock 实测手感，见 dock.py 里的 REORDER_SPRING / DRAGGED_SPRING）
# --------------------------------------------------------------------------
DEFAULT_STIFFNESS = 320.0
DEFAULT_RATIO = 0.82
DEFAULT_MASS = 1.0

#: 一帧最多切多细。1/240 秒远小于 60fps 的 1/60，
#: 保证 `k` 取到几千时 `ω·h` 仍然很小（semi-implicit Euler 的稳定条件是 ω·h < 2）。
MAX_SUBSTEP = 1.0 / 240.0

#: 单帧最大推进时间。掉帧 / 断点调试之后 `dt` 可能是好几秒，
#: 直接喂给积分器会让弹簧"炸开"，所以夹住。
MAX_FRAME = 0.05


def damping_for(stiffness: float, ratio: float, mass: float = DEFAULT_MASS) -> float:
    """由刚度与阻尼比算出阻尼系数 `c = 2 * ratio * sqrt(k * m)`。"""
    return 2.0 * float(ratio) * math.sqrt(max(0.0, float(stiffness) * float(mass)))


class Spring:
    """一个带速度的一维弹簧。"""

    __slots__ = ("value", "target", "velocity", "stiffness", "damping", "mass")

    def __init__(self, value: float = 0.0, *, stiffness: float = DEFAULT_STIFFNESS,
                 ratio: float = DEFAULT_RATIO, mass: float = DEFAULT_MASS,
                 damping: "float | None" = None):
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0
        self.stiffness = float(stiffness)
        self.mass = float(mass)
        self.damping = (float(damping) if damping is not None
                        else damping_for(stiffness, ratio, mass))

    # ---- 控制 ---------------------------------------------------------
    def move_to(self, target: float) -> None:
        """改目标。**不重置速度** —— 这是它比关键帧动画更适合拖拽的原因。"""
        self.target = float(target)

    def snap(self, value: float) -> None:
        """直接落到某处并停住（取消动画 / 让位交接时用）。"""
        self.value = self.target = float(value)
        self.velocity = 0.0

    def tune(self, *, stiffness: "float | None" = None,
             ratio: "float | None" = None,
             damping: "float | None" = None) -> None:
        """换一组手感参数（刚度 / 阻尼比 / 阻尼系数，后写的优先）。

        只给 `stiffness` 时按**原来的阻尼比**同步阻尼，免得手感突然变"硬"。

        ⚠️ 顺序有讲究：原阻尼比必须用**改之前**的刚度算。
        先写 `self.stiffness` 再算比值的话，`ratio_now` 会被除错一次，
        换来的阻尼系数完全不对（实测 k:100→400 时阻尼纹丝不动，
        临界阻尼悄悄变成了欠阻尼 0.5）。
        """
        if stiffness is not None:
            if damping is None and ratio is None:
                ratio = self.ratio()
            self.stiffness = float(stiffness)
        if damping is not None:
            self.damping = float(damping)
        elif ratio is not None:
            self.damping = damping_for(self.stiffness, ratio, self.mass)

    def ratio(self) -> float:
        """当前的阻尼比 `ζ = c / (2·sqrt(k·m))`。"""
        return self.damping / max(1e-9, 2.0 * math.sqrt(max(1e-9, self.stiffness) * self.mass))

    # ---- 积分 ---------------------------------------------------------
    def step(self, dt: float) -> None:
        """推进 `dt` 秒（semi-implicit Euler）。"""
        accel = (self.stiffness * (self.target - self.value)
                 - self.damping * self.velocity) / self.mass
        self.velocity += accel * dt
        self.value += self.velocity * dt

    def resting(self, *, eps_pos: float = 0.4, eps_vel: float = 0.8) -> bool:
        """够近了、也够慢了，就算停住了。

        阈值不能太小：`QWidget.move()` 收整数，亚像素的残余振动既看不见、
        又会让定时器永远停不下来（一直 60fps 重绘，白烧 CPU）。
        """
        return (abs(self.target - self.value) <= eps_pos
                and abs(self.velocity) <= eps_vel)


class SpringPoint:
    """二维弹簧：x / y 各自独立积分，但共享同一组手感参数。

    两个轴**必须互相独立**（各自有自己的速度），否则横向拖动会污染纵向、
    让图标在竖直方向莫名地抖。
    """

    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0, *,
                 stiffness: float = DEFAULT_STIFFNESS,
                 ratio: float = DEFAULT_RATIO,
                 mass: float = DEFAULT_MASS):
        self.x = Spring(x, stiffness=stiffness, ratio=ratio, mass=mass)
        self.y = Spring(y, stiffness=stiffness, ratio=ratio, mass=mass)

    def move_to(self, x: float, y: float) -> None:
        self.x.move_to(x)
        self.y.move_to(y)

    def snap(self, x: float, y: float) -> None:
        self.x.snap(x)
        self.y.snap(y)

    def tune(self, **kwargs) -> None:
        self.x.tune(**kwargs)
        self.y.tune(**kwargs)

    def step(self, dt: float) -> None:
        self.x.step(dt)
        self.y.step(dt)

    def resting(self) -> bool:
        return self.x.resting() and self.y.resting()


def advance(points, dt: float, *, substep: float = MAX_SUBSTEP) -> bool:
    """把一组弹簧推进 `dt` 秒；返回**是否还有在动的**。

    一帧切成若干子步，是为了让刚度大的弹簧（比如"跟手"的被拖图标，
    `k` 到几千）在 60fps 下也不会因为步长太大而数值发散。
    """
    points = list(points)
    if not points:
        return False
    dt = max(0.0, min(float(dt), MAX_FRAME))
    if dt <= 0.0:
        return any(not p.resting() for p in points)
    steps = max(1, int(math.ceil(dt / substep)))
    h = dt / steps
    for _ in range(steps):
        for point in points:
            point.step(h)
    return any(not p.resting() for p in points)
