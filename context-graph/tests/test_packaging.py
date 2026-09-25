import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

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
    assert set(hooks) == {"SessionStart", "SubagentStop", "PreCompact", "PostCompact", "SessionEnd"}


def test_session_lifecycle_hooks_record_only_through_the_portable_script():
    hooks_text = _read_text("context-graph", "hooks", "hooks.json")
    assert "record_session_event.py" in hooks_text
    assert "--event pre_compact" in hooks_text
    assert "--event post_compact" in hooks_text
    assert "--event session_end" in hooks_text
    assert "record --runtime claude-code" in hooks_text
    assert "--compile-proposal" in hooks_text
    assert "transcript" not in hooks_text


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


# ---------- installed Codex layout: parity, import isolation, CLI isolation ----------
# Codex installs skills/context-graph/ on its own. Everything ask.py and build_map.py need has to
# be a regular file inside skills/context-graph/scripts/, byte-identical to the bound scripts/
# implementation, and the CLI has to bind to the fixture project alone - no global config, no
# environment override, no path outside the installed directory.

BOUND_SCRIPTS = Path(ROOT).resolve() / "context-graph" / "scripts"
INSTALLED_SCRIPTS = Path(ROOT).resolve() / "context-graph" / "skills" / "context-graph" / "scripts"
SHIPPED_MODULES = ("ask.py", "build_map.py", "config.py", "freshness.py",
                   "conflicts.py", "parse_html.py", "parse_markdown.py", "score.py")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_the_codex_skill_ships_the_bound_scripts_byte_for_byte():
    for name in SHIPPED_MODULES:
        installed = INSTALLED_SCRIPTS / name
        assert installed.is_file() and not installed.is_symlink(), f"missing regular file: {installed}"
        assert _sha256(installed) == _sha256(BOUND_SCRIPTS / name), f"installed copy drifted: {name}"


def test_installed_scripts_import_only_stdlib_and_their_own_directory():
    """Static: every top-level import in the installed copies resolves to stdlib or a sibling file."""
    stdlib = set(sys.stdlib_module_names)
    siblings = {path.stem for path in INSTALLED_SCRIPTS.glob("*.py")}
    seen = 0
    for name in SHIPPED_MODULES:
        tree = ast.parse((INSTALLED_SCRIPTS / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module.split(".")[0]]
            else:
                continue
            for module in names:
                seen += 1
                assert module in stdlib or module in siblings, f"{name} imports {module} from outside the installed directory"
    assert seen > 20   # the walk found the imports; an empty walk would pass vacuously


def test_installed_scripts_import_in_an_isolated_interpreter(tmp_path):
    """Runtime: -I drops cwd, PYTHONPATH and user site; only the installed directory is on the path."""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); "
         "import ask, build_map, config, freshness, conflicts, score, parse_html, parse_markdown; "
         "print(config.__file__, freshness.__file__)", str(INSTALLED_SCRIPTS)],
        cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    for loaded in completed.stdout.split():
        assert Path(loaded).resolve().parent == INSTALLED_SCRIPTS, loaded


def _hostile_env(tmp_path, foreign_root):
    """A global config and an environment override that both point at the other project."""
    from test_project_binding import project as _bound_project  # noqa: F401 - keeps fixture import explicit
    home = tmp_path / "home"
    (home / ".claude" / "context-graph").mkdir(parents=True)
    (home / ".claude" / "context-graph" / "config.json").write_text(
        (foreign_root / ".context-graph" / "config.json").read_text())
    env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1",
               KNOWLEDGE_MAP_CONFIG=str(foreign_root / ".context-graph" / "config.json"))
    env.pop("PWD", None)
    return env


@pytest.fixture
def bound_pair(tmp_path):
    from test_project_binding import project
    return project(tmp_path / "A", "ALPHA_ONLY"), project(tmp_path / "B", "BETA_ONLY")


def _run(script, root, *args, env):
    return subprocess.run([sys.executable, "-B", str(script), *args], cwd=str(root.resolve()),
                          env=env, capture_output=True, text=True)


def _snapshot(*roots):
    return {str(p): p.read_bytes() for r in roots for p in r.rglob("*") if p.is_file()}


