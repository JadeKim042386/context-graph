# Project knowledge contract

This repository follows the persistent LLM Wiki / Second Brain pattern with
an evidence-first boundary: source material is preserved, knowledge is
compiled into reviewable records, and generated views remain reproducible.

## Layer ownership

- Treat raw source files and captured source revisions as immutable. Never
  rewrite them to match a summary or conclusion.
- Keep canonical records separate from generated projections. Edit canonical
  Claim, Evidence, Source, Media, Decision, and Review records; rebuild search
  indexes, graph maps, context packs, reports, and other projections.
- Preserve stable IDs and history. Represent a meaning-changing update with a
  new record plus `supersedes`, `deprecated`, or `retracted`; do not silently
  overwrite an accepted claim.
- An LLM may extract, link, summarize, and propose changes. Promotion to an
  accepted canonical record requires the configured curator or approval rule.

## Evidence and provenance

- Every conclusion must trace to Claim IDs, Evidence IDs, source revisions,
  and reproducible locators.
- Use format-specific locators: text quote/position or HTML selector, PDF page
  and region, table/sheet/row/column, image bounding region, audio/video start
  and end timecode, dataset version/query/slice, or code revision/path/line.
- Record canonical URL or stable source identifier, access date, content hash
  when available, rights/license status, and extraction method/version.
  Unknown rights or metadata must remain `unverified`; never infer them.
- Record acquisition, transformation, review, approval, and projection builds
  as provenance activities with their input revision and responsible agent.
- Do not count OCR, transcript, summary, and frame extracts from one source as
  independent corroborating sources.

## Retrieval and conclusions

- Search the index or graph before opening whole sources. Expand from direct
  matches by bounded hops and open full source material only for locator
  verification, unresolved conflict, or missing evidence.
- A retrieval prior, similarity score, cached answer, or model inference is not
  evidence. Direct evidence is required for an accepted conclusion.
- Keep conflicting claims when their scope or validity overlaps. Return the
  conflict and its decision criteria instead of averaging incompatible values.
- Mark stale dependencies and invalidate affected conclusions. When evidence
  is absent, conflicting, stale, or unlocatable, return `insufficient`,
  `conflict`, or `abstain` rather than a guessed answer.
- Reuse a cached conclusion only when its canonical question key, scope,
  as-of date, and dependency revision digest still match.

## Evaluation isolation

- Keep questions and permitted routing features separate from evaluator gold.
  Gold answers, Claim IDs, locators, oracle topics, and labels belong only in a
  sealed evaluator sidecar and must never enter retrieval or Context Packs.
- Report retrieval and generation separately. Retrieval measures include
  recall@k, rank, locator recall, candidate count, graph hops, calls, pack size,
  and latency. Generation measures include correctness, faithfulness, citation
  agreement, false answers, conflict handling, and abstention.
- Label proxy token counts, synthetic fixtures, model-judged scores, and
  non-independent gold explicitly. Do not present them as operational quality.
- Fix corpus snapshot, model, prompt, tokenizer, cache condition, and question
  order for paired comparisons; report cold and warm latency separately.

## Safe maintenance

- Inspect the working tree before editing. Preserve unrelated user changes and
  never revert, reformat, stage, commit, or delete them as collateral.
- Do not store credentials, tokens, private identifiers, personal data, raw
  customer data, or secrets in knowledge records, projections, logs, fixtures,
  reports, AGENTS.md, or memory.
- Keep durable memory short and pointer-based. Store accepted decision,
  current-goal, unresolved-item, and verified-snapshot pointers—not source
  copies, long summaries, guesses, or transient model output.
- Update `knowledge-base/_ops/memory/index.json` only after a review or
  verification event. Add or replace pointers for the current goal, accepted
  decisions, unresolved items, and verified snapshots; include the target
  artifact path, revision or snapshot hash, status, and update timestamp.
- When a project-wide rule or an accepted workflow changes, update this
  `AGENTS.md` rule and record the related decision pointer in memory. Do not
  use memory as a second copy of source content, and do not treat an
  unverified pointer as an accepted decision.
- After memory or `AGENTS.md` changes, rebuild dependent indexes and HTML
  projections, then validate JSON shape, links, and snapshot consistency.
- After changes, run the relevant parser, schema, link, projection, benchmark,
  and diff checks. Record commands, results, snapshot hash, tool versions, and
  every failed or unverified condition; never promote missing evidence to pass.
