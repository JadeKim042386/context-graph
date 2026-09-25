"""Gold-free fixture records: exact review bindings, no model or live memory writes."""
import json

import pytest

from test_task_continuity import pointer, digest, write_memory, run, tree_bytes, SCRIPTS


def decision(root, name, *, outcome="store-json", scope="project", as_of="2026-09-25",
             supersedes=None, conflicts=None, status="accepted", lifecycle="active"):
    entry = pointer(root, name, status=status, lifecycle=lifecycle, supersedes=supersedes)
    path = root / entry["review_pointer"]
    proof = json.loads(path.read_text())
    proof["continuity"].update(decision_context={"question_key": "Q-storage", "scope": scope,
        "as_of": as_of, "outcome_id": outcome}, conflicts_with=conflicts or [])
    path.write_text(json.dumps(proof))
    entry["review_sha256"] = digest(path)
    return entry


def test_new_accepted_superseder_is_considered_before_output_limit(tmp_path):
    old = decision(tmp_path, "old")
    new = decision(tmp_path, "new", outcome="store-rdf", supersedes=["DEC-old"])
    write_memory(tmp_path, approved_decision_pointers=[old, new])
    before = tree_bytes(tmp_path)
    _, pack = run(tmp_path, "--max-entries", "1")
    assert pack["items"][0]["record_id"] == "DEC-new"
    assert pack["assessed_count"] == 2 and pack["relation_scan_complete"]
    assert pack["omitted_count"] == 1 and pack["pack_status"] == "partial"
    assert not pack["items"][0]["applicable"]  # omitted context is still a safety limit
    _, complete = run(tmp_path)
    by_id = {i["record_id"]: i for i in complete["items"]}
    assert by_id["DEC-new"]["applicable"] and not by_id["DEC-old"]["applicable"]
    assert by_id["DEC-old"]["lifecycle_status"] == "superseded"
    assert tree_bytes(tmp_path) == before


def test_only_identical_revision_aliases_are_deduplicated(tmp_path):
    a = decision(tmp_path, "a")
    write_memory(tmp_path, approved_decision_pointers=[a, dict(a)])
    _, pack = run(tmp_path)
    assert pack["duplicate_count"] == 1
    assert sum(i["applicable"] for i in pack["items"]) == 1
    assert pack["items"][1]["lifecycle_status"] == "duplicate"
    assert pack["items"][1]["duplicate_of"] == "DEC-a"
    # Equal source body bytes do NOT equate independent proofs/paths.
    b = decision(tmp_path, "b")
    write_memory(tmp_path, approved_decision_pointers=[a, b])
    _, distinct = run(tmp_path)
    assert distinct["duplicate_count"] == 0
    assert sum(i["applicable"] for i in distinct["items"]) == 2


@pytest.mark.parametrize("kind", ["outcome", "declared", "identity"])
def test_supported_conflicts_are_preserved_with_criteria(tmp_path, kind):
    a = decision(tmp_path, "a", conflicts=["DEC-b"] if kind == "declared" else [])
    b = decision(tmp_path, "b", outcome="store-rdf" if kind == "outcome" else "store-json")
    if kind == "identity":
        path = tmp_path / b["review_pointer"]
        proof = json.loads(path.read_text())
        proof["id"] = "DEC-a"
        path.write_text(json.dumps(proof))
        b["review_sha256"] = digest(path)
    write_memory(tmp_path, approved_decision_pointers=[a, b])
    result, pack = run(tmp_path)
    assert result.returncode == 0 and pack["pack_status"] == "conflict"
    assert pack["conflict_count"] == 2 and len(pack["items"]) == 2
    assert all(i["lifecycle_status"] == "conflict" and i["conflict_criteria"] and not i["applicable"] for i in pack["items"])
    assert {i["pointer"] for i in pack["items"]} == {a["pointer"], b["pointer"]}
    assert not pack["promotion_performed"] and "SENTINEL" not in result.stdout


@pytest.mark.parametrize("change", ["scope", "as_of", "question_key"])
def test_scope_and_asof_mismatch_never_apply(tmp_path, change):
    entry = decision(tmp_path, "a")
    write_memory(tmp_path, current_goal=entry)
    query = {"scope": "project", "as_of": "2026-09-25", "question_key": "Q-storage"}
    query[change] = {"scope": "another", "as_of": "2026-09-26", "question_key": "Q-other"}[change]
    options = [v for k, value in query.items() for v in ("--" + k.replace("_", "-"), value)]
    _, pack = run(tmp_path, *options)
    assert pack["pack_status"] == "partial" and pack["items"][0]["context_status"] == "mismatch"
    assert not pack["items"][0]["applicable"] and not pack["cache_reusable"]


def test_matching_query_and_cache_digest_bind_current_dependencies(tmp_path):
    entry = decision(tmp_path, "a")
    write_memory(tmp_path, current_goal=entry)
    args = ["--question-key", "Q-storage", "--scope", "project", "--as-of", "2026-09-25"]
    first, pack = run(tmp_path, *args)
    again, _ = run(tmp_path, *args)
    assert first.stdout == again.stdout and pack["items"][0]["applicable"]
    dependency = pack["dependency_sha256"]
    assert len(dependency) == 64
    _, cached = run(tmp_path, *args, "--expected-dependency-sha256", dependency)
    assert cached["cache_state"] == "match" and cached["cache_reusable"]
    # Dependency change with unchanged file mtime must invalidate old cache identity.
    import os
    target = tmp_path / "a.html"
    original = target.stat()
    target.write_text('<h1 id="result">MODIFIED_BODY</h1>')
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
    _, stale = run(tmp_path, *args, "--expected-dependency-sha256", dependency)
    assert stale["dependency_sha256"] != dependency
    assert stale["cache_state"] == "mismatch" and not stale["cache_reusable"]
    assert not stale["items"][0]["applicable"]


