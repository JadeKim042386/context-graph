# Validation Gates

Run the following before the final report.

1. Parse canonical and memory JSON.
2. Check required files, paths, and IDs.
3. Reproduce the Claim → Evidence → Source locator chain.
4. Compare projection and snapshot hashes.
5. Check the HTML parser, internal links, and embedded JSON.
6. Run relevant benchmarks and regression tests.
7. If Archify is configured, its diagram must pass 9 artifact checks with zero errors and warnings using `validate ... --quality showcase --json`.
8. Run `git diff --check`.

Do not report a failed gate as successful. Distinguish pre-existing snapshot mismatches from failures caused by the current change.
