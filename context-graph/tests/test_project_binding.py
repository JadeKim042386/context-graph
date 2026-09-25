"""Two-project, no-network project binding acceptance tests."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CONTINUITY = SCRIPTS.parent / "skills/knowledge-engineering/scripts/build_task_continuity.py"


def command(root, script, *args, env=None):
    return subprocess.run([sys.executable, "-B", str(script), *args], cwd=root,
                          env=env, capture_output=True, text=True)


def project(root, label):
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / ".context-graph").mkdir()
    (root / "knowledge/facts.md").write_text(f"# Facts\n\n- uniqueanswer {label}.\n")
    config = {"source_dirs": ["knowledge"], "map_path": "map.json", "answer_budget": 8000,
              "project_binding": {"project_root": str(root.resolve()),
                  "config_path": ".context-graph/config.json", "map_path": "map.json",
                  "allowed_source_roots": ["knowledge"]}}
    (root / ".context-graph/config.json").write_text(json.dumps(config))
    return root


def build(root):
    result = command(root, SCRIPTS / "build_map.py", "--project-root", str(root), "--quiet")
    assert result.returncode == 0, result.stdout + result.stderr


def ask(root, *args, env=None):
    result = command(root, SCRIPTS / "ask.py", "--project-root", str(root), "--read-only",
                     *args, "uniqueanswer", env=env)
    assert result.stdout, result.stderr
    return result, json.loads(result.stdout)


@pytest.fixture
def pair(tmp_path):
    return project(tmp_path / "A", "ALPHA_ONLY"), project(tmp_path / "B", "BETA_ONLY")


def test_no_root_never_reads_environment_global_config(pair):
    a, b = pair
    env = dict(os.environ, KNOWLEDGE_MAP_CONFIG=str(b / ".context-graph/config.json"))
    result = command(a, SCRIPTS / "ask.py", "uniqueanswer", env=env)
    assert result.returncode == 2
    data = json.loads(result.stdout)
    assert data["binding"]["status"] == "unverified"
    assert data["binding"]["reason"] == "missing_project_root" and data["hits"] == []


def test_two_projects_have_zero_cross_project_hits_and_no_writes(pair):
    a, b = pair
    for root in pair: build(root)
    before = {str(p): p.read_bytes() for r in pair for p in r.rglob("*") if p.is_file()}
    for root, foreign, marker, forbidden in ((a,b,"ALPHA_ONLY","BETA_ONLY"),(b,a,"BETA_ONLY","ALPHA_ONLY")):
        result, data = ask(root, env=dict(os.environ, KNOWLEDGE_MAP_CONFIG=str(foreign / ".context-graph/config.json")))
        assert result.returncode == 0, data
        assert data["binding"]["status"] == "verified"
        assert data["binding"]["project_root"] == str(root.resolve())
        assert data["binding"]["config_sha256"] and data["binding"]["map_sha256"]
        assert marker in result.stdout and forbidden not in result.stdout
        assert all(Path(hit["source_file"]).is_relative_to(root) for hit in data["hits"])
    assert before == {str(p): p.read_bytes() for r in pair for p in r.rglob("*") if p.is_file()}


@pytest.mark.parametrize("mutation,reason", [
    ("missing_config", "missing_config"), ("missing_binding", "missing_binding"),
    ("wrong_root", "project_root_mismatch"), ("foreign_config", "config_outside_project"),
    ("foreign_source", "source_outside_project"), ("wrong_sources", "source_roots_mismatch"),
    ("foreign_map", "map_outside_project"), ("missing_map", "missing_map"),
    ("unbound_map", "map_binding_mismatch"), ("swapped_map", "map_binding_mismatch"),
    ("foreign_node", "map_source_outside_allowed_roots"),
])
def test_mismatches_return_no_hits(pair, mutation, reason):
    a, b = pair
    build(a); build(b)
    config_path = a / ".context-graph/config.json"
    config = json.loads(config_path.read_text())
    extra = []
    if mutation == "missing_config": config_path.unlink()
    elif mutation == "missing_binding":
        config.pop("project_binding"); config_path.write_text(json.dumps(config))
    elif mutation == "wrong_root":
        config["project_binding"]["project_root"] = str(b); config_path.write_text(json.dumps(config))
    elif mutation == "foreign_config": extra = ["--config", str(b / ".context-graph/config.json")]
    elif mutation == "foreign_source":
        config["source_dirs"] = [str(b / "knowledge")]; config_path.write_text(json.dumps(config))
    elif mutation == "wrong_sources":
        (a / "other").mkdir(); config["source_dirs"] = ["other"]; config_path.write_text(json.dumps(config))
    elif mutation == "foreign_map":
        config["map_path"] = str(b / "map.json"); config_path.write_text(json.dumps(config))
    elif mutation == "missing_map": (a / "map.json").unlink()
    elif mutation == "swapped_map": (a / "map.json").write_bytes((b / "map.json").read_bytes())
    else:
        graph = json.loads((a / "map.json").read_text())
        if mutation == "unbound_map": graph.pop("project_binding")
        else: graph["nodes"][0]["source_file"] = str(b / "knowledge/facts.md")
        (a / "map.json").write_text(json.dumps(graph))
    result, data = ask(a, *extra)
    assert result.returncode == 2 and data["hits"] == []
    assert data["binding"]["reason"] == reason


def test_cwd_mismatch_blocks_knowledge_and_memory(pair):
    a, b = pair
    build(a)
    result = command(b, SCRIPTS / "ask.py", "--project-root", str(a), "--read-only", "uniqueanswer")
    assert result.returncode == 2 and json.loads(result.stdout)["binding"]["reason"] == "cwd_mismatch"
    (a / "memory.json").write_text('{"schema_version":1}')
    result = command(b, CONTINUITY, "--root", str(a), "--memory", "memory.json")
    assert result.returncode == 2
    pack = json.loads(result.stdout)
    assert pack["binding"]["reason"] == "cwd_mismatch" and pack["items"] == []


def test_memory_binding_is_explicit_without_loading_knowledge_config(pair):
    a, b = pair
    (a / "memory.json").write_text('{"schema_version":1}')
    result = command(a, CONTINUITY, "--root", str(a), "--memory", "memory.json",
                     env=dict(os.environ, KNOWLEDGE_MAP_CONFIG=str(b / ".context-graph/config.json")))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["binding"]["status"] == "verified" and data["binding"]["scope"] == "memory"
    assert data["binding"]["root_id"] and data["binding"]["config_map_state"] == "not_used"
    assert data["pack_status"] == "empty"


def test_symlink_escape_blocks_build_before_outputs(pair):
    a, b = pair
    (a / "knowledge/escape.md").symlink_to(b / "knowledge/facts.md")
    result = command(a, SCRIPTS / "build_map.py", "--project-root", str(a), "--quiet")
    assert result.returncode == 2
    assert not (a / "map.json").exists()


def test_refresh_without_root_never_uses_global_config(pair):
    a, b = pair
    result = command(a, SCRIPTS / "build_map.py", "--quiet",
                     env=dict(os.environ, KNOWLEDGE_MAP_CONFIG=str(b / ".context-graph/config.json")))
    assert result.returncode == 2
    assert not (a / "map.json").exists() and not (b / "map.json").exists()


@pytest.mark.parametrize("mutation,reason", [
    ("config_id", "config_identity_mismatch"), ("map_id", "map_identity_mismatch"),
    ("local_source", "map_source_outside_allowed_roots"), ("relative_source", "invalid_map_source_path"),
    ("invalid_map", "invalid_map"),
])
def test_identity_and_locator_mismatches(pair, mutation, reason):
    a, _ = pair
    build(a)
    path = a / ".context-graph/config.json"
    config = json.loads(path.read_text())
    if mutation in {"config_id", "map_id"}:
        config["project_binding"]["config_path" if mutation == "config_id" else "map_path"] = "other.json"
        path.write_text(json.dumps(config))
    elif mutation == "invalid_map": (a / "map.json").write_text("invalid")
    else:
        graph = json.loads((a / "map.json").read_text())
        other = a / "outside.md"
        other.write_text("other")
        graph["nodes"][0]["source_file"] = "knowledge/facts.md" if mutation == "relative_source" else str(other)
        (a / "map.json").write_text(json.dumps(graph))
    result, data = ask(a)
    assert result.returncode == 2 and data["hits"] == []
    assert data["binding"]["reason"] == reason


def test_subdirectory_uses_declared_root_not_cwd_for_config(pair):
    a, _ = pair
    build(a)
    child = a / "nested"
    child.mkdir()
    result = command(child, SCRIPTS / "ask.py", "--project-root", str(a), "--read-only", "uniqueanswer")
    assert result.returncode == 0
    assert "ALPHA_ONLY" in result.stdout
    assert json.loads(result.stdout)["binding"]["config_path"] == str(a / ".context-graph/config.json")
