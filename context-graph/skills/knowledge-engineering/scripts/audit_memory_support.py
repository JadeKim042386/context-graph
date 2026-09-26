#!/usr/bin/env python3
"""Read-only replay of the local supporting evidence declared by memory-bound Reviews/Decisions.

One hop only: for every proof the continuity reader marks applicable, each entry of its
declared ``evidence`` list is resolved inside the project root and its bytes are hashed.
The result is pointer-only JSON reported separately from continuity applicability and
bounded by an explicit total output budget. Nothing is written, promoted, repaired,
inferred, cached, or fetched.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_task_continuity as continuity  # noqa: E402
import update_memory as integrity  # noqa: E402

STATUSES = ("valid", "stale", "unlocatable", "unverified")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _entry(index, path=None, expected=None):
    return {"locator": f"/evidence/{index}", "path": path if isinstance(path, str) else None,
            "expected_sha256": expected if isinstance(expected, str) else None,
            "actual_sha256": None, "status": "unverified", "reason": "invalid_entry"}


def replay_entry(root, reader, index, entry):
    """Classify one declared evidence entry. Hash equality certifies bytes only, never meaning."""
    if not isinstance(entry, dict):
        return _entry(index)
    result = _entry(index, entry.get("path"), entry.get("sha256"))
    if result["path"] is None or result["expected_sha256"] is None \
            or not continuity.HASH.fullmatch(result["expected_sha256"]):
        result["reason"] = "missing_locator_fields"
        return result
    try:
        path, _ = continuity.safe_pointer(root, result["path"])
        raw = reader.read(path)
    except integrity.IntegrityError as exc:
        result.update(status="unlocatable", reason=exc.reason)
        return result
    except continuity.ReadLimit as exc:
        result.update(status="unverified", reason=f"read_limit:{exc}")
        return result
    except OSError:
        result.update(status="unlocatable", reason="missing_or_unreadable")
        return result
    result["actual_sha256"] = _sha(raw)
    result.update(status="valid" if result["actual_sha256"] == result["expected_sha256"] else "stale",
                  reason="hash_match" if result["actual_sha256"] == result["expected_sha256"] else "hash_mismatch")
    return result


def _drop_entry(result, proof):
    """Omit the proof's last replayed entry; omission always forces incomplete support."""
    dropped = proof["entries"].pop()
    proof["counts"][dropped["status"]] -= 1
    proof["omitted_entries"] += 1
    proof["replay_status"] = "incomplete"
    result["totals"][dropped["status"]] -= 1
    result["totals"]["entries_assessed"] -= 1
    result["totals"]["omitted_entries"] += 1


def _fit(result, max_output_bytes):
    """Deterministic truncation from the end until the encoded output fits the budget."""
    while len(continuity.encode(result).encode("utf-8")) > max_output_bytes:
        result["output_truncated"] = True
        result["support_replay_complete"] = False
        with_entries = [proof for proof in result["proofs"] if proof["entries"]]
        if with_entries:
            _drop_entry(result, with_entries[-1])
        elif result["proofs"]:
            result["proofs"].pop()
            result["totals"]["omitted_proofs"] += 1
        else:
            raise ValueError("output budget too small for envelope")
    return result


