# tests/test_parse_markdown.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from parse_markdown import parse_markdown

SAMPLE = """---
title: 견본
---

## 크기

트레이 조각 길이의 중앙값은 1.19 m 입니다.

- 조각 수는 17,259개입니다.

## Relations

- supersedes [[앞선 결정]]
- 그냥 문장인데 [[다른 문서]] 를 가리킵니다
"""


def test_소제목을_줄번호와_함께_뽑는다():
    parsed = parse_markdown(SAMPLE)
    titles = [section["title"] for section in parsed["sections"]]
    assert titles == ["크기", "Relations"]
    assert parsed["sections"][0]["line"] == 5


def test_문장에_값과_줄번호가_붙는다():
    parsed = parse_markdown(SAMPLE)
    값문장 = [s for s in parsed["statements"] if "1.19" in s["text"]]
    assert len(값문장) == 1
    assert 값문장[0]["line"] == 7
    assert 값문장[0]["section"] == "크기"


def test_관계는_낱말이_붙은_줄만_잡는다():
    parsed = parse_markdown(SAMPLE)
    relations = [link for link in parsed["links"] if link["relation"]]
    mentions = [link for link in parsed["links"] if not link["relation"]]
    assert [(r["relation"], r["target"]) for r in relations] == [("supersedes", "앞선 결정")]
    assert [m["target"] for m in mentions] == ["다른 문서"]


def test_문장_이름표를_자르지_않는다():
    long_line = "짧은 앞말 " + "가" * 500 + " 끝에 숫자 42개"
    parsed = parse_markdown("## 절\n\n" + long_line + "\n")
    assert parsed["statements"][0]["text"].endswith("42개")
