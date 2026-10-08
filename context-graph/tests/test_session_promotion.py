import hashlib
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills/knowledge-engineering/scripts/promote_session.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_check_and_apply_are_explicit_and_receipt_backed(tmp_path):
    target = tmp_path / "goal.html"
    target.write_text('<h1 id="ok">goal</h1>')
    target_hash = digest(target.read_bytes())
    review = {
        "schema_version": 1, "id": "REV-1", "record_type": "Decision", "revision": 1,
        "status": "accepted", "created_at": "2026-10-08T00:00:00Z", "updated_at": "2026-10-08T00:00:00Z",
        "provenance": {"agent": "curator", "activity_id": "review-1"},
        "target_pointer": "goal.html#ok", "target_sha256": target_hash,
    }
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review))
    review_hash = digest(review_path.read_bytes())
    memory = tmp_path / "memory.json"
    memory.write_bytes(b'{"schema_version":1}\n')
    expected = digest(memory.read_bytes())
    request = {
        "schema_version": 1, "record_type": "SessionPromotionRequest", "transaction_id": "tx-1",
        "project_id": "project-1", "created_at": "2026-10-08T00:00:00Z", "event_refs": [], "canonical_refs": [],
        "memory_pointer": "memory.json", "expected_memory_sha256": expected, "status": "proposed",
        "operations": [{"kind": "goal", "pointer": "goal.html#ok", "hash": target_hash, "status": "accepted", "review_pointer": "review.json"}],
    }
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical(request))
    request_hash = digest(request_path.read_bytes())
    review["promotion_request_sha256"] = request_hash
    review_path.write_text(json.dumps(review))
    review_hash = digest(review_path.read_bytes())

    def run(mode):
        return subprocess.run([sys.executable, str(SCRIPT), mode, "--root", str(tmp_path), "--request", str(request_path),
                               "--request-sha256", request_hash, "--approval", str(review_path), "--approval-sha256", review_hash],
                              capture_output=True, text=True)

    checked = run("check")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["changed"] is False
    applied = run("apply")
    assert applied.returncode == 0, applied.stderr
    assert json.loads((tmp_path / "memory.json").read_text())["current_goal"]["pointer"] == "goal.html#ok"
    assert (tmp_path / "knowledge-base/_ops/promotion-receipts/tx-1.prepared.json").exists()
    assert (tmp_path / "knowledge-base/_ops/promotion-receipts/tx-1.committed.json").exists()


def test_base_conflict_does_not_mutate_memory(tmp_path):
    memory = tmp_path / "memory.json"
    memory.write_bytes(b'{"schema_version":1}\n')
    request = {
        "schema_version": 1, "record_type": "SessionPromotionRequest", "transaction_id": "tx-2",
        "project_id": "project-1", "created_at": "2026-10-08T00:00:00Z", "event_refs": [], "canonical_refs": [],
        "memory_pointer": "memory.json", "expected_memory_sha256": "0" * 64, "status": "proposed",
        "operations": [{"kind": "goal", "pointer": "missing.html", "status": "open"}],
    }
    path = tmp_path / "request.json"
    path.write_bytes(canonical(request))
    approval = tmp_path / "review.json"
    approval.write_text(json.dumps({"status": "verified", "promotion_request_sha256": digest(path.read_bytes())}))
    result = subprocess.run([sys.executable, str(SCRIPT), "apply", "--root", str(tmp_path), "--request", str(path),
                             "--request-sha256", digest(path.read_bytes()), "--approval", str(approval),
                             "--approval-sha256", digest(approval.read_bytes())], capture_output=True, text=True)
    assert result.returncode == 3
    assert "base_conflict" in result.stderr
    assert memory.read_bytes() == b'{"schema_version":1}\n'
