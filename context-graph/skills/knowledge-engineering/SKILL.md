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

## Multimedia collection mode

When collecting project-related or adjacent knowledge, search broadly across
papers, standards, datasets, code, text, images, video, audio, and other media,
but keep discovery, acquisition, evidence, and promotion as separate states.
Use official or primary sources first, bounded public retrieval, robots and
rate-limit compliance, immutable quarantine bytes, content hashes, explicit
rights status, and format-specific replayable locators. Metadata-only results
cannot support content claims. OCR, transcripts, captions, frames, thumbnails,
translations, and summaries are derivatives of their source, not independent
corroboration. Unknown rights remain `unverified`; public playback does not
imply download or redistribution permission. Never bypass authentication,
paywalls, robots, access controls, or rate limits, and never collect secrets,
private data, or raw session content.

Read [`references/multimedia-collection.md`](references/multimedia-collection.md)
for source discovery, bounded acquisition, media records, deduplication,
extraction, rights, locator, stop, and validation contracts.

Start with a collection plan that fixes scope axes, source priorities, query
families, budgets, metrics, and termination rules. For a strategy-only request,
return that plan and its validation contract; do not acquire, download, OCR,
transcribe, or promote sources. Execute a stage only when the request authorizes
that stage, and preserve a resumable checkpoint when a safety or budget gate
stops the work. Use `schemas/collection-strategy.schema.json` for machine-readable
plans, batches, checkpoints, decisions, and metrics; start from
`references/collection-strategy.example.json` for a no-acquisition plan.
Validate either strategy or execution artifacts without installing dependencies:

```bash
python context-graph/skills/knowledge-engineering/scripts/validate_collection_strategy.py <artifact.json>
```

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

## Code work mode

For repository analysis, bugs, features, refactors, compatibility work, and
test review, read [`references/code-workflow.md`](references/code-workflow.md).
Code uses the same evidence-first boundary: Git and reviewed JSON records are
canonical; symbol graphs, SCIP, Tree-sitter, RDF, SQLite, HTML, and Context
Packs are replaceable projections. A branch, line number, symbol name, search
result, passing test, or generated graph is not proof by itself.

### Current final code design

Use Git plus reviewed JSON/JSONL as the canonical layer. For Python code, use
the commit-bound AST adapter; recognized non-Python languages use a
deterministic lexical fallback. Preserve duplicate-safe symbols, bounded
`contains`/`imports` one-hop expansion for AST-backed Python nodes,
language/parser/confidence metadata, and replayable locators. Lexical fallback is low-confidence discovery evidence
and must not claim type resolution, control-flow certainty, or runtime binding.
Do not make SCIP, RDF, a graph database, embeddings, or a runtime backend
mandatory unless a paired held-out evaluation proves a material gain without
locator, false-answer, latency, or Context Pack regressions.

## Storage and host compatibility

- Keep immutable originals and canonical JSON separate from generated HTML, graphs, indexes, and reports. Explicitly named authored HTML in `knowledge/` is an input; generated HTML under `_ops/rebuild/` is a projection and must not be hand-edited.
- HTML is the human-readable knowledge projection; it must point to the Claim → Evidence → Source revision chain and media locators, not copy sealed evaluator gold or raw source indiscriminately. Metadata-only observations cannot support content claims.
- Update `knowledge-base/_ops/memory/index.json` with pointers, not source text, only after an approved review/decision, verified snapshot, or goal-state transition. Update `AGENTS.md` or `CLAUDE.md` only when an accepted shared rule changes.
- Codex reads `AGENTS.md`; Claude Code reads `CLAUDE.md` when present. Neither host file is required merely because the other exists.
- Host instruction files are platform-specific; do not require one runtime's host file in the other runtime.
- Use project-root paths and do not assume host-specific environment variables.

## Session and compaction continuity

When the Claude Code plugin receives `SessionStart`, `PreCompact`,
`PostCompact`, or `SessionEnd`, it records a privacy-filtered operational event
in `knowledge-base/_ops/session-events.jsonl` and regenerates a provisional
proposal under `knowledge-base/_ops/session-proposals/`. This occurs only after
the consuming project creates `knowledge-base/_ops/session-capture.json` with
the activation CLI in `references/post-install-verification.md`; otherwise
hooks are a successful no-op. The journal preserves the session boundary,
changed artifact pointers, hashes, and verification state so the next session
can recover work without copying the conversation.

Treat these events as provisional or unverified operational history. Never copy
raw prompts, transcripts, model reasoning, secrets, absolute paths, or diff
contents into the journal. Never update canonical Claim, Evidence, Decision,
`AGENTS.md`, `CLAUDE.md`, or `memory/index.json` directly from a lifecycle hook.
Promote durable knowledge only after a reviewed handoff, decision, verified
snapshot, or explicit goal transition. A missing `SessionEnd` event is not
completion evidence.

Codex has no verified universal lifecycle-hook surface. Do not claim automatic
Codex compaction or exit capture; use the CLI from an explicitly configured
automation when needed.

Read [`references/memory-update.md`](references/memory-update.md) for the
journal schema, privacy boundary, deduplication, and promotion rules.

## Session preflight (start and resume)

Before evidence-backed work in a new or resumed session, run these read-only
commands in this order from the selected installed skill roots and report their
states separately. Never reuse or cache a previous session's output.

```bash
python -B <context-graph skill root>/scripts/ask.py --project-root <project> --binding-only
python -B <knowledge-engineering skill root>/scripts/build_task_continuity.py --root <project>
python -B <knowledge-engineering skill root>/scripts/audit_memory_support.py --root <project>
```

If `scripts/audit_memory_support.py` is absent from the selected root, report
`supporting_evidence_audit=unavailable` and make no evidence-replay claim; do
not substitute a checkout copy or another installation. Report binding
`status`, continuity `pack_status` / applicable / unresolved / `memory_complete`,
and audit `support_replay_complete` plus valid / stale / unlocatable /
unverified and omission counts as distinct facts. Exit 0 means the audit ran,
not that support is complete; `inputs_sha256` is not a cache key. Read
[`references/memory-support-audit.md`](references/memory-support-audit.md).

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
