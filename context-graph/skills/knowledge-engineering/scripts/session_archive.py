"""Explicit immutable overlay archives, bounded replay and two-phase recovery.

Only operational views move. Source events and canonical records never change.
Call recover/rotate under the session-knowledge lock; readers never repair files.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from session_storage import safe_path, read_jsonl, atomic_write, MAX_BYTES

OVERLAY = 'knowledge-base/_ops/session-knowledge-overlay.jsonl'
DIRECTORY = 'knowledge-base/_ops/session-knowledge-archive'
HEAD = DIRECTORY + '/head.json'
MAX_SEGMENTS = 64
MAX_REPLAY_ITEMS = 50000
MAX_REPLAY_BYTES = 64 * 1024 * 1024


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rows_bytes(rows):
    return b''.join(encode(x) for x in rows)


def head(root):
    p = safe_path(root, HEAD)
    if not p.exists(): return []
    if p.stat().st_size > 262144: raise ValueError('archive_full')
    try:
        rows = json.loads(p.read_bytes())
        if not isinstance(rows, list) or len(rows) > MAX_SEGMENTS * 2: raise ValueError()
        prepared = {}
        for i, row in enumerate(rows):
            if not isinstance(row,dict) or set(row) != {'schema_version','segment_id','segment_sha256','item_count','overlay_sha256_before','overlay_sha256_after','created_at','status'}: raise ValueError()
            if row['schema_version'] != 1 or type(row['item_count']) is not int or not 1 <= row['item_count'] <= 5000: raise ValueError()
            if any(not isinstance(row[k],str) or not re.fullmatch('[0-9a-f]{64}',row[k]) for k in ['segment_id','segment_sha256','overlay_sha256_before','overlay_sha256_after']): raise ValueError()
            if row['status'] == 'prepared':
                if row['segment_id'] in prepared or (i and rows[i-1]['status'] != 'committed'): raise ValueError()
                prepared[row['segment_id']] = row
            elif row['status'] == 'committed':
                if i == 0 or rows[i-1]['status'] != 'prepared' or dict(rows[i-1],status='committed') != row: raise ValueError()
            else: raise ValueError()
        return rows
    except (ValueError,TypeError,KeyError) as exc: raise ValueError('archive_invalid') from exc


def segment(root, entry):
    path = safe_path(root, DIRECTORY+'/'+entry['segment_id']+'.jsonl')
    if not path.is_file() or path.stat().st_size > MAX_BYTES: raise ValueError('archive_invalid')
    raw = path.read_bytes()
    if sha(raw) != entry['segment_sha256']: raise ValueError('archive_conflict')
    rows = read_jsonl(path)
    if len(rows) != entry['item_count'] or any(not isinstance(r.get('overlay_id'),str) for r in rows): raise ValueError('archive_invalid')
    return rows, len(raw)


def read_view(root, include_archive=False):
    entries = head(root)
    archived, ids, total = [], {}, 0
    for entry in entries:
        if entry['status'] != 'prepared': continue
        rows, size = segment(root, entry)
        total += size
        if total > MAX_REPLAY_BYTES or len(archived)+len(rows) > MAX_REPLAY_ITEMS: raise ValueError('archive_full')
        for row in rows:
            identity = row['overlay_id']
            if identity in ids: raise ValueError('archive_conflict')
            ids[identity] = row
            archived.append(dict(row, archive_segment_id=entry['segment_id']))
    active_path = safe_path(root, OVERLAY)
    active = read_jsonl(active_path)
    if entries and entries[-1]['status'] == 'prepared':
        current = sha(active_path.read_bytes() if active_path.exists() else b'')
        if current not in (entries[-1]['overlay_sha256_before'], entries[-1]['overlay_sha256_after']):
            raise ValueError('archive_recovery_conflict')
    kept = []
    for row in active:
        if row.get('overlay_id') in ids:
            if row != ids[row['overlay_id']]: raise ValueError('archive_conflict')
        else: kept.append(row)
    return kept + archived if include_archive else kept


def recover(root):
    entries = head(root)
    # Validate all referenced bytes before mutating the active view.
    active = read_view(root)
    if entries and entries[-1]['status'] == 'prepared':
        pending = entries[-1]
        raw = rows_bytes(active)
        if sha(raw) != pending['overlay_sha256_after']: raise ValueError('archive_recovery_conflict')
        atomic_write(safe_path(root, OVERLAY), raw)
        atomic_write(safe_path(root, HEAD), encode(entries+[dict(pending,status='committed')]))
    return active


def orphan_count(root, entries):
    directory = safe_path(root, DIRECTORY)
    if not directory.exists(): return 0
    known = {r['segment_id']+'.jsonl' for r in entries}
    count = 0
    with os.scandir(directory) as files:
        for index, item in enumerate(files):
            if index >= 256: raise ValueError('archive_full')
            if item.name.endswith('.jsonl') and item.name not in known:
                count += 1
    return count


def rotate(root, states):
    active = recover(root)
    latest = {}
    for state in states:
        for alias in state.get('session_keys',[state.get('session_key')]):
            latest[(alias,state.get('agent_key'),state.get('task_key'),state.get('assignment_key'))] = state.get('state')
    def closed(item):
        session = item.get('session_key')
        # Missing close, any active agent or unknown state prevents session archival.
        values = [v for k,v in latest.items() if k[0] == session]
        return bool(values) and all(v == 'closed' for v in values)
    chosen = [r for r in active if closed(r)]
    if not chosen:
        count = orphan_count(root, head(root))
        return {'status':'unchanged','archived_count':0,'orphan_count':count,
                'reason':'archive_orphan' if count else 'nothing_closed'}
    entries = head(root)
    if len(entries)//2 >= MAX_SEGMENTS: raise ValueError('archive_full')
    raw = rows_bytes(chosen)
    identity = sha(raw)
    relative = DIRECTORY+'/'+identity+'.jsonl'
    path = safe_path(root,relative)
    if path.exists():
        if path.read_bytes() != raw: raise ValueError('archive_conflict')
    else:
        atomic_write(path,raw)  # unreferenced orphan after crash; reuse only identical bytes
    remaining = rows_bytes([r for r in active if not closed(r)])
    overlay_path = safe_path(root,OVERLAY)
    entry = {'schema_version':1,'segment_id':identity,'segment_sha256':sha(raw),'item_count':len(chosen),
        'overlay_sha256_before':sha(overlay_path.read_bytes() if overlay_path.exists() else b''),
        'overlay_sha256_after':sha(remaining),'created_at':datetime.now(timezone.utc).isoformat(), 'status':'prepared'}
    atomic_write(safe_path(root,HEAD),encode(entries+[entry]))
    atomic_write(overlay_path,remaining)
    atomic_write(safe_path(root,HEAD),encode(entries+[entry,dict(entry,status='committed')]))
    return {'status':'rotated','archived_count':len(chosen),'segment_path':relative,'segment_sha256':identity,
            'orphan_count':orphan_count(root, head(root))}
