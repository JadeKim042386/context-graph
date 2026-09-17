import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "context-graph" / "skills" / "knowledge-engineering" / "scripts" / "record_session_event.py"


def run_event(project: Path, event: str, payload: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--event", event],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )


def read_events(project: Path) -> list[dict]:
    path = project / "knowledge-base" / "_ops" / "session-events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_session_event_is_privacy_filtered_and_idempotent(tmp_path):
    payload = {
        "session_id": "opaque-session-123",
        "reason": "auto",
        "transcript_path": "/Users/example/private/transcript.jsonl",
        "prompt": "never store this prompt",
    }
    first = run_event(tmp_path, "pre_compact", payload)
    second = run_event(tmp_path, "pre_compact", payload)

    assert first.returncode == 0
    assert second.returncode == 0
    events = read_events(tmp_path)
    assert len(events) == 1
    record = events[0]
    assert record["event_type"] == "pre_compact"
    assert record["status"] == "provisional"
    assert record["session_id"] != payload["session_id"]
    assert "never store this prompt" not in json.dumps(record)
    assert "/Users/example" not in json.dumps(record)
    assert "transcript_path" not in record
    assert record["review_state"] == "not_reviewed"


def test_session_lifecycle_events_are_linked_without_promoting_memory(tmp_path):
    payload = {"session_id": "session-a", "reason": "prompt_input_exit"}
    assert run_event(tmp_path, "session_start", payload).returncode == 0
    assert run_event(tmp_path, "post_compact", payload).returncode == 0
    assert run_event(tmp_path, "session_end", payload).returncode == 0

    events = read_events(tmp_path)
    assert [event["event_type"] for event in events] == ["session_start", "post_compact", "session_end"]
    assert events[1]["supersedes_event_id"] == events[0]["event_id"]
    assert events[2]["supersedes_event_id"] == events[1]["event_id"]
    assert events[2]["status"] == "unverified"
    assert not (tmp_path / "knowledge-base" / "_ops" / "memory" / "index.json").exists()
