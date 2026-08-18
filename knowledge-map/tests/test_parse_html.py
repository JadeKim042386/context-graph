# tests/test_parse_html.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from parse_html import parse_html

SAMPLE = """<html><head><title>Sample report</title>
<style>.x{color:red}</style></head>
<body>
<h2>Size</h2>
<p>The median tray piece length is 1.19 m.</p>
<svg><rect/><text>text inside the diagram</text></svg>
<script>var dropped = 1;</script>
<ul><li>There are 17,259 pieces.</li></ul>
<a href="other-document.md">other document</a>
</body></html>"""


def test_headings_and_statements_come_with_line_numbers():
    parsed = parse_html(SAMPLE)
    assert [s["title"] for s in parsed["sections"]] == ["Size"]
    assert parsed["sections"][0]["line"] == 4
    value_statements = [s for s in parsed["statements"] if "1.19" in s["text"]]
    assert value_statements[0]["line"] == 5


def test_text_inside_diagrams_is_kept_and_styling_is_dropped():
    texts = [s["text"] for s in parse_html(SAMPLE)["statements"]]
    assert "text inside the diagram" in texts
    assert not any("color:red" in t for t in texts)
    assert not any("var dropped" in t for t in texts)


def test_anchors_become_links():
    links = parse_html(SAMPLE)["links"]
    assert [link["target"] for link in links] == ["other-document.md"]
    assert links[0]["relation"] is None