def audit(root, memory="knowledge-base/_ops/memory/index.json", *, max_entries=32, max_file_bytes=262144,
          max_total_bytes=1048576, max_evidence=64, max_output_bytes=32768):
    if type(max_evidence) is not int or not 1 <= max_evidence <= 256 \
            or type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 131072:
        raise ValueError("invalid limits")
    pack = continuity.build_pack(root, memory, max_entries=max_entries, max_file_bytes=max_file_bytes,
                                 max_total_bytes=max_total_bytes)
    root = Path(root).resolve()
    limits = {k: v for k, v in pack["limits"].items() if k != "max_pack_bytes"}
    limits.update(max_evidence=max_evidence, max_output_bytes=max_output_bytes)
    result = {"schema_version": 1, "read_only": True, "promotion_performed": False, "cache_reusable": False,
              "binding": pack["binding"], "pack_status": pack["pack_status"],
              "memory_sha256": pack["memory_sha256"], "dependency_sha256": pack["dependency_sha256"],
              "continuity": {"applicable_count": sum(1 for i in pack["items"] if i["applicable"]),
                             "unresolved_count": sum(1 for i in pack["items"] if i["group"] == "unresolved_pointers"),
                             "included_count": pack["included_count"], "memory_complete": pack["safety"]["memory_complete"]},
              "limits": limits, "proofs": [],
              "totals": {"proofs_assessed": 0, "proofs_with_declared_evidence": 0, "entries_assessed": 0,
                         "omitted_entries": 0, "omitted_proofs": 0, **{status: 0 for status in STATUSES}},
              "bytes_read": 0, "output_truncated": False, "support_replay_complete": False,
              "inputs_sha256": None, "observed_sha256": None,
              "safety": ["hash_equality_is_not_semantic_sufficiency", "applicability_is_not_approval",
                         "no_evidence_array_means_coverage_not_declared", "inputs_sha256_is_not_a_cache_key",
                         "omission_or_truncation_is_never_complete_support"]}
    if pack["pack_status"] in {"invalid_memory", "missing_memory"} or pack["binding"]["status"] != "verified":
        return _fit(result, max_output_bytes)
    reader = continuity.BoundedReader(root, max_file_bytes, max_total_bytes)
    inputs = [pack["memory_sha256"], pack["dependency_sha256"]]
    complete = True
    for item in pack["items"]:
        if not item["applicable"]:
            continue
        proof = {"group": item["group"], "slot": item["slot"], "record_id": item["record_id"],
                 "review_pointer": item["review_pointer"], "review_sha256": item["review_sha256"],
                 "evidence_declared": False, "replay_status": "unreadable", "entries": [],
                 "omitted_entries": 0, "counts": {status: 0 for status in STATUSES}}
        inputs.append([item["review_pointer"], item["review_sha256"]])
        result["totals"]["proofs_assessed"] += 1
        try:
            path, _ = continuity.safe_pointer(root, item["review_pointer"])
            raw = reader.read(path)
            record = continuity.strict_json(raw) if _sha(raw) == item["review_sha256"] else None
        except (integrity.IntegrityError, continuity.ReadLimit, OSError, ValueError, UnicodeError):
            record = None
        if not isinstance(record, dict):
            proof["replay_status"] = "stale_or_unreadable_proof"
        elif "evidence" not in record:
            proof["replay_status"] = "not_declared"
        elif not isinstance(record["evidence"], list):
            proof["replay_status"] = "invalid_evidence"
        else:
            proof["evidence_declared"] = True
            result["totals"]["proofs_with_declared_evidence"] += 1
            declared = record["evidence"]
            for index, entry in enumerate(declared[:max_evidence]):
                replayed = replay_entry(root, reader, index, entry)
                proof["entries"].append(replayed)
                proof["counts"][replayed["status"]] += 1
                result["totals"][replayed["status"]] += 1
                result["totals"]["entries_assessed"] += 1
            proof["omitted_entries"] = max(0, len(declared) - max_evidence)
            result["totals"]["omitted_entries"] += proof["omitted_entries"]
            proof["replay_status"] = "complete" if proof["counts"]["valid"] == len(proof["entries"]) \
                and not proof["omitted_entries"] and proof["entries"] else "incomplete"
        complete = complete and proof["replay_status"] == "complete"
        result["proofs"].append(proof)
    result["bytes_read"] = reader.bytes_read
    result["support_replay_complete"] = bool(result["proofs"]) and complete
    result["inputs_sha256"] = _sha(json.dumps(inputs, sort_keys=True).encode())
    # observed_sha256 binds what was actually replayed; it changes when a supporting file changes
    # even though memory and proof bytes (inputs_sha256) do not. Neither is a cache key.
    result["observed_sha256"] = _sha(json.dumps([[p["record_id"], [[e["locator"], e["status"], e["actual_sha256"]]
                                                                     for e in p["entries"]]]
                                                 for p in result["proofs"]], sort_keys=True).encode())
    return _fit(result, max_output_bytes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--memory", default="knowledge-base/_ops/memory/index.json")
    for name, default in (("max-entries", 32), ("max-file-bytes", 262144), ("max-total-bytes", 1048576),
                          ("max-evidence", 64), ("max-output-bytes", 32768)):
        parser.add_argument("--" + name, type=int, default=default)
    args = vars(parser.parse_args())
    try:
        result = audit(**args)
    except ValueError:
        parser.error("limit arguments are outside the supported bounds")
    sys.stdout.write(continuity.encode(result))
    return 2 if result["pack_status"] in {"invalid_memory", "missing_memory"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
