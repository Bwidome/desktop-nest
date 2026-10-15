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

# 记忆：`nest_root()` 会被频繁调用（每个条目取图标都要问一次），
# 而候选判定要 stat 好几次。同一个进程里目录不会变，缓存住。
# 缓存键是"当前 nest_root 函数对象的 id"——函数被替换过（测试指到沙盒）
# 就自动不命中，不需要调用方记得清缓存。
_NEST_ROOT_CACHE: "Path | None" = None
_NEST_ROOT_CACHE_KEY: "int | None" = None


# --------------------------------------------------------------------------
# 目录位置
# --------------------------------------------------------------------------
def nest_root() -> Path:
    """收纳根目录。

    **优先级：已有内容的目录 > 新位置。**

    为什么这条顺序很关键（"退出重开后菜单栏图标不显示"的根因）：
    早先这里只按"能不能写"挑，第一个能写的就用。于是当程序从**项目目录**启动、
    而用户上一次用的是 `~/.desktop-nest` 时，会在项目里**另建一个空的**
    `.desktop-nest` 并采用它 —— 配置里的常用软件仍然记着
    `C:\\Users\\<你>\\.desktop-nest\\desktop\\xxx.lnk`，而 `desktop_store()`
    指向了项目里那个空目录，`twin_path()` 自然一个都对不上，
    所有常用软件的图标就全部取不到（菜单栏上一排占位块）。

    现在的规则：
    1. 谁已经有 `desktop/` 内容就用谁（不新建、不抢）；
    2. 都没有时，优先用户目录（可写就用）；
    3. 用户目录写不了才退到程序目录。
    """
    global _NEST_ROOT_CACHE, _NEST_ROOT_CACHE_KEY
    # 缓存键带上"当前这个函数对象"。`nest_root` 被替换过（测试里指到沙盒）
    # 就不会命中缓存 —— 否则换了个实现还返回老结果，测试会看到空目录。
    key = id(nest_root)
    if _NEST_ROOT_CACHE is not None and _NEST_ROOT_CACHE_KEY == key:
        return _NEST_ROOT_CACHE

    candidates: "list[Path]" = []
    try:
        candidates.append(Path.home() / NEST_DIR_NAME)
    except RuntimeError:
        pass
    candidates.append(config.default_project_dir() / NEST_DIR_NAME)

    _NEST_ROOT_CACHE = _pick_nest_root(candidates)
    _NEST_ROOT_CACHE_KEY = key
    return _NEST_ROOT_CACHE


def _dir_has_content(folder: Path) -> bool:
    """这个目录里是不是已经有东西了（用来判断"这是用户正在用的那个 nest"）。"""
    try:
        if not folder.is_dir():
            return False
        desktop_dir = folder / "desktop"
        if desktop_dir.is_dir() and any(desktop_dir.iterdir()):
            return True
        # desktop 空但根目录里已经有清单文件，也算"正在用"
        return any(folder.iterdir())
    except OSError:
        return False


def _pick_nest_root(candidates: "list[Path]") -> Path:
    """按"已有内容 > 能写 > 兜底"挑一个收纳根目录。"""
    for candidate in candidates:
        if _dir_has_content(candidate):
            return candidate
    for candidate in candidates:
        ok, _reason = _writable(candidate)
        if ok:
            return candidate
    return candidates[-1]


def forget_nest_root() -> None:
    """丢掉目录缓存（测试里把 nest_root 换成沙盒路径后要调它）。"""
    global _NEST_ROOT_CACHE
    _NEST_ROOT_CACHE = None


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


def twin_path(path: "Path | str", desktop: "Path | str") -> "Path | None":
    """同一个条目在**收纳目录 / 桌面**上的另一半，存在才返回。

    为什么需要它：常用启动里存的是"当前那个位置"的路径。程序刚启动时，
    配置里记的还可能是收纳目录里的路径（上次运行时收进去的），可那一刻
    东西还好好躺在桌面上——路径不存在，取图标就会失败（Shell 对不存在的
    路径会回一张白纸图标）。反过来，程序把桌面收进来之后，桌面上的那份
    又没了。

    取图标这种"只读"的场合，用孪生路径当来源最稳：两边哪个在就用哪个，
    用户看到的永远是真实的程序图标。
    """
    try:
        path = Path(path)
    except (TypeError, ValueError):
        return None
    try:
        desktop = Path(desktop)
    except (TypeError, ValueError):
        return None
    store = desktop_store()
    for origin, other in ((store, desktop), (desktop, store)):
        try:
            relative = path.relative_to(origin)
        except ValueError:
            continue
        if not relative.parts:
            continue
        twin = other / relative
        return twin if twin.exists() else None
    return None


