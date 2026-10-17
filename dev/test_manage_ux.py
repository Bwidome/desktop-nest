#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主面板 · 管理页面与操作历史 自检（Phase 3）
==========================================
对应需求七节 + 验收：

一、顶部统计卡片：0 项 =「✓ 桌面已整理」，> 0 =「⚠ 还有 N 项未整理」，
    状态色只染文字（不铺底色，不大面积用绿/红）。
二、收纳位置：路径降权（小一号、淡一档、长了中间省略），按钮叫「在文件夹中打开」。
三、面板内容 / 操作历史两个 Tab；历史表五列（时间 / 动作 / 条目数 / 说明 / 操作），
    行距、表头、悬停、选中、滚动条、表格撑满中间空间。
四、撤销：没选中 disabled，选中 enabled，撤销成功弹 Toast。
五、清空历史：危险操作，要确认，且不动任何文件。
六、底部四个按钮，按状态 disabled。

以及验收要求重点测的：收纳 / 还原 / 撤销 / 连续撤销 / 历史选中 / 历史清空。
**所有文件操作都在临时沙盒里做，不会碰真实桌面。**

用法：python dev/test_manage_ux.py
"""
from __future__ import annotations

import os
import re
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
    suffix = f"  [{detail}]" if detail and not condition else ""
    print(f"  {'✓' if condition else '✗'} {label}{suffix}")


def section(title: str) -> None:
    print()
    print(title)


def build_sandbox():
    """临时沙盒：桌面 + 配置目录 + 数据目录（流水写在这里）。"""
    base = Path(tempfile.gettempdir()) / "nest-phase3-test"
    shutil.rmtree(base, ignore_errors=True)
    desktop, cfg_dir, data = base / "Desktop", base / "cfg", base / "data"
    for folder in (desktop, cfg_dir, data):
        folder.mkdir(parents=True)
    for name in ("文件A.txt", "文件B.txt", "文件C.txt"):
        (desktop / name).write_text(f"内容-{name}", encoding="utf-8")
    return base, desktop, cfg_dir, data


def main() -> int:
    base, desktop, cfg_dir, data = build_sandbox()

    import config as config_mod

    # 数据目录 / 桌面目录都指到沙盒——流水绝不能写进真实用户目录，
    # 还原时更不能把文件搬到真实桌面去
    config_mod._DATA_DIR = data
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: base / "PublicDesktop"
    (base / "PublicDesktop").mkdir(parents=True, exist_ok=True)

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop)})

    import engine
    import nest
    import theme as theme_mod
    from qt_compat import (
        QAbstractItemView, QApplication, QSizePolicy,
    )

    nest.nest_root = lambda: base / ".nest"
    nest.ensure_dirs()
    store = nest.desktop_store()

    app = QApplication.instance() or QApplication([])

    from panel import MainPanel

    panel = MainPanel(cfg)
    panel.resize(940, 680)

    def pump() -> None:
        app.processEvents()

    def refresh_panel() -> None:
        panel.refresh_history(nest.read_journal(40))

    # ==================================================================
    section("1. 顶部统计卡片：把「状态」说清楚")
    # ==================================================================
    check("三张卡片的标题保持原样",
          [panel.card_nest.title.text(), panel.card_desktop.title.text(),
           panel.card_quick.title.text()]
          == ["收纳面板里", "桌面待收纳", "常用启动"])

    panel.refresh_cards(nest_items=5, desktop_pending=0,
                        folders=1, shortcuts=1)
    check("待收纳 = 0：状态行是「✓ 桌面已整理」",
          panel.card_desktop.hint.text() == "✓ 桌面已整理",
          panel.card_desktop.hint.text())
    check("待收纳 = 0：状态属性是 ok",
          panel.card_desktop.hint.property("state") == "ok",
          str(panel.card_desktop.hint.property("state")))

    panel.refresh_cards(nest_items=5, desktop_pending=3,
                        folders=1, shortcuts=1)
    check("待收纳 > 0：状态行是「⚠ 还有 3 项未整理」",
          panel.card_desktop.hint.text() == "⚠ 还有 3 项未整理",
          panel.card_desktop.hint.text())
    check("待收纳 > 0：状态属性是 warn",
          panel.card_desktop.hint.property("state") == "warn",
          str(panel.card_desktop.hint.property("state")))
    check("收纳面板里那张卡片同时给出构成（快捷方式/文件夹/文件）",
          "快捷方式 1" in panel.card_nest.hint.text()
          and "文件夹 1" in panel.card_nest.hint.text(),
          panel.card_nest.hint.text())

    # 右上角徽标只报数字，不复读状态（状态已经由卡片说过了）
    panel.refresh_cards(nest_items=5, desktop_pending=0,
                        folders=1, shortcuts=1)
    check("待收纳 = 0 时徽标显示「N 项已收纳」",
          panel.badge_state.text() == "5 项已收纳", panel.badge_state.text())
    panel.refresh_cards(nest_items=5, desktop_pending=3,
                        folders=1, shortcuts=1)
    check("有待收纳时徽标显示「N 项待收纳」",
          panel.badge_state.text() == "3 项待收纳", panel.badge_state.text())
    check("徽标和卡片状态不重复（一个说数、一个说状态）",
          panel.badge_state.text() != panel.card_desktop.hint.text())

    # 状态色来自 Design Token，而且只染文字
    qss = theme_mod.stylesheet(glass=True)
    bodies = re.findall(r"#StatState[^{]*\{([^}]*)\}", qss)
    check("三档状态色齐备（ok / warn / idle）", len(bodies) >= 3, str(len(bodies)))
    check("状态色只染文字，不铺底色（避免大面积绿/红）",
          all("background" not in body for body in bodies),
          str([b.strip() for b in bodies]))
    success = theme_mod.glass_palette()["success"].lower()
    warn = theme_mod.glass_palette()["warn"].lower()
    check("ok 档用的是 success 色",
          any(success in body.lower() for body in bodies))
    check("warn 档用的是 warning 色",
          any(warn in body.lower() for body in bodies))

    # ==================================================================
    section("2. 收纳位置：路径降权")
    # ==================================================================
    check("路径标签的 objectName 是 PathText（样式靠它选中）",
          panel.path_label.objectName() == "PathText")
    check("路径字号不大于正文（降权）",
          panel.path_label.font().pointSizeF() < theme_mod.FONT_SIZE["base"],
          str(panel.path_label.font().pointSizeF()))
    # ⚠️ 不去比对"实测 pt 值"：Qt 会把 pt 折算成整数像素再折回来，
    #    8.25pt 在 96dpi 下实测是 9.0pt。要钉的是"样式表里用的是尺子上的 xs"。
    path_rule = re.search(r"#PathText \{[^}]*\}", qss)
    check("路径字号在样式表里取自 FONT_SIZE['xs']",
          path_rule is not None
          and f"font-size: {theme_mod.FONT_SIZE['xs']}pt" in path_rule.group(0),
          path_rule.group(0) if path_rule else "没有 #PathText 规则")
    check("路径文本本身仍是完整的（复制 / 悬停都能看到全路径）",
          panel.path_label.text() == str(nest.nest_root()),
          panel.path_label.text())
    check("长路径不会把窗口撑开（宽度交给布局，超出部分中间省略）",
          panel.path_label.sizePolicy().horizontalPolicy()
          == QSizePolicy.Policy.Ignored)
    check("按钮文案是「在文件夹中打开」",
          panel.btn_open_nest.text() == "在文件夹中打开",
          panel.btn_open_nest.text())
    check("按钮是低权重的 Ghost 款（不抢主按钮）",
          panel.btn_open_nest.objectName() == "Ghost")

    # ==================================================================
    section("3. 两个 Tab / 操作历史表")
    # ==================================================================
    check("仍然是两个 Tab", panel.tabs.count() == 2)
    check("Tab 标题是「面板内容 / 操作历史」",
          [panel.tabs.tabText(i) for i in range(2)] == ["面板内容", "操作历史"])

    tree = panel.history_tree
    check("历史表五列", tree.columnCount() == 5, str(tree.columnCount()))
    headers = [tree.headerItem().text(i) for i in range(tree.columnCount())]
    check("列名是 时间 / 动作 / 条目数 / 说明 / 操作",
          headers == ["时间", "动作", "条目数", "说明", "操作"], str(headers))
    check("「说明」列吃掉多余宽度（列表不会缩在左边留一大片空白）",
          tree.header().sectionResizeMode(3)
          == tree.header().ResizeMode.Stretch)
    check("「操作」列是固定窄列（位置稳定）",
          tree.header().sectionResizeMode(4)
          == tree.header().ResizeMode.Fixed)
    check("表格纵向撑满（中间空间全给数据）",
          tree.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding)
    check("滚动条按像素滚（40 行时不会一格跳三行）",
          tree.verticalScrollMode()
          == QAbstractItemView.ScrollMode.ScrollPerPixel)
    check("一次只选一行（撤销针对单条流水）",
          tree.selectionMode() == tree.SelectionMode.SingleSelection)
    check("点「操作」列接上了撤销", panel.history_tree.receivers(
        panel.history_tree.itemClicked) > 0)

    # 行距 / 表头层级来自 QSS
    check("行距由 #HistoryTree::item 的 padding 拉开",
          "#HistoryTree::item {" in qss
          and "padding: 8px 6px" in qss[qss.index("#HistoryTree::item {"):][:200])
    check("表头去掉实心底、压成一条分隔线（层级低于数据）",
          "#HistoryTree QHeaderView::section" in qss)
    check("悬停 / 选中都有淡底反馈",
          "#HistoryTree::item:hover" in qss
          and "#HistoryTree::item:selected" in qss)
    tray_src = (HERE / "tray_app.py").read_text(encoding="utf-8")
    check("只喂最近 40 条流水（需求：最近 40 次操作）",
          "read_journal(40)" in tray_src)

    # ==================================================================
    section("4. 验收：收纳 → 历史 → 撤销")
    # ==================================================================
    result = nest.take_from_desktop(desktop, include_public=False)
    check("收纳把桌面上 3 个文件搬进收纳目录", result.moved == 3, str(result.moved))
    check("桌面已空", not any(desktop.iterdir()),
          str([p.name for p in desktop.iterdir()]))
    check("收纳写了一条流水", len(nest.read_journal()) == 1)

    refresh_panel()
    check("历史表出现 1 行", tree.topLevelItemCount() == 1,
          str(tree.topLevelItemCount()))
    row = tree.topLevelItem(0)
    check("动作列写「收纳」", row.text(1) == "收纳", row.text(1))
    check("条目数列是 3", row.text(2) == "3", row.text(2))
    check("说明列讲清方向与涉及的文件",
          "桌面 → 收纳面板" in row.text(3) and "文件A.txt" in row.text(3),
          row.text(3))
    check("操作列写「撤销」", row.text(4) == "撤销", row.text(4))

    # 行高：padding 8px 上下 + 一行字 → 明显高于裸行
    tree.resize(700, 400)
    pump()
    row_height = tree.sizeHintForRow(0)
    check("行距拉开了（行高 > 24px）", row_height > 24, str(row_height))

    check("没选中任何记录时「撤销」按钮是 disabled",
          not panel.btn_undo.isEnabled())
    row.setSelected(True)
    pump()
    check("选中一条后「撤销」按钮变成 enabled", panel.btn_undo.isEnabled())
    check("选中状态真的生效了", len(tree.selectedItems()) == 1)

    panel.btn_undo.click()
    pump()
    check("撤销后 3 个文件都回到桌面",
          all((desktop / n).exists()
              for n in ("文件A.txt", "文件B.txt", "文件C.txt")))
    check("撤销后收纳目录空了", not any(store.iterdir()),
          str([p.name for p in store.iterdir()]))
    check("撤销成功后流水被删掉（不会重复撤销）", nest.read_journal() == [])

    toast = panel.toast
    check("撤销成功弹出 Toast", not toast.isHidden())
    check("Toast 首行是「✓ 已撤销」", toast.text().splitlines()[0] == "✓ 已撤销",
          toast.text())
    check("Toast 说清恢复了几个项目",
          "3 个项目已恢复到原来的位置" in toast.text(), toast.text())
    check("Toast 用成功款（绿底白字），不是中性灰",
          toast.objectName() == "ToastOk", toast.objectName())
    check("Toast 不抢鼠标（点得穿到下面的按钮）",
          toast.testAttribute(
              __import__("qt_compat").Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    check("Toast 会自己消失（已经挂上自动淡出的计时器）",
          toast._timer.isActive())

    # ==================================================================
    section("5. 验收：连续撤销")
    # ==================================================================
    for name in ("文件D.txt", "文件E.txt"):
        (desktop / name).write_text("内容", encoding="utf-8")
    nest.take_from_desktop(desktop, include_public=False)
    (desktop / "文件F.txt").write_text("内容", encoding="utf-8")
    nest.take_from_desktop(desktop, include_public=False)

    refresh_panel()
    check("两次收纳 → 两条流水", tree.topLevelItemCount() == 2,
          str(tree.topLevelItemCount()))
    check("新的那条排在最上面（时间倒序）",
          tree.topLevelItem(0).text(2) == "1",
          tree.topLevelItem(0).text(2))

    # 第一次撤销：最新那条（只有文件F）
    tree.topLevelItem(0).setSelected(True)
    pump()
    panel.btn_undo.click()
    pump()
    check("撤第一次：文件F 回到桌面", (desktop / "文件F.txt").exists())
    check("撤第一次：还剩一条流水", len(nest.read_journal()) == 1)
    check("撤第一次的 Toast 说的是 1 个项目",
          "1 个项目已恢复到原来的位置" in toast.text(), toast.text())

    refresh_panel()
    check("刷新后列表只剩一条", tree.topLevelItemCount() == 1)
    tree.topLevelItem(0).setSelected(True)
    pump()
    panel.btn_undo.click()
    pump()
    check("撤第二次：文件D / 文件E 也回到桌面",
          (desktop / "文件D.txt").exists() and (desktop / "文件E.txt").exists())
    check("撤第二次：流水清空", nest.read_journal() == [])
    # 第二次撤的是"把桌面上那 5 个一起收进来"的那条（A/B/C 上一节已经回到桌面了）
    check("连续撤销两次都弹了 Toast，且说的是 5 个项目",
          "5 个项目已恢复到原来的位置" in toast.text(), toast.text())

    # ==================================================================
    section("6. 验收：历史选中（刷新后不丢）")
    # ==================================================================
    nest.take_from_desktop(desktop, include_public=False)
    refresh_panel()
    check("又有一条流水", tree.topLevelItemCount() == 1)
    tree.topLevelItem(0).setSelected(True)
    pump()
    refresh_panel()
    check("重新读一遍流水后，原来选中的那条仍然是选中的",
          len(tree.selectedItems()) == 1)
    check("撤销按钮跟着保持 enabled", panel.btn_undo.isEnabled())

    # 「操作」列点一下也能撤销（不用先选再点按钮）
    tree.itemClicked.emit(tree.topLevelItem(0), 4)
    pump()
    check("点行尾「撤销」直接生效（文件回到桌面）",
          any(desktop.iterdir()))

    # ==================================================================
    section("7. 验收：清空历史（危险操作要确认）")
    # ==================================================================
    nest.take_from_desktop(desktop, include_public=False)
    refresh_panel()
    before = len(nest.read_journal())
    check("清空前有流水", before >= 1, str(before))
    stored = [p.name for p in store.iterdir()]
    check("清空前收纳目录里有文件", bool(stored), str(stored))

    # 取消：什么都不该变
    panel._confirm_clear_history = lambda: False
    panel._clear_history()
    pump()
    check("确认框里点「取消」→ 流水一条不少",
          len(nest.read_journal()) == before, str(len(nest.read_journal())))

    # 确认：只清记录，不动文件
    panel._confirm_clear_history = lambda: True
    panel._clear_history()
    pump()
    check("确认后流水清空", nest.read_journal() == [])
    check("清空历史不会动文件（收纳目录里还是那些东西）",
          [p.name for p in store.iterdir()] == stored,
          str([p.name for p in store.iterdir()]))

    # 确认框的按钮文案
    src = (HERE / "panel.py").read_text(encoding="utf-8")
    check("确认框标题是「清空操作历史」", '"清空操作历史"' in src)
    check("确认框正文说明「不会影响已经收纳的文件」",
          "此操作不会影响已经收纳的文件" in src)
    check("按钮写成「取消」/「清空」，不是「是/否」",
          'addButton("取消"' in src and 'addButton("清空"' in src)
    check("默认按钮是「取消」（回车不会误清空）",
          "setDefaultButton(cancel)" in src)

    # ==================================================================
    section("8. 底部四个按钮按状态 disabled")
    # ==================================================================
    check("底部按钮文案是 刷新 / 打开收纳面板 / 收纳桌面 / 还原桌面",
          [panel.btn_refresh.text(), panel.btn_browse.text(),
           panel.btn_take.text(), panel.btn_restore.text()]
          == ["刷新", "打开收纳面板", "收纳桌面", "还原桌面"],
          str([panel.btn_refresh.text(), panel.btn_browse.text(),
               panel.btn_take.text(), panel.btn_restore.text()]))

    panel.refresh_cards(nest_items=0, desktop_pending=0)
    check("待收纳 0 + 收纳 0：两个动作按钮都 disabled",
          not panel.btn_take.isEnabled() and not panel.btn_restore.isEnabled())
    check("刷新 / 打开收纳面板 始终可点",
          panel.btn_refresh.isEnabled() and panel.btn_browse.isEnabled())

    panel.refresh_cards(nest_items=4, desktop_pending=2)
    check("有待收纳：「收纳桌面」可点", panel.btn_take.isEnabled())
    check("有收纳项：「还原桌面」可点", panel.btn_restore.isEnabled())

    panel.refresh_cards(nest_items=4, desktop_pending=0)
    check("待收纳 0 时「收纳桌面」disabled（没什么可收的）",
          not panel.btn_take.isEnabled())
    check("收纳项 > 0 时「还原桌面」仍然可点", panel.btn_restore.isEnabled())

    # ==================================================================
    section("9. 验收：还原（文件实际移动逻辑没变）")
    # ==================================================================
    result = nest.restore_to_desktop(desktop)
    check("还原把收纳目录里的东西放回桌面", result.moved >= 1, str(result.moved))
    check("还原后桌面上的文件都在",
          all((desktop / name).exists() for name in stored), str(stored))
    check("还原也写了一条流水（可撤销）",
          len(nest.read_journal()) >= 1, str(len(nest.read_journal())))
    refresh_panel()
    check("还原的流水在表里显示动作「还原」",
          tree.topLevelItem(0).text(1) == "还原",
          tree.topLevelItem(0).text(1))
    check("还原的说明是「收纳面板 → 桌面」",
          "收纳面板 → 桌面" in tree.topLevelItem(0).text(3),
          tree.topLevelItem(0).text(3))

    # ==================================================================
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print(f"  · {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
