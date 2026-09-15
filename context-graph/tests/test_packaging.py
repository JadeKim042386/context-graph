import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
BUILD_MAP_SCRIPT = os.path.join(ROOT, "context-graph", "scripts", "build_map.py")

# Every test in this file reads the repository around the plugin - the marketplace manifest
# beside it, the plugin folder it points at. An installed copy has neither: the plugin is
# unpacked on its own, without the folders that hold it in the repository. Running these there
# used to fail nine times over something that was never wrong, so they stand down instead.
# The mark has to be something these tests do not themselves check. Using the marketplace
# manifest meant that losing it - the very regression this file exists to catch - turned nine
# failures into nine quiet skips.
# exists, not isdir: in a worktree checkout .git is a file, and isdir let those skip too.
IN_THE_REPOSITORY = os.path.exists(os.path.join(ROOT, ".git"))
pytestmark = pytest.mark.skipif(
    not IN_THE_REPOSITORY,
    reason="packaging is checked against the repository layout; this is an installed copy")


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
    assert plugin["author"]["name"] == "KimJooYoung"


def test_the_plugin_packages_a_knowledge_engineer_agent():
    agent = _read_text("context-graph", "agents", "knowledge-engineer.md")
    assert "name: knowledge-engineer" in agent
    assert "skills: context-graph" in agent
    assert "analysis" in agent.lower()
    assert "propose" in agent.lower()
    assert "modify" in agent.lower()
    assert "build_map.py" in agent
    assert "ask.py" in agent


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
    assert "answer_budget" in readme                    # two: the answer budget, named not quoted
    assert "narrowly" in readme                         # three: a broad question returns a cut list


def test_the_packaged_readme_does_not_keep_a_claim_the_code_stopped_making():
    """This file ships with the plugin, and it kept three sentences the code no longer backs."""
    readme = _read_text("context-graph", "README.md")
    assert "matches nothing" not in readme
    assert "four points" not in readme
    assert "The answer budget is 20,000" not in readme


def test_the_skill_states_the_same_rules():
    skill = _read_text("context-graph", "skills", "context-graph", "SKILL.md")
    assert "written in" in skill
    assert "answer_budget" in skill                  # the setting is named, not a number in prose
    assert "narrowly" in skill


def test_the_skill_quotes_the_default_budget_the_code_actually_uses():
    """A number written into prose drifts away from the code. This is the check that it has not."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from config import DEFAULT_CONFIG

    skill = _read_text("context-graph", "skills", "context-graph", "SKILL.md")
    default = DEFAULT_CONFIG["answer_budget"]
    assert f"{default:,}" in skill or str(default) in skill
