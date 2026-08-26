# tests/test_odd_documents.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from parse_markdown import parse_markdown

# A real document that was mis-parsed once: a Relations section followed by
# prose. The Korean text is deliberate, the parser has to handle documents that
# are not written in English.
DOCUMENT_WITH_PROSE_AFTER_RELATIONS = """## Relations

- relates_to [[다른 문서]]
- [2026-07-08] 이 날짜 조각은 관계가 아니라 문장입니다
- 처리량은 3,683개였습니다
"""


def test_a_date_fragment_is_not_taken_for_a_relation():
    parsed = parse_markdown(DOCUMENT_WITH_PROSE_AFTER_RELATIONS)
    relation_names = [link["relation"] for link in parsed["links"] if link["relation"]]
    assert relation_names == ["relates_to"]


def test_values_after_the_relations_section_are_kept_as_statements():
    parsed = parse_markdown(DOCUMENT_WITH_PROSE_AFTER_RELATIONS)
    assert any("3,683" in statement["text"] for statement in parsed["statements"])


def test_an_empty_document_does_not_blow_up():
    parsed = parse_markdown("")
    assert parsed == {"sections": [], "statements": [], "links": []}


def test_a_line_that_is_nothing_but_a_relation_is_not_stored_twice():
    """It is already a link. Storing it as a statement as well puts the same fact in twice.

    The worry that used to keep it was that dropping it would lose the prose after the
    relations section. The test above shows it does not: scanning carries on line by line.
    """
    parsed = parse_markdown(DOCUMENT_WITH_PROSE_AFTER_RELATIONS)
    assert not any(statement["text"].startswith("relates_to")
                   for statement in parsed["statements"])
    assert any(link["relation"] == "relates_to" for link in parsed["links"])


def test_a_fence_is_only_closed_by_its_own_kind():
    """A ``` line inside a ~~~ block is code, not the end of the block."""
    parsed = parse_markdown("~~~\n```\nstill code\n~~~\n\nprose after with 42 items\n")
    texts = [statement["text"] for statement in parsed["statements"]]
    assert "still code" not in texts
    assert any("42 items" in text for text in texts)


def test_a_fence_left_open_does_not_swallow_the_rest_of_the_document():
    """A typo must cost one line, not half a note."""
    parsed = parse_markdown("intro line\n\n```\nsome code\n\nthe value is 0.66 m\n")
    assert any("0.66 m" in statement["text"] for statement in parsed["statements"])


def test_what_is_inside_a_closed_fence_stays_out():
    parsed = parse_markdown("```python\n# not a heading\nvalue = 1\n```\n\nreal prose\n")
    texts = [statement["text"] for statement in parsed["statements"]]
    assert texts == ["real prose"]
    assert parsed["sections"] == []


def test_an_orphan_fence_after_a_closed_one_does_not_eat_the_prose_before_it():
    """The stray marker is usually the last one, so taking out the first inverts the whole file.

    Removing the wrong marker turns the real closing marker into an opening one: the prose that
    carried the value is swallowed as code, and the code comes out as prose.
    """
    document = ("intro\n\n```\ncode A secret=1\n```\n\n"
                "prose B value 0.66 m\n\n```\ntail C\n")
    texts = [statement["text"] for statement in parse_markdown(document)["statements"]]
    assert any("0.66 m" in text for text in texts)
    assert not any("secret=1" in text for text in texts)


def test_a_four_backtick_block_may_hold_a_three_backtick_example():
    """The standard way to show a fence in markdown is to wrap it in a longer one."""
    parsed = parse_markdown("````\n```\nexample code\n```\n````\n\nreal prose\n")
    assert [statement["text"] for statement in parsed["statements"]] == ["real prose"]


def test_a_document_full_of_fence_mentions_still_builds():
    """Recovering from a stray fence must not walk the document once per mention."""
    document = "x\n" + "use ``` to open a fence\n" * 1200 + "```\ntail\n"
    assert len(parse_markdown(document)["statements"]) > 1000
