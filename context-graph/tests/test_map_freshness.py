"""Content/revision freshness using temporary bound projects, not wall-clock sleeps."""
import json
import os
import sys
from pathlib import Path

import pytest

from test_project_binding import project, build, ask, command, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import build_map as builder


@pytest.fixture
def bound(tmp_path):
    root = project(tmp_path / "project", "OLD_VALUE")
    build(root)
    return root


@pytest.mark.parametrize("mutation,reason", [
    ("same_mtime", "source_content_changed"),
    ("deleted", "source_deleted"),
    ("renamed", "source_set_changed"),
    ("added", "source_added"),
])
def test_changed_sources_fail_closed_without_rebuild(bound, mutation, reason):
    source = bound / "knowledge/facts.md"
    previous_stat = source.stat()
    if mutation == "same_mtime":
        source.write_text(source.read_text().replace("OLD_VALUE", "NEW_VALUE"))
        os.utime(source, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
    elif mutation == "deleted": source.unlink()
    elif mutation == "renamed": source.rename(bound / "knowledge/renamed.md")
    else: (bound / "knowledge/new.md").write_text("# New\n\n- uniqueanswer NEW_VALUE.\n")
    before = {str(p): p.read_bytes() for p in bound.rglob("*") if p.is_file()}
    result, data = ask(bound)
    assert result.returncode == 2
    assert data["binding"]["status"] == "unverified"
    assert data["binding"]["reason"] == reason and data["hits"] == []
    assert before == {str(p): p.read_bytes() for p in bound.rglob("*") if p.is_file()}


def test_unchanged_bytes_are_verified_even_when_mtime_changes(bound):
    source = bound / "knowledge/facts.md"
    fingerprint = builder._fingerprint([str(source.parent)])
    previous_stat = source.stat()
    os.utime(source, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 10_000_000_000))
    assert builder._fingerprint([str(source.parent)]) == fingerprint
    result, data = ask(bound)
    assert result.returncode == 0 and len(data["hits"]) == 1
    assert data["binding"]["freshness_state"] == "verified"
    assert data["binding"]["source_snapshot_sha256"]


def test_fingerprint_detects_same_count_same_mtime_bytes_and_rename(bound):
    source = bound / "knowledge/facts.md"
    roots = [str(source.parent)]
    before = builder._fingerprint(roots)
    previous_stat = source.stat()
    source.write_text(source.read_text().replace("OLD_VALUE", "NEW_VALUE"))
    os.utime(source, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
    after = builder._fingerprint(roots)
    assert after != before
    assert not builder.unchanged_since_last_build(roots, str(bound / "map.json"))
    source.rename(source.with_name("renamed.md"))
    assert builder._fingerprint(roots) != after


@pytest.mark.parametrize("mutation,reason", [
    ("missing_snapshot", "freshness_unverified"),
    ("bad_snapshot", "invalid_source_snapshot"),
    ("stale_record", "map_records_changed"),
])
def test_map_snapshot_and_record_drift_are_not_trusted(bound, mutation, reason):
    path = bound / "map.json"
    data = json.loads(path.read_text())
    if mutation == "missing_snapshot": data.pop("source_snapshot", None)
    elif mutation == "bad_snapshot": data["source_snapshot"] = {"schema_version": 1, "files": []}
    else:
        node = next(n for n in data["nodes"] if n["kind"] == "statement")
        node["label"] = "uniqueanswer FABRICATED_VALUE."
    path.write_text(json.dumps(data))
    result, output = ask(bound)
    assert result.returncode == 2 and output["hits"] == []
    assert output["binding"]["reason"] == reason


def test_approved_rebuild_removes_old_records_after_rename(bound):
    source = bound / "knowledge/facts.md"
    source.rename(source.with_name("renamed.md"))
    build(bound)
    result, data = ask(bound)
    assert result.returncode == 0
    assert all(hit["source_file"].endswith("renamed.md") for hit in data["hits"])
    graph = json.loads((bound / "map.json").read_text())
    assert all(not n.get("source_file", "").endswith("facts.md") for n in graph["nodes"])
    assert graph["source_snapshot"]["files"][0]["path"].endswith("renamed.md")


def test_source_change_during_build_cannot_replace_previous_map(bound, monkeypatch):
    source = bound / "knowledge/facts.md"
    path = bound / "map.json"
    before = path.read_bytes()
    real_parse = builder.parse_markdown

    def parse_then_mutate(text):
        parsed = real_parse(text)
        source.write_text("# Facts\n\n- uniqueanswer CHANGED_DURING_BUILD.\n")
        return parsed

    monkeypatch.setattr(builder, "parse_markdown", parse_then_mutate)
    with pytest.raises(ValueError, match="source_changed_during_build"):
        builder.build_map([str(source.parent)], str(path))
    assert path.read_bytes() == before
    assert not (bound / "map.json.tmp").exists()


def test_normal_query_also_rejects_changed_bytes_before_graphify(bound):
    source = bound / "knowledge/facts.md"
    old = source.stat()
    source.write_text(source.read_text().replace("OLD_VALUE", "NEW_VALUE"))
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    result = command(bound, SCRIPTS / "ask.py", "--project-root", str(bound), "uniqueanswer")
    assert result.returncode == 2
    data = json.loads(result.stdout)
    assert data["hits"] == [] and data["binding"]["reason"] == "source_content_changed"