def test_both_entrypoint_layouts_bind_the_same_fixture_and_only_that_fixture(tmp_path, bound_pair):
    a, b = bound_pair
    env = _hostile_env(tmp_path, b)
    for root in bound_pair:   # maps come only from the installed build, bound to each fixture
        built = _run(INSTALLED_SCRIPTS / "build_map.py", root, "--project-root", str(root), "--quiet", env=env)
        assert built.returncode == 0, built.stdout + built.stderr
    before = _snapshot(a, b, tmp_path / "home")

    bindings = []
    for script in (BOUND_SCRIPTS / "ask.py", INSTALLED_SCRIPTS / "ask.py"):
        result = _run(script, a, "--project-root", str(a), "--binding-only", env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        data = json.loads(result.stdout)
        assert data["hits"] == [] and data["binding"]["status"] == "verified"
        assert data["binding"]["global_config_used"] is False
        assert data["binding"]["project_root"] == str(a.resolve())
        bindings.append(data["binding"])
    assert bindings[0] == bindings[1]          # same identity, hashes and roots from both layouts
    assert bindings[0]["binding_id"] and bindings[0]["config_sha256"] and bindings[0]["map_sha256"]

    result = _run(INSTALLED_SCRIPTS / "ask.py", a, "--project-root", str(a), "--read-only", "uniqueanswer", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["retrieval"] == "lexical_read_only" and data["hits"]
    assert "ALPHA_ONLY" in result.stdout and "BETA_ONLY" not in result.stdout
    assert all(Path(hit["source_file"]).is_relative_to(a.resolve()) for hit in data["hits"])
    assert before == _snapshot(a, b, tmp_path / "home")   # read-only: nothing written anywhere


@pytest.mark.parametrize("mutation,reason", [
    ("missing_config", "missing_config"),
    ("wrong_root", "project_root_mismatch"),
    ("edited_same_mtime", "source_content_changed"),
    ("deleted", "source_deleted"),
])
def test_installed_entrypoint_fails_closed_on_missing_binding_and_stale_sources(tmp_path, bound_pair, mutation, reason):
    a, b = bound_pair
    env = _hostile_env(tmp_path, b)
    built = _run(INSTALLED_SCRIPTS / "build_map.py", a, "--project-root", str(a), "--quiet", env=env)
    assert built.returncode == 0, built.stdout + built.stderr
    config_path = a / ".context-graph" / "config.json"
    source = a / "knowledge" / "facts.md"
    if mutation == "missing_config":
        config_path.unlink()
    elif mutation == "wrong_root":
        config = json.loads(config_path.read_text())
        config["project_binding"]["project_root"] = str(b.resolve())
        config_path.write_text(json.dumps(config))
    elif mutation == "edited_same_mtime":
        stat = source.stat()
        source.write_text(source.read_text().replace("ALPHA_ONLY", "CHANGED"))
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    else:
        source.unlink()
    for args in (("--binding-only",), ("--read-only", "uniqueanswer")):
        result = _run(INSTALLED_SCRIPTS / "ask.py", a, "--project-root", str(a), *args, env=env)
        assert result.returncode == 2, result.stdout + result.stderr
        data = json.loads(result.stdout)
        assert data["binding"] == {"status": "unverified", "reason": reason} and data["hits"] == []


# ---------- hook argv expansion: the three map-refresh events, with the project variable set/empty/unset ----------

def _build_hooks():
    hooks = _read_json("context-graph", "hooks", "hooks.json")["hooks"]
    found = {event: hook["command"] for event, groups in hooks.items()
             for group in groups for hook in group["hooks"] if "build_map.py" in hook["command"]}
    assert set(found) == {"SessionStart", "SubagentStop", "PostCompact"}
    return found


def _python_shim(tmp_path):
    """A `python` on PATH that records its argv to a file, then runs the real interpreter."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    log = tmp_path / "argv.json"
    recorder = shim_dir / "record.py"
    recorder.write_text(
        "import json, os, sys\n"
        "json.dump(sys.argv[2:], open(sys.argv[1], 'w'))\n"
        "os.execv(sys.executable, [sys.executable, '-B', *sys.argv[2:]])\n")
    shim = shim_dir / "python"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{recorder}" "{log}" "$@"\n')
    shim.chmod(0o755)
    return shim_dir, log


@pytest.mark.parametrize("event", ["SessionStart", "SubagentStop", "PostCompact"])
@pytest.mark.parametrize("project_env", ["set", "empty", "unset"])
def test_hook_argv_expands_to_the_bound_project_and_builds_only_there(tmp_path, bound_pair, event, project_env):
    a, b = bound_pair
    command_text = _build_hooks()[event]
    shim_dir, log = _python_shim(tmp_path)
    env = _hostile_env(tmp_path, b)
    env["PATH"] = str(shim_dir) + os.pathsep + env["PATH"]
    env["CLAUDE_PLUGIN_ROOT"] = str(Path(ROOT).resolve() / "context-graph")
    if project_env == "set": env["CLAUDE_PROJECT_DIR"] = str(a.resolve())
    elif project_env == "empty": env["CLAUDE_PROJECT_DIR"] = ""
    else: env.pop("CLAUDE_PROJECT_DIR", None)
    completed = subprocess.run(["bash", "-c", command_text], cwd=str(a.resolve()), env=env,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    argv = json.loads(log.read_text())
    assert argv[0] == str(Path(ROOT).resolve() / "context-graph" / "scripts" / "build_map.py")
    assert argv[1:] == ["--project-root", str(a.resolve()), "--quiet"], argv
    assert (a / "map.json").exists() and not (b / "map.json").exists()
    graph = json.loads((a / "map.json").read_text())
    assert graph["project_binding"]["project_root"] == str(a.resolve())
    assert not list((tmp_path / "home").rglob("map*"))     # the hostile global config gained no map


def test_hook_with_a_foreign_project_variable_refuses_and_writes_nothing(tmp_path, bound_pair):
    a, b = bound_pair
    shim_dir, log = _python_shim(tmp_path)
    env = _hostile_env(tmp_path, b)
    env["PATH"] = str(shim_dir) + os.pathsep + env["PATH"]
    env["CLAUDE_PLUGIN_ROOT"] = str(Path(ROOT).resolve() / "context-graph")
    env["CLAUDE_PROJECT_DIR"] = str(b.resolve())      # points at B, but the hook runs inside A
    before = _snapshot(a, b)
    completed = subprocess.run(["bash", "-c", _build_hooks()["SessionStart"]], cwd=str(a.resolve()),
                               env=env, capture_output=True, text=True)
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert json.loads(log.read_text())[1:] == ["--project-root", str(b.resolve()), "--quiet"]
    assert json.loads(completed.stdout)["binding"]["reason"] == "cwd_mismatch"
    assert before == _snapshot(a, b)


def test_hooked_map_builds_pass_the_project_root():
    """The bound build refuses to guess its project; the hook has to say which one."""
    for event in _read_json("context-graph", "hooks", "hooks.json")["hooks"].values():
        for group in event:
            for hook in group["hooks"]:
                if "build_map.py" in hook["command"]:
                    assert "--project-root" in hook["command"], hook["command"]
