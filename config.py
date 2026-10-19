#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 配置持久化
==============================
所有用户设置都存在一个本地 JSON 文件里，不联网、不写注册表（除了可选的开机自启）。

配置项
------
desktop         被收纳的桌面路径（默认取系统桌面，兼容 OneDrive 重定向）
view_mode       list / grid，弹出窗口的默认视图
window_geometry 弹出窗口的位置和大小，记住上次拖动结果
quick_items     托盘"常用启动"列表（持久化，重启不丢）
autostart       是否开机自启
last_migrate    最近一次收纳的时间戳，用于首次启动提示"是否还原"
show_extensions 界面是否显示文件后缀名（默认关闭；只改显示，不动磁盘文件）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import winlink

APP_NAME = "桌面收纳"
APP_NAME_FULL = "桌面收纳美化工具"
VERSION = "1.0.0"
ORG_NAME = "DesktopNest"



# --------------------------------------------------------------------------
# 路径工具
# --------------------------------------------------------------------------
def _shell_folder(csidl: int, fallback: Path) -> Path:
    """按 CSIDL 取 shell 文件夹路径（能正确处理重定向）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
                if buf.value:
                    return Path(buf.value)
        except Exception:
            pass
    return fallback


def get_desktop_dir() -> Path:
    """取当前用户的桌面路径（优先 shell API，能正确处理 OneDrive 重定向）。"""
    # CSIDL_DESKTOPDIRECTORY = 0x0010
    return _shell_folder(0x0010, Path.home() / "Desktop")


def get_public_desktop_dir() -> Path:
    """取**公共桌面**路径：`C:\\Users\\Public\\Desktop`。

    放在这里的快捷方式会显示在**所有用户**的桌面上，所以想让桌面真正干净，
    必须连它一起收。用 shell API 取而不是硬拼字符串，兼容系统盘不在 C: 的情况。
    """
    # CSIDL_COMMON_DESKTOPDIRECTORY = 0x0019
    return _shell_folder(0x0019, Path(r"C:\Users\Public\Desktop"))


def desktop_dirs(include_public: bool = True) -> "list[tuple[Path, str]]":
    """要收纳的桌面列表：[(路径, 来源标记)]。

    来源标记会跟着条目走，还原时才知道该送回个人桌面还是公共桌面。
    """
    out = [(get_desktop_dir(), "")]
    if include_public:
        public = get_public_desktop_dir()
        try:
            if public.exists() and public.resolve() != get_desktop_dir().resolve():
                out.append((public, "public"))
        except OSError:
            pass
    return out


def default_project_dir() -> Path:
    """程序目录。

    **打包成 exe 后必须用 exe 自己所在的目录**，不能用 `__file__`。

    原因：PyInstaller 的 onefile 会把整个包解到 `%TEMP%\\_MEIxxxx` 再运行，
    那里面的 `__file__` 指向临时目录，**进程一退出就被删掉**。
    拿它当"程序目录"的后果是：配置 / 缓存每次启动都从零开始 ——
    表现就是"上次设的都忘了""图标每次都要重取一遍"，
    而且会在 TEMP 里堆一堆没人清理的 `_MEI` 目录。
    """
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            pass
    return Path(__file__).resolve().parent


def _data_candidates() -> "list[Path]":
    """配置文件的候选目录：优先 LOCALAPPDATA，不可写就退到程序目录。"""
    out: "list[Path]" = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local) / ORG_NAME)
    try:
        out.append(Path.home() / f".{ORG_NAME.lower()}")
    except RuntimeError:
        pass
    out.append(default_project_dir() / ".data")
    return out


_DATA_DIR: "Path | None" = None


def data_dir() -> Path:
    """返回一个确实可写的配置目录（结果缓存）。"""
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    for folder in _data_candidates():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            _DATA_DIR = folder
            return folder
        except OSError:
            continue
    fallback = Path(tempfile.gettempdir()) / ORG_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    _DATA_DIR = fallback
    return fallback


def config_path() -> Path:
    return data_dir() / "config.json"


def log_path() -> Path:
    return data_dir() / "app.log"


def log(message: str) -> None:
    """极简日志：出错时留个痕，方便排查。"""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path().open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# 配置对象
# --------------------------------------------------------------------------
DEFAULTS: "dict[str, Any]" = {
    "desktop": "",
    "view_mode": "grid",
    "window_geometry": "",
    "quick_items": [],
    "autostart": False,
    "last_migrate": 0.0,
    "migrate_count": 0,
    "show_confirm": True,
    # 启动时主面板的行为：first（仅第一次运行显示）/ always / never
    # 需求要求"主窗口默认隐藏，仅驻留托盘"，所以这里把选择权留给用户，
    # 首次运行为了让人知道程序在哪，默认显示一次。
    "panel_on_start": "first",
    "first_run_done": False,
    # ---- 收纳行为（核心）----
    "auto_take_on_start": True,      # 启动时自动把桌面收进收纳目录
    "restore_on_exit": True,         # 退出时自动把东西放回桌面
    "hide_desktop_icons": True,      # 收纳后隐藏桌面图标，做到"完全空白"
    "nest_active": False,            # 当前是否处于"桌面已被收纳"状态
    # ---- 界面显示 ----
    # 是否显示文件后缀名。默认**不**显示（`报告.docx` 显示成 `报告`）。
    # 只影响界面上的文字，磁盘上的真实文件名永远不变。
    "show_extensions": False,
    # ---- 收纳面板 / 底部菜单栏 ----
    "page_size": 28,                 # 面板每页显示数量
    "panel_geometry": "",
    "dock_visible": True,
    "dock_auto_show": True,          # 回到桌面时自动把菜单栏显示出来
    "dock_hidden_by_user": False,    # 用户主动点过隐藏（此时不自动弹）
    "dock_avoid_fullscreen": True,   # 全屏看视频/演示时自动让开，不遮挡
    # 别的窗口（哪怕不是全屏）压在菜单栏那块区域上时，也让开。
    # 关掉它就回到"只有全屏才让开"的老行为。
    "dock_avoid_overlap": True,
    "dock_x": None,
    "dock_icon_size": 44,
    "dock_always_on_top": True,
    "dock_opacity": 0.97,
    "desktop_version": VERSION,
}


class Config:
    """读写 config.json，属性式访问。"""

    def __init__(self, base_dir: "Path | None" = None):
        # base_dir 只有测试会用（把配置指向沙盒），正常启动不传
        self.path = (Path(base_dir) / "config.json") if base_dir else config_path()
        self.data: "dict[str, Any]" = dict(DEFAULTS)
        self.load()

    # ---- 读写 ---------------------------------------------------------
    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
        except (OSError, json.JSONDecodeError) as exc:
            log(f"读取配置失败：{exc}")

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)          # 原子替换，避免写一半断电
            return True
        except OSError as exc:
            log(f"写入配置失败：{exc}")
            return False

    # ---- 属性访问 -----------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self.save()

    def update(self, values: "dict[str, Any]", *, save: bool = True) -> None:
        self.data.update(values)
        if save:
            self.save()

    # ---- 具体配置 -----------------------------------------------------
    @property
    def desktop(self) -> Path:
        raw = str(self.get("desktop") or "").strip()
        return Path(raw) if raw else get_desktop_dir()

    @desktop.setter
    def desktop(self, value: "Path | str") -> None:
        self.set("desktop", str(value))

    # ---- 常用启动列表 -------------------------------------------------
    @property
    def quick_items(self) -> "list[dict]":
        items = self.get("quick_items")
        if not isinstance(items, list):
            return []
        clean = []
        for item in items:
            if isinstance(item, dict) and item.get("path"):
                clean.append({"path": str(item["path"]),
                              "name": str(item.get("name") or Path(item["path"]).name)})
            elif isinstance(item, str):
                clean.append({"path": item, "name": Path(item).name})
        return clean

    def is_quick(self, path: "Path | str") -> bool:
        target = os.path.normcase(str(path))
        return any(os.path.normcase(i["path"]) == target for i in self.quick_items)

    def add_quick(self, path: "Path | str", name: "str | None" = None) -> bool:
        """加入托盘常用启动；已存在返回 False。"""
        path = Path(path)
        if self.is_quick(path):
            return False
        items = self.quick_items
        items.append({"path": str(path), "name": name or path.stem or path.name})
        self.set("quick_items", items)
        return True

    def remove_quick(self, path: "Path | str") -> bool:
        target = os.path.normcase(str(path))
        items = [i for i in self.quick_items if os.path.normcase(i["path"]) != target]
        if len(items) == len(self.quick_items):
            return False
        self.set("quick_items", items)
        return True

    def add_quick_many(self, entries: "list[tuple[Path | str, str | None]]") -> int:
        """批量加入常用启动，返回**实际新增**的数量。

        已存在的会被跳过（不报错、不重复）。一次性写盘，避免逐条 `set()`
        造成"配置写了一半"的中间状态——之前批量操作时 UI 读到的是中间态，
        表现就是"加了新的、旧的却没了"。
        """
        items = self.quick_items
        known = {os.path.normcase(i["path"]) for i in items}
        added = 0
        for path, name in entries:
            key = os.path.normcase(str(path))
            if key in known:
                continue
            known.add(key)
            p = Path(path)
            items.append({"path": str(p), "name": name or p.stem or p.name})
            added += 1
        if added:
            self.set("quick_items", items)
        return added

    def remove_quick_many(self, paths: "list[Path | str]") -> int:
        """批量移除常用启动，返回实际移除的数量（同样只写一次盘）。"""
        targets = {os.path.normcase(str(p)) for p in paths}
        if not targets:
            return 0
        before = self.quick_items
        items = [i for i in before if os.path.normcase(i["path"]) not in targets]
        removed = len(before) - len(items)
        if removed:
            self.set("quick_items", items)
        return removed

    def move_quick(self, index: int, delta: int) -> bool:
        items = self.quick_items
        new_index = index + delta
        if not (0 <= index < len(items) and 0 <= new_index < len(items)):
            return False
        items[index], items[new_index] = items[new_index], items[index]
        self.set("quick_items", items)
        return True

    def move_to(self, from_index: int, to_index: int) -> bool:
        """把第 `from_index` 项挪到 `to_index` 这个位置（拖动排序用）。

        跟 `move_quick(index, ±1)` 的区别：那个是"和邻居交换"，只能左移/右移一格；
        拖动排序要的是"从任意位置落到任意位置"，所以这里用 pop + insert。

        下标按**最终列表**理解：`move_to(0, 2)` 在 `[A,B,C,D]` 上得到
        `[B,C,A,D]`（A 落在 C 原来的位置上，B、C 依次前移）。
        越界的 `to_index` 会被夹到合法范围，不抛异常。
        """
        items = self.quick_items
        count = len(items)
        if not (0 <= from_index < count):
            return False
        target = max(0, min(int(to_index), count - 1))
        if target == from_index:
            return False
        items.insert(target, items.pop(from_index))
        self.set("quick_items", items)
        return True


# --------------------------------------------------------------------------
# 开机自启（HKCU Run 键，用户级，不需要管理员）
# --------------------------------------------------------------------------
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "DesktopNest"
_STARTUP_LINK = "桌面收纳.lnk"


def _pythonw() -> str:
    """优先用 pythonw.exe，开机自启时不会闪出黑窗口。"""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def autostart_target(entry_script: "Path | None" = None) -> "tuple[str, str]":
    """开机自启要执行什么 —— 返回 `(可执行文件, 附加参数)`。

    **打包成 exe 之后不能再写"解释器 + main.py"**：发行版目录里根本没有
    `main.py`，也没有 `python.exe`，那样写出来的自启项一点就报错
    （用户看到的是"开机自启打开了，但开机后什么也没发生"）。

    冻结时正确写法就是 **exe 自己 + `--silent`**：
        "C:\\...\\DesktopNest.exe" --silent
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable)), ""
    script = entry_script or (default_project_dir() / "main.py")
    return _pythonw(), f'"{script}" '


