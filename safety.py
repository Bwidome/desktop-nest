#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 安全校验
============================
收纳的底线：**绝不删除任何文件，绝不移动系统关键项。**

这里集中处理三件事：
1. 识别桌面上那些"不能碰"的系统项（回收站、此电脑、网络…）
2. 判断路径包含关系（用于保证收纳目录不会落在桌面里面，否则会自己搬自己）
3. 判断文件是否被占用 / 可移动，并给出人话解释
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Windows 文件属性
# --------------------------------------------------------------------------
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_READONLY = 0x1

# 桌面上的系统虚拟项 / 系统文件：按名称保护（中英双语，覆盖各版本 Windows）
PROTECTED_NAMES = {
    # 虚拟图标
    "回收站", "recycle bin", "$recycle.bin", "recycler",
    "此电脑", "计算机", "我的电脑", "this pc", "computer", "my computer",
    "网络", "network", "network neighborhood", "网上邻居",
    "用户的文件", "用户文件夹", "user's files", "users files",
    "控制面板", "control panel",
    # 注意：这里只放「系统虚拟项 / 系统文件」。
    # 浏览器之类的普通应用快捷方式（如 Microsoft Edge）不在此列——
    # 它们就是桌面上普通的 .lnk，用户完全可能想收纳，不该被一刀切保护。
    # 系统文件
    "desktop.ini", "thumbs.db", "iconcache.db", ".ds_store", ".localized",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "bootmgr",
}

# 明确不该被收纳的文件后缀（系统/临时/半成品）
BLOCKED_SUFFIXES = {
    ".sys", ".drv", ".dll", ".ocx", ".cpl", ".msc",
    ".tmp", ".crdownload", ".part", ".partial", ".download",
}

# 明确不该被收纳的临时文件前缀（Office / 编辑器残留）
BLOCKED_PREFIXES = ("~$", ".~", "~")


@dataclass
class Verdict:
    """某个条目能不能收纳的结论。"""

    allowed: bool
    reason: str = ""
    kind: str = "ok"        # ok / protected / system / temp / busy / missing

    def __bool__(self) -> bool:
        return self.allowed


def get_attributes(path: Path) -> int:
    try:
        return int(path.stat().st_file_attributes)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return 0


def safe_exists(path: Path) -> bool:
    """``Path.exists()`` 在权限被拒时会直接抛 PermissionError（而不是返回 False），
    这在遍历桌面时很常见（比如某些沙箱目录）。所以统一走这个安全版本。"""
    try:
        return os.path.exists(path)
    except (OSError, ValueError):
        return False


def safe_is_dir(path: Path) -> bool:
    try:
        return os.path.isdir(path)
    except (OSError, ValueError):
        return False


def safe_is_file(path: Path) -> bool:
    try:
        return os.path.isfile(path)
    except (OSError, ValueError):
        return False


def safe_size(path: Path) -> int:
    try:
        return os.path.getsize(path)
    except (OSError, ValueError):
        return 0


def safe_mtime(path: Path) -> float:
    try:
        return os.path.getmtime(path)
    except (OSError, ValueError):
        return 0.0


def is_hidden(path: Path) -> bool:
    return bool(get_attributes(path) & FILE_ATTRIBUTE_HIDDEN)


def is_system(path: Path) -> bool:
    return bool(get_attributes(path) & FILE_ATTRIBUTE_SYSTEM)


def is_protected_name(name: str) -> bool:
    return name.strip().lower() in PROTECTED_NAMES


def is_blocked_suffix(name: str) -> bool:
    return Path(name).suffix.lower() in BLOCKED_SUFFIXES


def is_blocked_prefix(name: str) -> bool:
    return name.lower().startswith(BLOCKED_PREFIXES)


