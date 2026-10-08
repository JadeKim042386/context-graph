#!/usr/bin/env python3
"""Explicit, review-gated promotion of session pointers into project memory."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import update_memory as memory_api


MAX_BYTES = 32 * 1024
MAX_ITEMS = 16
MAX_OPERATIONS = 2
RECEIPT_DIR = Path("knowledge-base/_ops/promotion-receipts")


class PromotionError(ValueError):
    def __init__(self, reason: str, exit_code: int = 2):
        self.reason = reason
        self.exit_code = exit_code
        super().__init__(reason)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path, *, limit: int = MAX_BYTES) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) > limit:
        raise PromotionError("input_too_large")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError("invalid_json") from exc
    if not isinstance(data, dict):
        raise PromotionError("object_required")
    return data, raw


def project_path(root: Path, pointer: str) -> Path:
    path, anchor = memory_api.local_path(root, pointer)
    if anchor:
        raise PromotionError("fragment_not_allowed_for_record_file")
    if path.is_symlink():
        raise PromotionError("symlink_path")
    return path


def strict_request(request: dict[str, Any]) -> None:
    required = {
        "schema_version", "record_type", "transaction_id", "project_id", "created_at",
        "event_refs", "canonical_refs", "memory_pointer", "expected_memory_sha256",
        "operations", "status",
    }
    if set(request) - required or not required <= set(request):
        raise PromotionError("request_keys")
    if request["schema_version"] != 1 or request["record_type"] != "SessionPromotionRequest":
        raise PromotionError("request_type")
    if request["status"] != "proposed" or not all(isinstance(request.get(k), str) and request[k] for k in ("transaction_id", "project_id", "created_at", "memory_pointer")):
        raise PromotionError("request_header")
    digest = request["expected_memory_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise PromotionError("expected_memory_hash")
    for key in ("event_refs", "canonical_refs", "operations"):
        if not isinstance(request[key], list) or len(request[key]) > (MAX_OPERATIONS if key == "operations" else MAX_ITEMS):
            raise PromotionError(f"{key}_limit")
    if not request["operations"]:
        raise PromotionError("operations_empty")
    for ref in request["event_refs"] + request["canonical_refs"]:
        if not isinstance(ref, dict) or not isinstance(ref.get("pointer"), str) or not isinstance(ref.get("sha256"), str):
            raise PromotionError("reference_shape")
        if len(ref["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in ref["sha256"]):
            raise PromotionError("reference_hash")
    for operation in request["operations"]:
        if not isinstance(operation, dict) or operation.get("kind") not in {"goal", "snapshot"}:
            raise PromotionError("operation_shape")
        if operation["kind"] == "goal" and operation.get("status") not in {"verified", "accepted", "open", "blocked", "complete", "proposed"}:
            raise PromotionError("goal_status")
        if operation["kind"] == "snapshot" and not isinstance(operation.get("source"), str):
            raise PromotionError("snapshot_source")


def verify_request(root: Path, request: dict[str, Any], request_hash: str, approval: Path, approval_hash: str) -> tuple[Path, bytes, dict[str, Any]]:
    strict_request(request)
    if sha256_bytes(canonical(request)) != request_hash:
        raise PromotionError("request_revision_changed")
    memory = project_path(root, request["memory_pointer"])
    if not memory.exists():
        raise PromotionError("memory_missing")
    memory_bytes = memory.read_bytes()
    if sha256_bytes(memory_bytes) != request["expected_memory_sha256"]:
        raise PromotionError("base_conflict", 3)
    if approval.is_symlink() or not approval.is_file():
        raise PromotionError("approval_path")
    approval_bytes = approval.read_bytes()
    if sha256_bytes(approval_bytes) != approval_hash:
        raise PromotionError("approval_revision_changed")
    try:
        proof = json.loads(approval_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError("approval_invalid") from exc
    if not isinstance(proof, dict):
        raise PromotionError("approval_invalid")
    for ref in request["event_refs"] + request["canonical_refs"]:
        target = project_path(root, ref["pointer"])
        if not target.exists() or sha256_bytes(target.read_bytes()) != ref["sha256"]:
            raise PromotionError("target_revision_changed")
    for operation in request["operations"]:
        status = operation.get("status", "verified")
        target_pointer = operation.get("pointer", operation.get("source"))
        target_hash = operation.get("hash", operation.get("sha256"))
        if target_pointer and target_hash:
            memory_api.checked_bytes(root, target_pointer, target_hash, {memory})
            memory_api.checked_review(root, target_pointer, target_hash, status, operation.get("review_pointer"), {memory}, operation.get("review_sha256"))
    # The approval must bind the exact request, not merely a target artifact.
    if proof.get("promotion_request_sha256") != request_hash or (proof.get("record_type"), proof.get("status")) not in {("Decision", "accepted"), ("Review", "verified")}:
        raise PromotionError("approval_not_bound")
    return memory, memory_bytes, proof


def receipt(root: Path, request: dict[str, Any], request_pointer: str, request_hash: str, approval: Path, approval_hash: str, phase: str, expected: str, intended: str | None, observed: str | None, reason: str) -> Path:
    data: dict[str, Any] = {
        "schema_version": 1, "record_type": "PromotionReceipt", "transaction_id": request["transaction_id"],
        "project_id": request["project_id"], "phase": phase,
        "request_ref": {"pointer": request_pointer, "sha256": request_hash},
        "approval_ref": {"pointer": str(approval.relative_to(root)), "sha256": approval_hash},
        "expected_memory_sha256": expected, "intended_memory_sha256": intended,
        "observed_memory_sha256": observed, "created_at": datetime.now(timezone.utc).isoformat(),
        "previous_receipt_ref": None, "reason": reason, "authority_basis": "project_review_record",
    }
    data["receipt_sha256"] = sha256_bytes(canonical(data))
    directory = root / RECEIPT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{request['transaction_id']}.{phase}.json"
    payload = canonical(data)
    if path.exists():
        if path.read_bytes() != payload:
            raise PromotionError("receipt_identity_conflict", 3)
        return path
    memory_api.atomic_write(path, data)
    return path


def next_memory(root: Path, memory_bytes: bytes, request: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(memory_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError("memory_invalid") from exc
    if not isinstance(data, dict):
        raise PromotionError("memory_invalid")
    now = datetime.now(timezone.utc).isoformat()
    for operation in request["operations"]:
        if operation["kind"] == "goal":
            goal = {"pointer": operation["pointer"], "status": operation["status"], "updated_at": now}
            if operation.get("hash"):
                goal.update(revision_sha256=operation["hash"], review_pointer=operation.get("review_pointer"), review_sha256=operation.get("review_sha256"))
            data["current_goal"] = goal
        else:
            data["snapshot_hash"] = {"algorithm": "sha256", "value": operation["sha256"], "status": "verified", "updated_at": now, "source": operation["source"], "review_pointer": operation.get("review_pointer"), "review_sha256": operation.get("review_sha256")}
    return data


def locked(path: Path):
    class Lock:
        def __enter__(self):
            self.handle = path.open("a+")
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
            return self
        def __exit__(self, *_):
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
    return Lock()


def command(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    request, request_raw = read_json(args.request)
    request_hash = sha256_bytes(request_raw)
    if request_hash != sha256_bytes(canonical(request)):
        raise PromotionError("request_not_canonical")
    request_path = args.request.resolve()
    if request_path.is_symlink() or not request_path.is_relative_to(root):
        raise PromotionError("request_path")
    approval = args.approval.resolve()
    if approval.is_symlink() or not approval.is_relative_to(root):
        raise PromotionError("approval_path")
    approval_hash = args.approval_sha256
    memory, memory_bytes, _ = verify_request(root, request, args.request_sha256, approval, approval_hash)
    if args.mode == "check":
        print(json.dumps({"ok": True, "changed": False, "status": "validated", "transaction_id": request["transaction_id"]}))
        return 0
    with locked(memory.with_name(memory.name + ".lock")):
        current = memory.read_bytes()
        if sha256_bytes(current) != request["expected_memory_sha256"]:
            raise PromotionError("base_conflict", 3)
        data = next_memory(root, current, request)
        intended = sha256_bytes(canonical(data))
        prepared = receipt(root, request, str(request_path.relative_to(root)), args.request_sha256, approval, approval_hash, "prepared", request["expected_memory_sha256"], intended, sha256_bytes(current), "ready")
        memory_api.atomic_write(memory, data)
        committed = receipt(root, request, str(request_path.relative_to(root)), args.request_sha256, approval, approval_hash, "committed", request["expected_memory_sha256"], intended, sha256_bytes(memory.read_bytes()), "applied")
    print(json.dumps({"ok": True, "changed": True, "status": "applied", "transaction_id": request["transaction_id"], "prepared_receipt": str(prepared.relative_to(root)), "committed_receipt": str(committed.relative_to(root))}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("check", "apply"):
        p = sub.add_parser(mode)
        p.add_argument("--root", type=Path, default=Path.cwd())
        p.add_argument("--request", type=Path, required=True)
        p.add_argument("--request-sha256", required=True)
        p.add_argument("--approval", type=Path, required=True)
        p.add_argument("--approval-sha256", required=True)
        p.set_defaults(func=command)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PromotionError as exc:
        print(json.dumps({"ok": False, "status": "conflict" if exc.exit_code == 3 else "unverified", "reason": exc.reason}), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
