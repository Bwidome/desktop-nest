#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收纳目录管理（desktop -> nest）
=============================
这个模块管的就是一件事：**把桌面上的东西搬进一个隐藏的收纳目录，退出时再搬回来**。

目录结构（所有实际内容都藏在 `~/.desktop-nest/` 下）：

    ~/.desktop-nest/
    ├── desktop/          ← 桌面上原来的文件、文件夹、快捷方式
    ├── links/            ← "此电脑""回收站"这些系统位置的快捷方式
    └── links.json        ← 记录每个系统快捷方式对应哪个 shell 位置

为什么用隐藏目录而不是"收纳仓库"：用户要的是"桌面干净 + 分页里能看到"，
不需要再多一个需要自己管理的文件夹概念。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import config
import safety
import winlink

Progress = "Callable[[int, int, str], None]"

NEST_DIR_NAME = ".desktop-nest"


# --------------------------------------------------------------------------
# 目录位置
# --------------------------------------------------------------------------
def nest_root() -> Path:
    """收纳根目录（优先用户目录，不可写时退到程序目录）。"""
    candidates = []
    try:
        candidates.append(Path.home() / NEST_DIR_NAME)
    except RuntimeError:
        pass
    candidates.append(config.default_project_dir() / NEST_DIR_NAME)
    for candidate in candidates:
        ok, _reason = _writable(candidate)
        if ok:
            return candidate
    return candidates[-1]


def _writable(folder: Path) -> "tuple[bool, str]":
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".probe-{os.getpid()}"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)


def desktop_store() -> Path:
    """桌面上原来的东西放这里。"""
    return nest_root() / "desktop"


def links_store() -> Path:
    """系统位置（此电脑 / 回收站…）的快捷方式放这里。"""
    return nest_root() / "links"


def links_manifest() -> Path:
    return nest_root() / "links.json"


def sources_manifest() -> Path:
    """记录每个收纳条目原来在哪个桌面（个人 / 公共）。

    还原时必须送回原处：公共桌面的快捷方式丢回个人桌面，等于把它"挪走了"，
    其他用户就看不到了。
    """
    return nest_root() / "sources.json"


def read_sources() -> "dict[str, str]":
    try:
        path = sources_manifest()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def write_sources(mapping: "dict[str, str]") -> None:
    try:
        ensure_dirs()
        sources_manifest().write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        config.log(f"写入来源清单失败：{exc}")


def remember_source(name: str, source: str) -> None:
    mapping = read_sources()
    if source:
        mapping[name] = source
    else:
        mapping.pop(name, None)
    write_sources(mapping)


def source_of(name: str) -> str:
    """一个收纳条目原来在哪个桌面（""=个人，"public"=公共）。"""
    return read_sources().get(name, "")


def desktop_for_source(source: str) -> Path:
    """来源标记 → 对应的桌面路径。"""
    if source == "public":
        return config.get_public_desktop_dir()
    return config.get_desktop_dir()


def ensure_dirs() -> Path:
    root = nest_root()
    desktop_store().mkdir(parents=True, exist_ok=True)
    links_store().mkdir(parents=True, exist_ok=True)
    return root


# --------------------------------------------------------------------------
# 系统位置快捷方式
# --------------------------------------------------------------------------
@dataclass
class SystemLink:
    """一个指向系统位置的快捷方式。"""

    name: str
    shell_path: str            # 形如 ::{CLSID}
    icon_source: str = ""      # 取图标用的真实文件（通常是 explorer.exe）
    link: "Path | None" = None


def default_system_links() -> "list[SystemLink]":
    """默认提供的系统位置。图标统一从 explorer.exe 里取，保证是系统原生样子。"""
    explorer = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe")
    return [
        SystemLink("此电脑", f"::{winlink.CLSID_THIS_PC}", explorer),
        SystemLink("回收站", f"::{winlink.CLSID_RECYCLE_BIN}", explorer),
        SystemLink("网络", f"::{winlink.CLSID_NETWORK}", explorer),
        SystemLink("用户文件夹", f"::{winlink.CLSID_USER_FILES}", explorer),
    ]


