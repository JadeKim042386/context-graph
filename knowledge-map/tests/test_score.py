import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from score import format_score, score_map


def _지도를_만든다(path, nodes, links):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": nodes, "links": links}, handle, ensure_ascii=False)


def test_위치정보_비율을_잰다(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _지도를_만든다(map_path, [
        {"id": "a", "label": "값 1.19 m", "kind": "statement", "source_file": "가.md", "source_location": 3},
        {"id": "b", "label": "이름뿐", "kind": "name_only", "source_file": "", "source_location": None},
    ], [{"source": "a", "target": "b", "relation": "mentions"}])
    score = score_map(map_path)
    assert score["located_ratio"] == 0.5


def test_문서통짜_비율이_높으면_짚어준다(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _지도를_만든다(map_path, [
        {"id": f"d{i}", "label": f"문서{i}", "kind": "document", "source_file": f"{i}.md", "source_location": 1}
        for i in range(9)
    ] + [
        {"id": "t", "label": "문장", "kind": "statement", "source_file": "0.md", "source_location": 5}
    ], [])
    score = score_map(map_path)
    assert score["document_node_ratio"] > 0.8
    assert any("목록" in hint for hint in score["hints"])


def test_표본으로_값이_든_문장을_고른다(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _지도를_만든다(map_path, [
        {"id": "a", "label": "중앙값은 1.19 m 입니다", "kind": "statement", "source_file": "가.md", "source_location": 3},
        {"id": "b", "label": "숫자 없는 문장", "kind": "statement", "source_file": "가.md", "source_location": 9},
    ], [])
    labels = [sample["label"] for sample in score_map(map_path)["samples"]]
    assert labels == ["중앙값은 1.19 m 입니다"]


def test_사람이_읽는_한_줄로_바꾼다(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _지도를_만든다(map_path, [
        {"id": "a", "label": "값 1.19 m", "kind": "statement", "source_file": "가.md", "source_location": 3},
    ], [])
    line = format_score(score_map(map_path))
    assert "노드 1" in line and "위치" in line
