# Read-only task continuity at session start or resume

Run this explicitly from a new session or when resuming a task. It is a local
standard-library CLI, not a host lifecycle hook or automatic memory updater.
Codex and Claude can consume the same JSON; actual host invocation is not proven
by the existence of this script.

```bash
python -B context-graph/skills/knowledge-engineering/scripts/build_task_continuity.py \
  --root . --memory knowledge-base/_ops/memory/index.json
```

The CLI prints JSON to stdout only. It does not write memory, indexes, generated
files, config, host instructions, or bytecode. Do not redirect stdout over source
records. No network, model call, shell command execution, directory search, graph
refresh, or automatic promotion occurs.

Project binding is now explicit in `binding`: cwd must be the selected root or
a descendant, otherwise `invalid_memory` / `cwd_mismatch` / exit 2 with no items.
The root identity is its SHA-256 (`root_id`), not an absolute path copied to output.
`allowed_source_roots=["."]` means this reader's existing project-relative pointer
scope, subject to its privacy filters. `config_map_state=not_used` makes clear
that it never loads knowledge/global config; binding validity is independent of
memory integrity. An in-root path may still have missing/invalid memory content.

## Reading the pack

`items` retains the four memory groups: `current_goal`, `snapshot_hash`,
`approved_decision_pointers`, `unresolved_pointers`. `slot` identifies each list
entry. Ordering is current goal, snapshot, approved decisions in stored order,
then unresolved entries in stored order for assessment. Cycle 06 assesses up to
128 entries before applying the output limit, resolves verified relations, then
prioritizes active accepted Decisions, other active records, conflicts, and retired
or duplicate aliases. Ties preserve stored order. Wall-clock recency alone never
creates acceptance or supersession.

Each item includes a project-relative pointer, declared status, freshly computed
integrity classification, target revision SHA-256 when supplied, review pointer
and hash, lifecycle state, supersedes links, required constraints, and next-action
codes. `record_id` and `record_revision` refer to the bound Review/Decision, not an
invented source version; the source revision is `revision_sha256`. A `snapshot_hash`
item carries the source pointer and digest. The memory bytes are bound separately
by `memory_sha256`. These are evidence bindings, not freshness guarantees after
the invocation has ended.

The pack does not replay the `evidence[]` entries a proof declares; for that one
extra read-only hop see [`memory-support-audit.md`](memory-support-audit.md).

Do not infer permission from a field named `approved_decision_pointers`. The
cycle-01 `update_memory.classify` contract is recomputed with bounded reads.
Historical `accepted`/`verified` status alone cannot enable an item.

| Field/state | Meaning |
|---|---|
| `pack_status=ready` | The bounded inventory has valid integrity, known decision context and resolved relations; no mismatch, omission or unresolved relation was found |
| `partial` | Missing/unsafe/stale/unverified/unknown entries, metadata or relation problems remain visible; independently verified items may be applicable, subject to the bounds below |
| `conflict` | Conflicting items remain visible and inapplicable with criterion codes; independent non-conflicting items may still be applicable |
| `empty` | Valid schema-version-1 memory with zero entries; not evidence that there are no project rules |
| `missing_memory` | Requested memory file does not exist; exit 2 |
| `invalid_memory` | Invalid schema/JSON, duplicate keys, unsafe memory path, unreadable file or input limit; exit 2 |
| `integrity_status=valid/stale/unlocatable/unverified` | Same target/anchor/hash/recorded-review semantics as cycle-01 |
| `integrity_status=unknown` | Invalid entry, unsupported data or a read limit prevents classification |
| `continuity_state=unknown` | No fully validated structured continuation metadata; not an empty list of obligations |
| `applicable=true` | This item has replayable proof, known matching/inventory context, active lifecycle and no blocking relation; usable within its evidence scope, not approval to execute or promote |
| `safety.memory_complete=false` | The memory is incomplete even if some items are applicable; preserve unresolved items and review them before dependent actions |

Exit 0 for `partial`/`conflict`/`empty` means successful pack construction, **not permission
to proceed**. The consumer must inspect pack and item states, preserve unresolved
conditions, and obtain missing evidence/approval before acting. A pack never
overrides current user instructions or host/project rules.

### Cycle 11: item applicability is separate from pack completeness

