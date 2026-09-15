# Gates: KE knowledge improvement cycles

OWNS: knowledge-base/_ops/rebuild/local_rebuild.py, knowledge-base/_ops/rebuild/test_local_knowledge_rebuild.py, knowledge-base/_ops/rebuild/validate_knowledge_cycle.py, knowledge-base/_ops/rebuild/knowledge-cycle-report.html, knowledge-base/_ops/rebuild/local-evidence.json, knowledge-base/_ops/rebuild/typed-knowledge-graph.local-v2.json, knowledge-base/_ops/rebuild/conclusions.local-v2.json, knowledge-base/_ops/rebuild/semantic-conflict-audit.json, knowledge-base/_ops/rebuild/local-rebuild-audit.json, knowledge-base/_ops/rebuild/knowledge-projection.local-v2.html, knowledge-base/_ops/rebuild/build-log.jsonl, work/coordination/KE-KNOWLEDGE-CYCLE-PLAN-001.md, work/coordination/GATES.md

Scope: execute at least two measured local knowledge improvement cycles and stop only when all hard gates pass without coverage regression

- [x] G1: source, evidence, graph, conclusion, provenance and snapshot integrity all pass
  CHECK: python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope integrity
  EXPECT: CYCLE_INTEGRITY_OK
  CWD: ../..
  EVIDENCE: exit 0; CYCLE_INTEGRITY_OK

- [x] G2: HTML locator model and embedded projection JSON are machine-verifiable
  CHECK: python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope locator
  EXPECT: CYCLE_LOCATOR_OK
  CWD: ../..
  EVIDENCE: exit 0; CYCLE_LOCATOR_OK

- [x] G3: evaluator-only evidence is sealed and public HTML exposes no gold locator
  CHECK: python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope gold
  EXPECT: CYCLE_GOLD_ISOLATION_OK
  CWD: ../..
  EVIDENCE: exit 0; CYCLE_GOLD_ISOLATION_OK

- [x] G4: two measured cycles and their deltas are embedded in the HTML report
  CHECK: python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope report
  EXPECT: CYCLE_REPORT_OK
  CWD: ../..
  EVIDENCE: exit 0; CYCLE_REPORT_OK; cycle-1, cycle-2, cycle-3 parsed

- [x] G5: targeted regression tests pass
  CHECK: pytest -q knowledge-base/_ops/rebuild/test_local_knowledge_rebuild.py
  EXPECT: 9 passed
  CWD: ../..
  EVIDENCE: exit 0; 9 passed in 0.92s

- [x] G6: tracked diff has no whitespace errors
  CHECK: python knowledge-base/_ops/rebuild/validate_knowledge_cycle.py --scope diff
  EXPECT: CYCLE_DIFF_OK
  CWD: ../..
  EVIDENCE: exit 0; CYCLE_DIFF_OK
