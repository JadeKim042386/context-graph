import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from score import format_score, score_map


def _write_map(path, nodes, links):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": nodes, "links": links}, handle, ensure_ascii=False)


def test_it_measures_the_located_ratio(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _write_map(map_path, [
        {"id": "a", "label": "value 1.19 m", "kind": "statement", "source_file": "a.md", "source_location": 3},
        {"id": "b", "label": "name only", "kind": "name_only", "source_file": "", "source_location": None},
    ], [{"source": "a", "target": "b", "relation": "mentions"}])
    score = score_map(map_path)
    assert score["located_ratio"] == 0.5


def test_a_high_whole_document_ratio_is_pointed_out(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _write_map(map_path, [
        {"id": f"d{i}", "label": f"document {i}", "kind": "document", "source_file": f"{i}.md", "source_location": 1}
        for i in range(9)
    ] + [
        {"id": "t", "label": "statement", "kind": "statement", "source_file": "0.md", "source_location": 5}
    ], [])
    score = score_map(map_path)
    assert score["document_node_ratio"] > 0.8
    assert any("list of documents" in hint for hint in score["hints"])


def test_the_samples_are_statements_carrying_a_number(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _write_map(map_path, [
        {"id": "a", "label": "The median is 1.19 m", "kind": "statement", "source_file": "a.md", "source_location": 3},
        {"id": "b", "label": "a statement with no number", "kind": "statement", "source_file": "a.md", "source_location": 9},
    ], [])
    labels = [sample["label"] for sample in score_map(map_path)["samples"]]
    assert labels == ["The median is 1.19 m"]


def test_it_formats_a_single_human_readable_line(tmp_path):
    map_path = str(tmp_path / "graph.json")
    _write_map(map_path, [
        {"id": "a", "label": "value 1.19 m", "kind": "statement", "source_file": "a.md", "source_location": 3},
    ], [])
    line = format_score(score_map(map_path))
    assert "nodes 1" in line and "located" in line


def test_the_samples_are_spread_across_documents(tmp_path):
    """Taking the first few by id took four lines of whatever the alphabet put in front."""
    map_path = tmp_path / "graph.json"
    nodes = [{"id": "a_doc", "kind": "document", "label": "a", "source_file": "C:/v/a.md",
              "source_location": 1}]
    for index in range(9):                    # one crowded document
        nodes.append({"id": f"a_t{index}", "kind": "statement", "label": f"value {index} m",
                      "source_file": "C:/v/a.md", "source_location": index + 2})
    for name in ("b", "c", "d", "e"):         # and four quiet ones
        nodes.append({"id": f"{name}_t0", "kind": "statement", "label": f"value in {name} 3 m",
                      "source_file": f"C:/v/{name}.md", "source_location": 2})
    map_path.write_text(json.dumps({"nodes": nodes, "links": []}, ensure_ascii=False),
                        encoding="utf-8")
    score = score_map(str(map_path))
    assert len({sample["source_file"] for sample in score["samples"]}) == 5
