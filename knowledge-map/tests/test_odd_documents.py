# tests/test_odd_documents.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from parse_markdown import parse_markdown

RELATIONS_뒤에_본문이_붙은_문서 = """## Relations

- relates_to [[다른 문서]]
- [2026-07-08] 이 날짜 조각은 관계가 아니라 문장입니다
- 처리량은 3,683개였습니다
"""


def test_날짜_조각을_관계로_잡지_않는다():
    parsed = parse_markdown(RELATIONS_뒤에_본문이_붙은_문서)
    relation_names = [link["relation"] for link in parsed["links"] if link["relation"]]
    assert relation_names == ["relates_to"]


def test_관계_절_뒤의_값도_문장으로_남는다():
    parsed = parse_markdown(RELATIONS_뒤에_본문이_붙은_문서)
    assert any("3,683" in statement["text"] for statement in parsed["statements"])


def test_빈_문서도_터지지_않는다():
    parsed = parse_markdown("")
    assert parsed == {"sections": [], "statements": [], "links": []}


def test_관계_줄_자체도_문장으로_남는다():
    # 관계로 잡힌 줄을 문장에서 빼 버리면, 관계 절 뒤에 본문이 이어 붙은 문서에서
    # 값이 든 문장을 통째로 잃습니다.
    parsed = parse_markdown(RELATIONS_뒤에_본문이_붙은_문서)
    assert any("relates_to" in statement["text"] for statement in parsed["statements"])
