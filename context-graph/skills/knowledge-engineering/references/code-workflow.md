# Code Work Mode

Use this mode for repository analysis, bug investigation, feature work, refactoring, compatibility review, and test review.

Keep source code and history in Git. Store reviewed knowledge about code as canonical JSON records; do not make an AST, code graph, SCIP database, branch name, or search result the source of truth.

Every accepted code claim must resolve to a repository ID, full commit SHA, tree/blob identity when applicable, repository-relative path and line or byte range, content hash, Evidence ID, and review/decision status. A branch is only an observation that resolves to a commit. Issues are requirement/report evidence, not implementation proof. TestRun evidence records the exact command, selected tests, commit, environment/toolchain digest, exit code, and immutable report hash.

## Code workflow

1. Scope the repository, requirement, base commit, allowed paths, and acceptance tests.
2. Capture repository identity, commit/tree, branch observation, dirty-tree digest, and existing test state.
3. Analyze and propose read-only with exact commit/path/line evidence.
4. Modify only after explicit approval for target paths; preserve unrelated dirty work.
5. Run focused then broader checks and capture command, environment, exit code, and report hash.
6. Review requirement, diff, code locators, test evidence, security findings, and unresolved risk independently.
7. Rebuild derived projections from the pinned commit and canonical-record snapshot.

Commit, push, deployment, issue updates, and pull-request actions require separate authorization.

## Derived projections and evaluation

The current final design is Git plus reviewed JSON/JSONL as the canonical layer, with a commit-bound Python AST projection, duplicate-safe symbols, bounded `contains`/`imports` one-hop expansion, and lexical fallback. Code graphs, Tree-sitter, SCIP, SQLite, RDF/PROV-O, HTML dossiers, and Context Packs remain optional reproducible projections. Record input commit/tree, canonical-record snapshot hash, generator version, configuration digest, and output hash. Do not make an optional projection mandatory without a paired held-out evaluation showing a performance gain.

Compare lexical/path retrieval and the derived code index on the same commit, question order, model, and cache condition. Report locator replay, recall@k, candidate count, Context Pack size, cold/warm latency, correctness, locator agreement, false answers, and abstention. Promote a precise code graph only when gates pass; otherwise improve routing or the lightweight index and repeat.
