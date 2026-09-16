from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "context-graph" / "skills" / "knowledge-engineering" / "SKILL.md"
README = ROOT / "context-graph" / "README.md"


def test_skill_matches_final_eight_stage_design_and_role_boundaries():
    text = SKILL.read_text(encoding="utf-8")
    for marker in (
        "1. Scope",
        "2. Collect",
        "3. Normalize",
        "4. Model",
        "5. Validate",
        "6. Review",
        "7. Project",
        "8. Measure",
        "analysis/proposal role",
        "modification role",
        "HTML-first",
        "sealed evaluator gold",
        "cmux",
    ):
        assert marker in text


def test_readme_exposes_final_flow_and_cross_runtime_installation():
    text = README.read_text(encoding="utf-8")
    for marker in (
        "Scope",
        "Collect",
        "Normalize",
        "Model",
        "Validate",
        "Review",
        "Project",
        "Measure",
        "Codex",
        "Claude Code",
        "CLAUDE.md",
        "HTML",
        "quick_validate.py",
    ):
        assert marker in text
