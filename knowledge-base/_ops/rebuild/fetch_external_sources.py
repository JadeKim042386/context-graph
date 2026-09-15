"""Fetch one bounded batch of external URL HEAD metadata with stdlib urllib."""

import argparse
import hashlib
import ipaddress
import json
import socket
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "external-source-manifest.json"
RESULTS = HERE / "external-fetch-results.json"
USER_AGENT = "ContextGraphKnowledgeVerifier/1.1 (metadata-only; respects robots and rate limits)"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json,application/pdf,image/*;q=0.8,*/*;q=0.5",
    "Accept-Encoding": "identity",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def public_host(url):
    host = urlsplit(url).hostname
    if not host:
        return False, "missing_host"
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError as error:
        return False, f"dns_error:{type(error).__name__}:{error}"
    for address in addresses:
        try:
            if not ipaddress.ip_address(address).is_global:
                return False, f"non_public_address:{address}"
        except ValueError:
            return False, f"invalid_address:{address}"
    return True, None


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed, error = public_host(newurl)
        if not allowed:
            raise URLError(f"unsafe_redirect:{error}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


SAFE_OPENER = build_opener(SafeRedirectHandler())


def safe_open(request, timeout):
    return SAFE_OPENER.open(request, timeout=timeout)


def retry_delay(headers, attempt):
    raw = headers.get("Retry-After") if headers else None
    if raw:
        try:
            return min(8.0, max(0.0, float(raw)))
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
                return min(8.0, max(0.0, seconds))
            except (TypeError, ValueError):
                pass
    return min(4.0, float(2 ** attempt))


def network_error_class(error):
    text = f"{type(error).__name__}:{error}".lower()
    if "gaierror" in text or "name or service" in text or "nodename nor servname" in text:
        return "dns_resolution_retryable"
    if "timed out" in text or "timeout" in text:
        return "timeout_retryable"
    if "connection refused" in text or "errno 61" in text:
        return "connection_refused_retryable"
    if "unsafe_redirect" in text or "non_public_address" in text:
        return "network_policy_nonretryable"
    return "network_other_retryable"


def robots_check(url, timeout):
    split = urlsplit(url)
    robots_url = urlunsplit((split.scheme, split.netloc, "/robots.txt", "", ""))
    allowed, error = public_host(robots_url)
    if not allowed:
        return "unavailable_abstain", error
    request = Request(robots_url, method="GET", headers=REQUEST_HEADERS)
    try:
        with safe_open(request, timeout) as response:
            payload = response.read(262145)
            if len(payload) > 262144:
                return "unavailable_abstain", "robots_too_large"
            parser = robotparser.RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(payload.decode("utf-8", errors="replace").splitlines())
            return ("allowed", None) if parser.can_fetch(USER_AGENT, url) else ("disallowed", "robots_disallow")
    except HTTPError as exc:
        if exc.code in {404, 410}:
            return "not_found_allow", None
        if exc.code in {401, 403}:
            return "disallowed", f"robots_http_{exc.code}"
        if exc.code in {429, 500, 502, 503, 504}:
            return "rate_limited_abstain", f"robots_http_{exc.code}"
        return "unavailable_abstain", f"robots_http_{exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        return "unavailable_abstain", f"robots_{network_error_class(exc)}"


def extraction_format(content_type):
    value = (content_type or "").lower()
    for marker, name in (
        ("text/html", "html"), ("application/json", "json"),
        ("application/pdf", "pdf"), ("image/", "image"),
        ("video/", "video"), ("audio/", "audio"), ("text/", "text"),
    ):
        if marker in value:
            return name
    return "unknown"


def header_metadata(headers):
    selected = {}
    for name in ("Content-Type", "Content-Length", "Last-Modified", "ETag", "License", "Rights", "Link", "Retry-After"):
        value = headers.get(name)
        if value is not None:
            selected[name.lower().replace("-", "_")] = value
    explicit = selected.get("license") or selected.get("rights")
    link = selected.get("link", "")
    if not explicit and 'rel="license"' in link.lower():
        explicit = link
    return selected, ("verified-explicit-http-header" if explicit else "unverified"), explicit


def request_metadata(url, method, timeout, attempts):
    """Return response metadata only; never retain or hash a response body."""
    headers = dict(REQUEST_HEADERS)
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    retryable_http = {403, 429, 500, 502, 503, 504}
    for attempt in range(3):
        request = Request(url, method=method, headers=headers)
        try:
            with safe_open(request, timeout) as response:
                selected, rights_status, license_evidence = header_metadata(response.headers)
                attempts.append({
                    "method": method,
                    "attempt": attempt + 1,
                    "http_status": response.status,
                    "error_class": None,
                    "wait_seconds": 0.0,
                })
                return {
                    "ok": True,
                    "http_status": response.status,
                    "final_url": response.geturl(),
                    "headers": selected,
                    "fetch_status": "metadata_fetched",
                    "fetch_error": None,
                    "network_error_class": None,
                    "extraction_format": extraction_format(selected.get("content_type")),
                    "rights_status": rights_status,
                    "license_evidence": license_evidence,
                }
        except HTTPError as exc:
            selected, rights_status, license_evidence = header_metadata(exc.headers or {})
            try:
                error_url = exc.geturl()
            except (AttributeError, KeyError):
                error_url = url
            wait = retry_delay(exc.headers, attempt) if exc.code in retryable_http and attempt < 2 else 0.0
            attempts.append({
                "method": method,
                "attempt": attempt + 1,
                "http_status": exc.code,
                "error_class": f"http_{exc.code}",
                "wait_seconds": wait,
            })
            if wait:
                time.sleep(wait)
                continue
            return {
                "ok": False,
                "http_status": exc.code,
                "final_url": error_url,
                "headers": selected,
                "fetch_status": "rate_limited" if exc.code in {429, 503} else "http_error",
                "fetch_error": f"HTTPError:{exc.code}:{exc.reason}",
                "network_error_class": None,
                "extraction_format": extraction_format(selected.get("content_type")),
                "rights_status": rights_status,
                "license_evidence": license_evidence,
            }
        except (URLError, TimeoutError, OSError) as exc:
            error_class = network_error_class(exc)
            retryable = error_class.endswith("_retryable") and error_class != "network_policy_nonretryable"
            wait = min(4.0, float(2 ** attempt)) if retryable and attempt < 2 else 0.0
            attempts.append({
                "method": method,
                "attempt": attempt + 1,
                "http_status": None,
                "error_class": error_class,
                "wait_seconds": wait,
            })
            if wait:
                time.sleep(wait)
                continue
            return {
                "ok": False,
                "http_status": None,
                "final_url": None,
                "headers": {},
                "fetch_status": "failed",
                "fetch_error": f"{type(exc).__name__}:{exc}",
                "network_error_class": error_class,
                "extraction_format": "unknown",
                "rights_status": "unverified",
                "license_evidence": None,
            }
    raise AssertionError("bounded metadata retry loop exhausted without a result")


def fetch_recovery(record, timeout, batch_id):
    observed_at = now()
    attempts = []
    base = {
        "stable_id": record["stable_id"],
        "url": record["url"],
        "first_reference": record["first_reference"],
        "method": "HEAD",
        "robots_outcome": "not_checked",
        "http_status": None,
        "final_url": None,
        "redirects": [],
        "headers": {},
        "fetch_status": "failed",
        "fetch_error": None,
        "content_sha256": None,
        "extraction_format": "unknown",
        "rights_status": "unverified",
        "license_evidence": None,
        "fallback_used": None,
        "network_error_class": None,
        "attempt_count": 0,
        "attempts": attempts,
        "recovery_status": "unresolved",
        "provenance": {
            "activity_id": batch_id,
            "agent": "knowledge-engineer",
            "method": "bounded urllib metadata recovery; HEAD then robots-approved GET Range fallback; no response body retained",
            "observed_at": observed_at,
            "inventory_snapshot_sha256": record["provenance"]["inventory_snapshot_sha256"],
            "network_used": True,
        },
    }

    allowed = False
    host_error = None
    for attempt in range(3):
        allowed, host_error = public_host(record["url"])
        if allowed:
            break
        error_class = network_error_class(RuntimeError(host_error))
        retryable = error_class == "dns_resolution_retryable"
        wait = min(4.0, float(2 ** attempt)) if retryable and attempt < 2 else 0.0
        attempts.append({
            "method": "DNS",
            "attempt": attempt + 1,
            "http_status": None,
            "error_class": error_class,
            "wait_seconds": wait,
        })
        if wait:
            time.sleep(wait)
    if not allowed:
        base.update({
            "fetch_error": host_error,
            "network_error_class": network_error_class(RuntimeError(host_error)),
            "attempt_count": len(attempts),
        })
        return base

    result = request_metadata(record["url"], "HEAD", timeout, attempts)
    if not result["ok"] and result["http_status"] in {403, 405}:
        robots_outcome, robots_error = robots_check(record["url"], timeout)
        base["robots_outcome"] = robots_outcome
        if robots_outcome in {"allowed", "not_found_allow"}:
            base["fallback_used"] = "GET-range-metadata"
            result = request_metadata(record["url"], "GET", timeout, attempts)
        elif robots_error:
            result["fetch_error"] = f"{result['fetch_error']};{robots_error}"

    base.update(result)
    base["attempt_count"] = len(attempts)
    base["redirects"] = (
        [record["url"], result["final_url"]]
        if result.get("final_url") and result["final_url"] != record["url"] else []
    )
    base["recovery_status"] = "recovered" if result["ok"] else "unresolved"
    return base


def fetch(record, timeout, batch_id):
    observed_at = now()
    base = {
        "stable_id": record["stable_id"],
        "url": record["url"],
        "first_reference": record["first_reference"],
        "method": "HEAD",
        "robots_outcome": "not_checked_metadata_only",
        "http_status": None,
        "final_url": None,
        "redirects": [],
        "headers": {},
        "fetch_status": "failed",
        "fetch_error": None,
        "content_sha256": None,
        "extraction_format": "unknown",
        "rights_status": "unverified",
        "license_evidence": None,
        "provenance": {
            "activity_id": batch_id,
            "agent": "knowledge-engineer",
            "method": "stdlib urllib HEAD metadata only; no response body retained",
            "observed_at": observed_at,
            "inventory_snapshot_sha256": record["provenance"]["inventory_snapshot_sha256"],
            "network_used": True,
        },
    }
    allowed, error = public_host(record["url"])
    if not allowed:
        base["fetch_error"] = error
        return base
    request = Request(record["url"], method="HEAD", headers=REQUEST_HEADERS)
    try:
        with safe_open(request, timeout=timeout) as response:
            headers, rights_status, license_evidence = header_metadata(response.headers)
            final_url = response.geturl()
            base.update({
                "http_status": response.status,
                "final_url": final_url,
                "redirects": [record["url"], final_url] if final_url != record["url"] else [],
                "headers": headers,
                "fetch_status": "metadata_fetched",
                "extraction_format": extraction_format(headers.get("content_type")),
                "rights_status": rights_status,
                "license_evidence": license_evidence,
            })
    except HTTPError as exc:
        headers, rights_status, license_evidence = header_metadata(exc.headers)
        base.update({
            "http_status": exc.code,
            "final_url": exc.geturl(),
            "headers": headers,
            "fetch_status": "rate_limited" if exc.code in {429, 503} else "http_error",
            "fetch_error": f"HTTPError:{exc.code}:{exc.reason}",
            "extraction_format": extraction_format(headers.get("content_type")),
            "rights_status": rights_status,
            "license_evidence": license_evidence,
        })
    except (URLError, TimeoutError, OSError) as exc:
        base["fetch_error"] = f"{type(exc).__name__}:{exc}"
    return base


def select_recovery_records(records, limit=10):
    records = sorted(records, key=lambda record: record["stable_id"])
    chosen = []
    chosen_ids = set()

    def take(predicate, count):
        for record in records:
            if len([item for item in chosen if predicate(item)]) >= count:
                break
            if record["stable_id"] not in chosen_ids and predicate(record):
                chosen.append(record)
                chosen_ids.add(record["stable_id"])

    take(lambda record: record.get("fetch_status") == "http_error" and record.get("http_status") == 403, 4)
    take(lambda record: record.get("fetch_status") == "http_error" and record.get("http_status") == 405, 2)
    take(lambda record: record.get("fetch_status") == "failed" and "dns" in (record.get("fetch_error") or "").lower(), 2)
    take(lambda record: record.get("fetch_status") == "failed" and "timeout" in (record.get("fetch_error") or "").lower(), 1)
    take(lambda record: record.get("fetch_status") == "failed" and "refused" in (record.get("fetch_error") or "").lower(), 1)

    for record in records:
        if len(chosen) >= min(limit, 10):
            break
        if record["stable_id"] not in chosen_ids and record.get("fetch_status") in {"http_error", "failed"}:
            chosen.append(record)
            chosen_ids.add(record["stable_id"])
    return chosen[:min(limit, 10)]


def sync_manifest(manifest, output):
    for manifest_key, batch_key in (("records", "batches"), ("media_records", "media_batches"), ("records", "retry_batches"), ("records", "recovery_batches")):
        latest = {}
        for batch in output.get(batch_key, []):
            for result in batch["records"]:
                latest[result["stable_id"]] = result
        for record in manifest[manifest_key]:
            result = latest.get(record["stable_id"])
            if not result:
                continue
            record.update({
                "fetch_status": result["fetch_status"],
                "http_status": result["http_status"],
                "fetch_error": result["fetch_error"],
                "content_sha256": result["content_sha256"],
                "extraction_format": result["extraction_format"],
                "rights_status": result["rights_status"],
                "accessed_at": result["provenance"]["observed_at"],
                "final_url": result["final_url"],
                "redirects": result["redirects"],
                "robots_outcome": result["robots_outcome"],
                "metadata_headers": result["headers"],
                "license_evidence": result["license_evidence"],
                "external_fetch_result_locator": {
                    "type": "json-record",
                    "path": "knowledge-base/_ops/rebuild/external-fetch-results.json",
                    "batch_id": result["provenance"]["activity_id"],
                    "stable_id": result["stable_id"],
                },
                "fetch_provenance": result["provenance"],
            })
    manifest["network_fetch_performed"] = any(
        record.get("fetch_status") != "not_started"
        for key in ("records", "media_records") for record in manifest[key]
    )
    manifest["fetch_status_counts"] = dict(sorted(Counter(record["fetch_status"] for record in manifest["records"]).items()))
    manifest["media_fetch_status_counts"] = dict(sorted(Counter(record["fetch_status"] for record in manifest["media_records"]).items()))
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--media", action="store_true")
    parser.add_argument("--final-retry", action="store_true")
    parser.add_argument("--recovery", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {
        "schema_version": 1,
        "results_id": "EXTFETCH-KE-20260914-001",
        "inventory_snapshot_sha256": manifest["inventory_snapshot_sha256"],
        "batches": [],
    }
    output.setdefault("media_batches", [])
    output.setdefault("retry_batches", [])
    output.setdefault("recovery_batches", [])
    batch_key = "recovery_batches" if args.recovery else ("retry_batches" if args.final_retry else ("media_batches" if args.media else "batches"))
    manifest_key = "media_records" if args.media else "records"
    processed = {item["stable_id"] for batch in output[batch_key] for item in batch["records"]}
    if args.recovery:
        if output["recovery_batches"]:
            raise SystemExit("bounded recovery batch already exists")
        selected = select_recovery_records(manifest["records"], limit=min(args.batch_size, 10))
    elif args.final_retry:
        if output["retry_batches"]:
            raise SystemExit("final retry batch already exists")
        unresolved = sorted(
            (record for record in manifest["records"] if record["fetch_status"] in {"not_started", "http_error"}),
            key=lambda record: record["stable_id"],
        )
        not_started = [record for record in unresolved if record["fetch_status"] == "not_started"][:5]
        http_errors = [record for record in unresolved if record["fetch_status"] == "http_error"][:5]
        selected = (not_started + http_errors)[:min(args.batch_size, 10)]
    else:
        selected = [
            record for record in manifest[manifest_key]
            if record["fetch_status"] == "not_started" and record["stable_id"] not in processed
        ][:args.batch_size]
    started_at = now()
    prefix = "ACT-EXTRECOVERY-" if args.recovery else ("ACT-EXTRETRY-" if args.final_retry else ("ACT-MEDIAFETCH-" if args.media else "ACT-EXTFETCH-"))
    batch_id = prefix + hashlib.sha256((started_at + "|" + "|".join(item["stable_id"] for item in selected)).encode()).hexdigest()[:20].upper()
    fetch_function = fetch_recovery if args.recovery else fetch
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda item: fetch_function(item, args.timeout, batch_id), selected))
    counts = dict(sorted({status: sum(item["fetch_status"] == status for item in records) for status in {item["fetch_status"] for item in records}}.items()))
    output[batch_key].append({
        "batch_id": batch_id,
        "started_at": started_at,
        "completed_at": now(),
        "config": {
            "batch_size": min(args.batch_size, 10) if args.recovery else args.batch_size,
            "timeout_seconds": args.timeout,
            "workers": args.workers,
            "method": "HEAD with robots-approved GET Range metadata fallback" if args.recovery else "HEAD",
            "max_attempts_per_method": 3 if args.recovery else 1,
            "retry_after_honored": bool(args.recovery),
            "response_body_retained": False,
        },
        "counts": counts,
        "records": records,
    })
    RESULTS.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_manifest(manifest, output)
    errors = dict(sorted(Counter(
        item["fetch_error"] for item in records if item["fetch_error"]
    ).items()))
    print(json.dumps({"batch_id": batch_id, "selected": len(selected), "counts": counts, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
