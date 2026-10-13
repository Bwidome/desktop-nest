#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 快捷方式（.lnk）底层封装
================================
用 COM 的 `IShellLinkW` + `IPersistFile` 创建和读取 .lnk。

为什么要用 COM 而不是自己写二进制：Explorer 对 .lnk 的结构相当挑剔，
而 `IShellLinkW` 是官方接口，能正确生成"此电脑""回收站"这类**虚拟位置**
的快捷方式（路径写成 `::{CLSID}` 的形式），自己拼字节很容易做出打不开的链接。

对外只暴露两个简单函数：
    create_shortcut(link, target, arguments, icon, description)
    resolve_shortcut_target(link)
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# 常用系统位置的 CLSID（可以直接当成路径用：'::{CLSID}'）
CLSID_THIS_PC = "{20D04FE0-3AEA-1069-A2D8-08002B30309D}"        # 此电脑
CLSID_RECYCLE_BIN = "{645FF040-5081-101B-9F08-00AA002F954E}"     # 回收站
CLSID_NETWORK = "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}"         # 网络
CLSID_USER_FILES = "{59031a47-3f72-44a7-89c5-5595fe6b30ee}"      # 用户文件夹
CLSID_CONTROL_PANEL = "{5399E694-6CE5-4D6C-8FCE-1D8870FDCBA0}"   # 控制面板
CLSID_DRIVES = "{8E908FC9-BECC-40f6-915B-F4CA0E70D03D}"          # 此电脑（驱动器视图）

_IID_ISHELLLINKW = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPERSISTFILE = "{0000010b-0000-0000-C000-000000000046}"
_CLSID_SHELLLINK = "{00021401-0000-0000-C000-000000000046}"

CLSCTX_INPROC_SERVER = 1

# IShellLinkW 的 GetPath 标志
SLGP_RAWPATH = 0x00000004
SLGP_UNCPRIORITY = 0x00000002


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    value = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(str(text), ctypes.byref(value))
    return value


_COM_READY = False


def _init_com() -> None:
    """初始化 COM（同一线程重复调用是安全的）。"""
    global _COM_READY
    if _COM_READY or not IS_WINDOWS:
        return
    try:
        # COINIT_APARTMENTTHREADED = 0x2
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)
    except Exception:
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
    _COM_READY = True


