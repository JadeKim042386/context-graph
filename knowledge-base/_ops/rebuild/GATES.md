# Gates: KE-KNOWLEDGE-REBUILD-002 external sources

OWNS: knowledge-base/_ops/rebuild/external-source-*, knowledge-base/_ops/rebuild/fetched-cache/**, knowledge-base/_ops/rebuild/GATES.md, knowledge-base/_ops/rebuild/test_external_sources.py

Scope: make every external URL and media reference traceable without inferring unavailable content or rights

- [ ] G1: external source parser and safety contracts pass
  CHECK: pytest -q knowledge-base/_ops/rebuild/test_external_sources.py
  EXPECT: passed
  EVIDENCE: pending

- [ ] G2: generated manifest, cache hashes, overlay graph, and conclusions are internally consistent
  CHECK: python knowledge-base/_ops/rebuild/external_sources.py --verify-only
  EXPECT: EXTERNAL_SOURCE_VERIFICATION_OK
  EVIDENCE: pending

- [ ] G3: changed tracked files have no whitespace errors
  CHECK: git diff --check
  EXPECT: GIT_DIFF_CHECK_OK
  EVIDENCE: pending
