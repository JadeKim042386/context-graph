# Post-install integration verification

Run this read-only check from the consuming project root after installing the
skill. Installation is not integration proof: verify package files, host
discovery, and an actual harmless response separately.

## Procedure

1. Record `git status --short` before the check.
2. Confirm that the installed copy contains these readable files:
   - `skills/knowledge-engineering/SKILL.md`
   - `skills/knowledge-engineering/references/record-schema.md`
   - `skills/knowledge-engineering/references/evidence-rules.md`
   - `skills/knowledge-engineering/scripts/validate_workspace.py`
3. Test the hosts independently:
   - Codex: invoke or select `knowledge-engineering`; apply `AGENTS.md` when
     present.
   - Claude Code: load the same skill through the plugin; apply `CLAUDE.md`
     when present. Do not require `AGENTS.md` for Claude Code.
4. Send this harmless smoke request to each host:

   > Use the knowledge-engineering skill in read-only analysis mode. From the
   > installed SKILL.md, report the default answer state when evidence is
   > missing, classify the statement as FACT, cite the exact file and line, and
   > do not edit, rebuild, or update memory.

5. Confirm that the response visibly:
   - identifies or applies `knowledge-engineering`;
   - returns `FACT` and `abstain`;
   - cites the exact default-state lines in `SKILL.md`;
   - reports `changed: none`;
   - creates no records, projections, memory entries, or commits.
6. Compare `git status --short` with the pre-check output. They must be
   identical.
7. Run the portable validator from the consuming project root:

   ```bash
   python context-graph/skills/knowledge-engineering/scripts/validate_workspace.py --root . --profile portable
   ```

   Use `--profile project` only when the consuming project intentionally
   provides the required knowledge, memory, and design artifacts.

## Project-local session capture

After the read-only smoke test passes, explicitly activate privacy-filtered
session capture for the consuming project:

```bash
python skills/knowledge-engineering/scripts/record_session_event.py init \
  --root . \
  --runtime claude-code \
  --include 'knowledge/**' \
  --include 'design/**'
```

Then simulate lifecycle events with fake prompt, transcript, token, and secret
fields. Confirm that only whitelisted metadata appears in
`knowledge-base/_ops/session-events.jsonl` and that provisional proposals are
written under `knowledge-base/_ops/session-proposals/`. No canonical records,
memory pointers, prompts, transcripts, commands, secrets, or absolute paths may
be created. Codex has no verified universal lifecycle-hook surface; do not
claim automatic Codex compaction or exit capture.

## Acceptance and failure handling

Integration is verified only when all package, host-discovery, smoke-response,
unchanged-worktree, and validator checks pass for the host being tested. Test
Codex and Claude Code independently; success in one host does not prove the
other.

If a check fails, report the exact failed boundary (`files`, `discovery`,
`smoke`, `working tree`, or `validator`), keep the result unverified, and do
not create project records or claim that the skill is integrated. A file's
presence, a host prompt, a spinner, or a generic successful answer is not
evidence of skill loading.