def autostart_command(entry_script: "Path | None" = None) -> str:
    exe, prefix = autostart_target(entry_script)
    return f'"{exe}" {prefix}--silent'


def startup_folder() -> Path:
    """「开始菜单 → 启动」文件夹。"""
    return (Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")


def _startup_shortcut() -> Path:
    return startup_folder() / _STARTUP_LINK


def _write_startup_shortcut(entry_script: "Path | None" = None) -> bool:
    """备用方案：把快捷方式放进「启动」文件夹。

    有些环境不允许写 HKCU\\...\\Run（被安全软件或权限策略拦住），
    但「启动」文件夹一定能用，效果一样。

    快捷方式的写法统一走 `winlink.create_shortcut`——COM 虚表下标只有那一处
    定义，避免两处各抄一份、日后改下标时悄悄不同步。
    """
    exe, prefix = autostart_target(entry_script)
    link = _startup_shortcut()
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        ok, reason = winlink.create_shortcut(
            link,
            exe,
            arguments=f"{prefix}--silent".strip(),
            icon_path=exe,
            working_dir=str(Path(exe).parent),
        )
        if not ok:
            log(f"写启动文件夹快捷方式失败：{reason}")
        return bool(ok and link.exists())
    except Exception as exc:
        log(f"写启动文件夹快捷方式失败：{exc}")
        return False


def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            if value:
                return True
    except OSError:
        pass
    try:
        return _startup_shortcut().exists()
    except OSError:
        return False


def set_autostart(enabled: bool, entry_script: "Path | None" = None) -> bool:
    """写入 / 删除开机自启。注册表优先，失败则用「启动」文件夹。"""
    if sys.platform != "win32":
        return False
    # 具体启动什么交给 autostart_target() 判断（冻结版是 exe 自己，
    # 脚本版才是 "pythonw.exe main.py"）。这里只透传调用方的覆盖值。
    script = entry_script

    registry_ok = False
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ,
                                  autostart_command(script))
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except FileNotFoundError:
                    pass
        registry_ok = True
    except OSError as exc:
        log(f"写注册表自启项失败（将改用启动文件夹）：{exc}")

    if not registry_ok:
        if enabled:
            return _write_startup_shortcut(script)
        try:
            link = _startup_shortcut()
            if link.exists():
                link.unlink()
            return True
        except OSError as exc:
            log(f"删除启动文件夹快捷方式失败：{exc}")
            return False
    return True


