---
name: knowledge-engineering
description: Use when analyzing, proposing, collecting, modeling, reviewing, modifying, or answering from project knowledge that must remain evidence-linked and reproducible.
---

# Knowledge Engineering

Use an evidence-first Second Brain workflow: preserve what was found, compile it
into small reviewable records, validate it, then project and retrieve it. The
default answer is `abstain` when a claim is missing, stale, conflicting, or not
locatable.

## Final eight-stage workflow

1. Scope — define the question, domain, date, answer state, and acceptance criteria.
2. Collect — capture documents, datasets, images, video, audio, or URLs with identity, rights, access date, hash, and immutable revision.
3. Normalize — create stable `Source`, `Evidence`, `Claim`, `Media`, `Question`, and `ProvenanceActivity` records.
4. Model — represent typed entities, relations, temporal scope, provenance, and media derivatives; use RDF/OWL/SHACL where the project requires it.
5. Validate — run schema, SHACL, reasoning, hash, locator-replay, freshness, conflict, competency-question, and sealed-evaluator-gold checks.
6. Review — compare support and counter-evidence; keep conflicts visible; choose accept, revise, hold, or reject.
7. Project — rebuild HTML-first knowledge pages, graph JSON, search indexes, reports, Context Packs, memory pointers, and optional Archify diagrams from the approved snapshot.
8. Measure — compare baseline and ontology-assisted retrieval/generation on the same snapshot and question order; label fixture results as local measurements, not production guarantees.

## Role boundaries

### analysis/proposal role

Reason over the current graph and sources, distinguish `FACT`, `INFERENCE`,
`GAP`, `CONFLICT`, and `PROPOSAL`, and return exact evidence locators,
counter-evidence, target files, and expected effects. Keep proposals as
`proposed`; do not edit files or promote claims.

### modification role

Apply only an explicit user request or an approved proposal. Preserve originals,
provenance, prior decisions, and unrelated work. For a meaning change, append a
new revision with `supersedes` instead of overwriting history. Rebuild projections,
update state pointers, and report verification after editing.

### Coordination boundary

When delegated reasoning is needed and the project exposes a cmux session, inspect
it first and reuse its configured knowledge-engineer subagent. Create a
project-scoped one only if none exists. If cmux is unavailable, use the host's
documented coordination mechanism or report the limitation; do not silently
replace an explicitly configured project coordinator.

## Storage and host compatibility

- Keep immutable originals and canonical JSON separate from generated HTML, graphs, indexes, and reports. Explicitly named authored HTML in `knowledge/` is an input; generated HTML under `_ops/rebuild/` is a projection and must not be hand-edited.
- HTML is the human-readable knowledge projection; it must point to the Claim → Evidence → Source revision chain and media locators, not copy sealed evaluator gold or raw source indiscriminately. Metadata-only observations cannot support content claims.
- Update `knowledge-base/_ops/memory/index.json` with pointers, not source text, only after an approved review/decision, verified snapshot, or goal-state transition. Update `AGENTS.md` or `CLAUDE.md` only when an accepted shared rule changes.
- Codex reads `AGENTS.md`; Claude Code reads `CLAUDE.md` when present. Neither host file is required merely because the other exists.
- Host instruction files are platform-specific; do not require one runtime's host file in the other runtime.
- Use project-root paths and do not assume host-specific environment variables.

## Post-install integration verification

After installation, verify the skill separately from package presence. Follow
[`references/post-install-verification.md`](references/post-install-verification.md)
to confirm readable package files, host-specific discovery, one harmless
read-only smoke response, unchanged working-tree state, and the portable
workspace validator. Test Codex and Claude Code independently; success in one
host does not prove the other. Do not claim integration from a file listing,
prompt, spinner, or generic response alone.

## Required checks

Before work, read `references/record-schema.md` and the relevant sections of
`references/evidence-rules.md`. After work, run the workspace validator, the
knowledge-cycle gates, and focused tests. Never hand-edit generated projections.

```bash
python context-graph/skills/knowledge-engineering/scripts/validate_workspace.py --root . --profile project
python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope all
pytest -q context-graph/tests/test_knowledge_engineering_skill.py
```

Reports must state changed files, evidence, checks and results, failures,
unverified items, unresolved conflicts, and the next role. Read
`references/memory-update.md` and `references/validation-gates.md` when those
boundaries apply.

Answer states are `answer` (accepted claim with replayable evidence), `conflict`
(incompatible supported claims), and `abstain` (missing, stale, unknown, or
unlocatable support).
