"""Regression: automatic refresh must not fail in an unactivated project."""

import json
import os
from pathlib import Path
import subprocess

import pytest


PLUGIN = Path(__file__).resolve().parents[1]
HOOKS = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
REFRESH = [(event, hook["command"]) for event, groups in HOOKS.items()
           for group in groups for hook in group["hooks"] if "build_map.py" in hook["command"]]


def run_hook(command, root):
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(PLUGIN), CLAUDE_PROJECT_DIR=str(root),
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(["bash", "-c", command], cwd=root, env=env, input="{}",
                          text=True, capture_output=True, timeout=20)


@pytest.mark.parametrize("event,command", REFRESH)
def test_unactivated_project_skips_refresh_without_writes(tmp_path, event, command):
    result = run_hook(command, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["reason"] == "project_not_activated"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("event,command", REFRESH)
def test_malformed_activation_remains_an_error(tmp_path, event, command):
    config = tmp_path / ".context-graph/config.json"
    config.parent.mkdir()
    config.write_text("{broken")
    result = run_hook(command, tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["binding"]["reason"] == "invalid_config"
    assert config.read_text() == "{broken"
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == [
        ".context-graph", ".context-graph/config.json"]


@pytest.mark.parametrize("event,command", REFRESH)
def test_broken_activation_symlink_is_not_an_inactive_project(tmp_path, event, command):
    config = tmp_path / ".context-graph/config.json"
    config.parent.mkdir()
    config.symlink_to(tmp_path / "missing.json")
    result = run_hook(command, tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["binding"]["status"] == "unverified"
    assert config.is_symlink()


@pytest.mark.parametrize("event,command", REFRESH)
def test_foreign_activation_directory_is_not_skipped(tmp_path, event, command):
    (tmp_path / ".context-graph").symlink_to(tmp_path.parent / "absent-foreign-config")
    result = run_hook(command, tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["binding"]["reason"] == "config_outside_project"


def test_recording_hook_without_capture_activation_is_already_a_noop(tmp_path):
    command = HOOKS["SessionStart"][0]["hooks"][0]["command"]
    result = run_hook(command, tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert list(tmp_path.iterdir()) == []
