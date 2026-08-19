# tests/test_build_map.py
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from build_map import build_map


def _write_document(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def test_a_statement_carries_its_file_and_line_number(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    _write_document(source, "size.md", "## Size\n\nThe median is 1.19 m.\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    with open(map_path, encoding="utf-8-sig") as handle:
        graph = json.load(handle)
    value_nodes = [n for n in graph["nodes"] if "1.19" in n["label"]]
    assert len(value_nodes) == 1
    assert value_nodes[0]["source_location"] == 3
    assert value_nodes[0]["source_file"].endswith("size.md")


def test_the_relation_name_is_kept_as_written(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    _write_document(source, "a.md", "## Section\n\n- supersedes [[b]]\n")
    _write_document(source, "b.md", "## Section\n\nbody\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    with open(map_path, encoding="utf-8-sig") as handle:
        graph = json.load(handle)
    relations = [link for link in graph["links"] if link["relation"] == "supersedes"]
    assert len(relations) == 1


def test_a_missing_target_still_becomes_a_name_only_node(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    _write_document(source, "a.md", "## Section\n\n- relates_to [[missing document]]\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    with open(map_path, encoding="utf-8-sig") as handle:
        graph = json.load(handle)
    name_only = [n for n in graph["nodes"] if n["kind"] == "name_only"]
    assert [n["label"] for n in name_only] == ["missing document"]
    assert name_only[0]["source_location"] is None


def test_building_twice_gives_byte_identical_output(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    for name in ["c.md", "a.md", "b.md"]:
        _write_document(source, name, f"## {name}\n\nbody {name}\n\n- relates_to [[a]]\n")
    map_path = str(tmp_path / "map" / "graph.json")
    build_map([source], map_path)
    first = open(map_path, "rb").read()
    build_map([source], map_path)
    assert open(map_path, "rb").read() == first


def test_the_knowledge_documents_are_never_modified(tmp_path):
    source = str(tmp_path / "docs"); os.makedirs(source)
    path = _write_document(source, "a.md", "## Section\n\nbody\n")
    before = open(path, "rb").read()
    build_map([source], str(tmp_path / "map" / "graph.json"))
    assert open(path, "rb").read() == before
    assert sorted(os.listdir(source)) == ["a.md"]


def test_a_named_relation_beats_a_bare_mention_between_the_same_two_documents(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "later.md").write_text(
        "# Later\n\n- The earlier call was [[earlier]], now revisited.\n\n## Relations\n"
        "- supersedes [[earlier]]\n", encoding="utf-8")
    (source / "earlier.md").write_text("# Earlier\n\n- The first call.\n", encoding="utf-8")
    map_path = tmp_path / "graph.json"
    build_map([str(source)], str(map_path))
    graph = json.loads(map_path.read_text(encoding="utf-8"))
    between = [link["relation"] for link in graph["links"]
               if link["source"] == "doc_later" and link["target"] == "doc_earlier"]
    assert between == ["supersedes"]
