"""Item-scoped applicability must not convert incomplete memory into approval."""
import json

import pytest

from test_task_continuity import pointer, digest, write_memory, run, tree_bytes, SCRIPTS
from test_continuity_relations import decision


@pytest.fixture(autouse=True)
def project_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def review(root, name, *, scope="project"):
    entry = pointer(root, name, status="verified")
    path = root / entry["review_pointer"]
    proof = json.loads(path.read_text())
    proof.update(record_type="Review", status="verified")
    proof["continuity"]["decision_context"]["scope"] = scope
    path.write_text(json.dumps(proof))
    entry["review_sha256"] = digest(path)
    return entry


def test_three_verified_reviews_survive_four_visible_open_items(tmp_path):
    valid = [review(tmp_path, name) for name in ("one", "two", "three")]
    pending = [{"pointer": f"pending-{i}.html", "status": "open"} for i in range(4)]
    write_memory(tmp_path, approved_decision_pointers=valid, unresolved_pointers=pending)
    before = tree_bytes(tmp_path)
    first, pack = run(tmp_path)
    second, _ = run(tmp_path)
    assert first.stdout == second.stdout and tree_bytes(tmp_path) == before
    assert pack["pack_status"] == "partial" and pack["included_count"] == 7
    assert sum(i["applicable"] for i in pack["items"]) == 3
    assert all(i["applicable"] for i in pack["items"] if i["proof_type"] == "Review")
    assert sum(i["group"] == "unresolved_pointers" and not i["applicable"] for i in pack["items"]) == 4
    assert not pack["safety"]["memory_complete"]
    assert "review_unresolved_before_dependent_action" in pack["safety"]["constraints"]
    assert "applicability_is_not_approval" in pack["safety"]["constraints"]
    assert not pack["cache_reusable"] and not pack["promotion_performed"]
    import jsonschema
    jsonschema.validate(pack, json.loads((SCRIPTS.parent / "schemas/task-continuity-pack.schema.json").read_text()))


def test_conflicting_items_block_only_their_context(tmp_path):
    a, b = decision(tmp_path, "a"), decision(tmp_path, "b", outcome="different")
    independent = review(tmp_path, "independent", scope="independent")
    write_memory(tmp_path, approved_decision_pointers=[a, b, independent])
    _, pack = run(tmp_path)
    by_id = {i["record_id"]: i for i in pack["items"]}
    assert pack["pack_status"] == "conflict" and pack["conflict_count"] == 2
    assert not by_id["DEC-a"]["applicable"] and not by_id["DEC-b"]["applicable"]
    assert by_id["DEC-independent"]["applicable"]
    assert not pack["safety"]["memory_complete"] and not pack["cache_reusable"]


def test_missing_context_blocks_that_item_not_known_review(tmp_path):
    a, b = review(tmp_path, "a"), review(tmp_path, "b")
    path = tmp_path / b["review_pointer"]
    proof = json.loads(path.read_text())
    proof["continuity"].pop("decision_context")
    path.write_text(json.dumps(proof))
    b["review_sha256"] = digest(path)
    write_memory(tmp_path, approved_decision_pointers=[a, b])
    _, pack = run(tmp_path)
    by_id = {i["record_id"]: i for i in pack["items"]}
    assert by_id["DEC-a"]["applicable"] and not by_id["DEC-b"]["applicable"]
    assert by_id["DEC-b"]["context_status"] == "unknown"
    assert pack["pack_status"] == "partial"


def test_query_mismatch_is_item_scoped_and_incomplete_cache_is_never_reused(tmp_path):
    a, b = review(tmp_path, "a"), review(tmp_path, "b", scope="other")
    write_memory(tmp_path, approved_decision_pointers=[a, b],
                 unresolved_pointers=[{"pointer": "pending.html", "status": "open"}])
    args = ["--question-key", "Q-continuity", "--scope", "project", "--as-of", "2026-09-25"]
    _, pack = run(tmp_path, *args)
    by_id = {i["record_id"]: i for i in pack["items"] if i["record_id"]}
    assert by_id["DEC-a"]["applicable"] and not by_id["DEC-b"]["applicable"]
    assert by_id["DEC-b"]["context_status"] == "mismatch"
    _, cached = run(tmp_path, *args, "--expected-dependency-sha256", pack["dependency_sha256"])
    assert cached["cache_state"] == "match" and not cached["cache_reusable"]
    assert cached["pack_status"] == "partial"
    _, stale = run(tmp_path, *args, "--expected-dependency-sha256", "0" * 64)
    assert stale["cache_state"] == "mismatch" and not any(i["applicable"] for i in stale["items"])


def test_missing_memory_exposes_global_incomplete_safety(tmp_path):
    result, pack = run(tmp_path)
    assert result.returncode == 2 and pack["pack_status"] == "missing_memory"
    assert not pack["safety"]["memory_complete"] and not pack["items"]


def test_unknown_relation_does_not_disable_unrelated_review(tmp_path):
    bad = decision(tmp_path, "bad", supersedes=["DEC-absent"])
    good = review(tmp_path, "good", scope="independent")
    write_memory(tmp_path, approved_decision_pointers=[bad, good])
    _, pack = run(tmp_path)
    by_id = {i["record_id"]: i for i in pack["items"]}
    assert by_id["DEC-bad"]["reason"] == "unresolved_supersedes" and not by_id["DEC-bad"]["applicable"]
    assert by_id["DEC-good"]["applicable"] and pack["pack_status"] == "partial"
