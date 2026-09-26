# Read-only supporting-evidence replay for memory-bound proofs

`build_task_continuity.py` classifies each memory pointer's target and its bound
Review/Decision (proof) hash. It does not replay the local `evidence` entries that
the proof itself declares. `audit_memory_support.py` adds that one hop, read-only,
and reports it separately so a consumer can keep a proof's recorded status while
withholding a "fully replayed evidence chain" claim.

```bash
python -B context-graph/skills/knowledge-engineering/scripts/audit_memory_support.py \
  --root . --memory knowledge-base/_ops/memory/index.json
```

Scope: only proofs the continuity reader marks `applicable`; only `evidence[]`
entries with a project-relative `path` and a 64-hex `sha256`; one hop, no
recursion, no network, no inference, no repair, no writes, no bytecode. Path
confinement and bounded reads reuse the continuity reader (`safe_pointer`,
`BoundedReader`), so outside-root paths, dot-prefixed parts, symlink escapes and
unsafe names are `unlocatable`, and file/total limits surface as `unverified`
with a `read_limit` reason instead of a silent pass.

Output is pointer-only JSON: `binding`, `pack_status`, `memory_sha256`,
`dependency_sha256`, the unchanged continuity counts, then per proof the
`record_id`, `review_pointer`/`review_sha256`, `evidence_declared`,
`replay_status` (`complete`, `incomplete`, `not_declared`, `invalid_evidence`,
`stale_or_unreadable_proof`) and per entry `locator` (`/evidence/N`), `path`,
`expected_sha256`, `actual_sha256`, `status` (`valid`, `stale`, `unlocatable`,
`unverified`) and `reason`. `totals` counts entries and omissions,
`support_replay_complete` is true only when every applicable proof declared
evidence and every entry replayed `valid` with no omissions or truncation.
Exit 2 only for missing/invalid memory.

Output budget: `--max-output-bytes` (default 32768, bounds 1024–131072) caps
the encoded JSON. When exceeded, entries are dropped deterministically from the
end of the last proof that still has entries (then whole proofs), each drop is
counted in `omitted_entries` / `omitted_proofs`, `output_truncated` becomes
true, the affected proof becomes `incomplete`, and `support_replay_complete`
is false. A truncated subset is never reported as complete. `--max-evidence`
bounds entries per proof the same way.

Digests: `inputs_sha256` binds memory, the continuity dependency digest and
every proof revision; it does **not** change when a supporting file changes,
so it is not a cache key (`cache_reusable` is always false). `observed_sha256`
binds the replayed statuses and actual hashes and does change. Rerun the audit
on every session start or resume.

Interpretation limits: hash equality certifies bytes, not a quote, region,
conclusion or reviewer authority. A `stale` entry means the declared live path no
longer holds those historical bytes; it does not by itself reopen the proof, and
an archived revision may be supplied explicitly for historical replay. No
`evidence` array means coverage was not declared, not that it was verified.
`applicable=true` from continuity remains applicability, never approval.
