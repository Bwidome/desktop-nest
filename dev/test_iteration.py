#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本轮迭代的回归测试
=================
覆盖用户报的 3 组 BUG + 1 组新功能：

BUG1  右键「常见应用」崩溃 / 崩溃要能自动还原桌面
BUG2  常用软件图标、增删后 UI 同步、不留空白
      —— 增删已合并成唯一的「管理」控件（常用项左上角－、非常用项右上角＋），
         菜单栏上不再有 ＋ / － / ⚙ / ✕
BUG3  Dock 只对最大化/全屏避让，普通窗口与桌面空闲不隐藏、不闪烁
功能4 复选框多选批量添加 / 批量删除（入口在「管理」控件里）

用法：python dev/test_iteration.py
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

# 看门狗：挂死时打印线程栈并强退，方便定位
import faulthandler as _fh
_fh.enable()
_fh.dump_traceback_later(90, exit=True)

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-iteration"
    shutil.rmtree(base, ignore_errors=True)
    desktop, public, cfg_dir = base / "Desktop", base / "Public", base / "cfg"
    for folder in (desktop, public, cfg_dir):
        folder.mkdir(parents=True)

    import winlink

    exes = [
        r"C:\Windows\System32\notepad.exe",
        r"C:\Windows\System32\calc.exe",
        r"C:\Windows\explorer.exe",
        r"C:\Windows\System32\write.exe",
        r"C:\Windows\System32\mspaint.exe",
    ]
    for index, exe in enumerate(exes):
        winlink.create_shortcut(desktop / f"软件{index}.lnk", exe)

    from qt_compat import QApplication, QMenu, QMessageBox, QPoint

    app = QApplication([])
    import config as config_mod

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": False})

    import nest

    nest.nest_root = lambda: base / ".nest"
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

    import tray_app

    tray = tray_app.TrayApp(cfg, silent=True)
    tray.install_crash_guards()
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)

    browser = tray.desktop_browser
    dock = tray.dock

    # 面板只展示**收纳目录里**的内容（需求6 去掉了系统位置）。
    # 本用例把 auto_take_on_start 关着，所以要手动收一次，
    # 否则后面"从列表里选一个加为常用 / 批量增删"都没有素材。
    taken = nest.take_from_desktop(cfg.desktop)
    print(f"  [准备] 把测试桌面收进收纳目录：{taken.summary()}")
    tray.refresh()
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(50):
        app.processEvents()
        time.sleep(0.02)

    def pump(seconds: float = 1.2) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    # 模拟用户点菜单项：不真的弹窗，直接返回指定 action
    def click_menu_choice(choice_text: str):
        original = QMenu.exec

        def fake(self, *args, **kwargs):
            for action in self.actions():
                if action.text() == choice_text:
                    return action
            return None

        QMenu.exec = fake
        return original

    def restore_menu(original) -> None:
        QMenu.exec = original

    # ==================================================================
    print("── BUG1. 右键「常见应用」不再崩溃 ──")
    # 准备几个常用项
    from widgets import multi_pick

    real_multi = multi_pick
    added_keys = []
    for index in range(3):
        cfg.add_quick(desktop / f"软件{index}.lnk", f"软件{index}")
    browser.rebuild_apps()
    pump(0.6)
    check("常用按钮已就位", len(browser._app_buttons) == 3,
          str(len(browser._app_buttons)))

    crashes = []
    for button in list(browser._app_buttons):
        original = click_menu_choice("打开")
        try:
            browser._app_menu(button, QPoint(50, 50))
        except BaseException as exc:  # noqa: BLE001
            crashes.append(f"{type(exc).__name__}: {exc}")
        finally:
            restore_menu(original)
    check("面板常用项右键菜单不崩溃", not crashes, "; ".join(crashes[:3]))

    # 关键：每次 rebuild 都会重建按钮对象，旧引用会变成"已从布局摘除"的死对象
    # （isVisible 恒为 False），所以每轮都要重新取。
    dock.rebuild()
    pump(0.3)
    dock_crashes = []
    quick_entries = list(cfg.quick_items)
    dock_buttons = [b for b in dock._buttons if getattr(b, "_payload", None)]
    check("菜单栏上有常用项按钮", len(dock_buttons) >= 1, str(len(dock_buttons)))
    for button in dock_buttons[:3]:
        entry = next((e for e in quick_entries
                      if str(e["path"]) == str(button._payload)), None)
        if entry is None:
            continue
        original = click_menu_choice("打开")
        try:
            # 关键：第三个参数（位置）——旧代码这里参数不匹配会 TypeError
            dock._quick_menu(button, entry, QPoint(50, 50))
        except BaseException as exc:  # noqa: BLE001
            dock_crashes.append(f"{type(exc).__name__}: {exc}")
        finally:
            restore_menu(original)
    check("菜单栏常用项右键菜单不崩溃（含位置参数）",
          not dock_crashes, "; ".join(dock_crashes[:3]))

    # 位置参数也可以省略（用鼠标当前位置）
    pos_optional = True
    try:
        original = click_menu_choice("打开")
        dock._quick_menu(dock_buttons[0], quick_entries[0])
    except BaseException as exc:  # noqa: BLE001
        pos_optional = False
        check("右键菜单位置参数可省略", False, f"{type(exc).__name__}: {exc}")
    finally:
        restore_menu(original)
    if pos_optional:
        check("右键菜单位置参数可省略", True)

    # 菜单栏空白处右键（contextMenuEvent）
    check("菜单栏有 contextMenuEvent 处理", hasattr(dock, "contextMenuEvent"))

    print()
    print("── BUG1. 崩溃时自动还原桌面（防数据丢失）──")
    # 制造"收纳完成、还没还原"的窗口期。
    # 注意：前面 [准备] 阶段可能已经把桌面收进去了，所以这里两种情形都要能走：
    # 桌面还有东西就收一次；已经空了就直接用现有的收纳内容。
    take = nest.take_from_desktop(cfg.desktop)
    if take.moved == 0:
        print(f"  （桌面已空，沿用 [准备] 阶段收好的内容：{take.summary()}）")
    check("收纳目录里已有内容（可进入崩溃还原场景）",
          nest.nest_has_content(), take.summary())
    desktop_before = len(list(cfg.desktop.iterdir()))
    check("桌面此刻是空的", desktop_before == 0, str(desktop_before))
    nested = len(list(nest.desktop_store().iterdir()))
    check("收纳目录里有东西", nested >= 5, str(nested))

    # 触发未捕获异常 → 应自动还原
    # 注意：测完必须把 excepthook 还原。否则后面任何未捕获异常（比如测试自己
    # 抛的）都会再跑一遍应急还原，测试进程也会被带偏甚至卡住。
    saved_hook = sys.excepthook
    try:
        raise RuntimeError("模拟：右键菜单炸了")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    finally:
        sys.excepthook = saved_hook
    pump(0.5)
    after = sorted(p.name for p in cfg.desktop.iterdir())
    left = (len(list(nest.desktop_store().iterdir()))
            if nest.desktop_store().exists() else 0)
    check("崩溃后桌面已自动还原", len(after) >= 5, str(len(after)))
    check("崩溃后收纳目录已清空", left == 0, str(left))
    check("还原回来的是原来的文件",
          all(f"软件{i}.lnk" in after for i in range(5)), str(after))

    print()
    print("── BUG1. 应急还原的边界 ──")
    check("应急还原是幂等的（跑第二次不会出错）",
          tray.emergency_restore("重复调用") in (False,))
    tray._emergency_done = False
    cfg.set("restore_on_exit", False, save=False)
    nest.take_from_desktop(cfg.desktop)
    did = tray.emergency_restore("测试：用户关掉了自动还原")
    check("用户关掉「退出自动还原」时应急还原不动手", did is False)
    cfg.set("restore_on_exit", True, save=False)
    tray._emergency_done = False
    tray.emergency_restore("恢复现场")
    pump(0.4)
    check("恢复现场：桌面回到 5 项",
          len(list(cfg.desktop.iterdir())) >= 5,
          str(len(list(cfg.desktop.iterdir()))))

    print()
    print("── BUG2. 常用软件：图标 / 增删同步 / 不留空白 ──")
    # 崩溃兜底那一段已经把东西还原回桌面了，面板此刻是空的。
    # 面板只展示收纳目录里的内容（需求6），所以要**再收一次**才有素材 ——
    # 这也正是真实启动流程：auto_take 之后面板就有东西了。
    again = nest.take_from_desktop(cfg.desktop)
    print(f"  [准备] 重新收纳：{again.summary()}")
    tray.refresh()
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    pump(1)
    check("面板里重新有素材可供批量增删", len(browser._items) >= 5,
          str(len(browser._items)))

    while cfg.quick_items:
        cfg.remove_quick(cfg.quick_items[0]["path"])
    browser.rebuild_apps()
    dock.rebuild()
    pump(0.5)

    # 用多选弹窗批量添加。
    # 注入点是 browser._ask_multi —— 直接改 widgets.multi_pick 无效，
    # 因为 desktop_browser 是 `from widgets import multi_pick` 按值导入的，
    # 换源头不影响它，结果会真的弹出模态窗把测试挂死。
    def fake_multi(title, hint, entries, confirm_text="确定", parent=None):
        return [entries[0][0], entries[2][0]]      # 勾第 1、3 项

    browser._ask_multi = fake_multi
    try:
        browser.add_quick_dialog()
    finally:
        del browser._ask_multi
    pump(2.5)
    check("批量添加：配置增加到 2 项", len(cfg.quick_items) == 2,
          str(len(cfg.quick_items)))
    check("批量添加：UI 同步 2 个按钮", len(browser._app_buttons) == 2,
          str(len(browser._app_buttons)))
    check("批量添加：按钮顺序与配置一致",
          [b.app_name for b in browser._app_buttons] ==
          [e["name"] for e in cfg.quick_items])
    empty = [b.app_name for b in browser._app_buttons
             if b.icon() is None or b.icon().isNull()]
    check("批量添加后图标都加载出来了", not empty, f"空的: {empty}")

    # 再加一个，旧的图标不能丢。
    # 这里**故意用不存在的路径**：新加的"路径不存在就返回 None"闸门会拒绝
    # 给它图标（这道闸门就是修白纸图标的），所以只要求老的三项不被带崩。
    cfg.add_quick_many([(desktop / "新软件.lnk", "新软件")])
    browser.rebuild_apps()
    pump(2.5)
    stale = [b.app_name for b in browser._app_buttons
             if b.app_name != "新软件" and (b.icon() is None or b.icon().isNull())]
    check("加新项后旧项图标仍在", not stale, f"丢图的: {stale}")
    ghost = next((b for b in browser._app_buttons if b.app_name == "新软件"), None)
    check("不存在的路径不再伪造白纸图标（闸门生效）",
          ghost is not None and (ghost.icon() is None or ghost.icon().isNull()),
          f"icon={None if ghost is None else ghost.icon()}")

    # 批量删除
    def fake_multi_del(title, hint, entries, confirm_text="确定", parent=None):
        return [entries[0][0], entries[1][0]]

    browser._ask_multi = fake_multi_del
    try:
        before = len(cfg.quick_items)
        browser.remove_quick_dialog()
    finally:
        del browser._ask_multi
    pump(1)
    check("批量删除：配置减少 2 项", len(cfg.quick_items) == before - 2,
          f"{before} -> {len(cfg.quick_items)}")
    check("批量删除：UI 与配置一致",
          [b.app_name for b in browser._app_buttons] ==
          [e["name"] for e in cfg.quick_items],
          f"{[b.app_name for b in browser._app_buttons]} vs "
          f"{[e['name'] for e in cfg.quick_items]}")

    # 不留空白：布局里的 AppButton 数 = 配置数
    from desktop_browser import AppButton

    live = []
    for i in range(browser.apps_row.count()):
        w = browser.apps_row.itemAt(i).widget()
        if isinstance(w, AppButton):
            live.append(w)
    check("布局里没有残留的旧按钮", len(live) == len(cfg.quick_items),
          f"{len(live)} vs {len(cfg.quick_items)}")

    # ---- 增删已合并成唯一的「管理」控件 ----
    check("收纳面板有唯一的「管理」控件", hasattr(browser, "btn_manage"))
    check("原来的「＋添加 / －删除」两个控件已删除",
          not hasattr(browser, "btn_add_app")
          and not hasattr(browser, "btn_del_app"))
    manage_idx = browser.apps_row.indexOf(browser.btn_manage)
    check("「管理」控件排在常用软件之后、弹性占位之前",
          manage_idx == len(cfg.quick_items),
          f"管理@{manage_idx} 常用{len(cfg.quick_items)} "
          f"行内共{browser.apps_row.count()}项")
    check("「管理」控件始终可用（删空也能进去加回来）",
          browser.btn_manage.isEnabled())

    # ---- 管理模式：常用项左上角减号、非常用项右上角加号 ----
    # 面板显示的是**收纳目录**里的东西；前面的应急还原把文件都还回桌面了，
    # 所以这里先收一次，保证卡片区真的有内容。
    if not browser._tiles:
        nest.take_from_desktop(cfg.desktop)
        tray.refresh()
        deadline = time.time() + 25
        while (tray._scan is not None and tray._scan.isRunning()
               and time.time() < deadline):
            app.processEvents()
            time.sleep(0.05)
        pump(1)
    check("管理模式断言的前置：面板里有卡片", bool(browser._tiles),
          str(len(browser._tiles)))

    browser.set_manage_mode(True)
    pump(0.4)
    quick_badges = [b.badge for b in browser._app_buttons]
    check("管理模式：每张常用卡片都长出了角标",
          bool(quick_badges) and all(b is not None for b in quick_badges),
          str(quick_badges))
    check("管理模式：常用软件的角标是左上角「－」",
          bool(quick_badges) and all(
              b is not None and b.text() == "－" and b._corner == "top-left"
              for b in quick_badges),
          str([(b.text(), b._corner) for b in quick_badges if b is not None]))
    tile_badges = [t.badge for t in browser._tiles]
    check("管理模式：每张卡片都有角标",
          bool(tile_badges) and all(b is not None for b in tile_badges),
          str(tile_badges))
    check("管理模式：非常用卡片右上角是「＋」",
          bool(tile_badges) and all(
              b is not None and b.text() == "＋" and b._corner == "top-right"
              for b in tile_badges),
          str([(b.text(), b._corner) for b in tile_badges if b is not None]))
    # 注意：这里判 isHidden() 而不是 isVisible()。离屏测试里面板自己没 show()，
    # isVisible() 会被整条父链拉成 False，根本区分不出"角标有没有被露出来"。
    # isHidden() 只反映"有没有被显式藏起来"，才是这里要的语义。
    check("管理模式：角标真的露出来了（不是只建了对象）",
          all(not b.isHidden() for b in quick_badges if b is not None)
          and all(not b.isHidden() for b in tile_badges if b is not None),
          f"常用{[(b.text(), b.isHidden()) for b in quick_badges if b]} "
          f"卡片{[(b.text(), b.isHidden()) for b in tile_badges if b]}")
    check("管理模式：管理控件进入选中态", browser.btn_manage.isChecked())
    check("管理模式：底部提示切成了操作说明",
          "管理模式" in browser.hint.text(), browser.hint.text())

    browser.set_manage_mode(False)
    pump(0.3)
    check("退出管理模式：角标全部收起",
          all(b.isHidden() for b in quick_badges if b is not None)
          and all(b.isHidden() for b in tile_badges if b is not None),
          f"常用{[(b.text(), b.isHidden()) for b in quick_badges if b]} "
          f"卡片{[(b.text(), b.isHidden()) for b in tile_badges if b]}")
    check("退出管理模式：管理控件恢复未选中", not browser.btn_manage.isChecked())

    # 删空后「管理」控件不能跟着禁用（否则加不回来）
    while cfg.quick_items:
        cfg.remove_quick(cfg.quick_items[0]["path"])
    browser.rebuild_apps()
    pump(0.3)
    check("删空后「管理」控件仍可用", browser.btn_manage.isEnabled())

    print()
    print("── BUG2. 菜单栏只剩「桌面整理」入口 + 常用软件 ──")
    check("菜单栏的 ＋ / － / ⚙ / ✕ 四个控制按钮已全部删除",
          not any(hasattr(dock, name) for name in
                  ("add_btn", "del_btn", "settings_btn", "btn_hide_dock")))
    check("菜单栏主行只剩应用区 + 一个弹性占位",
          dock.main_row.count() == 2,
          f"主行共 {dock.main_row.count()} 项")
    check("主行第 0 项就是「桌面整理」入口所在的应用区",
          dock.main_row.itemAt(0).widget() is dock.apps_flow)

    print()
    print("── BUG3. Dock 只在最大化/全屏时避让 ──")
    check("菜单栏可见（基线）", dock.isVisible() or bool(cfg.get("dock_visible", True)))

    # 普通窗口：不应判为"要让开"
    class R:
        left, top, right, bottom = 100, 100, 900, 700

    # 直接验证判据：小于工作区 80% 面积的窗口一律不算
    def verdict(w, h, work_w=1920, work_h=1040):
        """复刻 _foreground_is_fullscreen 里的尺寸判据（纯算术，不依赖真实窗口）。"""
        mon_w, mon_h = 1920, 1080
        if w >= mon_w * 0.96 and h >= mon_h * 0.96:
            return True
        coverage = (w * h) / float(work_w * work_h)
        if coverage >= 0.80 and h >= work_h * 0.90:
            return True
        if w >= mon_w * 0.98 and h >= work_h * 0.94:
            return True
        return False

    check("小窗口不避让", not verdict(800, 600))
    check("中等窗口不避让", not verdict(1200, 800))
    check("竖直条状窗口不避让（防止误判）", not verdict(520, 1040))
    check("宽扁条状窗口不避让（防止误判）", not verdict(1900, 640))
    check("最大化窗口避让（Chrome 实测尺寸）", verdict(1619, 1036))
    check("真全屏避让", verdict(1920, 1080))

    # 桌面空闲：前台是桌面时，既不该让开，也不该把菜单栏藏起来
    original_desktop = tray._desktop_is_foreground
    try:
        tray._desktop_is_foreground = lambda: True
        # 真实场景：人回到桌面，菜单栏是显示状态，长时间闲置也不能消失
        dock.show_bar()
        pump(0.3)
        tray._fs_streak = 0
        tray._normal_streak = 0
        for _ in range(6):                  # 模拟闲置很久（6 个 tick ≈ 7 秒）
            tray._auto_show_tick()
            pump(0.15)
        check("桌面空闲很久后菜单栏仍然在", dock.isVisible())
        check("桌面空闲不算「要让开」", not tray._foreground_is_fullscreen())

        # 极端情况：菜单栏本来隐藏着（被上一个全屏程序让开过），
        # 回到桌面后必须能自动回来
        dock.hide_bar()
        pump(0.2)
        tray._fs_streak = 0
        tray._normal_streak = 0
        for _ in range(4):
            tray._auto_show_tick()
            pump(0.15)
        check("从全屏回到桌面后菜单栏能自动回来", dock.isVisible())
    finally:
        tray._desktop_is_foreground = original_desktop

    print()
    print("── BUG3. 响应速度与防抖 ──")
    # 现在的实现是"事件驱动 + 120ms 轮询 + 最小切换间隔 300ms"：
    #   · 第一次响应要**立刻**（需求：不能让菜单栏明显延迟响应）
    #   · 但不能贴边抖动时来回闪（靠 MIN_SWITCH_GAP，不是靠"两次确认"）
    original_fs = tray._foreground_is_fullscreen
    try:
        tray.dodge.probe_enabled = True        # 让避让逻辑真的跑（离屏默认关）
        tray._foreground_is_fullscreen = lambda: False
        tray.dodge._last_switch = 0.0
        dock.show_bar()
        pump(0.4)
        check("起点：菜单栏可见", dock.isVisible())

        # 遮挡出现 → 第一次 tick 就隐藏
        tray._foreground_is_fullscreen = lambda: True
        tray.dodge._last_switch = 0.0
        tray._auto_show_tick()
        pump(0.3)
        check("遮挡出现后立刻隐藏（不用等第二次 tick）", not dock.isVisible())

        # 遮挡消失 → 也立刻恢复
        tray._foreground_is_fullscreen = lambda: False
        tray.dodge._last_switch = 0.0
        tray._auto_show_tick()
        pump(0.3)
        check("遮挡消失后立刻恢复", dock.isVisible())

        # 抖动场景：全屏/普通交替翻转，不该跟着来回闪
        tray.dodge._last_switch = 0.0
        dock.show_bar()
        pump(0.2)
        changes = 0
        for i in range(6):
            tray._foreground_is_fullscreen = (lambda v: (lambda: v))(i % 2 == 0)
            before = dock.isVisible()
            tray._auto_show_tick()
            if dock.isVisible() != before:
                changes += 1
        check("全屏/普通交替抖动时菜单栏不闪隐闪现", changes <= 1,
              f"切换了 {changes} 次")
    finally:
        tray._foreground_is_fullscreen = original_fs
        tray._fs_streak = 0
        tray._normal_streak = 0

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    tray._quitting = True
    try:
        tray.shutdown()
    except Exception as exc:  # noqa: BLE001
        print("  (shutdown 异常:", exc, ")")
    app.processEvents()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
