# tests/test_parse_html.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from parse_html import parse_html

SAMPLE = """<html><head><title>견본 보고서</title>
<style>.x{color:red}</style></head>
<body>
<h2>크기</h2>
<p>트레이 조각 길이의 중앙값은 1.19 m 입니다.</p>
<svg><rect/><text>도식 안 글자</text></svg>
<script>var 버릴것 = 1;</script>
<ul><li>조각 수는 17,259개입니다.</li></ul>
<a href="다른문서.md">다른 문서</a>
</body></html>"""


def test_소제목과_문장을_줄번호와_함께_뽑는다():
    parsed = parse_html(SAMPLE)
    assert [s["title"] for s in parsed["sections"]] == ["크기"]
    assert parsed["sections"][0]["line"] == 4
    값문장 = [s for s in parsed["statements"] if "1.19" in s["text"]]
    assert 값문장[0]["line"] == 5


def test_그림_속_글자는_건지고_꾸밈은_버린다():
    texts = [s["text"] for s in parse_html(SAMPLE)["statements"]]
    assert "도식 안 글자" in texts
    assert not any("color:red" in t for t in texts)
    assert not any("버릴것" in t for t in texts)


def test_링크를_연결로_잡는다():
    links = parse_html(SAMPLE)["links"]
    assert [link["target"] for link in links] == ["다른문서.md"]
    assert links[0]["relation"] is None
