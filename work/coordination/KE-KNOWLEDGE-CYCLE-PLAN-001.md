# Knowledge Engineering Improvement Cycles Implementation Plan

> **For agentic workers:** Execute this plan inline in the existing Sol workspace. Do not dispatch another agent or use Computer Use.

**Goal:** Run the already collected local knowledge-engineering material through `material build → KB design → design-based rebuild → validation and measurement → defect feedback` at least twice, producing verifiable improvements and an explicit stopping decision.

**Architecture:** Use a frozen inventory snapshot and local-v2 artifacts as the baseline. Each cycle measures input defects, updates a bounded design rule, regenerates projections with a deterministic local builder, and performs a paired comparison with the same metrics. HTML is an L5 projection rather than the canonical source, and evaluator-only gold is isolated from public projections.

**Tech Stack:** Python 3, JSON/JSONL, HTML5 parser, pytest, jq, git diff validation.

**Spec:** `design/knowledge-base-context-efficiency-design.html`, `knowledge/knowledge-base-architecture-design.html`, `AGENTS.md`

## Global constraints

- Local Cycles 1–3 do not perform external network fetches. External Cycle 1 collects only public-URL HEAD metadata under explicit user approval.
- Do not delete, overwrite, or restore existing originals, legacy L3/L4, or `graphify-out`.
- Use inventory snapshot `66dee5187dca93f9069f3388f8374ed88fece66f4a3094f1ca47f005b8ad90af` for paired comparisons.
- Do not promote source assertions to facts without independent verification.
- Do not merge conflicts into a scalar score; preserve source/evidence locators and the abstention rationale.
- Do not allow evaluator-only gold into retrieval or public projection content.
- Do not publish, deploy, commit, or push.

## Baseline

| Metric | Current value | Evidence/status |
|---|---:|---|
| Frozen source coverage | 22/22 (100%) | `source-manifest.json`, `local-evidence.json#/source_coverage` |
| Local evidence | 3,389 | projected 3,379; evaluator-only 10 |
| Evidence field integrity | 3,389/3,389 | source ID, locator, provenance, and content SHA exist; source SHA and inventory snapshot are validated as separate fields |
| Typed graph | nodes 3,411 / edges 3,389 | Source 22 + Evidence 3,389; one `has_evidence` edge per evidence |
| Typed conclusions | 22 | observed 18; binary extraction abstain 4 |
| Semantic conflict audit | 1 | `semantic_claims=[]`, `not_inferred`, `abstain` |
| Design requirements | 9/9 passed | `local-rebuild-audit.json` |
| Gold isolation | 10/10 sealed | `visibility=evaluator-only`, `content=null`, `status=sealed` |
| Regression tests | 5 passed | `pytest -q knowledge-base/_ops/rebuild/test_local_knowledge_rebuild.py` |
| Append-only provenance | passed | Existing events preserved; two builder reruns append unique events |
| External content | URL 1,203 / media 17 / fetched 0 | Unverified and out of scope; not fetched in this cycle |
| HTML locator selector semantics | Not measured | Cycle 1 tests whether global `nth-of-type` represents a reproducible locator |
| Embedded projection JSON parseability | Not measured | Cycle 1 independently parses the HTML script payload |
| Public projection gold-locator exposure | Not measured | Cycle 2 measures `/evaluator_sidecar` exposure |

## Stop conditions

Run a minimum of 2 and a maximum of 3 cycles. After Cycle 2, stop when all hard gates pass, one complete improvement pass finds zero new high-severity local defects, and improvement over the prior cycle is zero or minor.

Improvement is minor only when all of the following hold.

- coverage improvement is below 0.1 percentage points.
- fewer than 1 newly resolved, verifiable local defect exists.
- source/evidence/graph/conclusion counts and reference integrity do not regress.

Hard gate:

1. All 9/9 design requirements are `passed`.
2. Source coverage is 22/22 and all 3,389 evidence records have valid source ID, locator, provenance, and content SHA.
3. The graph contains Source 22 + Evidence 3,389 and 3,389 `has_evidence` edges.
4. Conclusions cover source 22/22 and every evidence reference resolves in the graph.
5. All 10 evaluator-only records are sealed and public HTML exposes 0 gold pointers.
6. Conflict audit preserves source/evidence locators and abstain reasons without guessing claim meaning.
7. All rebuild JSON/JSONL and both HTML files parse and point to the same snapshot.
8. Targeted pytest and `git diff --check` pass.
9. Existing originals, legacy L3/L4, and `graphify-out` are preserved.

If hard gates are not satisfied by Cycle 3 or the same blocker remains, stop as `status=partial` rather than looping indefinitely, and hand off the reproducible blocker and next role.

## Cycle 1 — locator and projection machine-readability

**Input defect hypothesis:** Representing an HTML locator's global ordinal like CSS `nth-of-type` can change selector meaning, and the L5 summary script's JSON may not be machine-readable.

**Files:**

- Modify: `knowledge-base/_ops/rebuild/local_rebuild.py`
- Modify: `knowledge-base/_ops/rebuild/test_local_knowledge_rebuild.py`
- Regenerate: local-v2 JSON/HTML and append-only log artifacts