An integrity-valid, context-known verified **Review** or accepted **Decision** can
be applicable in a partial pack. A Review supports only its recorded observation;
it does not become an accepted Decision. Missing/open/unverified, context-unknown,
retired, duplicate, conflicting and invalid-relation items stay inapplicable and
remain in the output. Failed relation claims also block their named endpoints.
No record is promoted, repaired or deleted by this calculation.

Every memory-mode response, including errors, carries `safety.memory_complete`
and the fixed constraints `do_not_assume_complete_memory`,
`review_unresolved_before_dependent_action`, and `applicability_is_not_approval`.
Only ready or valid empty inventories are complete. Applications must surface
these warnings with applicable items, not hide the unresolved list. This is not
a proof that an unknown historical decision cannot affect a proposed action.

Output omissions, an incomplete relation scan/read budget, or a supplied cache
dependency mismatch still block **all** item applicability. Complete assessment
is required before allowing independent items. Pack cache reuse still requires
a ready pack and exact query/digest match; partial/conflict packs never reuse
cached answers. The dependency policy is `continuity-item-applicability-v3`, so
old policy digests cannot silently authorize reuse. No real memory migration is
performed by this contract update. The additive `safety` field is required by
the current output schema; consumers validating old saved packs must retain
their old schema or regenerate rather than mutate historical outputs.

## Structured metadata boundary

The existing bound Review/Decision JSON may contain this optional `continuity`
object. It is protected by the memory entry's `review_sha256`; adding it to an
existing record requires the normal review/revision process. This reader never
adds it and never repairs memory hashes to make it appear verified.

```json
{
  "continuity": {
    "lifecycle_status": "active",
    "supersedes": [],
    "required_constraints": ["no_commit", "no_push", "preserve_user_changes"],
    "next_actions": ["review_evidence", "run_focused_tests"],
    "decision_context": {
      "question_key": "Q-storage",
      "scope": "project",
      "as_of": "2026-09-25",
      "outcome_id": "store-json"
    },
    "conflicts_with": []
  }
}
```

The outer record must satisfy cycle-01's complete Review/Decision contract.
This fragment alone is neither a valid proof nor a new approval. `decision_context`
is required for applicability as of cycle 06; legacy proofs without it remain
preserved but `context_status=unknown`, partial and inapplicable. Never invent or
automatically insert context into an accepted proof. A curator must explicitly
review/bind question, scope, date and normalized outcome. Required lists
must be explicit (including `[]`); absent or unsupported values produce unknown,
never inferred defaults. Memory-level free text, summary, constraint and action
fields are not trusted instructions because they are not bound by the review hash.
No prose is extracted from HTML bodies, prompts, transcripts or source documents.

Allowed constraint codes:

| Code | Meaning |
|---|---|
| `no_network` | No external acquisition or network request |
| `no_commit`, `no_push`, `no_deploy` | Do not perform the named external/version-control operation |
| `no_source_edits` | Preserve source material without editing |
| `no_memory_edits` | Do not modify actual memory |
| `no_generated_edits` | Do not hand-edit generated projections |
| `preserve_user_changes` | Preserve unrelated existing changes |
| `review_before_promotion` | Require configured review before acceptance |
| `no_secrets` | Do not store or expose secrets/private transcript content |

Allowed next-action codes are `review_evidence`, `replay_locator`,
`run_focused_tests`, `check_snapshot`, `request_approval`, `resolve_conflict`,
and `review_unresolved`. They describe review tasks associated with that item's
pointer. They are not runnable commands. Arbitrary project-specific prose or a
new code is deliberately unsupported in this first slice and remains unknown.

Lifecycle may be `active`, `superseded`, `deprecated`, or `retracted` in the
bound continuity object. The memory's recorded retirement and a JSON target's
explicit retired status cannot be upgraded to active. Only bound metadata
provides effective `supersedes` links, using the Review/Decision IDs present in
the pack. Unknown IDs, contradictory duplicate ID bindings, self-links and cycles
block applicability. Retired/superseded entries remain visible, not deleted.
This does not discover unlisted decisions or resolve semantic conflicts.

### Cycle 06: conflicts, exact scope, deduplication and cache identity

