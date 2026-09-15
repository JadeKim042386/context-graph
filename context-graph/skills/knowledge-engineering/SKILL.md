---
name: knowledge-engineering
description: Use when collecting, analyzing, proposing, reviewing, modifying, or answering from project knowledge that must remain evidence-linked, reproducible, and safe to update.
---

# Knowledge Engineering Skill

Manage project knowledge as **originals → canonical records → review and approval → search and answers**. Keep originals separate from generated results; do not guess when evidence cannot be reproduced.

## Cross-runtime project instructions

This skill is shared by Codex and Claude Code, but host instruction files are
platform-specific. Read the instruction file that exists in the host project:

- Codex commonly uses `AGENTS.md`.
- Claude Code commonly uses `CLAUDE.md`; it does not automatically load `AGENTS.md`.

Do not require either file merely because the other platform uses it. Update the
host's instruction file only when the shared project rules actually changed;
otherwise keep durable state in `knowledge-base/_ops/memory/index.json`.

Run the quick commands from the project root. In a Claude Code plugin checkout,
use the plugin-root paths shown by the plugin README; in a Codex Skill upload,
use paths relative to the project being worked on. Never assume that a
platform-specific environment variable exists in the other runtime.

## Scope

- Collect and normalize material; create Claim, Evidence, Source, and Media records
- Write analyses, proposals, and modifications
- Manage approvals and revisions through Review and Decision records
- Update project-state pointers in `AGENTS.md` and `knowledge-base/_ops/memory/index.json`
- Rebuild HTML, search indexes, relationship graphs, and Archify diagrams

## Execution contract

1. Before starting, read `references/record-schema.md` and the relevant `references/evidence-rules.md`.
2. Preserve originals as immutable inputs and assign stable IDs, revisions, and provenance to canonical records.
3. Keep analysis results as `proposed`; do not promote them to `accepted` without the user's request.
4. Edit only canonical JSON or explicitly named Markdown/HTML originals. Do not edit generated HTML, graphs, or indexes directly.
5. After review and approval, update project-state pointers using `references/memory-update.md`. Change `AGENTS.md` only when shared rules change.
6. Rebuild projections and Archify artifacts from the approved snapshot, then run `references/validation-gates.md` checks.
7. Reports must state changed files, evidence, tests, failures, unverified items, and the next role.

## Analysis and proposal role

Break questions into scope, reference date, and decision criteria. Separate direct evidence from interpretation and state evidence, trade-offs, and verification methods for each alternative. Search scores are candidate-selection signals, not evidence.

## Modification role

Apply only approved proposals. When meaning changes, create a new revision with a `supersedes` relationship instead of overwriting the old record. Rebuild affected projections and update project-state pointers after the change.

## Answer states

- `answer`: an accepted Claim, reproducible Evidence, and matching Source revision exist
- `conflict`: incompatible evidence exists within the same scope and no decision criterion resolves it
- `abstain`: evidence is missing, stale, unknown, or unlocatable

## Quick commands

```bash
python context-graph/skills/knowledge-engineering/scripts/update_memory.py --help
python context-graph/skills/knowledge-engineering/scripts/validate_workspace.py --root .
python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope all
```

Use the references for detailed fields and exception rules. Do not place secrets, source copies, evaluation answers, or transient model output in memory, reports, or Context Packs.
