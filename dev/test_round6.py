#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本轮三条需求的回归测试
======================

需求 1：**收纳面板右下角的「加为常用」控件无法正常使用**
        根因不是"没连上"，而是连上之后**崩了**：
        `QPushButton.clicked` 的签名是 `clicked(bool checked = False)`，
        它会把这个 bool **真的**传进槽函数。`add_selected_to_apps(self,
        item=None)` 带默认参数，PyQt 就认为"它还能再收一个"，
        于是把 `False` 当成 `item` 塞进去 → `False.path` → AttributeError。
        而 PyQt6 里**槽函数里逃出去的异常会直接 abort 整个进程**：
        没有报错、没有弹窗，用户看到的就是"点了完全没反应"。
        （`btn_restore` → `restore_selected(self, item=None)` 一模一样的病。）

需求 2：**不该写死「加为常用」，要按选中项判断**
        选中的不是常用 → 写「加为常用」；已经是常用 → 写「移出常用」，
        点下去执行对应的加 / 移。

需求 3：**右键收纳面板里的应用要有「删除」功能，删到回收站**
        新增 `recycle.py`，走 Shell 的 `SHFileOperationW + FOF_ALLOWUNDO`
        （和资源管理器按 Delete 是同一条路径），不是永久删除。

用法：python dev/test_round6.py
"""
from __future__ import annotations

import ast
import ctypes
import os
import shutil
import struct
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
_fh.dump_traceback_later(240, exit=True)

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  {'✓' if condition else '✗'} {label}"
          + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print()
    print(f"── {title} ──")


# --------------------------------------------------------------------------
# 回收站取证：直接看 C:\$Recycle.Bin\<用户SID>\ 里有没有多出 $I / $R 配对
# --------------------------------------------------------------------------
# 为什么不用 `SHQueryRecycleBinW` 的条目数/体积差值：实测这台机器上它会
# 被**无关操作**带偏（`config.data_dir()` 每进程一次的 `.write-test`
# 写探针 unlink 之后，计数会莫名其妙地 +1/+2 字节）。拿它当断言会假失败。
# 直接看回收站目录最实在：$I 是元数据（含原始路径），$R 是真身。
def bin_items() -> "set[tuple[str, int]]":
    """回收站里所有 $R*（真身）的 (文件名, 大小)。读不了的目录跳过。"""
    out = set()
    root = Path("C:/$Recycle.Bin")
    try:
        folders = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue          # SYSTEM(S-1-5-18) 那个目录没权限，正常
        for entry in entries:
            if not entry.name.startswith("$R"):
                continue
            try:
                out.add((entry.name, entry.stat().st_size))
            except OSError:
                pass
    return out


def bin_meta_files() -> "dict[str, Path]":
    """回收站里所有 $I 元数据文件：`{文件名: 路径}`。

    ⚠️ 为什么按**文件名**而不是按"原始路径"来比对新增：
    `$I` 的随机名每次删除都是新的，而"原始路径"会重复——同一个测试
    跑第二遍时，`%TEMP%\\nest-round6\\...\\随便一个文档.txt` 这个路径
    在回收站里**早就有**一条了，按路径做集合差永远是空的（踩过）。
    """
    out: "dict[str, Path]" = {}
    try:
        folders = [p for p in Path("C:/$Recycle.Bin").iterdir() if p.is_dir()]
    except OSError:
        return out
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue          # SYSTEM(S-1-5-18) 那个目录没权限，正常
        for entry in entries:
            if entry.name.startswith("$I"):
                out[entry.name] = entry
    return out


def read_meta(meta: Path):
    """解析一个 $I 文件，返回 `(原始大小, 原始路径)`；读不了返回 None。

    $I 的格式（Vista 之后都是版本 2）：
        0   int64  版本号
        8   int64  原始大小
        16  int64  删除时间
        24  int32  路径字符数
        28  UTF-16LE 原始路径
    """
    try:
        data = meta.read_bytes()
    except OSError:
        return None
    if len(data) < 28:
        return None
    version, size, _when = struct.unpack_from("<qqq", data, 0)
    if version != 2:
        return None
    (chars,) = struct.unpack_from("<i", data, 24)
    try:
        path = data[28:28 + chars * 2].decode("utf-16-le").rstrip("\x00")
    except UnicodeDecodeError:
        return None
    return int(size), path


def main() -> int:
    base = Path(tempfile.gettempdir()) / "nest-round6"
    shutil.rmtree(base, ignore_errors=True)
    desktop, cfg_dir = base / "Desktop", base / "cfg"
    public = base / "PublicDesktop"
    for folder in (desktop, cfg_dir, public):
        folder.mkdir(parents=True)

    from qt_compat import QApplication

    app = QApplication([])
    import config as config_mod
    import nest
    import winlink

    # 先烧掉 `config.data_dir()` 那次写探针（它会在回收站里留一条 2 字节记录，
    # 见上面 `bin_items()` 的说明），免得干扰后面按大小比对的断言。
    config_mod.log("round6 warmup")

    nest.nest_root = lambda: base / ".nest"
    nest.forget_nest_root()
    config_mod.get_desktop_dir = lambda: desktop
    config_mod.get_public_desktop_dir = lambda: public

    cfg = config_mod.Config(cfg_dir)
    cfg.update({"desktop": str(desktop)})

    def pump(seconds: float = 0.6) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    store = nest.desktop_store()
    store.mkdir(parents=True, exist_ok=True)
    winlink.create_shortcut(store / "记事本.lnk", r"C:\Windows\System32\notepad.exe")
    winlink.create_shortcut(store / "计算器.lnk", r"C:\Windows\System32\calc.exe")
    # 4096 字节：这个大小够特别，回收站里出现"同尺寸的新条目"就是它
    VICTIM_SIZE = 4096
    (store / "随便一个文档.txt").write_bytes(b"h" * VICTIM_SIZE)
    (store / "一个文件夹").mkdir()

    import desktop_browser
    import recycle
    from PyQt6.QtWidgets import QMessageBox as RealMessageBox

    # ------------------------------------------------------------------
    # 用一个"不弹窗"的 QMessageBox 顶掉真的，否则 offscreen 下模态框会把
    # 测试挂死（这也正是这个用例要跑的代码路径）。
    # ------------------------------------------------------------------
    class FakeBox:
        StandardButton = RealMessageBox.StandardButton
        answer = RealMessageBox.StandardButton.Yes
        calls: "list[tuple[str, str]]" = []

        @classmethod
        def question(cls, *args, **kwargs):
            cls.calls.append(("question", args[1] if len(args) > 1 else ""))
            return cls.answer

        @classmethod
        def information(cls, *args, **kwargs):
            cls.calls.append(("information", args[1] if len(args) > 1 else ""))

        @classmethod
        def warning(cls, *args, **kwargs):
            cls.calls.append(("warning", args[1] if len(args) > 1 else ""))

    desktop_browser.QMessageBox = FakeBox

    # ------------------------------------------------------------------
    # 右键菜单"点哪个"的替身：把菜单里的动作文本记下来，
    # 再按规则挑一个返回（这样能验证菜单里真的有"删除"这一项）。
    # ------------------------------------------------------------------
    class MenuSpy:
        def __init__(self):
            self.texts: "list[str]" = []
            self.pick = None

        def __call__(self, menu, pos):
            self.texts = [a.text() for a in menu.actions()]
            return self.pick(menu) if self.pick else None

    spy = MenuSpy()
    desktop_browser.popup_menu = spy

    # ------------------------------------------------------------------
    # 记录"真正交给 Shell 的那个结构体"：把生产代码里的
    # `_SHFILEOPSTRUCTW` 换成会自报家门的子类，就能读到 fFlags / wFunc。
    # 这是"到底有没有 FOF_ALLOWUNDO"最直接的证据。
    # ------------------------------------------------------------------
    built: "list" = []

    class RecordingStruct(recycle._SHFILEOPSTRUCTW):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(self)

    recycle._SHFILEOPSTRUCTW = RecordingStruct

    browser = desktop_browser.DesktopBrowser(cfg)
    browser.set_items(nest.list_nest_items())
    pump(0.3)

    def item_named(name: str):
        return next((i for i in browser._items if i.name == name), None)

    # ==================================================================
    section("A. 「加为常用」按钮：先证明它以前是真崩，再证明现在不崩")
    check("面板里有测试条目", len(browser._items) >= 4, str(len(browser._items)))

    # 老 bug 的复现式：clicked(bool) 会把 False 当 item 塞进槽函数
    crashed = ""
    try:
        browser.add_item_to_apps(False)          # 这就是老代码实际发生的事
    except Exception as exc:
        crashed = f"{type(exc).__name__}: {exc}"
    check("老写法确实会炸（说明这个坑真实存在）",
          "bool" in crashed and "path" in crashed, crashed)

    crashed2 = ""
    try:
        browser.restore_selected(False)
    except Exception as exc:
        crashed2 = f"{type(exc).__name__}: {exc}"
    check("「还原到桌面」也是一模一样的病",
          "bool" in crashed2 and "name" in crashed2, crashed2)

    # 现在真的去点按钮——以前这一下会让整个进程 abort
    check("没选中任何条目时，按钮是灰的", not browser.btn_add.isEnabled())
    browser.btn_add.click()
    pump(0.2)
    check("点灰按钮不会崩（以前这一下进程就没了）", True)

    doc = item_named("随便一个文档.txt")
    check("找得到那个文档条目", doc is not None)
    browser.select_item(doc)
    pump(0.2)
    check("选中之后按钮可用了", browser.btn_add.isEnabled())

    # ==================================================================
    section("B. 按钮文案随选中项切换（不写死「加为常用」）")
    check("未加过常用 → 文案是「加为常用」",
          browser.btn_add.text() == "加为常用", browser.btn_add.text())

    before = len(cfg.quick_items)
    browser.btn_add.click()                       # ← 以前这一下直接 abort
    pump(0.5)
    check("点一下真的加进去了", len(cfg.quick_items) == before + 1,
          f"{before} -> {len(cfg.quick_items)}")
    check("加完文案变成「移出常用」",
          browser.btn_add.text() == "移出常用", browser.btn_add.text())
    check("这一项确实在常用里了", cfg.is_quick(doc.path))

    browser.btn_add.click()
    pump(0.5)
    check("再点一下又移出去了", len(cfg.quick_items) == before,
          f"{len(cfg.quick_items)}")
    check("移出后文案变回「加为常用」",
          browser.btn_add.text() == "加为常用", browser.btn_add.text())

    # 选中一个"本来就是常用"的条目，文案应该直接是"移出常用"
    cfg.add_quick(store / "记事本.lnk", "记事本")
    browser.refresh_from_disk()
    pump(0.3)
    browser.select_item(item_named("记事本.lnk"))
    pump(0.2)
    check("选中已经是常用的条目 → 直接写「移出常用」",
          browser.btn_add.text() == "移出常用", browser.btn_add.text())
    check("tooltip 也说明白了「不动文件」",
          "不动文件" in browser.btn_add.toolTip(), browser.btn_add.toolTip())

    # ==================================================================
    section("C. 选中态要留得住（不然按钮永远来不及点）")
    doc = item_named("随便一个文档.txt")      # 上面刷新过，重新认领一次对象
    browser.select_item(doc)
    pump(0.2)
    check("刚选中时是高亮的", doc is browser._selected)
    # 老逻辑：单击后 1.2 秒自动 clear_selection → 按钮灰掉 → "点了没反应"
    pump(1.7)
    check("等了 1.7 秒（远超老的 1.2 秒）之后仍然是选中状态",
          browser._selected is not None
          and str(browser._selected.path) == str(doc.path),
          f"_selected={getattr(browser._selected, 'name', None)}")
    check("按钮也还是可用的", browser.btn_add.isEnabled())

    section("C2. 但「打开」之后高亮要自己消失")
    import engine as engine_mod

    real_launch = engine_mod.launch
    engine_mod.launch = lambda *a, **k: (True, "")   # 别真的去开记事本
    try:
        browser._open(doc)
    finally:
        engine_mod.launch = real_launch
    pump(1.7)
    check("打开之后选中态被清掉了", browser._selected is None,
          f"_selected={getattr(browser._selected, 'name', None)}")

    # ==================================================================
    section("D. 右键菜单里有「删除（移到回收站）」")
    doc = item_named("随便一个文档.txt")
    check("文档还在", doc is not None and doc.path.exists())

    spy.texts = []
    spy.pick = None                   # 只看看菜单里有什么，不真点
    browser._show_tile_menu(doc, None)
    pump(0.1)
    check("卡片右键菜单里有「删除（移到回收站）」",
          any("删除" in t and "回收站" in t for t in spy.texts),
          str(spy.texts))
    check("「删除」排在最后一行（别让手一滑就点到）",
          bool(spy.texts) and "删除" in spy.texts[-1], str(spy.texts))
    check("菜单里仍然有「还原到桌面」等老动作",
          "还原到桌面" in spy.texts and "复制完整路径" in spy.texts,
          str(spy.texts))

    # 菜单里选「否」→ 什么也不该发生
    FakeBox.answer = RealMessageBox.StandardButton.No
    spy.pick = lambda m: next(a for a in m.actions() if "删除" in a.text())
    browser._show_tile_menu(doc, None)
    pump(0.2)
    check("确认框选「否」→ 文件原地不动", doc.path.exists())
    check("选「否」时根本没去调 Shell",
          not any(int(s.fFlags) & recycle._FOF_ALLOWUNDO for s in built))

    # ==================================================================
    section("E. 真的删到回收站（三层证据）")
    check("回收站接口可用", recycle.available(), recycle.load_error())
    check("victim 的大小就是那个特殊值",
          doc.path.stat().st_size == VICTIM_SIZE,
          f"{doc.path.stat().st_size}")

    bin_before = bin_items()
    meta_before = set(bin_meta_files())
    built.clear()

    FakeBox.answer = RealMessageBox.StandardButton.Yes
    removed_path = doc.path
    browser._show_tile_menu(doc, None)
    pump(0.6)

    # --- 证据 1：交给 Shell 的标志位 ---
    check("确实调了 Shell 的删除接口", len(built) == 1, f"{len(built)} 次")
    if built:
        call = built[-1]
        check("wFunc 是 FO_DELETE",
              int(call.wFunc) == recycle._FO_DELETE, str(int(call.wFunc)))
        check("★ 带了 FOF_ALLOWUNDO（这就是「删到回收站」而不是真删）",
              bool(int(call.fFlags) & recycle._FOF_ALLOWUNDO),
              f"flags=0x{int(call.fFlags):X}")
        check("同时带了 FOF_NOCONFIRMATION（我们自己在界面里问过了）",
              bool(int(call.fFlags) & recycle._FOF_NOCONFIRMATION),
              f"flags=0x{int(call.fFlags):X}")
        check("pFrom 是那个文件的绝对路径",
              os.path.normcase(call.pFrom) == os.path.normcase(str(removed_path)),
              f"{call.pFrom!r} vs {removed_path!r}")

    # --- 证据 2 + 3：回收站目录里真的多了一条同尺寸记录，且原始路径对得上 ---
    # ⚠️ Shell 写 $I（元数据）/ $R（真身）有大约 0.3 秒的延迟，两者也不一定
    #    同时出现，所以要一起轮询。
    new_items = set()
    new_metas = set()
    new_paths = set()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        new_items = bin_items() - bin_before
        new_metas = set(bin_meta_files()) - meta_before
        new_paths = set()
        for name in new_metas:
            info = read_meta(bin_meta_files()[name])
            if info is not None:
                new_paths.add((info[0], os.path.normcase(info[1])))
        size_ok = any(size == VICTIM_SIZE for _name, size in new_items)
        path_ok = (VICTIM_SIZE, os.path.normcase(str(removed_path))) in new_paths
        if size_ok and path_ok:
            break
        pump(0.15)

    check("★ 回收站目录里多了一个同尺寸的条目（4096 字节）",
          any(size == VICTIM_SIZE for _name, size in new_items),
          str(sorted(new_items)))
    check("★ 回收站记的原始路径就是被删的那个文件",
          (VICTIM_SIZE, os.path.normcase(str(removed_path))) in new_paths,
          str(sorted(new_paths)[:4]))

    # --- 界面 ---
    check("文件从原位置消失了", not removed_path.exists())
    check("面板里那一条也没了", item_named("随便一个文档.txt") is None)
    check("提示语说明了可以还原",
          "回收站" in browser.hint.text(), browser.hint.text())

    # ==================================================================
    section("F. 删掉的如果是常用软件，要顺手从常用启动里摘掉")
    calc = item_named("计算器.lnk")
    check("计算器条目在", calc is not None)
    cfg.add_quick(calc.path, "计算器")
    browser.refresh_from_disk()
    pump(0.3)
    calc = item_named("计算器.lnk")
    check("已经把它加为常用了", cfg.is_quick(calc.path))
    check("常用那一排里有它",
          any(str(b.path) == str(calc.path) for b in browser._app_buttons))

    spy.pick = lambda m: next(a for a in m.actions() if "删除" in a.text())
    browser._show_tile_menu(calc, None)
    pump(0.6)
    check("文件没了", not calc.path.exists())
    check("常用启动里也摘干净了（不留死链）", not cfg.is_quick(calc.path),
          str([e["name"] for e in cfg.quick_items]))
    check("常用那一排里也没了",
          not any(str(b.path) == str(calc.path) for b in browser._app_buttons))

    # ==================================================================
    section("G. guard：该拦的必须拦住")
    scratch = base / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "desktop.ini").write_text("x", encoding="utf-8")
    (scratch / "回收站").write_text("x", encoding="utf-8")

    check("拦盘符根目录",
          not recycle.guard(Path("C:\\"))[0], str(recycle.guard(Path("C:\\"))))
    check("拦收纳目录本体",
          not recycle.guard(nest.nest_root())[0],
          str(recycle.guard(nest.nest_root())))
    check("拦不存在的路径",
          not recycle.guard(store / "压根没有这个文件.txt")[0])
    check("拦系统文件（desktop.ini）",
          not recycle.guard(scratch / "desktop.ini")[0],
          str(recycle.guard(scratch / "desktop.ini")))
    check("拦系统图标名（回收站）",
          not recycle.guard(scratch / "回收站")[0],
          str(recycle.guard(scratch / "回收站")))
    # 收纳目录**里面**的条目是允许删的（它只是收纳目录的子项，不是本体）
    victim = store / "临时受害者.txt"
    victim.write_text("x", encoding="utf-8")
    allowed, why = recycle.guard(victim)
    check("收纳目录里的普通文件可以删", allowed, why)
    check("确实删掉了", recycle.recycle(victim)[0] and not victim.exists())

    # ==================================================================
    section("H. 铁律：这条删除路径必须是「只进回收站」，不能有永久删除")
    src = (HERE / "recycle.py").read_text(encoding="utf-8")
    check("用了 FOF_ALLOWUNDO（Shell 的「删到回收站」标志）",
          "FOF_ALLOWUNDO" in src)

    # 用 AST 看**真正被调用的**函数，而不是 grep 文本——
    # 否则文档字符串里那句"为什么不用 os.remove()"会被误判成违规。
    banned = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("remove", "unlink", "rmtree", "rmdir",
                                  "removedirs"):
                banned.append(node.func.attr)
    check("recycle.py 的代码里没有任何永久删除调用（只看 AST，不看注释）",
          not banned, str(sorted(set(banned))))

    check("recycle() 自己会再过一遍 guard()",
          "guard(path)" in src and "def recycle" in src)

    ui_src = (HERE / "desktop_browser.py").read_text(encoding="utf-8")
    check("btn_add 用 lambda 把 clicked 的 bool 吃掉了",
          "self.btn_add.clicked.connect(lambda" in ui_src)
    check("btn_restore 同样处理了",
          "self.btn_restore.clicked.connect(lambda" in ui_src)
    check("删除走的是 recycle.recycle（不是 os.remove）",
          "recycle.recycle(" in ui_src and "os.remove(" not in ui_src)

    # ==================================================================
    browser.hide()
    pump(0.2)
    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for item in FAIL:
        print("  ·", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
