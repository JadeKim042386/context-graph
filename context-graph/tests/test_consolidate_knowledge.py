import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import consolidate_knowledge


def _overlay(root, items):
    path = root / consolidate_knowledge.OVERLAY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def _item(name, revision):
    return {"overlay_id": name, "source_event_id": "SEV-" + name, "source_store": "explicit",
            "source_pointer": "knowledge-base/_ops/session-events-v3/" + name + ".json",
            "source_revision_sha256": revision, "session_key": "s", "event_type": "session_end",
            "status": "provisional", "promotion_state": "review_required", "session_state": "closed"}


def test_unverified_duplicates_are_held_without_suppression(tmp_path):
    _overlay(tmp_path, [_item("one", "a" * 64), _item("two", "a" * 64), _item("three", "b" * 64)])
    result = consolidate_knowledge.compact(tmp_path)
    assert result["proposal_count"] == 1
    assert result["excluded_duplicate_count"] == 0
    projection = json.loads((tmp_path / consolidate_knowledge.PROJECTION).read_text())
    assert projection["items"] == []
    assert {item["overlay_id"] for item in projection["held_items"]} == {"one", "two", "three"}
    assert projection["quality"]["automatic_promotion"] is False
    assert projection["quality"]["automatic_deletion"] is False


def test_possible_overlap_is_retained_and_sent_to_review(tmp_path):
    first = _item("one", None)
    second = dict(first, overlay_id="two", source_event_id="SEV-two")
    _overlay(tmp_path, [first, second])
    result = consolidate_knowledge.plan(tmp_path)
    assert result["proposal_count"] == 1
    proposal = json.loads((tmp_path / consolidate_knowledge.PROPOSALS).read_text())
    assert proposal["kind"] == "possible_overlap"
    assert proposal["action"] == "retain_separately"
    assert not (tmp_path / consolidate_knowledge.PROJECTION).exists()
