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

### Harness knowledge boundary

Role names, session IDs, and agent IDs in a prompt or event payload are
attribution only. A trusted launcher must provide a project-bound harness
manifest containing a fail-closed role policy, trusted binding, and scope
catalog. The effective read set is the intersection of project policy,
session role, agent role, task cap, and assignment cap. Missing, unknown,
revoked, stale, foreign, uncatalogued, or unsafe inputs deny the request;
there is no wildcard or legacy bypass in harness mode. Filtering happens
before ranking, truncation, graph expansion, or source replay. Harness access
does not grant review, merge, promotion, or filesystem isolation authority.

Use `scripts/knowledge_harness.py` for the read-only authorization boundary.
The JSON contracts are `schemas/role-policy.schema.json`,
`role-binding.schema.json`, `knowledge-scope-catalog.schema.json`, and
`knowledge-access-decision.schema.json`. Legacy v3/v4 events remain unchanged
and are treated as unknown-role data when a role-bound read is requested.

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
hooks are a successful no-op. Likewise the map-refresh hooks (`SessionStart`,
`SubagentStop`, `PostCompact`) exit 0 with a one-line `status=skipped`,
`reason=project_not_activated` JSON in a project that has no
`.context-graph/config.json`; `build_map.py` itself still fails closed when
invoked directly, and symlinked or malformed config paths are still validated. The journal preserves the session boundary,
changed artifact pointers, hashes, and verification state so the next session
can recover work without copying the conversation.

For projects that set `checkpoint_mode` to `delta-v1`, lifecycle events use the
project-local checkpoint store instead of rereading the full journal. The first
`PreCompact` or `SessionEnd` event writes a privacy-filtered delta; repeated
events are idempotent by session, epoch, digest, and event identity. A later
`SessionStart` reopens the same checkpoint epoch, while `PostCompact` advances
the epoch once. A trusted current-context match returns `in_context` without
disk reads; missing or untrusted context returns bounded query-scoped
`bounded_reload`. This mode never stores raw prompts or transcripts and does
not claim context presence when the host cannot provide a trusted epoch and
dependency digest. See [`references/session-checkpoint.md`](references/session-checkpoint.md).

Treat these events as provisional or unverified operational history. Never copy
raw prompts, transcripts, model reasoning, secrets, absolute paths, or diff
contents into the journal. Never update canonical Claim, Evidence, Decision,
`AGENTS.md`, `CLAUDE.md`, or `memory/index.json` directly from a lifecycle hook.
Promote durable knowledge only after a reviewed handoff, decision, verified
snapshot, or explicit goal transition. A missing `SessionEnd` event is not
completion evidence.

### Actual knowledge partition lifecycle

Lifecycle events and checkpoints remain provisional operational history. Actual
knowledge is separated by explicit role- and scope-bound partitions. Use
`scripts/knowledge_partitions.py` to create a partition, write evidence-linked
`KnowledgeCandidate` records, freeze a partition, and query only explicitly
authorized partition IDs. `session_knowledge.close_agent()` freezes matching
knowledge partitions; it does not promote event logs into knowledge.

Use `scripts/merge_knowledge.py` to plan and apply a review-gated merge. All
input partitions must be frozen, conflicts remain visible, and approval must
bind the exact merge plan. Applied `CanonicalKnowledgeRecord` records retain
partition, session, agent, role, source, and approval provenance. The existing
`merge_session()` function remains the provisional event-overlay operation and
is not a canonical knowledge merge.

## Context efficiency

Use `scripts/context_efficiency.py` when preparing knowledge for a prompt.
`query_key()` combines the project, canonical question, scope, as-of date, and
dependency digest. `build_pack()` validates that query context, sorts inputs
deterministically, removes exact duplicates, preserves version conflicts and
governance fields, hashes raw provenance, applies item and final serialized-byte
limits, and sends locators/provenance references first; full claim values are
omitted for unverified, retracted, superseded, stale, or conflicting content.
`reuse()` verifies the sealed pack hash, internal counts, query-key derivation,
and dependency digest before reuse. Otherwise it returns `bounded_reload`, so
the caller retrieves only the missing or changed evidence instead of replaying
the whole knowledge base. Canonical JSON bytes and omitted items are measurable
local metrics, not model token counts; actual token savings require host
tokenizer measurement.

Codex has no verified universal lifecycle-hook surface. Do not claim automatic
Codex compaction or exit capture; use the CLI from an explicitly configured
automation when needed.

### Session/agent merge and split

Session and agent knowledge follows a reversible overlay pattern. When a
session or agent opens, its hashed identity and role boundary are registered.
During lifecycle capture, provisional event pointers are merged into the
project-wide `session-knowledge-overlay.jsonl` with their source store,
revision, session, agent, task, assignment, and role provenance. When the
session closes, the state is marked closed and the same overlay is rebuilt
idempotently. A split view filters that overlay by the original selectors,
so project-wide context can be assembled without losing per-session or
per-agent history.

This is a provisional merge, not automatic canonical-memory promotion. Only
the existing reviewed `promote_session.py` flow may update durable memory.
Use `scripts/session_knowledge.py open|close|merge|split`; denied or unknown
role-bound data remains withheld by the harness.

### Metacognitive consolidation loop

After overlay merge or session close, `scripts/consolidate_knowledge.py
compact` performs a bounded replay pass. It clusters exact source-revision
repeats, scores provenance and utility, writes duplicate/overlap proposals, and
rebuilds a separate compact projection. Exact duplicates are hidden only in
that generated projection; sources, evidence, conflicts, and unresolved
proposals remain available. Semantic equivalence is never assumed, canonical
records are never deleted, and promotion still requires review.

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

When the same work may have been attempted by another session, use the
opt-in `scripts/plan_task_reuse.py` planner after this preflight. It computes
separate task and evidence fingerprints and requires a trusted harness before
revealing candidates. Only a reproducible accepted 작업 완료·검토 참조 기록 can produce
`reuse` or `skip`; stale evidence produces `refresh`, a changed task produces
`branch`, and missing authority, provenance, locator, or completion evidence
produces `hold`/`abstain`. This planner never executes work, promotes records,
or treats semantic similarity as proof. See
[`references/task-reuse.md`](references/task-reuse.md).

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
