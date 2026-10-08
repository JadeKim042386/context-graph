# Explicit session checkpoints

The default lifecycle route is unchanged. Set `checkpoint_mode` to `delta-v1`
in an already activated project's `knowledge-base/_ops/session-capture.json`
when its launcher supplies `session_id`. In this mode `record_project` sends all
four lifecycle events to `session_checkpoint.checkpoint`; it does not scan legacy
events, compile all proposals, or promote memory. The hook hashes the session ID,
uses an explicit `last_event_id` or hashes `invocation_id` (otherwise event/session/
`occurred_at`), and uses an explicit epoch or the selected session head (default 0).
When `occurred_at` is absent, the fallback is deterministic within an epoch.
Callers must provide a new event ID for changed work in that same epoch; otherwise
changed-payload delivery is correctly held as an event conflict.
No project activation or host configuration is changed by installing this code.

Both the hook route and explicit checkpoint API handle `post_compact` and
`session_start` for epoch advancement and reopening respectively.
Reopening a closed session clears closure state and preserves its epoch and last
checkpoint. Each genuinely new delivery needs a new event ID; retries keep it.
Content-equal compaction/close deliveries keep one work checkpoint; close retains
closure metadata. Same delivery identity with changed content is a conflict.

Only allowlisted status, attribution hashes and artifact revision pointers are
stored. Artifact hashes supplied by the caller remain provisional; capture does
not establish source validity, rights, review, or completion. Raw prompts,
transcripts and arbitrary payload fields are not copied.

Writes use a checksummed `pending.json`, immutable records and an atomic
`head.json`. A valid pending transaction replays after interruption. Malformed
or checksum-invalid pending bytes are renamed unchanged to
`pending-invalid-<sha256>.json`, without modifying the head. That call reports
`pending_invalid` (explicit CLI exit 2); the next call may proceed. The lifecycle
wrapper reports the condition through its status file/sanitized hook response
while preserving exit 0. Existing quarantine destinations are never overwritten;
a collision requires explicit operator review. Symlinks and conflicts with an
otherwise valid transaction fail closed and are not silently discarded.

## Context-first delivery gate

The trusted launcher can call:

```python
from session_checkpoint import context_gate
from ask import retrieval_gate
decision = retrieval_gate(expected, launcher_context, context_gate=context_gate)
```

Both `expected` and `launcher_context` must come from the trusted harness.
`expected.context_digest` identifies the **current authorized query dependencies**;
it cannot be a stale digest copied from an earlier pack. Only a matching trusted
project/session/task/assignment/role, context epoch and digest yields
`in_context` with `read_bytes=0`. The launcher must attest actual pack consumption;
model JSON containing `trusted=true` is not authority. This pure gate does not
check source freshness or grant permission on its own.

Missing, untrusted or mismatched context returns `bounded_reload` with at most
32 items / 32768 bytes as the caller's reload contract. Cross-session pointer
restore remains `bounded_reload`; only a caller supplying explicitly authorized,
query-scoped pointers may perform the subsequent reload. The wrapper itself
never reads history or loads pointers, and does not implement that reload.
It does not skip the installed fresh-session binding/continuity/audit preflight.
