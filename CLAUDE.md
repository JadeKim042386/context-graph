# Checkout bridge for Claude Code (project memory and knowledge)

Approved minimal patch from `work/coordination/codex-memory-knowledge-review-20250925.md`
(task `memory-knowledge-cycle-20260925-01`). This file only routes the host to the
checkout's read-only continuity and binding CLIs. It changes no memory, config, hooks, or map.

## 1. Confirm the project root

The selected project root must be `/Users/joo/Desktop/context-graph`. Use the scripts
in this checkout at the exact paths below. Do not pick a globally installed or cached
copy of the `context-graph` plugin or skill because it has the same name; the cached
copy may be older and may lack the knowledge-engineering continuity scripts.

## 2. Follow AGENTS.md

Read this project's `AGENTS.md` and keep its delegated-reasoning and cmux boundary.
The main executor does not make semantic decisions itself. This file does not restate
or replace AGENTS rules.

## 3. Before any analysis or retrieval, run both read-only commands

```bash
python -B /Users/joo/Desktop/context-graph/context-graph/scripts/ask.py \
  --project-root /Users/joo/Desktop/context-graph --binding-only
python -B /Users/joo/Desktop/context-graph/context-graph/skills/knowledge-engineering/scripts/build_task_continuity.py \
  --root /Users/joo/Desktop/context-graph
```

Neither command writes memory, indexes, config, or host files.

## 4. Report what was consumed

In the response, state: binding `status` and `global_config_used`, the script paths used
and their SHA-256, `pack_status`, applicable count, unresolved count, and the `safety`
constraints. Report partial packs as partial (current baseline: partial, 3 applicable,
4 unresolved). Do not copy source bodies, transcripts, prompts, or secrets.

## 5. Interpret states strictly

- `binding.status` other than `verified`, or a missing/mismatched root, is a failure.
  Do not fall back to a global config.
- `pack_status=partial` or `conflict`: use only applicable items within their evidence
  scope; keep every unresolved item visible; do not close, promote, or infer historical state.
- `applicable=true` is not acceptance and not permission to execute or promote.
  A Review supports only its recorded observation.
- Scoped questions: pass `--question-key`, `--scope`, `--as-of`; use only matching items.

## 6. What this file does not prove

This bridge is not evidence that the cached plugin was upgraded, that hooks delivered
anything, or that Codex resume works. Those are verified separately.
