#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6 · 微交互与动画精修 —— 验收自检
======================================
需求的原则只有一句：**动画服务于交互，而不是装饰**。所以这一套用例
检查的不是"有没有动画"，而是：

1. 时长都在需求给的区间里（悬停 150~200、翻页 200~250）
2. 缓动是 ease-out，而且就是 `theme.EASING` 那一条（不是各写各的）
3. 悬停是**过渡**，不是瞬变；底色画在内容下面（不把字染灰）
4. Toast 进场是 fade + 上抬 8px，退场只有 fade
5. 翻页只淡入、**不动位置**
6. 对话框是 fade + 0.96→1.0 的轻微缩放
7. 按钮按下只有亮度变化（`:pressed`），没有缩放
8. Dock 弹簧参数没被动过（需求七：已经很好就不要改）
9. 拖拽四种情况：快速移动 / 反向移动 / 连续跨越 / 快速松开
10. 禁止项：没有无限动画、没有动画 width/height、没有大面积模糊/发光

用法：python dev/test_phase6.py
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
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


def pump(app, seconds: float = 0.25) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def pump_until_rest(app, dock, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if not dock._anim_timer.isActive():      # noqa: SLF001
            return True
        time.sleep(0.004)
    return False


def avg_red(image, rect) -> float:
    """一块区域的平均红通道（用来判断"变亮还是变暗"）。"""
    total = 0.0
    count = 0
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            total += image.pixelColor(x, y).red()
            count += 1
    return total / count if count else 0.0


def main() -> int:
    from qt_compat import (QApplication, QColor, QLabel, QPoint, QVariantAnimation,
                           QWidget)

    app = QApplication([])

    import anim as anim_mod
    import theme as theme_mod

    # ==================================================================
    section("1. 时长 token 都落在需求给的区间里")
    # ==================================================================
    D = theme_mod.DURATION
    check("悬停 150~200ms", 150 <= D["hover"] <= 200, str(D["hover"]))
    check("翻页 / 标签切换 200~250ms", 200 <= D["page"] <= 250, str(D["page"]))
    check("提示进场 150~300ms", 150 <= D["toast_in"] <= 300, str(D["toast_in"]))
    check("提示退场 150~300ms", 150 <= D["toast_out"] <= 300, str(D["toast_out"]))
    check("对话框进场 150~250ms", 150 <= D["dialog"] <= 250, str(D["dialog"]))
    check("所有时长都是正整数",
          all(isinstance(v, int) and v > 0 for v in D.values()), str(sorted(D)))
    check("交互反馈都不超过 400ms（动画不许拖住操作）",
          max(D[k] for k in ("hover", "page", "toast_in", "toast_out",
                             "dialog")) <= 400, str(D))

    # ==================================================================
    section("2. 缓动：ease-out，而且就是 theme.EASING 那一条")
    # ==================================================================
    curve = anim_mod.ease_curve()
    check("用上了贝塞尔曲线（不是默认的线性）",
          curve.type() == curve.Type.BezierSpline, str(curve.type()))
    check("是 ease-out：前段走得快（progress 0.3 时已过半）",
          curve.valueForProgress(0.3) > 0.5,
          f"{curve.valueForProgress(0.3):.3f}")
    check("端点对齐（0→0，1→1）",
          abs(curve.valueForProgress(0.0)) < 0.01
          and abs(curve.valueForProgress(1.0) - 1.0) < 0.01)
    check("单调不减（不会来回弹）",
          all(curve.valueForProgress(i / 20.0)
              <= curve.valueForProgress((i + 1) / 20.0) for i in range(20)))

    # 换一条曲线，Qt 这边应该跟着变 —— 证明两者是同一份配置
    original = theme_mod.EASING
    theme_mod.EASING = "cubic-bezier(0.50, 0.00, 1.00, 0.50)"     # ease-in
    slow = anim_mod.ease_curve().valueForProgress(0.3)
    theme_mod.EASING = original
    check("改 theme.EASING，Qt 这边的曲线跟着变（同一份配置）",
          slow < 0.3, f"{slow:.3f}")
    check("恢复之后又是 ease-out",
          anim_mod.ease_curve().valueForProgress(0.3) > 0.5)

    # ==================================================================
    section("3. 悬停：160ms 淡进来，且画在内容下面")
    # ==================================================================
    # ⚠️ 用 QFrame 而不是裸 QWidget 当宿主：裸 QWidget 的 QSS 背景要靠
    #    `WA_StyledBackground` 才画（项目里踩过这个坑，见 README）。
    from qt_compat import QFrame, QRect, Qt

    host = QFrame()
    host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    host.resize(160, 80)
    host.setStyleSheet("background: #202020;")
    block = QLabel(host)
    block.setStyleSheet("background: #FF0000;")
    block.setGeometry(12, 12, 40, 24)
    host.show()
    pump(app, 0.05)

    veil = anim_mod.HoverVeil(host, QColor(0, 0, 0, 150), radius=8)
    check("悬停层的时长取 DURATION['hover']",
          veil._anim.duration() == D["hover"], str(veil._anim.duration()))
    check("起始是透明的", veil.value == 0.0, f"{veil.value}")
    check("覆盖整个宿主（尺寸跟着宿主）", veil.geometry() == host.rect(),
          str(veil.geometry()))

    plain = host.grab().toImage()
    veil.enter()
    check("一触发就开始走过渡（不是瞬变）",
          veil._anim.state() == QVariantAnimation.State.Running,
          str(veil._anim.state()))
    pump(app, D["hover"] / 1000.0 + 0.12)
    check("过渡结束停在 1.0", abs(veil.value - 1.0) < 0.02, f"{veil.value:.2f}")

    hovered = host.grab().toImage()
    bg_rect = QRect(block.x() + block.width() + 10, block.y(),
                    50, block.height())
    before_bg = avg_red(plain, bg_rect)
    after_bg = avg_red(hovered, bg_rect)
    check("背景区域真的变暗了（底色画出来了）",
          after_bg < before_bg - 3, f"{before_bg:.0f} → {after_bg:.0f}")

    probe = block.geometry().center()
    before_px = plain.pixelColor(probe)
    after_px = hovered.pixelColor(probe)
    check("悬停层在内容**下面**：色块一点没被染色",
          before_px.getRgb() == after_px.getRgb(),
          f"{before_px.getRgb()} → {after_px.getRgb()}")

    veil.press()
    pressed = avg_red(host.grab().toImage(), bg_rect)
    check("按下时底色加深（亮度变化，不缩放）", pressed < after_bg - 1,
          f"{after_bg:.0f} → {pressed:.0f}")
    veil.release()
    veil.leave()
    pump(app, D["hover"] / 1000.0 + 0.12)
    check("离开后淡回透明（不是啪一下消失）", veil.value < 0.02,
          f"{veil.value:.2f}")
    check("离开后画面回到最初", host.grab().toImage() == plain)
    host.hide()

    # ==================================================================
    section("4. Toast：进场 fade + 上抬 8px，退场只有 fade")
    # ==================================================================
    from widgets import Toast

    host2 = QWidget()
    host2.resize(420, 260)
    host2.show()
    pump(app, 0.05)
    toast = Toast(host2)
    toast.show_message("✓ 已收纳\n60 个项目")
    check("进场时停在目标位置**下方** 8px",
          toast.y() - toast._base_pos.y() == toast.ENTER_RISE,
          f"{toast.y()} vs {toast._base_pos.y()}")
    check("进场时不透明度从 0 开始", toast._effect.opacity() < 0.5,
          f"{toast._effect.opacity():.2f}")
    pump(app, D["toast_in"] / 1000.0 + 0.12)
    check("抬到位（差 0px）", toast.y() == toast._base_pos.y(),
          f"{toast.y()} vs {toast._base_pos.y()}")
    check("淡到完全不透明", toast._effect.opacity() > 0.98,
          f"{toast._effect.opacity():.2f}")
    check("进场时长取 DURATION['toast_in']",
          toast._slide.duration() == D["toast_in"], str(toast._slide.duration()))

    y_before_exit = toast.y()
    toast.dismiss()
    pump(app, 0.06)
    check("退场时位置一动不动（只 fade）", toast.y() == y_before_exit,
          f"{toast.y()} vs {y_before_exit}")
    check("退场在往透明走", toast._effect.opacity() < 0.9,
          f"{toast._effect.opacity():.2f}")
    pump(app, D["toast_out"] / 1000.0 + 0.12)
    check("退场结束就隐藏", toast.isHidden())
    host2.hide()

    # ==================================================================
    section("5. 翻页：只淡入，不动位置")
    # ==================================================================
    base = Path(tempfile.gettempdir()) / "nest-phase6"
    shutil.rmtree(base, ignore_errors=True)
    desktop = base / "Desktop"
    desktop.mkdir(parents=True)
    for index in range(20):
        (desktop / f"文件{index}.txt").write_text("x", encoding="utf-8")

    import config as config_mod

    config_mod._DATA_DIR = base / "data"
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "PublicDesktop"
    (base / "PublicDesktop").mkdir(parents=True, exist_ok=True)

    import engine
    import nest
    import desktop_browser as db_mod

    nest.nest_root = lambda: base / ".nest"
    nest.ensure_dirs()

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(desktop), "page_size": 7})

    items = [engine.RepoItem(desktop / f"文件{i}.txt", f"文件{i}.txt", False,
                             "document", 1, 0.0) for i in range(20)]
    browser = db_mod.DesktopBrowser(cfg)
    browser.resize(940, 680)
    browser.set_items(items)
    browser.show()
    pump(app, 0.3)

    check("有不止一页（不然翻页测不了）", browser._page_count() > 1,
          str(browser._page_count()))
    grid = browser.grid_host
    before_pos = grid.pos()
    browser.goto_page(1)
    check("翻页起了淡入动画", grid.graphicsEffect() is not None,
          str(grid.graphicsEffect()))
    check("淡入时长取 DURATION['page']",
          grid._fade_anim.duration() == D["page"],
          str(grid._fade_anim.duration()))
    check("淡入过程中位置没变（需求：不要明显位移）",
          grid.pos() == before_pos, f"{grid.pos()} vs {before_pos}")
    pump(app, D["page"] / 1000.0 + 0.2)
    check("动画结束后位置仍然没变", grid.pos() == before_pos,
          f"{grid.pos()} vs {before_pos}")
    check("动画结束后把离屏渲染摘掉了（否则滚动会白花性能）",
          grid.graphicsEffect() is None, str(grid.graphicsEffect()))
    # 搜索 / 筛选也会重建，但那条路**不**淡入——每敲一个字闪一下就成了噪音
    browser.search.setText("文件1")
    pump(app, 0.3)
    check("搜索重建不触发翻页动画（只有翻页才淡入）",
          grid.graphicsEffect() is None, str(grid.graphicsEffect()))
    browser.search.setText("")
    pump(app, 0.2)

    # ==================================================================
    section("6. 对话框：fade + 轻微缩放（0.96 → 1.0）")
    # ==================================================================
    from settings import SettingsDialog

    dialog = SettingsDialog(cfg)
    dialog.show()
    pump(app, 0.02)
    intro = getattr(dialog, "_intro_anim", None)
    check("对话框进场动画存在", intro is not None, str(intro))
    if intro is not None:
        check("时长取 DURATION['dialog']", intro.duration() == D["dialog"],
              str(intro.duration()))
        check("进场时窗口比最终尺寸小一点（0.96 档）",
              dialog.width() < dialog.sizeHint().width()
              or dialog.height() < dialog.sizeHint().height(),
              f"{dialog.size()} vs {dialog.sizeHint()}")
        pump(app, D["dialog"] / 1000.0 + 0.2)
        check("放大到位",
              dialog.width() >= dialog.sizeHint().width() - 2,
              f"{dialog.width()} vs {dialog.sizeHint().width()}")
        check("不透明度回到 1.0", abs(dialog.windowOpacity() - 1.0) < 0.01,
              str(dialog.windowOpacity()))
        first = dialog.geometry()
        dialog.hide()
        dialog.show()
        pump(app, 0.05)
        check("第二次显示不再重播（动画只用来表示「出现一次」）",
              dialog.geometry() == first, f"{dialog.geometry()} vs {first}")
    dialog.close()

    # ==================================================================
    section("7. 按钮按下：亮度变化，不缩放")
    # ==================================================================
    sheet = theme_mod.stylesheet(False)
    for name in ("QPushButton:pressed", "QToolButton:pressed",
                 "QPushButton#Primary:pressed", "#AppButton:pressed",
                 "#DockIcon:pressed"):
        check(f"有 {name} 规则", name + " {" in sheet)

    def rule_color(selector: str) -> str:
        body = sheet.split(selector + " {")[1].split("}")[0]
        for line in body.splitlines():
            if "background" in line:
                return line.split("background:")[1].strip().rstrip(";")
        return ""

    normal = rule_color("QPushButton#Primary")
    pressed = rule_color("QPushButton#Primary:pressed")
    check("按下色和常态色不一样（真的能看出来）",
          bool(normal) and bool(pressed) and normal != pressed,
          f"{normal} → {pressed}")

    button = db_mod.AppButton("记事本", desktop / "文件0.txt",
                              theme_mod.palette(False))
    check("悬停动画动的是 iconSize，不是几何尺寸",
          button._icon_anim.propertyName() in (b"iconSize", "iconSize"),
          str(button._icon_anim.propertyName()))
    check("悬停放大比例在 1.0~1.15 之间（需求：不要超过 1.15）",
          1.0 < db_mod.APP_HOVER_SCALE <= 1.15, str(db_mod.APP_HOVER_SCALE))
    check("悬停动画用的是统一那条缓动",
          button._icon_anim.easingCurve().type()
          == anim_mod.ease_curve().type(),
          str(button._icon_anim.easingCurve().type()))
    browser.hide()

    # ==================================================================
    section("8. Dock 弹簧：参数没动（需求七：已经很好就不要改）")
    # ==================================================================
    import dock as dock_mod

    check("让位弹簧仍是 stiffness=340 / ratio=0.80",
          dock_mod.REORDER_SPRING["stiffness"] == 340.0
          and abs(dock_mod.REORDER_SPRING["ratio"] - 0.80) < 1e-6,
          str(dock_mod.REORDER_SPRING))
    check("被拖图标仍是 stiffness=2600 / ratio=1.0",
          dock_mod.DRAGGED_SPRING["stiffness"] == 2600.0
          and abs(dock_mod.DRAGGED_SPRING["ratio"] - 1.0) < 1e-6,
          str(dock_mod.DRAGGED_SPRING))
    check("菜单栏仍然不画任何东西（Phase 4 的纯透明底板）",
          "paintEvent" not in vars(dock_mod.DockBar))

    # ==================================================================
    section("9. 拖拽四种情况：快速移动 / 反向移动 / 连续跨越 / 快速松开")
    # ==================================================================
    import winlink

    drag_desktop = base / "DragDesktop"
    drag_desktop.mkdir(parents=True, exist_ok=True)
    for index in range(4):
        winlink.create_shortcut(drag_desktop / f"软件{index}.lnk",
                                r"C:\Windows\System32\notepad.exe")

    drag_cfg = config_mod.Config(base / "dragcfg")
    drag_cfg.update({"desktop": str(drag_desktop), "dock_visible": True})
    for link in sorted(drag_desktop.glob("*.lnk")):
        drag_cfg.add_quick(link, link.stem)

    dock = dock_mod.DockBar(drag_cfg)
    dock.show_bar()
    pump(app, 0.4)

    buttons = dock._app_buttons
    check("拖拽用例：有 4 个常用项", len(buttons) == 4, str(len(buttons)))
    if len(buttons) == 4:
        def center_of(widget) -> QPoint:
            return widget.mapToGlobal(QPoint(widget.width() // 2,
                                             widget.height() // 2))

        def slot_center(index: int) -> QPoint:
            origin = dock.apps_flow.mapToGlobal(QPoint(0, 0))
            slot = dock._slots[index]
            button = dock._app_buttons[index]
            return QPoint(origin.x() + int(slot[0]) + button.width() // 2,
                          origin.y() + int(slot[1]) + button.height() // 2)

        def order() -> "list[str]":
            return [entry["name"] for entry in drag_cfg.quick_items]

        src = buttons[0]
        press = center_of(src)
        dock._on_icon_press(src, press)
        dock._on_icon_hold(src, press)
        pump(app, 0.05)

        dock._on_icon_move(src, slot_center(3))
        check("快速移动：一步跨 3 格，目标槽位立刻 = 3",
              dock._reorder_to == 3, str(dock._reorder_to))

        dock._on_icon_move(src, slot_center(1))
        check("反向移动：目标槽位立刻 = 1", dock._reorder_to == 1,
              str(dock._reorder_to))

        seen = []
        for index in (2, 3, 2, 1):
            dock._on_icon_move(src, slot_center(index))
            seen.append(dock._reorder_to)
        check("连续跨越：0→2→3→2→1 每一格都跟上了", seen == [2, 3, 2, 1],
              str(seen))

        dock._on_icon_move(src, slot_center(2))
        check("松手前让位动画确实还在跑", dock._anim_timer.isActive())
        dock._on_icon_release(src, slot_center(2))
        check("快速松开：配置顺序当场就写好了（不用等动画）",
              order()[2] == "软件0", str(order()))
        pump_until_rest(app, dock)
        check("快速松开：配置顺序没被回弹改回去",
              order()[2] == "软件0", str(order()))
        xs = [button.x() for button in dock._app_buttons]
        slots = [int(slot[0]) for slot in dock._slots] if dock._slots else []
        check("回弹结束后每个图标都落在某个槽位上",
              not slots or sorted(xs) == sorted(slots), f"{xs} vs {slots}")
        check("弹簧表清空（交接完成）", not dock._springs,
              str(len(dock._springs)))
        dock.hide_bar()

    # ==================================================================
    section("10. 禁止项：无限动画 / 动画尺寸 / 大面积模糊")
    # ==================================================================
    sources = {}
    for name in ("anim.py", "widgets.py", "desktop_browser.py", "dock.py",
                 "panel.py", "settings.py", "tray_app.py"):
        path = HERE / name
        if path.is_file():
            sources[name] = path.read_text(encoding="utf-8")

    check("没有任何无限循环的动画（setLoopCount(-1) / Infinite）",
          not any("setLoopCount(-1)" in text or "Infinite" in text
                  for text in sources.values()))
    check("anim.py 不动 width / height / 布局（只动 opacity 与 pos）",
          not any(token in sources.get("anim.py", "")
                  for token in ("setFixedWidth", "setFixedHeight", "resize(",
                                "setMinimumWidth", "setMaximumWidth")))
    check("全项目没有实例化阴影/发光效果（Phase 4 已删掉 Dock 那层）",
          not any("QGraphicsDropShadowEffect(" in text
                  for text in sources.values()))
    check("没有粒子 / 模糊这类装饰动画",
          not any("particle" in text.lower() or "BlurEffect" in text
                  for text in sources.values()))
    check("anim.py 里没有自己的定时器（动画都挂在具体控件上）",
          "QTimer" not in sources.get("anim.py", ""))

    # ==================================================================
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for label in FAIL:
            print(f"  ✗ {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
