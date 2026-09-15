# Canonical Record Contract

Canonical records are JSON originals reviewed and modified by people. Keep one record per file and preserve these common fields: `schema_version`, `id`, `record_type`, `revision`, `status`, `created_at`, `updated_at`, and `provenance`.

- `Concept`: a term and its definition
- `Claim`: a reviewable assertion; it cannot be accepted without `evidence_ids`
- `Source`: original identity, canonical URL/path, access date, revision, hash, and rights state
- `Evidence`: a reproducible selector, page, row, bbox, timecode, and quote inside a Source
- `Media`: location, format, time, hash, rights, and derivative relationships for image, video, or audio
- `Review`: the target revision, finding, issue, and proposal
- `Decision`: the accepted, held, or rejected decision and its rationale
- `Question`: a standard question, scope, reference date, and answer state

The default state flow is `proposed → verified → accepted`. Do not automatically include `deprecated`, `retracted`, or `unknown` records in answers.
