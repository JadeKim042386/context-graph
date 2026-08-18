# tests/test_build_map.py
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from build_map import build_map


def _문서를_만든다(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def test_문장에_파일과_줄번호가_붙는다(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    _문서를_만든다(source, "크기.md", "## 크기\n\n중앙값은 1.19 m 입니다.\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    with open(map_path, encoding="utf-8-sig") as handle:
        graph = json.load(handle)
    값노드 = [n for n in graph["nodes"] if "1.19" in n["label"]]
    assert len(값노드) == 1
    assert 값노드[0]["source_location"] == 3
    assert 값노드[0]["source_file"].endswith("크기.md")


def test_관계_이름이_그대로_남는다(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    _문서를_만든다(source, "가.md", "## 절\n\n- supersedes [[나]]\n")
    _문서를_만든다(source, "나.md", "## 절\n\n내용\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    with open(map_path, encoding="utf-8-sig") as handle:
        graph = json.load(handle)
    관계 = [link for link in graph["links"] if link["relation"] == "supersedes"]
    assert len(관계) == 1


def test_없는_대상도_이름뿐인_노드로_잇는다(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    _문서를_만든다(source, "가.md", "## 절\n\n- relates_to [[없는문서]]\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    with open(map_path, encoding="utf-8-sig") as handle:
        graph = json.load(handle)
    이름뿐 = [n for n in graph["nodes"] if n["kind"] == "name_only"]
    assert [n["label"] for n in 이름뿐] == ["없는문서"]
    assert 이름뿐[0]["source_location"] is None


def test_두_번_만들면_바이트까지_같다(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    for name in ["다.md", "가.md", "나.md"]:
        _문서를_만든다(source, name, f"## {name}\n\n내용 {name}\n\n- relates_to [[가]]\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    first = open(map_path, "rb").read()
    build_map([source], map_path)
    assert open(map_path, "rb").read() == first


def test_지식_문서를_고치지_않는다(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    path = _문서를_만든다(source, "가.md", "## 절\n\n내용\n")
    before = open(path, "rb").read()
    build_map([source], str(tmp_path / "map" / "graph.json"))
    assert open(path, "rb").read() == before
    assert sorted(os.listdir(source)) == ["가.md"]
