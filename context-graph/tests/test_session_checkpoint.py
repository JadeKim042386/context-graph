"""Local checkpoint persistence and trusted context gate contracts."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/knowledge-engineering/scripts'
sys.path.insert(0, str(SCRIPTS))


def api():
    assert (SCRIPTS / 'session_checkpoint.py').exists(), 'checkpoint implementation missing'
    import session_checkpoint
    return session_checkpoint


def payload(**updates):
    return dict(session_id='session-a', checkpoint_epoch=0, last_event_id='event-1',
                work_status='open', artifacts=[], **updates)


def test_first_compaction_wins_over_close_and_retry(tmp_path):
    cp = api()
    first = cp.checkpoint(tmp_path, 'pre_compact', payload())
    assert first['status'] == 'created'
    assert cp.checkpoint(tmp_path, 'pre_compact', payload())['status'] == 'duplicate'
    close = cp.checkpoint(tmp_path, 'session_end', payload())
    assert close['checkpoint_id'] == first['checkpoint_id']
    assert close['status'] == 'closed'
    assert cp.checkpoint(tmp_path, 'session_end', payload())['status'] == 'duplicate'
    assert len(list(tmp_path.rglob('checkpoint-*.json'))) == 1


def test_end_can_be_first_and_changed_content_is_not_lost(tmp_path):
    cp = api()
    assert cp.checkpoint(tmp_path, 'session_end', payload())['status'] == 'closed'
    second = cp.checkpoint(tmp_path, 'session_end', dict(payload(), work_status='complete', last_event_id='event-2'))
    assert second['created'] is True
    assert len(list(tmp_path.rglob('checkpoint-*.json'))) == 2


def test_post_compact_does_not_increment_twice_or_persist_work(tmp_path):
    cp = api()
    cp.checkpoint(tmp_path, 'pre_compact', payload())
    out = cp.checkpoint(tmp_path, 'post_compact', payload())
    assert out['checkpoint_epoch'] == 1
    again = cp.checkpoint(tmp_path, 'post_compact', payload())
    assert again['checkpoint_epoch'] == 1 and again['status'] == 'duplicate'
    assert cp.checkpoint(tmp_path, 'pre_compact', dict(payload(), checkpoint_epoch=1))['created'] is False
    assert len(list(tmp_path.rglob('checkpoint-*.json'))) == 1


@pytest.mark.parametrize('boundary', ['checkpoint', 'head'])
def test_pending_replays_once_after_crash(tmp_path, monkeypatch, boundary):
    cp = api()
    original = cp.publish
    def crash(path, value):
        if (boundary == 'checkpoint' and path.name.startswith('checkpoint-')) or (boundary == 'head' and path.name == 'head.json'):
            raise OSError('simulated crash')
        return original(path, value)
    monkeypatch.setattr(cp, 'publish', crash)
    with pytest.raises(OSError): cp.checkpoint(tmp_path, 'pre_compact', payload())
    monkeypatch.setattr(cp, 'publish', original)
    result = cp.checkpoint(tmp_path, 'pre_compact', payload())
    assert result['status'] == 'duplicate'
    assert len(list(tmp_path.rglob('checkpoint-*.json'))) == 1
    assert not list(tmp_path.rglob('pending.json'))


def test_raw_transcript_and_raw_identity_are_never_saved(tmp_path):
    cp = api()
    cp.checkpoint(tmp_path, 'pre_compact', payload(transcript='SECRET RAW', prompt='PRIVATE INPUT'))
    content = '\n'.join(p.read_text() for p in tmp_path.rglob('*.json'))
    assert 'SECRET RAW' not in content and 'PRIVATE INPUT' not in content
    assert 'session-a' not in content and 'event-1' not in content


def test_context_gate_requires_trusted_epoch_digest_and_scope():
    cp = api()
    expected = dict(project_id='p', session_id='s', task_id='t', assignment_id='a', role='reader', context_epoch=3, context_digest='a'*64)
    assert cp.context_gate(expected, None)['decision'] == 'bounded_reload'
    assert cp.context_gate(expected, dict(expected, trusted=False))['decision'] == 'bounded_reload'
    assert cp.context_gate(expected, dict(expected, trusted=True))['decision'] == 'in_context'
    for key, value in [('context_epoch', 4), ('context_digest', 'b'*64), ('session_id', 'other'), ('role', 'other')]:
        assert cp.context_gate(expected, dict(expected, trusted=True, **{key:value}))['decision'] == 'bounded_reload'


def test_gate_performs_no_disk_reads(monkeypatch):
    cp = api()
    def forbidden(*a, **k): raise AssertionError('gate read history')
    monkeypatch.setattr(Path, 'read_text', forbidden)
    expected = dict(project_id='p', session_id='s', task_id='t', assignment_id='a', role='r', context_epoch=0, context_digest='a'*64)
    assert cp.context_gate(expected, dict(expected, trusted=True))['decision'] == 'in_context'


def test_same_event_with_different_content_is_conflict(tmp_path):
    cp = api()
    cp.checkpoint(tmp_path, 'pre_compact', payload())
    with pytest.raises(ValueError, match='event_conflict'):
        cp.checkpoint(tmp_path, 'pre_compact', dict(payload(), work_status='complete'))


def test_lifecycle_checkpoint_mode_is_explicit_and_skips_legacy_history(tmp_path, monkeypatch):
    import record_session_event as recorder
    config = {'schema_version': 1, 'enabled': True,
              'project_id': 'PRJ-' + recorder.digest(str(tmp_path))[:16],
              'include_globs': ['knowledge/**'], 'tracked_paths_only': True,
              'capture_content': False, 'capture_commands': False, 'capture_untracked': False}
    path = tmp_path / 'knowledge-base/_ops/session-capture.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    def history_forbidden(*args):
        raise AssertionError('legacy history read')
    monkeypatch.setattr(recorder, 'load_records', history_forbidden)
    with pytest.raises(AssertionError, match='legacy history read'):
        recorder.record_project(tmp_path, 'pre_compact', payload(), True)
    config['checkpoint_mode'] = 'delta-v1'
    path.write_text(json.dumps(config))
    for event in ('pre_compact', 'pre_compact', 'session_end', 'session_end'):
        assert recorder.record_project(tmp_path, event, payload(transcript='RAW NEVER STORE'), True) == 0
    assert len(list(tmp_path.rglob('checkpoint-*.json'))) == 1
    assert not (path.parent / 'session-events.jsonl').exists()
    assert not (path.parent / 'session-proposals').exists()
    assert 'RAW NEVER STORE' not in ''.join(p.read_text() for p in tmp_path.rglob('*.json'))
    # Missing session identity remains an error; hook epoch/event IDs are synthesized.
    assert recorder.record_project(tmp_path, 'pre_compact', {}, False) == 0
    status = json.loads((path.parent / 'session-knowledge-status.json').read_text())
    assert status['ok'] is False and status['reason'] == 'checkpoint_failed'


def test_ask_retrieval_gate_calls_real_context_gate_without_history(tmp_path, monkeypatch):
    sys.path.insert(0, str(SCRIPTS.parents[2] / 'scripts'))
    import ask
    cp = api()
    expected = dict(project_id='p', session_id='s', task_id='t', assignment_id='a', role='r',
                    context_epoch=0, context_digest='a'*64)
    def forbidden(*args, **kwargs):
        raise AssertionError('retrieval gate opened a file')
    monkeypatch.setattr(Path, 'open', forbidden)
    monkeypatch.setattr('builtins.open', forbidden)
    assert ask.retrieval_gate(expected)['decision'] == 'bounded_reload'
    for state in (None, dict(expected, trusted=False), dict(expected, trusted=True, context_epoch=1)):
        assert ask.retrieval_gate(expected, state, context_gate=cp.context_gate)['decision'] == 'bounded_reload'
    result = ask.retrieval_gate(expected, dict(expected, trusted=True), context_gate=cp.context_gate)
    assert result['decision'] == 'in_context' and result['read_bytes'] == 0


def test_session_start_reopens_closed_session_preserving_epoch(tmp_path):
    cp = api()
    cp.checkpoint(tmp_path, 'pre_compact', payload())
    cp.checkpoint(tmp_path, 'post_compact', payload())
    at_epoch_one = dict(payload(), checkpoint_epoch=1, last_event_id='close-1')
    cp.checkpoint(tmp_path, 'session_end', at_epoch_one)
    reopened = cp.checkpoint(tmp_path, 'session_start', dict(at_epoch_one, last_event_id='resume-1'))
    assert reopened['status'] == 'reopened' and reopened['checkpoint_epoch'] == 1
    head = json.loads(next(tmp_path.rglob('head.json')).read_text())
    assert head['closed'] is False and head['awaiting_post'] is False
    assert 'closure' not in head
    following = dict(at_epoch_one, last_event_id='work-2', work_status='complete')
    assert cp.checkpoint(tmp_path, 'pre_compact', following)['created'] is True


@pytest.mark.parametrize('raw', [b'{broken json', b'{"sha256":"wrong"}',
                                b'{"previous":null,"head":null,"checkpoint":null,"delivery":null}'])
def test_corrupt_pending_is_preserved_then_next_checkpoint_proceeds(tmp_path, raw):
    cp = api()
    cp.checkpoint(tmp_path, 'pre_compact', payload())
    head_path = next(tmp_path.rglob('head.json'))
    before = head_path.read_bytes()
    pending = head_path.parent / 'pending.json'
    pending.write_bytes(raw)
    request = dict(payload(), last_event_id='new-work', work_status='complete')
    result = cp.checkpoint(tmp_path, 'pre_compact', request)
    assert result['status'] == 'pending_invalid' and result['created'] is False
    import hashlib
    quarantine = head_path.parent / ('pending-invalid-' + hashlib.sha256(raw).hexdigest() + '.json')
    assert quarantine.read_bytes() == raw and not pending.exists()
    assert head_path.read_bytes() == before
    assert cp.checkpoint(tmp_path, 'pre_compact', request)['created'] is True
    assert quarantine.read_bytes() == raw


def test_realistic_hook_payload_runs_full_checkpoint_lifecycle(tmp_path):
    import hashlib
    import os
    import subprocess
    root = tmp_path.resolve()
    ops = root / 'knowledge-base/_ops'
    ops.mkdir(parents=True)
    (ops / 'session-capture.json').write_text(json.dumps({
        'schema_version': 1, 'enabled': True, 'checkpoint_mode': 'delta-v1',
        'project_id': 'PRJ-' + hashlib.sha256(str(root).encode()).hexdigest()[:16],
        'include_globs': ['knowledge/**'], 'tracked_paths_only': True,
        'capture_content': False, 'capture_commands': False, 'capture_untracked': False}))
    realistic = {'session_id': 'b4cadff7-3851-4a48-8eed-467bfc84e521', 'cwd': str(root),
                 'transcript_path': '/private/never-read-transcript.jsonl', 'source': 'startup'}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    cli = SCRIPTS / 'record_session_event.py'
    for event in ('session_start', 'pre_compact', 'pre_compact', 'post_compact', 'post_compact',
                  'session_end', 'session_end', 'session_start'):
        response = subprocess.run([sys.executable, '-B', str(cli), 'record', '--root', str(root),
                                   '--event', event, '--compile-proposal'], input=json.dumps(realistic),
                                  capture_output=True, text=True, cwd=root, env=env)
        assert response.returncode == 0 and response.stdout == '' and response.stderr == ''
        latest = json.loads((ops / 'session-knowledge-status.json').read_text())
        assert latest['ok'] is True, latest
    head = json.loads(next(ops.rglob('head.json')).read_text())
    assert head['checkpoint_epoch'] == 1 and head['closed'] is False
    assert 'closure' not in head
    assert len(list(ops.rglob('checkpoint-*.json'))) == 1
    assert not (ops / 'session-events.jsonl').exists()
    assert not (ops / 'session-proposals').exists()
    stored = ''.join(p.read_text() for p in ops.rglob('*.json'))
    assert 'never-read-transcript' not in stored and realistic['session_id'] not in stored
