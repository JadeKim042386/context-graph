"""Regression gates for provisional knowledge; never capture the real project."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/knowledge-engineering/scripts'
sys.path.insert(0, str(SCRIPTS))
import consolidate_knowledge as ck
import session_knowledge as sk
from test_session_knowledge import _root, _project


def put(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')
    return path


def test_unattributed_never_inherits_an_agent_role(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    for agent, role in [('a', 'analyst'), ('b', 'editor')]:
        sk.open_agent(root, session_id='raw', agent_instance_id=agent, task_id='t', assignment_id=agent, role=role)
    key = sk.event_key([_project(root), 'raw'])
    put(root, 'knowledge-base/_ops/session-events.jsonl', {'record_type': 'SessionLifecycleEvent', 'event_id': 'SEV-u', 'session_id': key})
    sk.merge_session(root)
    item = sk.split(root)['items'][0]
    assert item['role_key'] is None
    assert item['session_state'] in ('unknown', 'ambiguous')


def test_raw_identity_matches_legacy_registry_and_v3_event(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    legacy = hashlib.sha256(b'raw').hexdigest()[:24]
    state = sk.open_agent(root, session_id='raw', session_key=legacy, agent_instance_id='a', task_id='t', assignment_id='x', role='reviewer')
    event = {'record_type': 'SessionLifecycleEvent', 'event_id': 'SEV-a', 'session_id': sk.event_key([_project(root), 'raw']),
             'attribution': {'agent_instance_id': state['agent_key'], 'task_id': state['task_key'], 'assignment_id': state['assignment_key']}}
    put(root, 'knowledge-base/_ops/session-events.jsonl', event)
    sk.merge_session(root)
    assert sk.split(root)['items'][0]['role_key'] == state['role_key']


def test_malformed_overlay_fails_closed(tmp_path):
    p = tmp_path / ck.OVERLAY
    p.parent.mkdir(parents=True)
    p.write_text('{broken\n')
    with pytest.raises(ValueError, match='overlay_invalid'):
        ck.compact(tmp_path)
    assert not (tmp_path / ck.PROJECTION).exists()


def test_unverified_revision_never_excludes_or_claims_replay(tmp_path):
    items = [dict(overlay_id=x, source_event_id='SEV-'+x, source_store='explicit', source_pointer=x+'.json',
                  source_revision_sha256='a'*64, session_key='s', artifact_pointers=[]) for x in ['a', 'b']]
    p = tmp_path / ck.OVERLAY
    p.parent.mkdir(parents=True)
    p.write_text(''.join(json.dumps(x)+'\n' for x in items))
    ck.compact(tmp_path)
    projection = json.loads((tmp_path / ck.PROJECTION).read_text())
    assert projection['excluded_exact_duplicates'] == []
    assert projection['quality']['source_preserved'] is False
    assert projection['items'] == []


def test_unchanged_build_does_not_rewrite_projection(tmp_path):
    p = tmp_path / ck.OVERLAY
    p.parent.mkdir(parents=True)
    p.write_text('')
    ck.compact(tmp_path)
    target = tmp_path / ck.PROJECTION
    before = target.stat().st_mtime_ns
    ck.compact(tmp_path)
    assert target.stat().st_mtime_ns == before


def test_overlay_limit_refuses_whole_batch(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    monkeypatch.setattr(sk, 'MAX_OVERLAY_ITEMS', 1, raising=False)
    p = root / 'knowledge-base/_ops/session-events.jsonl'
    p.write_text(''.join(json.dumps({'record_type':'SessionLifecycleEvent','event_id':f'SEV-{i}','session_id':'s'})+'\n' for i in range(2)))
    result = sk.merge_session(root)
    assert result['status'] == 'overlay_full'
    assert not (root / sk.OVERLAY).exists()


def test_conflicting_artifacts_stay_visible_as_conflict(tmp_path):
    p = tmp_path / ck.OVERLAY
    p.parent.mkdir(parents=True)
    p.write_text(''.join(json.dumps({'overlay_id':x,'source_pointer':x+'.json','source_store':'explicit','session_key':'s',
        'content_fingerprint':x*64,'artifact_pointers':[{'pointer':'knowledge/a.html','sha256':x*64}]})+'\n' for x in ['a','b']))
    ck.compact(tmp_path)
    proposals = [json.loads(x) for x in (tmp_path / ck.PROPOSALS).read_text().splitlines()]
    assert any(x['kind'] == 'conflict' for x in proposals)
    assert json.loads((tmp_path / ck.PROJECTION).read_text())['excluded_exact_duplicates'] == []


def test_decisions_are_an_explicit_api(tmp_path):
    assert callable(getattr(ck, 'record_decision', None))
    with pytest.raises(ValueError):
        ck.record_decision(tmp_path, 'missing', 'accept', 'missing.json', 'a'*64)


def test_hook_failure_is_visible_without_leaking_exception(tmp_path, monkeypatch, capsys):
    import record_session_event as hook
    monkeypatch.setattr(hook, 'load_config', lambda root: {'enabled': True})
    monkeypatch.setattr(hook, 'make_record', lambda *args: {'session_id':'s'})
    monkeypatch.setattr(hook, 'append_locked', lambda *args: None)
    def broken(*args, **kwargs):
        raise ValueError('PRIVATE-SECRET')
    monkeypatch.setattr(sk, 'merge_session', broken)
    assert hook.record_project(tmp_path, 'pre_compact', {'session_id':'raw'}, False) == 0
    output = capsys.readouterr().out
    assert '"ok": false' in output
    assert 'PRIVATE-SECRET' not in output
    assert (tmp_path / 'knowledge-base/_ops/session-knowledge-status.json').is_file()


def verified_fixture(root):
    artifact = root / 'knowledge.txt'
    artifact.write_text('The permitted value is 12 metres.\n')
    h = hashlib.sha256(artifact.read_bytes()).hexdigest()
    rights = put(root, 'source.json', {'record_type':'Source','status':'accepted',
        'content_sha256':h,'rights':{'status':'rights_verified'}})
    rights_hash = hashlib.sha256(rights.read_bytes()).hexdigest()
    rows = []
    for name in ['a', 'b']:
        event = {'event_id':'SEV-'+name,'record_type':'SessionLifecycleEvent','session_id':'s'}
        event_hash = hashlib.sha256((ck.canonical(event)+'\n').encode()).hexdigest()
        put(root, name+'.json', dict(event, record_sha256=event_hash))
        rows.append({'schema_version':1,'record_type':'SessionKnowledgeOverlay','overlay_id':name,
            'source_event_id':'SEV-'+name,'source_store':'explicit','source_pointer':name+'.json',
            'source_revision_sha256':event_hash,'session_key':'s','event_type':'pre_compact',
            'content_fingerprint':'c'*64,'promotion_state':'review_required','status':'provisional',
            'artifact_pointers':[{'pointer':'knowledge.txt','sha256':h,'locator':'line:1',
                                 'quote':'12 metres','rights_ref':{'pointer':'source.json','sha256':rights_hash}}]})
        event.update({k:rows[-1][k] for k in ['content_fingerprint','artifact_pointers','event_type']})
        event_hash = hashlib.sha256((ck.canonical(event)+'\n').encode()).hexdigest()
        put(root, name+'.json', dict(event, record_sha256=event_hash))
        rows[-1]['source_revision_sha256'] = event_hash
    p = root / ck.OVERLAY
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(x)+'\n' for x in rows))
    context = {'root':root,'policy':{'revision':1,'roles':{'reviewer':{'scope_ids':['s']}}},
       'binding':{'task_scope_ids':['s'],'assignment_scope_ids':['s']},
       'session_role':'reviewer','agent_role':'reviewer',
       'catalog':{'artifacts':{p:{'scope_ids':['s']} for p in ['a.json','b.json','knowledge.txt','source.json']}}}
    return rows, context


def approve(root, proposal, outcome='accept', name='review.json'):
    proof = {'id':'DEC-'+name,'record_type':'Decision','status':'accepted',
             'provenance':{'agent':'configured-curator'},
             'consolidation_proposal_sha256':ck.digest(ck._base_proposal(proposal))}
    path = put(root, name, proof)
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    policy = root / ck.REVIEW_POLICY
    refs = json.loads(policy.read_text())['approved_review_refs'] if policy.exists() else []
    put(root, str(ck.REVIEW_POLICY), {'approved_review_refs':refs+[{'pointer':name,'sha256':h}]})
    return ck.record_decision(root, proposal['proposal_id'], outcome, name, h)


def test_review_is_durable_idempotent_and_bound_to_candidates(tmp_path):
    rows, context = verified_fixture(tmp_path)
    ck.compact(tmp_path, context)
    p = ck.read_jsonl(tmp_path / ck.PROPOSALS)[0]
    assert p['kind'] == 'exact_duplicate'
    assert len(json.loads((tmp_path / ck.PROJECTION).read_text())['items']) == 2
    first = approve(tmp_path, p)
    assert approve(tmp_path, p)['status'] == 'duplicate'
    ck.compact(tmp_path, context)
    d = json.loads((tmp_path / ck.PROJECTION).read_text())
    assert len(d['items']) == len(d['excluded_provenance']) == 1
    assert d['quality']['source_preserved'] is True
    assert ck.read_jsonl(tmp_path / ck.PROPOSALS)[0]['decision_state'] == 'accept'
    assert first['decision_id'] in ck.read_jsonl(tmp_path / ck.PROPOSALS)[0]['decision_refs']
    rows[1]['source_event_id'] = 'SEV-changed'
    (tmp_path / ck.OVERLAY).write_text(''.join(json.dumps(x)+'\n' for x in rows))
    ck.compact(tmp_path, context)
    assert json.loads((tmp_path / ck.PROJECTION).read_text())['excluded_exact_duplicates'] == []


def test_conflicting_review_decisions_are_both_preserved(tmp_path):
    _, context = verified_fixture(tmp_path)
    ck.compact(tmp_path, context)
    p = ck.read_jsonl(tmp_path / ck.PROPOSALS)[0]
    approve(tmp_path, p, 'accept')
    approve(tmp_path, p, 'reject', 'reject.json')
    ck.compact(tmp_path, context)
    assert len(ck.read_jsonl(tmp_path / ck.DECISIONS)) == 2
    assert ck.read_jsonl(tmp_path / ck.PROPOSALS)[0]['decision_state'] == 'conflict'
    assert json.loads((tmp_path / ck.PROJECTION).read_text())['excluded_exact_duplicates'] == []


@pytest.mark.parametrize('breakage', ['stale','missing','rights','locator'])
def test_incomplete_evidence_is_held(tmp_path, breakage):
    rows, context = verified_fixture(tmp_path)
    if breakage == 'stale':
        (tmp_path / 'knowledge.txt').write_text('The value is now 13 metres.')
    elif breakage == 'missing':
        (tmp_path / 'a.json').unlink()
        (tmp_path / 'b.json').unlink()
    else:
        for row in rows:
            if breakage == 'rights':
                row['artifact_pointers'][0].pop('rights_ref')
            else:
                row['artifact_pointers'][0]['locator'] = 'line:999'
        (tmp_path / ck.OVERLAY).write_text(''.join(json.dumps(x)+'\n' for x in rows))
    ck.compact(tmp_path, context)
    d = json.loads((tmp_path / ck.PROJECTION).read_text())
    assert d['items'] == []
    assert len(d['held_items']) == 2
    assert not any(i['assessment']['eligible'] for i in d['held_items'])


def test_denied_harness_metadata_never_enters_projection(tmp_path):
    _, context = verified_fixture(tmp_path)
    context['catalog']['artifacts']['knowledge.txt']['scope_ids'] = ['foreign']
    ck.compact(tmp_path, context)
    d = json.loads((tmp_path / ck.PROJECTION).read_text())
    assert d['omitted_count'] == 2
    assert not d['items'] and not d['held_items'] and not d['review_queue']
    assert 'knowledge.txt' not in (tmp_path / ck.PROJECTION).read_text()


def test_overlay_cannot_substitute_source_evidence(tmp_path):
    rows, context = verified_fixture(tmp_path)
    rows[0]['session_key'] = 'foreign-session'
    (tmp_path / ck.OVERLAY).write_text(''.join(json.dumps(x)+'\n' for x in rows))
    ck.compact(tmp_path, context)
    d = json.loads((tmp_path / ck.PROJECTION).read_text())
    assert all(i['overlay_id'] != 'a' for i in d['items'])


def test_concurrent_merge_has_no_duplicate_append(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    root = _root(tmp_path, monkeypatch)
    put(root, 'knowledge-base/_ops/session-events.jsonl', {'record_type':'SessionLifecycleEvent','event_id':'SEV-one','session_id':'s'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sk.merge_session(root), range(2)))
    assert sorted(r['merged_count'] for r in results) == [0, 1]
    assert len(sk.split(root)['items']) == 1


def test_failed_projection_publication_preserves_previous_bytes(tmp_path, monkeypatch):
    import session_storage
    _, context = verified_fixture(tmp_path)
    ck.compact(tmp_path, context)
    original = (tmp_path / ck.PROJECTION).read_bytes()
    (tmp_path / 'knowledge.txt').write_text('changed')
    real_replace = session_storage.os.replace
    def fail_projection(src, dst):
        if Path(dst).name == ck.PROJECTION.name:
            raise OSError('simulated interrupted publication')
        return real_replace(src, dst)
    monkeypatch.setattr(session_storage.os, 'replace', fail_projection)
    with pytest.raises(OSError):
        ck.compact(tmp_path, context)
    assert (tmp_path / ck.PROJECTION).read_bytes() == original


def test_emitted_records_validate_schemas(tmp_path, monkeypatch):
    import jsonschema
    rows, context = verified_fixture(tmp_path)
    ck.compact(tmp_path, context)
    proposal = ck.read_jsonl(tmp_path / ck.PROPOSALS)[0]
    approve(tmp_path, proposal)
    ck.compact(tmp_path, context)
    samples = {'session-knowledge-overlay':rows,
               'consolidation-proposal':ck.read_jsonl(tmp_path / ck.PROPOSALS),
               'consolidation-decision':ck.read_jsonl(tmp_path / ck.DECISIONS),
               'consolidated-knowledge-projection':[json.loads((tmp_path / ck.PROJECTION).read_text())]}
    root = _root(tmp_path, monkeypatch)
    samples['session-agent-state'] = [sk.open_agent(root, session_id='raw', role='reviewer')]
    import record_session_event as hook
    import time
    hook._step_status(root, 'merge', time.perf_counter(), False, 'overlay_invalid')
    samples['session-knowledge-status'] = [json.loads((root / 'knowledge-base/_ops/session-knowledge-status.json').read_text())]
    for name, records in samples.items():
        schema = json.loads((SCRIPTS.parent / 'schemas' / (name+'.schema.json')).read_text())
        for record in records:
            jsonschema.Draft202012Validator(schema).validate(record)
