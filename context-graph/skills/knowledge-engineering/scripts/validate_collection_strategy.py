#!/usr/bin/env python3
"""Dependency-free structural validator for collection strategy artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath


STAGES = {
    "plan",
    "discover",
    "verify_identity_rights",
    "acquire",
    "extract_normalize",
    "deduplicate_review",
    "project_measure",
}
GAIN_FIELDS = {
    "identity_verified",
    "rights_verified",
    "body_verified",
    "locator_replayed",
    "independent_evidence",
    "coverage_cells_closed",
}
DECISION_STATES = {"continue", "completed", "partial", "blocked"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    pass


def require_keys(value, keys, label):
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    missing = sorted(set(keys) - set(value))
    if missing:
        raise ContractError(f"{label} missing keys: {', '.join(missing)}")


def non_negative_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{label} must be a non-negative integer")


def checkpoint_digest(checkpoint):
    payload = json.dumps(
        checkpoint,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_project_relative_path(value, label, allow_null):
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a project-relative path")
    if (
        value.startswith(("/", "~"))
        or re.match(r"^[A-Za-z]:", value)
        or "\\" in value
        or "$" in value
        or re.search(r"%[A-Za-z_][A-Za-z0-9_]*%", value)
        or "://" in value
        or any(part == ".." for part in PurePosixPath(value).parts)
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ContractError(f"{label} must be a host-neutral project-relative POSIX path")


def validate_checkpoint(checkpoint, label, allow_empty_batch):
    required = {
        "last_completed_batch_id",
        "resume_stage",
        "query_cursor",
        "remaining_query_families",
        "candidate_snapshot_sha256",
        "unresolved",
    }
    require_keys(checkpoint, required, label)
    batch_id = checkpoint["last_completed_batch_id"]
    if not allow_empty_batch and not isinstance(batch_id, str):
        raise ContractError(f"{label}.last_completed_batch_id must be a string")
    if checkpoint["resume_stage"] is not None and checkpoint["resume_stage"] not in STAGES:
        raise ContractError(f"{label}.resume_stage is invalid")
    if not isinstance(checkpoint["remaining_query_families"], list):
        raise ContractError(f"{label}.remaining_query_families must be an array")
    snapshot = checkpoint["candidate_snapshot_sha256"]
    if snapshot is not None and not (isinstance(snapshot, str) and SHA256.fullmatch(snapshot)):
        raise ContractError(f"{label}.candidate_snapshot_sha256 must be SHA-256 or null")
    if not isinstance(checkpoint["unresolved"], list):
        raise ContractError(f"{label}.unresolved must be an array")


def validate_artifact(data):
    top_keys = {
        "schema_version",
        "artifact_type",
        "plan_id",
        "revision",
        "mode",
        "inputs",
        "outputs",
        "authorized_stages",
        "batches",
        "checkpoint",
        "decision",
        "metrics",
        "validation",
    }
    require_keys(data, top_keys, "artifact")
    if data["schema_version"] != "1.0" or data["artifact_type"] != "CollectionStrategy":
        raise ContractError("unsupported schema_version or artifact_type")
    if data["mode"] not in {"strategy_only", "execution"}:
        raise ContractError("mode must be strategy_only or execution")

    inputs = data["inputs"]
    require_keys(inputs, {"budgets", "stop_rules"}, "inputs")
    budgets = inputs["budgets"]
    budget_fields = {"max_batches", "max_items", "max_requests", "max_bytes", "max_elapsed_seconds"}
    require_keys(budgets, budget_fields, "inputs.budgets")
    for field in budget_fields:
        non_negative_integer(budgets[field], f"inputs.budgets.{field}")

    stop_rules = inputs["stop_rules"]
    require_keys(stop_rules, {"saturation_batches", "material_gain_fields", "safety_halts"}, "inputs.stop_rules")
    non_negative_integer(stop_rules["saturation_batches"], "inputs.stop_rules.saturation_batches")
    if stop_rules["saturation_batches"] < 2:
        raise ContractError("saturation_batches must be at least 2")
    gain_fields = stop_rules["material_gain_fields"]
    if not isinstance(gain_fields, list) or not gain_fields or len(gain_fields) != len(set(gain_fields)):
        raise ContractError("material_gain_fields must be a non-empty unique array")
    if not set(gain_fields) <= GAIN_FIELDS:
        raise ContractError("material_gain_fields contains an unsupported field")

    stages = data["authorized_stages"]
    if not isinstance(stages, list) or not stages or len(stages) != len(set(stages)) or not set(stages) <= STAGES:
        raise ContractError("authorized_stages is invalid")
    batches = data["batches"]
    if not isinstance(batches, list):
        raise ContractError("batches must be an array")

    outputs = data["outputs"]
    require_keys(outputs, {"plan_path", "catalog_path", "checkpoint_path", "metrics_path", "report_path"}, "outputs")
    validate_project_relative_path(outputs["plan_path"], "outputs.plan_path", allow_null=False)
    validate_project_relative_path(outputs["report_path"], "outputs.report_path", allow_null=False)
    for field in ("catalog_path", "checkpoint_path", "metrics_path"):
        validate_project_relative_path(outputs[field], f"outputs.{field}", allow_null=True)
    if data["mode"] == "strategy_only":
        if stages != ["plan"] or batches:
            raise ContractError("strategy_only must authorize only plan and contain no batches")
        if any(outputs[field] is not None for field in ("catalog_path", "checkpoint_path", "metrics_path")):
            raise ContractError("strategy_only acquisition outputs must be null")
        if any(budgets[field] != 0 for field in budget_fields):
            raise ContractError("strategy_only budgets must all be zero")

    seen_batch_ids = set()
    for index, batch in enumerate(batches):
        label = f"batches[{index}]"
        require_keys(batch, {"batch_id", "status", "input_count", "metrics_delta", "checkpoint", "checkpoint_digest", "errors"}, label)
        if batch["batch_id"] in seen_batch_ids:
            raise ContractError("batch_id values must be unique and append-only")
        seen_batch_ids.add(batch["batch_id"])
        non_negative_integer(batch["input_count"], f"{label}.input_count")
        delta = batch["metrics_delta"]
        require_keys(delta, gain_fields, f"{label}.metrics_delta")
        for field in gain_fields:
            non_negative_integer(delta[field], f"{label}.metrics_delta.{field}")
        validate_checkpoint(batch["checkpoint"], f"{label}.checkpoint", allow_empty_batch=False)
        if batch["checkpoint"]["last_completed_batch_id"] != batch["batch_id"]:
            raise ContractError(f"{label}.checkpoint must advance to its batch_id")
        if checkpoint_digest(batch["checkpoint"]) != batch["checkpoint_digest"]:
            raise ContractError(f"{label}.checkpoint_digest does not match canonical checkpoint JSON")

    validate_checkpoint(data["checkpoint"], "checkpoint", allow_empty_batch=True)
    if batches and data["checkpoint"] != batches[-1]["checkpoint"]:
        raise ContractError("top-level checkpoint must equal the last batch checkpoint")
    if not batches and data["checkpoint"]["last_completed_batch_id"] is not None:
        raise ContractError("empty batch history requires a null last_completed_batch_id")

    decision = data["decision"]
    require_keys(decision, {"state", "reason", "resume_required"}, "decision")
    if decision["state"] not in DECISION_STATES or not isinstance(decision["resume_required"], bool):
        raise ContractError("decision state or resume_required is invalid")
    if decision["state"] in {"partial", "blocked"} and decision["resume_required"]:
        if data["checkpoint"]["resume_stage"] is None or not data["checkpoint"]["unresolved"]:
            raise ContractError("resumable partial/blocked decision requires resume_stage and unresolved items")

    trailing_non_improving = 0
    for batch in reversed(batches):
        if all(batch["metrics_delta"][field] == 0 for field in gain_fields):
            trailing_non_improving += 1
        else:
            break
    if trailing_non_improving >= stop_rules["saturation_batches"] and decision["state"] == "continue":
        raise ContractError("saturation reached after consecutive non-improving batches; decision cannot continue")

    metrics = data["metrics"]
    require_keys(metrics, {"denominators", "counts"}, "metrics")
    denominators = metrics["denominators"]
    counts = metrics["counts"]
    denominator_fields = {"required_candidates", "required_coverage_cells", "locator_eligible"}
    count_fields = {
        "discovered", "identity_verified", "revision_verified", "body_verified",
        "rights_verified", "locator_replayed", "independent_sources",
        "exact_duplicates", "near_duplicate_groups", "conflicts", "abstentions",
        "failures", "coverage_cells_met",
    }
    require_keys(denominators, denominator_fields, "metrics.denominators")
    require_keys(counts, count_fields, "metrics.counts")
    for field in denominator_fields:
        non_negative_integer(denominators[field], f"metrics.denominators.{field}")
    for field in count_fields:
        non_negative_integer(counts[field], f"metrics.counts.{field}")
    if counts["coverage_cells_met"] > denominators["required_coverage_cells"]:
        raise ContractError("coverage_cells_met exceeds required_coverage_cells")
    if counts["locator_replayed"] > denominators["locator_eligible"]:
        raise ContractError("locator_replayed exceeds locator_eligible")
    for field in ("revision_verified", "body_verified", "rights_verified", "independent_sources"):
        if counts[field] > counts["identity_verified"]:
            raise ContractError(f"{field} exceeds identity_verified")
    if counts["identity_verified"] > counts["discovered"]:
        raise ContractError("identity_verified exceeds discovered")

    validation = data["validation"]
    require_keys(validation, {"status", "checks"}, "validation")
    if validation["status"] not in {"passed", "failed", "unverified"}:
        raise ContractError("validation.status is invalid")
    if not isinstance(validation["checks"], list):
        raise ContractError("validation.checks must be an array")
    check_statuses = []
    for index, check in enumerate(validation["checks"]):
        require_keys(check, {"name", "status", "evidence"}, f"validation.checks[{index}]")
        if check["status"] not in {"passed", "failed", "unverified"}:
            raise ContractError(f"validation.checks[{index}].status is invalid")
        check_statuses.append(check["status"])
    if validation["status"] == "passed" and any(status != "passed" for status in check_statuses):
        raise ContractError("validation cannot pass when a check is failed or unverified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.artifact.read_text(encoding="utf-8"))
        validate_artifact(data)
    except (OSError, json.JSONDecodeError, ContractError) as error:
        print(f"COLLECTION_STRATEGY_INVALID: {error}", file=sys.stderr)
        return 1
    print(f"COLLECTION_STRATEGY_OK: {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
