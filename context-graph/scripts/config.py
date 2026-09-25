"""Reads and writes the config. No path is hard-coded anywhere else; everything goes through here."""
import json
import os
import hashlib
from pathlib import Path
from freshness import FreshnessError, verify_freshness

DEFAULT_CONFIG = {
    "source_dirs": [],            # where the knowledge documents live
    "map_path": "",               # where the map goes (outside the knowledge documents)
    # A cap on the answer, in characters. Asking here is only worth it when it costs less than
    # opening the document, so the cap is measured in the same unit a document is. Statements are
    # dropped whole from the back, never cut in the middle, and the count of what was dropped is
    # printed. Raise it and a broad question costs more than reading the note it came from.
    "answer_budget": 8000,
}


def load_config(config_path):
    """Read the config. A missing file or a missing key falls back to the default."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8-sig", errors="replace") as handle:
            config.update(json.load(handle))
    return config


def default_config_path():
    """Where the config lives. An environment variable overrides it, so each machine can differ."""
    return os.environ.get("KNOWLEDGE_MAP_CONFIG") or os.path.join(
        os.path.expanduser("~"), ".claude", "context-graph", "config.json")


def save_config(config_path, config):
    """Write the config, creating the folder if it does not exist."""
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)


class BindingError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def binding_failure(reason):
    return {"binding": {"status": "unverified", "reason": reason}, "hits": []}


def _project_path(root, value, kind):
    if not isinstance(value, str) or not value:
        raise BindingError(f"invalid_{kind}_path")
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise BindingError(f"{kind}_outside_project")
    return path


def _binding_json(path, kind):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        raw = path.read_bytes()
        data = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(data, dict):
            raise ValueError("not object")
        return data, hashlib.sha256(raw).hexdigest()
    except FileNotFoundError as exc:
        raise BindingError(f"missing_{kind}") from exc
    except (OSError, ValueError, RecursionError) as exc:
        raise BindingError(f"invalid_{kind}") from exc


def validate_source_path(path, binding, require_exists=True):
    root = Path(binding["project_root"])
    candidate = _project_path(root, path, "source")
    if not any(candidate.is_relative_to(Path(folder)) for folder in binding["allowed_source_roots"]):
        raise BindingError("map_source_outside_allowed_roots")
    if require_exists and not candidate.is_file():
        raise BindingError("map_source_missing")
    return candidate


def validate_bound_map(graph, binding):
    if graph.get("project_binding") != binding:
        raise BindingError("map_binding_mismatch")
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("links"), list):
        raise BindingError("invalid_map")
    ids = set()
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or node["id"] in ids:
            raise BindingError("invalid_map")
        ids.add(node["id"])
        source = node.get("source_file")
        if source:
            if not isinstance(source, str) or not Path(source).is_absolute():
                raise BindingError("invalid_map_source_path")
            try:
                validate_source_path(source, binding, require_exists=False)
            except BindingError as exc:
                if exc.reason == "source_outside_project":
                    raise BindingError("map_source_outside_allowed_roots") from exc
                raise
        elif node.get("kind") != "name_only":
            raise BindingError("map_source_missing")
    for link in graph["links"]:
        if not isinstance(link, dict) or not isinstance(link.get("source"), str) or not isinstance(link.get("target"), str):
            raise BindingError("invalid_map")
        if link["source"] not in ids or link["target"] not in ids:
            raise BindingError("invalid_map")


def load_project_config(project_root, config_path=None, *, require_map=True):
    """Explicit project-only runtime loading; never consult global defaults/environment."""
    if project_root is None:
        raise BindingError("missing_project_root")
    root = Path(project_root).resolve()
    if not root.is_dir() or not Path.cwd().resolve().is_relative_to(root):
        raise BindingError("cwd_mismatch")
    selected = _project_path(root, str(config_path) if config_path is not None else ".context-graph/config.json", "config")
    config, config_hash = _binding_json(selected, "config")
    declared = config.get("project_binding")
    if not isinstance(declared, dict):
        raise BindingError("missing_binding")
    if declared.get("project_root") != str(root):
        raise BindingError("project_root_mismatch")
    if _project_path(root, declared.get("config_path"), "config") != selected:
        raise BindingError("config_identity_mismatch")
    map_path = _project_path(root, config.get("map_path"), "map")
    if _project_path(root, declared.get("map_path"), "map") != map_path:
        raise BindingError("map_identity_mismatch")
    sources, allowed = config.get("source_dirs"), declared.get("allowed_source_roots")
    if not isinstance(sources, list) or not sources or not isinstance(allowed, list) or not allowed:
        raise BindingError("invalid_source_roots")
    sources = sorted({str(_project_path(root, path, "source")) for path in sources})
    allowed = sorted({str(_project_path(root, path, "source")) for path in allowed})
    if sources != allowed:
        raise BindingError("source_roots_mismatch")
    if not all(Path(path).is_dir() for path in allowed):
        raise BindingError("missing_source_root")
    binding = {"project_root": str(root), "config_path": str(selected),
               "map_path": str(map_path), "allowed_source_roots": allowed}
    binding["binding_id"] = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    graph, map_hash = None, None
    snapshot_hash = None
    if require_map:
        graph, map_hash = _binding_json(map_path, "map")
        validate_bound_map(graph, binding)
        try:
            snapshot_hash = verify_freshness(graph, sources, lambda path: validate_source_path(path, binding))
        except FreshnessError as exc:
            raise BindingError(str(exc)) from exc
    budget = config.get("answer_budget", DEFAULT_CONFIG["answer_budget"])
    if type(budget) is not int or budget <= 0:
        raise BindingError("invalid_answer_budget")
    config.update(source_dirs=sources, map_path=str(map_path), answer_budget=budget)
    resolved = {**binding, "status": "verified", "config_sha256": config_hash,
                "map_sha256": map_hash, "map_state": "verified" if require_map else "not_checked",
                "freshness_state": "verified" if require_map else "not_checked",
                "source_snapshot_sha256": snapshot_hash,
                "global_config_used": False}
    return config, binding, resolved, graph
