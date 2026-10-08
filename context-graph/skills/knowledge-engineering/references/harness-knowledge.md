# Harness knowledge boundary

The harness is the authorization layer between a session/agent and project
knowledge. It is not a prompt convention and it does not make a model a
reviewer.

```text
trusted launcher
  └─ harness manifest
      ├─ RolePolicy       project + revision + role → scope IDs
      ├─ RoleBinding      session + agent + task + assignment + role caps
      └─ ScopeCatalog      artifact pointer → required scope IDs
                │
                ▼
      project ∩ session role ∩ agent role ∩ task cap ∩ assignment cap
                │
                ▼
      authorize → filter whole records → rank/truncate → disclose pack
```

The launcher must set `trusted=true` and provide the policy and catalog
digests. A prompt, `--role` value, caller-declared attribution, copied policy,
foreign path, stale revision, revoked binding, unknown role, or uncatalogued
artifact is not authority. The effective result is deny/insufficient with no
fallback to a global corpus.

Each artifact is labeled with every scope it requires. A record with multiple
artifact pointers is disclosed only when every pointer is authorized. Filtering
happens before graph expansion, ranking, byte limits, or source replay, so a
denied record cannot leak through counts or truncation.

Legacy session events remain byte-compatible. In harness mode, events without a
trusted role binding are treated as `unknown-role` and are withheld. Read
authorization never grants review, promotion, merge, or filesystem isolation;
those remain separate controls.

The session overlay adds a reversible layer above this boundary:

```text
session/agent open → provenance registry
session events     → project overlay (provisional merge)
session/agent close → close state + idempotent overlay rebuild
split selectors    → original session/agent/task/assignment/role view
review approval    → optional canonical memory promotion
```

The read-only dispatcher is:

```bash
python context-graph/skills/knowledge-engineering/scripts/knowledge_harness.py \
  --root . --manifest .context-graph/harness-manifest.json authorize
```

The manifest and its referenced records are project-local operational state;
do not commit credentials, raw prompts, transcripts, or private identifiers.