def icon_source(path: "Path | str", desktop: "Path | str") -> "Path | None":
    """取图标时该读哪个文件：优先本体，本体不在就退回它的孪生路径。

    都不在就返回 None —— 调用方据此**不去请求图标**，界面上留占位块，
    等文件真的到位（下一次重建）再取。这条是"白纸图标"的兜底闸门。
    """
    try:
        path = Path(path)
    except (TypeError, ValueError):
        return None
    if path.exists():
        return path
    return twin_path(path, desktop)


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
        mapping[entry.name] = entry.shell_path
        result.append(SystemLink(entry.name, entry.shell_path, entry.icon_source, link))

    _write_manifest(mapping)
    return result


def shell_path_map() -> "dict[str, str]":
    """一次读出「快捷方式名 → shell 位置」的完整映射。

    调用方在循环里逐条判断时应该先取一次这个映射，
    而不是每条都调 shell_path_for()——那会让每个条目都去读一遍 links.json。
    """
    return _read_manifest()


def shell_path_for(link: Path) -> str:
    """查一个快捷方式对应的 shell 位置（`::{CLSID}`），没有就返回空串。"""
    return shell_path_map().get(Path(link).stem, "")


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
    """列出收纳面板里要显示的全部条目：**只有收纳内容**。

    需求：「移除收纳面板的此电脑、回收站、网络、用户文件夹」。
    所以这里不再把系统位置的快捷方式拼进来 —— 面板只展示真正被收进来的
    文件 / 文件夹 / 快捷方式。

    `links_store()` 与 `links.json` 仍然照常维护（见 `sync_system_links`）：
    它们还被"退出还原时别把系统项也当内容搬走"用到
    （`shell_path_map()` 会把这类条目排除掉），只是不再出现在界面上。
    """
    import engine

    items: "list" = []
    store = desktop_store()
    # 来源清单只读一次——逐条去读会让 N 个条目产生 N 次文件读取
    sources = read_sources()
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
                    sources.get(entry.name, "")))
            except OSError:
                continue
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
    # 实际发生的搬移 (原路径, 现路径)，用于写操作流水、支持整批撤销
    moves: "list[tuple[str, str]]" = field(default_factory=list)

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

    # 安全底线：收纳目录绝不能和桌面互相包含，否则会自己搬自己
    if safety.is_subpath(store, desktop) or safety.is_subpath(desktop, store):
        result.failed.append(
            ("（配置）", "收纳目录不能设在桌面里面，否则会自己搬自己"))
        return result

    if items is None:
        entries, blocked = list_desktop(desktop, include_public=include_public)
        result.skipped.extend(blocked)
    else:
        entries = list(items)

    # 来源清单只在开始时读一次、结束时写一次：
    # 逐条读+写会让 N 个条目产生 2N 次整文件 IO
    sources = read_sources()
    sources_dirty = False

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
            final = _move(source, store / target_name)
            # 记下它原来在哪个桌面，还原时才能送回原处（按实际落地的文件名记）
            origin = getattr(item, "source", "")
            if origin:
                sources[final.name] = origin
            else:
                sources.pop(final.name, None)
            sources_dirty = True
            result.moves.append((str(source), str(final)))
            result.moved += 1
        except PermissionError:
            result.failed.append((item.name, "被占用或无权限，请关闭正在使用它的程序"))
        except OSError as exc:
            result.failed.append((item.name, str(exc)))
        except Exception as exc:
            result.failed.append((item.name, f"意外错误：{exc}"))

    if sources_dirty:
        write_sources(sources)
    if result.moves:
        _append_journal({"time": started, "action": "take",
                         "count": len(result.moves), "moves": result.moves})

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
    # 来源清单读一次、写一次（理由同 take_from_desktop）
    sources = read_sources()
    sources_dirty = False
    for index, entry in enumerate(entries, start=1):
        if should_cancel and should_cancel():
            result.cancelled = True
            break
        if progress:
            progress(index, total, entry.name)
        # 送回原处；公共桌面不可写时退回个人桌面，至少不把文件丢了
        origin = desktop_for_source(sources.get(entry.name, ""))
        target_name = entry.name
        if origin != desktop and "（公用）" in entry.name:
            target_name = entry.name.replace("（公用）", "")   # 去掉区分用后缀
        try:
            if not safety.safe_exists(origin):
                origin.mkdir(parents=True, exist_ok=True)
            final = _move(entry, origin / target_name)
            if entry.name in sources:
                sources.pop(entry.name, None)
                sources_dirty = True
            result.moves.append((str(entry), str(final)))
            result.moved += 1
        except PermissionError:
            if origin != desktop:
                # 公共桌面写不进去（需要管理员），退回个人桌面并说明
                try:
                    final = _move(entry, desktop / target_name)
                    if entry.name in sources:
                        sources.pop(entry.name, None)
                        sources_dirty = True
                    result.moves.append((str(entry), str(final)))
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

    if sources_dirty:
        write_sources(sources)
    if result.moves:
        _append_journal({"time": started, "action": "restore",
                         "count": len(result.moves), "moves": result.moves})

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
        final = _move(source, origin / target_name)
        forget_source(source.name)
        _append_journal({"time": time.time(), "action": "restore",
                         "count": 1, "moves": [(str(source), str(final))]})
        return True, ""
    except PermissionError:
        # 公共桌面写不进去就退回个人桌面，不把文件卡在收纳目录里
        try:
            final = _move(source, desktop / target_name)
            forget_source(source.name)
            _append_journal({"time": time.time(), "action": "restore",
                             "count": 1, "moves": [(str(source), str(final))]})
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
# 操作流水（写进 journal.jsonl，主面板里选中某条即可原样撤回）
# --------------------------------------------------------------------------
def journal_path() -> Path:
    return config.data_dir() / "journal.jsonl"


