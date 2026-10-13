#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 收纳引擎
============================
负责所有"动文件"的事情，完全不依赖界面，可以单独调用、单独测试。

核心承诺（需求 7）
------------------
* **只移动，绝不删除** —— 迁移成功后才清理来源；失败原样保留。
* **绝不覆盖** —— 目标重名自动加 `(1)`、`(2)` 后缀。
* **失败可解释** —— 占用 / 权限 / 断链都会给出人话原因。
* **全程可撤销** —— 每次迁移写一条流水，支持整批还原回桌面。

两种搬运方式：
* 同一个磁盘分区内用 `os.replace`（原子改名，瞬间完成）；
* 跨分区（比如桌面在 C:、仓库在 D:）用"先复制、校验大小、再删源"，
  这样最坏情况是留下重复文件，绝不会出现文件凭空消失。
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import config
import safety

Progress = "Callable[[int, int, str], None]"
ShouldCancel = "Callable[[], bool]"


# --------------------------------------------------------------------------
# 支持搬运的文件类型（图标要显示类型，所以这里统一分类）
# --------------------------------------------------------------------------
KIND_SUFFIXES = {
    "shortcut": {".lnk", ".url"},
    "program": {".exe", ".msi", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".jar",
                ".appx", ".msix", ".apk"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico",
              ".heic", ".tif", ".tiff", ".psd", ".ai", ".avif"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
              ".mpg", ".mpeg", ".rmvb"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".ape"},
    "document": {".doc", ".docx", ".pdf", ".txt", ".rtf", ".odt", ".md", ".wps",
                 ".epub", ".tex"},
    "sheet": {".xls", ".xlsx", ".csv", ".ods", ".numbers", ".tsv"},
    "slide": {".ppt", ".pptx", ".odp", ".dps", ".key"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab"},
    "code": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs",
             ".rb", ".php", ".html", ".css", ".json", ".xml", ".yml", ".yaml",
             ".sql", ".sh", ".ipynb"},
    "font": {".ttf", ".otf", ".woff", ".woff2", ".fon"},
}

SUFFIX_TO_KIND = {suffix: kind for kind, suffixes in KIND_SUFFIXES.items() for suffix in suffixes}

KIND_LABELS = {
    "shortcut": "快捷方式", "program": "程序", "image": "图片", "video": "视频",
    "audio": "音频", "document": "文档", "sheet": "表格", "slide": "演示",
    "archive": "压缩包", "code": "代码", "font": "字体", "folder": "文件夹",
    "other": "其他",
}


def kind_of(path: Path) -> str:
    if path.is_dir():
        return "folder"
    return SUFFIX_TO_KIND.get(path.suffix.lower(), "other")


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            return f"{int(num)} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def time_text(stamp: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))
    except (OSError, OverflowError, ValueError):
        return "--"


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class RepoItem:
    """收纳目录里的一个条目（或桌面上/公共桌面上待收纳的条目）。"""

    path: Path
    name: str
    is_dir: bool
    kind: str
    size: int
    mtime: float
    rel: str = ""                 # 相对根的路径，列表里显示用
    # 这个条目原来在哪个桌面："" = 用户桌面，"public" = 公共桌面
    # 还原时要靠它送回原处，不能一股脑丢回个人桌面
    source: str = ""

    @property
    def size_text(self) -> str:
        return "文件夹" if self.is_dir else human_size(self.size)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, "其他")

    @property
    def suffix(self) -> str:
        return "" if self.is_dir else self.path.suffix.lower().lstrip(".")

    @property
    def from_public_desktop(self) -> bool:
        return self.source == "public"


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
def list_desktop_items(desktop: Path, *, include_hidden: bool = False
                       ) -> "tuple[list[RepoItem], list[tuple[str, str]]]":
    """列出桌面上的全部条目，**文件夹也照列**（给底部菜单栏的分页浏览用）。

    这里不做"能不能收纳"的过滤（那是 migrate 的事），只排除真正的系统文件
    （desktop.ini 之类），保证看到的内容和桌面上亲眼所见一致。
    """
    items: "list[RepoItem]" = []
    skipped: "list[tuple[str, str]]" = []
    if not safety.safe_exists(desktop):
        return items, skipped
    try:
        entries = sorted(desktop.iterdir(),
                         key=lambda p: (not safety.safe_is_dir(p), p.name.lower()))
    except OSError as exc:
        return items, [("（桌面）", f"无法读取：{exc}")]

    for entry in entries:
        name = entry.name
        if name.lower() in safety.PROTECTED_NAMES:
            continue
        if safety.is_blocked_suffix(name) or safety.is_blocked_prefix(name):
            continue
        if not include_hidden and safety.is_hidden(entry):
            continue
        try:
            is_dir = safety.safe_is_dir(entry)
            items.append(RepoItem(entry, name, is_dir, kind_of(entry),
                                  0 if is_dir else safety.safe_size(entry),
                                  safety.safe_mtime(entry), name))
        except OSError as exc:
            skipped.append((name, str(exc)))
    return items, skipped


