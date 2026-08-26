# tests/test_build_map.py
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from build_map import _nearest, build_map, folder_notes
from build_map import main as build_map_main


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


def test_a_folder_that_is_not_there_is_named(tmp_path):
    notes = folder_notes([str(tmp_path / "typo")], document_count=0)
    assert notes == [f"[the document folder in the config is not there - {tmp_path / 'typo'}]"]


def test_a_folder_with_no_documents_says_so(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    notes = folder_notes([str(empty)], document_count=0)
    assert notes == [f"[no .md, .markdown, .html or .htm documents under {empty}]"]


def test_a_folder_holding_documents_says_nothing(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "a.md").write_text("# A\n\n- A statement.\n", encoding="utf-8")
    assert folder_notes([str(source)], document_count=1) == []


def test_the_build_reports_the_sampled_check(tmp_path, capsys):
    source = tmp_path / "docs"; source.mkdir()
    (source / "facts.md").write_text("# Facts\n\n- The median is 1.19 m.\n", encoding="utf-8")
    build_map_main(["--source", str(source), "--out", str(tmp_path / "graph.json")])
    assert "samples 1/1 verbatim" in capsys.readouterr().out


def test_a_link_goes_to_the_document_beside_the_one_that_wrote_it(tmp_path):
    """Two vaults both hold index.md, and whoever was scanned last used to win every link."""
    first, second = tmp_path / "vault_a", tmp_path / "vault_b"
    for folder in (first, second):
        folder.mkdir()
        (folder / "index.md").write_text("# Index\n\na listing\n", encoding="utf-8")
    (first / "note.md").write_text("# Note\n\nsee [[index]]\n", encoding="utf-8")
    (second / "other.md").write_text("# Other\n\nsee [[index]]\n", encoding="utf-8")
    map_path = tmp_path / "graph.json"
    build_map([str(first), str(second)], str(map_path))

    graph = json.loads(map_path.read_text(encoding="utf-8"))
    by_id = {node["id"]: node for node in graph["nodes"]}
    for link in graph["links"]:
        if link["relation"] != "mentions":
            continue
        source_folder = os.path.dirname(by_id[link["source"]]["source_file"])
        target_folder = os.path.dirname(by_id[link["target"]]["source_file"])
        assert source_folder == target_folder      # each note reached its own vault's index


def test_a_link_takes_the_nearest_index_above_it_not_the_shallowest(tmp_path):
    """Taking the first match took the shallowest folder, which is the farthest away."""
    deep = tmp_path / "vault" / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (tmp_path / "vault" / "index.md").write_text("# Index\n\ntop\n", encoding="utf-8")
    (tmp_path / "vault" / "a" / "b" / "index.md").write_text("# Index\n\nmiddle\n",
                                                            encoding="utf-8")
    (deep / "note.md").write_text("# Note\n\nsee [[index]]\n", encoding="utf-8")
    map_path = tmp_path / "graph.json"
    build_map([str(tmp_path / "vault")], str(map_path))

    graph = json.loads(map_path.read_text(encoding="utf-8"))
    by_id = {node["id"]: node for node in graph["nodes"]}
    reached = [by_id[link["target"]]["source_file"] for link in graph["links"]
               if link["relation"] == "mentions" and by_id[link["source"]]["label"] == "note"]
    assert reached and os.path.join("a", "b", "index.md") in reached[0]


def test_vaults_on_two_drives_do_not_stop_the_build():
    """Asking for a common path across drives raises, and this is the function for two vaults."""
    candidates = [("C:\\vault_a\\notes", "a"), ("D:\\vault_b\\notes", "b")]
    assert _nearest(candidates, "D:\\vault_b\\deep\\note.md") in {"a", "b"}
    assert _nearest([("C:\\a\\b", "a"), ("relative\\c", "b")], "C:\\x\\y\\n.md") in {"a", "b"}