def _read_manifest() -> "dict[str, str]":
    try:
        if links_manifest().exists():
            data = json.loads(links_manifest().read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_manifest(mapping: "dict[str, str]") -> None:
    try:
        ensure_dirs()
        links_manifest().write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        config.log(f"写入系统链接清单失败：{exc}")


def sync_system_links(links: "list[SystemLink] | None" = None) -> "list[SystemLink]":
    """确保系统位置的快捷方式都存在，并记录名称 → shell 路径的映射。

    这样分页里就能显示出"此电脑""回收站"，点一下也能正确打开。
    """
    ensure_dirs()
    wanted = links if links is not None else default_system_links()
    mapping = _read_manifest()
    result: "list[SystemLink]" = []

    for entry in wanted:
        link = links_store() / f"{entry.name}.lnk"
        if not link.exists():
            ok, reason = winlink.create_shortcut(
                link, entry.shell_path,
                icon_path=entry.icon_source or None)
            if not ok:
                config.log(f"创建系统位置快捷方式失败 {entry.name}：{reason}")
                continue
        if entry.icon_source and entry.icon_source.lower().endswith(".exe"):
            # 让图标固定指向 explorer.exe 里那张标准图标
            pass
        mapping[entry.name] = entry.shell_path
        result.append(SystemLink(entry.name, entry.shell_path, entry.icon_source, link))

    _write_manifest(mapping)
    return result


def shell_path_for(link: Path) -> str:
    """查一个快捷方式对应的 shell 位置（`::{CLSID}`），没有就返回空串。"""
    mapping = _read_manifest()
    return mapping.get(Path(link).stem, "")


def open_system_link(link: Path) -> "tuple[bool, str]":
    """打开系统位置快捷方式。

    直接用 os.startfile 也行（Shell 认这种 DIDL 链接），但显式走
    `explorer.exe ::{CLSID}` 更稳，不依赖 ShellExecute 对 DIDL 的处理。
    """
    shell_path = shell_path_for(link)
    if shell_path:
        try:
            import subprocess

            subprocess.Popen(["explorer.exe", shell_path])
            return True, ""
        except OSError as exc:
            return False, str(exc)
    # 退回让 Shell 自己处理
    import engine

    return engine.launch(link)


# --------------------------------------------------------------------------
# 桌面条目
# --------------------------------------------------------------------------
def list_desktop(desktop: Path, *, include_public: bool = True
                 ) -> "tuple[list, list[tuple[str, str]]]":
    """列出要收纳的桌面条目（个人桌面 + 公共桌面）。

    文件夹整体算一个，不展开。公共桌面上的条目会带上 `source="public"` 标记，
    还原时才知道该送回哪里。
    """
    import engine

    items: "list" = []
    blocked: "list[tuple[str, str]]" = []

    targets = [(Path(desktop), "")]
    if include_public:
        public = config.get_public_desktop_dir()
        try:
            if public.exists() and public.resolve() != Path(desktop).resolve():
                targets.append((public, "public"))
        except OSError:
            pass

    for folder, source in targets:
        folder_items, folder_blocked = engine.list_desktop_items(folder)
        for item in folder_items:
            item.source = source
        items.extend(folder_items)
        if source == "public":
            blocked.extend((name, f"公共桌面：{reason}")
                           for name, reason in folder_blocked)
        else:
            blocked.extend(folder_blocked)
    return items, blocked


def list_nest_items() -> "list":
    """列出分页里要显示的全部条目：收纳内容 + 系统位置快捷方式。"""
    import engine

    items: "list" = []
    store = desktop_store()
    if safety.safe_exists(store):
        try:
            entries = sorted(store.iterdir(),
                             key=lambda p: (not safety.safe_is_dir(p), p.name.lower()))
        except OSError:
            entries = []
        for entry in entries:
            if safety.is_protected_name(entry.name):
                continue
            if entry.suffix.lower() == ".tmp" or entry.name.startswith("~$"):
                continue
            try:
                is_dir = safety.safe_is_dir(entry)
                items.append(engine.RepoItem(
                    entry, entry.name, is_dir, engine.kind_of(entry),
                    0 if is_dir else safety.safe_size(entry),
                    safety.safe_mtime(entry), entry.name,
                    source_of(entry.name)))
            except OSError:
                continue

    # 系统位置排在前面，和桌面上的观感一致
    for name, shell_path, _icon in [(e.name, e.shell_path, e.icon_source)
                                    for e in default_system_links()]:
        link = links_store() / f"{name}.lnk"
        if not link.exists():
            continue
        items.append(engine.RepoItem(link, name, False, "shortcut",
                                     0, safety.safe_mtime(link), name))
    return items


# --------------------------------------------------------------------------
# 搬移：桌面 → 收纳
# --------------------------------------------------------------------------
@dataclass
class MoveResult:
    moved: int = 0
    failed: "list[tuple[str, str]]" = field(default_factory=list)
    skipped: "list[tuple[str, str]]" = field(default_factory=list)
    cancelled: bool = False
    duration: float = 0.0

    def summary(self) -> str:
        parts = []
        if self.moved:
            parts.append(f"成功 {self.moved} 项")
        if self.failed:
            parts.append(f"失败 {len(self.failed)} 项")
        if self.skipped:
            parts.append(f"跳过 {len(self.skipped)} 项")
        if self.cancelled:
            parts.append("已中断")
        return "，".join(parts) if parts else "没有需要处理的条目"


def _unique(target: Path) -> Path:
    if not safety.safe_exists(target):
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    index = 1
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not safety.safe_exists(candidate):
            return candidate
        index += 1


def _move(source: Path, target: Path) -> Path:
    """把一个条目搬到 target。

    两条路径：
    * 同一个磁盘分区：`os.replace`，原子改名，瞬间完成、没有中间状态；
    * 跨分区：**复制 → 逐项校验 → 再删源**。校验通过才删源，
      一旦删源失败就把复制出来的东西回滚掉——绝不留下"两边都有一份"的重复文件。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    final = _unique(target)

    try:
        os.replace(source, final)
        return final
    except OSError:
        pass                                   # 跨分区或权限问题，走复制路径

    is_dir = safety.safe_is_dir(source)
    try:
        if is_dir:
            shutil.copytree(source, final)
            _verify_tree(source, final)
        else:
            shutil.copy2(source, final)
            _verify_copy(source, final)
    except Exception:
        _remove_quietly(final)                 # 复制/校验失败：清掉半成品
        raise

    try:
        if is_dir:
            shutil.rmtree(source)
        else:
            source.unlink()
    except OSError as exc:
        # 复制成功但删不掉源（被占用 / 权限不足）：
        # 回滚复制出来的那份，保持"要么都成、要么都不动"
        _remove_quietly(final)
        raise OSError(f"复制成功但无法删除原文件（{exc}），已回滚，未产生重复") from exc

    return final


def _remove_quietly(path: Path) -> None:
    """尽力删掉一个文件/目录，失败就算了（不掩盖原始错误）。"""
    try:
        if safety.safe_is_dir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif safety.safe_exists(path):
            path.unlink()
    except OSError:
        pass


def _verify_copy(source: Path, target: Path) -> None:
    """校验复制结果：大小、修改时间都要对上。"""
    if not safety.safe_exists(target):
        raise OSError("校验失败：目标文件不存在")
    src_size, dst_size = safety.safe_size(source), safety.safe_size(target)
    if src_size != dst_size:
        raise OSError(f"校验失败：大小不一致（{src_size} → {dst_size}）")


def _verify_tree(source: Path, target: Path) -> None:
    """递归校验整棵树：文件数量与每个文件的大小都要对上。"""
    checked = 0
    for current, _dirs, names in os.walk(source):
        rel = Path(current).relative_to(source)
        for name in names:
            src = Path(current) / name
            dst = target / rel / name
            if not safety.safe_exists(dst):
                raise OSError(f"校验失败：{name} 没有复制过去")
            if safety.safe_size(dst) != safety.safe_size(src):
                raise OSError(f"校验失败：{name} 大小不一致")
            checked += 1
    if checked == 0 and any(Path(source).iterdir()):
        raise OSError("校验失败：源目录里有内容但一个文件都没复制成功")


def take_from_desktop(desktop: Path, *, progress: "Progress | None" = None,
                      should_cancel: "Callable[[], bool] | None" = None,
                      items: "Iterable | None" = None,
                      include_public: bool = True) -> MoveResult:
    """把桌面上的条目搬进收纳目录。文件夹连同内容整体搬走。

    同时处理**个人桌面**和**公共桌面**（`C:\\Users\\Public\\Desktop`）——
    公共桌面上的快捷方式在所有用户桌面都会显示，不一起收就收不干净。
    每个条目的来源会记进 sources.json，还原时送回原处。
    """
    started = time.time()
    result = MoveResult()
    ensure_dirs()
    store = desktop_store()

    if items is None:
        entries, blocked = list_desktop(desktop, include_public=include_public)
        result.skipped.extend(blocked)
    else:
        entries = list(items)

    total = len(entries)
    for index, item in enumerate(entries, start=1):
        if should_cancel and should_cancel():
            result.cancelled = True
            break
        if progress:
            progress(index, total, item.name)
        source = Path(item.path)
        if not safety.safe_exists(source):
            result.failed.append((item.name, "文件已不存在"))
            continue
        if safety.is_protected_name(source.name):
            result.skipped.append((item.name, "系统图标，保持原样"))
            continue
        # 公共桌面上的东西可能和用户桌面同名，重名时前面加个标记便于区分
        target_name = source.name
        if getattr(item, "source", "") == "public" and \
                safety.safe_exists(store / f"{target_name}"):
            stem, suffix = Path(target_name).stem, Path(target_name).suffix
            target_name = f"{stem}（公用）{suffix}"
        try:
            _move(source, store / target_name)
            # 记下它原来在哪个桌面，还原时才能送回原处
            remember_source(target_name, getattr(item, "source", ""))
            result.moved += 1
        except PermissionError:
            result.failed.append((item.name, "被占用或无权限，请关闭正在使用它的程序"))
        except OSError as exc:
            result.failed.append((item.name, str(exc)))
        except Exception as exc:
            result.failed.append((item.name, f"意外错误：{exc}"))

    result.duration = time.time() - started
    return result


def restore_to_desktop(desktop: Path, *, progress: "Progress | None" = None,
                       should_cancel: "Callable[[], bool] | None" = None) -> MoveResult:
    """把收纳目录里的东西全部搬回**各自原来的桌面**。

    公共桌面的快捷方式送回公共桌面，个人桌面的送回个人桌面——
    否则公用快捷方式会被挪到个人桌面，其他用户就看不到了。
    """
    started = time.time()
    result = MoveResult()
    try:
        desktop.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.failed.append(("（桌面）", f"无法访问桌面：{exc}"))
        return result

    store = desktop_store()
    if not safety.safe_exists(store):
        return result
    try:
        entries = sorted(store.iterdir(),
                         key=lambda p: (not safety.safe_is_dir(p), p.name.lower()))
    except OSError:
        return result

    total = len(entries)
    for index, entry in enumerate(entries, start=1):
        if should_cancel and should_cancel():
            result.cancelled = True
            break
        if progress:
            progress(index, total, entry.name)
        # 送回原处；公共桌面不可写时退回个人桌面，至少不把文件丢了
        origin = desktop_for_source(source_of(entry.name))
        target_name = entry.name
        if origin != desktop and "（公用）" in entry.name:
            target_name = entry.name.replace("（公用）", "")   # 去掉区分用后缀
        try:
            if not safety.safe_exists(origin):
                origin.mkdir(parents=True, exist_ok=True)
            _move(entry, origin / target_name)
            forget_source(entry.name)
            result.moved += 1
        except PermissionError:
            if origin != desktop:
                # 公共桌面写不进去（需要管理员），退回个人桌面并说明
                try:
                    _move(entry, desktop / target_name)
                    forget_source(entry.name)
                    result.moved += 1
                    result.skipped.append(
                        (entry.name, "公共桌面不可写，已放回个人桌面"))
                    continue
                except OSError as exc:
                    result.failed.append((entry.name, f"公共桌面与个人桌面都写不进去：{exc}"))
                    continue
            result.failed.append((entry.name, "被占用或无权限"))
        except OSError as exc:
            result.failed.append((entry.name, str(exc)))
        except Exception as exc:
            result.failed.append((entry.name, f"意外错误：{exc}"))

    result.duration = time.time() - started
    return result


def forget_source(name: str) -> None:
    mapping = read_sources()
    if name in mapping:
        mapping.pop(name, None)
        write_sources(mapping)


def restore_item_to_desktop(desktop: Path, item) -> "tuple[bool, str]":
    """把单个条目搬回它原来的桌面。"""
    source = Path(item.path)
    if not safety.safe_exists(source):
        return False, "文件已不存在"
    origin = desktop_for_source(getattr(item, "source", "") or source_of(source.name))
    target_name = source.name
    if origin != desktop and "（公用）" in target_name:
        target_name = target_name.replace("（公用）", "")
    try:
        if not safety.safe_exists(origin):
            origin.mkdir(parents=True, exist_ok=True)
        _move(source, origin / target_name)
        forget_source(source.name)
        return True, ""
    except PermissionError:
        # 公共桌面写不进去就退回个人桌面，不把文件卡在收纳目录里
        try:
            _move(source, desktop / target_name)
            forget_source(source.name)
            return True, "公共桌面不可写，已放回个人桌面"
        except OSError as exc:
            return False, f"公共桌面与个人桌面都写不进去：{exc}"
    except OSError as exc:
        return False, str(exc)


def nest_has_content() -> bool:
    """收纳目录里是否还有东西（判断"桌面被搬空了"）。"""
    store = desktop_store()
    if not safety.safe_exists(store):
        return False
    try:
        return any(store.iterdir())
    except OSError:
        return False


def desktop_item_count(desktop: Path) -> int:
    """真实桌面上还剩多少可收纳的东西。"""
    items, _blocked = list_desktop(desktop)
    return len(items)


# --------------------------------------------------------------------------
# 桌面图标开关（把桌面上的图标藏起来，做到"完全空白"）
# --------------------------------------------------------------------------
def icons_visible() -> "bool | None":
    return safety.desktop_icons_visible()


def set_icons_visible(visible: bool) -> "tuple[bool, str]":
    return safety.set_desktop_icons_visible(visible)


if __name__ == "__main__":
    import engine

    print(f"收纳根目录：{nest_root()}")
    print(f"  桌面内容：{desktop_store()}")
    print(f"  系统链接：{links_store()}")
    print(f"  可写：{_writable(nest_root())[0]}")
    print()
    links = sync_system_links()
    print(f"系统位置快捷方式（{len(links)} 个）：")
    for entry in links:
        print(f"  {entry.name:<8} shell={entry.shell_path}  link={entry.link}")
    print()
    print(f"桌面图标当前可见：{icons_visible()}")
    print(f"收纳目录里有内容：{nest_has_content()}")
    print(f"真实桌面待收纳：{desktop_item_count(config.get_desktop_dir())} 项")
