import json
import sys
from pathlib import Path
import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/knowledge-engineering/scripts'
sys.path.insert(0,str(SCRIPTS))


def fixture(tmp_path):
    source=tmp_path/'context-graph';(source/'.claude-plugin').mkdir(parents=True)
    (source/'.claude-plugin/plugin.json').write_text('{"name":"context-graph","version":"0.9.2"}')
    (source/'scripts').mkdir();(source/'scripts/example.py').write_text('print("fixture")\n')
    (source/'tests/fixtures/sealed_private').mkdir(parents=True)
    (source/'tests/fixtures/sealed_private/gold.json').write_text('PRIVATE_GOLD')
    return source


def test_snapshot_duplicate_changed_revision_and_sealed_exclusion(tmp_path):
    import install_project_payload as tool
    source=fixture(tmp_path)
    first=tool.install(tmp_path)
    assert first['status']=='installed'
    assert tool.install(tmp_path)['status']=='duplicate'
    before=(Path(first['snapshot'])/'manifest.json').read_bytes()
    assert not list(Path(first['snapshot']).rglob('gold.json'))
    (source/'scripts/example.py').write_text('print("new fixture")\n')
    second=tool.install(tmp_path)
    assert second['payload_id']!=first['payload_id']
    assert (Path(first['snapshot'])/'manifest.json').read_bytes()==before
    assert tool.verify(Path(first['snapshot']))['status']=='verified'


def test_snapshot_tamper_never_overwrites(tmp_path):
    import install_project_payload as tool
    fixture(tmp_path);first=tool.install(tmp_path)
    p=Path(first['plugin_root'])/'scripts/example.py';p.write_text('tampered')
    assert tool.verify(Path(first['snapshot']))['status']=='tampered'
    with pytest.raises(ValueError,match='snapshot_conflict'):tool.install(tmp_path)
    assert p.read_text()=='tampered'


def test_snapshot_rejects_symlink_and_validates_manifest(tmp_path):
    import install_project_payload as tool
    import jsonschema
    source=fixture(tmp_path)
    (source/'scripts/link.py').symlink_to(source/'scripts/example.py')
    with pytest.raises(ValueError,match='unsafe_path'):tool.install(tmp_path)
    (source/'scripts/link.py').unlink();result=tool.install(tmp_path)
    manifest=json.loads((Path(result['snapshot'])/'manifest.json').read_bytes())
    schema=json.loads((SCRIPTS.parent/'schemas/project-plugin-manifest.schema.json').read_bytes())
    jsonschema.validate(manifest,schema)
    assert manifest['source']['kind']=='worktree' and manifest['immutable'] is True


def test_csv_cell_range_is_bound_and_formula_unsupported():
    import locator_replay as lr
    body=b'name,value\nheight,12 metres\nformula,=1+1\n'
    assert lr.replay(body,'table:sheet=CSV;cell=B2','12 metres')=='valid'
    assert lr.replay(body,'table:sheet=CSV;cell=A1:B1','12 metres')=='unlocatable'
    assert lr.replay(body,'table:sheet=CSV;cell=A9')=='unlocatable'
    assert lr.replay(body,'table:sheet=CSV;cell=B3')=='unsupported'


def test_oversize_locator_has_distinct_fail_closed_state():
    import locator_replay as lr
    assert lr.replay(b'x'*(lr.MAX_INPUT+1),'line:1')=='oversize'


def test_host_cli_emits_one_hook_control_object(tmp_path):
    import subprocess
    script=SCRIPTS/'record_session_event.py'
    subprocess.run([sys.executable,'-B',str(script),'init','--root',str(tmp_path)],check=True,capture_output=True)
    result=subprocess.run([sys.executable,'-B',str(script),'record','--root',str(tmp_path),'--event','session_start','--compile-proposal'],input='{"session_id":"synthetic-host"}',text=True,capture_output=True,cwd=tmp_path)
    assert result.returncode==0
    assert result.stdout == ''
    status=json.loads((tmp_path/'knowledge-base/_ops/session-knowledge-status.json').read_bytes())
    assert [s['step'] for s in status['recent_steps']]==['open','session_proposal']
    assert all(s['ok'] for s in status['recent_steps'])


def test_hook_failure_is_one_control_object_and_visible(tmp_path):
    import subprocess
    script=SCRIPTS/'record_session_event.py'
    subprocess.run([sys.executable,'-B',str(script),'init','--root',str(tmp_path)],check=True,capture_output=True)
    (tmp_path/'knowledge-base/_ops/session-knowledge-overlay.jsonl').write_text('{broken\n')
    result=subprocess.run([sys.executable,'-B',str(script),'record','--root',str(tmp_path),'--event','pre_compact'],input='{"session_id":"synthetic-host"}',text=True,capture_output=True,cwd=tmp_path)
    message=json.loads(result.stdout)
    assert result.returncode==0 and message['continue'] is True
    status=json.loads(message['systemMessage'])
    assert status['ok'] is False and status['reason']=='overlay_invalid'


def test_sealed_host_shaped_payloads_freeze_before_gold(tmp_path):
    import hashlib
    from test_session_continuity import project,run
    root=project(tmp_path)
    sealed=Path(__file__).parent/'fixtures/sealed_metacognitive'
    cases=json.loads((sealed/'host_inputs.json').read_bytes())['cases']
    results=[]
    for case in cases:
        payload=case['payload']
        payload['artifact_pointers'][0]['revision_sha256']=hashlib.sha256((root/'knowledge/result.html').read_bytes()).hexdigest()
        process,result=run(root,payload,runtime=case['runtime']);results.append({'exit_code':process.returncode,'status':result['status']})
    frozen=json.dumps(results,sort_keys=True).encode();digest=hashlib.sha256(frozen).hexdigest()
    gold=json.loads((sealed/'host_gold.json').read_bytes())
    assert json.loads(frozen)==gold['expected_results']
    assert len(digest)==64
    assert len(list((root/'knowledge-base/_ops/session-events-v3').glob('SEV-*.json')))==4
    assert not (root/'knowledge-base/_ops/memory').exists()
