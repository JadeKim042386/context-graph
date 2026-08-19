import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ask import (USAGE, build_graphify_command, condense_answer, stale_documents,
                 truncation_notice)


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


RAW_ANSWER = """Traversal: BFS depth=2 | Start: ['Median 1.19 m.'] | 3 nodes found

NODE Tray Facts [src=facts/Tray.md loc=1 community=]
NODE Piece size: median 1.19 m. [src=facts/Tray.md loc=192 community=]
NODE Central Index [src= loc=None community=]
EDGE Piece size: median 1.19 m. --part_of []--> Tray Facts
"""


def test_the_answer_keeps_the_statement_with_its_line():
    condensed = condense_answer(RAW_ANSWER)
    assert "NODE Piece size: median 1.19 m." in condensed
    assert "[src=facts/Tray.md loc=192]" in condensed


def test_the_answer_drops_edges_and_nodes_with_no_location():
    condensed = condense_answer(RAW_ANSWER)
    assert "EDGE" not in condensed
    assert "Central Index" not in condensed
    assert "Traversal:" not in condensed


def test_the_documents_are_named_once_at_the_end():
    assert condense_answer(RAW_ANSWER).endswith("[also touched: Tray Facts]")


def test_an_unrecognised_answer_is_shown_as_it_came():
    assert condense_answer("graphify: no results") == "graphify: no results"


def test_the_matched_statement_comes_first():
    raw = ("Traversal: BFS depth=2 | Start: ['Piece size: median 1.19 m.'] | 2 nodes found\n"
           "NODE A neighbour statement. [src=facts/Tray.md loc=8 community=]\n"
           "NODE Piece size: median 1.19 m. [src=facts/Tray.md loc=192 community=]\n")
    assert condense_answer(raw).startswith("NODE Piece size: median 1.19 m.")


def test_the_document_tail_names_only_a_few():
    raw = "".join(f"NODE Doc {i} [src=d{i}.md loc=1 community=]\n" for i in range(7))
    raw += "NODE A statement. [src=d0.md loc=4 community=]\n"
    tail = condense_answer(raw).splitlines()[-1]
    assert tail.endswith("and 3 more]")
