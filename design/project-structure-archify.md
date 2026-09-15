# context-graph Project Structure

This document describes the project structure diagram generated with Archify and how to read it.

## Diagram

[Open the interactive Archify diagram](./project-structure.architecture.html)

> The linked file is a self-contained HTML artifact generated and validated by Archify. Open the link if a Markdown preview does not render HTML as an image.

## Core structure

```text
context-graph/
├── AGENTS.md                         # rules applied to all work
├── knowledge/                        # human-readable knowledge HTML
├── knowledge-base/                   # canonical knowledge data
│   ├── 10-concepts/                  # concepts
│   ├── 20-claims/                    # claims
│   ├── 30-sources/                   # source identity
│   ├── 35-evidence/                  # evidence locations
│   ├── 40-decisions/                 # approval decisions
│   ├── 60-reviews/                   # review findings
│   ├── 70-media/                     # media metadata
│   ├── 80-views/                     # generated HTML and JSON
│   ├── _index/                       # search indexes and relationships
│   └── _ops/                         # rules, rebuilds, logs, and memory
├── design/                           # design and comparison experiments
└── graphify-out/                     # externally generated graph and search results
```

## Reading order

1. Review canonical records in `knowledge-base/10~70`.
2. Check approval through `Review` and `Decision` records.
3. Rebuild `80-views/`, `_index/`, and `graphify-out/` from an approved snapshot.
4. Record shared-rule changes in `AGENTS.md`; record current state and unresolved items as pointers in `_ops/memory/index.json`.

## Generation details

- Diagram type: `architecture`
- Source specification: [`project-structure.architecture.json`](./project-structure.architecture.json)
- Renderer: `tt-a1i/archify`
- Original knowledge files and Markdown remain unchanged; only diagram artifacts are added.
