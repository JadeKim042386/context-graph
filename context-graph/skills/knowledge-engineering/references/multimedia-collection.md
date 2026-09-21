# Multimedia Collection Contract

Use this contract when collecting knowledge related or adjacent to the current
project. Broad discovery is allowed; unsupported promotion is not.

## Collection plan contract

Before discovery or acquisition, write a plan with these scope axes:

- question and intended decisions, including what is out of scope;
- core topic versus adjacent research and the relationship that makes it useful;
- source types and media kinds to cover;
- date range, freshness, language, geography, and audience constraints;
- required evidence strength and source independence;
- allowed access and rights states;
- search, time, network, storage, item-count, and review budgets;
- coverage targets, quality metrics, stop rules, and final states.

Represent the axes as a coverage matrix. Each required cell states its target
count or `not_applicable`, current count, gap, and evidence status. A
strategy-only request ends with this plan: it does not authorize network access,
downloads, OCR, transcription, canonical records, or promotion.

## Machine-readable plan and checkpoint

Write the plan and every execution checkpoint against
[`../schemas/collection-strategy.schema.json`](../schemas/collection-strategy.schema.json).
Use [`collection-strategy.example.json`](collection-strategy.example.json) as the
strategy-only example. The artifact has these mechanically testable parts:

- `inputs`: scoped question, excluded scope, coverage axes, source tiers, query
  families, allowed access/rights states, fixed budgets, and stop rules;
- `outputs`: pointers for the plan, candidate catalog, checkpoint, metrics, and
  report; a strategy-only plan leaves acquisition outputs `null`;
- `authorized_stages`: the exact stages the current request permits; in
  `strategy_only` mode this is exactly `["plan"]`;
- `batches`: append-only batch results with input count, per-dimension material
  gain, errors, and a checkpoint digest;
- `checkpoint`: last completed batch, next stage, query cursor, remaining query
  families, candidate snapshot hash, and unresolved blockers;
- `decision`: `continue`, `completed`, `partial`, or `blocked`, with reason and
  whether resume is required;
- `metrics`: fixed denominators and separate counts; compute ratios from these
  values rather than storing a blended score;
- `validation`: named pass/fail/unverified checks and their evidence.

Create a new `revision` when plan inputs, budgets, authorization, denominators,
or stop rules change. Append a batch instead of rewriting prior batch evidence.
The current checkpoint may advance, but its digest and referenced candidate
snapshot must make the prior boundary replayable. Resume only from
`checkpoint.resume_stage`; do not infer authorization from an earlier run.

Validate plans and execution checkpoints with the dependency-free command:

```bash
python context-graph/skills/knowledge-engineering/scripts/validate_collection_strategy.py <artifact.json>
```

For an execution example with no network or source content, read
[`collection-strategy.execution.example.json`](collection-strategy.execution.example.json).
Each batch embeds its resulting checkpoint. `checkpoint_digest` is the SHA-256
of that checkpoint encoded as UTF-8 canonical JSON with sorted keys and compact
separators. The top-level checkpoint must equal the last batch checkpoint.

A batch has no material gain only when all configured `material_gain_fields`
are zero. Once trailing non-improving batches reach `saturation_batches`, the
decision cannot be `continue`: use `completed` only when required coverage is
met without unresolved work, `partial` when unresolved work has a valid resume
checkpoint, or `blocked` for a safety/access halt. Never average the gain fields
into one score.

Collection artifacts are host-neutral JSON. Store every output pointer as a
project-root-relative POSIX path. Reject absolute paths, Windows drive paths,
backslashes, `~`, environment-variable placeholders, URI schemes, and `..`
traversal. Do not assume `AGENTS.md`, `CLAUDE.md`, a home directory, or a
runtime-specific environment variable exists. JSON key order, indentation, and
ASCII escaping do not change meaning; canonical digests use UTF-8, sorted keys,
and compact separators.

## Source priority

Search in this order unless the plan gives an evidence-based exception:

1. official and primary standards, specifications, registries, APIs, releases,
   government data, original papers, datasets, and maintained repositories;
2. publisher, author, institution, or project pages that identify the original;
3. reputable reviews and secondary syntheses for vocabulary and citation leads;
4. aggregators, mirrors, social posts, and search snippets for discovery only.

Prefer a fixed release, DOI, accession, commit, or versioned download over a
mutable landing page. A mirror or derivative may improve access but is not an
independent source. Record the reason whenever a lower-priority source is used.

## Query expansion

Create query families from the scoped question rather than one broad query:

- names, synonyms, acronyms, translations, former names, and stable identifiers;
- entities plus relationships, methods, claims, failures, conflicts, and dates;
- standards, papers, datasets, repositories, benchmarks, rights, and errata;
- media terms such as lecture, talk, podcast, transcript, diagram, image, audio,
  table, appendix, supplementary material, and raw data;
- official-domain and file-type filters where they reduce ambiguity.

Keep a query log with the normalized query, source/catalog, time, result rank,
candidate ID, discovery reason, and parent query or citation. Follow citations,
references, and related-item links at most one or two hops. Query expansion is
discovery metadata and never evidence for a content claim.

## Staged execution

Each stage has a checkpoint and may be authorized separately.

1. **Plan:** freeze scope axes, coverage matrix, budgets, allowed rights, metrics,
   and stop rules.
2. **Discover:** collect candidate metadata and query-log entries without treating
   snippets or search scores as evidence.
