#!/usr/bin/env python3
"""Review-gated merge of frozen knowledge partitions into canonical records."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from knowledge_partitions import CANDIDATES, PARTITIONS, PartitionError, _rows, _write_rows, _digest
from session_storage import locked, safe_path

MERGES = "knowledge-base/_ops/knowledge-merges.jsonl"
CANONICAL = "knowledge-base/_ops/canonical-knowledge.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_partitions(root: Path, ids: list[str]) -> list[dict]:
    rows = {row.get("partition_id"): row for row in _rows(root, PARTITIONS)}
    result = []
    for partition_id in ids:
        row = rows.get(partition_id)
        if not row:
            raise PartitionError("partition_missing")
        if row.get("state") != "frozen":
            raise PartitionError("partition_not_frozen")
        result.append(row)
    return result


def plan_merge(root: Path, *, partition_ids: list[str], expected_revisions: dict[str, int] | None = None) -> dict:
    if not partition_ids or len(set(partition_ids)) != len(partition_ids):
        raise PartitionError("merge_partitions_required")
    partitions = _load_partitions(root, partition_ids)
    expected_revisions = expected_revisions or {p["partition_id"]: p["revision"] for p in partitions}
    if any(expected_revisions.get(p["partition_id"]) != p["revision"] for p in partitions):
        raise PartitionError("partition_revision_conflict")
    candidates = [row for row in _rows(root, CANDIDATES) if row.get("partition_id") in set(partition_ids)]
    conflicts = []
    seen = {}
    for candidate in candidates:
        key = (candidate.get("claim_key"), json.dumps(candidate.get("conditions", {}), sort_keys=True))
        value = json.dumps(candidate.get("value"), sort_keys=True)
        if key in seen and seen[key][0] != value:
            conflicts.append({"claim_key": candidate.get("claim_key"), "candidate_ids": [seen[key][1], candidate["candidate_id"]]})
        else:
            seen[key] = (value, candidate["candidate_id"])
    plan = {"schema_version": 1, "record_type": "KnowledgeMergePlan", "merge_id": "KMERGE-" + _digest([partition_ids, expected_revisions, [c.get("candidate_id") for c in candidates]])[:24],
            "partition_ids": partition_ids, "expected_revisions": expected_revisions,
            "candidate_ids": [c.get("candidate_id") for c in candidates], "conflicts": conflicts,
            "status": "conflict" if conflicts else "proposed", "created_at": _now()}
    plan["plan_sha256"] = _digest(plan)
    return plan


def apply_merge(root: Path, *, plan: dict, approval: dict) -> dict:
    if plan.get("status") != "proposed":
        raise PartitionError("merge_not_approved_for_plan")
    if approval.get("status") not in {"accepted", "verified"} or approval.get("merge_plan_sha256") != plan.get("plan_sha256"):
        raise PartitionError("approval_not_bound")
    partitions = _load_partitions(root, list(plan["partition_ids"]))
    if any(p.get("revision") != plan["expected_revisions"].get(p["partition_id"]) for p in partitions):
        raise PartitionError("partition_revision_conflict")
    candidates = [row for row in _rows(root, CANDIDATES) if row.get("candidate_id") in set(plan["candidate_ids"])]
    canonical = _rows(root, CANONICAL)
    existing = {row.get("canonical_id") for row in canonical}
    added = []
    for candidate in candidates:
        canonical_id = "KREC-" + _digest([candidate["candidate_id"], plan["merge_id"]])[:24]
        if canonical_id in existing:
            continue
        partition = next(p for p in partitions if p["partition_id"] == candidate["partition_id"])
        row = {"schema_version": 1, "record_type": "CanonicalKnowledgeRecord", "canonical_id": canonical_id,
               "claim_key": candidate["claim_key"], "value": candidate["value"], "conditions": candidate.get("conditions", {}),
               "source_refs": candidate["source_refs"], "locator": candidate.get("locator"),
               "rights_status": candidate.get("rights_status", "unverified"), "status": "accepted",
               "provenance": {"partition_id": partition["partition_id"], "session_id": partition["session_id"],
                              "agent_instance_id": partition["agent_instance_id"], "role": partition["role"],
                              "merge_id": plan["merge_id"], "approval": approval.get("approval_id")},
               "created_at": _now()}
        row["canonical_sha256"] = _digest(row)
        canonical.append(row)
        added.append(canonical_id)
    _write_rows(root, CANONICAL, canonical)
    merges = _rows(root, MERGES)
    receipt = {"schema_version": 1, "record_type": "KnowledgeMergeReceipt", "merge_id": plan["merge_id"],
               "plan_sha256": plan["plan_sha256"], "approval_id": approval.get("approval_id"),
               "partition_ids": plan["partition_ids"], "canonical_ids": added, "status": "applied", "created_at": _now()}
    merges.append(receipt)
    _write_rows(root, MERGES, merges)
    return receipt


def query_canonical(root: Path, *, allowed_partition_ids: set[str]) -> list[dict]:
    if not allowed_partition_ids:
        raise PartitionError("partition_scope_required")
    return [row for row in _rows(root, CANONICAL)
            if row.get("provenance", {}).get("partition_id") in allowed_partition_ids]