class _ShellLink:
    """IShellLinkW 的极简封装（只用到几个方法）。

    下面这些下标是**实测**出来的，不是照文档背的：COM 虚表一旦错位，
    调用不会报错，只会静默把数据写到别的属性上（例如"说明"写成了"参数"），
    生成一堆看起来正常、实际打不开的快捷方式。
    验证方式见 `dev/probe_vtable.py`：逐个下标写标记值，再用 Windows 官方的
    `WScript.Shell` 读回来对账。
    """

    # 实测确认的虚表下标
    IDX_GET_PATH = 3
    IDX_GET_ARGUMENTS = 6
    IDX_SET_DESCRIPTION = 7          # 用不到，但留着备查
    IDX_SET_WORKING_DIR = 9
    IDX_SET_ARGUMENTS = 11
    IDX_SET_ICON_LOCATION = 17
    IDX_SET_PATH = 20

    def __init__(self) -> None:
        _init_com()
        ptr = ctypes.c_void_p()
        clsid = _guid(_CLSID_SHELLLINK)
        iid = _guid(_IID_ISHELLLINKW)
        hr = ctypes.windll.ole32.CoCreateInstance(
            ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER,
            ctypes.byref(iid), ctypes.byref(ptr))
        if hr != 0 or not ptr:
            raise OSError(f"创建 ShellLink 失败（HRESULT 0x{hr & 0xFFFFFFFF:08X}）")
        self.ptr = ptr
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        self._vtbl = vtbl

    def _method(self, index: int, *argtypes):
        proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
        return proto(self._vtbl[index])

    # ---- IShellLinkW ----
    def set_path(self, path: str) -> None:
        self._method(self.IDX_SET_PATH, wintypes.LPCWSTR)(self.ptr, str(path))

    def set_arguments(self, arguments: str) -> None:
        self._method(self.IDX_SET_ARGUMENTS, wintypes.LPCWSTR)(self.ptr, str(arguments))

    def set_working_dir(self, folder: str) -> None:
        self._method(self.IDX_SET_WORKING_DIR, wintypes.LPCWSTR)(self.ptr, str(folder))

    def set_icon_location(self, icon_path: str, index: int = 0) -> None:
        self._method(self.IDX_SET_ICON_LOCATION, wintypes.LPCWSTR, ctypes.c_int)(
            self.ptr, str(icon_path), int(index))

    def get_path(self) -> str:
        buffer = ctypes.create_unicode_buffer(1024)
        hr = self._method(self.IDX_GET_PATH, wintypes.LPWSTR, ctypes.c_int,
                          ctypes.c_void_p, ctypes.c_uint)(
            self.ptr, buffer, 1024, None, SLGP_RAWPATH)
        if hr != 0:
            return ""
        return buffer.value

    def get_arguments(self) -> str:
        """读取链接参数。

        注意：Windows 的 `IShellLinkW::GetArguments` 在 ctypes 直连虚表时
        会返回 E_INVALIDARG（本机实测，写入侧正常、官方 COM 也能读到，
        但直连读取不成功）。与其返回一个可能是错的空串，不如明确返回空串并由
        调用方走"我们自己记录的清单"来判断——见 `nest.shell_path_for()`。
        """
        return ""

    def save(self, link: Path) -> bool:
        """通过 IPersistFile::Save 落盘。"""
        iid = _guid(_IID_IPERSISTFILE)
        persist = ctypes.c_void_p()
        query = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p))(self._vtbl[0])
        if query(self.ptr, ctypes.byref(iid), ctypes.byref(persist)) != 0 or not persist:
            return False
        try:
            pvtbl = ctypes.cast(
                persist, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            link.parent.mkdir(parents=True, exist_ok=True)
            # IPersistFile::Save(LPCOLESTR, BOOL fRemember)
            save = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                      wintypes.LPCWSTR, ctypes.c_int)(pvtbl[6])
            hr = save(persist, str(link), 1)
            if hr != 0:
                return False
            return link.exists()
        finally:
            try:
                release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(pvtbl[2])
                release(persist)
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(self._vtbl[2])
            release(self.ptr)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def create_shortcut(link: Path, target: str, *, arguments: str = "",
                    icon_path: "str | None" = None, icon_index: int = 0,
                    working_dir: "str | None" = None) -> "tuple[bool, str]":
    """创建一个 .lnk。

    target 可以是文件路径，也可以是 `::{CLSID}` 形式的系统位置
    （此电脑、回收站等虚拟文件夹）。
    """
    if not IS_WINDOWS:
        return False, "仅支持 Windows"
    try:
        shell_link = _ShellLink()
        shell_link.set_path(target)
        if arguments:
            shell_link.set_arguments(arguments)
        if working_dir:
            shell_link.set_working_dir(working_dir)
        # 只有真实存在的文件才拿来当图标来源；虚拟位置交给系统自己决定图标
        icon = icon_path
        if icon is None and target and not target.startswith("::") and os.path.exists(target):
            icon = target
        if icon:
            shell_link.set_icon_location(icon, icon_index)
        if shell_link.save(Path(link)):
            return True, ""
        return False, "保存快捷方式失败"
    except OSError as exc:
        return False, str(exc)
    except Exception as exc:                       # COM 什么怪错都可能抛
        return False, f"{type(exc).__name__}: {exc}"


def resolve_shortcut_target(link: Path) -> "Path | None":
    """读取 .lnk 指向的目标路径；解析不出来返回 None（比如指向虚拟位置）。"""
    if not IS_WINDOWS or Path(link).suffix.lower() != ".lnk":
        return None
    try:
        shell_link = _ShellLink()
        # IPersistFile::Load
        iid = _guid(_IID_IPERSISTFILE)
        persist = ctypes.c_void_p()
        query = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p))(shell_link._vtbl[0])
        if query(shell_link.ptr, ctypes.byref(iid), ctypes.byref(persist)) != 0 or not persist:
            return None
        pvtbl = ctypes.cast(
            persist, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        load = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR,
                                  ctypes.c_uint)(pvtbl[5])
        if load(persist, str(link), 0) != 0:
            try:
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(pvtbl[2])(persist)
            except Exception:
                pass
            return None
        path = shell_link.get_path()
        try:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(pvtbl[2])(persist)
        except Exception:
            pass
        if not path:
            # 有些链接把目标放在参数里（例如指向控制面板项）
            arguments = shell_link.get_arguments()
            if arguments.startswith("::") or arguments.startswith("/"):
                candidate = arguments.split(" ")[0]
                if candidate.startswith("::"):
                    return None                    # 虚拟位置，没有文件路径
            return None
        return Path(path)
    except Exception:
        return None


