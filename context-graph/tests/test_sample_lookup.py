import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from score import score_map, verify_samples


def test_a_sample_matching_its_source_line_passes(tmp_path):
    document = tmp_path / "a.md"
    document.write_text("## Section\n\nThe median is 1.19 m\n", encoding="utf-8")
    map_path = str(tmp_path / "graph.json")
    with open(map_path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": [{"id": "a", "label": "The median is 1.19 m", "kind": "statement",
                              "source_file": str(document), "source_location": 3}], "links": []},
                  handle, ensure_ascii=False)
    result = verify_samples(score_map(map_path))
    assert result["checked"] == 1 and result["matched"] == 1 and result["failed"] == []


def test_a_wrong_line_number_is_caught_as_a_failure(tmp_path):
    document = tmp_path / "a.md"
    document.write_text("## Section\n\nThe median is 1.19 m\n", encoding="utf-8")
    map_path = str(tmp_path / "graph.json")
    with open(map_path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": [{"id": "a", "label": "The median is 1.19 m", "kind": "statement",
                              "source_file": str(document), "source_location": 1}], "links": []},
                  handle, ensure_ascii=False)
    result = verify_samples(score_map(map_path))
    assert result["matched"] == 0 and len(result["failed"]) == 1
