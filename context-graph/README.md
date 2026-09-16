# Context Graph Skill Package

This package provides a cross-runtime Knowledge Engineering Skill for Codex and
Claude Code. It turns source material into traceable, reviewable knowledge and
HTML-first projections that can answer with evidence or deliberately abstain.

## What the skill does

The final structure is:

```text
1 Scope → 2 Collect → 3 Normalize → 4 Model
      → 5 Validate → 6 Review → 7 Project → 8 Measure
      → retrieve the smallest supported evidence set
      → answer | conflict | abstain
```

Each stage has one job:

| Stage | Core responsibility | Output |
|---|---|---|
| Scope | Define the question and acceptance criteria | Bounded question |
| Collect | Preserve documents, datasets, images, video, audio, and URLs | Immutable source revision |
| Normalize | Create stable Source, Evidence, Claim, Media, and provenance records | Reviewable canonical records |
| Model | Add typed entities, relations, time, and ontology constraints | Graph/RDF/OWL/SHACL model |
| Validate | Check schema, locators, hashes, freshness, reasoning, conflicts, and gold isolation | Promotion evidence |
| Review | Compare support and counter-evidence | Approved, held, revised, or rejected decision |
| Project | Rebuild HTML, graph, search, reports, Context Packs, memory pointers, and optional Archify diagrams | Reproducible views |
| Measure | Compare strategies on the same snapshot and question order | Local performance evidence |

The analysis/proposal role reasons and returns an evidence-backed handoff without
editing. The review and modification roles apply only an approved request,
preserve provenance, create revisions, rebuild projections, and verify the result.
When delegated reasoning is required and cmux is exposed by the project, its
configured knowledge-engineer subagent is preferred; otherwise use the host's
documented coordination mechanism and report any limitation.

## Installation and use

### Codex

Copy or link this package's `skills/knowledge-engineering/` directory into the
project's configured Codex skills location, or keep the package in the project
and reference the skill at:

```text
skills/knowledge-engineering/SKILL.md
```

### Claude Code

Install the same package as a Claude Code plugin checkout. Claude Code uses the
skill's `SKILL.md` and its `CLAUDE.md` host instructions when present; it does
not require `AGENTS.md`. The skill itself does not assume a host-specific
environment variable.

After installation, run from the project root and ask for a knowledge-analysis,
proposal, review, modification, or evidence-backed answer.

## Retrieval limits

Graph answers follow the project's existing limits: ask in the language the
document is written in, respect the configured `answer_budget`, and ask
narrowly so broad questions return only the relevant set.

## Contracts and tools

Detailed contracts are in `skills/knowledge-engineering/references/`:

| Reference | Purpose |
|---|---|
| `record-schema.md` | Canonical Source, Evidence, Claim, Media, Review, and Decision fields |
| `evidence-rules.md` | Support, conflict, freshness, and reproducibility rules |
| `memory-update.md` | Pointer-only Second Brain state updates |
| `validation-gates.md` | Workspace, provenance, projection, and cycle checks |

```bash
python skills/knowledge-engineering/scripts/update_memory.py --help
python skills/knowledge-engineering/scripts/validate_workspace.py --root .. --profile portable
```

For Codex package validation, run the `quick_validate.py` script provided by the
installed `skill-creator` skill. Do not hard-code a machine-specific path.

The existing graph tools remain deterministic and explicit:

```bash
python scripts/build_map.py --help
python scripts/ask.py "question"
python scripts/ask.py --conflicts
```

## Verification

```bash
pytest -q tests/test_final_skill_contract.py
pytest -q tests/test_knowledge_engineering_skill.py
pytest -q tests
```

Explicitly named authored HTML under `knowledge/` is an input. Generated HTML,
graph files, indexes, reports, and optional Archify diagrams under rebuild/output
folders are projections rebuilt from approved inputs; they are not hand-edited.
Every content claim must retain a Claim → Evidence → Source revision chain;
metadata-only observations cannot support content claims. Keep source copies, secrets,
transient model output, and sealed evaluator answers out of memory and Context
Packs.