Question key, scope and outcome are conservative opaque identifiers, not free text.
The as-of value is an exact ISO calendar date. A curated outcome ID denotes one
mutually exclusive answer alternative for that exact question/scope/date. Do not
use unrelated outcome IDs for claims that can coexist: the checker intentionally
blocks different IDs with the same context as a conflict, it cannot infer meaning.

Optional query mode requires all three arguments together:

```bash
python -B context-graph/skills/knowledge-engineering/scripts/build_task_continuity.py \
  --root . --question-key Q-storage --scope project --as-of 2026-09-25
```

Exact match yields `context_status=match`; a mismatch yields `mismatch`, partial,
and blocks that item, not independently matching items. With no query, `inventory` is review context, not a scoped
answer. No date-range reasoning, scope inheritance or alias normalization is inferred.

Only integrity-valid, active **accepted Decision** metadata may supersede another
record of the same question/scope/date. A verified Review is not sufficient. Missing
targets, ambiguous IDs, cycles, cross-context links and retired superseders block
applicability. Retraction of a superseder does not silently approve an old decision.
No timestamp or larger revision number manufactures a replacement decision.

Identity means record ID/revision, target path/hash, proof path/hash, recorded status
and lifecycle, not just equal source bytes. Identical aliases stay visible for audit
with `duplicate_of`, `lifecycle_status=duplicate`, and `applicable=false`; only the
representative is an application candidate. Different revisions/proofs/paths are
never collapsed. `duplicate_count` counts aliases, not missing entries, so existing
`included_count + omitted_count = total_count` continues to hold.

Conflicting items retain their own target/review pointers and hashes, `conflicts_with`
IDs and `conflict_criteria` codes:

| Criterion | Evidence boundary |
| --- | --- |
| `same_context_different_outcome` | Different curated alternatives for identical question/scope/date |
| `declared_conflict` | Explicit bound conflict link, including a self-conflict declaration |
| `duplicate_record_id` | One ID used for incompatible revision bindings; neither is silently chosen |
| `supersedes_cycle` | Cyclic verified replacement links; not a valid precedence order |
| `target_conflict` | Hashed canonical JSON target itself records conflict |
| `recorded_conflict_unverified` | Memory declares conflict; warning retained without promoting its truth |

`conflict_count` covers assessed records even if output truncation hides some. Unknown
or cross-context conflict IDs block as unresolved. `assessed_count` and
`relation_scan_complete` expose the 128-entry inspection limit/read-limit gaps.
Relations are assessed before output ranking, so an old first-listed pointer cannot
hide a verified superseding Decision within that bound. Any omitted or unassessed
context still blocks application; the tool does not pretend to have complete memory.

`dependency_sha256` binds policy version, project-root identity, exact memory bytes,
query, limits, hashes of actually read target/proof bytes, and assessed states. It
does not use mtime as revision proof. Pass an earlier digest with
`--expected-dependency-sha256 <64-lowercase-hex>` only to check a proposed cache reuse.
The tool still replays all relevant evidence and **never reads or writes a cached
answer**. Digest match alone does not authorize reuse: `cache_reusable=true` also
requires an exact query and a ready, complete, non-conflicting pack. Mismatch blocks
applicability and reuse. Missing, stale, conflicting or incomplete evidence never
becomes eligible just because a digest matches. Changes to the retrieval policy
require a policy-version bump; this is not a signed model/prompt/runtime attestation.

Ordinary `ask.py` lexical/graph source ranking is not changed by this cycle. Use this
continuity gate for memory decisions, not lexical relevance as approval. There is
no evaluator lookup, answer oracle, learned conflict resolver, or automatic memory
repair. Sealed gold remains outside pointers and Context Packs.

## Boundedness and privacy

Defaults: 32 entries, 256 KiB per target/review, 1 MiB total unique-file reads,
32 KiB output. Memory itself has a fixed 256 KiB cap independent of the target
limit. CLI overrides are capped at 128 entries / 1 MiB target / 8 MiB total /
128 KiB output. Reads are cached within one invocation, not across sessions.
Output over budget drops complete trailing ranked items and increments `omitted_count`;
it never truncates a constraint string or silently claims a complete pack.
The JSON plus final newline respects the requested byte budget.
If even the empty metadata envelope cannot fit, the CLI rejects the requested limit
with exit 2 instead of emitting an oversized pack. Up to 128 entries are assessed
independently of `max_entries`, under the same total byte-read budget.
One overflow-detection byte is reserved inside the total read budget, so a file
growing after its size check cannot push total bytes read beyond that budget.

