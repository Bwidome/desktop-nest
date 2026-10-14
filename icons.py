#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面收纳美化工具 —— 图标提取
============================
清单里每个条目都要显示图标，而 `.lnk` 快捷方式必须显示**它指向的程序**的图标，
不能用那个千篇一律的快捷方式箭头小图标。

做法：直接向 Windows Shell 要图标（`SHGetFileInfoW`）。
Shell 内部会自己解析 .lnk、.url、.exe 的资源段、文件类型关联，比手写解析可靠得多。

**两档取法**，按清晰度需求挑：

* `get_icon()`      —— `SHGetFileInfoW` 的 LARGEICON / SMALLICON，最大 32×32。
                       清单、列表这类小图标够用，也最省内存（几百个条目一起取）。
* `get_icon_best()` —— `SHGetImageList(SHIL_JUMBO)` 拿 **256×256**，
                       再交给 Qt 平滑缩到显示尺寸。菜单栏那种"图标要放大显示"
                       的地方必须走这条，否则就是把 32×32 硬拉大，一片糊。

因为图标要在后台线程里取（避免几百个文件卡住界面），这里只负责产出
「原始像素 + 尺寸」这种纯数据，转成 Qt 图片的事情交给界面线程做。
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# SHGetFileInfo 标志位
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001
SHGFI_USEFILEATTRIBUTES = 0x000000010
SHGFI_SHELLICONSIZE = 0x000000004
SHGFI_SYSICONINDEX = 0x00004000

# 系统图像列表（SHGetImageList）的尺寸编号
SHIL_LARGE = 0            # 32×32
SHIL_SMALL = 1            # 16×16
SHIL_EXTRALARGE = 2       # 48×48
SHIL_SYSSMALL = 3
SHIL_JUMBO = 4            # 256×256 —— 菜单栏要的就是这张
ILD_TRANSPARENT = 0x00000001

# IImageList 的 IID（`{46EB5926-...}` 是 shell 公布的稳定值，不要改）
IID_IIMAGE_LIST = "{46EB5926-582E-4017-9FDF-E8998DAA0950}"

# 菜单栏图标的目标边长：先拿 256×256 的原图，再由 Qt 平滑缩到显示尺寸
JUMBO_SIZE = 256

FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_DIRECTORY = 0x10

# 缓存目录放在包的旁边，跟着程序走
_CACHE_DIR_NAME = ".icon-cache"


# --------------------------------------------------------------------------
# Win32 结构
# --------------------------------------------------------------------------
class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_uint),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_bool),
        ("xHotspot", ctypes.c_uint),
        ("yHotspot", ctypes.c_uint),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", ctypes.c_ushort),
        ("bmBitsPixel", ctypes.c_ushort),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint),
        ("biSizeImage", ctypes.c_uint),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint),
        ("biClrImportant", ctypes.c_uint),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint * 3)]


class _GUID(ctypes.Structure):
    """COM 的 GUID（只用来承载 IImageList 的 IID）。"""

    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


@dataclass(frozen=True)
class RawIcon:
    """图标的原始像素（BGRA，Qt 的 Format_ARGB32 就是这个字节序）。"""

    width: int
    height: int
    bgra: bytes
    key: str = ""

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0 and len(self.bgra) == self.width * self.height * 4


# --------------------------------------------------------------------------
# 提取
# --------------------------------------------------------------------------
def _hicon_to_raw(hicon: int) -> "RawIcon | None":
    """把 HICON 转成原始 BGRA 像素。用完就销毁句柄，不泄漏 GDI 资源。"""
    if not hicon:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    info = _ICONINFO()
    if not user32.GetIconInfo(ctypes.c_void_p(hicon), ctypes.byref(info)):
        return None
    hbm_color = info.hbmColor
    hbm_mask = info.hbmMask
    try:
        if not hbm_color:
            return None
        bmp = _BITMAP()
        if not gdi32.GetObjectW(ctypes.c_void_p(hbm_color), ctypes.sizeof(bmp),
                                ctypes.byref(bmp)):
            return None
        width, height = int(bmp.bmWidth), int(bmp.bmHeight)
        if width <= 0 or height <= 0 or width > 1024 or height > 1024:
            return None

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height        # 负数 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0         # BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        hdc = user32.GetDC(None)
        try:
            copied = gdi32.GetDIBits(hdc, ctypes.c_void_p(hbm_color), 0, height,
                                     buffer, ctypes.byref(bmi), 0)
        finally:
            user32.ReleaseDC(None, hdc)
        if not copied:
            return None
        data = bytes(buffer.raw)

        # 有些图标 alpha 全 0（老式 24 位图标），用掩码补出不透明区域，
        # 否则显示出来会是一张全透明的空图。
        if not any(data[3::4]):
            data = _apply_mask_alpha(data, hbm_mask, width, height)
        return RawIcon(width, height, data)
    finally:
        if hbm_color:
            gdi32.DeleteObject(ctypes.c_void_p(hbm_color))
        if hbm_mask:
            gdi32.DeleteObject(ctypes.c_void_p(hbm_mask))
        user32.DestroyIcon(ctypes.c_void_p(hicon))