3. **Verify identity and rights:** resolve canonical identity, source revision,
   access state, rights URL/locator, and expected acquisition size.
4. **Acquire:** fetch only authorized public resources with fixed timeout, byte,
   redirect, retry, and concurrency limits. Respect robots, authentication,
   paywalls, and rate limits. Store raw bytes outside canonical records and
   compute SHA-256.
5. **Extract and normalize:** create separate Source, Media, Evidence, and
   ProvenanceActivity proposals; record extractor and version.
6. **Deduplicate and review:** group exact hashes, mirrors, derivatives, and
   near-duplicates; replay locators; assess conflicts, freshness, and source
   independence; keep unsupported items on hold or abstain.
7. **Project and measure:** after approval, rebuild projections from the approved
   snapshot and compare final metrics with the frozen plan.

Do not infer authorization for a later stage from approval of an earlier one.

## Per-format handling

| Format | Identity and acquisition | Evidence locator and derivative rule |
|---|---|---|
| HTML/text | Canonical URL, final URL, access time, revision headers or page version, raw hash | Selector plus exact quote or text position; rendered/extracted text points back to the raw page |
| Paper/PDF | DOI/accession, publisher record, file URL, edition/version, file hash and page count | Page, region, and quote; OCR records tool/version and remains `derived_from` |
| Image/SVG | Asset URL or repository ID, file hash, dimensions, creator and rights scope | Bounding region or SVG selector; OCR/caption/thumbnail is a derivative |
| Video | Stable video ID, publisher, release date, stream/file revision, duration and rights | Start/end timecodes; transcript, subtitles, frames, and clips are derivatives |
| Audio | Stable episode/recording ID, publisher, release date, stream/file revision, duration and rights | Start/end timecodes; transcript, waveform, and excerpt are derivatives |
| Dataset/table | DOI/accession/release, query or immutable slice, schema and file hash | Query, table/sheet, row, column, field, and version; exports point to the source slice |
| JSON/XML/RDF | Endpoint or file revision, content hash, media type and schema/version | JSON Pointer, XPath, IRI, named graph, or triple selector |
| Code/archive | Repository/release, full commit and blob, archive hash and rights | Commit, path, line/byte range, symbol when available, and replay command |

## Locator rules

- HTML/text: selector plus quote or text position.
- PDF: file hash, page, region, and quote; record OCR tool/version if used.
- Image: file hash, bounding region or SVG selector, and caption/OCR provenance.
- Video/audio: immutable file or stream revision and start/end timecodes.
- Dataset/table: release/version and query, slice, sheet, row, and column.
- JSON/XML/RDF: content hash with JSON Pointer, XPath, IRI, or triple selector.
- Code/archive: commit, blob, path, line/byte range, and replay command.

## Search and stop rules

Use query families for standards, methods, evaluation, media, implementation,
and failure analysis across each coverage axis: core standards/data models,
provenance/quality, retrieval/context efficiency, ontology/KG/CQ validation,
code knowledge, multimodal extraction, operations/rights, and benchmarks.
Stop a query family after two consecutive batches produce no new verified
identity, rights evidence, replayable locator, independent evidence, or required
coverage. Stop the cycle as `completed` when required coverage and quality gates
are met and two consecutive batches show no material improvement. Stop as
`partial` when budgets expire after a valid checkpoint. Stop as `blocked` when
robots, authorization, paywalls, rate limits, unsafe redirects, or repeated
network failures prevent the required evidence. A stopped cycle retains its
query log, candidate states, metrics, errors, and resume condition.

## Coverage and quality metrics

Freeze each denominator in the plan and report counts and ratios separately:

- coverage by scope axis, media kind, source type, and required matrix cell;
- canonical identity, fixed revision, body hash, and provenance completeness;
- access-state distribution and rights coverage by permitted use;
- body verification and format-specific locator replay rates;
- exact duplicates, near-duplicate clusters, derivative groups, and source
  independence;
- new accepted evidence per batch, conflict/stale/abstain counts, failures,
  bytes, requests, elapsed time, and review effort.

Do not combine metadata, body, rights, locator, review, or acceptance into one
score. Do not count a derivative, mirror, or repeated host as corroboration.

## Validation checklist

Before reporting or promotion, verify:

1. the plan fixes scope axes, budgets, metrics, and termination rules;
2. every candidate has discovery provenance and normalized canonical identity;
3. acquired bytes match recorded length and SHA-256 and remain outside canonical
   records;
4. access and rights statuses cite their own evidence and permitted-use scope;
5. each Evidence proposal replays its format-specific locator against the fixed
   source revision;
6. derivative, mirror, exact-hash, near-duplicate, and source-family links prevent
   false source independence;
7. coverage metrics reconcile with the candidate catalog and review decisions;
8. safety stops and failures remain explicit, and the final state is exactly
   `completed`, `partial`, or `blocked` with a resume condition;
9. no metadata-only record supports a content claim and no proposed record is
   automatically promoted;
10. focused tests, the workspace validator, and `git diff --check` pass or are
    reported as failed/unverified.

## Promotion gates

A content claim requires body verification, explicit rights state, content hash,
replayable locator, provenance, and a review decision. Metadata-only records may
remain in a catalog but cannot support claims. OCR, transcripts, captions,
frames, thumbnails, translations, and summaries retain `derived_from` and do
not count as independent corroboration. Never store credentials, private data,
raw prompts, or raw session transcripts.
