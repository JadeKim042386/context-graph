"""Explicit capture/resume contract; no host hooks, network, or actual memory writes."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/knowledge-engineering/scripts"
STORE = "knowledge-base/_ops/session-events-v3"
CONFIG = "knowledge-base/_ops/session-capture.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def project(root):
    (root / "knowledge").mkdir(parents=True)
    (root / "knowledge/result.html").write_text('<h1 id="result">BODY_NOT_FOR_OUTPUT</h1>')
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "knowledge/result.html"], check=True, capture_output=True)
    cfg = root / CONFIG
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"schema_version": 1, "enabled": True,
        "project_id": "PRJ-" + sha(str(root.resolve()).encode())[:16],
        "include_globs": ["knowledge/**"], "capture_content": False,
        "capture_commands": False, "capture_untracked": False, "tracked_paths_only": True}))
    return root


def payload(root, session=1, invocation=1, attribution=None):
    data = {"schema_version": 1,
        "session_id": f"00000000-0000-4000-8000-{session:012d}",
        "invocation_id": f"00000000-0000-4000-8000-{invocation:012d}",
        "occurred_at": "2026-09-25T01:00:00Z",
        "artifact_pointers": [{"pointer": "knowledge/result.html#result",
                               "revision_sha256": sha((root / "knowledge/result.html").read_bytes())}],
        "required_constraints": ["no_push", "no_commit"], "next_actions": ["review_evidence"]}
    if attribution is not None:
        data["schema_version"] = 2
        data["attribution"] = attribution
    return data


def run(root, data=None, event="pre_compact", runtime="codex", cwd=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": "/unrelated", "KNOWLEDGE_MAP_CONFIG": "/unrelated/config"}
    args = [sys.executable, "-B", str(SCRIPTS / "record_session_event.py"), "capture",
            "--root", str(root), "--runtime", runtime, "--event", event]
    result = subprocess.run(args, input=data if isinstance(data, str) else json.dumps(data),
                            cwd=cwd or root, env=env, capture_output=True, text=True)
    assert result.stdout, result.stderr
    return result, json.loads(result.stdout)


def handoff(root, *, session_id=None, runtime=None, invocation_ids=None,
            agent_instance_id=None, task_id=None, assignment_id=None,
            include_attribution=False):
    args = [sys.executable, "-B", str(SCRIPTS / "build_task_continuity.py"),
            "--root", str(root), "--session-handoff"]
    if session_id is not None:
        args += ["--session-id", session_id]
    if runtime is not None:
        args += ["--session-runtime", runtime]
    if invocation_ids == []:
        args += ["--task-invocation-id", ""]
    for invocation_id in invocation_ids or []:
        args += ["--task-invocation-id", invocation_id]
    for flag, value in (("--agent-instance-id", agent_instance_id), ("--task-id", task_id),
                        ("--assignment-id", assignment_id)):
        if value is not None:
            args += [flag, value]
    if include_attribution:
        args += ["--include-attribution"]
    result = subprocess.run(args, cwd=root,
                            capture_output=True, text=True)
    assert result.stdout, result.stderr
    return result, json.loads(result.stdout)


def bytes_tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_two_sessions_compact_close_replay_and_readonly_handoff(tmp_path):
    root = project(tmp_path)
    initial = bytes_tree(root)
    first, a = run(root, payload(root))
    assert first.returncode == 0 and a["status"] == "captured"
    captured = bytes_tree(root)
    second, replay = run(root, payload(root))
    assert second.returncode == 0 and replay["status"] == "duplicate"
    assert bytes_tree(root) == captured
    assert run(root, payload(root, invocation=2), event="session_end")[0].returncode == 0
    assert run(root, payload(root, session=2), runtime="claude-code", event="post_compact")[0].returncode == 0
    before = bytes_tree(root)
    result, pack = handoff(root)
    again, _ = handoff(root)
    assert result.returncode == 0 and result.stdout == again.stdout
    assert pack["pack_status"] == "ready" and pack["included_count"] == 3
    assert len({i["session_id"] for i in pack["items"]}) == 2
    assert {i["event_type"] for i in pack["items"]} == {"pre_compact", "post_compact", "session_end"}
    assert all(i["integrity_status"] == "valid" and not i["applicable"] for i in pack["items"])
    assert not pack["promotion_performed"] and pack["read_only"]
    assert all(i["review_state"] == "not_reviewed" for i in pack["items"])
    assert bytes_tree(root) == before
    assert all(before[k] == v for k, v in initial.items())
    assert not (root / "knowledge-base/_ops/memory").exists()
    assert "BODY_NOT_FOR_OUTPUT" not in result.stdout and str(root) not in result.stdout
    for i in pack["items"]:
        raw = (root / i["pointer"]).read_bytes()
        assert sha(raw) == i["revision_sha256"]
        record = json.loads(raw)
        assert record["status"] == "provisional" and record["schema_version"] == 3
    assert payload(root)["session_id"] not in raw.decode()


def test_scoped_handoff_filters_before_limits_and_keeps_selection_provisional(tmp_path):
    root = project(tmp_path)
    assert run(root, payload(root, session=1, invocation=1))[0].returncode == 0
    assert run(root, payload(root, session=1, invocation=2), event="session_end")[0].returncode == 0
    assert run(root, payload(root, session=2, invocation=3), runtime="claude-code")[0].returncode == 0
    session_id = payload(root, session=1, invocation=1)["session_id"]
    invocation_id = payload(root, session=1, invocation=1)["invocation_id"]
    result, pack = handoff(root, session_id=session_id, runtime="codex",
                           invocation_ids=[invocation_id])
    assert result.returncode == 0
    assert pack["total_count"] == pack["included_count"] == 1
    assert pack["omitted_count"] == 0
    assert pack["selection"]["mode"] == "session_and_invocations"
    assert pack["selection"]["scope_matched"] is True
    assert pack["selection"]["missing_invocation_count"] == 0
    assert all(item["runtime"] == "codex" for item in pack["items"])
    assert all(item["session_id"] != payload(root, session=2, invocation=3)["session_id"] for item in pack["items"])
    assert all(not item["applicable"] for item in pack["items"])
    assert session_id not in result.stdout and invocation_id not in result.stdout


def test_attributed_capture_is_opt_in_and_legacy_events_remain_unknown(tmp_path):
    root = project(tmp_path)
    attr = {"agent_instance_id": "00000000-0000-4000-8000-000000000101",
            "task_id": "00000000-0000-4000-8000-000000000102",
            "assignment_id": "00000000-0000-4000-8000-000000000103",
            "reassigned_from_event_id": None}
    result, out = run(root, payload(root, attribution=attr))
    assert result.returncode == 0 and out["status"] == "captured"
    record = json.loads(next((root / STORE).glob("*.json")).read_text())
    assert record["schema_version"] == 4
    assert set(record["attribution"]) == {"agent_instance_id", "task_id", "assignment_id",
                                           "reassigned_from_event_id", "basis"}
    import jsonschema
    jsonschema.validate(record, json.loads((SCRIPTS.parent / "schemas/session-event-v4.schema.json").read_text()))
    session_id = payload(root)["session_id"]
    result, pack = handoff(root, session_id=session_id, runtime="codex",
                           invocation_ids=[payload(root)["invocation_id"]],
                           agent_instance_id=attr["agent_instance_id"], task_id=attr["task_id"],
                           assignment_id=attr["assignment_id"])
    assert result.returncode == 0 and pack["items"][0]["actor_state"] == "declared"
    assert pack["items"][0]["attribution"]["basis"] == "caller_supplied"

    legacy_root = project(tmp_path / "legacy")
    assert run(legacy_root, payload(legacy_root))[0].returncode == 0
    result, pack = handoff(legacy_root, include_attribution=True)
    assert result.returncode == 0 and pack["items"][0]["actor_state"] == "actor_unknown"
    assert pack["items"][0]["attribution"] is None


def test_attribution_reassignment_requires_existing_v4_predecessor(tmp_path):
    root = project(tmp_path)
    first = {"agent_instance_id": "00000000-0000-4000-8000-000000000111",
             "task_id": "00000000-0000-4000-8000-000000000112",
             "assignment_id": "00000000-0000-4000-8000-000000000113",
             "reassigned_from_event_id": None}
    assert run(root, payload(root, attribution=first))[0].returncode == 0
    event = json.loads(next((root / STORE).glob("*.json")).read_text())
    successor = {**first, "agent_instance_id": "00000000-0000-4000-8000-000000000114",
                 "assignment_id": "00000000-0000-4000-8000-000000000115",
                 "reassigned_from_event_id": event["event_id"]}
    result, out = run(root, payload(root, invocation=2, attribution=successor), event="session_end")
    assert result.returncode == 0 and out["status"] == "captured"
    invalid = {**successor, "reassigned_from_event_id": "SEV-" + "f" * 64}
    result, out = run(root, payload(root, invocation=3, attribution=invalid))
    assert result.returncode == 2 and out["reason"] in {"invalid_attribution", "assignment_conflict"}


def test_attribution_relation_loss_is_partial_and_duplicate_stays_acknowledged(tmp_path):
    root = project(tmp_path)
    first = {"agent_instance_id": "00000000-0000-4000-8000-000000000121",
             "task_id": "00000000-0000-4000-8000-000000000122",
             "assignment_id": "00000000-0000-4000-8000-000000000123",
             "reassigned_from_event_id": None}
    assert run(root, payload(root, attribution=first))[0].returncode == 0
    predecessor = json.loads(next((root / STORE).glob("*.json")).read_text())
    successor = {**first, "agent_instance_id": "00000000-0000-4000-8000-000000000124",
                 "assignment_id": "00000000-0000-4000-8000-000000000125",
                 "reassigned_from_event_id": predecessor["event_id"]}
    successor_result, successor_out = run(root, payload(root, invocation=2, attribution=successor), event="session_end")
    assert successor_result.returncode == 0 and successor_out["status"] == "captured"
    repeated_result, repeated_out = run(root, payload(root, invocation=2, attribution=successor), event="pre_compact")
    assert repeated_result.returncode == 0 and repeated_out["status"] == "captured"
    predecessor_path = root / STORE / f"{predecessor['event_id']}.json"
    predecessor_path.unlink()
    result, pack = handoff(root, include_attribution=True)
    assert result.returncode == 0 and pack["pack_status"] == "partial"
    assert pack["items"][0]["attribution_status"] == "unverified"
    retry, out = run(root, payload(root, invocation=2, attribution=successor), event="session_end")
    assert retry.returncode == 0 and out["status"] == "duplicate"


def test_same_assignment_cannot_change_actor(tmp_path):
    root = project(tmp_path)
    base = {"agent_instance_id": "00000000-0000-4000-8000-000000000131",
            "task_id": "00000000-0000-4000-8000-000000000132",
            "assignment_id": "00000000-0000-4000-8000-000000000133",
            "reassigned_from_event_id": None}
    assert run(root, payload(root, attribution=base))[0].returncode == 0
    conflict = {**base, "agent_instance_id": "00000000-0000-4000-8000-000000000134"}
    result, out = run(root, payload(root, invocation=2, attribution=conflict), event="session_end")
    assert result.returncode == 2 and out["reason"] == "assignment_conflict"


@pytest.mark.parametrize("kwargs", [
    {"session_id": None, "runtime": "codex"},
    {"session_id": "bad", "runtime": "codex"},
    {"session_id": "00000000-0000-4000-8000-000000000001", "runtime": "other"},
    {"session_id": "00000000-0000-4000-8000-000000000001", "runtime": "codex", "invocation_ids": []},
])
def test_invalid_scoped_selection_fails_without_echoing_identifiers(tmp_path, kwargs):
    root = project(tmp_path)
    result, pack = handoff(root, **kwargs)
    assert result.returncode == 2 and pack["reason"] == "invalid_selection" and not pack["items"]
    assert "00000000-0000-4000-8000-000000000001" not in result.stdout


@pytest.mark.parametrize("change", ["prompt", "gold", "bad_hash", "missing_anchor", "external", "many", "id", "time", "duplicate_keys", "oversize"])
def test_invalid_or_unsafe_payload_never_writes_or_echoes(tmp_path, change):
    root = project(tmp_path)
    data = payload(root)
    if change in {"prompt", "gold"}: data[change] = "PRIVATE_SENTINEL"
    elif change == "bad_hash": data["artifact_pointers"][0]["revision_sha256"] = "0" * 64
    elif change == "missing_anchor": data["artifact_pointers"][0]["pointer"] = "knowledge/result.html#absent"
    elif change == "external": data["artifact_pointers"][0]["pointer"] = "../PRIVATE_SENTINEL"
    elif change == "many": data["artifact_pointers"] *= 9
    elif change == "id": data["session_id"] = "PRIVATE_SENTINEL"
    elif change == "time": data["occurred_at"] = "bad"
    elif change == "duplicate_keys": data = '{"schema_version":1,"schema_version":1}'
    else: data = " " * 20000
    before = bytes_tree(root)
    result, out = run(root, data)
    assert result.returncode == 2 and out["status"] == "unverified"
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert bytes_tree(root) == before


@pytest.mark.parametrize("change,reason", [("missing", "missing_config"), ("malformed", "invalid_config"),
    ("disabled", "capture_disabled"), ("foreign", "project_binding_mismatch"), ("privacy", "unsafe_config")])
def test_unconfigured_and_invalid_configuration_are_explicit(tmp_path, change, reason):
    root = project(tmp_path)
    cfg = root / CONFIG
    data = json.loads(cfg.read_text())
    if change == "missing": cfg.unlink()
    elif change == "malformed": cfg.write_text("{broken")
    else:
        if change == "disabled": data["enabled"] = False
        if change == "foreign": data["project_id"] = "PRJ-foreign"
        if change == "privacy": data["capture_content"] = True
        cfg.write_text(json.dumps(data))
    before = bytes_tree(root)
    result, out = run(root, payload(root))
    assert result.returncode == 2 and out["reason"] == reason
    result, pack = handoff(root)
    assert result.returncode == 2 and pack["items"] == [] and pack["reason"] == reason
    assert bytes_tree(root) == before


def test_project_isolation_and_copied_event_are_fail_closed(tmp_path):
    a, b = project(tmp_path / "a"), project(tmp_path / "b")
    assert run(a, payload(a))[0].returncode == 0
    before = bytes_tree(b)
    result, out = run(b, payload(b), cwd=a)
    assert result.returncode == 2 and out["reason"] == "cwd_mismatch"
    assert bytes_tree(b) == before
    assert handoff(b)[1]["pack_status"] == "empty"
    source = next((a / STORE).glob("*.json"))
    (b / STORE).mkdir()
    (b / STORE / source.name).write_bytes(source.read_bytes())
    result, pack = handoff(b)
    assert result.returncode == 2 and pack["items"] == [] and pack["reason"] == "invalid_event"


def test_replay_conflict_preserves_original_bytes(tmp_path):
    root = project(tmp_path)
    assert run(root, payload(root))[0].returncode == 0
    before = bytes_tree(root)
    data = payload(root)
    data["next_actions"] = ["request_approval"]
    result, out = run(root, data)
    assert result.returncode == 2 and out["reason"] == "event_id_conflict"
    assert bytes_tree(root) == before


@pytest.mark.parametrize("change,state", [("bytes", "stale"), ("delete", "unlocatable"), ("rename", "unlocatable")])
def test_session_pointer_drift_is_visible_not_promoted(tmp_path, change, state):
    root = project(tmp_path)
    assert run(root, payload(root))[0].returncode == 0
    target = root / "knowledge/result.html"
    if change == "bytes": target.write_text('<h1 id="result">Changed</h1>')
    elif change == "delete": target.unlink()
    else: target.rename(target.with_name("renamed.html"))
    result, pack = handoff(root)
    assert result.returncode == 0 and pack["pack_status"] == "partial"
    assert pack["items"][0]["integrity_status"] == state
    assert not pack["items"][0]["applicable"]


def test_corrupt_event_and_symlink_store_do_not_get_silently_skipped(tmp_path):
    root = project(tmp_path / "a")
    assert run(root, payload(root))[0].returncode == 0
    path = next((root / STORE).glob("*.json"))
    path.write_text("{broken")
    before = bytes_tree(root)
    result, pack = handoff(root)
    assert result.returncode == 2 and pack["items"] == []
    assert run(root, payload(root, invocation=2))[0].returncode == 2
    assert bytes_tree(root) == before
    other = project(tmp_path / "b")
    (other / STORE).symlink_to(root / STORE, target_is_directory=True)
    assert run(other, payload(other))[0].returncode == 2
    assert handoff(other)[0].returncode == 2


def test_payload_and_store_are_bounded_without_partial_publication(tmp_path):
    root = project(tmp_path)
    target = root / "knowledge/result.html"
    target.write_bytes(b"x" * 262145)
    before = bytes_tree(root)
    assert run(root, payload(root))[0].returncode == 2
    assert bytes_tree(root) == before


def test_event_contract_schema_and_configuration_revision(tmp_path):
    import jsonschema
    root = project(tmp_path)
    assert run(root, payload(root))[0].returncode == 0
    record = json.loads(next((root / STORE).glob("*.json")).read_text())
    schema = SCRIPTS.parent / "schemas/session-event-v3.schema.json"
    assert schema.is_file(), "explicit event schema is missing"
    jsonschema.validate(record, json.loads(schema.read_text()))
    invalid = {**record, "raw_prompt": "PRIVATE_SENTINEL"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, json.loads(schema.read_text()))
    cfg = root / CONFIG
    cfg.write_text(cfg.read_text() + "\n")
    result, pack = handoff(root)
    assert result.returncode == 0 and pack["pack_status"] == "partial"
    assert pack["items"][0]["integrity_status"] == "unverified"


def test_concurrent_identical_delivery_publishes_one_complete_record(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    root = project(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: run(root, payload(root)), range(4)))
    assert all(r.returncode == 0 for r, _ in results)
    assert sorted(d["status"] for _, d in results) == ["captured", "duplicate", "duplicate", "duplicate"]
    assert len(list((root / STORE).iterdir())) == 1
    assert handoff(root)[1]["included_count"] == 1


def test_store_budget_and_omission_are_explicit(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import session_events
    for number in range(128):
        result = session_events.capture(root, "pre_compact", "codex", json.dumps(payload(root, invocation=number)).encode())
        assert result["status"] == "captured"
    before = bytes_tree(root)
    result = session_events.capture(root, "session_end", "codex", json.dumps(payload(root, invocation=129)).encode())
    assert result["status"] == "unverified" and result["reason"] == "journal_limit"
    pack = session_events.handoff(root)
    assert pack["pack_status"] == "partial"
    assert (pack["total_count"], pack["included_count"], pack["omitted_count"]) == (128, 16, 112)
    assert len(session_events.encode(pack)) <= 32768
    assert bytes_tree(root) == before


def test_explicit_pointer_still_respects_tracked_only_config(tmp_path):
    root = project(tmp_path)
    subprocess.run(["git", "-C", str(root), "rm", "--cached", "knowledge/result.html"], check=True, capture_output=True)
    before = bytes_tree(root)
    result, out = run(root, payload(root))
    assert result.returncode == 2 and out["reason"] == "pointer_not_verified"
    assert bytes_tree(root) == before
