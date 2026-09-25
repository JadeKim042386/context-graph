"""Promotion failures must never replace the original memory bytes."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


UPDATER = Path(__file__).resolve().parents[1] / "skills/knowledge-engineering/scripts/update_memory.py"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "target.html").write_text('<h1 id="approved">Checked</h1>')
    digest = hashlib.sha256((tmp_path / "target.html").read_bytes()).hexdigest()
    proof = {
        "schema_version": 1, "id": "DEC-1", "record_type": "Decision",
        "revision": 1, "status": "accepted",
        "created_at": "2026-09-25T00:00:00Z", "updated_at": "2026-09-25T00:00:00Z",
        "provenance": {"agent": "fixture-reviewer", "activity_id": "review-1"},
        "target_pointer": "target.html#approved", "target_sha256": digest,
    }
    (tmp_path / "review.json").write_text(json.dumps(proof))
    (tmp_path / "memory.json").write_bytes(b'{ "schema_version": 1, "custom": "preserve" }\n')
    return tmp_path, digest


def run(root, *args):
    return subprocess.run(
        [sys.executable, str(UPDATER), "--root", str(root),
         "--memory", str(root / "memory.json"), *args],
        capture_output=True, text=True,
    )


def promote(root, digest, **overrides):
    options = {"goal": "target.html#approved", "status": "accepted",
               "goal-hash": digest, "review": "review.json"}
    options.update(overrides)
    return run(root, *(value for key, val in options.items() if val is not None
                       for value in ("--" + key, val)))


def test_original_unsafe_cli_rejects_promotion_without_changing_bytes(project):
    root, _ = project
    memory = root / "memory.json"
    before = memory.read_bytes()
    result = subprocess.run(
        [sys.executable, str(UPDATER), "--memory", str(memory),
         "--goal", "missing.html", "--status", "accepted", "--snapshot-hash", "not-a-hash"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert memory.read_bytes() == before


@pytest.mark.parametrize("override,reason", [
    ({"goal": "missing.html"}, "unlocatable"),
    ({"goal": "target.html#missing"}, "unlocatable"),
    ({"goal-hash": "bad"}, "unverified"),
    ({"goal-hash": "0" * 64}, "stale"),
    ({"goal-hash": None}, "unverified"),
    ({"review": None}, "unverified"),
    ({"review": "absent.json"}, "unverified"),
    ({"goal": "../outside.html"}, "unlocatable"),
])
def test_rejected_pointer_preserves_original_bytes(project, override, reason):
    root, digest = project
    before = (root / "memory.json").read_bytes()
    result = promote(root, digest, **override)
    assert result.returncode != 0
    assert reason in result.stderr
    assert (root / "memory.json").read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("status", "proposed"), ("target_pointer", "target.html"),
    ("target_sha256", "0" * 64), ("provenance", {}), ("id", ""),
    ("record_type", "Claim"),
])
def test_unbound_or_unreviewed_evidence_cannot_promote(project, field, value):
    root, digest = project
    proof = json.loads((root / "review.json").read_text())
    proof[field] = value
    (root / "review.json").write_text(json.dumps(proof))
    before = (root / "memory.json").read_bytes()
    result = promote(root, digest)
    assert result.returncode != 0
    assert "unverified" in result.stderr
    assert (root / "memory.json").read_bytes() == before


@pytest.mark.parametrize("status,kind,proof_status", [
    ("accepted", "Decision", "accepted"),
    ("verified", "Review", "verified"),
])
def test_bound_pointer_promotes_without_source_copy(project, status, kind, proof_status):
    root, digest = project
    proof = json.loads((root / "review.json").read_text())
    proof.update(record_type=kind, status=proof_status)
    (root / "review.json").write_text(json.dumps(proof))
    result = promote(root, digest, status=status)
    assert result.returncode == 0, result.stderr
    data = json.loads((root / "memory.json").read_text())
    goal = data["current_goal"]
    assert goal["pointer"] == "target.html#approved"
    assert goal["status"] == status and goal["integrity_status"] == "valid"
    assert goal["revision_sha256"] == digest
    assert goal["review_pointer"] == "review.json"
    assert goal["review_sha256"] == hashlib.sha256((root / "review.json").read_bytes()).hexdigest()
    assert "Checked" not in json.dumps(data)
    assert data["custom"] == "preserve"


def test_review_cannot_accept_a_pointer(project):
    root, digest = project
    proof = json.loads((root / "review.json").read_text())
    proof.update(record_type="Review", status="verified")
    (root / "review.json").write_text(json.dumps(proof))
    before = (root / "memory.json").read_bytes()
    result = promote(root, digest)
    assert result.returncode != 0
    assert "unverified" in result.stderr
    assert (root / "memory.json").read_bytes() == before


def test_atomic_transaction_rejects_invalid_snapshot_after_valid_goal(project):
    root, digest = project
    before = (root / "memory.json").read_bytes()
    result = run(root, "--goal", "target.html#approved", "--status", "accepted",
                 "--goal-hash", digest, "--review", "review.json",
                 "--snapshot-hash", "invalid")
    assert result.returncode != 0
    assert "unverified" in result.stderr
    assert (root / "memory.json").read_bytes() == before


def test_snapshot_requires_matching_source_and_review(project):
    root, digest = project
    result = run(root, "--snapshot-hash", digest, "--snapshot-source", "target.html#approved",
                 "--snapshot-review", "review.json", "--snapshot-id", "S-1")
    assert result.returncode == 0, result.stderr
    snapshot = json.loads((root / "memory.json").read_text())["snapshot_hash"]
    assert snapshot["value"] == digest and snapshot["integrity_status"] == "valid"
    assert snapshot["source"] == "target.html#approved" and snapshot["snapshot_id"] == "S-1"


def test_legacy_classifications_do_not_delete_or_reapprove(project):
    root, digest = project
    legacy = [
        {"pointer": "missing.html", "status": "accepted", "id": "old-1"},
        {"pointer": "target.html#missing", "status": "open"},
        {"pointer": "target.html#approved", "status": "accepted", "revision_sha256": "0" * 64},
        {"pointer": "target.html#approved", "status": "accepted", "revision_sha256": digest},
    ]
    memory = root / "memory.json"
    memory.write_text(json.dumps({"schema_version": 1, "approved_decision_pointers": legacy}))
    before = memory.read_bytes()
    checked = run(root, "--check")
    assert checked.returncode == 0, checked.stderr
    assert [r["integrity_status"] for r in json.loads(checked.stdout)["classifications"]] == [
        "unlocatable", "unlocatable", "stale", "unverified"]
    assert memory.read_bytes() == before
    assert promote(root, digest).returncode == 0
    after = json.loads(memory.read_text())["approved_decision_pointers"]
    assert len(after) == len(legacy)
    for original, annotated in zip(legacy, after):
        assert all(annotated[key] == value for key, value in original.items())
        assert annotated["integrity_status"] != "valid"


def test_changed_review_invalidates_prior_promotion(project):
    root, digest = project
    assert promote(root, digest).returncode == 0
    (root / "review.json").write_text('{}')
    result = run(root, "--check")
    assert result.returncode == 0
    assert json.loads(result.stdout)["classifications"][0]["integrity_status"] == "stale"


def test_no_arguments_is_byte_preserving_noop(project):
    root, _ = project
    before = (root / "memory.json").read_bytes()
    result = run(root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["changed"] is False
    assert (root / "memory.json").read_bytes() == before


def test_replace_failure_retains_memory_and_removes_temporary_file(project, monkeypatch):
    root, _ = project
    spec = importlib.util.spec_from_file_location("memory_updater", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    memory = root / "memory.json"
    before = memory.read_bytes()
    paths_before = set(root.iterdir())

    def fail_replace(source, destination):
        assert Path(destination) == memory
        assert json.loads(Path(source).read_text()) == {"schema_version": 1}
        raise OSError("simulated replace failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        module.atomic_write(memory, {"schema_version": 1})
    assert memory.read_bytes() == before
    assert set(root.iterdir()) == paths_before


def test_legacy_snapshot_cannot_claim_another_hash_algorithm(project):
    root, digest = project
    result = run(root, "--snapshot-hash", digest, "--snapshot-source", "target.html#approved",
                 "--snapshot-review", "review.json")
    assert result.returncode == 0, result.stderr
    memory = root / "memory.json"
    data = json.loads(memory.read_text())
    data["snapshot_hash"]["algorithm"] = "md5"
    memory.write_text(json.dumps(data))
    before = memory.read_bytes()
    result = run(root, "--check")
    assert json.loads(result.stdout)["classifications"][0]["integrity_status"] == "unverified"
    assert memory.read_bytes() == before


def test_open_unresolved_goal_is_not_promoted(project):
    root, _ = project
    result = run(root, "--goal", "pending.html", "--status", "open")
    assert result.returncode == 0, result.stderr
    goal = json.loads((root / "memory.json").read_text())["current_goal"]
    assert goal["status"] == "open" and goal["integrity_status"] == "unlocatable"


def test_snapshot_without_review_preserves_bytes(project):
    root, digest = project
    before = (root / "memory.json").read_bytes()
    result = run(root, "--snapshot-hash", digest, "--snapshot-source", "target.html#approved")
    assert result.returncode != 0 and "unverified" in result.stderr
    assert (root / "memory.json").read_bytes() == before


def test_symlink_outside_root_is_rejected(project, tmp_path):
    root, digest = project
    # The allowed project is a child; target bytes exist but are outside it.
    child = root / "child"
    child.mkdir()
    (child / "memory.json").write_bytes(b'{"schema_version":1}\n')
    (child / "target.html").symlink_to(root / "target.html")
    before = (child / "memory.json").read_bytes()
    result = promote(child, digest)
    assert result.returncode != 0 and "unlocatable" in result.stderr
    assert (child / "memory.json").read_bytes() == before


def test_failed_new_memory_update_creates_no_file(project):
    root, _ = project
    memory = root / "new" / "index.json"
    result = subprocess.run(
        [sys.executable, str(UPDATER), "--root", str(root), "--memory", str(memory),
         "--goal", "target.html#approved", "--status", "accepted"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not memory.parent.exists()


def test_check_cannot_apply_updates(project):
    root, _ = project
    before = (root / "memory.json").read_bytes()
    result = run(root, "--check", "--goal", "missing.html", "--status", "open")
    assert result.returncode != 0
    assert (root / "memory.json").read_bytes() == before


def test_recheck_cannot_write_newly_stale_accepted_pointer(project, monkeypatch):
    root, digest = project
    spec = importlib.util.spec_from_file_location("memory_updater", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real_check = module.checked_bytes
    before = (root / "memory.json").read_bytes()

    def check_then_change(*args):
        content = real_check(*args)
        (root / "target.html").write_text('<h1 id="approved">New revision</h1>')
        return content

    monkeypatch.setattr(module, "checked_bytes", check_then_change)
    monkeypatch.setattr(sys, "argv", [str(UPDATER), "--root", str(root), "--memory", str(root / "memory.json"),
                                     "--goal", "target.html#approved", "--status", "accepted",
                                     "--goal-hash", digest, "--review", "review.json"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code != 0
    assert (root / "memory.json").read_bytes() == before


def test_malformed_legacy_status_is_classified_without_deleting_it(project):
    root, digest = project
    memory = root / "memory.json"
    legacy = {"pointer": "target.html#approved", "revision_sha256": digest, "status": ["accepted"]}
    memory.write_text(json.dumps({"schema_version": 1, "unresolved_pointers": [legacy]}))
    before = memory.read_bytes()
    result = run(root, "--check")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["classifications"][0]["integrity_status"] == "unverified"
    assert memory.read_bytes() == before
    assert promote(root, digest).returncode == 0
    assert json.loads(memory.read_text())["unresolved_pointers"][0]["status"] == ["accepted"]
