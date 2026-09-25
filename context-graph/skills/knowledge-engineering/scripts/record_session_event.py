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
from fnmatch import fnmatch

try:
    import fcntl
except ImportError:  # pragma: no cover - the package also ships to non-POSIX hosts
    fcntl = None


SCHEMA_VERSION = 2
PRIVACY_FILTER_VERSION = "session-event-v2"
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


def config_path(root: Path) -> Path:
    return root / "knowledge-base" / "_ops" / "session-capture.json"


def load_config(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(config_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) and value.get("enabled") is True else {}


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


def changed_paths(root: Path, config: dict[str, Any]) -> list[str]:
    candidates = run_git(root, "diff", "--name-only") + run_git(root, "diff", "--cached", "--name-only")
    safe: list[str] = []
    for value in candidates:
        path = value.replace("\\", "/")
        if path.startswith("/") or ".." in Path(path).parts or path.startswith("."):
            continue
        includes = config.get("include_globs", ["knowledge/**", "design/**"])
        if UNSAFE_PATH.search(path) or path in safe or not any(fnmatch(path, pattern) for pattern in includes):
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
                item["hash_state"] = "captured"
            else:
                item["sha256"] = None
                item["hash_state"] = "unverified"
        except OSError:
            item["sha256"] = None
            item["hash_state"] = "unverified"
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


ALLOWED_TRIGGERS = {"startup", "resume", "clear", "prompt_input_exit", "manual", "auto", "unknown"}


def make_record(root: Path, event_type: str, payload: dict[str, Any], records: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    raw_session = scalar(payload.get("session_id")) or "missing-session"
    session_key = digest(raw_session)[:24]
    trigger = scalar(payload.get("reason")) or scalar(payload.get("trigger")) or "unknown"
    if trigger not in ALLOWED_TRIGGERS:
        trigger = "unknown"
    invocation_id = scalar(payload.get("invocation_id"))
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    event_key = "|".join((digest(str(root))[:24], session_key, event_type, trigger, invocation_id or occurred_at))
    event_id = "SEV-" + digest(event_key)[:32]
    session_records = [item for item in records if item.get("session_id") == session_key]
    related = session_records[-1].get("event_id") if session_records else None
    sequence = len(session_records) + 1
    status = "provisional"
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "SessionLifecycleEvent",
        "event_id": event_id,
        "session_id": session_key,
        "event_type": event_type,
        "sequence": sequence,
        "occurred_at": occurred_at,
        "runtime": scalar(payload.get("runtime")) or "claude",
        "status": status,
        "trigger": trigger,
        "project_id": config.get("project_id", "PRJ-" + digest(str(root))[:16]),
        "artifact_pointers": artifact_pointers(root, changed_paths(root, config)),
        "working_tree_digest": working_tree_digest(root),
        "review_state": "not_reviewed",
        "supersedes_event_id": related,
        "privacy_filter_version": PRIVACY_FILTER_VERSION,
        "knowledge_state": "provisional",
        "content_fingerprint": digest(json.dumps({"event_type": event_type, "session_id": session_key, "artifacts": changed_paths(root, config)}, sort_keys=True)),
        "producer": {"name": "context-graph", "version": "0.6.0"},
    }
    if event_type == "session_end":
        record["termination_reason"] = trigger
    return record


def init_project(root: Path, runtime: str, includes: list[str]) -> int:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "enabled": True,
        "project_id": "PRJ-" + digest(str(root))[:16],
        "journal_path": "knowledge-base/_ops/session-events.jsonl",
        "proposal_dir": "knowledge-base/_ops/session-proposals",
        "runtime": runtime,
        "include_globs": includes or ["knowledge/**", "design/**"],
        "tracked_paths_only": True,
        "capture_content": False,
        "capture_commands": False,
        "capture_untracked": False,
        "max_artifacts": MAX_ARTIFACTS,
        "max_file_hash_bytes": MAX_FILE_HASH_BYTES,
    }
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return 0


def record_project(root: Path, event_type: str, payload: dict[str, Any], compile_proposal: bool) -> int:
    config = load_config(root)
    if not config:
        return 0
    event_path = root / "knowledge-base" / "_ops" / "session-events.jsonl"
    records = load_records(event_path)
    append_locked(event_path, make_record(root, event_type, payload, records, config))
    if compile_proposal:
        from build_session_proposal import write_outputs
        write_outputs(root)
    return 0


def main() -> int:
    # Explicit route has strict errors and never inherits host environment roots.
    # Keep the legacy best-effort hook interface separate and unchanged.
    if len(sys.argv) > 1 and sys.argv[1] == "capture":
        sys.dont_write_bytecode = True
        from session_events import MAX_INPUT, capture, encode
        explicit = argparse.ArgumentParser(description="Explicit project-bound provisional capture")
        explicit.add_argument("--root", type=Path, required=True)
        explicit.add_argument("--runtime", choices=("codex", "claude-code"), required=True)
        explicit.add_argument("--event", choices=("pre_compact", "post_compact", "session_end"), required=True)
        args = explicit.parse_args(sys.argv[2:])
        result = capture(args.root, args.event, args.runtime, sys.stdin.buffer.read(MAX_INPUT + 1))
        sys.stdout.write(encode(result).decode())
        return 2 if result["status"] == "unverified" else 0
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--root", type=Path, default=None)
    init_parser.add_argument("--runtime", default="claude-code")
    init_parser.add_argument("--include", action="append", default=[])
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--root", type=Path, default=None)
    record_parser.add_argument("--runtime", default="claude-code")
    record_parser.add_argument("--event", required=True, choices=("session_start", "pre_compact", "post_compact", "session_end"))
    record_parser.add_argument("--compile-proposal", action="store_true")
    parser.add_argument("--event", choices=("session_start", "pre_compact", "post_compact", "session_end"))
    args = parser.parse_args()
    try:
        root = (getattr(args, "root", None) or root_path()).resolve()
        if args.command == "init":
            return init_project(root, args.runtime, args.include)
        event_type = getattr(args, "event", None)
        if args.command == "record" or event_type:
            return record_project(root, event_type, read_input(), getattr(args, "compile_proposal", False))
        return 0
    except Exception:
        # Recording must never block compaction or application exit.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
