# Task reuse planner

> 사용자에게 표시하는 용어: **작업 완료·검토 참조 기록** (Task Completion
> and Review Record). 내부 호환성을 위해 schema의 `TaskReuseReceipt` 이름은
> 당분간 유지한다.

`scripts/plan_task_reuse.py` is an opt-in, read-only decision layer for
preventing duplicate session work. It does not replace continuity packs,
session handoffs, canonical review, or promotion.

## Decision contract

1. `task_fingerprint` identifies the project, question, scope, date, and
   acceptance-contract version. Session and agent IDs are intentionally not
   part of it.
2. `evidence_fingerprint` identifies the selected artifact hashes and
   locators, plus rights, review, and policy revisions.
3. A trusted harness must authorize the continuity lookup. Missing or stale
   authority returns `abstain` without exposing candidate counts.
4. `reuse` requires an accepted receipt, a replayable review, current artifact
   hashes, current locators, and matching fingerprints. `skip` additionally
   requires the request's explicit `allow_skip=true`.
5. Changed evidence is `refresh`; changed task identity is `branch`; an
   unverifiable or conflicting receipt is `hold`.

The internal reference-record journal is
`knowledge-base/_ops/work-reuse-receipts.jsonl`. It is read only by the
planner. Writing a reference record remains a separate reviewed operation and
is not implemented by the lookup command.

## CLI

```bash
python -B scripts/plan_task_reuse.py \
  --root PROJECT \
  --request REQUEST.json \
  --harness-manifest .context-graph/harness.json
```

The output is deterministic JSON. A successful lookup can still return
`hold`; exit status only distinguishes a valid authorized lookup from a
binding, request, or harness failure.

This planner does not prove that the final work product is better. It only
decides whether an earlier accepted result is safe to reuse. Final-result
quality requires a separate paired A/B evaluation with sealed gold answers,
allowed locators, correctness, faithfulness, completeness, citation, and
abstention metrics.

Run the deterministic quality evaluation with:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B \
  tests/benchmark_task_reuse_quality.py --repetitions 30
```

This compares final structured results, not planner decisions. The current
local fixture is a safety and regression benchmark; it does not represent
LLM-generated production quality.

## Safety and measurement

The planner fails closed on missing permissions, stale review/artifact hashes,
unknown locators, conflicting receipts, and incomplete completion evidence.
Performance must report lookup latency separately from avoided task execution.
The repository benchmark is synthetic and local; it is not an operational
host-quality claim.
