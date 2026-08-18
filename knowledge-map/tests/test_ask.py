import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ask import USAGE, build_graphify_command, stale_documents, truncation_notice


def test_finds_documents_newer_than_the_map(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "a.md").write_text("body", encoding="utf-8")
    map_path = tmp_path / "graph.json"
    map_path.write_text("{}", encoding="utf-8")
    assert stale_documents([str(source)], str(map_path)) == []
    time.sleep(0.01)
    (source / "b.md").write_text("new body", encoding="utf-8")
    assert stale_documents([str(source)], str(map_path)) == ["b"]


def test_a_missing_map_counts_everything_as_stale(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "a.md").write_text("body", encoding="utf-8")
    assert stale_documents([str(source)], str(tmp_path / "missing.json")) == ["(no map)"]


def test_the_query_command_carries_the_budget(tmp_path):
    command = build_graphify_command("query", ["chunk criterion"], "C:/maps/graph.json", 20000)
    assert command[:2] == ["graphify", "query"]
    assert "--budget" in command and "20000" in command
    assert "--graph" in command and "C:/maps/graph.json" in command


def test_path_finding_does_not_carry_a_budget():
    command = build_graphify_command("path", ["a", "b"], "C:/maps/graph.json", 20000)
    assert command[:2] == ["graphify", "path"]
    assert "--budget" not in command


def test_an_answer_that_fills_the_budget_is_reported():
    truncated_answer = "... budget 20000 tokens, 12 results cut by budget ..."
    assert "Narrow" in truncation_notice(truncated_answer)


def test_a_short_answer_gets_no_notice():
    assert truncation_notice("The median is 1.19 m (a.md:8)") == ""


def test_the_usage_text_tells_you_to_ask_narrowly():
    assert "narrowly" in USAGE
