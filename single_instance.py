#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单实例守卫
==========
需求：「在同一台电脑上不能出现多个收纳软件进程」。

为什么必须挡住第二个进程，而不是"两个一起跑也行"：
本程序启动时会 `auto_take_desktop()`（把桌面上的东西收进收纳目录）、
退出时会 `restore_desktop_on_exit()`（再放回去）。两个进程同时干这件事，
就是两边抢同一批文件——轻则图标重复、重则搬一半卡住，
而且两个托盘图标、两条菜单栏会一起浮在屏幕上，用户根本分不清点哪个。

两道闸
------
1. **命名互斥体**（Windows `CreateMutexW`）——权威判据。
   互斥体是**内核对象**，进程一结束（哪怕是被任务管理器强杀、蓝屏重启前）
   操作系统立刻回收，所以永远不会留下"假锁"。这比"锁文件 + PID 探活"
   可靠得多：锁文件在崩溃后会残留，而残留的 PID 还可能被别的进程复用。
2. **本地套接字**（`QLocalServer` / `QLocalSocket`）——只用来**叫醒**
   已经在跑的那个实例："用户又点了一次，把面板亮出来"。
   拿不到 QtNetwork 就降级成"只拦不叫醒"，不影响第 1 条。

名字里带用户名
--------------
`Global\\` 前缀让互斥体跨会话可见（同一个人开了两个远程桌面会话时，
第二个也该被挡住）。但名字里**带上当前用户名**：
不同 Windows 用户各有各的桌面，各跑一份是正常的，
不能因为"另一个用户在用"就把自己锁在门外。

用法
----
    guard = SingleInstance()
    if not guard.try_acquire():
        guard.send_to_running("show")     # 叫醒已经在跑的那个
        return 0                          # 自己安静退出
    guard.on_message = handle_command     # 第一个实例：收到消息后亮面板
