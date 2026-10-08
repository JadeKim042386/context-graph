import hashlib
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import session_knowledge


def _project(root):
    return "PRJ-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]


def _root(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "knowledge-base" / "_ops").mkdir(parents=True)
    (root / "knowledge-base" / "_ops" / "session-capture.json").write_text(json.dumps({
        "schema_version": 1, "enabled": True, "project_id": _project(root),
        "include_globs": ["knowledge/**"], "tracked_paths_only": True,
        "capture_content": False, "capture_commands": False, "capture_untracked": False,
    }), encoding="utf-8")
    monkeypatch.chdir(root)
    return root


def test_session_knowledge_merges_once_and_splits_back(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    journal = root / "knowledge-base" / "_ops" / "session-events.jsonl"
    journal.write_text(json.dumps({"record_type": "SessionLifecycleEvent", "event_id": "SEV-1",
                                   "session_id": "session-key-1", "event_type": "session_end",
                                   "runtime": "claude-code", "record_sha256": "a" * 64}) + "\n",
                        encoding="utf-8")
    opened = session_knowledge.open_agent(root, session_id="raw-session", session_key="session-key-1",
                                          agent_instance_id="a1", task_id="t1", assignment_id="x1", role="analyst")
    assert opened["status"] == "opened"
    first = session_knowledge.merge_session(root, session_key="session-key-1")
    assert first["merged_count"] == 1
    second = session_knowledge.merge_session(root, session_key="session-key-1")
    assert second["merged_count"] == 0
    split = session_knowledge.split(root, session_key="session-key-1")
    assert split["total_count"] == 1
    assert split["items"][0]["promotion_state"] == "review_required"


def test_close_marks_state_and_never_promotes_canonical_memory(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    closed = session_knowledge.close_agent(root, session_id="raw-session", session_key="session-key-2",
                                            agent_instance_id="a1", task_id="t1", assignment_id="x1", role="analyst")
    assert closed["status"] == "closed"
    assert closed["merged_count"] == 0
    states = [json.loads(line) for line in (root / session_knowledge.REGISTRY).read_text().splitlines()]
    assert states[-1]["state"] == "closed"
    assert not (root / "knowledge-base" / "_ops" / "memory" / "index.json").exists()


def test_close_raw_session_id_matches_v3_event_encoding(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    project_id = _project(root)
    v3_key = session_knowledge.event_key([project_id, "raw-session"])
    journal = root / "knowledge-base" / "_ops" / "session-events.jsonl"
    journal.write_text(json.dumps({"record_type": "SessionLifecycleEvent", "event_id": "SEV-v3",
                                   "session_id": v3_key, "event_type": "session_end",
                                   "runtime": "codex", "record_sha256": "c" * 64}) + "\n", encoding="utf-8")
    closed = session_knowledge.close_agent(root, session_id="raw-session")
    assert closed["merged_count"] == 1


def test_unreviewed_replay_is_proposed_without_suppression(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    common = {"record_type": "SessionLifecycleEvent", "session_id": "s-replay",
              "event_type": "post_compact", "runtime": "codex",
              "content_fingerprint": "content-1", "artifact_pointers": [{"pointer": "knowledge/a.md"}]}
    journal = root / "knowledge-base" / "_ops" / "session-events.jsonl"
    journal.write_text("\n".join(json.dumps(dict(common, event_id=name, record_sha256=revision))
                                  for name, revision in (("SEV-a", "a" * 64), ("SEV-b", "b" * 64))) + "\n",
                        encoding="utf-8")
    result = session_knowledge.merge_session(root, session_key="s-replay")
    assert result["merged_count"] == 2
    assert result["consolidation"]["excluded_duplicate_count"] == 0
    assert result["consolidation"]["held_count"] == 2


def test_explicit_v3_replay_and_agent_roles_are_consolidated_separately(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    project_id = _project(root)
    session_key = session_knowledge.event_key([project_id, "raw-session"])
    agent_a = session_knowledge.selector_key(project_id, "agent", "a1")
    task_a = session_knowledge.selector_key(project_id, "task", "t1")
    assignment_a = session_knowledge.selector_key(project_id, "assignment", "x1", task_a)
    agent_b = session_knowledge.selector_key(project_id, "agent", "b1")
    task_b = session_knowledge.selector_key(project_id, "task", "t2")
    assignment_b = session_knowledge.selector_key(project_id, "assignment", "x2", task_b)
    session_knowledge.open_agent(root, session_id="raw-session", agent_instance_id="a1", task_id="t1",
                                assignment_id="x1", role="analyst")
    session_knowledge.open_agent(root, session_id="raw-session", agent_instance_id="b1", task_id="t2",
                                assignment_id="x2", role="editor")
    store = root / "knowledge-base" / "_ops" / "session-events-v3"
    store.mkdir(parents=True)
    def event(name, agent, task, assignment, fp):
        return {"record_type": "SessionLifecycleEvent", "event_id": name, "session_id": session_key,
                "event_type": "post_compact", "runtime": "codex", "record_sha256": name[-1] * 64,
                "content_fingerprint": fp, "artifact_pointers": [{"pointer": "knowledge/a.md"}],
                "attribution": {"agent_instance_id": agent, "task_id": task, "assignment_id": assignment}}
    (store / "SEV-a.json").write_text(json.dumps(event("SEV-a", agent_a, task_a, assignment_a, "same")), encoding="utf-8")
    (store / "SEV-b.json").write_text(json.dumps(event("SEV-b", agent_b, task_b, assignment_b, "same")), encoding="utf-8")
    result = session_knowledge.merge_session(root, session_key=session_key)
    assert result["merged_count"] == 2
    items = session_knowledge._read(root / session_knowledge.OVERLAY)
    assert {item["role_key"] for item in items} == {
        session_knowledge.selector_key(project_id, "role", "analyst"),
        session_knowledge.selector_key(project_id, "role", "editor")}
