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

## Session lifecycle journal

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
