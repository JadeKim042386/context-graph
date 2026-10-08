#!/usr/bin/env python3
"""Fail-closed, read-only planner for reusing completed work across sessions.

This is deliberately an opt-in planning layer.  It never promotes knowledge,
executes a task, or treats a similarity match as evidence.  A trusted harness
must authorize the lookup before any candidate count or candidate content is
returned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from knowledge_harness import load_manifest  # noqa: E402
from role_access import AccessDenied, authorize, authorize_pointer  # noqa: E402

SCHEMA_VERSION = 1
RECEIPTS = "knowledge-base/_ops/work-reuse-receipts.jsonl"
HASH = set("0123456789abcdef")
MAX_BYTES = 1_048_576
REQUEST_KEYS = {"schema_version", "record_type", "project_id", "question_key", "scope", "as_of",
                "acceptance_contract", "artifacts", "rights_sha256", "review_sha256", "policy_sha256", "allow_skip"}


class ReuseError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _hash(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - HASH:
        raise ReuseError("invalid_hash")
    return value


def task_fingerprint(request: dict[str, Any]) -> str:
    """Fingerprint work identity, excluding session/agent and dependencies."""
    required = ("project_id", "question_key", "scope", "as_of", "acceptance_contract")
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS or request.get("schema_version") != SCHEMA_VERSION or request.get("record_type") != "TaskReuseRequest":
        raise ReuseError("invalid_request")
    contract = request["acceptance_contract"]
    if not isinstance(contract, dict) or set(contract) != {"id", "version"}:
        raise ReuseError("invalid_acceptance_contract")
    if (not all(isinstance(request[key], str) and 0 < len(request[key]) <= 160 for key in required[:3])
            or not isinstance(request.get("as_of"), str) or not 0 < len(request["as_of"]) <= 64
            or type(request.get("allow_skip")) is not bool):
        raise ReuseError("invalid_request")
    if (not isinstance(contract["id"], str) or not contract["id"] or len(contract["id"]) > 160
            or type(contract["version"]) is not int or contract["version"] < 1):
        raise ReuseError("invalid_acceptance_contract")
    for key in ("rights_sha256", "review_sha256", "policy_sha256"):
        values = request.get(key)
        if not isinstance(values, list) or len(values) > 32 or not all(isinstance(value, str) for value in values):
            raise ReuseError("invalid_evidence_metadata")
    return digest(["work-v1", request["project_id"], request["question_key"],
                   request["scope"], request["as_of"], contract["id"], contract["version"]])


def evidence_fingerprint(request: dict[str, Any]) -> str:
    artifacts = request.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
        raise ReuseError("invalid_artifacts")
    normalized = []
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "locator"}:
            raise ReuseError("invalid_artifact")
        if (not isinstance(item["path"], str) or not 0 < len(item["path"]) <= 480
                or not isinstance(item["locator"], str) or not 0 < len(item["locator"]) <= 160):
            raise ReuseError("invalid_artifact")
        normalized.append((item["path"], _hash(item["sha256"]), item["locator"]))
    def hashes(name):
        values = request.get(name, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ReuseError("invalid_evidence_metadata")
        return sorted(set(_hash(value) for value in values))
    return digest({"artifacts": sorted(normalized), "rights": hashes("rights_sha256"),
                   "reviews": hashes("review_sha256"),
                   "policy": hashes("policy_sha256")})


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or os.path.isabs(relative) or ".." in Path(relative).parts:
        raise ReuseError("unsafe_pointer")
    cursor = root
    for part in Path(relative).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ReuseError("unsafe_pointer")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ReuseError("unsafe_pointer")
    return path


def _read_hash(root: Path, relative: str) -> str:
    path = _safe_path(root, relative)
    if not path.is_file() or stat.S_ISLNK(path.stat().st_mode) or path.stat().st_size > MAX_BYTES:
        raise ReuseError("unlocatable_artifact")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locator_replays(root: Path, relative: str, locator: str) -> bool:
    if not isinstance(locator, str) or not locator:
        return False
    if locator.startswith("line:"):
        try:
            line = int(locator[5:])
        except ValueError:
            return False
        if line < 1:
            return False
        path = _safe_path(root, relative)
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return False
        return line <= len(path.read_text(encoding="utf-8").splitlines())
    # Unknown locator dialects are never treated as replayable by this v1 planner.
    return False


def _receipt_digest(record: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in record.items() if key != "receipt_sha256"}
    return digest(unsigned)


def _authorized_candidate(record: Any, harness: dict[str, Any]) -> bool:
    """Authorize all referenced pointers before any receipt classification."""
    if not isinstance(record, dict) or not isinstance(record.get("review_pointer"), str):
        return False
    artifacts = record.get("artifact_refs")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
        return False
    try:
        if not authorize_pointer(harness, record["review_pointer"]):
            return False
        return all(isinstance(item, dict) and isinstance(item.get("path"), str)
                   and authorize_pointer(harness, item["path"]) for item in artifacts)
    except (AccessDenied, TypeError):
        return False


def _valid_receipt(root: Path, record: Any, request: dict[str, Any], task: str, evidence: str, harness: dict[str, Any]) -> tuple[bool, str]:
    required = {"schema_version", "record_type", "receipt_id", "project_id", "task_fingerprint",
                "evidence_fingerprint", "outcome", "receipt_status", "artifact_refs", "review_pointer",
                "review_sha256", "acceptance_contract", "rights_sha256", "policy_sha256", "created_at",
                "receipt_sha256"}
    if (not isinstance(record, dict) or set(record) != required or record.get("schema_version") != SCHEMA_VERSION
            or record.get("record_type") != "TaskReuseReceipt"):
        return False, "invalid_receipt"
    if record.get("project_id") != request["project_id"] or record.get("task_fingerprint") != task:
        return False, "not_same_task"
    if record.get("outcome") not in {"reuse", "skip"} or record.get("receipt_status") != "accepted_artifact":
        return False, "not_accepted"
    if (not isinstance(record.get("receipt_id"), str) or not record["receipt_id"]
            or not isinstance(record.get("created_at"), str) or not record["created_at"]):
        return False, "invalid_receipt"
    if record.get("acceptance_contract") != request["acceptance_contract"]:
        return False, "acceptance_contract_changed"
    if record.get("receipt_sha256") != _receipt_digest(record):
        return False, "receipt_digest_mismatch"
    try:
        if not isinstance(record.get("review_pointer"), str) or not isinstance(record.get("review_sha256"), str):
            return False, "missing_review"
        artifacts = record.get("artifact_refs")
        if not isinstance(artifacts, list):
            return False, "artifact_set_mismatch"
        if not authorize_pointer(harness, record["review_pointer"]):
            return False, "review_not_authorized"
        for item in artifacts:
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "locator"}:
                return False, "invalid_artifact_ref"
            if not authorize_pointer(harness, item["path"]):
                return False, "artifact_not_authorized"
        if artifacts != request.get("artifacts"):
            record_paths = [item.get("path") for item in artifacts if isinstance(item, dict)]
            request_paths = [item.get("path") for item in request.get("artifacts", []) if isinstance(item, dict)]
            return False, "evidence_changed" if record_paths == request_paths else "artifact_set_mismatch"
        if record.get("rights_sha256") != sorted(set(request.get("rights_sha256", []))) or record.get("policy_sha256") != sorted(set(request.get("policy_sha256", []))):
            return False, "evidence_changed"
        # Do all authorization checks before returning evidence-change details.
        if _read_hash(root, record["review_pointer"]) != _hash(record["review_sha256"]):
            return False, "review_stale"
        review = json.loads(_safe_path(root, record["review_pointer"]).read_text(encoding="utf-8"))
        if (not isinstance(review, dict) or review.get("record_type") != "Review"
                or review.get("status") != "accepted" or review.get("completion_status") != "complete"
                or review.get("task_fingerprint") != task or review.get("evidence_fingerprint") != evidence
                or review.get("artifact_refs") != request.get("artifacts")):
            return False, "review_not_accepted"
        if record.get("evidence_fingerprint") != evidence:
            return False, "evidence_changed"
        for item in artifacts:
            if (not item["locator"] or not _locator_replays(root, item["path"], item["locator"])
                    or _read_hash(root, item["path"]) != _hash(item["sha256"])):
                return False, "artifact_stale"
    except (ReuseError, AccessDenied, OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return False, "unlocatable_or_unauthorized"
    return True, "validated"


def decide(request: dict[str, Any], receipts: list[dict[str, Any]], harness: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic decision; no semantic/LLM comparison is used."""
    task = task_fingerprint(request)
    evidence = evidence_fingerprint(request)
    if harness is None:
        return {"decision": "abstain", "reason": "harness_required", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": None}
    binding_project = harness.get("binding", {}).get("project_id")
    if binding_project != request.get("project_id"):
        return {"decision": "abstain", "reason": "project_binding_mismatch", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": None}
    candidates = []
    same_task_invalid = False
    evidence_changed = False
    denied_candidate = False
    conflicting_receipt = False
    visible_other_task = False
    seen_receipts = {}
    for raw in receipts:
        record = dict(raw) if isinstance(raw, dict) else raw
        if isinstance(record, dict) and record.get("project_id") != binding_project:
            continue
        if not _authorized_candidate(record, harness):
            denied_candidate = True
            continue
        if isinstance(record, dict):
            receipt_id = record.get("receipt_id")
            if isinstance(receipt_id, str) and receipt_id in seen_receipts:
                if seen_receipts[receipt_id] == record:
                    continue
                conflicting_receipt = True
                continue
            if isinstance(receipt_id, str):
                seen_receipts[receipt_id] = record
        valid, reason = _valid_receipt(harness["root"], record, request, task, evidence, harness)
        if valid:
            candidates.append(record)
        elif isinstance(record, dict) and record.get("task_fingerprint") == task:
            if reason in {"review_not_authorized", "artifact_not_authorized", "unlocatable_or_unauthorized"}:
                denied_candidate = True
                continue
            same_task_invalid = True
            evidence_changed |= reason == "evidence_changed"
        elif isinstance(record, dict) and record.get("project_id") == binding_project:
            visible_other_task = True
    if conflicting_receipt or len(candidates) > 1:
        return {"decision": "hold", "reason": "conflicting_receipts", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": len(candidates)}
    if candidates:
        decision = "skip" if request.get("allow_skip") is True else "reuse"
        return {"decision": decision, "reason": "validated_receipt", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": 1,
                "receipt_id": candidates[0].get("receipt_id")}
    if denied_candidate:
        return {"decision": "abstain", "reason": "candidate_not_authorized", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": None}
    if evidence_changed:
        return {"decision": "refresh", "reason": "evidence_changed", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": 0}
    if same_task_invalid:
        return {"decision": "hold", "reason": "receipt_not_reproducible", "task_fingerprint": task,
                "evidence_fingerprint": evidence, "candidate_count": 0}
    return {"decision": "branch" if visible_other_task else "hold",
            "reason": "task_changed" if visible_other_task else "no_valid_receipt",
            "task_fingerprint": task, "evidence_fingerprint": evidence,
            "candidate_count": 0}


def _load_receipts(root: Path) -> list[dict[str, Any]]:
    path = _safe_path(root, RECEIPTS)
    if not path.exists():
        return []
    if path.stat().st_size > MAX_BYTES:
        raise ReuseError("receipt_limit")
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--harness-manifest", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        harness = load_manifest(root, args.harness_manifest)
        authorize(harness, action="continuity")
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or request.get("schema_version") != SCHEMA_VERSION or request.get("record_type") != "TaskReuseRequest":
            raise ReuseError("invalid_request")
        result = decide(request, _load_receipts(root), harness)
    except (AccessDenied, ReuseError, OSError, ValueError, UnicodeError) as exc:
        # Do not disclose candidate existence when the trusted channel fails.
        print(json.dumps({"decision": "abstain", "reason": str(exc), "candidate_count": None}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
