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


def test_the_relation_line_itself_is_kept_as_a_statement():
    # Dropping relation lines from the statements loses every value-carrying
    # statement in documents that continue with prose after the relations section.
    parsed = parse_markdown(DOCUMENT_WITH_PROSE_AFTER_RELATIONS)
    assert any("relates_to" in statement["text"] for statement in parsed["statements"])
