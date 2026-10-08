"""Fixed local microbenchmark for the opt-in task reuse planner."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "skills/knowledge-engineering/scripts"
sys.path.insert(0, str(SCRIPT))
import plan_task_reuse as planner  # noqa: E402


def run(repetitions=30):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        request = {"schema_version": 1, "record_type": "TaskReuseRequest", "project_id": "p1",
                   "question_key": "q1", "scope": "knowledge", "as_of": "2026-10-08",
                   "acceptance_contract": {"id": "contract", "version": 1},
                   "artifacts": [{"path": "knowledge/out.json", "sha256": hashlib.sha256(b"stable\n").hexdigest(), "locator": "line:1"}],
                   "rights_sha256": [], "review_sha256": [], "policy_sha256": [], "allow_skip": False}
        (root / "knowledge").mkdir()
        (root / "knowledge/out.json").write_bytes(b"stable\n")
        (root / "knowledge/review.json").write_text(json.dumps({"record_type": "Review", "status": "accepted",
            "completion_status": "complete", "task_fingerprint": planner.task_fingerprint(request),
            "evidence_fingerprint": planner.evidence_fingerprint(request), "artifact_refs": request["artifacts"]}) + "\n", encoding="utf-8")
        (root / "knowledge/rejected.json").write_text('{"status":"rejected"}\n', encoding="utf-8")
        review_sha = hashlib.sha256((root / "knowledge/review.json").read_bytes()).hexdigest()
        harness = {"root": root, "policy": {"roles": {"s": {"scope_ids": ["k"]}, "a": {"scope_ids": ["k"]}}},
                   "binding": {"project_id": "p1", "task_scope_ids": ["k"], "assignment_scope_ids": ["k"]}, "session_role": "s", "agent_role": "a",
                   "catalog": {"artifacts": {"knowledge/out.json": {"scope_ids": ["k"]}, "knowledge/review.json": {"scope_ids": ["k"]}}}}
        receipt = {"schema_version": 1, "record_type": "TaskReuseReceipt", "receipt_id": "r1", "project_id": "p1",
                   "task_fingerprint": planner.task_fingerprint(request), "evidence_fingerprint": planner.evidence_fingerprint(request),
                   "outcome": "reuse", "receipt_status": "accepted_artifact", "artifact_refs": request["artifacts"],
                   "review_pointer": "knowledge/review.json", "review_sha256": review_sha,
                   "rights_sha256": [], "policy_sha256": [],
                   "acceptance_contract": request["acceptance_contract"], "rights_sha256": [], "policy_sha256": [],
                   "created_at": "2026-10-08T00:00:00Z", "receipt_sha256": "0" * 64}
        receipt["receipt_sha256"] = planner._receipt_digest(receipt)
        baseline = []
        improved = []
        negative = []
        false_reuse = 0
        permission_leaks = 0
        rejected = json.loads(json.dumps(receipt))
        rejected["review_pointer"] = "knowledge/rejected.json"
        rejected["review_sha256"] = hashlib.sha256((root / "knowledge/rejected.json").read_bytes()).hexdigest()
        rejected["receipt_sha256"] = planner._receipt_digest(rejected)
        harness["catalog"]["artifacts"]["knowledge/rejected.json"] = {"scope_ids": ["k"]}
        denied_harness = copy.deepcopy(harness)
        denied_harness["catalog"]["artifacts"]["knowledge/out.json"]["scope_ids"] = ["private"]
        for _ in range(repetitions):
            start = time.perf_counter_ns()
            json.loads(json.dumps(request, sort_keys=True))
            baseline.append((time.perf_counter_ns() - start) / 1_000_000)
            start = time.perf_counter_ns()
            valid = planner.decide(request, [receipt], harness)
            assert valid["decision"] == "reuse"
            improved.append((time.perf_counter_ns() - start) / 1_000_000)
            negative_start = time.perf_counter_ns()
            invalid = planner.decide(request, [rejected], harness)
            false_reuse += int(invalid["decision"] in {"reuse", "skip"})
            denied = planner.decide(request, [receipt], denied_harness)
            permission_leaks += int(denied["candidate_count"] is not None or denied["decision"] != "abstain")
            negative.append((time.perf_counter_ns() - negative_start) / 1_000_000)
        return {"repetitions": repetitions, "fixture": "synthetic-local", "baseline_ms_p50": statistics.median(baseline),
                "improved_ms_p50": statistics.median(improved), "baseline_ms_p95": sorted(baseline)[int(repetitions * .95) - 1],
                "improved_ms_p95": sorted(improved)[int(repetitions * .95) - 1], "reuse_decisions": repetitions,
                "negative_ms_p50": statistics.median(negative), "negative_ms_p95": sorted(negative)[int(repetitions * .95) - 1],
                "baseline_executor_units": repetitions, "improved_executor_units": 0,
                "duplicate_executions_avoided": repetitions, "false_skips": false_reuse,
                "permission_leaks": permission_leaks, "negative_cases": repetitions * 2,
                "executor_model": "one unit per valid task; local synthetic fixture"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.repetitions)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
