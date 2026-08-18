import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
BUILD_MAP_SCRIPT = os.path.join(ROOT, "context-graph", "scripts", "build_map.py")


def _read_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as handle:
        return json.load(handle)


def _read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as handle:
        return handle.read()


def test_the_marketplace_points_at_the_plugin():
    marketplace = _read_json(".claude-plugin", "marketplace.json")
    assert marketplace["name"] == "context-graph"
    assert marketplace["plugins"][0]["source"] == "./context-graph"


def test_the_plugin_manifest_has_a_name_and_a_version():
    plugin = _read_json("context-graph", ".claude-plugin", "plugin.json")
    assert plugin["name"] == "context-graph"
    assert plugin["version"]


def test_all_four_refresh_points_are_hooked():
    hooks = _read_json("context-graph", "hooks", "hooks.json")["hooks"]
    assert set(hooks) == {"SessionStart", "SubagentStop", "PreCompact", "PostCompact"}


def test_no_machine_specific_path_is_baked_into_the_hooks():
    """It has to run on any machine, so paths go through ${CLAUDE_PLUGIN_ROOT} only."""
    hooks_text = _read_text("context-graph", "hooks", "hooks.json")
    assert "C:" not in hooks_text and "/home/" not in hooks_text
    for event in json.loads(hooks_text)["hooks"].values():
        for group in event:
            for hook in group["hooks"]:
                if "scripts" in hook["command"]:
                    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]


def test_the_build_the_hooks_call_actually_runs(tmp_path):
    """The hooks call the script from the command line. No entry point, no refresh at all."""
    source = tmp_path / "docs"
    source.mkdir()
    (source / "a.md").write_text("## Section\n\nThe median is 1.19 m\n", encoding="utf-8")
    map_path = tmp_path / "map" / "graph.json"
    completed = subprocess.run(
        [sys.executable, BUILD_MAP_SCRIPT, "--source", str(source), "--out", str(map_path)],
        capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert map_path.exists()


def test_the_readme_states_the_three_limits():
    readme = _read_text("context-graph", "README.md")
    assert "written in" in readme                       # one: ask in the language of the documents
    assert "20,000" in readme or "20000" in readme      # two: the answer budget
    assert "narrowly" in readme                         # three: a broad question returns a cut list


def test_the_skill_states_the_same_rules():
    skill = _read_text("context-graph", "skills", "context-graph", "SKILL.md")
    assert "written in" in skill
    assert "20,000" in skill or "20000" in skill
    assert "narrowly" in skill
