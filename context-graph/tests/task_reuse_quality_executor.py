"""Deterministic, non-LLM executor used only by the sealed A/B quality benchmark."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "skills/knowledge-engineering/scripts"
sys.path.insert(0, str(SCRIPT))
import plan_task_reuse as planner  # noqa: E402


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(root, paths):
    return {"root": root, "policy": {"roles": {"session": {"scope_ids": ["knowledge"]}, "agent": {"scope_ids": ["knowledge"]}}},
            "binding": {"project_id": "quality-project", "task_scope_ids": ["knowledge"], "assignment_scope_ids": ["knowledge"]},
            "session_role": "session", "agent_role": "agent",
            "catalog": {"artifacts": {path: {"scope_ids": ["knowledge"]} for path in paths}}}


def _request(task, root):
    artifacts = []
    for path in task["source_paths"]:
        file = root / path
        artifacts.append({"path": path, "sha256": _sha(file), "locator": "line:1"})
    return {"schema_version": 1, "record_type": "TaskReuseRequest", "project_id": "quality-project",
            "question_key": task["task_id"], "scope": "knowledge", "as_of": "2026-10-09",
            "acceptance_contract": {"id": "quality-v1", "version": 1}, "artifacts": artifacts,
            "rights_sha256": [], "review_sha256": [], "policy_sha256": [], "allow_skip": False}


def _result(task, root, *, status=None, include_prior=False):
    if status is None:
        paths = list(task.get("current_paths", task["source_paths"]))
        if include_prior:
            paths += list(task.get("prior_paths", []))
        facts = [json.loads((root / path).read_text()) for path in paths]
        grouped = {}
        for fact in facts:
            grouped.setdefault(fact["key"], []).append(fact)
        conflicts = any(len({item["value"] for item in values}) > 1 for values in grouped.values())
        if conflicts:
            status = "conflict"
        elif task["kind"] == "permission_denied":
            status = "abstain"
        else:
            status = "complete"
    claims = []
    citations = []
    unresolved = []
    if status == "complete":
        paths = list(task.get("current_paths", task["source_paths"]))
        if include_prior:
            paths += list(task.get("prior_paths", []))
        for path in paths:
            fact = json.loads((root / path).read_text())
            claims.append({"key": fact["key"], "value": fact["value"], "unit": fact["unit"], "condition": fact["condition"]})
            citations.append({"path": path, "locator": "line:1"})
    elif status == "conflict":
        unresolved.append("conflicting_evidence")
    else:
        unresolved.append("insufficient_authority")
    return {"status": status, "claims": claims, "citations": citations, "unresolved": unresolved}


def _make_receipt(task, request, root, context, *, complete=True, old_hashes=None):
    task_fp = planner.task_fingerprint(request)
    artifacts = copy.deepcopy(request["artifacts"])
    if old_hashes:
        artifacts = [{**item, "sha256": old_hashes[item["path"]]} for item in artifacts]
    evidence_fp = planner.evidence_fingerprint({**request, "artifacts": artifacts})
    review_data = {"record_type": "Review", "status": "accepted" if complete else "proposed",
                   "completion_status": "complete" if complete else "open", "task_fingerprint": task_fp,
                   "evidence_fingerprint": evidence_fp, "artifact_refs": artifacts}
    review_path = root / f"reviews/{task['task_id']}.json"
    review_path.parent.mkdir(exist_ok=True)
    review_path.write_text(json.dumps(review_data, sort_keys=True) + "\n")
    review_ref = review_path.relative_to(root).as_posix()
    context["catalog"]["artifacts"][review_ref] = {"scope_ids": ["knowledge"]}
    receipt = {"schema_version": 1, "record_type": "TaskReuseReceipt", "receipt_id": f"r-{task['task_id']}",
               "project_id": request["project_id"], "task_fingerprint": task_fp, "evidence_fingerprint": evidence_fp,
               "outcome": "reuse", "receipt_status": "accepted_artifact", "artifact_refs": artifacts,
               "review_pointer": review_ref, "review_sha256": _sha(review_path),
               "acceptance_contract": request["acceptance_contract"], "rights_sha256": [], "policy_sha256": [],
               "created_at": "2026-10-09T00:00:00Z", "receipt_sha256": ""}
    receipt["receipt_sha256"] = planner._receipt_digest(receipt)
    return receipt


def build_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    tasks = []
    paths = []
    for index in range(30):
        kind = ("valid_reuse", "incomplete_prior", "changed_evidence", "conflict", "permission_denied", "no_prior")[index // 5]
        task_id = f"quality-{index:02d}"
        source_paths = [f"sources/{task_id}.json"]
        root.joinpath("sources").mkdir(exist_ok=True)
        fact = {"key": f"metric_{index}", "value": index, "unit": "count", "condition": "current"}
        root.joinpath(source_paths[0]).write_text(json.dumps(fact) + "\n")
        paths.extend(source_paths)
        if kind == "conflict":
            second = f"sources/{task_id}-conflict.json"
            root.joinpath(second).write_text(json.dumps({**fact, "value": index + 100}) + "\n")
            source_paths.append(second)
            paths.append(second)
        tasks.append({"task_id": task_id, "kind": kind, "source_paths": source_paths,
                      "current_paths": list(source_paths), "prior_paths": []})
    # The valid-reuse cases have a validated prior-session fact that is not in
    # the current routing packet. Both arms receive the same artifact set;
    # only the reuse arm is allowed to consume the prior result.
    for task in tasks[:5]:
        prior_path = f"sources/{task['task_id']}-prior.json"
        index = int(task["task_id"].split("-")[-1])
        root.joinpath(prior_path).write_text(json.dumps({"key": f"prior_metric_{index}", "value": index * 10,
                                                          "unit": "count", "condition": "prior"}) + "\n")
        task["prior_paths"] = [prior_path]
        task["source_paths"] = task["current_paths"] + task["prior_paths"]
        paths.append(prior_path)
    context = _context(root, paths)
    receipts = {}
    for task in tasks[:5]:
        request = _request(task, root)
        prior = _result(task, root, include_prior=True)
        prior_path = root / f"prior/{task['task_id']}.json"
        prior_path.parent.mkdir(exist_ok=True)
        prior_path.write_text(json.dumps(prior, sort_keys=True) + "\n")
        task["prior_path"] = prior_path.relative_to(root).as_posix()
        receipts[task["task_id"]] = [_make_receipt(task, request, root, context)]
    for task in tasks[5:10]:
        request = _request(task, root)
        receipts[task["task_id"]] = [_make_receipt(task, request, root, context, complete=False)]
    old_hashes = {}
    for task in tasks[10:15]:
        request = _request(task, root)
        old_hashes[task["source_paths"][0]] = "0" * 64
        receipts[task["task_id"]] = [_make_receipt(task, request, root, context, old_hashes=old_hashes)]
    for task in tasks[20:25]:
        context["catalog"]["artifacts"][task["source_paths"][0]] = {"scope_ids": ["private"]}
    for task in tasks:
        task["request"] = _request(task, root)
        task["receipts"] = receipts.get(task["task_id"], [])
    return tasks, context


def run_mode(tasks, context, root, mode):
    results, calls, read_bytes = {}, 0, 0
    for task in tasks:
        request = task["request"]
        if mode == "reuse":
            decision = planner.decide(request, task["receipts"], context)
        else:
            decision = {"decision": "execute"}
        if mode == "reuse" and decision["decision"] in {"reuse", "skip"}:
            prior_path = root / task["prior_path"]
            prior = json.loads(prior_path.read_text())
            # The evaluator independently verifies that the reused result is
            # still source-grounded before accepting it as a quality result.
            valid = all((root / citation["path"]).exists() for citation in prior.get("citations", []))
            output = prior if valid else _result(task, root)
        else:
            calls += 1
            if task["kind"] == "permission_denied":
                output = _result(task, root, status="abstain")
            else:
                output = _result(task, root)
            for path in task["source_paths"]:
                read_bytes += (root / path).stat().st_size
        results[task["task_id"]] = output
    return results, {"executor_calls": calls, "read_bytes": read_bytes}


def score(results, gold):
    metrics = {"correctness": 0, "faithfulness": 0, "completeness": 0, "citation": 0, "abstention": 0}
    total = len(gold)
    for task_id, expected in gold.items():
        actual = results[task_id]
        expected_claims = [{"key": key, "value": value, "unit": unit, "condition": condition}
                           for key, value, unit, condition in expected.get("required_claims", [])]
        expected_paths = expected.get("required_citations", [])
        actual_atoms = {(item["key"], item["value"], item["unit"], item["condition"]) for item in actual["claims"]}
        required_atoms = {(item["key"], item["value"], item["unit"], item["condition"]) for item in expected_claims}
        actual_paths = {item["path"] for item in actual["citations"]}
        metrics["correctness"] += int(actual["status"] == expected["status"] and required_atoms <= actual_atoms)
        metrics["faithfulness"] += int(all(any(item["key"] == claim["key"] and item["value"] == claim["value"] for item in actual["claims"]) for claim in expected_claims))
        metrics["completeness"] += int(required_atoms <= actual_atoms)
        metrics["citation"] += int(set(expected_paths) <= actual_paths)
        metrics["abstention"] += int((actual["status"] == "abstain") == (expected["status"] == "abstain"))
    return {key: value / total for key, value in metrics.items()}
