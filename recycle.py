#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回收站（Windows Shell 的"删除到回收站"）
========================================
本程序有一条铁律：**自动流程绝不删除任何文件**——收纳只是"搬进收纳目录"，
还原只是"搬回桌面"，全程没有一条会丢数据的路径。

这个模块是那条铁律**唯一的例外**，而且必须同时满足三个条件才允许发生：

1. **只由用户显式触发**。右键菜单里点「删除」，还要在确认框上再点一次
   「是」。没有任何代码路径会自己走到这里。
2. **只进回收站，永不永久删除**。走的是 `FOF_ALLOWUNDO`，
   和资源管理器里按 Delete 键是**同一条 Shell 代码路径**：
   文件进回收站、能看原路径、能一键还原。
3. **不碰系统项**。`guard()` 会把"此电脑 / 回收站 / desktop.ini / 带系统
   属性的条目 / 盘符根目录 / 收纳目录本体"全部挡在外面。

为什么不用 `os.remove()` / `shutil.rmtree()`：那是**真删**，
用户手一抖就找不回来了，和这个程序"只搬不删"的定位直接冲突。

用法::

    ok, reason = recycle.guard(path)     # 先问能不能删
    if ok:
        ok, message = recycle.recycle(path)
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import safety

_IS_WINDOWS = os.name == "nt"

# --------------------------------------------------------------------------
# SHFileOperationW 的常量与结构体
# --------------------------------------------------------------------------
# 操作码：删除
_FO_DELETE = 0x0003

# 标志位（FILEOP_FLAGS，WORD 类型）
_FOF_SILENT = 0x0004            # 不显示进度对话框
_FOF_NOCONFIRMATION = 0x0010    # 不再问"确定要删除吗"——我们自己已经问过了
_FOF_ALLOWUNDO = 0x0040         # ★ 关键：删到回收站而不是真删
_FOF_NOERRORUI = 0x0400         # 出错也不弹系统对话框，把错误码还给我们
_FOF_NOCONFIRMMKDIR = 0x0200

_DELETE_FLAGS = (_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT
                 | _FOF_NOERRORUI | _FOF_NOCONFIRMMKDIR)


class _SHFILEOPSTRUCTW(ctypes.Structure):
    """`SHFileOperationW` 的入参结构体。

    字段顺序 / 类型必须和 Windows SDK 里的一模一样。注意 `fFlags` 是
    `FILEOP_FLAGS`，也就是 **WORD（2 字节）**，不是 DWORD——写成
    `c_uint32` 会让后面的 `fAnyOperationsAborted` 整体错位 2 字节，
    Shell 读到的是垃圾值，表现是"明明成功却报失败"。
    """

    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


class _SHQUERYRBINFO(ctypes.Structure):
    """`SHQueryRecycleBinW` 的出参：回收站里有多少东西、占多大。"""

    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


_SHELL32 = None
_LOAD_ERROR = ""


def _shell32():
    """拿到 shell32（带正确的 argtypes/restype），拿不到就返回 None。

    单例化是有原因的：`argtypes` 设错会让 ctypes 按默认的 `c_int` 传参，
    在 64 位下把指针截断——那种崩溃很难查。
    """
    global _SHELL32, _LOAD_ERROR
    if _SHELL32 is not None:
        return _SHELL32 or None
    if not _IS_WINDOWS:
        _LOAD_ERROR = "非 Windows 平台"
        _SHELL32 = False
        return None
    try:
        lib = ctypes.WinDLL("shell32", use_last_error=True)
        lib.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
        lib.SHFileOperationW.restype = ctypes.c_int
        lib.SHQueryRecycleBinW.argtypes = [ctypes.c_wchar_p,
                                           ctypes.POINTER(_SHQUERYRBINFO)]
        lib.SHQueryRecycleBinW.restype = ctypes.c_long
        _SHELL32 = lib
    except Exception as exc:                       # pragma: no cover
        _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        _SHELL32 = False
    return _SHELL32 or None


def available() -> bool:
    """这台机器上能不能用 Shell 的删除接口。"""
    return _shell32() is not None


def load_error() -> str:
    return _LOAD_ERROR


# --------------------------------------------------------------------------
# 错误码 → 人话
# --------------------------------------------------------------------------
_ERROR_TEXT = {
    0x02: "找不到文件（可能已经被移走了）",
    0x05: "拒绝访问（文件被占用，或需要管理员权限）",
    0x20: "文件正被其他程序占用",
    0x71: "源路径和目标路径是同一个",
    0x78: "拒绝访问源文件",
    0x7C: "路径无效",
    0x7D: "目标路径无效",
    0x7E: "卷上还有打开的文件",
    0x80: "试图把多个文件重命名成同一个名字",
    0x81: "试图把一个目录移到它自己的子目录里",
    0x84: "目录不是空的",
    0x85: "路径太长",
    0x86: "路径里有非法字符",
    0x87: "文件名里有非法字符",
    0xB7: "同名文件已经存在",
    0x10000: "磁盘已满或目标不可写",
}


def error_text(code: int) -> str:
    code = int(code)
    if code in _ERROR_TEXT:
        return _ERROR_TEXT[code]
    if code & 0xFFFF in _ERROR_TEXT:
        return _ERROR_TEXT[code & 0xFFFF]
    return f"Shell 返回错误码 0x{code:X}"


