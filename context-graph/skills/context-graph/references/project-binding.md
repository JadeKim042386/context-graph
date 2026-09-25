# Project-bound knowledge retrieval

`ask.py` now requires `--project-root`. It never selects a global config through
`default_config_path()` or `KNOWLEDGE_MAP_CONFIG`. The default config is
`<project-root>/.context-graph/config.json`; `--config` may select another file
inside the same project. Relative paths are resolved from project root, not cwd.
cwd must be the selected root or a descendant. Cross-project calls fail closed.

## Local config contract

This example is a contract, not permission to create or change configuration:

```json
{
  "source_dirs": ["knowledge"],
  "map_path": "graphify-out/context-graph.json",
  "answer_budget": 8000,
  "project_binding": {
    "project_root": "/absolute/path/to/project",
    "config_path": ".context-graph/config.json",
    "map_path": "graphify-out/context-graph.json",
    "allowed_source_roots": ["knowledge"]
  }
}
```

The declared root must exactly equal its resolved absolute root. Config/map paths
must identify the selected files. Normalized `source_dirs` must equal the explicit
allowlist, and every directory must exist within the project. Symlink escapes are
rejected. A moved project requires explicit rebinding; never silently rewrite its
identity. Global `load_config`/`save_config` helpers remain for setup compatibility,
not as the retrieval entry point.

After an authorized build, the map contains a `project_binding` envelope with the
resolved root/config/map/source roots and deterministic `binding_id`. Retrieval
checks this envelope, every located node's absolute source path, source existence,
unique node IDs, and link endpoints. Only `name_only` nodes may lack a locator.
An unbound legacy map is not automatically trusted. A swapped map or a located
node outside the allowlist returns no hits.

## Read-only checks

```bash
python context-graph/scripts/ask.py --project-root . --binding-only
python context-graph/scripts/ask.py --project-root . --read-only "one narrow question"
```

Use the installed runtime's script prefix when appropriate. A successful result
exposes resolved paths, allowed roots, binding ID, config/map SHA-256 and
`global_config_used=false`. `--read-only` searches the already validated in-memory
map using existing lexical matching; it does not call graphify, create caches,
rebuild anything, or implement a new embedding model. `--binding-only` returns no
hits. Failures have `binding.status=unverified`, an explicit reason, `hits=[]`,
and exit 2. Check the state, not just whether output exists.

The default graphify/chain/path/conflict modes also validate binding first.
Their existing behavior is otherwise retained; they are not the read-only probe,
and `--settle` remains a mutation requiring its own user authorization. They can
reopen the map after validation, so hostile concurrent replacement is not covered.

## Build and compatibility boundary

Only after build/config modification is authorized:

```bash
python context-graph/scripts/build_map.py --project-root .
```

Bound builds reject source/output CLI overrides, check candidate paths before
reading documents, and stamp the map envelope. A cached fingerprint cannot cause
an unbound/mismatched map to be accepted as a bound map. Existing explicit
`--source ... --out ...` and low-level `build_map(...)` utilities remain available
for tests/offline imports and produce **unbound** maps; they never consult global
config implicitly, and the new retrieval CLI rejects their unbound outputs.

Existing hooks, setup-generated configurations and installed copies are not
automatically migrated. Do not claim operational integration until the consuming
project has an approved local binding, an approved bound rebuild and host smoke
evidence. A missing binding is not permission to broaden the source allowlist.

## Memory is a separate route

The knowledge-engineering continuity reader uses explicit `--root`, root-relative
memory pointers and cycle-01 integrity checks. It now rejects cwd outside root and
emits a memory-scoped binding with root SHA-256 identity, relative memory path and
allowed root `.`. It deliberately reports `config_map_state=not_used` and does not
load any knowledge/global config. Root paths are hashed there to preserve the
continuity pack's no-absolute-private-path output contract. Binding validity does
not imply valid/accepted memory content; inspect `pack_status` and pointer states.

## Limits of verification

Binding is provenance routing, not authentication, rights verification, content
truth or freshness. A malicious map that lies about a local source path is not
detected solely by this envelope. Source content hashes/rename freshness,
multi-file locks and map size/resource hardening remain separate work. Explicitly
authorizing an overly broad project root/allowlist is not cured by syntactic path
checks. No cross-project content is intentionally imported or approved here.