"""

from __future__ import annotations

import os
import time

# --------------------------------------------------------------------------
# 可选依赖：QtNetwork 只是"叫醒"用的，缺了也能跑
# --------------------------------------------------------------------------
_QLocalServer = None
_QLocalSocket = None
_QT_NETWORK_ERROR = ""

try:
    from PyQt6.QtNetwork import QLocalServer as _QLocalServer  # noqa: N813
    from PyQt6.QtNetwork import QLocalSocket as _QLocalSocket  # noqa: N813
except Exception as exc:  # pragma: no cover - 环境相关
    _QT_NETWORK_ERROR = f"{type(exc).__name__}: {exc}"
    try:
        from PySide6.QtNetwork import QLocalServer as _QLocalServer  # type: ignore  # noqa: N813
        from PySide6.QtNetwork import QLocalSocket as _QLocalSocket  # type: ignore  # noqa: N813
        _QT_NETWORK_ERROR = ""
    except Exception as exc2:  # pragma: no cover - 环境相关
        _QT_NETWORK_ERROR = f"{_QT_NETWORK_ERROR} / {type(exc2).__name__}: {exc2}"


# --------------------------------------------------------------------------
# 名字
# --------------------------------------------------------------------------
BASE_KEY = "DesktopNest.SingleInstance.v1"
ERROR_ALREADY_EXISTS = 183


def _user_slug() -> str:
    """当前 Windows 用户名（取不到就退回进程 uid）。

    为什么名字里要带用户：桌面是**每个用户一份**的。不同用户各跑一份
    完全正常，带上用户名才不会互相挡住。
    """
    for getter in (lambda: os.environ.get("USERNAME"),
                   lambda: os.environ.get("USER"),
                   lambda: getattr(os, "getlogin", lambda: None)()):
        try:
            value = getter()
        except Exception:
            value = None
        if value:
            # 用户名可能带空格 / 点 / 反斜杠（域账号 DOMAIN\\user），
            # 统一换成一个安全的短串，避免互斥体名字非法。
            safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                           for ch in str(value))
            if safe:
                return safe[:64]
    return f"uid{getattr(os, 'getuid', lambda: 0)()}"


_USER = _user_slug()
MUTEX_NAME = f"Global\\{BASE_KEY}.{_USER}"
SOCKET_NAME = f"{BASE_KEY}.{_USER}"

_IS_WINDOWS = os.name == "nt"

_APP_INSTANCE_CACHE = []

_PROBE_RESULT: "bool | None" = None


def _probe_local_socket() -> bool:
    """本机到底能不能建本地套接字（结果缓存）。

    受限环境（DSH 沙盒、某些加固过的企业策略）里 `QLocalServer.listen()`
    会直接失败并报 `QLocalServerPrivate::addListener: 拒绝访问`。
    这时"叫醒"通道不可用 —— 但那是**环境限制**，不是代码坏了：
    互斥体（权威判据）照样工作，第二个实例仍会被挡住。

    所以调用方（尤其测试）需要能区分这两种情况，而不是把环境问题
    误判成功能缺陷。探测只做一次，建完立刻关掉。
    """
    global _PROBE_RESULT
    if _PROBE_RESULT is not None:
        return _PROBE_RESULT
    if _QLocalServer is None:
        _PROBE_RESULT = False
        return False
    name = f"{SOCKET_NAME}.probe"
    try:
        _QLocalServer.removeServer(name)
        server = _QLocalServer()
        _PROBE_RESULT = bool(server.listen(name))
        server.close()
        _QLocalServer.removeServer(name)
    except Exception:
        _PROBE_RESULT = False
    return _PROBE_RESULT


def _app_instance():
    """当前的 QCoreApplication（没有就返回 None）。

    `send_to_running` 要 pump 事件循环把缓冲区的字节推出去，
    而在 `run()` 里这一步发生在 `app.exec()` **之前**，所以得自己拿 app。
    """
    if _APP_INSTANCE_CACHE:
        return _APP_INSTANCE_CACHE[0]
    found = None
    for module_name in ("PyQt6.QtCore", "PySide6.QtCore"):
        try:
            module = __import__(module_name, fromlist=["QCoreApplication"])
            found = module.QCoreApplication.instance()
            break
        except Exception:
            continue
    _APP_INSTANCE_CACHE.append(found)
    return found


# --------------------------------------------------------------------------
# Windows 命名互斥体
# --------------------------------------------------------------------------
_KERNEL32 = None


def _kernel32():
    """拿一个 `use_last_error=True` 的 kernel32。

    ⚠️ 必须**复用同一个对象**，而且必须 `use_last_error=True`：
    `GetLastError()` 是**线程全局**状态，不这么设的话 ctypes 不会在调用
    之后立刻把它存下来，中间任何一次 Python 层的分配都可能把它冲掉，
    读到的就是别的错误码（实测会稳定读到 0，于是"已经有实例在跑"
    永远判断不出来）。
    """
    global _KERNEL32
    if _KERNEL32 is None and _IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            lib = ctypes.WinDLL("kernel32", use_last_error=True)
            lib.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                         wintypes.LPCWSTR]
            lib.CreateMutexW.restype = ctypes.c_void_p
            lib.CloseHandle.argtypes = [ctypes.c_void_p]
            lib.CloseHandle.restype = wintypes.BOOL
            _KERNEL32 = lib
        except Exception:
            _KERNEL32 = False
    return _KERNEL32 or None


def _create_mutex(name: str) -> "tuple[int | None, int]":
    """建一个命名互斥体。返回 `(句柄, GetLastError)`。

    句柄为 None 表示根本没建出来（极端情况）；句柄有效但错误码是
    `ERROR_ALREADY_EXISTS` 表示**这个名字已经被别人占着**了。
    """
    lib = _kernel32()
    if lib is None:
        return None, 0
    try:
        import ctypes

        handle = lib.CreateMutexW(None, False, name)
        error = int(ctypes.get_last_error())      # 必须紧跟调用，中间别插东西
        if not handle:
            return None, error
        return int(handle), error
    except Exception:
        return None, 0


def _close_handle(handle: int) -> None:
    lib = _kernel32()
    if lib is None:
        return
    try:
        import ctypes

        lib.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass


# --------------------------------------------------------------------------
# 守卫本体
# --------------------------------------------------------------------------
class SingleInstance:
    """一次进程生命周期里只该有一个的"锁"。"""

    def __init__(self, mutex_name: "str | None" = None,
                 socket_name: "str | None" = None):
        # ⚠️ 名字必须**在这儿现取**，不能写成
        # `def __init__(self, mutex_name: str = MUTEX_NAME, ...)`。
        # Python 的默认参数是在**函数定义那一刻**求值的，之后改模块里的
        # `MUTEX_NAME` 对它毫无影响 —— 测试想换个不冲突的探测名字就会失效
        # （表现为"明明改了名字，拿到的还是生产的那把锁"）。
        self._mutex_name = MUTEX_NAME if mutex_name is None else mutex_name
        self._socket_name = SOCKET_NAME if socket_name is None else socket_name
        self._mutex = None
        self._server = None
        self._held = False
        # 收到别的实例发来的命令时回调（只给"第一个实例"用）
        self.on_message = None

    # ---- 取锁 ----
    def try_acquire(self) -> bool:
        """试着成为唯一实例。成功 True；已经有别人在跑 False。"""
        if _IS_WINDOWS:
            handle, error = _create_mutex(self._mutex_name)
            if handle is not None:
                if error == ERROR_ALREADY_EXISTS:
                    # 已经有人占着这个名字 → 我们不是唯一实例
                    _close_handle(handle)
                    return False
                self._mutex = handle
                self._held = True
                # 顺带把本地套接字开起来，好让后来的实例能叫醒我们。
                # 开不起来也无所谓（只是少一个"叫醒"能力），不影响拦不拦。
                self._start_server()
                return True
            # 互斥体建不出来（权限异常之类的极端情况）：下面用套接字兜底
        return self._start_server()

    def _start_server(self) -> bool:
        """开本地套接字。开得成就说明没有别人占着这个名字。"""
        if _QLocalServer is None:
            # 连 IPC 能力都没有：不拦。宁可多开一个，也别让用户完全打不开。
            self._held = True
            return True
        server = _QLocalServer()
        if not server.listen(self._socket_name):
            # 可能是上一次崩溃留下的僵尸套接字（Unix 上是文件）。
            # ⚠️ 只在这里 removeServer：一上来就 remove 会把**正在运行**
            # 那个实例的名字抢走，第二个进程反而能挤进来。
            server.removeServer(self._socket_name)
            if not server.listen(self._socket_name):
                return False
        server.newConnection.connect(self._on_connection)
        self._server = server
        self._held = True
        return True

    # ---- 叫醒已经在跑的那个 ----
    def send_to_running(self, command: str = "show",
                        timeout_ms: int = 800) -> bool:
        """给正在运行的实例捎一句话。送不到返回 False（调用方自行提示用户）。"""
        if _QLocalSocket is None:
            return False
        socket = None
        try:
            socket = _QLocalSocket()
            socket.connectToServer(self._socket_name)
            if not socket.waitForConnected(timeout_ms):
                return False
            socket.write(command.encode("utf-8"))
            socket.flush()
            # ⚠️ 这里**不能**写完就 disconnect。QLocalSocket 的写是带缓冲的，
            # 而在命名管道上 `waitForBytesWritten()` 实测直接返回 False，
            # 紧接着 `disconnectFromServer()` 会把还没出缓冲区的数据一起丢掉——
            # 现象就是"第二个实例明明发了消息，第一个却毫无反应"。
            # 所以要一直 pump 事件循环，直到 `bytesToWrite()` 归零。
            deadline = time.monotonic() + timeout_ms / 1000.0
            app = _app_instance()
            while socket.bytesToWrite() > 0 and time.monotonic() < deadline:
                if app is not None:
                    app.processEvents()
                else:
                    socket.waitForBytesWritten(20)
                time.sleep(0.005)
            delivered = socket.bytesToWrite() == 0
            socket.disconnectFromServer()
            return delivered
        except Exception:
            return False
        finally:
            if socket is not None:
                try:
                    socket.abort()
                except Exception:
                    pass

    # ---- 作为"第一个实例"接收消息 ----
    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                break
            conn.readyRead.connect(lambda c=conn: self._read_message(c))
            conn.disconnected.connect(conn.deleteLater)
            # 消息可能在我们接上信号之前就已经到齐了，补一次读，
            # 否则这条连接会静静地烂掉（readyRead 不会再发第二次）。
            if conn.bytesAvailable():
                self._read_message(conn)

    def _read_message(self, conn) -> None:
        try:
            payload = bytes(conn.readAll()).decode("utf-8", "replace").strip()
        except Exception:
            payload = ""
        if payload and self.on_message is not None:
            try:
                self.on_message(payload)
            except Exception:
                pass

    # ---- 收尾 ----
    @property
    def held(self) -> bool:
        return self._held

    def close(self) -> None:
        """释放。互斥体是内核对象，进程退出时系统本来也会回收；
        这里显式放掉，是为了"同一个进程里再建一个"时立刻能成功
        （测试里会这么用）。"""
        if self._server is not None:
            try:
                self._server.close()
                _QLocalServer.removeServer(self._socket_name)  # type: ignore[union-attr]
            except Exception:
                pass
            self._server = None
        if self._mutex is not None:
            _close_handle(self._mutex)
            self._mutex = None
        self._held = False

    def __enter__(self) -> "SingleInstance":
        self.try_acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def describe() -> str:
    """给自检 / 日志用的一句话。"""
    return (f"互斥体 {MUTEX_NAME} · 套接字 {SOCKET_NAME} · "
            + ("QtNetwork 可用" if _QLocalServer is not None
               else f"QtNetwork 不可用（{_QT_NETWORK_ERROR}）"))
