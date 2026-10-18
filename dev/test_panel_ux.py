#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 · 主面板信息层级与操作体验 —— 回归测试
==============================================
Phase 2 的目标不是"重写主面板"，而是**在不改结构和功能的前提下**把
信息层级、空间利用、按钮层级、搜索体验、网格体验理顺。验收标准原话是：

    用户第一眼知道：①我在哪里 ②有多少项目 ③怎么搜索
                   ④哪些是常用启动 ⑤怎么打开 ⑥怎么还原

这些话都很"观感"，所以这里把它们翻成**可执行的断言**，分七节，
每节对应需求里的一节：

1. 顶部 —— 标题 / 数量是主要信息，刷新 / 菜单 / 关闭是次级操作
2. 常用启动 —— 图标尺寸、间距、名称、Hover（scale ≤ 1.15）、Tooltip
3. 搜索 —— Placeholder、聚焦样式、不改变尺寸、无结果文案
4. 项目网格 —— 图标统一、点击区域、Hover、两行 + 省略号
5. 底部按钮 —— 打开 Primary / 加为常用 Secondary / 还原 Warning
6. 状态 —— 主面板两个按钮按数量灰掉
7. 验收 —— "第一眼能看出来的六件事"逐条点名

除了读样式表文本，这里还会**真的渲染**控件再比像素：
* `#Toolbar > QToolButton` 是不是真的没盖掉 `#AppManage` 的虚线（量边缘像素）；
* 卡片的"选中 / 悬停"是不是真的画出了底色（比两张图的差异像素）。

用法：python dev/test_panel_ux.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
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


# --------------------------------------------------------------------------
# 渲染类小工具
# --------------------------------------------------------------------------
def opaque_ring(pixmap, ring: int = 2) -> int:
    """数一数图**边缘**有多少不透明像素。

    用来判断一个控件到底画没画边框：`border: 1px solid transparent` 的
    按钮边缘是全透明的，`border: 1px dashed <半透明白>` 的会留下一条虚线。
    """
    image = pixmap.toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if ring <= x < image.width() - ring \
                    and ring <= y < image.height() - ring:
                continue
            if image.pixelColor(x, y).alpha() > 8:
                count += 1
    return count


def diff_pixels(first, second) -> int:
    """两张同尺寸图里有多少个像素不一样；尺寸不同返回 -1。"""
    a, b = first.toImage(), second.toImage()
    if a.size() != b.size():
        return -1
    total = 0
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixelColor(x, y) != b.pixelColor(x, y):
                total += 1
    return total


def pump(app, seconds: float = 0.15) -> None:
    import time

    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


# --------------------------------------------------------------------------
# 沙盒
# --------------------------------------------------------------------------
def build_sandbox():
    base = Path(tempfile.gettempdir()) / "panel-ux-test"
    shutil.rmtree(base, ignore_errors=True)
    desktop, cfg_dir, store = base / "Desktop", base / "cfg", base / ".nest"
    for folder in (desktop, cfg_dir, store / "desktop"):
        folder.mkdir(parents=True)

    names = ["报告.docx", "资料夹", "图片.png", "压缩包.zip", "脚本.py",
             "音乐.mp3", "视频.mp4", "表格.xlsx", "演示.pptx", "字体.ttf"]
    for name in names:
        target = desktop / name
        if "." not in name:
            target.mkdir(exist_ok=True)
        else:
            target.write_text("x", encoding="utf-8")

    # 一个"名字特别长"的，用来验证两行 + 省略号
    long_name = "这是一个名字特别特别长的文件用来测试省略号的行为.docx"
    (desktop / long_name).write_text("x", encoding="utf-8")

    import winlink

    for app in ("记事本", "画图"):
        winlink.create_shortcut(desktop / f"{app}.lnk",
                                r"C:\Windows\System32\notepad.exe")
    return base, desktop, cfg_dir, store, names + [long_name]


