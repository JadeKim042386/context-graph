# Context Graph Skill Package

This package provides a cross-runtime Knowledge Engineering Skill for Codex and
Claude Code. It supports analysis, proposal, review, and modification workflows,
turning source material into traceable, reviewable knowledge and
HTML-first projections that answer with evidence or deliberately abstain.

## 1. Overall structure

![Overall knowledge-engineering structure](assets/readme/overall-structure-v2.png)

The system moves from a bounded question and preserved source material to
canonical records, evidence checks, graph validation, projections, and measured
retrieval. The final answer state is `answer`, `conflict`, or `abstain`.

## 2. Operation flow and order

![Knowledge-engineering workflow and state transitions](assets/readme/workflow-static-v4.png)

The workflow has eight ordered stages:

1. **Scope** — define the question, domain, date, and acceptance criteria.
2. **Collect** — preserve documents, datasets, images, video, audio, or URLs.
3. **Normalize** — create stable Source, Evidence, Claim, Media, and provenance records.
4. **Model** — represent typed entities, relations, time, and ontology constraints.
5. **Validate** — check schemas, locators, hashes, freshness, reasoning, conflicts, and gold isolation.
6. **Review** — compare supporting and counter-evidence and decide accept, revise, hold, or reject.
7. **Project** — rebuild HTML, graph, search, reports, Context Packs, memory pointers, and optional Archify diagrams.
8. **Measure** — compare strategies on the same snapshot and question order.

The analysis/proposal role is read-only and returns an evidence-backed handoff.
The modification role applies only an approved request, preserves provenance,
creates revisions, rebuilds projections, and verifies the result.

## 3. Installation and use

### Codex

Copy or link `skills/knowledge-engineering/` into the project's configured Codex
skills location, or keep it in the project at:

```text
skills/knowledge-engineering/SKILL.md
```

### Claude Code

Install this package as a Claude Code plugin checkout. Claude Code loads the same
`SKILL.md` and uses `CLAUDE.md` host instructions when present; it does not
require `AGENTS.md`. The skill does not assume a host-specific environment
variable.

After installation, run from the project root and ask for a knowledge analysis,
proposal, review, modification, or evidence-backed answer.

Retrieval follows the project's language rule: ask in the language the document
is written in, respect the configured `answer_budget`, and ask narrowly so broad
questions return only the relevant set.

Useful commands:

```bash
python skills/knowledge-engineering/scripts/update_memory.py --help
python skills/knowledge-engineering/scripts/validate_workspace.py --root .. --profile portable
python scripts/build_map.py --help
python scripts/ask.py "question"
python scripts/ask.py --conflicts
```

For Codex package validation, run the `quick_validate.py` script provided by the
installed `skill-creator` skill. Do not hard-code a machine-specific path.

## 4. Folder structure

![Knowledge-engineering repository folder structure](assets/readme/folder-structure-v2.png)

| Folder | What it contains | Editing rule |
|---|---|---|
| `skills/knowledge-engineering/` | Skill instructions, references, and helper scripts | Change shared workflow rules deliberately |
| `agents/` | Analysis, modification, and coordination roles | Keep role boundaries explicit |
| `tests/` | Skill, packaging, parser, and integration tests | Add regression coverage for contract changes |
| `scripts/` | Map-building, parsing, lookup, and validation helpers | Run from the consuming project root |
| `assets/readme/` | Documentation images for the skill package | Keep images aligned with the package workflow |
| `.claude-plugin/` | Claude Code plugin metadata | Keep package source and version aligned |

## 5. Record information

![Knowledge-engineering record and evidence chain](assets/readme/record-chain-v2.png)

Records are small, stable, and connected by provenance. A content claim is
usable only when its chain can be replayed:

```text
Claim → Evidence → Source revision
   ↑          ↑
Review    Provenance activity
```

| Record | Purpose | Important information |
|---|---|---|
| `Source` | Identifies the original material | `id`, revision, title, URL/path, access date, hash, rights |
| `Evidence` | Points to the exact supporting location | `id`, source revision, locator, observed text/data, freshness |
| `Claim` | States one atomic proposition | `id`, statement, scope, status, evidence references, `supersedes` |
| `Media` | Describes image, video, or audio evidence | format, hash, rights, region/page/timecode locator, derivative links |
| `Review` / `Decision` | Records human assessment and approval | reviewer, criteria, decision, status, conflicts, date |
| `Validation` | Records quality and consistency checks | method, snapshot, result, failures, replay details |

Metadata-only observations cannot support content claims. Generated HTML,
graphs, indexes, reports, and optional Archify diagrams are projections rebuilt
from approved inputs; they are never hand-edited. Memory stores pointers rather
than source text and is updated only after an approved decision, verified
snapshot, or goal-state transition.

## Contracts and verification

Detailed contracts are in `skills/knowledge-engineering/references/`:

- `record-schema.md` — canonical record fields
- `evidence-rules.md` — support, conflict, freshness, and reproducibility rules
- `memory-update.md` — pointer-only Second Brain state updates
- `validation-gates.md` — workspace and projection checks

```bash
pytest -q tests/test_final_skill_contract.py
pytest -q tests/test_knowledge_engineering_skill.py
pytest -q tests
```
