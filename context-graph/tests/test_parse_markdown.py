# tests/test_parse_markdown.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from parse_markdown import parse_markdown

SAMPLE = """---
title: Sample
---

## Size

The median tray piece length is 1.19 m.

- There are 17,259 pieces.

## Relations

- supersedes [[earlier decision]]
- just a sentence pointing at [[another document]]
"""


def test_headings_come_with_line_numbers():
    parsed = parse_markdown(SAMPLE)
    titles = [section["title"] for section in parsed["sections"]]
    assert titles == ["Size", "Relations"]
    assert parsed["sections"][0]["line"] == 5


def test_a_statement_carries_its_value_and_line_number():
    parsed = parse_markdown(SAMPLE)
    value_statements = [s for s in parsed["statements"] if "1.19" in s["text"]]
    assert len(value_statements) == 1
    assert value_statements[0]["line"] == 7
    assert value_statements[0]["section"] == "Size"


def test_only_lines_with_a_leading_word_count_as_relations():
    parsed = parse_markdown(SAMPLE)
    relations = [link for link in parsed["links"] if link["relation"]]
    mentions = [link for link in parsed["links"] if not link["relation"]]
    assert [(r["relation"], r["target"]) for r in relations] == [("supersedes", "earlier decision")]
    assert [m["target"] for m in mentions] == ["another document"]


def test_statement_labels_are_never_cut():
    long_line = "short opening " + "x" * 500 + " ending in 42 items"
    parsed = parse_markdown("## Section\n\n" + long_line + "\n")
    assert parsed["statements"][0]["text"].endswith("42 items")


def test_a_korean_relation_word_is_kept_and_named_in_english():
    parsed = parse_markdown("## Relations\n\n- 대체함 [[earlier decision]]\n- 참고 [[related fact]]\n")
    relations = [(link["relation"], link["target"]) for link in parsed["links"] if link["relation"]]
    assert relations == [("supersedes", "earlier decision"), ("relates_to", "related fact")]


def test_a_korean_word_outside_the_table_is_kept_as_written():
    parsed = parse_markdown("- 검토함 [[a decision]]\n")
    relations = [(link["relation"], link["target"]) for link in parsed["links"] if link["relation"]]
    assert relations == [("검토함", "a decision")]


def test_several_words_before_the_link_are_still_only_a_mention():
    parsed = parse_markdown("- this decision supersedes [[ADR 7]]\n")
    assert [link["relation"] for link in parsed["links"]] == [None]
