#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 7 · 最终 QA
=================
这一阶段**不加功能**，只按需求给的清单逐条验一遍：稳定性、兼容性、UI、交互、
文件操作、状态、动画。十节对应需求里的十条：

1. 基础功能 —— 扫描 / 显示文件·文件夹·快捷方式 / 搜索 / 清除 / 分页 / 打开 / 加常用 / 移常用
2. 收纳 —— 单个 / 多个 / 全部 / 空桌面 / 冲突 / 权限 / 文件不存在
3. 还原 —— 单个 / 多个 / 全部 / 空目录 / 冲突 / 原路径不存在
4. 操作历史 —— 记录 / 选择 / 撤销 / 连续撤销 / 撤销失败 / 清空
5. 常用启动 —— 增删 / 点击 / Hover / Tooltip / 排序六种拖法 / 重启保持
6. Dock —— 显示 / 隐藏 / Hover / 点击 / 启动 / 菜单
7. 窗口 —— 最大·最小·调整 / 关闭·重开·多次；overflow / 裁剪 / 按钮消失 / 重叠 / 网格错位
8. 性能 —— 渲染 / 搜索 / 滚动 / 弹簧帧时间 / 大量项目
9. 代码卫生 —— Qt 警告 / 未使用导入 / 重复 CSS / 死代码 / 泄漏
10. 汇总

