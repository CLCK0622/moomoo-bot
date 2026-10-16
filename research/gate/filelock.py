"""
filelock.py —— 共享门禁状态的跨进程互斥 + 原子落盘（工部 2026-07-30，都察院终审必修 2）

背景：`OOSBudget.consume()` 与 `TrialLedger.register_run()` 原本是**无锁的 read-modify-write**：
各自在进程内 load → 判定 → write。两个进程并发时判定基于各自的陈旧快照，双方都认为自己
"还有额度 / 还没登记"，于是：

  * OOS 单发预算：10 进程同刻 consume 同一 key → **10 个全部拿到票**（应为 1），落盘只记 1；
  * 试验台账：10 个 register_run 并发 → 仅 3 行落盘、1 行可解析，**9 条试验凭空消失**，
    且文件被交错写坏（后续任何 run 读它直接 JSONDecodeError）。

两者都往**放松**方向失效（OOS 多拿票 = 反复偷看样本外；漏记 N/V = DSR 的 haircut 变松），
和本线一路堵的 fail-open 同向。故此处提供：

  * `state_lock(path)`：以 `<path>.lock` 为锁文件的 `fcntl.flock` 排他锁（POSIX），
    进入后**必须重新从磁盘 load**，在锁内完成"加载-校验-写入"三步再释放；
  * `atomic_write_text(path, text)`：临时文件 + `os.replace` 原子替换，杜绝半截/交错文件。

注意：flock 是**建议锁**，只在都走本模块的进程间有效；跨 NFS 不保证。本仓的门禁状态都是本机
单目录文件，够用。
"""
from __future__ import annotations

import errno
import os
import tempfile
from contextlib import contextmanager
from typing import Iterator

try:
    import fcntl  # POSIX
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows 兜底
    _HAVE_FCNTL = False


@contextmanager
def state_lock(path: str, timeout: float = 30.0) -> Iterator[None]:
    """对 `path` 取跨进程排他锁（锁文件 = `<path>.lock`）。

    用法（**锁内必须重新 load**，否则仍是拿陈旧快照做判定）：

        with state_lock(self.path):
            self._load()          # 重新读盘
            ...校验...
            self._save_atomic()   # 原子写
    """
    if not path or not _HAVE_FCNTL:
        yield  # 无路径（纯内存）或无 fcntl：退化为无锁，行为同旧版
        return
    lock_path = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _acquire_blocking(fd, lock_path, timeout)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _acquire_blocking(fd: int, lock_path: str, timeout: float) -> None:
    """阻塞获取排他锁，超时抛错（避免死等把整条管线挂住）。"""
    import time
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as e:
            if e.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if time.time() >= deadline:
                raise TimeoutError(
                    f"取门禁状态锁超时（{timeout}s）：{lock_path}。"
                    "疑有进程持锁未释放；确认无僵死进程后再重试。")
            time.sleep(0.01)


def atomic_write_text(path: str, text: str) -> None:
    """原子写：同目录临时文件 + fsync + os.replace，避免读到半截/交错内容。"""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".swap")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # 同一文件系统内原子替换
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
