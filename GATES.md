# Similar-materials review gates

## G1 — Current corpus and project scope are inventoried

CHECK: `rg --files knowledge design | sort`
EXPECT: output contains the three knowledge HTML files and the two design/validation HTML files.

## G2 — Comparable references are reviewed and traceable

CHECK: manual review of primary/official comparable materials and source links in the knowledge HTML.
EXPECT: each material added or retained has a clear relevance note and a traceable source link.

## G3 — HTML artifacts remain parseable

CHECK: `python -c 'from html.parser import HTMLParser; import pathlib; [HTMLParser().feed(pathlib.Path(p).read_text()) for p in pathlib.Path("knowledge").glob("*.html")]; print("HTML_OK")'`
EXPECT: `HTML_OK`

## G4 — Existing performance checks remain green

CHECK: `pytest -q design/test_knowledge_base_performance.py`
EXPECT: `5 passed`

## G5 — Review findings are reflected without overstating evidence

CHECK: manual review of changed HTML claims against the cited sources and validation results.
EXPECT: synthetic, operational, and unverified results are explicitly distinguished.
