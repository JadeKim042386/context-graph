import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "context-graph" / "skills" / "knowledge-engineering" / "scripts"


def load():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("audit_memory_support", SCRIPTS / "audit_memory_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def project(tmp_path, evidence, *, review_extra=None):
    """Memory + one verified Review whose target stays valid while its declared evidence varies."""
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "records").mkdir()
    target = root / "docs" / "goal.md"
    target.write_bytes(b"goal text\n")
    review = {"schema_version": 1, "id": "REV-fixture-1", "record_type": "Review", "revision": 1,
              "status": "verified", "created_at": "2026-09-26T00:00:00Z", "updated_at": "2026-09-26T00:00:00Z",
              "provenance": {"agent": "fixture", "activity_id": "ACT-fixture"},
              "target_pointer": "docs/goal.md", "target_sha256": sha(target.read_bytes()),
              "continuity": {"lifecycle_status": "active", "supersedes": [], "required_constraints": [],
                             "next_actions": [], "decision_context": {"question_key": "Q-fixture", "scope": "s",
                                                                       "as_of": "2026-09-26", "outcome_id": "o"},
                             "conflicts_with": []}}
    if evidence is not None:
        review["evidence"] = evidence
    review.update(review_extra or {})
    review_path = root / "records" / "REV-fixture-1.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    memory = {"schema_version": 1, "current_goal": {"pointer": "docs/goal.md", "status": "verified",
                                                    "updated_at": "2026-09-26T00:00:00Z",
                                                    "revision_sha256": review["target_sha256"],
                                                    "review_pointer": "records/REV-fixture-1.json",
                                                    "review_sha256": sha(review_path.read_bytes())}}
    (root / "memory.json").write_text(json.dumps(memory), encoding="utf-8")
    return root


