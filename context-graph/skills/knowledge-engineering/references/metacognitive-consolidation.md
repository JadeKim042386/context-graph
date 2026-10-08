# Provisional consolidation and review boundaries

Session overlays are operational records, not accepted canonical knowledge. Raw sources, memory and canonical records are never promoted or deleted by consolidation.

Unattributed events never inherit an agent role. New state records store hashed legacy/v3 session aliases derived from the supplied raw session; old states are not rewritten and unknown aliases cannot be recovered by guessing. Attributed events match agent, task and assignment. Role labels remain caller attribution, not authorization.

Overlay/registry readers and writers are bounded at 5,000 records and 16 MiB, with 64 KiB per JSONL record. An over-limit merge refuses the whole batch with overlay_full and requests review_archive_policy. Rotation is explicit and never runs automatically in a hook; there is no deletion or silent truncation. Raw event capture is separate and may have recorded its event before overlay refusal. Symlinked operational paths fail closed. Writes use temporary files and atomic replacement; merge and consolidation use separate locks. Unchanged output bytes are not rewritten; input scans still occur.

plan creates a regenerable proposal file. compact creates a regenerable projection. Matching fingerprints are candidate similarity only. Different fingerprints on one scoped artifact create a candidate conflict; semantic equivalence remains unverified. Missing, stale, unsupported or unlocatable dependencies are held, never silently selected. Locator replay supports bounded text/HTML and optional local binary parsers as specified below. Unknown formats or missing parsers remain unsupported. Explicit source event hashes, event/overlay identity, artifact hashes, locator range/optional quote and accepted Source/Media rights metadata are checked before eligibility. Native v3 pointers may lack locator/rights information and therefore remain held.

An in-process trusted harness context is required for eligible representatives. With a supplied context, denied dependencies are filtered before proposals and only an omitted count is exposed. Without context, the CLI is a project-maintenance metadata view: it creates proposals/held operational records, never an authorized representative view. It is not an OS filesystem isolation boundary. Existing scope policy/subject authenticity remains the launcher's responsibility.

Duplicates are suppressed only after a bound explicit reviewed decision and successful evidence checks. record_decision(root, proposal_id, outcome, review_pointer, review_sha256), or the decide CLI, requires an accepted Decision binding the exact base proposal digest and an exact pointer/hash allowlist in knowledge-base/_ops/consolidation-review-policy.json under approved_review_refs. This policy is curator-controlled; no default policy is generated. It does not authorize canonical promotion. Durable operational decisions live outside regenerated proposals in consolidation-decisions.jsonl. Identical retries are no-ops; opposing outcomes remain conflict; changed inputs or approval hashes invalidate use. Canonical approval and integration remain separate.

```sh
python -B context-graph/skills/knowledge-engineering/scripts/consolidate_knowledge.py --root . plan
python -B context-graph/skills/knowledge-engineering/scripts/consolidate_knowledge.py --root . compact
python -B context-graph/skills/knowledge-engineering/scripts/consolidate_knowledge.py --root . decide --proposal-id SCP-ID --outcome hold --review-pointer review.json --review-sha256 HASH
```

These commands write operational outputs; do not run them on a real project for read-only checks. No production CLI harness-consumption integration is claimed. Projection held_items and excluded_provenance retain operational membership; raw split remains authoritative. source_preserved reports replay coverage, not merely unchanged input bytes. conflicts_retained describes the candidate scan, not a proof of semantic conflict completeness.

Lifecycle overlay failures retain bounded status diagnostics, never exception payloads, and keep lifecycle exit 0. The hook CLI emits nothing when all steps succeed. Failures emit one host-compatible JSON object with continue=true and a sanitized systemMessage; direct Python API diagnostics remain JSONL. The status file preserves a bounded recent_steps list (four steps) plus last status and failure count. Multiple top-level JSON objects are never sent as hook stdout. A bounded status file records the last step and cumulative failure count. A failure writing that status produces a visible status_write_failed line. Session start/close receive raw session identity only long enough to derive aliases. Pre/post compact remain proposal-only; session close requests full compact.

Tests validate emitted overlay, agent, proposal, decision, status and projection records against schemas. No new runtime jsonschema dependency is added. Real-host gold, OS cold-cache measurements and installed-root parity require separate evidence. This checkout is not installed or released by these repairs.

## Explicit archive rotation

`session_knowledge.py --root PROJECT rotate` archives closed sessions only. Every latest agent state for the session must be closed; a missing close or any open agent prevents rotation. No event, source or canonical file moves. Segments under `_ops/session-knowledge-archive/` are content-addressed JSONL, never overwritten. The bounded `head.json` preserves prepared/committed entries, segment digest/count, pre/post active-overlay digest and timestamp. Publication order is segment → prepared head → active overlay → committed head. Retries verify existing bytes. A prepared transaction is completed only against the exact before/after digest; any other base fails closed. Unreferenced orphan bytes are retained, never deleted; an identical orphan can be reused. This is process-crash recovery, not a power-loss durability certification.

