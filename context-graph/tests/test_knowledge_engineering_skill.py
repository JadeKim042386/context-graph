import json
import hashlib
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
        "code-workflow.md",
        "multimedia-collection.md",
    ):
        assert (SKILL / "references" / name).exists()
    for name in ("session-capture.schema.json", "session-event.schema.json", "session-proposal.schema.json"):
        assert (SKILL / "schemas" / name).exists()


def test_skill_documents_post_install_integration_verification():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "post-install-verification.md").read_text(encoding="utf-8")
    for marker in ("Post-install integration verification", "host-specific discovery", "portable", "workspace validator"):
        assert marker in text
    for marker in ("Codex", "Claude Code", "smoke request", "git status --short", "--profile portable"):
        assert marker in reference


def test_skill_documents_multimedia_collection_boundaries():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "multimedia-collection.md").read_text(encoding="utf-8")
    for marker in ("Multimedia collection mode", "Metadata-only", "rights", "locator", "derivatives"):
        assert marker in text
    for marker in ("public resources", "SHA-256", "timecodes", "near-duplicates", "robots", "Promotion gates"):
        assert marker in reference


def test_multimedia_collection_is_an_executable_strategy_workflow():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "multimedia-collection.md").read_text(encoding="utf-8")
    assert "strategy-only" in text
    assert "do not acquire" in text
    for heading in (
        "## Collection plan contract",
        "## Source priority",
        "## Query expansion",
        "## Per-format handling",
        "## Coverage and quality metrics",
        "## Staged execution",
        "## Validation checklist",
    ):
        assert heading in reference
    for marker in (
        "scope axes",
        "official and primary",
        "query log",
        "rights coverage",
        "source independence",
        "two consecutive batches",
        "completed",
        "partial",
        "blocked",
    ):
        assert marker in reference


def test_collection_strategy_plan_checkpoint_and_decisions_are_machine_readable():
    schema_path = SKILL / "schemas" / "collection-strategy.schema.json"
    example_path = SKILL / "references" / "collection-strategy.example.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    example = json.loads(example_path.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(schema["required"]) >= {
        "mode", "inputs", "outputs", "authorized_stages", "batches",
        "checkpoint", "decision", "metrics", "validation",
    }
    properties = schema["properties"]
    assert properties["mode"]["enum"] == ["strategy_only", "execution"]
    assert properties["decision"]["properties"]["state"]["enum"] == [
        "continue", "completed", "partial", "blocked"
    ]
    assert set(properties["checkpoint"]["required"]) >= {
        "last_completed_batch_id", "resume_stage", "remaining_query_families",
        "candidate_snapshot_sha256", "unresolved",
    }
    stop_rules = properties["inputs"]["properties"]["stop_rules"]
    assert set(stop_rules["required"]) >= {
        "saturation_batches", "material_gain_fields", "safety_halts"
    }
    assert stop_rules["properties"]["saturation_batches"]["minimum"] == 2
    assert set(properties["metrics"]["required"]) == {"denominators", "counts"}

    assert example["mode"] == "strategy_only"
    assert example["authorized_stages"] == ["plan"]
    assert example["batches"] == []
    assert example["decision"]["state"] == "completed"
    assert example["decision"]["resume_required"] is False
    assert example["metrics"]["counts"]["body_verified"] == 0
    assert example["metrics"]["counts"]["rights_verified"] == 0
    assert example["outputs"]["catalog_path"] is None
    assert example["outputs"]["checkpoint_path"] is None