Pointers must be conservative ASCII project-relative paths. Traversal, external
URLs, absolute paths, hidden paths, escaping symlinks, non-regular files and
sensitive-name paths (secrets, credentials, prompts, transcripts, evaluator/gold)
are not loaded. Unsupported Unicode/path syntax is conservatively unlocatable,
not rewritten. Unsafe input strings and exception details are not echoed.
Fields are allowlisted; no source/proof body is emitted. Closed constraint/action
vocabularies cannot carry arbitrary prompt instructions. Record IDs and paths
still require the repository's no-secrets convention: syntactic filters cannot
prove that a seemingly benign identifier has no private meaning.

The process does not lock source files against concurrent edits, authenticate
reviewers, or prove semantic correctness. A cached byte snapshot is consistent
within the read operation but is not a multi-file atomic repository snapshot.
Filesystem races under hostile concurrent mutation remain outside this slice.

## Verification

Output schema: `schemas/task-continuity-pack.schema.json` (JSON Schema 2020-12).
The CLI adds no dependency; tests use the repository's existing jsonschema package.
Schema validation alone does not enforce arithmetic or cross-record relationships;
behavioral tests assert counts, byte budgets, relation handling and no side effects.

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  context-graph/tests/test_task_continuity.py \
  context-graph/tests/test_update_memory.py \
  context-graph/tests/test_session_events.py \
  context-graph/tests/test_knowledge_engineering_skill.py
```

New-session procedure: build the pack → inspect its state and unresolved entries
→ review the valid constraints/pointers → carry the user's current task boundaries
forward. No automatically delivered Codex/Claude hook, memory migration or improved
model recall is claimed by these deterministic fixture tests.

## Explicit compact/close capture and session handoff (cycle 05)

Use this route only when the user has authorized project-local lifecycle capture.
It is not an installed host hook. Existing `record` / v2 JSONL / proposal behavior
is unchanged; the strict new route is `capture`. It never auto-detects a root from
`CLAUDE_PROJECT_DIR`, reads the global map config, compiles a projection, or writes
memory. Do not describe a successful CLI fixture as automatic Codex/Claude delivery.

From the selected project root (or a descendant):

```bash
python -B context-graph/skills/knowledge-engineering/scripts/record_session_event.py \
  capture --root . --runtime codex --event pre_compact < approved-event.json
python -B context-graph/skills/knowledge-engineering/scripts/build_task_continuity.py \
  --root . --session-handoff