def snapshot(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def mixed_fixture(tmp_path):
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    ok = root / "docs" / "ok.txt"; ok.write_bytes(b"same")
    changed = root / "docs" / "changed.txt"; changed.write_bytes(b"before")
    before_hash = sha(b"before")
    info = changed.stat()
    changed.write_bytes(b"after!")  # same length, then restore mtime: content changed, mtime unchanged
    os.utime(changed, ns=(info.st_atime_ns, info.st_mtime_ns))
    big = root / "docs" / "big.txt"; big.write_bytes(b"x" * 3000)
    evidence = [{"path": "docs/ok.txt", "sha256": sha(b"same")},
                {"path": "docs/changed.txt", "sha256": before_hash},
                {"path": "docs/missing.txt", "sha256": "0" * 64},
                {"path": "../outside.txt", "sha256": "1" * 64},
                {"path": "docs/big.txt", "sha256": sha(b"x" * 3000)},
                {"path": "docs/ok.txt"},
                "not-an-object"]
    return project(tmp_path, evidence), changed, info.st_mtime_ns


def test_dependency_drift_is_visible_while_proof_and_target_stay_valid(tmp_path, monkeypatch):
    module = load()
    root, changed, mtime = mixed_fixture(tmp_path)
    assert changed.stat().st_mtime_ns == mtime
    monkeypatch.chdir(root)
    before = snapshot(root)
    first = module.audit(root, "memory.json", max_file_bytes=2048)
    second = module.audit(root, "memory.json", max_file_bytes=2048)

    assert first == second
    assert first["read_only"] is True and first["promotion_performed"] is False
    assert first["pack_status"] == "ready" and first["continuity"]["applicable_count"] == 1
    proof = first["proofs"][0]
    assert proof["record_id"] == "REV-fixture-1" and proof["evidence_declared"] is True
    assert [(e["locator"], e["status"]) for e in proof["entries"]] == [
        ("/evidence/0", "valid"), ("/evidence/1", "stale"), ("/evidence/2", "unlocatable"),
        ("/evidence/3", "unlocatable"), ("/evidence/4", "unverified"), ("/evidence/5", "unverified"),
        ("/evidence/6", "unverified")]
    assert proof["entries"][1]["expected_sha256"] == sha(b"before")
    assert proof["entries"][1]["actual_sha256"] == sha(b"after!")
    assert proof["entries"][4]["reason"].startswith("read_limit")
    assert proof["entries"][5]["reason"] == "missing_locator_fields"
    assert proof["replay_status"] == "incomplete"
    assert first["totals"] == {"proofs_assessed": 1, "proofs_with_declared_evidence": 1, "entries_assessed": 7,
                               "omitted_entries": 0, "omitted_proofs": 0,
                               "valid": 1, "stale": 1, "unlocatable": 2, "unverified": 3}
    assert first["support_replay_complete"] is False and first["output_truncated"] is False
    assert snapshot(root) == before and not list(root.rglob("__pycache__"))
    dumped = json.dumps(first)
    assert "before" not in dumped and "after!" not in dumped and "goal text" not in dumped


def test_all_valid_dependencies_replay_complete(tmp_path, monkeypatch):
    module = load()
    root = project(tmp_path, [{"path": "docs/goal.md", "sha256": sha(b"goal text\n")}])
    monkeypatch.chdir(root)
    result = module.audit(root, "memory.json")
    assert result["support_replay_complete"] is True
    assert result["proofs"][0]["replay_status"] == "complete"
    assert result["totals"]["valid"] == 1 and result["totals"]["stale"] == 0


def test_no_evidence_array_is_not_declared_not_verified(tmp_path, monkeypatch):
    module = load()
    root = project(tmp_path, None)
    monkeypatch.chdir(root)
    result = module.audit(root, "memory.json")
    proof = result["proofs"][0]
    assert proof["evidence_declared"] is False and proof["replay_status"] == "not_declared"
    assert result["totals"]["proofs_with_declared_evidence"] == 0
    assert result["support_replay_complete"] is False
    assert result["continuity"]["applicable_count"] == 1  # applicability is untouched


def test_omitted_entries_never_become_a_clean_pass(tmp_path, monkeypatch):
    module = load()
    root = project(tmp_path, [{"path": "docs/goal.md", "sha256": sha(b"goal text\n")}] * 3)
    monkeypatch.chdir(root)
    result = module.audit(root, "memory.json", max_evidence=2)
    assert result["totals"]["entries_assessed"] == 2 and result["totals"]["omitted_entries"] == 1
    assert result["proofs"][0]["replay_status"] == "incomplete"
    assert result["support_replay_complete"] is False


def test_inputs_digest_detects_memory_change_and_is_stable_otherwise(tmp_path, monkeypatch):
    module = load()
    root = project(tmp_path, [{"path": "docs/goal.md", "sha256": sha(b"goal text\n")}])
    monkeypatch.chdir(root)
    a = module.audit(root, "memory.json")
    b = module.audit(root, "memory.json")
    assert a["inputs_sha256"] == b["inputs_sha256"]
    memory = json.loads((root / "memory.json").read_text())
    memory["unresolved_pointers"] = [{"pointer": "docs/goal.md", "status": "open"}]
    (root / "memory.json").write_text(json.dumps(memory))
    c = module.audit(root, "memory.json")
    assert c["inputs_sha256"] != a["inputs_sha256"] and c["memory_sha256"] != a["memory_sha256"]


def test_invalid_memory_and_limits(tmp_path, monkeypatch):
    module = load()
    root = tmp_path / "proj"; root.mkdir()
    (root / "memory.json").write_text("{not json")
    monkeypatch.chdir(root)
    result = module.audit(root, "memory.json")
    assert result["pack_status"] == "invalid_memory" and result["proofs"] == []
    assert result["support_replay_complete"] is False
    with pytest.raises(ValueError):
        module.audit(root, "memory.json", max_evidence=0)


def test_cli_from_installed_layout_in_isolated_interpreter(tmp_path, monkeypatch):
    """Installed copy: only stdlib + sibling files, -I isolation, no bytecode, exit codes."""
    installed = tmp_path / "installed" / "scripts"
    shutil.copytree(SCRIPTS, installed, ignore=shutil.ignore_patterns("__pycache__"))
    root = project(tmp_path, [{"path": "docs/goal.md", "sha256": sha(b"goal text\n")}])
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run([sys.executable, "-I", "-B", str(installed / "audit_memory_support.py"),
                                "--root", str(root), "--memory", "memory.json"],
                               cwd=root, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["support_replay_complete"] is True and result["binding"]["status"] == "verified"
    assert not list(installed.rglob("__pycache__")) and not list(root.rglob("__pycache__"))
    (root / "memory.json").write_text("{bad")
    failed = subprocess.run([sys.executable, "-I", "-B", str(installed / "audit_memory_support.py"),
                             "--root", str(root), "--memory", "memory.json"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert failed.returncode == 2 and json.loads(failed.stdout)["pack_status"] == "invalid_memory"


def test_output_budget_truncates_deterministically_and_never_reports_complete(tmp_path, monkeypatch):
    module = load()
    root = project(tmp_path, [{"path": "docs/goal.md", "sha256": sha(b"goal text\n")}] * 120)
    monkeypatch.chdir(root)
    full = module.audit(root, "memory.json", max_evidence=256)
    assert full["support_replay_complete"] is True and full["totals"]["entries_assessed"] == 120
    assert len(json.dumps(full, sort_keys=True, separators=(",", ":"))) > 4096

    a = module.audit(root, "memory.json", max_evidence=256, max_output_bytes=4096)
    b = module.audit(root, "memory.json", max_evidence=256, max_output_bytes=4096)
    encoded = json.dumps(a, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    assert a == b and len(encoded.encode("utf-8")) <= 4096
    assert a["output_truncated"] is True and a["support_replay_complete"] is False
    proof = a["proofs"][0]
    assert proof["replay_status"] == "incomplete" and proof["omitted_entries"] > 0
    assert proof["omitted_entries"] + len(proof["entries"]) == 120
    assert a["totals"]["omitted_entries"] == proof["omitted_entries"]
    assert a["totals"]["entries_assessed"] == len(proof["entries"]) == proof["counts"]["valid"]
    assert [e["locator"] for e in proof["entries"]] == [f"/evidence/{i}" for i in range(len(proof["entries"]))]
    assert a["limits"]["max_output_bytes"] == 4096

    encode = lambda value: (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    envelope = dict(a, proofs=[], totals=dict(a["totals"], omitted_proofs=1, omitted_entries=0, entries_assessed=0, valid=0))
    with_empty_proof = dict(envelope, proofs=[dict(proof, entries=[], omitted_entries=120)])
    budget = len(encode(with_empty_proof)) - 1  # fits the envelope, not even one emptied proof
    assert 1024 <= len(encode(envelope)) <= budget
    tiny = module.audit(root, "memory.json", max_evidence=256, max_output_bytes=budget)
    assert tiny["proofs"] == [] and tiny["totals"]["omitted_proofs"] == 1
    assert tiny["output_truncated"] is True and tiny["support_replay_complete"] is False
    assert len(encode(tiny)) <= budget
    with pytest.raises(ValueError):  # budget below the envelope is refused, never silently emptied
        module.audit(root, "memory.json", max_output_bytes=1024)
    with pytest.raises(ValueError):
        module.audit(root, "memory.json", max_output_bytes=512)


def test_multibyte_content_replays_and_non_ascii_path_is_unlocatable(tmp_path, monkeypatch):
    module = load()
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    body = ("근거 문서 — 다국어 증거 ✓\n" * 40).encode("utf-8")
    (root / "docs" / "multibyte.md").write_bytes(body)
    (root / "docs" / "증거.md").write_bytes(body)
    root = project(tmp_path, [{"path": "docs/multibyte.md", "sha256": sha(body)},
                              {"path": "docs/증거.md", "sha256": sha(body)}])
    monkeypatch.chdir(root)
    result = module.audit(root, "memory.json")
    statuses = [(e["locator"], e["status"], e["reason"]) for e in result["proofs"][0]["entries"]]
    assert statuses == [("/evidence/0", "valid", "hash_match"), ("/evidence/1", "unlocatable", "unsafe_pointer")]
    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert encoded.isascii() and "근거" not in encoded
    assert result["support_replay_complete"] is False


def test_supporting_file_mutation_changes_observed_status_without_changing_inputs(tmp_path, monkeypatch):
    module = load()
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    dep = root / "docs" / "dep.txt"
    dep.write_bytes(b"v1")
    root = project(tmp_path, [{"path": "docs/dep.txt", "sha256": sha(b"v1")}])
    monkeypatch.chdir(root)
    before = module.audit(root, "memory.json")
    info = dep.stat()
    dep.write_bytes(b"v2")
    os.utime(dep, ns=(info.st_atime_ns, info.st_mtime_ns))
    after = module.audit(root, "memory.json")
    assert before["inputs_sha256"] == after["inputs_sha256"]  # memory and proof bytes unchanged
    assert before["observed_sha256"] != after["observed_sha256"]
    assert before["proofs"][0]["entries"][0]["status"] == "valid"
    assert after["proofs"][0]["entries"][0]["status"] == "stale"
    assert before["support_replay_complete"] is True and after["support_replay_complete"] is False
    assert after["cache_reusable"] is False and "inputs_sha256_is_not_a_cache_key" in after["safety"]
