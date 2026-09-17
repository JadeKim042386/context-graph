import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "context-graph" / "skills" / "knowledge-engineering"


def test_project_skill_has_a_triggering_description_and_workflow_contract():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: knowledge-engineering\n")
    assert "description: Use when" in text
    for required in ("analysis", "proposal", "modification", "Review", "AGENTS.md", "CLAUDE.md", "memory/index.json", "Archify"):
        assert required in text


def test_skill_explains_cross_runtime_instruction_and_script_paths():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "Codex" in text and "Claude Code" in text
    assert "CLAUDE_PLUGIN_ROOT" not in text
    assert "platform-specific" in text


def test_skill_references_the_project_contracts():
    for name in (
        "record-schema.md",
        "evidence-rules.md",
        "memory-update.md",
        "validation-gates.md",
        "post-install-verification.md",
    ):
        assert (SKILL / "references" / name).exists()


def test_skill_documents_post_install_integration_verification():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "post-install-verification.md").read_text(encoding="utf-8")
    for marker in ("Post-install integration verification", "host-specific discovery", "portable", "workspace validator"):
        assert marker in text
    for marker in ("Codex", "Claude Code", "smoke request", "git status --short", "--profile portable"):
        assert marker in reference


def test_memory_updater_is_safe_and_pointer_only(tmp_path):
    memory = tmp_path / "index.json"
    memory.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    updater = SKILL / "scripts" / "update_memory.py"
    result = subprocess.run(
        [sys.executable, str(updater), "--memory", str(memory), "--goal", "design/example.html", "--status", "verified"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(memory.read_text(encoding="utf-8"))
    assert data["current_goal"]["pointer"] == "design/example.html"
    assert "content" not in data["current_goal"]


def test_workspace_validator_accepts_the_current_project():
    validator = SKILL / "scripts" / "validate_workspace.py"
    result = subprocess.run([sys.executable, str(validator), "--root", str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_readme_describes_the_knowledge_engineering_skill():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Knowledge Engineering Skill" in readme
    assert "analysis" in readme
    assert "proposal" in readme
    assert "review, and modification" in readme
    assert "A Claude Code plugin" not in readme
    assert "Codex" in readme and "Claude Code" in readme
    assert "CLAUDE.md" in readme