def _apply_mask_alpha(data: bytes, hbm_mask: int, width: int, height: int) -> bytes:
    """用 AND 掩码把 1 位透明信息补成 alpha 通道。"""
    if not hbm_mask:
        return data
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    bmp = _BITMAP()
    if not gdi32.GetObjectW(ctypes.c_void_p(hbm_mask), ctypes.sizeof(bmp), ctypes.byref(bmp)):
        return data
    mask_w, mask_h = int(bmp.bmWidth), int(bmp.bmHeight)
    if mask_w != width or mask_h not in (height, height * 2):
        return data
    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = mask_w
    bmi.bmiHeader.biHeight = -mask_h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 1
    bmi.bmiHeader.biCompression = 0
    stride = ((mask_w + 31) // 32) * 4
    buffer = ctypes.create_string_buffer(stride * mask_h)
    hdc = user32.GetDC(None)
    try:
        if not gdi32.GetDIBits(hdc, ctypes.c_void_p(hbm_mask), 0, mask_h, buffer,
                               ctypes.byref(bmi), 0):
            return data
    finally:
        user32.ReleaseDC(None, hdc)

    mask = buffer.raw
    out = bytearray(data)
    for y in range(height):
        row = y * stride
        for x in range(width):
            bit = (mask[row + (x >> 3)] >> (7 - (x & 7))) & 1
            if bit:                              # 掩码为 1 = 透明
                out[(y * width + x) * 4 + 3] = 0
    return bytes(out)


def _shell_icon(path: Path, size: int) -> "RawIcon | None":
    """向 Shell 要图标。size 取 16 / 32 / 48 / 256。"""
    if not IS_WINDOWS:
        return None
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    flags = SHGFI_ICON
    if size <= 16:
        flags |= SHGFI_SMALLICON
    else:
        flags |= SHGFI_LARGEICON

    info = _SHFILEINFOW()
    # 路径不存在时（比如断掉的快捷方式）用 USEFILEATTRIBUTES 仍能拿到类型图标
    exists = path.exists()
    attributes = 0
    flags_used = flags
    if not exists:
        flags_used |= SHGFI_USEFILEATTRIBUTES
        attributes = FILE_ATTRIBUTE_DIRECTORY if path.suffix == "" else FILE_ATTRIBUTE_NORMAL

    # SHGFI 会自己解析 .lnk / .url；给文件夹或 exe 时直接给路径
    icon_path = str(path)

    result = shell32.SHGetFileInfoW(icon_path, attributes, ctypes.byref(info),
                                    ctypes.sizeof(info), flags_used)
    if not result or not info.hIcon:
        # 兜底：按扩展名取类型图标
        result = shell32.SHGetFileInfoW(path.suffix or "file", FILE_ATTRIBUTE_NORMAL,
                                        ctypes.byref(info), ctypes.sizeof(info),
                                        flags | SHGFI_USEFILEATTRIBUTES)
        if not result or not info.hIcon:
            return None
    return _hicon_to_raw(int(info.hIcon))


def _extract_exe_icon(exe: Path, size: int) -> "RawIcon | None":
    """直接从 exe 资源段取图标（快捷方式指向的程序常常能取到更清晰的大图）。"""
    if not IS_WINDOWS or not exe.exists():
        return None
    try:
        user32 = ctypes.windll.user32
        # 让 Windows 按目标尺寸从 exe 里挑最合适的那张图
        hicon = user32.PrivateExtractIconW(0, str(exe), 0)
        if not hicon:
            large = ctypes.c_void_p()
            small = ctypes.c_void_p()
            count = ctypes.windll.shell32.ExtractIconExW(str(exe), 0,
                                                         ctypes.byref(large),
                                                         ctypes.byref(small), 1)
            if not count:
                return None
            chosen = large if (size >= 32 and large.value) else small
            other = small if chosen is large else large
            if other.value:
                user32.DestroyIcon(other)
            hicon = chosen.value
        if not hicon:
            return None
        return _hicon_to_raw(int(hicon))
    except Exception:
        return None


# --------------------------------------------------------------------------
# 高清图标：系统图像列表里的 256×256（jumbo）
# --------------------------------------------------------------------------
def _system_icon_index(path: Path) -> "int | None":
    """问 Shell 要这个条目的图标**编号**（而不是图标本身）。

    `SHGFI_SYSICONINDEX` 返回的编号是"系统图像列表"里的下标，
    同一份编号在 16 / 32 / 48 / 256 各张列表里指的是**同一个图标**，
    所以拿它去 jumbo 列表里取，就能得到同一张图的 256×256 版本。
    """
    if not IS_WINDOWS:
        return None
    info = _SHFILEINFOW()
    result = ctypes.windll.shell32.SHGetFileInfoW(
        str(path), 0, ctypes.byref(info), ctypes.sizeof(info), SHGFI_SYSICONINDEX)
    if not result:
        return None
    return int(info.iIcon)


def _image_list_icon(index: int, shil: int = SHIL_JUMBO) -> "RawIcon | None":
    """从系统图像列表里按下标取指定尺寸的图标（默认 jumbo = 256×256）。

    这里要手工走一次 COM 虚表，因为 ctypes 没有 IImageList 的现成绑定：
        [2]  Release()
        [10] GetIcon(int i, UINT flags, HICON *phicon)
    取到的 HICON 交给 `_hicon_to_raw` 转像素（它会顺手 DestroyIcon，不漏 GDI 句柄）。
    """
    if not IS_WINDOWS:
        return None
    shell32 = ctypes.windll.shell32
    if not hasattr(shell32, "SHGetImageList"):
        return None                      # XP 时代的系统没有这个导出
    try:
        iid = _GUID()
        ctypes.oledll.ole32.CLSIDFromString(IID_IIMAGE_LIST, ctypes.byref(iid))
        image_list = ctypes.c_void_p()
        if shell32.SHGetImageList(shil, ctypes.byref(iid),
                                  ctypes.byref(image_list)) != 0 or not image_list:
            return None
    except Exception:
        return None

    try:
        vtbl = ctypes.cast(image_list,
                           ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_icon = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_uint,
                                      ctypes.POINTER(ctypes.c_void_p))(vtbl[10])
        hicon = ctypes.c_void_p()
        if get_icon(image_list, int(index), ILD_TRANSPARENT,
                    ctypes.byref(hicon)) != 0 or not hicon:
            return None
        return _hicon_to_raw(int(hicon.value))
    except Exception:
        return None
    finally:
        # IImageList 是引用计数的，取完图标必须 Release，否则每次调用都漏一个
        try:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
            release(image_list)
        except Exception:
            pass


def _jumbo_icon(path: Path) -> "RawIcon | None":
    """取某个条目的 256×256 原图；拿不到返回 None（调用方会退回老路径）。"""
    if not IS_WINDOWS or not path.exists():
        return None
    index = _system_icon_index(path)
    if index is None:
        return None
    return _image_list_icon(index, SHIL_JUMBO)


# --------------------------------------------------------------------------
# 缓存
# --------------------------------------------------------------------------
def cache_dir() -> Path:
    folder = Path(__file__).resolve().parent / _CACHE_DIR_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(os.environ.get("TEMP", ".")) / "DesktopNestIcons"
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def icon_key(path: Path, size: int) -> str:
    """缓存键：路径 + 修改时间 + 大小，文件换了图标会自动失效。"""
    try:
        stat = path.stat()
        stamp = f"{int(stat.st_mtime)}-{stat.st_size}"
    except OSError:
        stamp = "missing"
    raw = f"{os.path.normcase(str(path))}|{stamp}|{size}|v1"
    return hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()[:20]


_MEMORY: "dict[str, RawIcon]" = {}
_PNG_OK = True


def _try_load_png(key: str) -> "RawIcon | None":
    global _PNG_OK
    if not _PNG_OK:
        return None
    try:
        from PIL import Image
    except ImportError:
        _PNG_OK = False
        return None
    target = cache_dir() / f"{key}.png"
    if not target.exists():
        return None
    try:
        with Image.open(target) as img:
            img = img.convert("RGBA")
            width, height = img.size
            # Pillow 给的是 RGBA，Qt 的 ARGB32 在内存里是 BGRA
            data = bytearray(img.tobytes())
            data[0::4], data[2::4] = data[2::4], data[0::4]
        return RawIcon(width, height, bytes(data), key)
    except Exception:
        return None


def _save_png(raw: RawIcon) -> None:
    global _PNG_OK
    if not _PNG_OK or not raw.is_valid():
        return
    try:
        from PIL import Image
    except ImportError:
        _PNG_OK = False
        return
    try:
        data = bytearray(raw.bgra)
        data[0::4], data[2::4] = data[2::4], data[0::4]
        img = Image.frombytes("RGBA", (raw.width, raw.height), bytes(data))
        img.save(cache_dir() / f"{raw.key}.png", "PNG", optimize=True)
    except Exception:
        pass


def get_icon(path: "Path | str", size: int = 32,
             exe_hint: "Path | None" = None) -> "RawIcon | None":
    """
    取图标（带内存缓存 + PNG 磁盘缓存）。

    exe_hint：当 path 是 .lnk 时，传它指向的 exe 可以拿到更清晰的大图标。
    """
    path = Path(path)
    key = icon_key(path, size)
    cached = _MEMORY.get(key)
    if cached is not None:
        return cached
    on_disk = _try_load_png(key)
    if on_disk is not None:
        _MEMORY[key] = on_disk
        return on_disk

    raw: "RawIcon | None" = None
    if path.is_dir():
        raw = _shell_icon(path, size)
    else:
        if exe_hint is not None and size >= 32:
            raw = _extract_exe_icon(exe_hint, size)
        if raw is None:
            raw = _shell_icon(path, size)
        if raw is None and exe_hint is not None:
            raw = _shell_icon(exe_hint, size)

    if raw is None or not raw.is_valid():
        return None
    raw = RawIcon(raw.width, raw.height, raw.bgra, key)
    _MEMORY[key] = raw
    _save_png(raw)
    return raw


def get_icon_best(path: "Path | str", size: int = 32,
                  exe_hint: "Path | None" = None) -> "RawIcon | None":
    """取**尽可能清晰**的图标：优先 256×256 的 jumbo 原图。

    为什么需要它（"菜单栏图标清晰度太低"的根因）：
    `SHGetFileInfoW` 只有两档——`SHGFI_LARGEICON` 顶天 **32×32**，
    `SHGFI_SMALLICON` 是 16×16；`PrivateExtractIconW` 当兜底时也常常只给 32×32。
    菜单栏图标要显示 44 / 52 甚至更大，等于把 32×32 硬拉大，自然一片糊。

    这里换成 `SHGetImageList(SHIL_JUMBO)` 拿 **256×256**，
    再让 Qt 平滑缩到显示尺寸（`QIcon` 内部用 `SmoothTransformation`）。
    缩放这一步交给 Qt 还有个好处：高 DPI 下按物理像素请求也照样清晰。

    拿不到 jumbo（老系统 / 条目不存在）时**静默退回** `get_icon`，
    行为跟改动前完全一致，不会因为新路径失败而没图标。
    """
    path = Path(path)
    key = icon_key(path, JUMBO_SIZE)
    cached = _MEMORY.get(key)
    if cached is not None:
        return cached
    on_disk = _try_load_png(key)
    if on_disk is not None:
        _MEMORY[key] = on_disk
        return on_disk

    raw = _jumbo_icon(path)
    if raw is None and exe_hint is not None:
        raw = _jumbo_icon(Path(exe_hint))
    if raw is None or not raw.is_valid() or raw.width < 32:
        return get_icon(path, size, exe_hint)

    raw = RawIcon(raw.width, raw.height, raw.bgra, key)
    _MEMORY[key] = raw
    _save_png(raw)
    return raw


def clear_cache() -> int:
    """清掉磁盘缓存，返回删除的文件数。"""
    removed = 0
    _MEMORY.clear()
    try:
        for f in cache_dir().glob("*.png"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def prune_cache(max_files: int = 600) -> int:
    """缓存文件太多时，按最久未使用清掉一批。"""
    try:
        files = sorted(cache_dir().glob("*.png"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return 0
    if len(files) <= max_files:
        return 0
    removed = 0
    for f in files[: len(files) - max_files]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            continue
    return removed


if __name__ == "__main__":
    import sys as _sys

    targets = [Path(p) for p in _sys.argv[1:]] or [Path(_sys.executable)]
    for target in targets:
        started = time.time()
        icon = get_icon(target, 32)
        cost = (time.time() - started) * 1000
        if icon:
            print(f"  {target.name:<40} 32px 档 {icon.width}x{icon.height} "
                  f"{len(icon.bgra)} bytes  {cost:.0f}ms")
        else:
            print(f"  {target.name:<40} 32px 档 取图标失败  {cost:.0f}ms")
        started = time.time()
        best = get_icon_best(target, 44)
        cost = (time.time() - started) * 1000
        if best:
            print(f"  {'':<40} 高清档 {best.width}x{best.height} "
                  f"{len(best.bgra)} bytes  {cost:.0f}ms")
        else:
            print(f"  {'':<40} 高清档 取图标失败  {cost:.0f}ms")