`split --include-archive` restores archived membership with `source_store=archive`, `original_source_store`, and `archive_segment_id`. `plan/compact --include-archive` retains the original evidence store and adds archive_segment_id so source replay stays bound. Default reads remain active-only. Merge deduplicates against active plus archived IDs, preventing reappend. Limits: 64 segments, 5,000 rows/16 MiB each; total replay 50,000 archived rows/64 MiB, plus bounded active overlay. Reaching limits fails closed; no unlimited retention claim. Registry and source-journal caps remain separate.

## Locator contract

Artifact bytes (maximum 256 KiB), exact source revision and accepted rights proof are checked before locator eligibility. `evidence-locator.schema.json` describes syntax; runtime replay checks content and bounds. Native capture pointers are not silently enriched. Supported strings:

| Locator | Replay | Limit |
|---|---|---|
| `line:N[-M]` | UTF-8 line range and optional quote | quote within selected lines |
| `html:#id` | unique id or named anchor and element text | malformed nesting/duplicate id fails; no arbitrary CSS selector |
| `pdf:page=N[;bbox=x0,y0,x1,y1]` | optional pypdf; page and bbox bounds; page text quote | bbox plus quote is unsupported because glyph containment is not guaranteed |
| `table:sheet=S;cell=A1[:B4]` | optional openpyxl; existing XLSX sheet/range and cell quote; `sheet=CSV` also supports UTF-8 CSV cells | 10,000 cells, 16 MiB uncompressed; formulas unsupported; no external links/evaluation |
| `image:bbox=x0,y0,x1,y1` | optional Pillow; region bounds and image integrity | 20 million pixels; no OCR; any quote unsupported |
| `av:t=HH:MM:SS[.sss]-HH:MM:SS[.sss]` | optional ffprobe; finite duration and time range | local WAV/FLAC/MP3/MOV/MP4 only; no network protocols; quotes/transcripts unsupported |

A valid geometry/time range proves a location, not semantic correctness. Derivative transcripts/OCR require their own hash-bound source and locator; this adapter never invents them. Bodies above 256 KiB: oversize (held); missing parser: unsupported; malformed syntax: unverified; invalid content/range: unlocatable. Binary parsers run in a four-second subprocess budget (CPU limit three seconds; ffprobe two seconds); no downloads or parser installation. An over-budget parser is unlocatable. Hook steps retain exit 0 and report failure; many parser-backed representatives are not guaranteed to fit a lifecycle timeout. No-harness hooks do not parse knowledge bodies.

The hook payload can explicitly provide all four `agent_instance_id`, `task_id`, `assignment_id`, `role` fields (bounded opaque identifiers). They are hashed into registry state and never treated as authorization. Partial/invalid declarations fail the overlay step visibly with invalid_attribution. Archive read/recovery failures also retain their bounded reason codes. Events without explicit attribution always keep role=None, even with a single agent.

## Evaluation isolation and cache conditions

`tests/benchmark_metacognitive.py --repetitions 30 --output /tmp/result.json` runs entirely in temporary projects. Sealed `tests/fixtures/sealed_metacognitive/gold.json` is opened only after projection bytes and digest are frozen. An audit hook rejects runtime access during retrieval. The 60-event/two-session/two-runtime-labelled fixture is synthetic local data, not real host observations. Metrics are proposal-pair precision/recall, conflict recall, held membership, zero false exclusions, and locator/provenance membership. No automatic reviewer decisions are fabricated.

The harness separates warm_in_process, fresh_interpreter, and fresh_file_proxy. The fresh-file proxy creates a new pathname but immediately writes its bytes, so OS page cache may be warm. OS-cold remains unverified; no cache purge is performed. Thirty alternating forward/reverse runs report p50/p95, byte counts, Python allocation peak and process RSS high-water with their different scopes. Timed missing-evidence fixtures exercise held output, not semantic compression. A split/plan/compact comparison is not a before/after release speedup claim. No models, tokenizer, host launch or external API is used.

## Schema digests

- schemas/session-agent-state.schema.json: `96add6fbb59746f76e8cef8e7753ca187ff8c5e8c94fd95b1e6ac9cc4deba71e`
- schemas/session-knowledge-overlay.schema.json: `5397494ebb8e31a04fba3a32d49a9b10ca18303eb32285f294d8a34e2e1c403e`
- schemas/consolidation-proposal.schema.json: `145658f61ee693080c315b85a1a89d4718f814742caf288578d0f972ecf05dd8`
- schemas/consolidated-knowledge-projection.schema.json: `72b7a9a6faa9bfa13f8662e04bd242943bb13061d112f706a8153013d715a82f`
- schemas/consolidation-decision.schema.json: `fd1b7d063d366e8fc4be8e58aaa3a33442b7878a6e3616279f70388d50e89b0e`
- schemas/session-knowledge-status.schema.json: `aa64d9f469e49f0d83cc00383b4202edfb64bfe9c73e556f958ef05c09a2f715`
- schemas/session-knowledge-archive-head.schema.json: `e954aaf79fd4d1a575a79aca2576f178fe0be7c705d62ae5b582364e97a4f8d0`
- schemas/evidence-locator.schema.json: `ff67f3dc326383b6389844bbca4745e989c2464cca8201ecc8e9f7684e84d979`
