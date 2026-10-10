import sys
import hashlib
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import knowledge_partitions as kp
import merge_knowledge as mk
import session_knowledge
import pytest


def test_partition_freeze_blocks_writes_and_reviewed_merge_preserves_provenance(tmp_path):
    root = tmp_path / "project"
    (root / "knowledge-base" / "_ops").mkdir(parents=True)
    a = kp.open_partition(root, project_id="P", session_id="S1", agent_instance_id="A", role="research", scope_ids=["scope-x"])
    b = kp.open_partition(root, project_id="P", session_id="S2", agent_instance_id="B", role="review", scope_ids=["scope-x"])
    kp.put_candidate(root, partition_id=a["partition_id"], candidate_id="C1", claim_key="temperature", value="20 C", source_refs=[{"source_id": "SRC1", "locator": "p1"}])
    kp.put_candidate(root, partition_id=b["partition_id"], candidate_id="C2", claim_key="temperature", value="20 C", source_refs=[{"source_id": "SRC2", "locator": "p2"}])
    kp.freeze_partition(root, partition_id=a["partition_id"], reason="agent_closed")
    kp.freeze_partition(root, partition_id=b["partition_id"], reason="agent_closed")
    with pytest.raises(kp.PartitionError, match="partition_frozen"):
        kp.put_candidate(root, partition_id=a["partition_id"], candidate_id="C3", claim_key="x", value=1, source_refs=[{"source_id": "SRC3"}])
    plan = mk.plan_merge(root, partition_ids=[a["partition_id"], b["partition_id"]])
    assert plan["status"] == "proposed"
    receipt = mk.apply_merge(root, plan=plan, approval={"approval_id": "D1", "status": "accepted", "merge_plan_sha256": plan["plan_sha256"]})
    assert receipt["status"] == "applied"
    records = mk.query_canonical(root, allowed_partition_ids={a["partition_id"]})
    assert records[0]["provenance"]["session_id"] == "S1"
    assert {r["provenance"]["agent_instance_id"] for r in mk.query_canonical(root, allowed_partition_ids={a["partition_id"], b["partition_id"]})} == {"A", "B"}


def test_session_close_freezes_knowledge_partition(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "knowledge-base" / "_ops").mkdir(parents=True)
    project_id = "PRJ-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    (root / "knowledge-base" / "_ops" / "session-capture.json").write_text(json.dumps({
        "schema_version": 1, "enabled": True, "project_id": project_id,
        "include_globs": ["knowledge/**"], "tracked_paths_only": True,
        "capture_content": False, "capture_commands": False, "capture_untracked": False,
    }), encoding="utf-8")
    monkeypatch.chdir(root)
    part = kp.open_partition(root, project_id="P", session_id="S1", agent_instance_id="A", role="research", scope_ids=["scope-x"])
    closed = session_knowledge.close_agent(root, session_id="S1", agent_instance_id="A", role="research")
    assert part["partition_id"] in closed["frozen_knowledge_partition_ids"]
    assert kp._partition(root, part["partition_id"])["state"] == "frozen"


def test_conflicting_candidates_are_not_merged(tmp_path):
    root = tmp_path / "project"
    (root / "knowledge-base" / "_ops").mkdir(parents=True)
    a = kp.open_partition(root, project_id="P", session_id="S1", agent_instance_id="A", role="research", scope_ids=["scope-x"])
    b = kp.open_partition(root, project_id="P", session_id="S2", agent_instance_id="B", role="review", scope_ids=["scope-x"])
    for part, cid, value in ((a, "C1", "20 C"), (b, "C2", "30 C")):
        kp.put_candidate(root, partition_id=part["partition_id"], candidate_id=cid, claim_key="temperature", value=value, source_refs=[{"source_id": cid}])
        kp.freeze_partition(root, partition_id=part["partition_id"], reason="closed")
    plan = mk.plan_merge(root, partition_ids=[a["partition_id"], b["partition_id"]])
    assert plan["status"] == "conflict"
    with pytest.raises(kp.PartitionError, match="merge_not_approved"):
        mk.apply_merge(root, plan=plan, approval={"status": "accepted", "merge_plan_sha256": plan["plan_sha256"]})
