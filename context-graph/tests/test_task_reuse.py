import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "skills/knowledge-engineering/scripts"
sys.path.insert(0, str(SCRIPT))
import plan_task_reuse as planner  # noqa: E402


def _harness(root, pointers):
    policy = {"roles": {"session": {"scope_ids": ["knowledge"]}, "agent": {"scope_ids": ["knowledge"]}}}
    binding = {"project_id": "p1", "task_scope_ids": ["knowledge"], "assignment_scope_ids": ["knowledge"]}
    return {"root": root, "policy": policy, "binding": binding, "session_role": "session",
            "agent_role": "agent", "catalog": {"artifacts": {p: {"scope_ids": ["knowledge"]} for p in pointers}}}


def _request(project="p1", evidence_path="knowledge/out.json"):
    content = b"stable output\n"
    return {"schema_version": 1, "record_type": "TaskReuseRequest", "project_id": project,
            "question_key": "q1", "scope": "knowledge", "as_of": "2026-10-08",
            "acceptance_contract": {"id": "contract", "version": 1},
            "artifacts": [{"path": evidence_path, "sha256": hashlib.sha256(content).hexdigest(), "locator": "line:1"}],
            "rights_sha256": [], "review_sha256": [], "policy_sha256": [], "allow_skip": False}


def _receipt(root, request, harness):
    task = planner.task_fingerprint(request)
    evidence = planner.evidence_fingerprint(request)
    artifact = root / "knowledge/out.json"
    review = root / "knowledge/review.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"stable output\n")
    review.write_text(json.dumps({"record_type": "Review", "status": "accepted", "completion_status": "complete",
                                 "task_fingerprint": planner.task_fingerprint(request),
                                 "evidence_fingerprint": planner.evidence_fingerprint(request),
                                 "artifact_refs": request["artifacts"]}) + "\n", encoding="utf-8")
    review_sha = hashlib.sha256(review.read_bytes()).hexdigest()
    harness["catalog"]["artifacts"]["knowledge/review.json"] = {"scope_ids": ["knowledge"]}
    receipt = {"schema_version": 1, "record_type": "TaskReuseReceipt", "receipt_id": "r1",
            "project_id": request["project_id"], "task_fingerprint": task,
            "evidence_fingerprint": evidence, "outcome": "reuse", "receipt_status": "accepted_artifact",
            "artifact_refs": json.loads(json.dumps(request["artifacts"])), "review_pointer": "knowledge/review.json",
            "review_sha256": review_sha, "acceptance_contract": request["acceptance_contract"],
            "rights_sha256": [], "policy_sha256": [],
            "created_at": "2026-10-08T00:00:00Z", "receipt_sha256": "0" * 64}
    receipt["receipt_sha256"] = planner._receipt_digest(receipt)
    return receipt


def test_reuses_only_reproducible_accepted_receipt(tmp_path):
    request = _request()
    harness = _harness(tmp_path, ["knowledge/out.json"])
    receipt = _receipt(tmp_path, request, harness)
    assert planner.decide(request, [receipt], harness)["decision"] == "reuse"
    request["allow_skip"] = True
    assert planner.decide(request, [receipt], harness)["decision"] == "skip"


def test_missing_harness_abstains_without_candidate_count():
    request = _request()
    result = planner.decide(request, [], None)
    assert result["decision"] == "abstain"
    assert result["candidate_count"] is None


def test_stale_artifact_holds_and_does_not_skip(tmp_path):
    request = _request()
    harness = _harness(tmp_path, ["knowledge/out.json"])
    receipt = _receipt(tmp_path, request, harness)
    (tmp_path / "knowledge/out.json").write_bytes(b"changed output\n")
    result = planner.decide(request, [receipt], harness)
    assert result["decision"] == "hold"
    assert result["reason"] == "receipt_not_reproducible"


def test_changed_evidence_refreshes_same_task(tmp_path):
    request = _request()
    harness = _harness(tmp_path, ["knowledge/out.json"])
    receipt = _receipt(tmp_path, request, harness)
    request["artifacts"][0]["locator"] = "line:2"
    result = planner.decide(request, [receipt], harness)
    assert result["decision"] == "refresh"