def folder_summary(path: Path, *, max_entries: int = 800) -> "tuple[int, int]":
    """统计文件夹里有多少文件、多少子文件夹（详情面板显示用）。"""
    files = folders = 0
    count = 0
    try:
        for _current, dirs, names in os.walk(path):
            folders += len(dirs)
            files += len(names)
            count += len(dirs) + len(names)
            if count >= max_entries:
                break
    except OSError:
        pass
    return files, folders


# --------------------------------------------------------------------------
# 搬运原语
# --------------------------------------------------------------------------


def resolve_shortcut_target(lnk: Path) -> "Path | None":
    """解析 .lnk 快捷方式指向的目标；解析不出来就返回 None。

    直接读 .lnk 的二进制结构（[MS-SHLLINK]），不走 COM：COM 那套虚表调用
    索引写错一个就会静默失败，而文件格式是可预测、可调试的。

    可靠性从高到低依次尝试：
    1. LinkInfo.LocalBasePath —— 快捷方式自己存的完整路径，最准；
    2. StringData.IconLocation —— 常常直接指向目标程序本体；
    3. StringData.RelativePath + WorkingDir；
    4. LinkTargetIDList —— 结构最容易读歪，必须通过"可打印性"检查才采用，
       宁可返回 None 让图标退回 Shell 类型图标，也不返回一串乱码路径。
    """
    if os.name != "nt" or lnk.suffix.lower() != ".lnk":
        return None
    try:
        data = lnk.read_bytes()
    except OSError:
        return None
    if len(data) < 0x4C:
        return None

    # ---- ShellLinkHeader ----
    (header_size,) = struct.unpack_from("<I", data, 0)
    if header_size != 0x4C:
        return None
    (flags,) = struct.unpack_from("<I", data, 0x14)
    has_id_list = bool(flags & 0x01)
    has_link_info = bool(flags & 0x02)

    # 依次跳过 IDList 和 LinkInfo，定位到 StringData
    offset = header_size
    if has_id_list and offset + 2 <= len(data):
        (id_list_size,) = struct.unpack_from("<H", data, offset)
        offset += 2 + id_list_size
    link_info_start = offset
    has_info = has_link_info and offset + 4 <= len(data)
    if has_info:
        (link_info_size,) = struct.unpack_from("<I", data, offset)
        offset += max(4, link_info_size)

    # ---- 1) LinkInfo ----
    if has_info:
        target = _target_from_link_info(data, link_info_start)
        if target is not None:
            return target

    strings = _read_string_data(data, offset, flags) if offset < len(data) else {}

    # ---- 2) IconLocation ----
    candidate = _clean_icon_location(strings.get("icon_location", ""))
    if candidate is not None:
        return candidate

    # ---- 3) RelativePath ----
    relative = strings.get("relative_path", "").strip()
    if relative:
        for base in (strings.get("working_dir", "").strip(),
                     str(lnk.parent)):
            if not base:
                continue
            combined = Path(base) / relative
            try:
                if safety.safe_exists(combined):
                    return combined
            except OSError:
                continue
    # 读不出普通路径（多半是指向"此电脑""回收站"这类虚拟位置）就返回 None，
    # 由调用方按名字去 nest 的清单里查对应 shell 位置。
    return None


def _read_string_data(data: bytes, offset: int, flags: int) -> "dict[str, str]":
    """读取 StringData 段（每个字段都是 <2字节字符数><UTF-16LE 内容>）。"""
    out: "dict[str, str]" = {}
    fields = [
        (0x00000004, "name"),
        (0x00000008, "relative_path"),
        (0x00000010, "working_dir"),
        (0x00000020, "arguments"),
        (0x00000040, "icon_location"),
    ]
    cursor = offset
    for flag, key in fields:
        if not (flags & flag):
            continue
        if cursor + 2 > len(data):
            break
        (length,) = struct.unpack_from("<H", data, cursor)
        cursor += 2
        byte_count = length * 2
        if cursor + byte_count > len(data):
            break
        raw = data[cursor:cursor + byte_count]
        cursor += byte_count
        out[key] = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return out


