"""Small standard-library storage primitives shared by personal data writers."""
from contextlib import contextmanager
import errno
import json
import math
import os
from pathlib import Path
import tempfile
import time


@contextmanager
def file_lock(root, timeout=10.0):
    """Lock cooperating writers on the same filesystem, with a bounded wait.

    Keep the lock file in place: unlinking it could let two processes lock
    different inodes. All cooperating writers must use this same lock.
    This does not coordinate copies synchronized across machines or provide
    distributed synchronization; filesystem locking semantics still apply.
    """
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Lock timeout must be a finite, non-negative number")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".pm-grow.lock"
    with lock_path.open("a+b") as handle:
        # Windows byte-range locks need an existing byte at offset zero.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for data lock: {lock_path}") from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            release()


def atomic_write_json(path, value):
    """Replace one JSON file atomically; callers coordinate read/modify/write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".pm-grow-", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