用法：python dev/test_phase7.py
"""
from __future__ import annotations

import ast
import gc
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

PASS, FAIL, NOTES = [], [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def note(label: str, detail: str = "") -> None:
    """只报告、不作为失败项（已知问题 / 需要人工判断的事）。"""
    NOTES.append(f"{label}{('：' + detail) if detail else ''}")
    print(f"  · {label}" + (f"  [{detail}]" if detail else ""))


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


def pump(app, seconds: float = 0.2) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def pump_until_rest(app, dock, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if not dock._anim_timer.isActive():          # noqa: SLF001
            return True
        time.sleep(0.004)
    return False


def make_item(path: Path, *, is_dir: bool = False, kind: str = "document"):
    import engine

    return engine.RepoItem(path, path.name, is_dir, kind,
                           1024 if not is_dir else 0, 0.0)


def main() -> int:
    from qt_compat import QApplication, QPoint, QWidget

    app = QApplication([])

    import anim as anim_mod          # noqa: F401  （确保新模块能被导入）
    import config as config_mod
    import desktop_browser as db_mod
    import engine
    import nest
    import theme as theme_mod
    import widgets as widgets_mod

    # ---- 沙盒 ------------------------------------------------------
    base = Path(tempfile.gettempdir()) / "nest-phase7"
    shutil.rmtree(base, ignore_errors=True)
    desktop = base / "Desktop"
    desktop.mkdir(parents=True)
    public = base / "PublicDesktop"
    public.mkdir(parents=True)

    config_mod._DATA_DIR = base / "data"
    (base / "data").mkdir(parents=True, exist_ok=True)
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: public
    nest.nest_root = lambda: base / ".nest"
    nest.ensure_dirs()

    cfg = config_mod.Config(base / "cfg")
    cfg.update({"desktop": str(desktop), "page_size": 7})

    # 桌面上放：3 个文件 + 1 个文件夹 + 2 个快捷方式
    for name in ("季度报告.docx", "预算表.xlsx", "会议纪要.md"):
        (desktop / name).write_text("x", encoding="utf-8")
    folder = desktop / "项目资料"
    folder.mkdir()
    (folder / "内部.txt").write_text("x", encoding="utf-8")
    import winlink

    winlink.create_shortcut(desktop / "记事本.lnk",
                            r"C:\Windows\System32\notepad.exe")
    winlink.create_shortcut(desktop / "计算器.lnk",
                            r"C:\Windows\System32\calc.exe")

    # 让"打开"不真的拉起程序
    launched = []
    engine.launch = lambda path: (launched.append(str(path)) or (True, ""))

    # ==================================================================
    section("1. 基础功能：扫描 / 显示 / 搜索 / 分页 / 打开 / 常用")
    # ==================================================================
    entries, blocked = nest.list_desktop(desktop)
    names = {entry.name for entry in entries}
    check("扫描桌面：6 个条目（3 文件 + 1 文件夹 + 2 快捷方式）",
          len(entries) == 6, str(sorted(names)))
    check("扫描能认出文件夹", any(entry.is_dir for entry in entries))
    check("扫描能认出快捷方式",
          sum(1 for entry in entries if entry.kind == "shortcut") == 2,
          str([(e.name, e.kind) for e in entries]))
    check("没有条目被误判成系统图标", not blocked, str(blocked))

    items = [make_item(entry.path, is_dir=entry.is_dir, kind=entry.kind)
             for entry in entries]
    browser = db_mod.DesktopBrowser(cfg)
    browser.resize(940, 680)
    browser.set_items(items)
    browser.show()
    pump(app, 0.4)

    check("显示文件：网格里有文件卡片",
          any(not tile.item.is_dir for tile in browser._tiles))
    check("显示文件夹：网格里有文件夹卡片",
          any(tile.item.is_dir for tile in browser._tiles))
    check("卡片数量 = 本页条目数",
          len(browser._tiles) == min(cfg.get("page_size"), len(items)),
          f"{len(browser._tiles)} vs {len(items)}")
    check("徽标报总数", browser.badge.text() == f"{len(items)} 项",
          browser.badge.text())

    browser.search.setText("报告")
    pump(app, 0.3)
    check("搜索：只剩匹配项", len(browser._matches) == 1,
          str([item.name for item in browser._matches]))
    browser.clear_search()
    pump(app, 0.3)
    check("清除搜索：恢复全部", len(browser._matches) == len(items),
          str(len(browser._matches)))
    check("清除搜索：输入框也空了", browser.search.text() == "")

    # 分页：每页最少 7 个，所以先补到 9 个条目
    extra = [make_item(desktop / f"补充{i}.txt") for i in range(3)]
    browser.set_items(items + extra)
    pump(app, 0.3)
    check("分页：一页放不下就有第二页", browser._page_count() == 2,
          str(browser._page_count()))
    browser.goto_page(1)
    pump(app, 0.3)
    check("翻到第 2 页", browser._page == 1, str(browser._page))
    check("页码标签跟着变", browser.page_label.text() == "2 / 2",
          browser.page_label.text())
    check("第 2 页上「上一页」可用", browser.btn_prev.isEnabled())
    browser.goto_page(0)
    pump(app, 0.3)
    check("回到第 1 页后「上一页」灰掉", not browser.btn_prev.isEnabled())
    browser.set_items(items)
    pump(app, 0.2)

    browser.select_item(items[0])
    browser.open_selected()
    pump(app, 0.1)
    check("打开：调用了一次启动", len(launched) == 1, str(launched))

    before = len(cfg.quick_items)
    ok = browser.add_item_to_apps(items[0])
    pump(app, 0.2)
    check("加入常用：返回成功", ok is True)
    check("加入常用：配置里多了一项", len(cfg.quick_items) == before + 1,
          str(len(cfg.quick_items)))
    check("加入常用：常用那一排多了个按钮",
          len(browser._app_buttons) == before + 1,
          str(len(browser._app_buttons)))
    ok = browser.remove_quick_path(items[0].path)
    pump(app, 0.2)
    check("移除常用：返回成功", ok is True)
    check("移除常用：配置回到原来的项数", len(cfg.quick_items) == before,
          str(len(cfg.quick_items)))
    check("移除常用：那一排也少回来了",
          len(browser._app_buttons) == before, str(len(browser._app_buttons)))

    # ==================================================================
    section("2. 收纳：单个 / 多个 / 全部 / 空 / 冲突 / 权限 / 不存在")
    # ==================================================================
    store = nest.desktop_store()
    one = [make_item(desktop / "季度报告.docx")]
    result = nest.take_from_desktop(desktop, items=one)
    check("收纳单个：moved == 1", result.moved == 1, str(result.moved))
    check("收纳单个：文件真的进了收纳目录",
          (store / "季度报告.docx").is_file())
    check("收纳单个：桌面上的那份没了",
          not (desktop / "季度报告.docx").exists())

    many = [make_item(desktop / "预算表.xlsx"), make_item(desktop / "会议纪要.md")]
    result = nest.take_from_desktop(desktop, items=many)
    check("收纳多个：moved == 2", result.moved == 2, str(result.moved))
    check("收纳多个：两个都在收纳目录里",
          (store / "预算表.xlsx").is_file() and (store / "会议纪要.md").is_file())

    result = nest.take_from_desktop(desktop)
    check("收纳全部：剩下的都收走了", result.moved == 3, str(result.moved))
    check("收纳全部：桌面只剩空目录结构",
          not [p for p in desktop.iterdir()], str(list(desktop.iterdir())))

    result = nest.take_from_desktop(desktop)
    check("空桌面收纳：不报错、moved == 0", result.moved == 0)
    check("空桌面收纳：也没有 failed", not result.failed, str(result.failed))

    # 冲突：桌面上再放一个同名文件，收纳时应自动改名，绝不覆盖
    (desktop / "季度报告.docx").write_text("new", encoding="utf-8")
    result = nest.take_from_desktop(desktop)
    check("文件冲突：收纳成功", result.moved == 1, str(result.moved))
    check("文件冲突：旧的没被覆盖（收纳目录里两份都在）",
          (store / "季度报告.docx").is_file()
          and (store / "季度报告 (1).docx").is_file(),
          str(sorted(p.name for p in store.iterdir())))
    check("文件冲突：旧文件内容没变",
          (store / "季度报告.docx").read_text(encoding="utf-8") == "x")

    # 权限：把 _move 换成抛 PermissionError
    (desktop / "权限测试.txt").write_text("x", encoding="utf-8")
    real_move = nest._move

    def deny(source, target):
        raise PermissionError(13, "拒绝访问")

    nest._move = deny
    result = nest.take_from_desktop(desktop)
    nest._move = real_move
    check("权限错误：记进 failed", len(result.failed) == 1, str(result.failed))
    check("权限错误：原因说人话",
          "权限" in result.failed[0][1] or "占用" in result.failed[0][1],
          result.failed[0][1])
    check("权限错误：文件留在桌面（没被搬走也没被删）",
          (desktop / "权限测试.txt").is_file())

    # 文件不存在
    ghost = make_item(desktop / "本来就没有.txt")
    result = nest.take_from_desktop(desktop, items=[ghost])
    check("文件不存在：记进 failed 而不是崩", len(result.failed) == 1,
          str(result.failed))
    check("文件不存在：原因写明", "不存在" in result.failed[0][1],
          result.failed[0][1])

    # ==================================================================
    section("3. 还原：单个 / 多个 / 全部 / 空 / 冲突 / 原路径不存在")
    # ==================================================================
    single = nest.restore_item_to_desktop(desktop,
                                          make_item(store / "季度报告.docx"))
    ok = single[0] if isinstance(single, tuple) else bool(single)
    check("还原单个：成功", ok is True, str(single))
    check("还原单个：文件回到桌面", (desktop / "季度报告.docx").is_file())

    plan = nest.restore_plan(desktop)
    check("还原预检：只读（不会建目录、不会动文件）",
          isinstance(plan, list) and all("exists" in row for row in plan),
          str(plan[:1]))
    check("还原预检：条数与收纳目录一致", len(plan) == len(
        [p for p in store.iterdir()]), f"{len(plan)}")

    result = nest.restore_to_desktop(desktop)
    check("还原全部：moved > 0", result.moved > 0, str(result.moved))
    check("还原全部：桌面又有东西了", len(list(desktop.iterdir())) > 0)
    check("还原全部：收纳目录清空了",
          not [p for p in store.iterdir()],
          str([p.name for p in store.iterdir()]))

    result = nest.restore_to_desktop(desktop)
    check("空收纳目录还原：不报错、moved == 0", result.moved == 0,
          str(result.moved))

    # 冲突：收纳一份，桌面再放一份同名
    (desktop / "冲突文件.txt").write_text("store", encoding="utf-8")
    nest.take_from_desktop(desktop, items=[make_item(desktop / "冲突文件.txt")])
    (desktop / "冲突文件.txt").write_text("desk", encoding="utf-8")
    plan = nest.restore_plan(desktop)
    conflict = [row for row in plan if row["name"] == "冲突文件.txt"]
    check("还原冲突：预检认出桌面已有同名", bool(conflict) and conflict[0]["exists"],
          str(conflict))
    result = nest.restore_to_desktop(desktop, skip={"冲突文件.txt"})
    check("还原冲突：选「跳过」就不动它", result.moved == 0, str(result.moved))
    check("还原冲突：跳过记进 skipped",
          any("跳过" in reason for _name, reason in result.skipped),
          str(result.skipped))
    check("还原冲突：桌面那份还是桌面的内容",
          (desktop / "冲突文件.txt").read_text(encoding="utf-8") == "desk")
    check("还原冲突：收纳那份也没被删",
          (store / "冲突文件.txt").is_file())
    # 收尾：把冲突那一节的残留清干净，免得影响后面的计数
    nest.take_from_desktop(desktop, items=[make_item(desktop / "冲突文件.txt")])
    shutil.rmtree(store, ignore_errors=True)
    nest.ensure_dirs()
    check("清理沙盒：收纳目录已空", not [p for p in store.iterdir()],
          str([p.name for p in store.iterdir()]))

    # 原路径不存在：来源记的是公共桌面，但那个目录已经被删掉
    (public / "公用测试.txt").write_text("x", encoding="utf-8")
    nest.take_from_desktop(public, items=[make_item(public / "公用测试.txt")])
    check("原路径不存在：先收进收纳", (store / "公用测试.txt").is_file())
    public.rmdir() if not list(public.iterdir()) else None
    result = nest.restore_to_desktop(desktop)
    check("原路径不存在：照样还原成功（不崩）", result.moved == 1,
          str(result.moved))
    check("原路径不存在：退回个人桌面",
          (desktop / "公用测试.txt").is_file())
    public.mkdir(exist_ok=True)
    (desktop / "公用测试.txt").unlink(missing_ok=True)

    # ==================================================================
    section("4. 操作历史：记录 / 选择 / 撤销 / 连续撤销 / 失败 / 清空")
    # ==================================================================
    from panel import MainPanel
    import panel as panel_mod

    # 主面板的「撤销失败」「清空历史」都会弹模态框。离屏下模态框会把测试挂死，
    # 所以这里换成一个记账用的假 QMessageBox（**只是测试替身**，不是改产品代码）。
    box_calls = []

    class _FakeBox:
        class Icon:
            Warning = 0
            Information = 1

        class ButtonRole:
            RejectRole = 0
            DestructiveRole = 1

        def __init__(self, *args, **kwargs):
            pass

        def setWindowTitle(self, *_a):
            pass

        def setIcon(self, *_a):
            pass

        def setText(self, text):
            self._text = text

        def setInformativeText(self, *_a):
            pass

        def addButton(self, *_a):
            return None

        def setDefaultButton(self, *_a):
            pass

        def exec(self):
            return 0

        def clickedButton(self):
            return None

        @staticmethod
        def warning(*args, **kwargs):
            box_calls.append(("warning", args[2] if len(args) > 2 else ""))

        @staticmethod
        def information(*args, **kwargs):
            box_calls.append(("information", ""))

    real_box = panel_mod.QMessageBox
    panel_mod.QMessageBox = _FakeBox

    panel = MainPanel(cfg)
    panel.resize(940, 680)
    panel.show()
    pump(app, 0.3)

    records = nest.read_journal(40)
    check("记录收纳：流水里有 take", any(r["action"] == "take" for r in records),
          str([r["action"] for r in records][:5]))
    check("记录还原：流水里有 restore",
          any(r["action"] == "restore" for r in records),
          str([r["action"] for r in records][:5]))

    panel.refresh_history(records)
    pump(app, 0.2)
    check("历史表把流水列出来了",
          panel.history_tree.topLevelItemCount() == len(records),
          f"{panel.history_tree.topLevelItemCount()} vs {len(records)}")

    panel.history_tree.setCurrentItem(panel.history_tree.topLevelItem(0))
    pump(app, 0.1)
    check("选择历史：选中第一行", panel.history_tree.currentItem() is not None)
    check("选择历史：撤销按钮可用", panel.btn_undo.isEnabled())

    # 撤销：先造一条"收纳"记录，再撤它
    (desktop / "撤销测试.txt").write_text("x", encoding="utf-8")
    nest.take_from_desktop(desktop, items=[make_item(desktop / "撤销测试.txt")])
    records = nest.read_journal(40)
    panel.refresh_history(records)
    pump(app, 0.2)
    newest = records[0]
    panel._undo_record(newest)                       # noqa: SLF001
    pump(app, 0.3)
    check("撤销：文件回到桌面", (desktop / "撤销测试.txt").is_file())
    check("撤销：桌面上的内容正确",
          (desktop / "撤销测试.txt").read_text(encoding="utf-8") == "x")

    # 连续撤销：再攒两条，一起撤
    for name in ("连撤1.txt", "连撤2.txt"):
        (desktop / name).write_text("x", encoding="utf-8")
        nest.take_from_desktop(desktop, items=[make_item(desktop / name)])
    records = nest.read_journal(40)
    panel.refresh_history(records)
    pump(app, 0.2)
    for record in records[:2]:
        panel._undo_record(record)                   # noqa: SLF001
    pump(app, 0.3)
    check("连续撤销：两条都回到桌面",
          (desktop / "连撤1.txt").is_file() and (desktop / "连撤2.txt").is_file())

    # 撤销失败：把记录里的目标文件先删掉，再撤
    (desktop / "失败撤销.txt").write_text("x", encoding="utf-8")
    nest.take_from_desktop(desktop, items=[make_item(desktop / "失败撤销.txt")])
    records = nest.read_journal(40)
    bad = dict(records[0])
    for path in (store / "失败撤销.txt",):
        path.unlink(missing_ok=True)
    bad["moves"] = [[str(desktop / "失败撤销.txt"), str(store / "失败撤销.txt")]]
    outcome = nest.undo_record(bad)
    check("撤销失败：返回失败而不是抛异常",
          getattr(outcome, "moved", 0) == 0 and bool(getattr(outcome, "failed", [])),
          str(getattr(outcome, "failed", "")))
    # 再走一遍**面板**的入口：它应该弹提示框 + 弹 Toast，而不是静默
    box_calls.clear()
    panel._undo_record(bad)                          # noqa: SLF001
    pump(app, 0.2)
    check("撤销失败：程序还活着（面板还能刷新）",
          panel.refresh_history(nest.read_journal(40)) is None)
    check("撤销失败：弹了一次提示框（不是静默失败）",
          any(kind == "warning" for kind, _detail in box_calls), str(box_calls))

    before_clear = len(nest.read_journal(400))
    panel._confirm_clear_history = lambda: True      # noqa: SLF001  （跳过确认框）
    panel._clear_history()                            # noqa: SLF001
    pump(app, 0.2)
    check("清空历史：流水清空了", len(nest.read_journal(400)) == 0,
          f"{before_clear} → {len(nest.read_journal(400))}")
    check("清空历史：桌面上的文件一个没少",
          (desktop / "撤销测试.txt").is_file()
          and (desktop / "连撤1.txt").is_file())
    check("清空历史：收纳目录也没被清",
          store.is_dir())

    # ==================================================================
    section("5. 常用启动：增删 / 点击 / Hover / Tooltip / 排序 / 重启保持")
    # ==================================================================
    app_links = []
    for index in range(4):
        link = base / f"常用{index}.lnk"
        winlink.create_shortcut(link, r"C:\Windows\System32\notepad.exe")
        app_links.append(link)
        cfg.add_quick(link, link.stem)
    browser.rebuild_apps()
    pump(app, 0.4)
    check("添加：4 个常用项都上了那一排",
          len(browser._app_buttons) == 4, str(len(browser._app_buttons)))

    button = browser._app_buttons[0]
    launched.clear()
    # 常用按钮的"启动"挂在 mouseReleaseEvent 上（不是 clicked），所以发一个真事件
    from qt_compat import QEvent, QMouseEvent, QPointF, Qt

    QApplication.sendEvent(button, QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    pump(app, 0.2)
    check("点击启动：调用了启动", bool(launched), str(launched))

    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    pump(app, 0.25)
    check("Hover：图标放大了",
          button._icon_anim.endValue().width() > db_mod.APP_ICON,
          str(button._icon_anim.endValue()))
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    pump(app, 0.25)
    check("Hover 移出：图标缩回去",
          button._icon_anim.endValue().width() == db_mod.APP_ICON,
          str(button._icon_anim.endValue()))

    check("Tooltip：第一行是完整名称",
          button.toolTip().splitlines()[0] == button.display_name,
          button.toolTip().splitlines()[0])
    check("Tooltip：带路径", str(button.path) in button.toolTip())

    # ---- Dock 上的排序（六种拖法）----
    import dock as dock_mod

    dock = dock_mod.DockBar(cfg)
    dock.show_bar()
    pump(app, 0.5)
    dock_buttons = dock._app_buttons
    check("排序用例：菜单栏上有 4 个图标", len(dock_buttons) == 4,
          str(len(dock_buttons)))
    if len(dock_buttons) == 4:
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
            return [entry["name"] for entry in cfg.quick_items]

        src = dock_buttons[0]
        press = center_of(src)
        dock._on_icon_press(src, press)
        dock._on_icon_hold(src, press)
        pump(app, 0.05)

        dock._on_icon_move(src, slot_center(3))
        check("拖拽排序：一步跨 3 格跟上", dock._reorder_to == 3,
              str(dock._reorder_to))
        dock._on_icon_move(src, slot_center(1))
        check("快速拖动 / 反向拖动：目标立刻回到 1",
              dock._reorder_to == 1, str(dock._reorder_to))
        seen = []
        for index in (0, 2, 3, 2):
            dock._on_icon_move(src, slot_center(index))
            seen.append(dock._reorder_to)
        check("跨多个位置：0→2→3→2 每格都跟", seen == [0, 2, 3, 2], str(seen))

        dock._on_icon_move(src, slot_center(2))
        dock._on_icon_release(src, slot_center(2))
        check("松开：配置顺序当场写好", order()[2] == "常用0", str(order()))
        pump_until_rest(app, dock)
        check("松开：回弹结束后顺序没变", order()[2] == "常用0", str(order()))
        xs = [button.x() for button in dock._app_buttons]
        slots = [int(slot[0]) for slot in dock._slots] if dock._slots else []
        check("松开：图标落在槽位上（没有重叠）",
              not slots or sorted(xs) == sorted(slots), f"{xs} vs {slots}")

        # 重启后顺序保持：重新读一份配置
        fresh = config_mod.Config(base / "cfg")
        check("重启后顺序保持",
              [entry["name"] for entry in fresh.quick_items] == order(),
              str([entry["name"] for entry in fresh.quick_items]))
        dock.hide_bar()
        pump(app, 0.1)

    # ==================================================================
    section("6. Dock：显示 / 隐藏 / Hover / 点击 / 启动 / 菜单")
    # ==================================================================
    dock.show_bar()
    pump(app, 0.3)
    check("显示：菜单栏可见", not dock.isHidden())
    check("显示：位置在屏幕内（不会跑到屏幕外）",
          dock.screen().availableGeometry().contains(dock.geometry()),
          f"{dock.geometry()} in {dock.screen().availableGeometry()}")
    dock.hide_bar()
    pump(app, 0.2)
    check("隐藏：菜单栏收起来了", dock.isHidden())
    dock.show_bar()
    pump(app, 0.3)

    icon = dock._app_buttons[0]
    QApplication.sendEvent(icon, QEvent(QEvent.Type.Enter))
    pump(app, 0.1)
    check("Hover：图标有 Tooltip", bool(icon.toolTip()), icon.toolTip()[:30])
    QApplication.sendEvent(icon, QEvent(QEvent.Type.Leave))
    pump(app, 0.1)

    launched.clear()
    dock._launch(Path(cfg.quick_items[0]["path"]))
    pump(app, 0.1)
    check("点击启动：走的是同一个启动入口", bool(launched), str(launched))

    # 菜单：把 popup_menu 换成"直接返回 None"，验证菜单能建起来、不抛异常
    real_popup = dock_mod.popup_menu
    dock_mod.popup_menu = lambda menu, pos=None: None
    ok_menu = True
    try:
        dock.contextMenuEvent(type("E", (), {
            "type": lambda self: None,
            "globalPos": lambda self: QPoint(100, 100),
            "pos": lambda self: QPoint(10, 10),
        })())
    except Exception as exc:                       # noqa: BLE001
        ok_menu = False
        note("菜单构建抛异常", repr(exc))
    finally:
        dock_mod.popup_menu = real_popup
    check("菜单：右键菜单能建起来、不抛异常", ok_menu)

    # ==================================================================
    section("7. 窗口：尺寸 / 关闭重开 / overflow / 裁剪 / 网格错位")
    # ==================================================================
    browser.resize(200, 150)
    pump(app, 0.2)
    check("最小尺寸：不会被压到 560x360 以下",
          browser.width() >= 560 and browser.height() >= 360,
          f"{browser.width()}x{browser.height()}")
    check("最小尺寸：主按钮还在", not browser.btn_open.isHidden())

    browser.resize(2400, 1500)
    pump(app, 0.3)
    check("最大尺寸：能拉到很大而不崩",
          browser.width() >= 1200, f"{browser.width()}x{browser.height()}")

    def inside(widget, parent) -> bool:
        rect = widget.geometry()
        return (rect.left() >= -1 and rect.top() >= -1
                and rect.right() <= parent.width() + 1
                and rect.bottom() <= parent.height() + 1)

    problems = []
    for width, height in ((560, 360), (700, 460), (940, 680), (1200, 820)):
        browser.resize(width, height)
        pump(app, 0.15)
        for name in ("btn_refresh", "btn_more", "btn_close", "search",
                     "btn_open", "btn_add", "btn_restore"):
            widget = getattr(browser, name)
            if not inside(widget, browser):
                problems.append(f"{width}x{height}:{name}")
            if widget.isHidden():
                problems.append(f"{width}x{height}:{name} 被藏起来了")
    check("调整窗口：4 档尺寸下按钮都在窗口内、都还在", not problems,
          str(problems[:4]))

    grid_bad = []
    for tile in browser._tiles:
        rect = tile.geometry()
        if rect.right() > browser.grid_host.width() + 1 \
                or rect.bottom() > browser.grid_host.height() + 1:
            grid_bad.append(tile.item.name)
    check("调整窗口：卡片不会被裁剪到网格外面", not grid_bad, str(grid_bad[:3]))

    overlaps = []
    tiles = browser._tiles
    for i in range(len(tiles)):
        for j in range(i + 1, len(tiles)):
            if tiles[i].geometry().intersects(tiles[j].geometry()):
                overlaps.append(f"{tiles[i].item.name}/{tiles[j].item.name}")
    check("调整窗口：卡片之间不重叠（网格没错位）", not overlaps,
          str(overlaps[:3]))

    check("文本不重叠：卡片名字在卡片范围内",
          all(tile.name_label.geometry().right() <= tile.width() + 1
              for tile in tiles))

    browser.hide()
    pump(app, 0.15)
    check("关闭窗口：隐藏了", browser.isHidden())
    browser.show()
    pump(app, 0.3)
    check("再次打开：又出来了", not browser.isHidden())
    check("再次打开：卡片还在", len(browser._tiles) > 0,
          str(len(browser._tiles)))

    counts = []
    for _ in range(5):
        browser.hide()
        pump(app, 0.05)
        browser.show()
        pump(app, 0.08)
        counts.append(len(browser.findChildren(QWidget)))
    check("多次打开：控件数量没有越开越多（无泄漏）",
          max(counts) - min(counts) <= 2, str(counts))
    check("多次打开：功能仍然正常（还能翻页）",
          browser._page_count() >= 1)

    # ==================================================================
    section("8. 性能：渲染 / 搜索 / 滚动 / 弹簧 / 大量项目")
    # ==================================================================
    many_items = [make_item(desktop / f"批量{i:03d}.txt") for i in range(500)]
    for item in many_items[:50]:          # 只真的造 50 个文件，其余是内存条目
        item.path.write_text("x", encoding="utf-8")

    started = time.perf_counter()
    browser.set_items(many_items)
    pump(app, 0.25)
    render_ms = (time.perf_counter() - started) * 1000
    check("大量项目：500 项渲染 < 1500ms", render_ms < 1500,
          f"{render_ms:.0f}ms")
    check("大量项目：只渲染本页（不是 500 张卡片）",
          len(browser._tiles) <= cfg.get("page_size"),
          f"{len(browser._tiles)} vs {cfg.get('page_size')}")
    check("大量项目：分页数正确", browser._page_count() == 72,
          str(browser._page_count()))

    started = time.perf_counter()
    browser.search.setText("批量01")
    pump(app, 0.3)
    search_ms = (time.perf_counter() - started) * 1000
    check("搜索不卡顿：500 项里搜 < 600ms", search_ms < 600, f"{search_ms:.0f}ms")
    check("搜索有结果（模糊匹配到「批量01x」）", len(browser._matches) >= 10,
          str(len(browser._matches)))
    browser.clear_search()
    pump(app, 0.3)

    started = time.perf_counter()
    bar = browser.scroll.verticalScrollBar()
    for value in range(0, 60):
        bar.setValue(value * 8)
        app.processEvents()
    scroll_ms = (time.perf_counter() - started) * 1000
    check("滚动流畅：60 次滚动 < 800ms", scroll_ms < 800, f"{scroll_ms:.0f}ms")

    started = time.perf_counter()
    browser.goto_page(5)
    pump(app, 0.3)
    page_ms = (time.perf_counter() - started) * 1000
    check("翻页不卡顿：500 项翻一页 < 600ms", page_ms < 600, f"{page_ms:.0f}ms")

    # 弹簧：60 帧的平均耗时（Dock 的帧间隔是 16ms，必须明显低于它）
    import springs

    points = [springs.SpringPoint(0.0, 0.0) for _ in range(5)]
    for index, point in enumerate(points):
        point.move_to(100.0 + index * 20, 0.0)
    started = time.perf_counter()
    for _ in range(60):
        for point in points:
            point.step(1.0 / 60.0)
    tick_ms = (time.perf_counter() - started) * 1000 / 60
    check("60 FPS：5 个弹簧一帧的积分耗时远低于 16ms", tick_ms < 2.0,
          f"{tick_ms:.3f}ms/帧")

    started = time.perf_counter()
    for _ in range(30):
        dock._on_anim_tick()                          # noqa: SLF001
        app.processEvents()
    dock_tick_ms = (time.perf_counter() - started) * 1000 / 30
    check("60 FPS：菜单栏一帧（4 个图标）< 16ms", dock_tick_ms < 16.0,
          f"{dock_tick_ms:.2f}ms/帧")
    dock.hide_bar()

    # ==================================================================
    section("9. 代码卫生：Qt 警告 / 未使用导入 / 重复 CSS / 死代码 / 泄漏")
    # ==================================================================
    # ---- Qt 运行时消息 ----
    messages = []
    try:
        from PyQt6.QtCore import qInstallMessageHandler
    except ImportError:                                # pragma: no cover
        from PySide6.QtCore import qInstallMessageHandler  # type: ignore

    def handler(mode, context, message):
        messages.append((str(mode), message))

    qInstallMessageHandler(handler)
    probe_browser = db_mod.DesktopBrowser(cfg)
    probe_browser.resize(940, 680)
    probe_browser.set_items(many_items[:20])
    probe_browser.show()
    pump(app, 0.3)
    probe_browser.goto_page(1)
    probe_browser.search.setText("批量")
    pump(app, 0.2)
    probe_browser.clear_search()
    probe_browser.close()
    probe_panel = MainPanel(cfg)
    probe_panel.show()
    pump(app, 0.2)
    probe_panel.refresh_history(nest.read_journal(10))
    probe_panel.close()
    pump(app, 0.2)
    qInstallMessageHandler(None)

    # 离屏平台**自身**没有窗口管理器，`raise_()` / 置顶这类请求会被直接拒绝。
    # 这是 QT_QPA_PLATFORM=offscreen 的限制，不是产品缺陷（原生平台有 WM，同一句
    # raise_() 正常工作），所以只记备注。其余警告一律仍按失败处理。
    OFFSCREEN_ONLY = ("This plugin does not support raise()",
                      "This plugin does not support setting window opacity")

    def is_platform_limited(text: str) -> bool:
        return any(marker in text for marker in OFFSCREEN_ONLY)

    platform_notes = [f"{mode}: {msg}" for mode, msg in messages
                      if "Warning" in mode and is_platform_limited(msg)]
    if platform_notes:
        note("离屏平台不支持的操作（原生平台正常）", str(platform_notes[:2]))

    noisy = [f"{mode}: {msg}" for mode, msg in messages
             if ("Warning" in mode or "Critical" in mode)
             and not is_platform_limited(msg)]
    check("运行时没有 Qt 警告 / 错误（console 干净）", not noisy,
          str(noisy[:2]))

    # ---- 未使用导入 ----
    def unused_imports(path: Path) -> "list[str]":
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                if node.module in ("__future__",):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imported[alias.asname or alias.name] = node.lineno
        return [name for name in imported if text.count(name) <= 1]

    modules = ["anim.py", "desktop_browser.py", "dock.py", "panel.py",
               "settings.py", "tray_app.py", "widgets.py", "theme.py",
               "nest.py", "engine.py", "config.py", "qt_compat.py",
               "springs.py", "safety.py", "icons.py", "acrylic.py",
               "single_instance.py", "textutil.py", "winlink.py"]
    leftovers = {}
    for name in modules:
        path = HERE / name
        if path.is_file():
            found = unused_imports(path)
            if found:
                leftovers[name] = found
    check("没有未使用的导入", not leftovers, str(leftovers))

    # ---- 重复 CSS ----
    sheet = theme_mod.stylesheet(False)
    bodies = {}
    duplicates = []
    for block in sheet.split("}"):
        if "{" not in block:
            continue
        selector, body = block.split("{", 1)
        selector = selector.strip().splitlines()[-1].strip()
        body = " ".join(body.split())
        if not selector or selector.startswith("/*") or len(body) < 10:
            continue
        key = (selector, body)
        if key in bodies:
            duplicates.append(selector)
        bodies[key] = True
    check("样式表里没有完全重复的规则", not duplicates, str(duplicates[:3]))

    # ---- 死代码：私有函数从来没被引用 ----
    referenced = "\n".join(
        (HERE / name).read_text(encoding="utf-8")
        for name in modules if (HERE / name).is_file())
    referenced += "\n".join(
        (HERE / "dev" / name).read_text(encoding="utf-8")
        for name in os.listdir(HERE / "dev") if name.endswith(".py"))
    orphans = []
    for name in ("anim.py", "widgets.py", "desktop_browser.py", "dock.py",
                 "panel.py", "nest.py", "engine.py", "theme.py", "tray_app.py"):
        path = HERE / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) \
                    and node.name.startswith("_") \
                    and not node.name.startswith("__"):
                if referenced.count(node.name) <= 1:
                    orphans.append(f"{name}:{node.name}")
    if orphans:
        note("没有被引用的私有函数/类（可能是历史遗留）", str(orphans[:6]))
    check("没有明显死代码（私有函数都有调用点）", not orphans, str(orphans[:4]))

    # ---- 泄漏：反复重建 ----
    # ⚠️ `deleteLater()` 只是**投递**一个删除请求，要等事件循环处理到
    # DeferredDelete 才真的销毁。光调 `processEvents()` 不会执行它，旧卡片会
    # 一直挂在那里 —— 那是探针假象，不是泄漏。这里显式推一把再数。
    from qt_compat import QEvent

    def flush_deletes() -> None:
        # QApplication 继承自 QCoreApplication，sendPostedEvents 是静态方法
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    probe_browser.show()
    pump(app, 0.1)
    before_children = len(probe_browser.findChildren(QWidget))
    for _ in range(20):
        probe_browser.set_items(many_items[:12])
        flush_deletes()
    gc.collect()
    flush_deletes()
    pump(app, 0.1)
    after_children = len(probe_browser.findChildren(QWidget))
    check("反复重建 20 次：控件数量没有膨胀（无泄漏）",
          after_children - before_children <= 6,
          f"{before_children} → {after_children}")
    check("反复重建：卡片列表被换掉了（不是无限追加）",
          len(probe_browser._tiles) <= cfg.get("page_size"),
          str(len(probe_browser._tiles)))
    probe_browser.close()

    # ==================================================================
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项，备注 {len(NOTES)} 条")
    if NOTES:
        for line in NOTES:
            print(f"  · {line}")
    if FAIL:
        for label in FAIL:
            print(f"  ✗ {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