Execution:

1. Measure the current locator model and embedded JSON parseability and record them as cycle input.
2. Make the locator explicit with a document-global tag ordinal plus line/text quote or a Web Annotation-compatible selector.
3. Generate the projection summary so an independent JSON parser can read it.
4. After rebuild, perform a paired comparison of source/evidence/graph/conclusion coverage and snapshot.
5. Record remaining defects as Cycle 2 input.

Acceptance: locator model coverage 100%, embedded summary JSON parse 1/1, and no regression in baseline count/reference metrics.

## Cycle 2 — gold isolation and feedback closure

**Input defect hypothesis:** Even when evaluator-only content is null, exposing an `/evaluator_sidecar` locator in public L5 HTML makes gold isolation incomplete.

**Files:**

- Modify: `knowledge-base/_ops/rebuild/local_rebuild.py`
- Modify: `knowledge-base/_ops/rebuild/test_local_knowledge_rebuild.py`
- Regenerate: local-v2 JSON/HTML, audit and append-only log artifacts
- Create/update: `knowledge-base/_ops/rebuild/knowledge-cycle-report.html`

Execution:

1. Measure public projection gold-pointer exposure from Cycle 1.
2. Keep only stable ID and sealed status for evaluator-only articles; exclude content, locator, and content hash from public HTML.
3. Preserve provenance and visibility in restricted evidence JSON and the typed graph.
4. Rerun all hard gates and calculate the delta from Cycle 1.
5. Decide whether to stop or enter Cycle 3 from improvement and new-defect counts.

Acceptance: evaluator-only 10/10 sealed, public HTML gold-pointer exposure 0, and no regression in existing coverage/reference metrics.

## Cycle 3 — integrated validation and stopping decision

One additional cycle ran because Cycle 2 produced a meaningful improvement. RED confirmed the missing cumulative HTML report and project-scoped validator; five scopes—integrity, locator, gold, report, and diff—and the pytest gate were implemented. No new knowledge or external material was added; stop when core source/evidence/graph/conclusion improvement is 0 and all hard gates pass.

## External Cycle 1 — bounded availability verification

After user approval, URL HEAD metadata was processed in batches of 20. Including the final bounded retry, 775 unique URLs were observed across 40 URL batches/780 attempts: HTTP metadata was confirmed for 693, while 64 HTTP errors and 18 DNS/timeout/connection failures were preserved as unknown/abstain. 428 URLs are not started. All 17 media records were metadata_fetched in one separate batch. No body download occurred, so content hashes are 0; only 4 records with explicit HTTP-header evidence have verified rights. The final deterministic retry newly confirmed 5 of 10 records; the 5 existing HTTP errors all remained 403. Crawling stopped after the approved final retry and the partial external result was projected.

## Cycle summary

| Stage | Input | Change | Core metrics | Result | Next decision |
|---|---|---|---|---|---|
| Baseline | frozen local snapshot | none | source 22, evidence 3,389, graph 3,411/3,389, conclusions 22, gates 9/9, tests 5 passed | baseline confirmed | run Cycle 1 |
| Cycle 1 | locator model 0/3,196; embedded JSON 0/1 | document-global ordinal + TextQuoteSelector; raw JSON script generation | locator 3,196/3,196; JSON 1/1; no source/evidence/graph/conclusion regression; 7 tests passed | two defects resolved | use 10 public gold-pointer exposures as Cycle 2 input |
| Cycle 2 | 10 public gold-pointer exposures | exclude evaluator-only locator/content from public HTML; preserve restricted JSON/graph | exposure 10→0; sealed 10/10; no coverage regression; 8 tests passed | one meaningful defect class resolved | run one additional Cycle 3 as planned |
| Cycle 3 | integrated validator 0/5; cumulative report 0/1 | integrity/locator/gold/report/diff validators and machine-readable HTML cycle report | validator 5/5; validation gates 6/6; report 1/1; core coverage delta 0 | validation/reporting defects resolved; core improvement 0 | stop with hard gates satisfied and core improvement 0 |
| External Cycle 1 | URL 1,203/media 17 all unverified by fetch | URL 39×bounded HEAD batch + final retry 1 batch, media 1 batch, result locators and typed external projection | URL metadata 693, HTTP error 64, network failure 18, not_started 428; media metadata 17; rights evidence 4; body hash 0 | promoted 710 accessible metadata records; final retry +5 | stop after final bounded retry; hand off errors/unprocessed records as abstain |

## Final verification commands

```text
python knowledge-base/_ops/rebuild/local_rebuild.py
pytest -q knowledge-base/_ops/rebuild/test_local_knowledge_rebuild.py
jq -e . knowledge-base/_ops/rebuild/*.json
jq -e . knowledge-base/_ops/rebuild/build-log.jsonl
git diff --check
```

Parse the existing projection, local-v2 projection, and cycle report with Python `html.parser`; validate the cycle report's embedded JSON separately with `json.loads`.
