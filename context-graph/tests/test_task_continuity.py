"""No-network, temporary-project acceptance tests for read-only task resume."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/knowledge-engineering/scripts"
CLI = SCRIPTS / "build_task_continuity.py"
CONSTRAINTS = ["no_network", "no_commit", "no_push", "no_deploy", "no_source_edits",
               "no_memory_edits", "no_generated_edits", "preserve_user_changes",
               "review_before_promotion", "no_secrets"]


@pytest.fixture(autouse=True)
def fixture_project_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pointer(root, name="one", *, status="accepted", supersedes=None, lifecycle="active"):
    target = root / f"{name}.html"
    target.write_text('<h1 id="result">PRIVATE_BODY_SENTINEL</h1>', encoding="utf-8")
    review = root / f"{name}-review.json"
    proof = {
        "schema_version": 1, "id": f"DEC-{name}", "record_type": "Decision", "revision": 1,
        "status": "accepted", "created_at": "2026-09-25T00:00:00Z", "updated_at": "2026-09-25T00:00:00Z",
        "provenance": {"agent": "fixture-reviewer", "activity_id": "fixture-review"},
        "target_pointer": f"{name}.html#result", "target_sha256": digest(target),
        "continuity": {"lifecycle_status": lifecycle, "supersedes": supersedes or [],
                       "required_constraints": CONSTRAINTS,
                       "next_actions": ["review_evidence", "run_focused_tests"],
                       "decision_context": {"question_key": "Q-continuity", "scope": "project",
                                            "as_of": "2026-09-25", "outcome_id": "continue"},
                       "conflicts_with": []},
        "raw_prompt": "PROMPT_SENTINEL", "transcript": "TRANSCRIPT_SENTINEL",
        "secret": "SECRET_SENTINEL",
    }
    review.write_text(json.dumps(proof), encoding="utf-8")
    return {"pointer": f"{name}.html#result", "status": status,
            "revision_sha256": digest(target), "review_pointer": review.name,
            "review_sha256": digest(review)}


def write_memory(root, **fields):
    path = root / "memory.json"
    path.write_text(json.dumps({"schema_version": 1, **fields}), encoding="utf-8")
    return path


def run(root, *options):
    result = subprocess.run([sys.executable, "-B", str(CLI), "--root", str(root),
                             "--memory", "memory.json", *options], cwd=root, capture_output=True, text=True)
    assert result.stdout, result.stderr
    return result, json.loads(result.stdout)


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_ready_pack_is_deterministic_read_only_and_pointer_only(tmp_path):
    goal = pointer(tmp_path)
    decision = pointer(tmp_path, "two")
    pending = {"pointer": "missing.html", "status": "open"}
    write_memory(tmp_path, current_goal=goal, approved_decision_pointers=[decision],
                 unresolved_pointers=[pending], snapshot_hash={
                     **goal, "source": goal["pointer"], "value": goal["revision_sha256"], "algorithm": "sha256"})
    before = tree_bytes(tmp_path)
    result, data = run(tmp_path)
    again, _ = run(tmp_path)
    assert result.returncode == 0 and result.stdout == again.stdout
    assert tree_bytes(tmp_path) == before
    assert data["pack_status"] == "partial" and data["read_only"] and not data["promotion_performed"]
    assert {i["group"] for i in data["items"]} == {
        "current_goal", "approved_decision_pointers", "unresolved_pointers", "snapshot_hash"}
    item = data["items"][0]
    assert item["integrity_status"] == "valid"
    assert item["revision_sha256"] == goal["revision_sha256"]
    assert set(item["required_constraints"]) == set(CONSTRAINTS)
    assert item["next_actions"] == ["review_evidence", "run_focused_tests"]
    assert item["review_sha256"] == goal["review_sha256"]
    # Cycle 11: the two independent proofs remain usable; the alias and open
    # pointer remain visible but cannot be applied or authorize cache reuse.
    assert sum(i["applicable"] for i in data["items"]) == 2
    assert not next(i for i in data["items"] if i["group"] == "unresolved_pointers")["applicable"]
    assert not data["safety"]["memory_complete"] and not data["cache_reusable"]
    for secret in ("PRIVATE_BODY_SENTINEL", "PROMPT_SENTINEL", "TRANSCRIPT_SENTINEL", "SECRET_SENTINEL"):
        assert secret not in result.stdout
    assert str(tmp_path) not in result.stdout


@pytest.mark.parametrize("content,state,exit_code", [
    (None, "missing_memory", 2), ("{broken", "invalid_memory", 2),
    ('{"schema_version":1}', "empty", 0), ('[]', "invalid_memory", 2),
    ('{"schema_version":1,"approved_decision_pointers":{}}', "invalid_memory", 2),
    ('{"schema_version":1,"schema_version":2}', "invalid_memory", 2),
])
def test_missing_invalid_and_empty_are_distinct(tmp_path, content, state, exit_code):
    if content is not None:
        (tmp_path / "memory.json").write_text(content)
    before = tree_bytes(tmp_path)
    result, data = run(tmp_path)
    assert result.returncode == exit_code and data["pack_status"] == state
    assert not data["items"]
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("change,state", [
    ("hash", "stale"), ("anchor", "unlocatable"), ("proof", "unverified"),
    ("nonobject", "unknown"),
])
def test_unsafe_pointer_has_explicit_state_and_no_instructions(tmp_path, change, state):
    entry = pointer(tmp_path)
    if change == "hash": entry["revision_sha256"] = "0" * 64
    if change == "anchor": entry["pointer"] = "one.html#absent"
    if change == "proof": entry.pop("review_sha256")
    if change == "nonobject": entry = "RAW_PROMPT_SENTINEL"
    write_memory(tmp_path, current_goal=entry)
    result, data = run(tmp_path)
    item = data["items"][0]
    assert item["integrity_status"] == state
    assert not item["applicable"] and not item["required_constraints"] and not item["next_actions"]
    assert data["pack_status"] == "partial" and "RAW_PROMPT_SENTINEL" not in result.stdout


def test_superseded_and_retracted_cannot_become_active(tmp_path):
    old = pointer(tmp_path, "old")
    new = pointer(tmp_path, "new", supersedes=["DEC-old"])
    retired = pointer(tmp_path, "retired", lifecycle="retracted")
    write_memory(tmp_path, approved_decision_pointers=[old, new, retired])
    _, data = run(tmp_path)
    by_id = {i["record_id"]: i for i in data["items"]}
    assert by_id["DEC-old"]["lifecycle_status"] == "superseded"
    assert by_id["DEC-old"]["superseded_by"] == ["DEC-new"]
    assert not by_id["DEC-old"]["applicable"]
    assert by_id["DEC-new"]["supersedes"] == ["DEC-old"] and by_id["DEC-new"]["applicable"]
    assert not by_id["DEC-retired"]["applicable"]


def test_recorded_retraction_is_never_upgraded(tmp_path):
    entry = pointer(tmp_path, status="retracted")
    write_memory(tmp_path, current_goal=entry)
    _, data = run(tmp_path)
    item = data["items"][0]
    assert item["recorded_status"] == "retracted" and item["lifecycle_status"] == "retracted"
    assert not item["applicable"] and item["integrity_status"] != "valid"


def test_unbound_memory_instructions_are_not_used(tmp_path):
    entry = pointer(tmp_path)
    proof_path = tmp_path / entry["review_pointer"]
    proof = json.loads(proof_path.read_text())
    proof.pop("continuity")
    proof_path.write_text(json.dumps(proof))
    entry["review_sha256"] = digest(proof_path)
    entry["required_constraints"] = ["no_commit"]
    entry["next_actions"] = ["RAW_PROMPT_SENTINEL"]
    write_memory(tmp_path, current_goal=entry)
    result, data = run(tmp_path)
    item = data["items"][0]
    assert item["integrity_status"] == "valid" and item["continuity_state"] == "unknown"
    assert item["required_constraints"] == [] and item["next_actions"] == []
    assert data["pack_status"] == "partial" and "RAW_PROMPT_SENTINEL" not in result.stdout


@pytest.mark.parametrize("path", ["../outside.html", "/tmp/outside.html", "https://example.org/",
                                  ".env", "raw-transcripts.json", "evaluator-gold.json"])
def test_unsafe_or_private_path_is_never_read_or_echoed(tmp_path, path):
    write_memory(tmp_path, current_goal={"pointer": path, "status": "accepted"})
    result, data = run(tmp_path)
    assert data["items"][0]["pointer"] is None
    assert data["items"][0]["integrity_status"] == "unlocatable"
    assert path not in result.stdout


def test_limits_never_silently_drop_constraints(tmp_path):
    entries = [pointer(tmp_path, str(i)) for i in range(4)]
    write_memory(tmp_path, approved_decision_pointers=entries)
    result, data = run(tmp_path, "--max-entries", "2", "--max-pack-bytes", "2048")
    assert len(result.stdout.encode()) <= 2048
    assert data["pack_status"] == "partial" and data["omitted_count"] >= 2
    assert not any(i["applicable"] for i in data["items"])


def test_oversize_artifact_is_unknown_not_valid(tmp_path):
    entry = pointer(tmp_path)
    write_memory(tmp_path, current_goal=entry)
    _, data = run(tmp_path, "--max-file-bytes", "32")
    assert data["items"][0]["integrity_status"] == "unknown"
    assert data["pack_status"] == "partial"


def test_unknown_superseder_and_cycle_cannot_authorize_resume(tmp_path):
    a = pointer(tmp_path, "a", supersedes=["DEC-b"])
    b = pointer(tmp_path, "b", supersedes=["DEC-a"])
    c = pointer(tmp_path, "c", supersedes=["DEC-missing"])
    write_memory(tmp_path, approved_decision_pointers=[a, b, c])
    _, data = run(tmp_path)
    assert data["pack_status"] == "conflict"
    assert not any(i["applicable"] for i in data["items"])


def test_cli_output_schema(tmp_path):
    # Existing test dependency only; production CLI remains standard-library-only.
    import jsonschema
    write_memory(tmp_path, current_goal=pointer(tmp_path))
    _, data = run(tmp_path)
    schema = json.loads((SCRIPTS.parent / "schemas/task-continuity-pack.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(data)
    assert data["pack_status"] == "ready" and data["items"][0]["applicable"]


def test_reuses_cycle01_classifier(tmp_path, monkeypatch):
    assert CLI.exists(), "continuity builder is not implemented"
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("continuity", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_memory(tmp_path, current_goal=pointer(tmp_path))
    calls = []
    real = module.integrity.classify

    def spy(*args, **kwargs):
        calls.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.integrity, "classify", spy)
    data = module.build_pack(tmp_path, "memory.json")
    assert calls and data["items"][0]["integrity_status"] == "valid"


@pytest.mark.parametrize("field,value", [
    ("required_constraints", ["SECRET_SENTINEL"]),
    ("next_actions", ["echo PROMPT_SENTINEL"]),
    ("supersedes", ["../SECRET_SENTINEL"]),
])
def test_unsupported_bound_metadata_is_unknown_not_interpreted(tmp_path, field, value):
    entry = pointer(tmp_path)
    proof_path = tmp_path / entry["review_pointer"]
    proof = json.loads(proof_path.read_text())
    proof["continuity"][field] = value
    proof_path.write_text(json.dumps(proof))
    entry["review_sha256"] = digest(proof_path)
    write_memory(tmp_path, current_goal=entry)
    result, pack = run(tmp_path)
    assert pack["pack_status"] == "partial"
    assert pack["items"][0]["continuity_state"] == "unknown"
    assert not pack["items"][0]["applicable"]
    assert "SENTINEL" not in result.stdout


def test_retired_json_target_overrides_active_envelope(tmp_path):
    entry = pointer(tmp_path)
    target = tmp_path / "record.json"
    target.write_text('{"record_type":"Claim","status":"retracted"}')
    entry.update(pointer="record.json", revision_sha256=digest(target))
    proof_path = tmp_path / entry["review_pointer"]
    proof = json.loads(proof_path.read_text())
    proof.update(target_pointer=entry["pointer"], target_sha256=entry["revision_sha256"])
    proof_path.write_text(json.dumps(proof))
    entry["review_sha256"] = digest(proof_path)
    write_memory(tmp_path, current_goal=entry)
    _, pack = run(tmp_path)
    assert pack["items"][0]["lifecycle_status"] == "retracted"
    assert not pack["items"][0]["applicable"]


def test_total_read_budget_and_counts(tmp_path):
    entries = [pointer(tmp_path, str(i)) for i in range(4)]
    write_memory(tmp_path, approved_decision_pointers=entries)
    _, pack = run(tmp_path, "--max-total-bytes", "2048")
    assert pack["bytes_read"] <= 2048
    assert pack["pack_status"] == "partial"
    assert pack["included_count"] + pack["omitted_count"] == pack["total_count"] == 4
    assert any(i["reason"] == "read_limit" for i in pack["items"])


def test_symlinked_private_or_foreign_source_is_not_opened(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("continuity", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outside = tmp_path / "outside.html"
    outside.write_text("FOREIGN_PRIVATE_SENTINEL")
    root = tmp_path / "project"
    root.mkdir()
    (root / "alias.html").symlink_to(outside)
    write_memory(root, current_goal={"pointer": "alias.html", "status": "accepted"})
    opened = []
    original = Path.open

    def recording_open(path, *args, **kwargs):
        opened.append(path.resolve())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recording_open)
    monkeypatch.chdir(root)
    pack = module.build_pack(root, "memory.json")
    assert pack["items"][0]["integrity_status"] == "unlocatable"
    assert outside not in opened


def test_schema_validates_every_state_and_counts(tmp_path):
    import jsonschema
    schema = json.loads((SCRIPTS.parent / "schemas/task-continuity-pack.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    jsonschema.Draft202012Validator.check_schema(schema)
    for value in (None, "broken", '{"schema_version":1}'):
        if value is not None:
            (tmp_path / "memory.json").write_text(value)
        _, pack = run(tmp_path)
        validator.validate(pack)
        assert pack["total_count"] == pack["included_count"] + pack["omitted_count"]
    write_memory(tmp_path, current_goal={"pointer": "absent.html", "status": "open"})
    _, pack = run(tmp_path)
    validator.validate(pack)


def test_growing_file_cannot_exceed_total_read_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("continuity", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "growing.html"
    target.write_bytes(b"x" * 256)
    real_stat = Path.stat

    def stale_size(path, *args, **kwargs):
        actual = real_stat(path, *args, **kwargs)
        return SimpleNamespace(st_size=0, st_mode=actual.st_mode) if path == target else actual

    monkeypatch.setattr(Path, "stat", stale_size)
    reader = module.BoundedReader(tmp_path, file_limit=64, total_limit=64)
    with pytest.raises(module.ReadLimit):
        reader.read(target)
    assert reader.bytes_read <= 64


def test_cli_runs_under_isolated_interpreter_without_implicit_script_path(tmp_path):
    """python -I drops the script directory from sys.path; the sibling import must not depend on it."""
    import os
    import shutil

    write_memory(tmp_path, current_goal=pointer(tmp_path))
    installed = tmp_path.parent / "installed-scripts"
    shutil.copytree(SCRIPTS, installed, ignore=shutil.ignore_patterns("__pycache__"))
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    argv = [str(installed / "build_task_continuity.py"), "--root", str(tmp_path), "--memory", "memory.json"]
    isolated = subprocess.run([sys.executable, "-I", "-B", *argv], cwd=tmp_path, env=env, capture_output=True, text=True)
    normal = subprocess.run([sys.executable, "-B", *argv], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert isolated.returncode == 0, isolated.stderr
    assert isolated.stdout == normal.stdout and json.loads(isolated.stdout)["pack_status"] == "ready"
    assert not list(installed.rglob("__pycache__")) and not list(tmp_path.rglob("__pycache__"))
