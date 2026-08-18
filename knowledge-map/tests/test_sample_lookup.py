import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from score import score_map, verify_samples


def test_원본_줄과_글자가_같으면_통과(tmp_path):
    document = tmp_path / "가.md"
    document.write_text("## 절\n\n중앙값은 1.19 m 입니다\n", encoding="utf-8")
    map_path = str(tmp_path / "graph.json")
    with open(map_path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": [{"id": "a", "label": "중앙값은 1.19 m 입니다", "kind": "statement",
                              "source_file": str(document), "source_location": 3}], "links": []},
                  handle, ensure_ascii=False)
    result = verify_samples(score_map(map_path))
    assert result["checked"] == 1 and result["matched"] == 1 and result["failed"] == []


def test_줄번호가_어긋나면_실패로_잡는다(tmp_path):
    document = tmp_path / "가.md"
    document.write_text("## 절\n\n중앙값은 1.19 m 입니다\n", encoding="utf-8")
    map_path = str(tmp_path / "graph.json")
    with open(map_path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": [{"id": "a", "label": "중앙값은 1.19 m 입니다", "kind": "statement",
                              "source_file": str(document), "source_location": 1}], "links": []},
                  handle, ensure_ascii=False)
    result = verify_samples(score_map(map_path))
    assert result["matched"] == 0 and len(result["failed"]) == 1