# --------------------------------------------------------------------------
# 文件占用检测
# --------------------------------------------------------------------------
def is_locked(path: Path) -> bool:
    """判断文件是否被别的程序"独占"占用。

    只用两种明确信号判断，不做"能不能写"这种猜测：
    * 连**打开**都失败（且不是只读属性造成的）→ 占用；
    * 打开成功但**加不上锁** → 别人正独占持有它。

    只读文件会退化成只读方式打开再试，所以"只读"不会被误报成"被占用"。
    """
    if not path.is_file():
        return False

    import msvcrt

    readonly = bool(get_attributes(path) & FILE_ATTRIBUTE_READONLY)
    handle = None
    try:
        try:
            handle = os.open(str(path), os.O_RDWR | os.O_BINARY)
        except PermissionError:
            if not readonly:
                return True          # 不是只读属性却打不开 → 被独占
            handle = os.open(str(path), os.O_RDONLY | os.O_BINARY)
        except OSError:
            return True
        try:
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
            return False
        except OSError:
            return True
    except OSError:
        return True
    finally:
        if handle is not None:
            try:
                os.close(handle)
            except OSError:
                pass


def can_move(path: Path) -> "tuple[bool, str]":
    """检查条目是否可以安全移动，返回 (能否移动, 原因)。"""
    if not safe_exists(path):
        return False, "文件已不存在"
    if safe_is_file(path):
        # 源文件所在的文件夹必须可写（改名需要），只读文件本身不影响移动
        try:
            probe = path.parent / f".dsh-write-{os.getpid()}.tmp"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except OSError:
            return False, "所在文件夹不可写（可能需要管理员权限）"
    if is_locked(path):
        return False, "文件正被其他程序独占使用"
    return True, ""


def check_desktop_item(path: Path) -> Verdict:
    """综合判断桌面上的一个条目能否收纳。"""
    name = path.name
    if not safe_exists(path):
        return Verdict(False, "文件已不存在", "missing")
    if is_protected_name(name):
        return Verdict(False, "系统图标，不参与收纳", "protected")
    if is_blocked_suffix(name):
        return Verdict(False, "系统文件或临时文件", "system")
    if is_blocked_prefix(name):
        return Verdict(False, "临时文件（~$ 开头）", "temp")
    if is_system(path):
        return Verdict(False, "带系统属性，为安全起见跳过", "system")
    if is_hidden(path):
        return Verdict(False, "隐藏文件，为安全起见跳过", "protected")
    ok, reason = can_move(path)
    if not ok:
        return Verdict(False, reason, "busy")
    return Verdict(True)


# --------------------------------------------------------------------------
# 路径合法性
# --------------------------------------------------------------------------
def is_subpath(child: Path, parent: Path) -> bool:
    """child 是否在 parent 里面（同级或更浅都返回 False）。"""
    try:
        child_r = child.resolve()
        parent_r = parent.resolve()
    except OSError:
        return False
    if child_r == parent_r:
        return True
    try:
        child_r.relative_to(parent_r)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# 桌面图标显示开关（可选功能，默认不动）
# --------------------------------------------------------------------------
_WIN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"


def desktop_icons_visible() -> "bool | None":
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "HideIcons")
            return int(value) == 0
    except (OSError, ValueError):
        return None


def set_desktop_icons_visible(visible: bool) -> "tuple[bool, str]":
    """隐藏 / 显示桌面图标（等效于桌面右键 → 查看 → 显示桌面图标）。"""
    if sys.platform != "win32":
        return False, "仅支持 Windows"
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _WIN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "HideIcons", 0, winreg.REG_DWORD,
                              0 if visible else 1)
    except OSError as exc:
        return False, f"写入设置失败：{exc}"

    # 通知 Explorer 立即刷新
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        result = ctypes.c_long()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0,
            ctypes.c_wchar_p("Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced"),
            0x0002, 2000, ctypes.byref(result))
    except Exception:
        pass

    state = desktop_icons_visible()
    if state is not None and state != visible:
        return True, "设置已保存，重启资源管理器后完全生效"
    return True, ""


if __name__ == "__main__":
    import config

    desk = config.get_desktop_dir()
    print(f"桌面目录：{desk}")
    print(f"桌面图标可见：{desktop_icons_visible()}")
    print()
    print("桌面条目校验结果：")
    if safe_exists(desk):
        for entry in sorted(desk.iterdir(), key=lambda p: p.name.lower()):
            verdict = check_desktop_item(entry)
            mark = "收纳" if verdict.allowed else "跳过"
            print(f"  [{mark}] {entry.name:<32} {verdict.reason}")