def test_different_task_branches(tmp_path):
    request = _request()
    harness = _harness(tmp_path, ["knowledge/out.json"])
    receipt = _receipt(tmp_path, request, harness)
    request["question_key"] = "q2"
    result = planner.decide(request, [receipt], harness)
    assert result["decision"] == "branch"


def test_foreign_project_abstains_without_count(tmp_path):
    request = _request(project="foreign")
    harness = _harness(tmp_path, ["knowledge/out.json"])
    harness["binding"]["project_id"] = "bound"
    result = planner.decide(request, [], harness)
    assert result["decision"] == "abstain"
    assert result["candidate_count"] is None


def test_unauthorized_artifact_holds(tmp_path):
    request = _request()
    harness = _harness(tmp_path, ["knowledge/out.json"])
    receipt = _receipt(tmp_path, request, harness)
    harness["catalog"]["artifacts"]["knowledge/out.json"]["scope_ids"] = ["private"]
    result = planner.decide(request, [receipt], harness)
    assert result["decision"] == "abstain"
    assert result["candidate_count"] is None


def test_cli_requires_and_uses_project_harness(tmp_path):
    request = _request(project="PRJ-test", evidence_path="knowledge/out.json")
    harness_dir = tmp_path / ".context-graph"
    harness_dir.mkdir()
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge/out.json").write_bytes(b"stable output\n")
    (tmp_path / "knowledge/review.json").write_text("{\"status\":\"accepted\"}\n", encoding="utf-8")
    policy = {"schema_version": 1, "project_id": "PRJ-test", "revision": "r1", "default_effect": "deny",
              "roles": {"session": {"scope_ids": ["knowledge"]}, "agent": {"scope_ids": ["knowledge"]}}}
    catalog = {"schema_version": 1, "artifacts": {p: {"scope_ids": ["knowledge"]} for p in ("knowledge/out.json", "knowledge/review.json")}}
    binding = {"schema_version": 1, "binding_id": "b1", "project_id": "PRJ-test", "session_id": "s1",
               "agent_instance_id": "a1", "task_id": "t1", "assignment_id": "x1", "session_role": "session",
               "agent_role": "agent", "task_scope_ids": ["knowledge"], "assignment_scope_ids": ["knowledge"],
               "policy_revision": "r1", "issuer": "launcher", "trusted": True, "revoked": False}
    import role_access
    binding["policy_sha256"] = role_access._digest(policy)
    binding["catalog_sha256"] = role_access._digest(catalog)
    for name, value in (("policy.json", policy), ("binding.json", binding), ("catalog.json", catalog)):
        (harness_dir / name).write_text(json.dumps(value), encoding="utf-8")
    subject = {"trusted": True, "issuer": "launcher", "project_id": "PRJ-test", "session_id": "s1",
               "agent_instance_id": "a1", "task_id": "t1", "assignment_id": "x1"}
    manifest = {"policy": ".context-graph/policy.json", "binding": ".context-graph/binding.json",
                "catalog": ".context-graph/catalog.json", "subject": subject}
    (harness_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    harness = planner.load_manifest(tmp_path, ".context-graph/manifest.json")
    receipt = _receipt(tmp_path, request, harness)
    (tmp_path / "knowledge-base/_ops").mkdir(parents=True)
    (tmp_path / "knowledge-base/_ops/work-reuse-receipts.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT / "plan_task_reuse.py"), "--root", str(tmp_path),
                          "--request", str(request_path), "--harness-manifest", ".context-graph/manifest.json"],
                         capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "reuse"


@pytest.mark.parametrize("field", ["question_key", "scope", "as_of"])
def test_task_identity_changes_are_not_semantic_matches(field):
    request = _request()
    baseline = planner.task_fingerprint(request)
    request[field] += "-changed"
    assert planner.task_fingerprint(request) != baseline