def autostart_status() -> "bool | None":
    """注册表里的真实状态；无法判断返回 None。"""
    if sys.platform != "win32":
        return None
    return is_autostart_enabled()


# --------------------------------------------------------------------------
# 文件夹选择：优先现代对话框，失败再退回 tkinter，最后退回输入框
# --------------------------------------------------------------------------
def pick_folder(title: str = "选择文件夹", start: "Path | None" = None) -> "Path | None":
    start = start or Path.home()
    # 1) Windows 现代选择框（IFileDialog，COM）
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

            def __init__(self, text: str):
                super().__init__()
                ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(self))

        class IFileDialog(ctypes.Structure):
            pass

        # 用 IFileOpenDialog 取文件夹（FOS_PICKFOLDERS = 0x20）
        ctypes.windll.ole32.CoInitialize(None)
        clsid = GUID("{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}")   # FileOpenDialog
        iid = GUID("{42f85136-db7e-439c-85f1-e4075d135fc8}")     # IFileDialog
        ptr = ctypes.c_void_p()
        if ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr)) != 0:
            raise OSError("CoCreateInstance failed")

        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

        def method(index, restype, *argtypes):
            proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
            return proto(vtbl[index])

        set_options = method(9, ctypes.HRESULT, ctypes.c_uint)          # SetOptions
        set_title = method(17, ctypes.HRESULT, wintypes.LPCWSTR)        # SetTitle
        show = method(3, ctypes.HRESULT, wintypes.HWND)                 # Show
        get_result = method(20, ctypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))

        set_options(ptr, 0x20 | 0x800)      # PICKFOLDERS | FORCEFILESYSTEM
        set_title(ptr, title)
        if show(ptr, None) != 0:
            return None

        item_ptr = ctypes.c_void_p()
        if get_result(ptr, ctypes.byref(item_ptr)) != 0 or not item_ptr:
            return None

        item_vtbl = ctypes.cast(item_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_path = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                      ctypes.c_uint, ctypes.c_void_p)(item_vtbl[5])  # SIGDN_FILESYSPATH=0x80058000
        buf = ctypes.c_void_p()
        if get_path(item_ptr, 0x80058000, ctypes.byref(buf)) != 0 or not buf:
            return None
        result = ctypes.wstring_at(buf)
        ctypes.windll.ole32.CoTaskMemFree(buf)
        return Path(result) if result else None
    except Exception as exc:
        log(f"现代文件夹对话框不可用，改用备用方案：{exc}")

    # 2) tkinter 备用
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title=title, initialdir=str(start))
        root.destroy()
        return Path(chosen) if chosen else None
    except Exception as exc:
        log(f"tkinter 文件夹对话框也不可用：{exc}")
        return None


if __name__ == "__main__":
    cfg = Config()
    print(f"{APP_NAME_FULL} v{VERSION}")
    print(f"配置文件：{config_path()}")
    print(f"收纳目录：{cfg.get('desktop') or '(默认桌面)'}")
    print(f"桌面目录：{cfg.desktop}")
    print(f"视图模式：{cfg.get('view_mode')}")
    print(f"常用启动：{len(cfg.quick_items)} 项")
    print(f"开机自启：{autostart_status()}（配置记录：{cfg.get('autostart')}）")