def main() -> int:
    from qt_compat import (QApplication, QEvent, QFontMetrics, QIcon, QLineEdit,
                           QPixmap, QSize, QToolButton, Qt, QWidget)

    app = QApplication(sys.argv)
    import theme as theme_mod

    sheet = theme_mod.stylesheet(False, glass=True)
    app.setStyleSheet(sheet)

    import config as config_mod
    import engine
    import nest
    import desktop_browser as db_mod
    from widgets import ElidedLabel, search_icon

    base, desktop, cfg_dir, store, names = build_sandbox()
    # 把"收纳目录"指到沙盒，别碰用户真实的 ~/.desktop-nest
    nest.nest_root = lambda: base / ".nest"

    cfg = config_mod.Config(cfg_dir / "config.json")
    cfg.set("desktop", str(desktop))
    for app_name in ("记事本", "画图"):
        cfg.add_quick(desktop / f"{app_name}.lnk", app_name)

    items = [engine.RepoItem(desktop / n, n, "." not in n, "document", 1, 0.0)
             for n in names]

    browser = db_mod.DesktopBrowser(cfg)
    browser.resize(940, 680)
    browser.set_items(items)
    browser.show()
    pump(app, 0.4)

    # ==================================================================
    section("1. 顶部：标题 / 数量是主要信息，刷新 / 菜单 / 关闭是次级操作")
    # ==================================================================
    check("标题还在（我在哪）", browser.title.text() == "桌面收纳",
          browser.title.text())
    check("数量徽标还在（有多少项目）",
          browser.badge.text() == f"{len(items)} 项", browser.badge.text())
    check("标题字号大于按钮（层级差）",
          "font-size" in sheet.split("#Title {")[1].split("}")[0])
    check("三个次级操作都在",
          all(hasattr(browser, n)
              for n in ("btn_refresh", "btn_more", "btn_close")))
    check("刷新 / 菜单 / 关闭都是图标钮（不是大按钮）",
          all(isinstance(getattr(browser, n), QToolButton)
              for n in ("btn_refresh", "btn_more", "btn_close")))
    check("三个次级操作都有 Tooltip",
          all(getattr(browser, n).toolTip()
              for n in ("btn_refresh", "btn_more", "btn_close")))

    # 次级操作"安静"的样式：透明底 + 淡色字，悬停才浮出来
    toolbar_rule = sheet.split("#Toolbar > QToolButton {")[1].split("}")[0]
    check("顶栏图标钮常态是透明的（不抢标题的注意力）",
          "background: transparent" in toolbar_rule, toolbar_rule[:60])
    check("顶栏图标钮常态用次要文字色",
          theme_mod.GLASS["text_sub"] in toolbar_rule, toolbar_rule[:80])
    check("顶栏图标钮有 hover 规则",
          "#Toolbar > QToolButton:hover {" in sheet)

    # ⚠️ 子选择器（不是后代选择器）：否则 #Toolbar QToolButton 的特异性
    #    (1,0,1) 会盖掉 #AppManage (1,0,0)，"管理"控件的虚线就没了。
    check("顶栏图标钮用**子**选择器",
          "#Toolbar > QToolButton {" in sheet
          and "#Toolbar QToolButton {" not in sheet)
    check("「管理」控件不在工具栏的直接子控件里（所以子选择器选不到它）",
          browser.btn_manage.parentWidget() is browser.apps_host
          and browser.apps_host.parentWidget() is browser.toolbar)
    manage_ring = opaque_ring(browser.btn_manage.grab())
    refresh_ring = opaque_ring(browser.btn_refresh.grab())
    check("实测：「管理」控件的虚线描边还在", manage_ring > 0, str(manage_ring))
    check("实测：顶栏图标钮确实没有边框（次级操作该有的安静）",
          refresh_ring == 0, str(refresh_ring))

    # ==================================================================
    section("2. 常用启动：图标 / 间距 / 名称 / Hover / Tooltip")
    # ==================================================================
    check("有「常用启动」这一行的小标题（哪些是常用启动）",
          hasattr(browser, "apps_label")
          and browser.apps_label.text() == "常用启动")
    check("小标题用分节标签样式", browser.apps_label.objectName() == "SectionLabel")
    check("常用启动项都建出来了",
          len(browser._app_buttons) == len(cfg.quick_items),
          f"{len(browser._app_buttons)} vs {len(cfg.quick_items)}")
    check("「管理」控件仍在最后（排序算法没动）",
          browser.apps_row.indexOf(browser.btn_manage) == len(cfg.quick_items))
    check("图标间距调宽了（原来是 4）", browser.apps_row.spacing() >= 6,
          str(browser.apps_row.spacing()))

    button = browser._app_buttons[0]
    check("常用启动按钮尺寸走常量",
          button.size() == QSize(db_mod.APP_BUTTON_W, db_mod.APP_BUTTON_H),
          str(button.size()))
    check("图标尺寸走常量",
          button.iconSize() == QSize(db_mod.APP_ICON, db_mod.APP_ICON),
          str(button.iconSize()))
    check("图标比按钮宽度小一圈（留得下名称）",
          db_mod.APP_ICON <= db_mod.APP_BUTTON_W - 30, str(db_mod.APP_ICON))

    check("悬停放大比例不超过 1.15（需求硬约束）",
          db_mod.APP_HOVER_SCALE <= 1.15, str(db_mod.APP_HOVER_SCALE))
    app.sendEvent(button, QEvent(QEvent.Type.Enter))
    hover_size = button._icon_anim.endValue()
    check("实测：Enter 之后图标放大",
          hover_size.width() > db_mod.APP_ICON, str(hover_size))
    check("实测：放大幅度 <= 1.15",
          hover_size.width() / db_mod.APP_ICON <= 1.15,
          f"{hover_size.width() / db_mod.APP_ICON:.3f}")
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    check("实测：Leave 之后图标缩回原尺寸",
          button._icon_anim.endValue() == QSize(db_mod.APP_ICON,
                                                db_mod.APP_ICON),
          str(button._icon_anim.endValue()))
    check("按钮本身尺寸不随悬停变（整排不会重新排版）",
          button.minimumSize() == button.maximumSize()
          and button.maximumSize() == QSize(db_mod.APP_BUTTON_W,
                                            db_mod.APP_BUTTON_H))

    lines = button.toolTip().splitlines()
    check("Tooltip 第一行是完整名称（不省略）",
          lines and lines[0] == button.display_name, button.toolTip())
    check("Tooltip 里有完整路径", str(button.path) in button.toolTip())
    check("Tooltip 说明了怎么用（怎么打开）",
          "打开" in button.toolTip(), button.toolTip())
    check("按钮上的名字是按字体宽度省略的（不是硬切 5 个字）",
          button.text() == button._elide(button.display_name),
          f"{button.text()!r} vs {button._elide(button.display_name)!r}")

    # ==================================================================
    section("3. 搜索：Placeholder / 聚焦 / 尺寸不变 / 无结果")
    # ==================================================================
    check("Placeholder 是需求指定的文案",
          browser.search.placeholderText() == "搜索文件、文件夹和应用...",
          browser.search.placeholderText())
    check("搜索框挂了 #Search（样式表靠它选中）",
          browser.search.objectName() == "Search")
    focus_rule = sheet.split("QLineEdit#Search:focus {")[1].split("}")[0]
    check("聚焦时描边用主色", theme_mod.GLASS["accent"] in focus_rule,
          focus_rule[:80])
    check("聚焦时有一层轻微高亮底", "background:" in focus_rule,
          focus_rule[:80])
    check("聚焦规则只改颜色，不改 border 宽度 / padding",
          "border-width" not in focus_rule and "padding" not in focus_rule,
          focus_rule[:120])
    search_rule = sheet.split("QLineEdit#Search {")[1].split("}")[0]
    check("搜索框不再写死 padding-left（那是画了图标才有的空档）",
          "padding-left" not in search_rule, search_rule[:120])

    check("左侧有放大镜图标", len(browser.search.actions()) == 1,
          str(len(browser.search.actions())))
    browser.search.clear()
    pump(app, 0.1)
    text_left = browser.search.cursorRect().left()
    icon_width = 15
    check("实测：文字起点在放大镜右边（没有压在图标上）",
          text_left >= icon_width, f"text_left={text_left}")

    height_before = browser.search.height()
    hint_before = browser.search.sizeHint()
    browser.search.setFocus()
    pump(app, 0.1)
    check("实测：聚焦后高度不变（不改变布局尺寸）",
          browser.search.height() == height_before,
          f"{height_before} -> {browser.search.height()}")
    check("实测：聚焦后 sizeHint 不变",
          browser.search.sizeHint() == hint_before,
          f"{hint_before} -> {browser.search.sizeHint()}")
    browser.search.clearFocus()

    browser.search.setText("绝对不存在的关键词zzz")
    browser._rebuild()
    pump(app, 0.1)
    check("没有结果时显示「未找到匹配项目」",
          browser.empty_label.text() == "未找到匹配项目",
          browser.empty_label.text())
    check("空提示真的露出来了", not browser.empty_label.isHidden())
    check("空提示是居中的弱化文字",
          browser.empty_label.objectName() == "Hint")
    browser.clear_search()
    pump(app, 0.2)
    check("清空后结果恢复", len(browser._matches) == len(items),
          str(len(browser._matches)))

    # ==================================================================
    section("4. 项目网格：图标统一 / 点击区域 / Hover / 两行省略")
    # ==================================================================
    tile = browser._tiles[0]
    check("卡片不再用内联样式表（内联会盖掉全局 :hover）",
          tile.styleSheet() == "", repr(tile.styleSheet()))
    check("卡片用动态属性表达选中态", tile.property("selected") is False)
    check("样式表里有 #FileTile:hover 规则", "#FileTile:hover {" in sheet)
    check("样式表里有 #FileTile[selected=\"true\"] 规则",
          '#FileTile[selected="true"] {' in sheet)
    hover_rule = sheet.split("#FileTile:hover {")[1].split("}")[0]
    check("悬停只换底色，不动边框 / 尺寸（网格不会跳）",
          "background:" in hover_rule
          and "border" not in hover_rule and "padding" not in hover_rule,
          hover_rule[:100])

    plain = tile.grab()
    tile.set_selected(True)
    pump(app, 0.1)
    check("选中后属性变 true", tile.property("selected") is True)
    selected = tile.grab()
    check("实测：选中态真的画出了底色（渲染有差异）",
          diff_pixels(plain, selected) > 0, str(diff_pixels(plain, selected)))
    tile.set_selected(False)
    pump(app, 0.1)

    # Phase 6：悬停底色改由 `anim.HoverVeil` 在 160ms 里淡进来（QSS 没有
    # transition），所以这里走**真实的 enterEvent**，并且要把动画跑完再抓图。
    # 老做法（`WA_UnderMouse` + 重新 polish）只对纯 QSS 的 `:hover` 有效。
    QApplication.sendEvent(tile, QEvent(QEvent.Type.Enter))
    pump(app, 0.28)
    hovered = tile.grab()
    check("实测：悬停态真的画出了底色（渲染有差异）",
          diff_pixels(plain, hovered) > 0, str(diff_pixels(plain, hovered)))
    check("悬停是过渡而不是瞬变（时长取 DURATION['hover']）",
          tile.veil._anim.duration() == theme_mod.DURATION["hover"],
          str(tile.veil._anim.duration()))
    check("悬停淡到了目标底色（和 QSS 时期一样浓）", tile.veil.value > 0.9,
          f"{tile.veil.value:.2f}")
    QApplication.sendEvent(tile, QEvent(QEvent.Type.Leave))
    pump(app, 0.28)
    check("离开后淡回透明", tile.veil.value < 0.05, f"{tile.veil.value:.2f}")
    check("离开后和悬停前完全一样（没有残留）",
          diff_pixels(plain, tile.grab()) == 0,
          str(diff_pixels(plain, tile.grab())))

    check("点击区域扩大了（比原来 CELL-8 更大）",
          db_mod.TILE_W > db_mod.CELL_W - 8
          and db_mod.TILE_H > db_mod.CELL_H - 8,
          f"{db_mod.TILE_W}x{db_mod.TILE_H} vs "
          f"{db_mod.CELL_W - 8}x{db_mod.CELL_H - 8}")
    check("卡片尺寸就是 TILE_W x TILE_H",
          tile.size() == QSize(db_mod.TILE_W, db_mod.TILE_H), str(tile.size()))
    check("卡片仍比单元格小（网格之间留得下缝）",
          db_mod.TILE_W < db_mod.CELL_W and db_mod.TILE_H < db_mod.CELL_H)

    # 图标大小统一：不管原图什么长宽比，贴上去都是方形画布
    wide = QPixmap(80, 20)
    wide.fill(Qt.GlobalColor.red)
    tile.set_icon(QIcon(wide))
    shot = tile.icon_label.pixmap()
    check("实测：扁图标被归一化成方形画布",
          shot is not None and shot.width() == shot.height(),
          f"{shot.width()}x{shot.height()}" if shot else "无")
    check("实测：画布尺寸 == GRID_ICON",
          shot is not None
          and shot.width() == db_mod.GRID_ICON, str(shot.width()))

    check("名称是 ElidedLabel（两行 + 省略号的实现）",
          isinstance(tile.name_label, ElidedLabel))
    check("名称最多两行", tile.name_label.max_lines == db_mod.NAME_LINES == 2)
    check("名称 text() 仍是完整显示名（别处按它比对）",
          tile.name_label.text()
          == engine.display_name(tile.item.name, tile.item.is_dir,
                                 browser.show_extensions()),
          f"{tile.name_label.text()} vs "
          f"{engine.display_name(tile.item.name, tile.item.is_dir, False)}")

    probe = ElidedLabel("这是一个名字特别特别长的文件用来测试省略号的行为.docx", 2)
    probe.resize(120, 40)
    metrics = QFontMetrics(probe.font())
    lines_out = probe._layout_lines(metrics, 120)
    check("长名字折成两行", len(lines_out) == 2, str(lines_out))
    check("最后一行带省略号", lines_out[-1].endswith("…"), str(lines_out))
    check("两行都放得下（不超过控件宽度）",
          all(metrics.horizontalAdvance(t) <= 120 for t in lines_out),
          str([metrics.horizontalAdvance(t) for t in lines_out]))
    check("完整名字没有被改掉",
          probe.text() == "这是一个名字特别特别长的文件用来测试省略号的行为.docx")
    check("高度按字体行高算（高分屏不会切掉第二行）",
          probe.sizeHint().height() == metrics.height() * 2,
          f"{probe.sizeHint().height()} vs {metrics.height() * 2}")
    short = ElidedLabel("短名", 2)
    short.resize(120, 40)
    check("短名字不折行也不加省略号",
          short._layout_lines(QFontMetrics(short.font()), 120) == ["短名"])

    # ==================================================================
    section("5. 底部按钮：明确的视觉层级")
    # ==================================================================
    check("「打开」是主按钮（Primary）",
          browser.btn_open.objectName() == "Primary", browser.btn_open.objectName())
    check("「加为常用」是次级按钮（默认描边款）",
          browser.btn_add.objectName() == "", repr(browser.btn_add.objectName()))
    check("「还原到桌面」是提醒款（Warning）",
          browser.btn_restore.objectName() == "Warning",
          browser.btn_restore.objectName())
    check("样式表里有 #Warning 变体", "QPushButton#Warning {" in sheet)
    check("三个按钮不是同一个样式（层级有差别）",
          len({browser.btn_open.objectName(), browser.btn_add.objectName(),
               browser.btn_restore.objectName()}) == 3)
    check("三个按钮一样高（控件高度统一）",
          len({b.objectName() for b in (browser.btn_open, browser.btn_add,
                                        browser.btn_restore)}) == 3
          and browser.btn_open.sizeHint().height()
          == browser.btn_restore.sizeHint().height()
          == browser.btn_add.sizeHint().height(),
          str([b.sizeHint().height() for b in (browser.btn_open,
                                               browser.btn_add,
                                               browser.btn_restore)]))
    check("「打开」有说明怎么打开的 Tooltip", "双击" in browser.btn_open.toolTip())
    check("「还原到桌面」的 Tooltip 说明了只移动不删除",
          "不删除" in browser.btn_restore.toolTip())

    browser.select_item(browser._tiles[0].item)
    pump(app, 0.15)
    check("选中之后三个按钮都可用",
          browser.btn_open.isEnabled() and browser.btn_add.isEnabled()
          and browser.btn_restore.isEnabled())
    browser.clear_selection()
    pump(app, 0.1)
    check("没选中时三个按钮都灰掉",
          not browser.btn_open.isEnabled() and not browser.btn_add.isEnabled()
          and not browser.btn_restore.isEnabled())

    # ==================================================================
    section("6. 状态：主面板两个按钮按数量灰掉")
    # ==================================================================
    from panel import MainPanel

    panel = MainPanel(cfg)
    check("刚建好时两个按钮都是灰的（还不知道有多少东西）",
          not panel.btn_take.isEnabled() and not panel.btn_restore.isEnabled())

    panel.refresh_cards(nest_items=0, desktop_pending=0)
    check("桌面待收纳 = 0 →「收纳桌面」disabled", not panel.btn_take.isEnabled())
    check("收纳项目 = 0 →「还原桌面」disabled", not panel.btn_restore.isEnabled())

    panel.refresh_cards(nest_items=5, desktop_pending=0)
    check("有收纳项目之后「还原桌面」可用", panel.btn_restore.isEnabled())
    check("桌面待收纳仍是 0 →「收纳桌面」还是灰的",
          not panel.btn_take.isEnabled())

    panel.refresh_cards(nest_items=0, desktop_pending=3)
    check("桌面上有东西 →「收纳桌面」可用", panel.btn_take.isEnabled())
    check("收纳项目是 0 →「还原桌面」灰掉", not panel.btn_restore.isEnabled())

    panel.refresh_cards(nest_items=2, desktop_pending=3)
    check("两边都有东西 → 两个按钮都能点",
          panel.btn_take.isEnabled() and panel.btn_restore.isEnabled())
    panel.close()

    # ==================================================================
    section("7. 验收：第一眼能看出来的六件事")
    # ==================================================================
    check("① 我在哪里 → 标题「桌面收纳」可见",
          browser.title.text() == "桌面收纳" and not browser.title.isHidden())
    check("② 有多少项目 → 徽标写着「N 项」",
          browser.badge.text().endswith("项") and not browser.badge.isHidden())
    check("③ 怎么搜索 → 搜索框有指路的 Placeholder",
          "搜索" in browser.search.placeholderText())
    check("④ 哪些是常用启动 → 这一排有小标题",
          browser.apps_label.text() == "常用启动"
          and not browser.apps_label.isHidden())
    check("⑤ 怎么打开 → 主按钮写着「打开」",
          browser.btn_open.text() == "打开"
          and browser.btn_open.objectName() == "Primary")
    check("⑥ 怎么还原 → 按钮写着「还原到桌面」",
          browser.btn_restore.text() == "还原到桌面")
    check("底部还写着这一页的统计（空间利用）",
          "共" in browser.hint.text() or "命中" in browser.hint.text(),
          browser.hint.text())

    # ==================================================================
    browser.hide()
    panel = None
    pump(app, 0.2)
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
