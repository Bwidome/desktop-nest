#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 5 验收：状态反馈与异常处理
================================
需求原文（`需求.txt` 第五阶段）：

  一、操作状态：收纳 / 还原过程中显示「正在收纳… X / 60」，完成显示
      「✓ 已收纳 / 60 个项目」。
  二、失败：不许无提示结束，要显示「部分项目处理失败 / 成功 58 / 失败 2 / [查看详情]」。
  三、文件冲突：目标已有同名文件时给出「文件已存在 / 替换 / 跳过 / 取消」，
      **优先复用现有冲突处理**（重名自动加 `(1)` 那条规则一行没改）。
  四、权限问题：「无法访问此项目 / 权限不足 / 文件正在使用」+ [重试] [跳过]。
  五、Toast 统一：成功 ✓ / 警告 ⚠ / 失败 ×，短、清楚、不阻塞。
  六、不要滥用 Dialog：只有危险操作 / 无法自动恢复的错误 / 重要冲突才弹窗。

所以这份自检的重点不是"界面长得对不对"，而是：

  * 该说话的时候**真的说了**（进度有回调、失败有明细、不是静默结束）；
  * 不该弹窗的时候**真的没弹**（把 QMessageBox 打桩计数）；
  * 搬运本身还是原来那套（`_unique` 的重名规则、`_move` 的原子性）。

用法：python dev/test_phase5.py
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


