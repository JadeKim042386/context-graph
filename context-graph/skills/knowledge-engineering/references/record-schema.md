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

The default state flow is `proposed → verified → accepted`. Do not automatically include `deprecated`, `retracted`, or `unknown` records in answers.

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