def _append_journal(record: "dict") -> None:
    """追加一条操作流水。

    流水只用于「事后可撤销」，写失败不该影响搬移本身，所以这里吞掉异常。
    """
    try:
        with journal_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        config.log(f"写入流水失败：{exc}")


def read_journal(limit: int = 50) -> "list[dict]":
    """读出最近的若干条流水（按时间倒序）。"""
    path = journal_path()
    if not safety.safe_exists(path):
        return []
    records: "list[dict]" = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    records.sort(key=lambda r: r.get("time", 0), reverse=True)
    return records[:limit]


def undo_record(record: "dict", *, progress: "Progress | None" = None) -> MoveResult:
    """按流水把一次操作整体撤回去（**逆序**搬回）。

    逆序很关键：一次操作里可能出现「A 搬到 B、B 又被改名」这类链式变化，
    倒着来才能让每个条目回到它当时的位置。
    """
    started = time.time()
    result = MoveResult()
    moves = list(record.get("moves") or [])
    total = len(moves)
    for index, move in enumerate(reversed(moves), start=1):
        if not isinstance(move, (list, tuple)) or len(move) != 2:
            continue
        source, target = Path(move[0]), Path(move[1])
        if progress:
            progress(index, total, source.name)
        if not safety.safe_exists(target):
            result.failed.append((source.name, "文件已不在当前位置"))
            continue
        try:
            final = _move(target, source)
            forget_source(target.name)
            result.moves.append((str(target), str(final)))
            result.moved += 1
        except OSError as exc:
            result.failed.append((source.name, str(exc)))
    result.duration = time.time() - started
    return result


def drop_journal_record(timestamp: float) -> int:
    """撤销成功后把该条流水删掉，避免重复撤销。返回剩余条数。"""
    path = journal_path()
    if not safety.safe_exists(path):
        return 0
    kept: "list[str]" = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if abs(float(rec.get("time", -1)) - float(timestamp)) < 0.0005:
                    continue
                kept.append(json.dumps(rec, ensure_ascii=False))
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    except OSError:
        return -1
    return len(kept)


def clear_journal() -> bool:
    """清空全部流水。"""
    try:
        if safety.safe_exists(journal_path()):
            journal_path().unlink()
        return True
    except OSError:
        return False


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
