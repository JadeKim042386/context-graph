#!/usr/bin/env python3
"""Bounded provisional proposals; evidence and decisions never imply canonical promotion."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from session_storage import read_jsonl, safe_path, atomic_write, locked, MAX_BYTES, MAX_ITEMS

OVERLAY = Path('knowledge-base/_ops/session-knowledge-overlay.jsonl')
PROPOSALS = Path('knowledge-base/_ops/consolidation-proposals.jsonl')
PROJECTION = Path('knowledge-base/_ops/rebuild/consolidated-session-knowledge.json')
DECISIONS = Path('knowledge-base/_ops/consolidation-decisions.jsonl')
REVIEW_POLICY = Path('knowledge-base/_ops/consolidation-review-policy.json')


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _bytes(root, pointer):
    path = safe_path(root, pointer)
    if not path.is_file():
        raise ValueError('unlocatable')
    if path.stat().st_size > 262144:
        raise ValueError('evidence_limit')
    return path.read_bytes()


def _fingerprint(item):
    # Same revision alone cannot equate different source/actor/locator scopes.
    return digest({k: item.get(k) for k in ('content_fingerprint', 'artifact_pointers',
        'session_key', 'event_type', 'attribution', 'role_key')})


def assess(root, item, harness_context=None):
    result = {'integrity': 'unverified', 'locator': 'unverified', 'rights': 'unverified',
              'permission': 'unverified', 'eligible': False}
    refs = item.get('artifact_pointers') or []
    # Read grants are checked before source/dependency replay, never inferred from actor labels.
    if harness_context is not None:
        from role_access import authorize, authorize_pointer
        try:
            if Path(harness_context['root']).resolve() != Path(root).resolve():
                raise ValueError('foreign_context')
            authorize(harness_context, action='read')
            pointers = [item.get('source_pointer')] + [r.get('pointer') for r in refs]
            pointers += [r['rights_ref']['pointer'] for r in refs if isinstance(r.get('rights_ref'), dict)]
            if not all(authorize_pointer(harness_context, p) for p in pointers):
                raise ValueError('denied')
            result['permission'] = 'allowed'
        except (ValueError, KeyError, TypeError):
            result['permission'] = 'denied'
            return result
    try:
        # With no harness, only operational pointer integrity is inspected; no knowledge body.
        raw = _bytes(root, item.get('source_pointer', ''))
        expected = item.get('source_revision_sha256')
        if item.get('source_store') == 'explicit':
            event = json.loads(raw)
            unsigned = {k: v for k, v in event.items() if k != 'record_sha256'}
            actual = hashlib.sha256((canonical(unsigned) + '\n').encode()).hexdigest()
            if not expected or event.get('record_sha256') != expected or actual != expected:
                result['integrity'] = 'stale' if expected else 'unverified'
                return result
            if event.get('event_id') != item.get('source_event_id'):
                result['integrity'] = 'stale'
                return result
            bindings = {'session_key': 'session_id', 'attribution': 'attribution',
                        'content_fingerprint': 'content_fingerprint', 'event_type': 'event_type',
                        'artifact_pointers': 'artifact_pointers'}
            if any(item.get(left) != event.get(right) for left, right in bindings.items()):
                result['integrity'] = 'stale'
                return result
        else:
            # Legacy journals have no immutable per-event revision in this boundary.
            result['integrity'] = 'unverified'
            return result
        result['integrity'] = 'valid'
        if result['permission'] != 'allowed' or not refs:
            return result
        for ref in refs:
            body = _bytes(root, ref['pointer'])
            if hashlib.sha256(body).hexdigest() != ref.get('sha256', ref.get('revision_sha256')):
                result['integrity'] = 'stale'
                return result
            rights = ref.get('rights_ref')
            if not isinstance(rights, dict):
                return result
            proof = _bytes(root, rights['pointer'])
            if hashlib.sha256(proof).hexdigest() != rights.get('sha256'):
                return result
            record = json.loads(proof)
            result['rights'] = record.get('rights', {}).get('status', 'unverified')
            if result['rights'] not in ('rights_verified','restricted','unknown','unverified'):
                result['rights'] = 'unverified'
            if (record.get('record_type') not in ('Source', 'Media')
                or record.get('status') != 'accepted'
                or result['rights'] != 'rights_verified'
                or record.get('content_sha256') != ref.get('sha256', ref.get('revision_sha256'))):
                if result['rights'] == 'rights_verified': result['rights'] = 'unverified'
                return result
            from locator_replay import replay
            result['locator'] = replay(body, ref.get('locator'), ref.get('quote'))
            if result['locator'] != 'valid':
                return result
        result.update(locator='valid', rights='rights_verified', eligible=True)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        result['integrity'] = 'unlocatable'
        if str(exc) == 'evidence_limit': result['locator'] = 'oversize'
    return result


def _review_valid(root, proposal_hash, pointer, expected):
    try:
        raw = _bytes(root, pointer)
        policy = json.loads(_bytes(root, REVIEW_POLICY))
        if {'pointer': pointer, 'sha256': expected} not in policy.get('approved_review_refs', []):
            return False
        proof = json.loads(raw)
        return (hashlib.sha256(raw).hexdigest() == expected
                and proof.get('record_type') == 'Decision' and proof.get('status') == 'accepted'
                and proof.get('consolidation_proposal_sha256') == proposal_hash
                and bool(proof.get('id')) and bool(proof.get('provenance')))
    except (ValueError, OSError, TypeError, KeyError):
        return False


def _base_proposal(p):
    return {k: v for k, v in p.items() if k not in ('decision_state', 'decision_refs')}


def _analyse(root, harness_context=None, include_archive=False):
    from session_archive import read_view
    items = read_view(root, include_archive=include_archive)
    visible, assessments, omitted = [], {}, 0
    for item in items:
        if not isinstance(item.get('overlay_id'), str):
            raise ValueError('overlay_invalid')
        state = assess(root, item, harness_context)
        if state['permission'] == 'denied':
            omitted += 1
            continue
        visible.append(item)
        assessments[item['overlay_id']] = state
    if len({i['overlay_id'] for i in visible}) != len(visible):
        raise ValueError('overlay_invalid')
    groups, by_pointer = defaultdict(list), defaultdict(list)
    for item in visible:
        groups[_fingerprint(item)].append(item)
        for ref in item.get('artifact_pointers', []):
            by_pointer[(item.get('session_key'), ref.get('pointer'))].append(item)
    proposals = []
    def proposal(kind, key, group):
        members = sorted({i['overlay_id']: i for i in group}.values(), key=lambda i: i['overlay_id'])
        exact = kind == 'exact_duplicate'
        p = {'schema_version': 1, 'record_type': 'ConsolidationProposal',
             'proposal_id': 'SCP-' + digest([kind, key])[:32], 'kind': kind,
             'candidate_overlay_ids': [i['overlay_id'] for i in members],
             'candidate_sha256': digest(members), 'recommended_representative': members[0]['overlay_id'],
             'action': 'review_merge' if exact else 'retain_separately',
             'confidence': 'unverified', 'reason': kind, 'promotion_state': 'review_required'}
        proposals.append(p)
    for key, group in sorted(groups.items()):
        if len(group) > 1:
            exact = bool(group[0].get('content_fingerprint')) and all(assessments[i['overlay_id']]['eligible'] for i in group)
            proposal('exact_duplicate' if exact else 'possible_overlap', key, group)
    for key, group in sorted(by_pointer.items(), key=lambda pair: str(pair[0])):
        if len({i.get('content_fingerprint') for i in group}) > 1:
            proposal('conflict', key, group)  # candidate conflict, not semantic adjudication
    decisions = read_jsonl(safe_path(root, DECISIONS))
    for p in proposals:
        phash = digest(p)
        related = [d for d in decisions if d.get('proposal_id') == p['proposal_id']]
        valid = [d for d in related if d.get('proposal_sha256') == phash and
                 _review_valid(root, phash, d.get('review_pointer'), d.get('review_sha256'))]
        outcomes = {d.get('outcome') for d in valid}
        p['decision_state'] = ('conflict' if len(outcomes) > 1 else
                               next(iter(outcomes)) if outcomes else 'stale' if related else 'open')
        p['decision_refs'] = sorted(d['decision_id'] for d in valid)
    return items, visible, assessments, proposals, omitted


def _write_plan(root, proposals):
    return atomic_write(safe_path(root, PROPOSALS), ''.join(canonical(p)+'\n' for p in proposals).encode())


def plan(root, harness_context=None, include_archive=False):
    root = Path(root).resolve()
    with locked(root, 'consolidation'):
        items, visible, states, proposals, omitted = _analyse(root, harness_context, include_archive)
        changed = _write_plan(root, proposals)
        return {'status': 'planned', 'proposal_count': len(proposals), 'overlay_count': len(items),
                'omitted_count': omitted, 'path': str(PROPOSALS), 'changed': changed}


def compact(root, harness_context=None, include_archive=False):
    root = Path(root).resolve()
    with locked(root, 'consolidation'):
        items, visible, states, proposals, omitted = _analyse(root, harness_context, include_archive)
        conflicts = {i for p in proposals if p['kind'] == 'conflict' for i in p['candidate_overlay_ids']}
        excluded = set()
        for p in proposals:
            if p['kind'] == 'exact_duplicate' and p['decision_state'] == 'accept' and not conflicts.intersection(p['candidate_overlay_ids']):
                excluded.update(p['candidate_overlay_ids'][1:])
        representatives = [i for i in visible if states[i['overlay_id']]['eligible'] and i['overlay_id'] not in excluded and i['overlay_id'] not in conflicts]
        representative_ids = {i['overlay_id'] for i in representatives}
        projection = {'schema_version': 1, 'record_type': 'ConsolidatedKnowledgeProjection',
            'projection_state': 'generated_not_canonical', 'source_overlay': str(OVERLAY),
            'source_overlay_sha256': digest(visible), 'items': representatives,
            'excluded_exact_duplicates': sorted(excluded),
            'excluded_provenance': [dict(i, assessment=states[i['overlay_id']]) for i in visible if i['overlay_id'] in excluded],
            'held_items': [dict(i, assessment=states[i['overlay_id']]) for i in visible if i['overlay_id'] not in representative_ids and i['overlay_id'] not in excluded],
            'review_queue': proposals, 'omitted_count': omitted,
            'quality': {'source_preserved': omitted == 0 and all(s['integrity'] == 'valid' for s in states.values()),
                        'automatic_promotion': False, 'automatic_deletion': False,
                        'conflicts_retained': not bool(conflicts & excluded), 'semantic_equivalence': 'unverified'}}
        raw = (canonical(projection)+'\n').encode()
        if len(raw) > MAX_BYTES:
            raise ValueError('projection_full')
        _write_plan(root, proposals)
        changed = atomic_write(safe_path(root, PROJECTION), raw)
        return {'status': 'compacted', 'overlay_count': len(items), 'proposal_count': len(proposals),
                'projection_count': len(representatives), 'excluded_duplicate_count': len(excluded),
                'held_count': len(projection['held_items']), 'omitted_count': omitted,
                'projection': str(PROJECTION), 'projection_bytes': len(raw),
                'overlay_bytes': safe_path(root, OVERLAY).stat().st_size if safe_path(root, OVERLAY).exists() else 0,
                'changed': changed}


def record_decision(root, proposal_id, outcome, review_pointer, review_sha256):
    root = Path(root).resolve()
    if outcome not in ('accept', 'reject', 'hold'):
        raise ValueError('decision_invalid')
    with locked(root, 'consolidation'):
        proposals = read_jsonl(safe_path(root, PROPOSALS))
        matches = [p for p in proposals if p.get('proposal_id') == proposal_id]
        if len(matches) != 1:
            raise ValueError('proposal_missing')
        phash = digest(_base_proposal(matches[0]))
        if not _review_valid(root, phash, review_pointer, review_sha256):
            raise ValueError('approval_unverified')
        decision = {'schema_version': 1, 'record_type': 'ConsolidationDecision',
                    'proposal_id': proposal_id, 'proposal_sha256': phash, 'outcome': outcome,
                    'review_pointer': review_pointer, 'review_sha256': review_sha256,
                    'canonical_promotion': False}
        decision['decision_id'] = 'SCD-' + digest(decision)
        path = safe_path(root, DECISIONS)
        rows = read_jsonl(path)
        if decision in rows:
            return {'status': 'duplicate', 'decision_id': decision['decision_id']}
        if len(rows) >= MAX_ITEMS:
            raise ValueError('decision_limit')
        old = path.read_bytes() if path.exists() else b''
        atomic_write(path, old + (canonical(decision)+'\n').encode())
        return {'status': 'recorded', 'decision_id': decision['decision_id']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('command', choices=('plan', 'compact', 'decide'))
    parser.add_argument('--include-archive', action='store_true')
    parser.add_argument('--proposal-id')
    parser.add_argument('--outcome', choices=('accept', 'reject', 'hold'))
    parser.add_argument('--review-pointer')
    parser.add_argument('--review-sha256')
    args = parser.parse_args(argv)
    try:
        result = record_decision(args.root, args.proposal_id, args.outcome, args.review_pointer, args.review_sha256) if args.command == 'decide' else (plan(args.root, include_archive=args.include_archive) if args.command == 'plan' else compact(args.root, include_archive=args.include_archive))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError):
        print(json.dumps({'status': 'blocked', 'reason': 'consolidation_invalid'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