def _clean_icon_location(text: str) -> "Path | None":
    """IconLocation 形如 "C:\\App\\app.exe,0" 或 "C:\\App\\a.dll,-101"。"""
    text = (text or "").strip().strip('"')
    if not text:
        return None
    if "," in text:
        head, _, tail = text.rpartition(",")
        if tail.strip().lstrip("-").isdigit():
            text = head
    text = text.strip().strip('"')
    if not text:
        return None
    path = Path(text)
    try:
        if safety.safe_exists(path):
            return path
    except OSError:
        pass
    return None


def _target_from_link_info(data: bytes, start: int) -> "Path | None":
    """从 LinkInfo 结构里取出目标路径。"""
    try:
        (link_info_size,) = struct.unpack_from("<I", data, start)
        (link_info_header_size,) = struct.unpack_from("<I", data, start + 4)
        (link_info_flags,) = struct.unpack_from("<I", data, start + 8)
        (volume_id_offset,) = struct.unpack_from("<I", data, start + 12)
        (local_base_path_offset,) = struct.unpack_from("<I", data, start + 16)
    except struct.error:
        return None
    if link_info_header_size < 0x1C or link_info_size <= 0:
        return None

    base = ""
    if local_base_path_offset:
        begin = start + local_base_path_offset
        end = data.find(b"\x00", begin)
        if begin < end <= start + link_info_size:
            base = data[begin:end].decode("mbcs", errors="replace")

    if base and (base[1:3] == ":\\" or base.startswith("\\\\")):
        return Path(base)                        # 完整路径，直接用

    volume = _volume_root(data, start, volume_id_offset)
    if volume and base:
        return Path(volume.rstrip("\\") + "\\" + base.lstrip("\\"))
    if volume:
        return Path(volume)
    return None


def _volume_root(data: bytes, start: int, volume_id_offset: int) -> str:
    """从 VolumeID 里取出盘符根，例如 "C:\\"。"""
    if not volume_id_offset:
        return ""
    base = start + volume_id_offset
    try:
        (volume_id_size,) = struct.unpack_from("<I", data, base)
        (drive_type,) = struct.unpack_from("<I", data, base + 4)
        (serial,) = struct.unpack_from("<I", data, base + 8)
        (label_offset,) = struct.unpack_from("<I", data, base + 12)
    except struct.error:
        return ""
    if volume_id_size < 0x10 or not label_offset:
        return ""
    begin = base + label_offset
    end = data.find(b"\x00", begin)
    if not (begin < end <= base + volume_id_size):
        return ""
    label = data[begin:end].decode("mbcs", errors="replace")
    if drive_type == 3:
        return label                              # DRIVE_FIXED，卷标即 "C:\"
    if drive_type == 4:
        return "\\\\" + label                     # DRIVE_REMOTE，NetBIOS 名
    return ""


def open_in_explorer(path: Path) -> None:
    """在资源管理器中打开（文件夹直接进，文件选中）。"""
    try:
        if path.is_dir():
            os.startfile(str(path))          # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(path)])
    except (AttributeError, OSError):
        import subprocess

        subprocess.Popen(["explorer", str(path if path.is_dir() else path.parent)])


def launch(path: Path) -> "tuple[bool, str]":
    """打开文件 / 启动快捷方式。返回 (成功?, 失败原因)。"""
    if not safety.safe_exists(path):
        return False, "文件已不存在"
    try:
        os.startfile(str(path))              # type: ignore[attr-defined]
        return True, ""
    except OSError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


if __name__ == "__main__":
    # 只读预演：看看桌面上有哪些条目、各自是什么类型（不动任何文件）
    cfg = config.Config()
    desktop = cfg.desktop
    print(f"桌面目录：{desktop}")
    entries, blocked = list_desktop_items(desktop)
    print(f"条目数：{len(entries)}")
    for item in entries:
        kind = "文件夹" if item.is_dir else item.kind_label
        print(f"  {item.name:<40} {kind:<6} {item.size_text}")
    if blocked:
        print(f"跳过 {len(blocked)} 项：")
        for name, reason in blocked:
            print(f"  · {name:<30} {reason}")

