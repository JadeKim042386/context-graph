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