def pump_until(app, predicate, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def build_sandbox():
    base = Path(tempfile.gettempdir()) / "nest-phase5"
    shutil.rmtree(base, ignore_errors=True)
    desktop, cfg_dir, data = base / "Desktop", base / "cfg", base / "data"
    public = base / "PublicDesktop"
    for folder in (desktop, cfg_dir, data, public):
        folder.mkdir(parents=True)
    for index in range(6):
        (desktop / f"文件{index:02d}.txt").write_text(f"内容-{index}",
                                                      encoding="utf-8")
    return base, desktop, cfg_dir, data, public


def main() -> int:
    base, desktop, cfg_dir, data, public = build_sandbox()

    import config as config_mod

    config_mod._DATA_DIR = data
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: public

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False, "restore_on_exit": False,
                "dock_visible": False})

    import nest

    nest.nest_root = lambda: base / ".nest"
    nest.ensure_dirs()
    store = nest.desktop_store()

    from qt_compat import QApplication, QMessageBox, QPushButton

    app = QApplication.instance() or QApplication([])

    from widgets import OperationBanner, Toast

    # ==================================================================
    section("1. Toast 统一：✓ / ⚠ / × 由 Toast 自己补")
    # ==================================================================
    check("成功 → ✓", Toast.mark("已收纳 60 个项目", "ok") == "✓ 已收纳 60 个项目",
          Toast.mark("已收纳 60 个项目", "ok"))
    check("警告 → ⚠",
          Toast.mark("桌面上没有需要收纳的内容", "warn") == "⚠ 桌面上没有需要收纳的内容",
          Toast.mark("桌面上没有需要收纳的内容", "warn"))
    check("失败 → ×", Toast.mark("操作失败", "danger") == "× 操作失败",
          Toast.mark("操作失败", "danger"))
    check("已经带符号不会重复补",
          Toast.mark("✓ 已撤销", "ok") == "✓ 已撤销", Toast.mark("✓ 已撤销", "ok"))
    check("符号和 kind 打架时以 kind 为准（不会出现 ⚠ 已加入）",
          Toast.mark("× 已加入常用启动", "ok") == "✓ 已加入常用启动",
          Toast.mark("× 已加入常用启动", "ok"))
    check("多行正文保留换行",
          Toast.mark("已收纳\n60 个项目", "ok") == "✓ 已收纳\n60 个项目",
          repr(Toast.mark("已收纳\n60 个项目", "ok")))

    # ==================================================================
    section("2. 状态条：正在做 → 12 / 60 → 失败明细")
    # ==================================================================
    banner = OperationBanner()
    banner.begin("正在收纳…", 60)
    check("进度标题是「正在收纳…」", banner.title.text() == "正在收纳…",
          banner.title.text())
    check("起始计数是「0 / 60」", banner.count.text() == "0 / 60",
          banner.count.text())
    check("进度条可见", not banner.bar.isHidden())
    banner.set_progress(12, 60)
    check("推进到「12 / 60」", banner.count.text() == "12 / 60", banner.count.text())
    check("进度条真的走到 12/60",
          (banner.bar.value(), banner.bar.maximum()) == (12, 60),
          f"{banner.bar.value()}/{banner.bar.maximum()}")

    banner.show_failure("部分项目处理失败", 58,
                        [("报表.xlsx", "被占用或无权限"),
                         ("预算表.xlsx", "权限不足")],
                        [("旧稿.docx", "已跳过（桌面已有同名文件）")])
    check("标题换成「部分项目处理失败」",
          banner.title.text() == "部分项目处理失败", banner.title.text())
    check("计数是「成功 58 · 失败 2 · 跳过 1」",
          banner.count.text() == "成功 58 · 失败 2 · 跳过 1", banner.count.text())
    check("失败时进度条收起（已经不是进行中了）", banner.bar.isHidden())
    check("有「查看详情」入口", not banner.link.isHidden(), banner.link.text())
    check("明细里列了 3 条（2 失败 + 1 跳过）", banner.row_count == 3,
          str(banner.row_count))
    banner.toggle_detail()
    check("点开之后明细真的展开", not banner.detail.isHidden())
    check("按钮文案变成「收起详情」", banner.link.text() == "收起详情",
          banner.link.text())

    # ==================================================================
    section("3. 权限问题：每一条都给 [重试] [跳过]")
    # ==================================================================
    rows = banner._rows                      # noqa: SLF001 - 自检要看明细
    first = rows[0]
    buttons = [b.text() for b in first.findChildren(QPushButton)]
    check("失败行有「重试」和「跳过」两个按钮",
          buttons == ["重试", "跳过"], str(buttons))
    skipped_row = rows[2]
    buttons = [b.text() for b in skipped_row.findChildren(QPushButton)]
    check("跳过的那些只给「跳过」（重试没有意义）",
          buttons == ["跳过"], str(buttons))

    retried, skipped = [], []
    banner.retry_requested.connect(retried.append)
    banner.skip_requested.connect(skipped.append)
    # 主面板就是这么接的：跳过 = 把这一行从明细里划掉（见 MainPanel.skip_item）
    banner.skip_requested.connect(banner.drop_row)
    for button in first.findChildren(QPushButton):
        if button.text() == "重试":
            button.click()
    check("点「重试」会发出重试请求（带条目名）",
          retried == ["报表.xlsx"], str(retried))
    for button in first.findChildren(QPushButton):
        if button.text() == "跳过":
            button.click()
    check("点「跳过」会发出跳过请求", skipped == ["报表.xlsx"], str(skipped))
    check("跳过之后这一行从明细里消失", banner.row_count == 2,
          str(banner.row_count))
    check("计数同步减一",
          banner.count.text() == "成功 58 · 失败 1 · 跳过 1", banner.count.text())

    # ==================================================================
    section("4. 主面板：完成态与失败态各自的说法")
    # ==================================================================
    from panel import MainPanel

    panel = MainPanel(cfg)
    panel.resize(940, 680)

    class _Result:
        def __init__(self, moved=0, failed=None, skipped=None):
            self.moved = moved
            self.failed = failed or []
            self.skipped = skipped or []
            self.cancelled = False
            self.duration = 0.0
            self.moves = []

    panel.begin_operation("正在收纳…", 60)
    check("开始搬运：两个按钮都灰掉",
          not panel.btn_take.isEnabled() and not panel.btn_restore.isEnabled())
    check("开始搬运：状态条进入进度态",
          panel.banner.property("state") == "progress",
          str(panel.banner.property("state")))
    panel.update_progress(12, 60, "文件00.txt")
    check("面板上的进度也在走", panel.banner.count.text() == "12 / 60",
          panel.banner.count.text())

    panel.finish_operation(_Result(moved=60), "take")
    check("全部成功：Toast 是「✓ 已收纳 / 60 个项目」两行",
          panel.toast.text() == "✓ 已收纳\n60 个项目", repr(panel.toast.text()))
    check("全部成功：状态条收起来（不占地方）", panel.banner.isHidden())
    check("全部成功：忙碌标记解除", panel._busy is False)      # noqa: SLF001

    panel.begin_operation("正在还原…", 60)
    panel.finish_operation(
        _Result(moved=58, failed=[("报表.xlsx", "被占用或无权限"),
                                  ("预算表.xlsx", "权限不足")]), "restore")
    check("有失败：标题是「部分项目处理失败」",
          panel.banner.title.text() == "部分项目处理失败",
          panel.banner.title.text())
    check("有失败：计数说清成功/失败",
          panel.banner.count.text().startswith("成功 58 · 失败 2"),
          panel.banner.count.text())
    check("有失败：状态条留在界面上（不是一闪而过）",
          not panel.banner.isHidden())
    check("有失败：同时给一条警告 Toast（⚠ 开头）",
          panel.toast.text().startswith("⚠ "), panel.toast.text())
    check("有失败：明细可以展开",
          not panel.banner.link.isHidden() and panel.banner.row_count == 2)
    panel.clear_banner()

    panel.fail_operation("操作失败：PermissionError")
    check("整体失败：用危险色，不是静默",
          panel.banner.property("state") == "error"
          and panel.toast.text().startswith("× "),
          f"{panel.banner.property('state')} / {panel.toast.text()}")
    panel.clear_banner()

    # ==================================================================
    section("5. 文件冲突：预检只读、跳过不动、替换不删")
    # ==================================================================
    result = nest.take_from_desktop(desktop)
    check("先把桌面收干净（准备冲突场景）", result.moved == 6, result.summary())
    check("桌面已空", not list(desktop.iterdir()))

    # 用户又往桌面上放了一个同名文件
    (desktop / "文件00.txt").write_text("桌面上新放的那份", encoding="utf-8")

    plan = nest.restore_plan(desktop)
    conflict = [row for row in plan if row["name"] == "文件00.txt"]
    check("预检能认出冲突项", conflict and conflict[0]["exists"] is True,
          str(conflict[:1]))
    check("预检不改文件：收纳里那份还在",
          (store / "文件00.txt").exists())
    check("预检不改文件：桌面那份也还在",
          (desktop / "文件00.txt").read_text(encoding="utf-8")
          == "桌面上新放的那份")
    check("没有冲突的项标成 exists=False",
          all(row["exists"] is False for row in plan if row["name"] != "文件00.txt"))

    # ---- 跳过 ----
    result = nest.restore_to_desktop(desktop, skip={"文件00.txt"})
    check("跳过：这一项留在收纳目录里", (store / "文件00.txt").exists())
    check("跳过：记进 skipped 并说明原因",
          any(name == "文件00.txt" for name, _why in result.skipped),
          str(result.skipped))
    check("跳过：桌面上的同名文件一个字节都没动",
          (desktop / "文件00.txt").read_text(encoding="utf-8")
          == "桌面上新放的那份")
    check("跳过：其余 5 项正常还原", result.moved == 5, result.summary())

    # ---- 替换（复用现有逻辑：先收进收纳，再把收纳里那份放回去）----
    taken = nest.take_from_desktop(
        desktop, items=[_PathItem(desktop / "文件00.txt")])
    check("替换第一步：桌面那份被收进收纳", taken.moved == 1, taken.summary())
    old_names = {Path(final).name for _src, final in taken.moves}
    check("替换第一步：收纳里已有同名，所以自动改名成 (1)",
          old_names == {"文件00 (1).txt"}, str(old_names))
    check("替换第一步：旧文件**没被删**，只是换了地方",
          all((store / name).exists() for name in old_names))

    result = nest.restore_to_desktop(desktop, skip=old_names)
    check("替换第二步：桌面恢复成收纳里那一份",
          (desktop / "文件00.txt").read_text(encoding="utf-8") == "内容-0")
    check("替换第二步：旧版本仍安全躺在收纳里",
          (store / "文件00 (1).txt").exists())
    check("替换全程没有覆盖：桌面上一份、收纳里一份",
          len(list(desktop.iterdir())) == 6, str(len(list(desktop.iterdir()))))

    # ---- 老规则没被动 ----
    probe = base / "重名探针.txt"
    probe.write_text("x", encoding="utf-8")
    check("重名仍然自动加 (1)（原有冲突处理一行没改）",
          nest._unique(probe).name == "重名探针 (1).txt",   # noqa: SLF001
          nest._unique(probe).name)                        # noqa: SLF001

    # ==================================================================
    section("6. 后台搬运线程：进度真的在报，不是假动画")
    # ==================================================================
    import tray_app

    events, done = [], {}
    worker = tray_app.OperationWorker(desktop, "take")
    worker.progressed.connect(lambda i, t, n: events.append((i, t, n)))
    worker.finished.connect(lambda r, k: done.update(result=r, kind=k))
    worker.start()
    pump_until(app, lambda: not worker.isRunning(), 20)
    worker.wait(5000)
    app.processEvents()

    check("进度回调次数 = 条目数（6）", len(events) == 6, str(len(events)))
    check("进度是从 1 数到 6 的",
          [e[0] for e in events] == [1, 2, 3, 4, 5, 6], str([e[0] for e in events]))
    check("每次回调都带总数", all(e[1] == 6 for e in events), str(events[:2]))
    check("回调里带条目名（出问题能说清是哪一项）",
          all(e[2] for e in events), str(events[:2]))
    check("结束时带回结果与动作类型",
          done.get("kind") == "take" and done.get("result").moved == 6,
          f"{done.get('kind')} / {getattr(done.get('result'), 'moved', None)}")

    # ==================================================================
    section("7. 端到端：从主程序点「收纳桌面」到 Toast")
    # ==================================================================
    tray = tray_app.TrayApp(cfg, silent=True)
    pump_until(app, lambda: tray._scan is None, 20)          # noqa: SLF001
    for _ in range(20):
        app.processEvents()

    # 先把桌面收空，验证"没东西可收"不弹窗
    nest.take_from_desktop(desktop)
    dialogs = []
    real_information = QMessageBox.information
    real_warning = QMessageBox.warning
    real_question = QMessageBox.question
    QMessageBox.information = staticmethod(lambda *a, **k: dialogs.append(("info", a)))
    QMessageBox.warning = staticmethod(lambda *a, **k: dialogs.append(("warn", a)))
    QMessageBox.question = staticmethod(
        lambda *a, **k: dialogs.append(("question", a)) or QMessageBox.StandardButton.No)
    try:
        dialogs.clear()
        tray.take_desktop_now()
        check("桌面是空的：不弹任何对话框", not dialogs, str(dialogs))
        check("桌面是空的：给了一条警告 Toast",
              tray.panel.toast.text().startswith("⚠ "),
              tray.panel.toast.text())

        # 再放 8 项进来，跑一次真正的异步收纳
        for index in range(8):
            (desktop / f"端到端{index}.txt").write_text("x", encoding="utf-8")
        dialogs.clear()
        tray.take_desktop_now()
        check("点了之后立刻进入进度态（不会卡住界面）",
              tray.panel.banner.property("state") == "progress",
              str(tray.panel.banner.property("state")))
        check("进度文案是「正在收纳…」",
              tray.panel.banner.title.text() == "正在收纳…",
              tray.panel.banner.title.text())
        check("按钮同时灰掉，防止点第二遍",
              not tray.panel.btn_take.isEnabled())
        finished = pump_until(app, lambda: tray._op is None, 20)   # noqa: SLF001
        check("后台线程在 20 秒内收尾", finished)
        for _ in range(10):
            app.processEvents()
        check("收纳完 8 项", tray.panel.toast.text() == "✓ 已收纳\n8 个项目",
              repr(tray.panel.toast.text()))
        check("收纳成功后状态条收起", tray.panel.banner.isHidden())
        check("桌面真的空了", not list(desktop.iterdir()),
              str([p.name for p in desktop.iterdir()]))
        check("全程没有弹对话框", not dialogs, str(dialogs))

        # ---- 还原：空收纳也不弹窗 ----
        nest.restore_to_desktop(desktop)          # 先清空收纳目录
        dialogs.clear()
        tray.restore_desktop()
        check("收纳目录是空的：不弹对话框", not dialogs, str(dialogs))
        check("收纳目录是空的：给了一条警告 Toast",
              tray.panel.toast.text().startswith("⚠ "),
              tray.panel.toast.text())

        # ---- 还原：有冲突时才弹，而且只有这一种弹窗 ----
        nest.take_from_desktop(desktop)
        (desktop / "文件00.txt").write_text("又放了一份", encoding="utf-8")
        dialogs.clear()
        # 对话框会阻塞：把 exec 换成"看一眼然后点取消"
        seen: "dict[str, object]" = {}
        real_exec = QMessageBox.exec

        def fake_exec(box):
            seen["text"] = box.text()
            seen["buttons"] = [b.text() for b in box.buttons()]
            default = box.defaultButton()
            seen["default"] = default.text() if default is not None else ""
            return 0

        QMessageBox.exec = fake_exec
        try:
            tray.restore_desktop()
        finally:
            QMessageBox.exec = real_exec
        check("有同名文件时才弹冲突对话框",
              seen.get("text") == "文件已存在", str(seen.get("text")))
        check("冲突对话框给的是「替换 / 跳过 / 取消」三个选择",
              sorted(seen.get("buttons") or []) == sorted(["替换", "跳过", "取消"]),
              str(seen.get("buttons")))
        check("默认按钮是「取消」（回车不会误选替换）",
              seen.get("default") == "取消", str(seen.get("default")))
        check("选了取消就真的什么都没动",
              (store / "文件00.txt").exists()
              and (desktop / "文件00.txt").read_text(encoding="utf-8")
              == "又放了一份")
        check("冲突对话框之外没有再弹别的窗", not dialogs, str(dialogs))
    finally:
        QMessageBox.information = real_information
        QMessageBox.warning = real_warning
        QMessageBox.question = real_question

    # ==================================================================
    section("8. 失败明细能真的重试（走的是原有单项入口）")
    # ==================================================================
    (desktop / "重试我.txt").write_text("x", encoding="utf-8")
    ok, why = tray._retry_one("take", "重试我.txt")          # noqa: SLF001
    check("单项重试成功", ok is True, why)
    check("重试真的把文件搬走了", not (desktop / "重试我.txt").exists())
    check("重试走的是同一个收纳目录", (store / "重试我.txt").exists())

    tray.panel.banner.show_failure(
        "部分项目处理失败", 1, [("重试我.txt", "被占用或无权限")])
    check("明细里有这一条", tray.panel.banner.row_count == 1)
    tray._on_skip_item("重试我.txt")                         # noqa: SLF001
    check("点跳过之后明细清空", tray.panel.banner.row_count == 0)
    check("跳过只动界面，不动文件（文件还在收纳里）",
          (store / "重试我.txt").exists())

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)

    tray._quitting = True
    tray.shutdown()
    app.processEvents()
    return 1 if FAIL else 0


class _PathItem:
    """`nest.take_from_desktop(items=...)` 认得的最小对象（和主程序里那个同款）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = self.path.name
        self.source = ""


if __name__ == "__main__":
    raise SystemExit(main())