def shortcut_details(link: Path) -> "dict[str, str]":
    """读出快捷方式的目标路径（能读到的话）。"""
    out = {"target": "", "arguments": ""}
    if not IS_WINDOWS:
        return out
    try:
        shell_link = _ShellLink()
        iid = _guid(_IID_IPERSISTFILE)
        persist = ctypes.c_void_p()
        query = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p))(shell_link._vtbl[0])
        if query(shell_link.ptr, ctypes.byref(iid), ctypes.byref(persist)) != 0 or not persist:
            return out
        pvtbl = ctypes.cast(
            persist, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        load = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR,
                                  ctypes.c_uint)(pvtbl[5])
        if load(persist, str(link), 0) == 0:
            out["target"] = shell_link.get_path()
            out["arguments"] = shell_link.get_arguments()
        try:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(pvtbl[2])(persist)
        except Exception:
            pass
    except Exception:
        pass
    return out


def is_system_location(link: Path) -> bool:
    """判断这个快捷方式是不是指向系统虚拟位置（此电脑 / 回收站这类）。

    判据：**读不出真实文件路径**。系统位置的链接里存的是 shell 的 DIDL
    （`::{CLSID}`），`GetPath()` 拿不到普通路径，因此模板在
    `winlink.SYSTEM_LOCATIONS` 里、且目标为空的，就是系统位置。

    这类链接不能用 `os.startfile` 直接打开——ShellExecute 对 DIDL 会失败
    （错误 5），得走 `explorer.exe ::{CLSID}`。
    """
    link = Path(link)
    if link.suffix.lower() != ".lnk":
        return False
    known = {name for name, _target, _desc in SYSTEM_LOCATIONS}
    if link.stem not in known:
        return False
    return not shortcut_details(link)["target"]


def open_system_location(link: Path) -> "tuple[bool, str]":
    """用资源管理器打开系统虚拟位置的快捷方式。"""
    import subprocess

    if not is_system_location(link):
        return False, "不是系统位置的快捷方式"
    target = ""
    for name, shell_target, _desc in SYSTEM_LOCATIONS:
        if Path(link).stem == name:
            target = shell_target
            break
    if not target:
        return False, "找不到对应的系统位置"
    try:
        subprocess.Popen(["explorer.exe", target])
        return True, ""
    except OSError as exc:
        return False, str(exc)


# --------------------------------------------------------------------------
# 系统位置的快捷方式
# --------------------------------------------------------------------------
SYSTEM_LOCATIONS: "list[tuple[str, str, str]]" = [
    # (显示名, 目标, 说明)
    ("此电脑", f"::{CLSID_THIS_PC}", "打开此电脑"),
    ("回收站", f"::{CLSID_RECYCLE_BIN}", "打开回收站"),
    ("网络", f"::{CLSID_NETWORK}", "打开网络位置"),
    ("用户文件夹", f"::{CLSID_USER_FILES}", "打开用户文件夹"),
    ("控制面板", f"::{CLSID_CONTROL_PANEL}", "打开控制面板"),
]


def ensure_system_shortcuts(folder: Path, locations: "list[tuple[str, str, str]] | None" = None
                            ) -> "tuple[int, list[str]]":
    """在指定文件夹里补齐"此电脑""回收站"这些系统位置的快捷方式。

    返回 (成功创建数量, 失败原因列表)。
    """
    folder = Path(folder)
    created = 0
    errors: "list[str]" = []
    for name, target, description in (locations or SYSTEM_LOCATIONS):
        link = folder / f"{name}.lnk"
        if link.exists():
            continue
        ok, reason = create_shortcut(link, target)
        if ok:
            created += 1
        else:
            errors.append(f"{name}: {reason}")
    return created, errors


if __name__ == "__main__":
    import shutil
    import tempfile

    print(f"COM 可用：{IS_WINDOWS}")
    base = Path(tempfile.gettempdir()) / "nest-lnk-test"
    # 每次都从干净目录开始，避免看到上一次的残留
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    created, errors = ensure_system_shortcuts(base)
    print(f"创建系统位置快捷方式：{created} 个，失败 {errors}")
    for link in sorted(base.glob("*.lnk")):
        details = shortcut_details(link)
        print(f"  {link.name:<16} 系统位置={is_system_location(link)}  "
              f"target={details['target']!r} args={details['arguments']!r}")

    probe = base / "记事本.lnk"
    ok, reason = create_shortcut(probe, r"C:\Windows\System32\notepad.exe")
    print(f"创建程序快捷方式：{ok} {reason}")
    print(f"  解析目标：{resolve_shortcut_target(probe)}")
    print(f"  被识别为系统位置（应为 False）：{is_system_location(probe)}")
