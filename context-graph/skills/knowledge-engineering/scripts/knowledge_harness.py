#!/usr/bin/env python3
"""Trusted-channel harness for role-scoped knowledge packs.

The launcher creates the manifest; an agent cannot turn legacy attribution or a
prompt field into authority.  This command is intentionally read-only.
"""
import argparse
import json
from pathlib import Path

from role_access import AccessDenied, filter_pack, load_access_context, authorize


def load_manifest(root: Path, path: str):
    manifest = json.loads((root / path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"policy", "binding", "catalog", "subject"}:
        raise AccessDenied("invalid_harness_manifest")
    context = load_access_context(root, manifest["policy"], manifest["binding"],
                                  manifest["catalog"], manifest["subject"])
    return context


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", required=True)
    parser.add_argument("operation", choices=("authorize", "filter-pack"))
    parser.add_argument("pack", nargs="?")
    args = parser.parse_args(argv)
    try:
        context = load_manifest(args.root.resolve(), args.manifest)
        if args.operation == "authorize":
            output = authorize(context)
        else:
            if not args.pack:
                parser.error("filter-pack requires a JSON pack path")
            output = filter_pack(context, json.loads(Path(args.pack).read_text(encoding="utf-8")))
    except (AccessDenied, OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"effect": "deny", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