def test_collection_strategy_validator_accepts_two_batch_saturation_fixture():
    validator = SKILL / "scripts" / "validate_collection_strategy.py"
    fixture = SKILL / "references" / "collection-strategy.execution.example.json"
    result = subprocess.run(
        [sys.executable, str(validator), str(fixture)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "COLLECTION_STRATEGY_OK" in result.stdout

    data = json.loads(fixture.read_text(encoding="utf-8"))
    gain_fields = data["inputs"]["stop_rules"]["material_gain_fields"]
    assert len(data["batches"]) == 2
    assert all(all(batch["metrics_delta"][field] == 0 for field in gain_fields) for batch in data["batches"])
    assert data["checkpoint"] == data["batches"][-1]["checkpoint"]
    assert data["checkpoint"]["last_completed_batch_id"] == "batch-002"
    assert data["checkpoint"]["unresolved"]
    assert data["decision"] == {
        "state": "partial",
        "reason": "saturation_after_2_non_improving_batches",
        "resume_required": True,
    }


def test_collection_strategy_validator_rejects_unsafe_or_inconsistent_states(tmp_path):
    validator = SKILL / "scripts" / "validate_collection_strategy.py"
    strategy_only = json.loads(
        (SKILL / "references" / "collection-strategy.example.json").read_text(encoding="utf-8")
    )
    strategy_only["authorized_stages"].append("acquire")
    unsafe_path = tmp_path / "unsafe-strategy.json"
    unsafe_path.write_text(json.dumps(strategy_only), encoding="utf-8")
    unsafe = subprocess.run(
        [sys.executable, str(validator), str(unsafe_path)],
        capture_output=True,
        text=True,
    )
    assert unsafe.returncode != 0
    assert "strategy_only" in unsafe.stderr

    saturated = json.loads(
        (SKILL / "references" / "collection-strategy.execution.example.json").read_text(encoding="utf-8")
    )
    saturated["decision"] = {
        "state": "continue",
        "reason": "incorrect_continue",
        "resume_required": False,
    }
    saturated_path = tmp_path / "saturated-continue.json"
    saturated_path.write_text(json.dumps(saturated), encoding="utf-8")
    inconsistent = subprocess.run(
        [sys.executable, str(validator), str(saturated_path)],
        capture_output=True,
        text=True,
    )
    assert inconsistent.returncode != 0
    assert "saturation" in inconsistent.stderr


def test_collection_strategy_is_host_neutral_across_serializations(tmp_path):
    validator = SKILL / "scripts" / "validate_collection_strategy.py"
    fixtures = (
        SKILL / "references" / "collection-strategy.example.json",
        SKILL / "references" / "collection-strategy.execution.example.json",
    )
    for fixture in fixtures:
        data = json.loads(fixture.read_text(encoding="utf-8"))
        codex_style = tmp_path / f"codex-{fixture.name}"
        claude_style = tmp_path / f"claude-{fixture.name}"
        codex_style.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        claude_style.write_text(
            json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        results = [
            subprocess.run([sys.executable, str(validator), str(path)], capture_output=True, text=True)
            for path in (codex_style, claude_style)
        ]
        assert all(result.returncode == 0 for result in results), [result.stderr for result in results]
        canonical = [
            hashlib.sha256(
                json.dumps(
                    json.loads(path.read_text(encoding="utf-8")),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for path in (codex_style, claude_style)
        ]
        assert canonical[0] == canonical[1]

    strategy = json.loads(fixtures[0].read_text(encoding="utf-8"))
    for index, invalid_path in enumerate(
        ("/Users/example/plan.json", "C:\\Users\\example\\plan.json", "~/.codex/plan.json", "$CLAUDE_PROJECT_DIR/plan.json")
    ):
        candidate = json.loads(json.dumps(strategy))
        candidate["outputs"]["plan_path"] = invalid_path
        path = tmp_path / f"host-specific-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        result = subprocess.run([sys.executable, str(validator), str(path)], capture_output=True, text=True)
        assert result.returncode != 0
        assert "project-relative" in result.stderr


def test_skill_defines_code_work_boundaries():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "code-workflow.md").read_text(encoding="utf-8")
    for marker in ("Code work mode", "Git", "canonical", "replaceable projections", "Current final code design"):
        assert marker in text
    for marker in ("full commit SHA", "TestRun", "derived projections", "held-out evaluation", "duplicate-safe symbols"):
        assert marker in reference


def test_session_capture_is_opt_in_and_provisional():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "post-install-verification.md").read_text(encoding="utf-8")
    for marker in ("session-capture.json", "session-proposals", "successful no-op", "Codex has no verified"):
        assert marker in text
    for marker in ("Project-local session capture", "provisional", "prompts", "secrets"):
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
