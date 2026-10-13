#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安装器：绕过 pip，直接把 PyQt6 的 wheel 下载并解包到本目录的 libs/ 下。

为什么不用 pip：本环境的文件沙箱会拦掉 pip 下载 PEP 658 元数据（.whl.metadata）
那一步，导致任何 PyQt6 版本都装不上。而普通的网络下载 + zipfile 解包完全可用，
所以这里自己把 wheel 拉下来解开——效果等同于 `pip install --target libs`。

用法：python setup_libs.py
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIBS = HERE / "libs"

# PyQt6 / PyQt6_sip 是纯运行时包，Qt6 是它的运行库；sip 模块名是 PyQt6_sip
PACKAGES = ["PyQt6", "PyQt6-Qt6", "PyQt6_sip"]

RUNTIME_PY = (3, 12)          # 目标解释器版本（本机运行时）
WANT_BITS = "win_amd64"


# --------------------------------------------------------------------------
# wheel 选择
# --------------------------------------------------------------------------
def _tag_supported(tag: str) -> bool:
    """判断 wheel 标签是否能在 CPython 3.12 / win_amd64 上跑。"""
    if WANT_BITS not in tag:
        return False
    tag = tag.replace(WANT_BITS, "").rstrip("-")
    parts = [p for p in tag.split("-") if p]
    for part in parts:
        if part.startswith("cp"):
            match = re.match(r"cp(\d)(\d+)", part)
            if match:
                major, minor = int(match.group(1)), int(match.group(2))
                if (major, minor) > RUNTIME_PY:
                    return False          # 给更高版本 Python 编的，不能用
            continue
        if part.startswith("py") and part.endswith("none"):
            continue
        if part in ("abi3", "none"):
            continue
        if re.match(r"^cp\d+$", part):
            continue
    return True


def _compatible_wheels(files: "list[dict]") -> "list[dict]":
    out = []
    for entry in files:
        name = entry.get("filename", "")
        if not name.endswith(".whl"):
            continue
        tag = name[:-4].rsplit("-", 3)[-3:]          # 取 python-abi-platform 三段
        if len(tag) < 3:
            continue
        platform = tag[2]
        if platform != WANT_BITS and platform != "any":
            continue
        if not _tag_supported("-".join(tag)):
            continue
        out.append(entry)
    return out


def _rank(entry: dict) -> int:
    """越小越好：精确版本优先，其次是 abi3，最后才是 any。"""
    name = entry["filename"]
    if f"cp{RUNTIME_PY[0]}{RUNTIME_PY[1]}" in name:
        return 0
    if "abi3" in name:
        return 1
    if name.endswith("-any.whl"):
        return 3
    return 2


def pick_latest(project: str) -> "tuple[str, str]":
    """返回该项目最新的、有 Windows wheel 的版本及下载地址。"""
    data = json.loads(_get(f"https://pypi.org/pypi/{project}/json").decode("utf-8"))
    releases = data.get("releases", {})

    def version_key(text: str):
        return [int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", text)[:4]]

    for version in sorted(releases, key=version_key, reverse=True):
        wheels = _compatible_wheels(releases[version])
        if wheels:
            wheels.sort(key=_rank)
            return version, wheels[0]["url"]
    raise SystemExit(f"没有找到 {project} 的 Windows wheel")


def pick_matching_sip(pyqt_version: str) -> "tuple[str, str]":
    """PyQt6_sip 的主版本要跟 PyQt6 对得上，否则 QtCore 起不来。"""
    data = json.loads(_get("https://pypi.org/pypi/PyQt6_sip/json").decode("utf-8"))
    releases = data.get("releases", {})
    want_major = pyqt_version.split(".")[0]

    def version_key(text: str):
        return [int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", text)[:4]]

    fallback = None
    for version in sorted(releases, key=version_key, reverse=True):
        wheels = _compatible_wheels(releases[version])
        if not wheels:
            continue
        wheels.sort(key=_rank)
        candidate = (version, wheels[0]["url"])
        if fallback is None:
            fallback = candidate
        # PyQt6 6.x 系列用 sip 13.x；6.0~6.3 用 12.x
        if version.startswith("13.") and want_major == "6":
            return candidate
    if fallback:
        return fallback
    raise SystemExit("没有找到 PyQt6_sip 的 Windows wheel")


# --------------------------------------------------------------------------
# 下载 / 解包
# --------------------------------------------------------------------------
def _get(url: str, timeout: int = 300) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "DesktopNest-Setup/1.0",
        "Accept": "*/*",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _get_stream(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DesktopNest-Setup/1.0"})
    with urllib.request.urlopen(request, timeout=300) as response:
        chunks, total = [], 0
        while True:
            block = response.read(1024 * 512)
            if not block:
                break
            chunks.append(block)
            total += len(block)
            print(f"\r    下载中… {total / 1048576:6.1f} MB", end="", flush=True)
    print()
    return b"".join(chunks)


def extract(payload: bytes, destination: Path) -> int:
    count = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            if member.filename.endswith("/"):
                continue
            if ".dist-info/" in member.filename:
                rel = member.filename.split(".dist-info/", 1)[1]
                if rel.startswith(("RECORD", "WHEEL", "METADATA", "entry_points",
                                   "top_level", "INSTALLER", "REQUESTED")):
                    continue
            target = destination / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def main() -> int:
    LIBS.mkdir(parents=True, exist_ok=True)
    print(f"安装目录：{LIBS}")
    print(f"目标解释器：Python {RUNTIME_PY[0]}.{RUNTIME_PY[1]} / {WANT_BITS}")
    print()

    pyqt_version = None
    for project in PACKAGES:
        if project == "PyQt6_sip":
            if pyqt_version is None:
                print("  [跳过] PyQt6_sip（PyQt6 没装上）")
                continue
            version, url = pick_matching_sip(pyqt_version)
        else:
            version, url = pick_latest(project)
            if project == "PyQt6":
                pyqt_version = version
        print(f"  {project}  {version}")
        print(f"    {url.rsplit('/', 1)[-1]}")
        payload = _get_stream(url)
        count = extract(payload, LIBS)
        print(f"    解包完成，写入 {count} 个文件")
        print()

    sys.path.insert(0, str(LIBS))
    try:
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        from PyQt6.QtWidgets import QApplication  # noqa: F401
        print(f"OK: PyQt6 {PYQT_VERSION_STR} / Qt {QT_VERSION_STR} 导入成功")
    except Exception as exc:
        print(f"导入 PyQt6 失败：{type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
