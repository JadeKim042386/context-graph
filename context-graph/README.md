# Context Graph Skill Package

This directory contains the project's Knowledge Engineering Skill and the existing local graph tool.

## Core Skill

`knowledge-engineering/SKILL.md` defines this flow:

```text
Collect → preserve originals → create canonical records
      → analyze and propose → review and modify
```

Detailed contracts are in `skills/knowledge-engineering/references/`.

| Reference | Purpose |
|---|---|
| `record-schema.md` | Concept, Claim, Source, Evidence, Review, and Decision fields |
| `evidence-rules.md` | How to compare questions, Claims, Evidence, and answers |
| `memory-update.md` | Existing project-state pointer conventions |
| `validation-gates.md` | Existing workspace and artifact checks |

## Provided scripts

```bash
python skills/knowledge-engineering/scripts/update_memory.py --help
python skills/knowledge-engineering/scripts/validate_workspace.py --root ..
```

`update_memory.py` updates pointers without copying source text. `validate_workspace.py` checks required project artifacts and JSON parsing.

## Answer scope limits

Graph queries follow these rules:

- Answer in the language recorded by the documents.
- Ask in the language the document you want is written in so matching reaches that document.
- Follow the configured `answer_budget`; the default is 8,000 characters.
- Ask narrowly: for broad questions, return a narrow relevant set instead of listing every document.

## Existing graph commands

The existing `scripts/` copy explicit Markdown and HTML statements and `[[target]]` relationships without model inference.

```bash
python scripts/build_map.py --help
python scripts/ask.py "question"
python scripts/ask.py --conflicts
```

## Tests

```bash
pytest -q tests/test_knowledge_engineering_skill.py
pytest -q tests
```

Report any existing graph ID-stability failure separately from Skill changes.
