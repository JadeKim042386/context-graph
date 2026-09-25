# Project-State Pointer Updates

Project memory is a short list of pointers for the next worker, not an archive of source text.

## Update triggers

- when a Review or Decision is approved
- when the current goal changes to complete, held, or blocked
- when a verified snapshot is created
- modify `AGENTS.md` only when shared working rules change

## Recorded values

- `current_goal`: goal artifact path, state, and update date
- `approved_decision_pointers`: decision artifact path, summary, state, and update date
- `unresolved_pointers`: unresolved artifact path, issue, state, and update date
- `snapshot_hash`: algorithm, actual hash, original path, snapshot ID, and state

Do not store source text, long summaries, credentials, personal data, or transient model output. If a pointer target is missing or not verified, keep its state as `unverified` or `open`.

## Order

`Review/Decision → AGENTS.md rules (when needed) → memory/index.json → projection rebuild → validators → report`

`scripts/update_memory.py` preserves the existing JSON and updates pointers only.
Pass an explicit `--status`; the updater refuses to silently mark a goal as
verified. After an automatic update, check the diff and parse the JSON.

## Pointer integrity and promotion gate

Use an explicit `--root` (default: current working directory). `--memory` must
resolve inside that project and must not itself be a symlink. Pointer paths are
project-relative; parent traversal, external URLs and symlink escapes are refused.
`path.html#id` checks an actual HTML `id` or named anchor. The SHA-256 always binds
the entire file bytes, not just the selected fragment. Other fragment formats are
not implemented by this updater and must not be claimed as verified.

`--goal ... --status verified|accepted` now also requires `--goal-hash` and
`--review`. `--snapshot-hash` requires `--snapshot-source` and
`--snapshot-review`. Hashes must be 64 lowercase hexadecimal characters and match
the current file. A missing target, missing anchor, bad/mismatched hash or missing
review fails the **whole transaction**, including any other requested update.
No directory or memory file is created on validation failure.

The review argument names a separate project-relative canonical JSON file.
Alongside the common record fields in `record-schema.md`, its minimum binding is:

```json
{
  "schema_version": 1,
  "id": "DEC-memory-goal-001",
  "record_type": "Decision",
  "revision": 1,
  "status": "accepted",
  "created_at": "2026-09-25T00:00:00Z",
  "updated_at": "2026-09-25T00:00:00Z",
  "provenance": {"agent": "configured-reviewer", "activity_id": "review-001"},
  "target_pointer": "design/example.html#result",
  "target_sha256": "REPLACE_WITH_THE_ACTUAL_64_CHARACTER_SHA256"
}
```

The placeholder deliberately fails validation; never substitute an invented hash.
`accepted` needs an accepted `Decision`; `verified` (including a snapshot) allows
a verified `Review` or accepted `Decision`. `target_pointer` must exactly match the
requested pointer including its fragment; `target_sha256` must match the requested
and recomputed hash. The updater stores `review_pointer` and `review_sha256` rather
than copying the review body. Nonempty IDs, timestamps and provenance agent/activity
and positive integer schema/revision values are required. This checks recorded
approval and revision linkage, **not reviewer identity, signature authenticity,
semantic correctness or the full canonical schema**. A trusted reviewer must create
the record under the existing approval rule; an agent must not manufacture it merely
to pass this gate.

```bash
python context-graph/skills/knowledge-engineering/scripts/update_memory.py \
  --root . --memory knowledge-base/_ops/memory/index.json --check
```

`--check` is read-only and cannot be combined with updates. Exit zero / `ok=true`
means classification completed, not that every pointer is valid. Inspect every
`classifications[].integrity_status`:

- `valid`: target/locator/hash and recorded promotion evidence all match;
- `stale`: target or stored review revision hash has changed;
- `unlocatable`: path or HTML anchor cannot be replayed;
- `unverified`: hash/approval evidence is absent, malformed, or insufficient.

Legacy pointer fields, IDs and approval history remain intact. A successful update
adds `integrity_status` and `integrity_reason` to existing pointer objects without
deleting them or rewriting their historical `status`. Read-only checks and failed
updates preserve original bytes. Consumers must not treat a historical `accepted`
status with non-valid integrity as current accepted evidence. An `open`, `proposed`,
`blocked` or `complete` goal transition is not evidence promotion; unresolved paths
can remain pending and receive a non-valid integrity classification.

All validation happens before writing, followed by a final promotion recheck.
A sibling temporary file is flushed/fsynced and atomically replaced; failed replace
leaves original bytes and removes the temporary file. No update arguments is a
byte-preserving no-op. Use a single writer: concurrent-writer locking and a lock on
mutable target/review files are not provided. This updater does not rebuild indexes,
edit AGENTS, or implement automatic approved/unresolved-list promotion.

## Session lifecycle journal

Before a new task/session or task resume, use the read-only continuity pack in
[`task-continuity.md`](task-continuity.md). It reuses this integrity contract;
it never updates memory, repairs hashes, promotes records, or executes actions.
Missing/invalid memory and an intentionally empty pack are distinct states.

After project-local capture is explicitly initialized, the Claude Code plugin
records `session_start`, `pre_compact`, `post_compact`, and `session_end` events
in the consuming project's `knowledge-base/_ops/session-events.jsonl` and
regenerates provisional proposals under
`knowledge-base/_ops/session-proposals/`. This is an operational journal and
review queue, not canonical knowledge and not the memory index. Without
`session-capture.json`, hooks are a successful no-op.

The journal stores only privacy-filtered metadata: an opaque session ID, event
type, timestamp, enumerated trigger, repository-relative artifact pointers and
hashes, working-tree digest, and review state. It must not contain prompts,
transcripts, model reasoning, command output, secrets, absolute paths, or diff
contents. Replaying a hook with the same event identity is a no-op.

Compaction and session exit may record provisional or unverified operational
state automatically. They must never promote a Claim, Evidence, Decision,
`AGENTS.md`, `CLAUDE.md`, or memory pointer. Promotion requires a later
reviewed handoff, decision, verified snapshot, or explicit goal transition.
If no close event is delivered, the absence remains unverified; it must not be
interpreted as completion.
