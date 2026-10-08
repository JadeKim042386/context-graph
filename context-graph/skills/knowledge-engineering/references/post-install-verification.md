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

### Automatic map refresh is separately activated

The `SessionStart`, `SubagentStop`, and `PostCompact` map-refresh hooks run
only when the selected project's `.context-graph/config.json` exists. Without
that activation they return exit 0 and `status=skipped`,
`reason=project_not_activated`, creating no config, map, or journal. Config-file
or config-directory symlinks are still sent to the bound builder for validation,
including broken symlinks; malformed or foreign bindings remain errors. This
hook-only no-op does not change the explicit `ask.py` / `build_map.py` contract:
missing or invalid binding still returns exit 2 when those CLIs are requested.

Map activation is independent of `session-capture.json`. A disabled/absent
capture configuration makes the recording hook a no-op, but does not disable
map refresh in a bound project. Do not initialize either configuration merely
to suppress a hook error; verify no-op and active-project behavior separately.

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

## Project-local worktree snapshots (no shared-cache changes)

`install_project_payload.py --root PROJECT install` copies the current
`PROJECT/context-graph/` runtime package into
`.context-graph/plugins/context-graph/<payload_id>/context-graph/` and writes
an immutable hash manifest alongside it. Tests and sealed gold are excluded.
The payload ID binds every packaged path, byte length and SHA-256. It is a
worktree identity, not a released commit. Identical installs return duplicate;
existing snapshots are verified, never repaired or overwritten.

```sh
python -B context-graph/skills/knowledge-engineering/scripts/install_project_payload.py --root . install
python -B context-graph/skills/knowledge-engineering/scripts/install_project_payload.py verify --snapshot .context-graph/plugins/context-graph/PAYLOAD_ID
```

For explicitly configured Codex CLI use, select the snapshot's
`context-graph/skills/context-graph` and `context-graph/skills/knowledge-engineering`
roots. Invoke binding, continuity, audit and portable validation by absolute
paths from those roots. This does not register an automatic Codex lifecycle hook.

For an authorized fresh Claude smoke, use a synthetic project and a separate
project-local `CLAUDE_CONFIG_DIR`; pass `--plugin-dir` with the immutable plugin
root, `--setting-sources ''`, `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`,
`--no-session-persistence`, `--tools ''`, and a harmless print-mode prompt.
Record sanitized init/plugin and SessionStart hook receipts, process exit,
result state, and protected before/after hashes. Do not copy authentication
secrets into the isolated config. If authentication or hook registration is
unavailable, leave that boundary unverified rather than falling back to the
user-wide installation. A fresh process alone is not a successful host response.

A direct hook-command subprocess proves local hook behavior only, not host
loading, discovery or lifecycle delivery. Keep it separate from a real
`claude -p --plugin-dir ...` receipt. Never install to or rewrite shared caches
for this project-local check. Verify shared payload hashes remain unchanged.
