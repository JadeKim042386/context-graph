#!/usr/bin/env python3
"""Lifecycle for role-scoped knowledge partitions.

This store is deliberately separate from session event/checkpoint storage.  It
holds proposed knowledge candidates, freezes them at lifecycle boundaries, and
is consumed by merge_knowledge.py after review.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from session_storage import atomic_write, locked, read_jsonl, safe_path

PARTITIONS = "knowledge-base/_ops/knowledge-partitions.jsonl"
CANDIDATES = "knowledge-base/_ops/knowledge-candidates.jsonl"


class PartitionError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _write_rows(root: Path, relative: str, rows: list[dict]) -> None:
    raw = b"".join((json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n").encode() for row in rows)
    atomic_write(safe_path(root, relative), raw)


def _rows(root: Path, relative: str) -> list[dict]:
    return read_jsonl(safe_path(root, relative))


def _partition(root: Path, partition_id: str) -> dict:
    for row in _rows(root, PARTITIONS):
        if row.get("partition_id") == partition_id:
            return row
    raise PartitionError("partition_missing")


def open_partition(root: Path, *, project_id: str, session_id: str, agent_instance_id: str,
                   role: str, scope_ids: list[str], task_id: str | None = None,
                   assignment_id: str | None = None) -> dict:
    if not all(isinstance(value, str) and value for value in (project_id, session_id, agent_instance_id, role)):
        raise PartitionError("partition_identity")
    if not isinstance(scope_ids, list) or not all(isinstance(value, str) and value for value in scope_ids):
        raise PartitionError("partition_scope")
    identity = [project_id, session_id, agent_instance_id, task_id, assignment_id, role]
    partition_id = "KPART-" + _digest(identity)[:24]
    rows = _rows(root, PARTITIONS)
    existing = next((row for row in rows if row.get("partition_id") == partition_id), None)
    if existing:
        return dict(existing, status="duplicate")
    row = {"schema_version": 1, "record_type": "KnowledgePartition", "partition_id": partition_id,
           "project_id": project_id, "session_id": session_id, "agent_instance_id": agent_instance_id,
           "task_id": task_id, "assignment_id": assignment_id, "role": role, "scope_ids": sorted(set(scope_ids)),
           "state": "open", "revision": 1, "candidate_ids": [], "created_at": _now()}
    row["partition_sha256"] = _digest(row)
    rows.append(row)
    _write_rows(root, PARTITIONS, rows)
    return dict(row, status="opened")


def put_candidate(root: Path, *, partition_id: str, candidate_id: str, claim_key: str,
                  value: object, source_refs: list[dict], conditions: dict | None = None,
                  rights_status: str = "unverified", locator: dict | None = None) -> dict:
    partition = _partition(root, partition_id)
    if partition.get("state") != "open":
        raise PartitionError("partition_frozen")
    if not isinstance(source_refs, list) or not source_refs:
        raise PartitionError("source_refs_required")
    if not isinstance(claim_key, str) or not claim_key:
        raise PartitionError("claim_key_required")
    rows = _rows(root, CANDIDATES)
    existing = next((row for row in rows if row.get("candidate_id") == candidate_id), None)
    if existing:
        if existing.get("partition_id") != partition_id or existing.get("candidate_sha256") != _digest(existing | {"candidate_sha256": None}):
            return dict(existing, status="duplicate")
        return dict(existing, status="duplicate")
    row = {"schema_version": 1, "record_type": "KnowledgeCandidate", "candidate_id": candidate_id,
           "partition_id": partition_id, "partition_revision": partition["revision"], "claim_key": claim_key,
           "value": value, "conditions": conditions or {}, "source_refs": source_refs,
           "locator": locator, "rights_status": rights_status, "status": "proposed", "created_at": _now()}
    row["candidate_sha256"] = _digest(row)
    rows.append(row)
    _write_rows(root, CANDIDATES, rows)
    partitions = _rows(root, PARTITIONS)
    for item in partitions:
        if item.get("partition_id") == partition_id:
            item["candidate_ids"] = sorted(set(item.get("candidate_ids", [])) | {candidate_id})
            item["revision"] += 1
            item["partition_sha256"] = _digest(item)
    _write_rows(root, PARTITIONS, partitions)
    return dict(row, status="proposed")


def freeze_partition(root: Path, *, partition_id: str, reason: str) -> dict:
    if not isinstance(reason, str) or not reason:
        raise PartitionError("freeze_reason_required")
    rows = _rows(root, PARTITIONS)
    for row in rows:
        if row.get("partition_id") == partition_id:
            if row.get("state") == "frozen":
                return dict(row, status="duplicate")
            row["state"] = "frozen"
            row["frozen_at"] = _now()
            row["freeze_reason"] = reason
            row["revision"] += 1
            row["partition_sha256"] = _digest(row)
            _write_rows(root, PARTITIONS, rows)
            return dict(row, status="frozen")
    raise PartitionError("partition_missing")


def close_session(root: Path, *, session_id: str, reason: str = "session_closed") -> dict:
    rows = _rows(root, PARTITIONS)
    frozen = []
    for row in rows:
        if row.get("session_id") == session_id and row.get("state") == "open":
            row["state"] = "frozen"
            row["frozen_at"] = _now()
            row["freeze_reason"] = reason
            row["revision"] += 1
            row["partition_sha256"] = _digest(row)
            frozen.append(row["partition_id"])
    _write_rows(root, PARTITIONS, rows)
    return {"status": "closed", "session_id": session_id, "frozen_partition_ids": frozen}


def list_candidates(root: Path, *, partition_ids: set[str] | None = None) -> list[dict]:
    rows = _rows(root, CANDIDATES)
    if partition_ids is None:
        return rows
    return [row for row in rows if row.get("partition_id") in partition_ids]


def query_partition_knowledge(root: Path, *, partition_ids: set[str]) -> list[dict]:
    """Return only candidates belonging to explicitly authorized partitions."""
    if not partition_ids:
        raise PartitionError("partition_scope_required")
    return list_candidates(root, partition_ids=partition_ids)


def main() -> int:
    raise SystemExit("use the explicit Python API; lifecycle writes require a trusted caller")


if __name__ == "__main__":
    main()
