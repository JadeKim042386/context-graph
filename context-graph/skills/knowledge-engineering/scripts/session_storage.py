"""Bounded local I/O for provisional records; no canonical writes."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
MAX_ITEMS = 5000


def safe_path(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('unsafe_path')
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError('unsafe_path')
    return path


def read_jsonl(path, *, max_items=MAX_ITEMS, max_bytes=MAX_BYTES):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('unsafe_path')
    if not path.exists():
        return []
    if path.stat().st_size > max_bytes:
        raise ValueError('overlay_full')
    rows = []
    try:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                if not line.strip():
                    continue
                if len(line.encode()) > 65536:
                    raise ValueError('overlay_invalid')
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('overlay_invalid')
                rows.append(row)
                if len(rows) > max_items:
                    raise ValueError('overlay_full')
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('overlay_invalid') from exc
    return rows


def atomic_write(path, raw, *, max_bytes=MAX_BYTES):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('unsafe_path')
    if len(raw) > max_bytes:
        raise ValueError('projection_full')
    if path.exists() and path.read_bytes() == raw:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


@contextmanager
def locked(root, name='session-knowledge'):
    path = safe_path(root, 'knowledge-base/_ops/' + name + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
