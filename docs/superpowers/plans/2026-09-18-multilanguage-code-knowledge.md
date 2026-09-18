# Multilanguage Code Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the commit-bound code knowledge index from Python-only input to recognized and unknown programming languages while preserving provenance and honest parser limitations.

**Architecture:** Keep the existing Python AST adapter. Add a language/extension registry and a deterministic lexical fallback adapter for languages without a dedicated parser. Every file and symbol retains Git commit/tree/blob locators and records its language, parser, and confidence.

**Tech Stack:** Python standard library, `ast`, deterministic regular expressions, Git CLI, pytest.

**Spec:** User-approved in-chat design: language adapters plus a universal lexical fallback, with explicit confidence and limitations.

## Global Constraints

- Git commit, tree, blob, content hash, and replayable locator remain mandatory provenance.
- Existing Python node kinds and `contains`/`imports` edges remain compatible.
- Lexical fallback must not claim AST-level certainty; mark parser and confidence explicitly.
- No third-party parser dependency is required for the baseline implementation.
- Generated indexes remain projections; canonical code evidence remains Git-pinned.

### Task 1: Lock the multilingual contract with fixtures

**Files:**
- Modify: `context-graph/tests/test_code_index.py`
- Test: `context-graph/tests/test_code_index.py`

**Interfaces:**
- `build_index()` accepts a repository containing multiple recognized language extensions.
- Returned file and symbol nodes expose `language`, `parser`, and `confidence`.

- [ ] Add JavaScript, TypeScript, Go, Rust, and an unknown-but-code-like fixture to the committed test repository.
- [ ] Assert each file is indexed, lexical symbols are emitted with `parser=lexical-fallback`, and imports are represented with `imports` edges.
- [ ] Assert Python still uses `parser=python-ast` and retains existing node kinds.
- [ ] Run `pytest -q context-graph/tests/test_code_index.py` and confirm the new test fails because the current implementation only selects `.py` files.

### Task 2: Add language registry and adapters

**Files:**
- Modify: `context-graph/scripts/code_index.py`
- Test: `context-graph/tests/test_code_index.py`

**Interfaces:**
- `language_for_path(path: str) -> str` returns a stable language label or `unknown`.
- `adapter_for_language(language: str)` returns the Python AST adapter or lexical fallback.
- `build_index()` scans the registered code extensions and explicit paths, preserving the existing JSON envelope.

- [ ] Add a stable extension and filename registry covering common compiled, scripting, mobile, data/query, and configuration languages.
- [ ] Implement a deterministic lexical fallback that extracts only conservative declarations/imports and records line ranges.
- [ ] Add parser/confidence/language fields without removing existing fields.
- [ ] Use `mixed` at the document-set level and retain per-node language metadata.
- [ ] Run the focused test and confirm it passes.

### Task 3: Update evaluation and documentation

**Files:**
- Modify: `context-graph/scripts/evaluate_code_index.py`
- Modify: `context-graph/skills/knowledge-engineering/references/code-workflow.md`
- Modify: `context-graph/skills/knowledge-engineering/SKILL.md`
- Test: `context-graph/tests/test_code_index.py`

**Interfaces:**
- Evaluation lexical baseline scans the same registered code paths as the index.
- Documentation names supported adapters, fallback semantics, and language-specific uncertainty.

- [ ] Replace Python-only evaluation filtering with the shared code-path registry.
- [ ] Document that unsupported languages are still captured lexically but not promoted to AST-level claims.
- [ ] Run focused tests, the full test suite, and `git diff --check`.

### Task 4: Verify the projection

**Files:**
- No production files beyond Tasks 1–3.

- [ ] Run `pytest -q context-graph/tests`.
- [ ] Run a temporary mixed-language repository through `collect` and `index` at a fixed commit.
- [ ] Replay every emitted evidence record and confirm commit/blob/content locators.
- [ ] Record unsupported parser limitations and unresolved risks in the final report.