# --------------------------------------------------------------------------
# 闸门
# --------------------------------------------------------------------------
def guard(path: "Path | str") -> "tuple[bool, str]":
    """先问一句"这个能不能删"。返回 `(能否删, 不能删的原因)`。

    宁可多挡几种，也不能让"删错了"这种事发生——它虽然可还原，
    但用户的心理成本远高于多点一次菜单。
    """
    if not _IS_WINDOWS:
        return False, "只支持 Windows"
    try:
        target = Path(path)
    except (TypeError, ValueError):
        return False, "路径无效"
    if not str(target):
        return False, "路径为空"
    if not safety.safe_exists(target):
        return False, "文件已经不存在了"

    # 盘符根目录：删掉等于把整个盘端掉
    try:
        if target.parent == target:
            return False, "这是盘符根目录，不能删"
    except OSError:
        pass

    if safety.is_protected_name(target.name):
        return False, "系统图标或系统文件，不参与删除"
    if safety.is_system(target):
        return False, "带系统属性，为安全起见不删"

    # 收纳目录本体（或它的上级）不能删：删掉的话桌面上的东西就无处安放了
    try:
        import nest as nest_mod

        root = nest_mod.nest_root()
    except Exception:
        root = None
    if root is not None and safety.is_subpath(root, target):
        return False, "这是收纳目录本身（或它的上级目录），不能删"

    return True, ""


# --------------------------------------------------------------------------
# 删除
# --------------------------------------------------------------------------
def recycle(path: "Path | str") -> "tuple[bool, str]":
    """把文件 / 文件夹送进回收站。返回 `(是否成功, 失败原因或空串)`。

    **这是本程序里唯一会"让文件从原位置消失"的函数**，所以它自己也会再跑
    一遍 `guard()`——不指望调用方一定先问过。
    """
    ok, reason = guard(path)
    if not ok:
        return False, reason
    lib = _shell32()
    if lib is None:
        return False, f"取不到 Shell 删除接口（{_LOAD_ERROR or '未知原因'}）"

    target = Path(path)
    # pFrom 必须是**绝对路径**，而且要以**两个** \0 结尾（这是双空终止的多字符串）
    absolute = os.path.abspath(str(target))

    struct = _SHFILEOPSTRUCTW()
    struct.hwnd = None
    struct.wFunc = _FO_DELETE
    struct.pFrom = absolute + "\0"
    struct.pTo = None
    struct.fFlags = _DELETE_FLAGS
    struct.fAnyOperationsAborted = 0
    struct.hNameMappings = None
    struct.lpszProgressTitle = None

    try:
        code = lib.SHFileOperationW(ctypes.byref(struct))
    except Exception as exc:                       # pragma: no cover
        return False, f"调用 Shell 删除接口失败：{exc}"

    code = int(code)

    # ------------------------------------------------------------------
    # 判据是**事实**，不是返回码。
    #
    # 实测（本机 Win11）：只要带上 `FOF_ALLOWUNDO`，Shell 会在**成功**之后
    # 仍然返回 `2`（ERROR_FILE_NOT_FOUND）—— 文件明明已经进了回收站、
    # `$I` 元数据里的原始路径也完全正确。不带 `ALLOWUNDO` 时才规规矩矩返回 0。
    # 反过来也见过：返回 0 而文件还在（被别的程序占着）。
    #
    # 所以这里两种方向都不能信，只看一件事：**文件还在不在原位置**。
    # 在 = 没成功；不在 = 成功（`guard()` 已经确认过它之前是存在的，
    # 而 pFrom 只有这一个路径，Shell 没有别的可动）。
    # ------------------------------------------------------------------
    if not safety.safe_exists(target):
        return True, ""

    if code != 0:
        return False, error_text(code)
    if int(struct.fAnyOperationsAborted):
        return False, "操作被中断"
    return False, "Shell 报告成功，但文件仍在（可能正被其他程序占用）"


# --------------------------------------------------------------------------
# 回收站现状（给自检用：删之前 / 删之后比一比，证明真的进了回收站）
# --------------------------------------------------------------------------
def bin_stats() -> "tuple[int, int] | None":
    """返回 `(回收站条目数, 占用字节)`；查不到返回 None。"""
    lib = _shell32()
    if lib is None:
        return None
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
    try:
        code = lib.SHQueryRecycleBinW(None, ctypes.byref(info))
    except Exception:                              # pragma: no cover
        return None
    if int(code) != 0:
        return None
    return int(info.i64NumItems), int(info.i64Size)


def describe() -> str:
    """给自检 / 日志用的一句话说明。"""
    if not available():
        return f"回收站不可用（{load_error()}）"
    stats = bin_stats()
    if stats is None:
        return "回收站可用（读不到统计信息）"
    count, size = stats
    return f"回收站可用（当前 {count} 项 / {size / 1048576:.1f} MB）"


if __name__ == "__main__":
    import sys as _sys

    print(describe())
    for raw in _sys.argv[1:]:
        allowed, why = guard(raw)
        print(f"  {'可删' if allowed else '拒绝'}  {raw}  {why}")
