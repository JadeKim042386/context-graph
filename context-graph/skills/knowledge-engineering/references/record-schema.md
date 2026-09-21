# Canonical Record Contract

Canonical records are JSON originals reviewed and modified by people. Keep one record per file and preserve these common fields: `schema_version`, `id`, `record_type`, `revision`, `status`, `created_at`, `updated_at`, and `provenance`.

- `Concept`: a term and its definition
- `Claim`: a reviewable assertion; it cannot be accepted without `evidence_ids`
- `Source`: original identity, canonical URL/path, access date, revision, hash, and rights state
- `Evidence`: a reproducible selector, page, row, bbox, timecode, and quote inside a Source
- `Media`: immutable source location, media kind, source revision, access state, content hash, rights state, technical metadata, replayable locators, deduplication state, provenance, and derivative relationships for image, video, audio, PDF, dataset, HTML, text, or structured media
- `Review`: the target revision, finding, issue, and proposal
- `Decision`: the accepted, held, or rejected decision and its rationale
- `Question`: a standard question, scope, reference date, and answer state
- `Ontology`: the identity, scope, namespace, version, owner, license, and reuse decision for a controlled conceptual model
- `Class`: a formally named category with definition, parent classes, and competency-question coverage
- `Property`: a formally named relationship or data field with domain, range, cardinality, and inverse/chain notes
- `Individual`: a named instance linked to classes and claims; keep instance facts separate from class definitions
- `Shape`: a validation contract for required properties, datatypes, cardinality, and allowed values
- `CompetencyQuestion`: a testable natural-language requirement with expected query shape and validation status
- `Mapping`: a source-term to ontology-term alignment with method, confidence, evidence, and reviewer
- `Axiom`: a logical rule or restriction that may be checked by a selected OWL profile or reasoner
- `Module`: a bounded, cohesive ontology slice with its dependencies and extraction rationale
- `EvaluationRun`: a reproducible ontology or retrieval evaluation with fixed inputs, metrics, and results
- `Code Source`: a repository snapshot with `repository_id`, full `commit_sha`, `tree_sha`, observed branch/ref, capture time, and access/rights state
- `Code Evidence`: a Git-pinned selector with `source_id`, `commit_sha`, `blob_sha`, `path_at_commit`, line or byte range, content hash, and reproducible locator command
- `TestRun Evidence`: an executed command and selected tests tied to a commit, environment/toolchain digest, exit code, immutable report path/hash, and time range

The default state flow is `proposed → verified → accepted`. Do not automatically include `deprecated`, `retracted`, or `unknown` records in answers.

## Media record minimums

Media records must keep these three state axes separate:

- `access_status`: `not_started`, `metadata_fetched`, `body_verified`,
  `failed`, `rate_limited`, `robots_disallowed`, `access_restricted`, or
  `unavailable`;
- `rights.status`: `rights_verified`, `restricted`, `unverified`, or `unknown`;
- `review_status`: `proposed`, `verified`, `accepted`, `held`, `rejected`,
  `superseded`, `stale`, or `abstain`.

HTTP success does not imply body or rights verification. A Media record should
include `canonical_url`, `final_url`, `source_revision`, `accessed_at`,
`content_sha256`, `byte_length`, `mime_type`, technical dimensions/duration or
page count when applicable, rights evidence and scope, acquisition activity and
tool version, format-specific locators, derivative links, and exact/near-duplicate
review state. A derivative must retain `derived_from`, extractor/version, hash,
and the source locator; it must not be counted as an independent source.

For code, a branch is mutable context and never an immutable revision. An issue establishes a requirement or report; it does not prove implementation correctness. A passing test supports only the behavior, inputs, environment, and commit it actually exercised.

## Ontology record minimums

Ontology records extend the same common fields and remain evidence-linked. A
minimum accepted model is:

```json
{
  "schema_version": 2,
  "id": "ONT-example-v1",
  "record_type": "Ontology",
  "revision": 1,
  "status": "proposed",
  "namespace": "https://example.org/ontology/",
  "version_iri": "https://example.org/ontology/1.0.0",
  "scope": "one sentence describing the domain boundary",
  "competency_question_ids": ["CQ-example-001"],
  "reuse_assessment": {"candidates": [], "decision": "unverified"},
  "provenance": {"activity_id": "ACT-example", "agent": "knowledge-engineer"},
  "created_at": "2026-09-16T00:00:00Z",
  "updated_at": "2026-09-16T00:00:00Z"
}
```

`Class` and `Property` records must include a stable IRI, human-readable
definition, scope, and their domain/range or parent links. `Shape` records
must name the target class and constraints. `CompetencyQuestion` records must
include a normalized question, scope, expected answer form, and pass/fail
result. `Mapping` records must retain the original source term, target IRI,
mapping relation, confidence, evidence IDs, and reviewer state. These are
design contracts; they do not promote a proposed ontology to accepted status.
`EvaluationRun` records must also declare the ontology revision, reasoning
profile (`OWL 2 EL`, `OWL 2 QL`, `OWL 2 RL`, or `unverified`), fixed snapshot,
question set, metric definitions, and limitations. An `unverified` profile is
valid only as a pending state; it cannot support a reasoning-performance claim.
