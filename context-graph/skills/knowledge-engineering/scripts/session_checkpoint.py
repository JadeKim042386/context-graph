#!/usr/bin/env python3
"""Explicit, project-local provisional checkpoints; never promotes canonical memory.

API callers supply stable event IDs and epochs. context_gate's second argument
is trusted launcher state, NOT model/tool JSON or a self-asserted permission.
The gate only suppresses duplicate context delivery; it grants no read access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from session_storage import atomic_write, locked, safe_path

STORE = 'knowledge-base/_ops/session-checkpoints'
LIMIT = 262144
HEX = re.compile(r'[0-9a-f]{64}')
ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
EVENTS = {'session_start', 'pre_compact', 'post_compact', 'session_end'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def sealed(value):
    return dict(value, sha256=digest(value))


def read(path):
    if path.is_symlink():
        raise ValueError('unsafe_path')
    if not path.exists():
        return None
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('checkpoint_limit')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('sha256') != digest({k:v for k,v in value.items() if k != 'sha256'}):
        raise ValueError('checkpoint_integrity')
    return value


def publish(path, value):
    """Atomic replace with file and directory durability; immutable callers compare first."""
    atomic_write(path, encoded(value), max_bytes=LIMIT)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def immutable(path, value):
    old = read(path)
    if old is not None and old != value:
        raise ValueError('checkpoint_conflict')
    if old is None:
        publish(path, value)


def _quarantine_pending(directory):
    path = directory / 'pending.json'
    if path.is_symlink():
        raise ValueError('unsafe_path')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            sha.update(chunk)
    target = directory / ('pending-invalid-' + sha.hexdigest() + '.json')
    # Never overwrite an earlier quarantined artifact, even if hashes match.
    if target.exists() or target.is_symlink():
        raise ValueError('checkpoint_quarantine_exists')
    os.rename(path, target)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return 'pending_invalid'


def _recover(directory):
    path = directory / 'pending.json'
    if path.is_symlink():
        raise ValueError('unsafe_path')
    try:
        pending = read(path)
        if pending is None:
            return
        if set(pending) != {'previous', 'head', 'checkpoint', 'delivery', 'sha256'}:
            raise ValueError('checkpoint_integrity')
        if pending['previous'] is not None and (not isinstance(pending['previous'], str) or not HEX.fullmatch(pending['previous'])):
            raise ValueError('checkpoint_integrity')
        for kind in ('head', 'checkpoint', 'delivery'):
            item = pending[kind]
            if kind == 'checkpoint' and item is None:
                continue
            if not isinstance(item, dict) or item.get('sha256') != digest({k:v for k,v in item.items() if k != 'sha256'}):
                raise ValueError('checkpoint_integrity')
            if kind != 'head':
                identifier = item.get(kind + '_id')
                if not isinstance(identifier, str) or not HEX.fullmatch(identifier):
                    raise ValueError('checkpoint_integrity')
        required_head = {'schema_version', 'session_id', 'checkpoint_epoch', 'checkpoint_id',
                         'context_digest', 'last_event_id', 'content', 'awaiting_post', 'closed', 'sha256'}
        if not required_head.issubset(pending['head']):
            raise ValueError('checkpoint_integrity')
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return _quarantine_pending(directory)
    head = read(directory / 'head.json')
    if (head or {}).get('sha256') not in {pending['previous'], pending['head']['sha256']}:
        raise ValueError('checkpoint_recovery_conflict')
    for kind, key in [('checkpoint', 'checkpoint_id'), ('delivery', 'delivery_id')]:
        item = pending[kind]
        if item is not None:
            identifier = item.get(key)
            if not isinstance(identifier, str) or not HEX.fullmatch(identifier):
                raise ValueError('checkpoint_integrity')
            if item.get('sha256') != digest({k:v for k,v in item.items() if k != 'sha256'}):
                raise ValueError('checkpoint_integrity')
            immutable(directory / f'{kind}-{identifier}.json', item)
    publish(directory / 'head.json', pending['head'])
    (directory / 'pending.json').unlink()
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _filtered(root, payload):
    session = payload.get('session_id')
    event = payload.get('last_event_id')
    if not isinstance(session, str) or not ID.fullmatch(session) or not isinstance(event, str) or not ID.fullmatch(event):
        raise ValueError('explicit_identity_required')
    epoch = payload.get('checkpoint_epoch')
    if type(epoch) is not int or not 0 <= epoch <= 2147483647:
        raise ValueError('invalid_epoch')
    status = payload.get('work_status', 'unknown')
    if status not in {'unknown', 'open', 'complete', 'blocked', 'partial'}:
        raise ValueError('invalid_work_status')
    unresolved = payload.get('unresolved_count', 0)
    if type(unresolved) is not int or not 0 <= unresolved <= 10000:
        raise ValueError('invalid_work_status')
    attribution = {}
    for key in ('agent_instance_id', 'task_id', 'assignment_id', 'role'):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not ID.fullmatch(value)):
            raise ValueError('invalid_attribution')
        attribution[key] = digest([str(root), key, value]) if value is not None else None
    if any(v is not None for v in attribution.values()) and not all(v is not None for v in attribution.values()):
        raise ValueError('incomplete_attribution')
    artifacts = payload.get('artifacts', [])
    if not isinstance(artifacts, list) or len(artifacts) > 100:
        raise ValueError('artifact_limit')
    filtered = {}
    from record_session_event import UNSAFE_PATH
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise ValueError('invalid_artifact')
        path, revision = item['path'], item['sha256']
        if not isinstance(path, str) or not path or len(path) > 480 or '\\' in path or path.startswith('.') or UNSAFE_PATH.search(path):
            raise ValueError('unsafe_artifact')
        safe_path(root, path)
        if not isinstance(revision, str) or not HEX.fullmatch(revision):
            raise ValueError('invalid_artifact')
        if path in filtered and filtered[path] != revision:
            raise ValueError('artifact_conflict')
        filtered[path] = revision
    content = dict(attribution=attribution, work_status=status, unresolved_count=unresolved,
                   artifacts=[{'path':p, 'sha256':h} for p,h in sorted(filtered.items())])
    # Payload metadata is provisional. Hash equality does not prove artifact bytes or approval.
    return digest([str(root), session]), epoch, digest(event), content


def current_epoch(root, session_id, event=None):
    """Read only the selected session head; never scan a journal or directory.

    A repeated post_compact addresses its completed epoch, not the newly opened
    one. Explicit API callers can still supply an epoch for out-of-order replay.
    """
    root = Path(root).resolve()
    if not isinstance(session_id, str) or not ID.fullmatch(session_id):
        raise ValueError('explicit_identity_required')
    session = digest([str(root), session_id])
    head = read(safe_path(root, f'{STORE}/{session}/head.json'))
    if head is None:
        return 0
    epoch = head.get('checkpoint_epoch')
    if event == 'post_compact' and not head.get('awaiting_post'):
        epoch = head.get('last_post_epoch', epoch)
    if type(epoch) is not int or not 0 <= epoch <= 2147483647:
        raise ValueError('invalid_epoch')
    return epoch


def checkpoint(root, event, payload):
    """Persist first pre_compact/end, replay duplicates, retain closure without work copies.

    This explicit API is caller-activated. No transcript parsing, global state,
    history scan, proposal rebuild, or canonical/memory update occurs here.
    """
    root = Path(root).resolve()
    if not root.is_dir() or event not in EVENTS or not isinstance(payload, dict):
        raise ValueError('invalid_checkpoint_request')
    session, epoch, last_event, content = _filtered(root, payload)
    directory = safe_path(root, f'{STORE}/{session}')
    content_digest = digest(content)
    with locked(root, 'checkpoint-' + session):
        directory.mkdir(parents=True, exist_ok=True)
        if _recover(directory) == 'pending_invalid':
            return dict(status='pending_invalid', created=False, reason='pending_quarantined')
        old = read(directory / 'head.json')
        head = {k:v for k,v in (old or {}).items() if k != 'sha256'} or dict(
            schema_version=1, session_id=session, checkpoint_epoch=0, checkpoint_id=None,
            context_digest=None, last_event_id=None, content=None, awaiting_post=False, closed=False)
        reopening = event == 'session_start' and head['closed']
        delivery_id = digest([session, epoch, event, last_event])
        if reopening:
            # A resumed host may reuse its startup identity. Closed-head revision
            # distinguishes a real reopen from an already completed start retry.
            delivery_id = digest([session, epoch, event, last_event, old['sha256']])
        previous = read(directory / f'delivery-{delivery_id}.json')
        if previous is not None:
            if previous['context_digest'] != content_digest:
                raise ValueError('event_conflict')
            return dict(status='duplicate', created=False, checkpoint_id=previous['checkpoint_id'],
                        checkpoint_epoch=head['checkpoint_epoch'], context_digest=previous['context_digest'])
        if epoch != head['checkpoint_epoch']:
            raise ValueError('epoch_mismatch')
        record = None
        result_status = 'duplicate'
        if event in {'pre_compact', 'session_end'}:
            if content_digest != head['context_digest']:
                checkpoint_id = digest([session, epoch, content_digest, last_event])
                before = {a['path']:a['sha256'] for a in (head.get('content') or {}).get('artifacts', [])}
                after = {a['path']:a['sha256'] for a in content['artifacts']}
                record = sealed(dict(schema_version=1, record_type='SessionCheckpoint',
                    checkpoint_id=checkpoint_id, session_id=session, checkpoint_epoch=epoch,
                    context_digest=content_digest, last_event_id=last_event,
                    previous_checkpoint_id=head['checkpoint_id'], status='provisional',
                    promotion_state='review_required', work_status=content['work_status'],
                    unresolved_count=content['unresolved_count'], attribution=content['attribution'],
                    artifact_delta=[{'path':p, 'sha256':h} for p,h in sorted(after.items()) if before.get(p) != h],
                    removed_artifact_paths=sorted(before.keys() - after.keys())))
                head.update(checkpoint_id=checkpoint_id, context_digest=content_digest,
                            content=content, last_event_id=last_event)
                result_status = 'created'
            if event == 'pre_compact':
                if head['closed']:
                    raise ValueError('session_closed')
                head['awaiting_post'] = True
            else:
                result_status = 'closed' if not head['closed'] or record else 'duplicate'
                head['closed'] = True
                head['closure'] = dict(checkpoint_id=head['checkpoint_id'], checkpoint_epoch=epoch)
        elif event == 'session_start' and head['closed']:
            head['closed'] = False
            head['awaiting_post'] = False
            head.pop('closure', None)
            result_status = 'reopened'
        elif event == 'post_compact' and head['awaiting_post'] and not head['closed']:
            head['last_post_epoch'] = head['checkpoint_epoch']
            head['checkpoint_epoch'] += 1
            head['awaiting_post'] = False
            result_status = 'advanced'
        delivery = sealed(dict(delivery_id=delivery_id, context_digest=content_digest,
                               checkpoint_id=head['checkpoint_id']))
        pending = sealed(dict(previous=old['sha256'] if old else None, head=sealed(head),
                              checkpoint=record, delivery=delivery))
        publish(directory / 'pending.json', pending)
        _recover(directory)
        return dict(status=result_status, created=record is not None, checkpoint_id=head['checkpoint_id'],
                    checkpoint_epoch=head['checkpoint_epoch'], context_digest=head['context_digest'])


def context_gate(expected, trusted_context=None):
    """Pure delivery gate: both arguments must originate in the trusted harness.

    expected describes CURRENT authorized query dependencies, not a cached past
    digest. A CLI/model cannot mark itself trusted. Missing evidence requests a
    bounded query-scoped reload; this API does not read, authorize, or execute it.
    """
    fallback = dict(decision='bounded_reload', reason='context_not_verified', max_items=32, max_bytes=32768)
    fields = ('project_id', 'session_id', 'task_id', 'assignment_id', 'role', 'context_epoch', 'context_digest')
    if not isinstance(expected, dict) or not isinstance(trusted_context, dict) or trusted_context.get('trusted') is not True:
        return fallback
    if any(not isinstance(expected.get(k), str) or not expected[k] for k in fields[:5]):
        return fallback
    if type(expected.get('context_epoch')) is not int or expected['context_epoch'] < 0:
        return fallback
    if not isinstance(expected.get('context_digest'), str) or not HEX.fullmatch(expected['context_digest']):
        return fallback
    if type(trusted_context.get('context_epoch')) is not int or any(expected[k] != trusted_context.get(k) for k in fields):
        return fallback
    return dict(decision='in_context', reason='trusted_epoch_and_dependencies_match', read_bytes=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--event', choices=sorted(EVENTS), required=True)
    args = parser.parse_args(argv)
    try:
        # Explicit CLI requires project activation; does not initialize or alter it.
        from session_events import binding
        root, _, _, _ = binding(args.root)
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('checkpoint_limit')
        result = checkpoint(root, args.event, json.loads(raw))
    except (ValueError, OSError, TypeError, KeyError):
        result = {'status':'unverified', 'reason':'checkpoint_failed'}
    print(json.dumps(result, sort_keys=True))
    return 2 if result['status'] in {'unverified', 'pending_invalid'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
