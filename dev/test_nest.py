#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳（nest）自检
===================
验证核心行为：

* 启动收纳：桌面 → 收纳目录，**桌面清空**
* 文件夹整体搬走（不拆内层）
* 系统位置快捷方式（此电脑 / 回收站）被创建、能被识别、能打开
* 退出还原：收纳目录 → 桌面，原样回来
* 分页：收纳面板的翻页与边界（菜单栏上那排分页条目已经移除）
* 搜索：模糊匹配、命中收拢到一页
* 显示文件后缀名开关：只改界面文字、不动磁盘文件、搜索两种写法都命中
* 打开 / 反复翻页收纳面板时，底部 Dock 不会无故消失
* 图标 + 下方名称的显示方式
* 整个程序能一起构造、启动即收纳、退出即还原

用法：python dev/test_nest.py [--shots]
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


def _settings_flag(cfg) -> bool:
    """设置窗口里的「显示文件后缀名」开关读到的值。"""
    from settings import SettingsDialog

    dialog = SettingsDialog(cfg, None, dark=False)
    try:
        return bool(dialog.chk_extensions.isChecked())
    finally:
        dialog.deleteLater()


def build_sandbox():
    base = Path(tempfile.gettempdir()) / "nest-v2-test"
    shutil.rmtree(base, ignore_errors=True)
    desktop, cfg_dir = base / "Desktop", base / "cfg"
    public = base / "PublicDesktop"
    for folder in (desktop, cfg_dir, public):
        folder.mkdir(parents=True)

    for index in range(30):
        (desktop / f"文件{index:02d}.txt").write_text(f"内容-{index}" * 4,
                                                      encoding="utf-8")
    # 两个文件夹，带嵌套
    folder_a = desktop / "资料夹A"
    folder_a.mkdir()
    (folder_a / "内层.txt").write_text("inner", encoding="utf-8")
    (folder_a / "子目录").mkdir()
    (folder_a / "子目录" / "深层.txt").write_text("deeper", encoding="utf-8")

    folder_b = desktop / "项目B"
    folder_b.mkdir()
    (folder_b / "说明.md").write_text("readme", encoding="utf-8")

    # 一个真的快捷方式
    import winlink

    winlink.create_shortcut(desktop / "记事本.lnk", r"C:\Windows\System32\notepad.exe")

    # 公共桌面（所有用户都能看到的那一份）
    import config as config_mod

    public_items = ["腾讯会议", "QQ音乐", "IntelliJ IDEA", "MegaDownloader"]
    for index, name in enumerate(public_items):
        winlink.create_shortcut(public / f"{name}.lnk",
                                rf"C:\Windows\System32\notepad.exe")
    (public / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")
    # 故意制造一个和用户桌面同名的，验证重名处理
    winlink.create_shortcut(public / "记事本.lnk", r"C:\Windows\System32\notepad.exe")
    return desktop, public, cfg_dir, base


def main() -> int:
    shots = "--shots" in sys.argv
    desktop, public, cfg_dir, base = build_sandbox()

    import config as config_mod

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop), "panel_on_start": "never",
                "auto_take_on_start": True, "restore_on_exit": True})

    import nest

    # 把收纳根目录指到沙盒，避免动到真实用户目录
    nest.nest_root = lambda: base / ".nest"
    # 把"公共桌面"也指到沙盒，保证测试不碰真实的 C:\Users\Public\Desktop
    config_mod.get_public_desktop_dir = lambda: public
    config_mod.get_desktop_dir = lambda: desktop

    print(f"沙盒个人桌面：{desktop}")
    print(f"沙盒公共桌面：{public}")
    print(f"沙盒收纳：{base / '.nest'}")
    print()

    print("── 0. 个人桌面 + 公共桌面都要被收集 ──")
    all_items, _blocked = nest.list_desktop(desktop)
    personal_items = [i for i in all_items if i.source != "public"]
    public_items = [i for i in all_items if i.source == "public"]
    check("个人桌面识别到 33 项", len(personal_items) == 33, str(len(personal_items)))
    check("公共桌面识别到 5 项（4 个快捷方式 + 1 个与个人桌面同名）",
          len(public_items) == 5, str(len(public_items)))
    check("公共桌面条目带 public 来源标记",
          all(i.source == "public" for i in public_items))
    check("公共桌面的 desktop.ini 被跳过",
          not any(i.name == "desktop.ini" for i in all_items))

    print()
    print("── 1. 启动收纳：两个桌面 → 收纳目录 ──")
    before = sorted(p.name for p in desktop.iterdir())
    check("个人桌面初始有 33 项", len(before) == 33, str(len(before)))
    public_before = sorted(p.name for p in public.iterdir())
    check("公共桌面初始有 6 项（含 desktop.ini）", len(public_before) == 6,
          str(len(public_before)))

    result = nest.take_from_desktop(desktop)
    check("两个桌面一起收纳成功", result.moved == 38, result.summary())
    check("个人桌面已被清空", not list(desktop.iterdir()),
          str(sorted(p.name for p in desktop.iterdir())))
    check("公共桌面只剩 desktop.ini",
          sorted(p.name for p in public.iterdir()) == ["desktop.ini"],
          str(sorted(p.name for p in public.iterdir())))

    store = nest.desktop_store()
    stored = sorted(p.name for p in store.iterdir())
    check("收纳目录收到全部 38 项", len(stored) == 38, str(len(stored)))
    check("公共桌面的条目也在里面", "腾讯会议.lnk" in stored, str(stored[:6]))
    check("与个人桌面同名的那份加了「（公用）」区分",
          "记事本（公用）.lnk" in stored,
          str([n for n in stored if "记事本" in n]))

    print()
    print("── 2. 文件夹整体搬走（不拆内层）──")
    check("文件夹 A 整体存在", (store / "资料夹A").is_dir())
    check("文件夹 A 内层文件还在", (store / "资料夹A" / "内层.txt").is_file())
    check("文件夹 A 深层嵌套保留",
          (store / "资料夹A" / "子目录" / "深层.txt").read_text(encoding="utf-8")
          == "deeper")
    check("文件夹 B 整体存在", (store / "项目B" / "说明.md").is_file())
    check("内层文件没有散落到收纳目录顶层",
          not any(n in stored for n in ("内层.txt", "深层.txt", "说明.md")),
          str([n for n in stored if n in ("内层.txt", "深层.txt", "说明.md")]))

    print()
    print("── 3. 系统位置快捷方式（此电脑 / 回收站）──")
    links = nest.sync_system_links()
    names = [entry.name for entry in links]
    check("创建了「此电脑」", "此电脑" in names, str(names))
    check("创建了「回收站」", "回收站" in names, str(names))
    check("创建了「用户文件夹」", "用户文件夹" in names)
    for entry in links:
        check(f"「{entry.name}」的 .lnk 文件存在", entry.link is not None
              and entry.link.exists())
    check("能查到「此电脑」的 shell 位置",
          nest.shell_path_for(nest.links_store() / "此电脑.lnk").startswith("::"),
          nest.shell_path_for(nest.links_store() / "此电脑.lnk"))
    check("能查到「回收站」的 shell 位置",
          nest.shell_path_for(nest.links_store() / "回收站.lnk").startswith("::"))

    print()
    print("── 4. 面板内容 = 收纳内容 + 系统位置 ──")
    items = nest.list_nest_items()
    check("条目数 = 38 + 4 个系统位置", len(items) == 42, str(len(items)))
    item_names = [i.name for i in items]
    check("包含「此电脑」", "此电脑" in item_names)
    check("包含「回收站」", "回收站" in item_names)
    check("包含收纳的文件夹", "资料夹A" in item_names)
    check("包含那个快捷方式", "记事本.lnk" in item_names)
    folders = [i for i in items if i.is_dir]
    check("文件夹被识别为文件夹", len(folders) == 2, str(len(folders)))

    print()
    print("── 5. 界面：图标 + 下方名称 / 分页 / 搜索 ──")
    from qt_compat import QApplication, QMessageBox, Qt

    app = QApplication(sys.argv)
    import theme as theme_mod

    app.setStyleSheet(theme_mod.stylesheet(False))
    # 离屏自检里把模态框变成"直接确定"，否则会卡住
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

    from desktop_browser import DesktopBrowser, ItemTile, DEFAULT_PER_PAGE

    browser = DesktopBrowser(cfg)
    browser.resize(920, 620)
    browser.set_items(items)
    browser.show_window()
    app.processEvents()

    check("面板构造成功", browser.isVisible())
    check("每页数量为默认值", browser._per_page == DEFAULT_PER_PAGE, str(browser._per_page))
    check("总页数为 2", browser._page_count() == 2, str(browser._page_count()))
    check("第一页放满 28 个", len(browser._tiles) == 28, str(len(browser._tiles)))
    check("页码显示 1/2", browser.page_label.text() == "1 / 2", browser.page_label.text())

    tile = browser._tiles[0]
    check("卡片是「图标 + 下方名称」结构",
          hasattr(tile, "icon_label") and hasattr(tile, "name_label"))
    check("卡片名称文字正确", tile.name_label.text() == tile.item.name,
          f"{tile.name_label.text()} vs {tile.item.name}")
    check("卡片有图标（占位也算）",
          tile.icon_label.pixmap() is not None and not tile.icon_label.pixmap().isNull())

    browser.goto_page(1)
    app.processEvents()
    check("第二页剩余 14 个", len(browser._tiles) == 14, str(len(browser._tiles)))
    check("末页禁用下一页", not browser.btn_next.isEnabled())
    browser.goto_page(999)
    check("越界夹到末页", browser.page_label.text() == "2 / 2")
    browser.goto_page(-3)
    check("负数夹到首页", browser.page_label.text() == "1 / 2")

    browser.search.setText("资料夹")
    browser._rebuild()
    app.processEvents()
    check("搜索「资料夹」命中 1 项", len(browser._matches) == 1, str(len(browser._matches)))
    browser.search.setText("文件00")
    browser._rebuild()
    app.processEvents()
    check("搜索「文件00」精确命中 1 项", len(browser._matches) == 1,
          str([i.name for i in browser._matches][:5]))
    browser.search.setText("文件0")
    browser._rebuild()
    app.processEvents()
    # 连续命中（文件00~文件09）必须都排在顺序命中（文件20 之类）前面
    names = [i.name for i in browser._matches]
    contiguous = [n for n in names if n.startswith("文件0")]
    check("搜索「文件0」把 10 个连续命中排在最前",
          names[:10] == sorted(contiguous) and len(contiguous) == 10,
          str(names[:14]))
    check("命中收拢成一页", browser._page_count() == 1)
    browser.search.setText("不存在xyz")
    browser._rebuild()
    app.processEvents()
    check("无结果显示空提示", browser.empty_label.isVisible())
    browser.clear_search()
    app.processEvents()
    check("清空搜索恢复 42 项", len(browser._matches) == 42, str(len(browser._matches)))

    print()
    print("── 6. Dock：第一个控件 + 主行（分页行已移除）──")
    from dock import DockBar

    dock = DockBar(cfg)
    dock.set_items(items)
    dock.show_bar()
    app.processEvents()

    check("Dock 构造成功", dock.isVisible())
    check("第一个控件是「桌面整理」", hasattr(dock, "desktop_btn"))
    # 需求：菜单栏上方那排分页条目整行删掉，分页浏览全部搬进收纳面板
    check("菜单栏上不再有分页行 UI",
          not hasattr(dock, "strip_panel")
          and not hasattr(dock, "strip_row")
          and not hasattr(dock, "strip_page_label")
          and not hasattr(dock, "btn_toggle_strip"),
          str([a for a in ("strip_panel", "strip_row", "strip_page_label",
                           "btn_toggle_strip") if hasattr(dock, a)]))
    check("菜单栏不再持有分页按钮", not hasattr(dock, "_strip_buttons"))
    check("不再有分页相关方法",
          not hasattr(dock, "rebuild_strip") and not hasattr(dock, "strip_pages")
          and not hasattr(dock, "toggle_strip"))
    check("配置里也没有分页行开关了", "dock_strip_visible" not in config_mod.DEFAULTS)
    check("收纳内容仍保留为「＋ 添加」的候选",
          len(dock._items) == len(items), f"{len(dock._items)} vs {len(items)}")
    check("主行控件齐全：＋ / ⚙ / ✕",
          hasattr(dock, "add_btn") and hasattr(dock, "settings_btn")
          and hasattr(dock, "btn_hide_dock"))
    check("常用启动行还在", dock.desktop_btn.isVisible())

    fired = []
    toggled = []
    dock.open_desktop_files.connect(lambda: fired.append("panel"))
    dock.toggle_desktop_files.connect(lambda: toggled.append("toggle"))
    dock.desktop_btn.activated.emit(dock.desktop_btn)
    # 第一个控件是「上拉菜单」的开关：再点一次要能收起，
    # 所以走 toggle_desktop_files，而不是只能打开的 open_desktop_files。
    check("点第一个控件 → 开关收纳面板（而非只能打开）",
          toggled == ["toggle"] and fired == [],
          f"toggle={toggled} open={fired}")

    check("Dock 贴底显示",
          dock.y() + dock.height() >= dock.screen().availableGeometry().bottom() - 6,
          f"{dock.y() + dock.height()} vs {dock.screen().availableGeometry().bottom()}")

    print()
    print("── 6b. Dock 上的控制按钮 ──")
    check("有「隐藏整条菜单栏」按钮", hasattr(dock, "btn_hide_dock"))
    check("有「设置」按钮", hasattr(dock, "settings_btn"))

    hidden_signals = []
    dock.hide_requested.connect(lambda: hidden_signals.append(True))
    dock.hide_self()
    app.processEvents()
    check("点隐藏按钮后菜单栏消失", not dock.isVisible())
    check("隐藏状态写进配置", cfg.get("dock_visible") is False)
    check("会广播隐藏事件（好让托盘菜单同步）", hidden_signals == [True],
          str(hidden_signals))
    dock.show_bar()
    cfg.set("dock_visible", True)
    app.processEvents()
    check("可以重新显示出来", dock.isVisible())

    print()
    print("── 7. 退出还原：收纳目录 → 桌面 ──")
    result2 = nest.restore_to_desktop(desktop)
    check("还原成功（38 项）", result2.moved == 38, result2.summary())
    after = sorted(p.name for p in desktop.iterdir())
    check("个人桌面恢复到 33 项", len(after) == 33, str(len(after)))
    check("收纳目录已空", not list(store.iterdir()))
    check("文件夹连同内层一起回来",
          (desktop / "资料夹A" / "子目录" / "深层.txt").read_text(encoding="utf-8")
          == "deeper")
    check("快捷方式也回来了", (desktop / "记事本.lnk").is_file())
    check("文件内容完好",
          (desktop / "文件00.txt").read_text(encoding="utf-8") == "内容-0" * 4)
    check("公共桌面的快捷方式回到了公共桌面",
          (public / "腾讯会议.lnk").is_file()
          and not (desktop / "腾讯会议.lnk").exists())
    check("公共桌面恢复了 5 个快捷方式",
          len([p for p in public.iterdir() if p.suffix == ".lnk"]) == 5,
          str(sorted(p.name for p in public.iterdir())))
    check("同名的那份回到了公共桌面",
          (public / "记事本.lnk").is_file() and (desktop / "记事本.lnk").is_file())

    print()
    print("── 8. 整个程序：启动即收纳 / 退出即还原 ──")
    import tray_app

    # 先重新造一批桌面内容
    for index in range(6):
        (desktop / f"再来{index}.txt").write_text("again", encoding="utf-8")
    pending = nest.desktop_item_count(desktop)
    check("程序启动前桌面有内容", pending > 0, str(pending))

    tray = tray_app.TrayApp(cfg, silent=True)
    deadline = time.time() + 25
    while tray._scan is not None and tray._scan.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.03)

    check("启动后桌面被自动收纳", not list(desktop.iterdir()),
          str(sorted(p.name for p in desktop.iterdir())))
    check("面板里能看到内容", len(tray.nest_items) > 0, str(len(tray.nest_items)))
    check("Dock 已同步收纳内容（供「＋ 添加」挑选）",
          len(tray.dock._items) == len(tray.nest_items),
          f"{len(tray.dock._items)} vs {len(tray.nest_items)}")
    check("菜单栏上依然没有分页行",
          not hasattr(tray.dock, "strip_panel"))
    check("收纳面板能拿到同一批内容",
          len(tray.desktop_browser._items) == len(tray.nest_items))

    tray._quitting = True
    tray.restore_desktop_on_exit()
    check("退出后桌面被自动还原", len(list(desktop.iterdir())) > 0,
          str(len(list(desktop.iterdir()))))
    check("退出后收纳目录已空", not list(store.iterdir()))

    print()
    print("── 9. 显示文件后缀名开关 ──")
    from engine import RepoItem, display_name

    check("默认不显示后缀", cfg.get("show_extensions") is False)
    check("显示名默认剥掉后缀", display_name("报告.docx", False, False) == "报告",
          display_name("报告.docx", False, False))
    check("开关打开时保留后缀", display_name("报告.docx", False, True) == "报告.docx")
    check("文件夹不受影响（v1.2 不会被切）",
          display_name("v1.2", True, False) == "v1.2")
    check("本来就无后缀的原样返回", display_name("说明", False, False) == "说明")
    check("点开头的文件不返回空串",
          display_name(".gitignore", False, False) == ".gitignore",
          display_name(".gitignore", False, False))

    # 造几个真实文件：验证"只改显示、绝不动磁盘"
    ext_dir = base / "ext"
    ext_dir.mkdir(exist_ok=True)
    (ext_dir / "报告.docx").write_text("x", encoding="utf-8")
    (ext_dir / "资料夹").mkdir(exist_ok=True)
    sample_items = [
        RepoItem(ext_dir / "报告.docx", "报告.docx", False, "document", 1, 0.0),
        RepoItem(ext_dir / "资料夹", "资料夹", True, "folder", 0, 0.0),
    ]

    browser = tray.desktop_browser
    browser.apply_theme(True)
    browser.set_items(sample_items)
    browser.search.clear()
    browser._rebuild()
    app.processEvents()

    def tile_labels():
        return [t.name_label.text() for t in browser._tiles]

    check("关闭时收纳面板不显示后缀", tile_labels() == ["报告", "资料夹"],
          str(tile_labels()))

    tray.panel.chk_extensions.setChecked(True)      # 从主面板的开关打开
    app.processEvents()
    check("打开时收纳面板显示完整后缀",
          tile_labels() == ["报告.docx", "资料夹"], str(tile_labels()))
    check("开关写进配置（重启能保持）", cfg.get("show_extensions") is True)
    check("设置窗口读到同一个值",
          _settings_flag(cfg) is True, str(_settings_flag(cfg)))

    # 搜索：带后缀 / 不带后缀都要命中
    for query in ("报告", "报告.docx"):
        browser.search.setText(query)
        names = [i.name for i in browser._filtered()]
        check(f"搜「{query}」都能命中 报告.docx", names == ["报告.docx"], str(names))
    browser.search.clear()
    browser._rebuild()

    tray.panel.update_overview(items=sample_items, nest_items=2, desktop_pending=0,
                               folders=1, shortcuts=0, history=[])
    tree = [tray.panel.items_tree.topLevelItem(i).text(0)
            for i in range(tray.panel.items_tree.topLevelItemCount())]
    check("主面板列表也跟着显示后缀", tree == ["报告.docx", "资料夹"], str(tree))

    check("磁盘上的真实文件名没被动过",
          (ext_dir / "报告.docx").is_file() and not (ext_dir / "报告").exists())

    tray.panel.chk_extensions.setChecked(False)
    app.processEvents()
    check("关回去之后配置也关掉", cfg.get("show_extensions") is False)
    check("关回去之后显示也恢复", tile_labels() == ["报告", "资料夹"], str(tile_labels()))
    check("磁盘文件依然完好", (ext_dir / "报告.docx").is_file())

    print()
    print("── 10. 打开 / 翻页收纳面板时 Dock 不会消失 ──")
    tray.cfg.set("dock_hidden_by_user", False)
    tray.cfg.set("dock_visible", True)
    tray.cfg.set("dock_auto_show", True)
    tray.dock.show_bar()
    app.processEvents()

    # 造多页内容，翻页才有意义
    page_dir = base / "page"
    page_dir.mkdir(exist_ok=True)
    page_items = []
    for index in range(42):
        p = page_dir / f"翻页{index:02d}.txt"
        p.write_text("p", encoding="utf-8")
        page_items.append(RepoItem(p, p.name, False, "document", 1, 0.0))
    browser.set_items(page_items)
    browser.set_per_page(14)
    app.processEvents()
    check("面板里有多页可翻", browser._page_count() == 3, str(browser._page_count()))

    check("Dock 初始可见", tray.dock.isVisible())
    check("面板关着时 _dock_in_use 为假", tray._dock_in_use() is False)

    browser.reposition()
    browser.show()
    app.processEvents()
    check("收纳面板已打开", browser.isVisible())
    check("面板打开时 _dock_in_use 为真", tray._dock_in_use() is True)

    # 关键：把自己窗口当成"前台窗口"，绝不能被判成"别的程序在遮挡菜单栏"
    real_hwnd = tray._foreground_hwnd
    try:
        tray._foreground_hwnd = lambda: int(browser.winId())
        check("前台窗口是自己时被识别出来", tray._foreground_is_self() is True)
        check("自己的面板不算「全屏遮挡」",
              tray._foreground_is_fullscreen() is False)
        tray._foreground_hwnd = lambda: int(tray.dock.winId())
        check("Dock 自己也不算「全屏遮挡」",
              tray._foreground_is_fullscreen() is False)
    finally:
        tray._foreground_hwnd = real_hwnd

    # 反复翻页 / 换每页数量 / 触发自动显隐检查，菜单栏必须一直在
    survived = True
    for _round in range(3):
        for page in range(browser._page_count()):
            browser.goto_page(page)
            tray._auto_show_tick()
            app.processEvents()
            if not tray.dock.isVisible():
                survived = False
        browser.set_per_page(21)
        app.processEvents()
        browser.set_per_page(14)
        app.processEvents()
        if not tray.dock.isVisible():
            survived = False
    check("反复翻页切换后 Dock 依然稳定可见", survived and tray.dock.isVisible())
    check("翻页没有篡改菜单栏「显示/隐藏」状态变量",
          bool(tray.cfg.get("dock_visible", True)) is True
          and bool(tray.cfg.get("dock_hidden_by_user", False)) is False,
          f"visible={tray.cfg.get('dock_visible')} "
          f"by_user={tray.cfg.get('dock_hidden_by_user')}")

    # 用户手动点 ✕ 隐藏：必须保持隐藏，自动逻辑不许把它弹回来
    tray.dock.hide_self()
    app.processEvents()
    for _ in range(3):
        tray._auto_show_tick()
        app.processEvents()
    check("用户手动隐藏后保持隐藏（不自动恢复）", not tray.dock.isVisible())
    check("手动隐藏标记被记住",
          bool(tray.cfg.get("dock_hidden_by_user", False)) is True)
    tray.cfg.set("dock_hidden_by_user", False)
    tray.cfg.set("dock_visible", True)
    tray.dock.show_bar()
    app.processEvents()
    check("清掉手动标记后可以再显示", tray.dock.isVisible())

    browser.hide()
    app.processEvents()

    if shots:
        out = HERE / "shots"
        out.mkdir(exist_ok=True)
        tray.auto_take_desktop()
        for _ in range(40):
            app.processEvents()
            time.sleep(0.03)
        tray.dock.show_bar()
        app.processEvents()
        time.sleep(0.3)
        # 注意：离屏平台截不到 DWM 的磨砂（模糊发生在合成阶段），
        # 所以这两个文件名带 offscreen 前缀，**不要**覆盖 README 用的
        # shots/dock.png 和 shots/popup-glass.png——那两张得用
        # dev/shot_panel.py 在真机上重拍。
        tray.dock.grab().save(str(out / "offscreen-dock.png"))
        tray.desktop_browser.resize(920, 620)
        tray.desktop_browser.show_window()
        for _ in range(60):
            app.processEvents()
            time.sleep(0.03)
        tray.desktop_browser.grab().save(str(out / "offscreen-panel.png"))
        print(f"  截图已保存到 {out}（离屏渲染，无磨砂模糊）")

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)

    tray._quitting = True
    tray.shutdown()
    app.processEvents()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