```

`--runtime` is `codex` or `claude-code`; events are `pre_compact`, `post_compact`,
and `session_end`. These are caller assertions, not verified runtime identities.
Use the same explicit route at a supported user/agent-controlled checkpoint;
do not invent host lifecycle support. Abrupt exit without invocation loses capture.

The read-only `--session-handoff` selects a **separate provisional session pack**,
not the reviewed memory pack. Run both modes on resume when both are needed.
Session success cannot upgrade missing/invalid memory to ready or override a current
instruction. Memory-specific CLI limit overrides do not change the fixed session
limits described below.

### Opt-in and request contract

The existing project-local `knowledge-base/_ops/session-capture.json` must have
schema version 1, `enabled=true`, a `project_id` equal to `PRJ-` plus the first
16 hex characters of SHA-256 of the resolved absolute root, nonempty `include_globs`,
`tracked_paths_only=true`, and `capture_content/capture_commands/capture_untracked=false`.
These flags prohibit automatic content/command/untracked-file collection.
The explicit route hashes only caller-selected pointers inside configured include
patterns and verifies they are tracked by the selected project's Git index. It does
not discover changed files, stage, or commit. Git root must match the explicit root;
foreign Git environment bindings are ignored and optional index writes disabled.
Git absence/failure or an untracked pointer remains unverified. A tracked file can
have uncommitted bytes: the event binds those actual bytes, not an invented commit.
Config absence/disabled/malformed/foreign binding
is an exit-2 error, not a successful capture. Do not initialize/overwrite config
just to make a probe pass; configuration changes require separate user authority.

Stdin is a strict, duplicate-key-free JSON object with exactly these fields:

```json
{
  "schema_version": 1,
  "session_id": "00000000-0000-4000-8000-000000000001",
  "invocation_id": "00000000-0000-4000-8000-000000000002",
  "occurred_at": "2026-09-25T01:00:00Z",
  "artifact_pointers": [
    {"pointer": "knowledge/result.html#result", "revision_sha256": "REPLACE_WITH_ACTUAL_64_LOWERCASE_HEX_SHA256"}
  ],
  "required_constraints": ["no_commit", "no_push"],
  "next_actions": ["review_evidence"]
}
```

The hash placeholder deliberately fails validation. Select actual permitted artifacts,
compute their bytes' hashes, and reuse the same opaque UUID-shaped session/invocation
IDs and UTC timestamp for a delivery retry. A new checkpoint needs a new invocation
ID. IDs are stored only as digests; arbitrary names, payload keys, prose, commands,
prompts/transcripts, evaluator/gold pointers, and sensitive paths are rejected.
Paths/identifiers must still obey the no-secrets convention; syntax is not a semantic
privacy classifier. `occurred_at` is supplied, not an authenticated timestamp.

### Immutable records and read-time verification

Records use `schemas/session-event-v3.schema.json`. The dependency-free implementation
also enforces dates, allowed paths, file/hash/HTML-anchor replay using cycle-01's
`checked_bytes`, deterministic event identity, canonical field normalization,
content digest, and current config binding. JSON Schema alone cannot prove these.

The only capture output is a new immutable record under
`knowledge-base/_ops/session-events-v3/SEV-<digest>.json`. Complete bytes are flushed
to a mode-0600 sibling temporary file and atomically linked without overwriting an
existing event. Byte-identical replay returns `duplicate`; reuse of an event key
with different content/config returns `event_id_conflict`. A concurrent identical
delivery publishes one record. Unsupported hard-link publication returns an error;
there is no unsafe overwrite fallback. Earlier events and source files are preserved.

`event_id` binds project/session/invocation/runtime/event type. `record_sha256` hashes
the canonical compact sorted JSON plus newline with that field omitted. Handoff
`revision_sha256` hashes the complete event file bytes instead. Neither is a signature.
Records stay `provisional/not_reviewed`. The stored v2 journal is neither migrated
nor silently treated as v3 verified evidence.

On resume, the reader verifies event structure/digest/project identity and replays
artifact hashes/HTML anchors without exposing bodies. It returns pointer + revision,
session/event metadata, coded constraints/actions, and `integrity_status`:
`valid`, `stale`, `unlocatable`, `unverified`, or `unknown`. Config-byte changes make
otherwise readable events unverified. `applicable=false` always: even valid session
metadata only supports review, never approval or a claim about successful work.

`pack_status=ready` means all selected provisional locators replay and none is omitted;
`partial` preserves stale/unlocatable/unknown entries or omissions; `empty` requires
valid enabled config and no v3 events. Malformed records, foreign binding, missing
config and unsafe journal paths yield `unverified`, explicit reason, no items, exit 2.
No records are deleted, repaired, promoted or silently skipped. Unpublished `.pending-`
temporary files are not events; they may remain after a crash.

### Limits and remaining boundaries

- 16 KiB stdin/config/event; 1–8 artifact pointers; 256 KiB per artifact read and
  2 MiB artifact-read budget per capture/handoff. Source bodies are hashed in memory,
  never saved or emitted.
- 128 published events per journal; at capacity a new capture fails with
  `journal_limit` (identical replay still works). Archival/rotation is not automatic.
- Handoff includes at most 16 events ordered by supplied timestamp then event ID,
  retains the latest bounded window, and fits 32 KiB. Counts expose omissions;
  omissions mean partial, never silently complete. Event scanning reads up to
  128 × 16 KiB in addition to artifact/config budgets.
- File and output limits are not an authenticated or transactional filesystem.
  Hostile concurrent filesystem mutation, hard-link alias attacks, machine crashes,
  timestamp trust and signed identity remain unverified. Directory scans and failed
  concurrent capacity races are not a production-scale journal service.

Tests: `pytest -q context-graph/tests/test_session_continuity.py` plus the existing
session, task-continuity, memory, package and skill tests. No actual configuration,
memory, journal or host-hook changes are implied by adding this capability.
