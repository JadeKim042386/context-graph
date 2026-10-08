#!/usr/bin/env python3
"""Merge provisional session knowledge into a provenance-preserving overlay.

The overlay is a project-wide view, not canonical memory.  It is reversible:
split() filters the same entries back by their hashed session/agent/task/
assignment/role selectors.  Canonical promotion remains review-gated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from session_storage import read_jsonl, atomic_write, locked, safe_path, MAX_BYTES

MAX_OVERLAY_ITEMS = 5000
MAX_OVERLAY_BYTES = MAX_BYTES

REGISTRY = "knowledge-base/_ops/session-agent-registry.jsonl"
OVERLAY = "knowledge-base/_ops/session-knowledge-overlay.jsonl"


def digest(project_id: str, kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    raw = json.dumps([kind, project_id, value], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def event_key(parts) -> str:
    raw = (json.dumps(parts, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def session_keys(project_id: str, raw_session: str) -> set[str]:
    """Accept the v3 and legacy lifecycle encodings without storing raw IDs."""
    return {event_key([project_id, raw_session]),
            hashlib.sha256(raw_session.encode()).hexdigest()[:24],
            digest(project_id, "session", raw_session)}


def selector_key(project_id: str, kind: str, value: str | None, task_key: str | None = None) -> str | None:
    if value is None:
        return None
    if kind == "agent":
        return event_key(["agent-instance-v1", project_id, value])
    if kind == "task":
        return event_key(["task-v1", project_id, value])
    if kind == "assignment":
        return event_key(["assignment-v1", project_id, task_key or selector_key(project_id, "task", value), value])
    if kind == "role":
        return event_key(["role-v1", project_id, value])
    return event_key([project_id, value])


def _append(path: Path, record: dict) -> None:
    rows = read_jsonl(path)
    if len(rows) >= MAX_OVERLAY_ITEMS:
        raise ValueError("overlay_full")
    old = path.read_bytes() if path.exists() else b""
    atomic_write(path, old + (json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n").encode(), max_bytes=MAX_OVERLAY_BYTES)


def _read(path: Path) -> list[dict]:
    return read_jsonl(path)


def _project_id(root: Path) -> str:
    from session_events import binding
    return binding(root)[2]


def _open_agent(root: Path, *, session_id: str, agent_instance_id: str | None = None,
               task_id: str | None = None, assignment_id: str | None = None,
               role: str | None = None, session_key: str | None = None) -> dict:
    project_id = _project_id(root)
    record = {"schema_version": 1, "record_type": "SessionAgentState", "state": "open",
              "project_id": project_id, "session_key": session_key or event_key([project_id, session_id]),
              "agent_key": selector_key(project_id, "agent", agent_instance_id),
              "task_key": selector_key(project_id, "task", task_id),
              "assignment_key": selector_key(project_id, "assignment", assignment_id, selector_key(project_id, "task", task_id)),
              "role_key": selector_key(project_id, "role", role), "role_present": role is not None,
              "session_keys": sorted(session_keys(project_id, session_id) | {session_key or event_key([project_id, session_id])})}
    record["state_id"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    states = _read(safe_path(root, REGISTRY))
    if any(item.get("state_id") == record["state_id"] for item in states):
        record["status"] = "duplicate"
        return record
    _append(safe_path(root, REGISTRY), record)
    record["status"] = "opened"
    return record


def _close_agent(root: Path, **selectors) -> dict:
    project_id = _project_id(root)
    session_id = selectors["session_id"]
    session_key = selectors.get("session_key") or event_key([project_id, session_id])
    record = {"schema_version": 1, "record_type": "SessionAgentState", "state": "closed",
              "project_id": project_id, "session_key": session_key,
              "agent_key": selector_key(project_id, "agent", selectors.get("agent_instance_id")),
              "task_key": selector_key(project_id, "task", selectors.get("task_id")),
              "assignment_key": selector_key(project_id, "assignment", selectors.get("assignment_id"), selector_key(project_id, "task", selectors.get("task_id"))),
              "role_key": selector_key(project_id, "role", selectors.get("role")),
              "role_present": selectors.get("role") is not None,
              "session_keys": sorted(session_keys(project_id, session_id) | {session_key})}
    record["state_id"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    if any(item.get("state_id") == record["state_id"] for item in _read(safe_path(root, REGISTRY))):
        record["status"] = "duplicate"
        return record
    _append(safe_path(root, REGISTRY), record)
    record["status"] = "closed"
    merged = _merge_session(root, session_key=record["session_key"], session_id=session_id)
    record["merged_count"] = merged["merged_count"]
    return record


def _source_events(root: Path) -> list[tuple[str, dict]]:
    found = []
    legacy = root / "knowledge-base" / "_ops" / "session-events.jsonl"
    for event in _read(legacy):
        found.append(("legacy", event))
    store = root / "knowledge-base" / "_ops" / "session-events-v3"
    if store.exists():
        for path in sorted(store.glob("SEV-*.json")):
            values = _read(path)
            if values:
                found.append(("explicit", values[0]))
    unique = {}
    for source, event in found:
        if event.get("record_type") == "SessionLifecycleEvent" and event.get("event_id"):
            unique.setdefault(event["event_id"], (source, event))
    return list(unique.values())


def _merge_session(root: Path, *, session_key: str | None = None, session_id: str | None = None,
                  rebuild_projection: bool = True) -> dict:
    root = Path(root).resolve()
    project_id = _project_id(root)
    from session_archive import recover, read_view
    prior = recover(root)
    known = {item.get("source_event_id") for item in read_view(root, include_archive=True)}
    states = [item for item in _read(safe_path(root, REGISTRY)) if item.get("state") in {"open", "closed"}]
    merged = []
    allowed_sessions = set()
    if session_key:
        allowed_sessions.add(session_key)
    if session_id:
        allowed_sessions.update(session_keys(project_id, session_id))
    for source, event in _source_events(root):
        event_session = event.get("session_id")
        if allowed_sessions and event_session not in allowed_sessions:
            continue
        if event.get("event_id") in known:
            continue
        attribution = event.get("attribution") or {}
        state = next((item for item in reversed(states)
                      if event_session in item.get("session_keys", [item.get("session_key")])
                      and bool(attribution) and (
                          item.get("agent_key") == attribution.get("agent_instance_id")
                          and item.get("task_key") == attribution.get("task_id")
                          and item.get("assignment_key") == attribution.get("assignment_id"))), {})
        item = {"schema_version": 1, "record_type": "SessionKnowledgeOverlay",
                "overlay_id": "SKO-" + hashlib.sha256((project_id + event["event_id"]).encode()).hexdigest(),
                "source_event_id": event["event_id"], "source_store": source,
                "source_pointer": ("knowledge-base/_ops/session-events-v3/" + event["event_id"] + ".json")
                if source == "explicit" else "knowledge-base/_ops/session-events.jsonl",
                "source_revision_sha256": event.get("record_sha256"),
                "session_key": event_session, "invocation_key": event.get("invocation_id"),
                "runtime": event.get("runtime"), "event_type": event.get("event_type"),
                "attribution": attribution or None, "content_fingerprint": event.get("content_fingerprint"),
                "artifact_pointers": event.get("artifact_pointers", []),
                "role_key": state.get("role_key"), "session_state": state.get("state", "unknown"),
                "promotion_state": "review_required", "status": "provisional"}
        merged.append(item)
    path = safe_path(root, OVERLAY)
    old = path.read_bytes() if path.exists() else b""
    pending = b"".join((json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n").encode() for item in merged)
    if len(prior) + len(merged) > MAX_OVERLAY_ITEMS or len(old) + len(pending) > MAX_OVERLAY_BYTES:
        return {"status": "overlay_full", "merged_count": 0, "canonical_promotion": "not_performed",
                "next_action": "review_archive_policy"}
    if merged:
        atomic_write(path, old + pending, max_bytes=MAX_OVERLAY_BYTES)
    from consolidate_knowledge import compact, plan
    consolidation = compact(root) if rebuild_projection else plan(root)
    return {"status": "merged", "merged_count": len(merged), "overlay": OVERLAY,
            "canonical_promotion": "not_performed", "consolidation": consolidation}


def open_agent(root: Path, **selectors) -> dict:
    with locked(root):
        return _open_agent(Path(root).resolve(), **selectors)


def close_agent(root: Path, **selectors) -> dict:
    with locked(root):
        return _close_agent(Path(root).resolve(), **selectors)


def merge_session(root: Path, **selectors) -> dict:
    with locked(root):
        return _merge_session(Path(root).resolve(), **selectors)


def rotate(root: Path) -> dict:
    from session_archive import rotate as archive_rotate
    with locked(root):
        _project_id(Path(root).resolve())
        return archive_rotate(root, _read(safe_path(root, REGISTRY)))


def split(root: Path, *, session_key=None, agent_key=None, task_key=None,
          assignment_key=None, role_key=None, include_archive=False) -> dict:
    selectors = {"session_key": session_key, "agent_key": agent_key, "task_key": task_key,
                "assignment_key": assignment_key, "role_key": role_key}
    items = []
    from session_archive import read_view
    for item in read_view(root, include_archive=include_archive):
        attribution = item.get("attribution") or {}
        candidates = {"session_key": item.get("session_key"), "agent_key": attribution.get("agent_instance_id"),
                     "task_key": attribution.get("task_id"), "assignment_key": attribution.get("assignment_id"),
                     "role_key": item.get("role_key")}
        if all(value is None or candidates.get(key) == value for key, value in selectors.items()):
            if "archive_segment_id" in item:
                item = dict(item, original_source_store=item["source_store"], source_store="archive")
            items.append(item)
    return {"schema_version": 1, "kind": "session_knowledge_split", "read_only": True,
            "promotion_performed": False, "items": items, "total_count": len(items),
            "selection": {key: value for key, value in selectors.items() if value is not None}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("open", "close"):
        p = sub.add_parser(command)
        p.add_argument("--session-id", required=True)
        p.add_argument("--agent-instance-id")
        p.add_argument("--task-id")
        p.add_argument("--assignment-id")
        p.add_argument("--role")
    p = sub.add_parser("merge")
    p.add_argument("--session-key")
    sub.add_parser("rotate")
    p = sub.add_parser("split")
    p.add_argument("--include-archive", action="store_true")
    for name in ("session-key", "agent-key", "task-key", "assignment-key", "role-key"):
        p.add_argument("--" + name)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "open":
        result = open_agent(root, session_id=args.session_id, agent_instance_id=args.agent_instance_id,
                            task_id=args.task_id, assignment_id=args.assignment_id, role=args.role)
    elif args.command == "close":
        result = close_agent(root, session_id=args.session_id, agent_instance_id=args.agent_instance_id,
                             task_id=args.task_id, assignment_id=args.assignment_id, role=args.role)
    elif args.command == "merge":
        result = merge_session(root, session_key=args.session_key)
    elif args.command == "rotate":
        result = rotate(root)
    else:
        result = split(root, include_archive=args.include_archive, session_key=args.session_key, agent_key=args.agent_key, task_key=args.task_key,
                       assignment_key=args.assignment_key, role_key=args.role_key)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