def test_missing_decision_context_never_invents_scope_or_acceptance(tmp_path):
    entry = pointer(tmp_path, "legacy")
    proof_path = tmp_path / entry["review_pointer"]
    proof = json.loads(proof_path.read_text())
    proof["continuity"].pop("decision_context", None)
    proof_path.write_text(json.dumps(proof))
    entry["review_sha256"] = digest(proof_path)
    write_memory(tmp_path, current_goal=entry)
    _, pack = run(tmp_path)
    assert pack["items"][0]["context_status"] == "unknown"
    assert not pack["items"][0]["applicable"] and pack["pack_status"] == "partial"


@pytest.mark.parametrize("lifecycle", ["retracted", "deprecated"])
def test_retired_pointer_cannot_retire_live_decision(tmp_path, lifecycle):
    old = decision(tmp_path, "old")
    revoked = decision(tmp_path, "revoked", supersedes=["DEC-old"], lifecycle=lifecycle)
    write_memory(tmp_path, approved_decision_pointers=[old, revoked])
    _, pack = run(tmp_path)
    by_id = {i["record_id"]: i for i in pack["items"]}
    assert by_id["DEC-old"]["lifecycle_status"] == "active"
    assert by_id["DEC-revoked"]["lifecycle_status"] == lifecycle and not by_id["DEC-revoked"]["applicable"]


def test_verified_review_cannot_supersede_accepted_decision(tmp_path):
    old = decision(tmp_path, "old")
    candidate = decision(tmp_path, "candidate", status="verified", supersedes=["DEC-old"])
    path = tmp_path / candidate["review_pointer"]
    proof = json.loads(path.read_text())
    proof.update(record_type="Review", status="verified")
    path.write_text(json.dumps(proof))
    candidate["review_sha256"] = digest(path)
    write_memory(tmp_path, approved_decision_pointers=[old, candidate])
    _, pack = run(tmp_path)
    assert pack["pack_status"] == "partial" and not any(i["applicable"] for i in pack["items"])
    assert next(i for i in pack["items"] if i["record_id"] == "DEC-old")["lifecycle_status"] == "active"


def test_cross_scope_supersession_is_not_inferred(tmp_path):
    old = decision(tmp_path, "old", scope="other")
    new = decision(tmp_path, "new", supersedes=["DEC-old"])
    write_memory(tmp_path, approved_decision_pointers=[old, new])
    _, pack = run(tmp_path)
    assert pack["pack_status"] == "partial"
    assert not any(i["applicable"] for i in pack["items"])
    assert next(i for i in pack["items"] if i["record_id"] == "DEC-old")["lifecycle_status"] == "active"


def test_scan_limit_blocks_invisible_newer_records(tmp_path):
    old = decision(tmp_path, "old")
    new = decision(tmp_path, "new", supersedes=["DEC-old"])
    write_memory(tmp_path, approved_decision_pointers=[old] * 128 + [new])
    _, pack = run(tmp_path)
    assert not pack["relation_scan_complete"] and pack["assessed_count"] <= 128
    assert not any(i["applicable"] for i in pack["items"])
    assert not pack["cache_reusable"]


def test_conflict_pack_matches_schema_and_does_not_read_evaluator(tmp_path):
    import jsonschema
    a, b = decision(tmp_path, "a"), decision(tmp_path, "b", outcome="store-rdf")
    (tmp_path / "sealed-evaluator-gold.json").write_text('NOT_PUBLIC_EVIDENCE')
    write_memory(tmp_path, approved_decision_pointers=[a, b])
    before = tree_bytes(tmp_path)
    result, pack = run(tmp_path)
    schema = json.loads((SCRIPTS.parent / "schemas/task-continuity-pack.schema.json").read_text())
    jsonschema.validate(pack, schema)
    assert pack["pack_status"] == "conflict" and "NOT_PUBLIC_EVIDENCE" not in result.stdout
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("where", ["memory", "target", "self_declaration"])
def test_recorded_conflict_cannot_be_hidden_by_active_approval(tmp_path, where):
    entry = decision(tmp_path, "a", conflicts=["DEC-a"] if where == "self_declaration" else [])
    if where == "memory":
        entry["status"] = "conflict"
    if where == "target":
        target = tmp_path / "claim.json"
        target.write_text('{"record_type":"Claim","status":"conflict"}')
        entry.update(pointer=target.name, revision_sha256=digest(target))
        path = tmp_path / entry["review_pointer"]
        proof = json.loads(path.read_text())
        proof.update(target_pointer=entry["pointer"], target_sha256=entry["revision_sha256"])
        path.write_text(json.dumps(proof))
        entry["review_sha256"] = digest(path)
    write_memory(tmp_path, current_goal=entry)
    _, pack = run(tmp_path)
    assert pack["pack_status"] == "conflict"
    item = pack["items"][0]
    assert item["lifecycle_status"] == "conflict" and item["conflict_criteria"]
    assert not item["applicable"]
