#!/usr/bin/env python3
"""Append a privacy-filtered Claude Code lifecycle event to the project journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - the package also ships to non-POSIX hosts
    fcntl = None


SCHEMA_VERSION = 1
PRIVACY_FILTER_VERSION = "session-event-v1"
MAX_ARTIFACTS = 100
MAX_FILE_HASH_BYTES = 20 * 1024 * 1024
UNSAFE_PATH = re.compile(r"(^|/)(\.env|.*(secret|token|credential|password|cookie|private|id_rsa).*)$", re.I)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scalar(value: Any, limit: int = 160) -> str | None:
    if not isinstance(value, (str, int, float, bool)):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def read_input() -> dict[str, Any]:
    try:
        value = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def root_path() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def run_git(root: Path, *args: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in result.stdout.splitlines() if line] if result.returncode == 0 else []


def changed_paths(root: Path) -> list[str]:
    candidates = run_git(root, "diff", "--name-only") + run_git(root, "diff", "--cached", "--name-only")
    safe: list[str] = []
    for value in candidates:
        path = value.replace("\\", "/")
        if path.startswith("/") or ".." in Path(path).parts or path.startswith("."):
            continue
        if UNSAFE_PATH.search(path) or path in safe:
            continue
        safe.append(path)
        if len(safe) >= MAX_ARTIFACTS:
            break
    return sorted(safe)


def artifact_pointers(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    pointers: list[dict[str, Any]] = []
    for relative in paths:
        path = root / relative
        item: dict[str, Any] = {"path": relative}
        try:
            if path.is_file() and path.stat().st_size <= MAX_FILE_HASH_BYTES:
                item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                item["state"] = "verified"
            else:
                item["sha256"] = None
                item["state"] = "unverified"
        except OSError:
            item["sha256"] = None
            item["state"] = "unverified"
        pointers.append(item)
    return pointers


def working_tree_digest(root: Path) -> str:
    return digest("\n".join(run_git(root, "status", "--porcelain=v1", "--untracked-files=no")))


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    except OSError:
        return []
    return records


def append_locked(path: Path, record: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing_ids = {
            item.get("event_id") for item in load_records(path) if isinstance(item.get("event_id"), str)
        }
        if record["event_id"] in existing_ids:
            return False
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return True


def make_record(root: Path, event_type: str, payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    raw_session = scalar(payload.get("session_id")) or "missing-session"
    session_key = digest(raw_session)[:24]
    trigger = scalar(payload.get("reason")) or scalar(payload.get("trigger")) or "unspecified"
    transcript_key = digest(scalar(payload.get("transcript_path")) or "missing-transcript")[:16]
    event_key = "|".join((digest(str(root))[:24], session_key, event_type, trigger, transcript_key))
    event_id = "SEV-" + digest(event_key)[:32]
    session_records = [item for item in records if item.get("session_id") == session_key]
    related = session_records[-1].get("event_id") if session_records else None
    sequence = len(session_records) + 1
    status = "provisional" if event_type in {"session_start", "pre_compact", "post_compact"} else "unverified"
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "session_id": session_key,
        "event_type": event_type,
        "sequence": sequence,
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime": scalar(payload.get("runtime")) or "claude",
        "status": status,
        "trigger": trigger,
        "artifact_pointers": artifact_pointers(root, changed_paths(root)),
        "working_tree_digest": working_tree_digest(root),
        "review_state": "not_reviewed",
        "supersedes_event_id": related,
        "privacy_filter_version": PRIVACY_FILTER_VERSION,
    }
    if event_type == "session_end":
        record["termination_reason"] = trigger
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, choices=("session_start", "pre_compact", "post_compact", "session_end"))
    args = parser.parse_args()
    root = root_path()
    event_path = root / "knowledge-base" / "_ops" / "session-events.jsonl"
    try:
        payload = read_input()
        records = load_records(event_path)
        append_locked(event_path, make_record(root, args.event, payload, records))
    except Exception:
        # Recording must never block compaction or application exit.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
