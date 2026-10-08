"""Boundary regressions: archive replay, typed locators, and real hook caller flow."""
import hashlib
import json
import sys
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/knowledge-engineering/scripts'
sys.path.insert(0, str(SCRIPTS))
import session_knowledge as sk
import consolidate_knowledge as ck
from test_session_knowledge import _root


def seed_closed(root):
    sk.open_agent(root, session_id='closed')
    sk.open_agent(root, session_id='open')
    project = sk._project_id(root)
    rows = [{'record_type':'SessionLifecycleEvent','event_id':'SEV-'+s,'session_id':sk.event_key([project,s])} for s in ['closed','open']]
    (root/'knowledge-base/_ops/session-events.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
    sk.merge_session(root)
    sk.close_agent(root, session_id='closed')
    return sk.split(root)['items']


def test_archive_rotation_replays_without_reappend(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    before = seed_closed(root)
    result = sk.rotate(root)
    assert result['archived_count'] == 1
    assert sk.split(root)['total_count'] == 1
    replay = sk.split(root, include_archive=True)['items']
    assert {x['overlay_id'] for x in replay} == {x['overlay_id'] for x in before}
    archived = [x for x in replay if x.get('source_store') == 'archive']
    assert len(archived) == 1 and archived[0]['original_source_store'] == 'legacy'
    segment = root / result['segment_path']
    snapshot = segment.read_bytes()
    assert sk.rotate(root)['archived_count'] == 0
    assert sk.merge_session(root)['merged_count'] == 0
    ck.plan(root, include_archive=True)
    assert segment.read_bytes() == snapshot


@pytest.mark.parametrize('crash_at', ['head', 'overlay', 'commit'])
def test_archive_recovers_each_publish_boundary(tmp_path, monkeypatch, crash_at):
    import session_storage as storage
    root = _root(tmp_path, monkeypatch)
    before = seed_closed(root)
    replace = storage.os.replace
    count = 0
    def crash(src, dst):
        nonlocal count
        if Path(dst).name == 'head.json':
            count += 1
        fail = (crash_at == 'head' and Path(dst).name == 'head.json' and count == 1 or
                crash_at == 'overlay' and Path(dst).name == 'session-knowledge-overlay.jsonl' or
                crash_at == 'commit' and Path(dst).name == 'head.json' and count == 2)
        if fail: raise OSError('simulated crash')
        return replace(src,dst)
    monkeypatch.setattr(storage.os,'replace',crash)
    with pytest.raises(OSError): sk.rotate(root)
    monkeypatch.setattr(storage.os,'replace',replace)
    sk.rotate(root)
    replay = sk.split(root, include_archive=True)['items']
    assert {i['overlay_id'] for i in replay} == {i['overlay_id'] for i in before}
    assert len(replay) == 2


def test_archive_tamper_and_symlink_fail_closed(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    seed_closed(root)
    result = sk.rotate(root)
    segment = root/result['segment_path']
    segment.write_bytes(b'{}\n')
    with pytest.raises(ValueError, match='archive'): sk.split(root, include_archive=True)
    segment.unlink()
    segment.symlink_to(root/'knowledge-base/_ops/session-events.jsonl')
    with pytest.raises(ValueError): sk.split(root, include_archive=True)


def test_html_quote_is_bound_to_exact_element():
    import locator_replay as lr
    body=b'<p id="yes">twelve metres</p><p>outside secret</p>'
    assert lr.replay(body,'html:#yes','twelve') == 'valid'
    assert lr.replay(body,'html:#no') == 'unlocatable'
    assert lr.replay(body,'html:#yes','outside') == 'unlocatable'


def test_optional_local_formats_and_ranges(tmp_path):
    import locator_replay as lr
    import io, wave
    from PIL import Image
    from pypdf import PdfWriter
    import openpyxl
    im=io.BytesIO(); Image.new('RGB',(10,20)).save(im,format='PNG')
    pdf=io.BytesIO(); w=PdfWriter(); w.add_blank_page(width=100,height=200); w.write(pdf)
    book=io.BytesIO(); wb=openpyxl.Workbook(); wb.active.title='Data'; wb.active['A1']='twelve'; wb.save(book)
    wav=io.BytesIO()
    with wave.open(wav,'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(b'\x00\x00'*8000)
    cases=[(im.getvalue(),'image:bbox=0,0,10,20','image:bbox=0,0,11,20'),
           (pdf.getvalue(),'pdf:page=1','pdf:page=2'),
           (book.getvalue(),'table:sheet=Data;cell=A1','table:sheet=Data;cell=A2'),
           (wav.getvalue(),'av:t=00:00:00-00:00:01','av:t=00:00:00-00:00:02')]
    for body, good,bad in cases:
        assert lr.replay(body,good) == 'valid',good
        assert lr.replay(body,bad) == 'unlocatable',bad
        assert lr.replay(body,good,'absent quote') in {'unlocatable','unsupported'}
    assert lr.replay(book.getvalue(),'table:sheet=Data;cell=A1','twelve') == 'valid'


def test_parser_absence_is_unsupported(monkeypatch):
    import locator_replay as lr
    import builtins
    original=builtins.__import__
    def denied(name,*args,**kwargs):
        if name in {'pypdf','PIL','openpyxl'}: raise ImportError('missing optional parser')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',denied)
    for locator in ['pdf:page=1','image:bbox=0,0,1,1','table:sheet=S;cell=A1']:
        assert lr._replay(b'placeholder',locator,None) == 'unsupported'


def test_hook_explicit_role_and_unattributed_separation(tmp_path,monkeypatch):
    import record_session_event as hook
    root=_root(tmp_path,monkeypatch)
    payload={'session_id':'private-session','agent_instance_id':'a','task_id':'t','assignment_id':'x','role':'reviewer'}
    assert hook.record_project(root,'session_start',payload,False)==0
    state=sk._read(root/sk.REGISTRY)[0]
    assert state['agent_key'] and state['role_key']
    event={'record_type':'SessionLifecycleEvent','event_id':'SEV-v3','session_id':sk.event_key([sk._project_id(root),'private-session']),
           'attribution':{'agent_instance_id':state['agent_key'],'task_id':state['task_key'],'assignment_id':state['assignment_key']}}
    with (root/'knowledge-base/_ops/session-events.jsonl').open('a') as f: f.write(json.dumps(event)+'\n')
    sk.merge_session(root)
    rows=sk.split(root)['items']
    assert next(x for x in rows if x['source_event_id']=='SEV-v3')['role_key']==state['role_key']
    assert all(x['role_key'] is None for x in rows if x['source_event_id']!='SEV-v3')
    assert 'private-session' not in (root/sk.REGISTRY).read_text()


def test_archive_preserves_open_agent_and_rejects_changed_pending_base(tmp_path,monkeypatch):
    import session_storage as storage
    root=_root(tmp_path,monkeypatch)
    seed_closed(root)
    sk.open_agent(root,session_id='closed',agent_instance_id='still-open')
    assert sk.rotate(root)['archived_count']==0
    sk.close_agent(root,session_id='closed',agent_instance_id='still-open')
    replace=storage.os.replace
    def fail_overlay(src,dst):
        if Path(dst).name=='session-knowledge-overlay.jsonl': raise OSError('crash')
        return replace(src,dst)
    monkeypatch.setattr(storage.os,'replace',fail_overlay)
    with pytest.raises(OSError): sk.rotate(root)
    monkeypatch.setattr(storage.os,'replace',replace)
    p=root/sk.OVERLAY; p.write_bytes(p.read_bytes()+b'{}\n')
    with pytest.raises(ValueError,match='archive_recovery_conflict'): sk.rotate(root)


@pytest.mark.parametrize('status',['restricted','unknown','unverified'])
def test_rights_state_remains_visible_and_ineligible(tmp_path,status):
    from test_metacognitive_boundaries import verified_fixture,put
    rows,context=verified_fixture(tmp_path)
    for row in rows:
        proof=json.loads((tmp_path/'source.json').read_bytes()); proof['rights']['status']=status
        raw=(json.dumps(proof)+'\n').encode(); (tmp_path/'source.json').write_bytes(raw)
        row['artifact_pointers'][0]['rights_ref']['sha256']=hashlib.sha256(raw).hexdigest()
        event=json.loads((tmp_path/row['source_pointer']).read_bytes()); event.pop('record_sha256')
        event['artifact_pointers']=row['artifact_pointers']
        h=hashlib.sha256((ck.canonical(event)+'\n').encode()).hexdigest()
        put(tmp_path,row['source_pointer'],dict(event,record_sha256=h)); row['source_revision_sha256']=h
        result=ck.assess(tmp_path,row,context)
        assert result['rights']==status and result['eligible'] is False


def test_binary_locator_integrated_source_and_schema(tmp_path):
    from test_metacognitive_boundaries import verified_fixture,put
    from PIL import Image
    import io,jsonschema
    rows,context=verified_fixture(tmp_path)
    b=io.BytesIO(); Image.new('RGB',(10,20)).save(b,format='PNG'); body=b.getvalue()
    (tmp_path/'knowledge.txt').write_bytes(body)
    proof=json.loads((tmp_path/'source.json').read_bytes()); proof['content_sha256']=hashlib.sha256(body).hexdigest()
    p=put(tmp_path,'source.json',proof)
    row=rows[0]; ref=row['artifact_pointers'][0]; ref.update(sha256=proof['content_sha256'],locator='image:bbox=0,0,10,20'); ref.pop('quote')
    ref['rights_ref']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    event=json.loads((tmp_path/row['source_pointer']).read_bytes()); event.pop('record_sha256'); event['artifact_pointers']=row['artifact_pointers']
    h=hashlib.sha256((ck.canonical(event)+'\n').encode()).hexdigest(); put(tmp_path,row['source_pointer'],dict(event,record_sha256=h)); row['source_revision_sha256']=h
    assert ck.assess(tmp_path,row,context)['eligible'] is True
    schema=json.loads((SCRIPTS.parent/'schemas/evidence-locator.schema.json').read_bytes())
    jsonschema.validate({'locator':ref['locator'],'quote':None},schema)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate({'locator':'image:bogus'},schema)


def test_archive_emitted_head_and_projection_schemas(tmp_path,monkeypatch):
    import jsonschema
    root=_root(tmp_path,monkeypatch); seed_closed(root); sk.rotate(root)
    head=json.loads((root/'knowledge-base/_ops/session-knowledge-archive/head.json').read_bytes())
    schema=json.loads((SCRIPTS.parent/'schemas/session-knowledge-archive-head.schema.json').read_bytes())
    jsonschema.validate(head,schema)
    ck.compact(root,include_archive=True)
    projection=json.loads((root/ck.PROJECTION).read_bytes())
    schema=json.loads((SCRIPTS.parent/'schemas/consolidated-knowledge-projection.schema.json').read_bytes())
    jsonschema.validate(projection,schema)


def test_first_hook_cli_preserves_protected_hashes(tmp_path):
    import subprocess
    root=tmp_path
    protected=['knowledge/source.html','knowledge-base/_ops/memory/index.json','knowledge-base/_ops/maps/map.json','AGENTS.md','CLAUDE.md']
    for name in protected:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('protected '+name)
    subprocess.run([sys.executable,'-B',str(SCRIPTS/'record_session_event.py'),'init','--root',str(root)],check=True,capture_output=True)
    before={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in protected}
    result=subprocess.run([sys.executable,'-B',str(SCRIPTS/'record_session_event.py'),'record','--root',str(root),'--event','session_start','--compile-proposal'],input=json.dumps({'session_id':'first-fixture','invocation_id':'repeat-id'}),text=True,capture_output=True,cwd=root)
    assert result.returncode==0 and '"ok": false' not in result.stdout
    assert before=={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in protected}
    assert (root/sk.REGISTRY).exists()


def test_sealed_gold_frozen_output_and_false_exclusion(tmp_path):
    import benchmark_metacognitive as bench
    result=bench.evaluate_local_gold(tmp_path)
    assert result['fixture_kind']=='synthetic_local_not_real_host'
    assert result['duplicate_precision']==result['duplicate_recall']==1
    assert result['conflict_recall']==1 and result['false_exclusion_count']==0
    assert result['gold_opened_after_output_freeze'] is True
    assert result['gold_runtime_reads']==0
    assert result['input_count']==60


def test_benchmark_reports_cache_limits_and_memory(tmp_path):
    import benchmark_metacognitive as bench
    result=bench.measure(tmp_path,sizes=[10],repetitions=2)
    assert result['os_cold']=='unverified_not_flushed'
    assert result['repetitions']==2
    assert result['rows'][0]['condition']=='warm_in_process'
    assert all(row['p50_ms']>=0 and row['p95_ms']>=row['p50_ms'] for row in result['rows'])
    assert any(row.get('rss_peak_bytes',0)>0 for row in result['rows'])
    assert result['raw_hashes_preserved']


def test_pdf_page_quote_region_and_video_timecode(tmp_path):
    import locator_replay as lr
    import io,subprocess,shutil
    from reportlab.pdfgen import canvas
    p=io.BytesIO();c=canvas.Canvas(p,pagesize=(100,200));c.drawString(5,150,'twelve');c.save()
    assert lr.replay(p.getvalue(),'pdf:page=1','twelve')=='valid'
    assert lr.replay(p.getvalue(),'pdf:page=1','wrong')=='unlocatable'
    assert lr.replay(p.getvalue(),'pdf:page=1;bbox=0,0,100,200')=='valid'
    assert lr.replay(p.getvalue(),'pdf:page=1;bbox=0,0,101,200')=='unlocatable'
    assert lr.replay(p.getvalue(),'pdf:page=1;bbox=0,0,100,200','twelve')=='unsupported'
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg: pytest.skip('optional ffmpeg fixture generator unavailable')
    video=tmp_path/'clip.mp4'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=16x16:d=1','-c:v','mpeg4','-y',str(video)],check=True,capture_output=True,timeout=10)
    assert lr.replay(video.read_bytes(),'av:t=00:00:00-00:00:01')=='valid'
    assert lr.replay(video.read_bytes(),'av:t=00:00:00-00:00:02')=='unlocatable'


def test_av_parser_missing_and_timeout_fail_closed(monkeypatch):
    import locator_replay as lr
    import subprocess
    monkeypatch.setattr(lr.shutil,'which',lambda _:None)
    assert lr._replay(b'RIFF'+b'\x00'*30,'av:t=00:00:00-00:00:01',None)=='unsupported'
    def timeout(*args,**kwargs): raise subprocess.TimeoutExpired('worker',4)
    monkeypatch.setattr(lr.subprocess,'run',timeout)
    assert lr.replay(b'body','pdf:page=1')=='unlocatable'


def test_rotation_refills_active_bound_without_readding_archived(tmp_path,monkeypatch):
    root=_root(tmp_path,monkeypatch);seed_closed(root);sk.rotate(root)
    monkeypatch.setattr(sk,'MAX_OVERLAY_ITEMS',2)
    p=root/'knowledge-base/_ops/session-events.jsonl'
    with p.open('a') as f:f.write(json.dumps({'record_type':'SessionLifecycleEvent','event_id':'SEV-new','session_id':'new'})+'\n')
    assert sk.merge_session(root)['merged_count']==1
    assert sk.split(root)['total_count']==2 and sk.split(root,include_archive=True)['total_count']==3


def test_archive_orphan_is_visible_and_preserved(tmp_path,monkeypatch):
    root=_root(tmp_path,monkeypatch)
    directory=root/'knowledge-base/_ops/session-knowledge-archive';directory.mkdir()
    orphan=directory/('a'*64+'.jsonl');orphan.write_text('{}\n')
    result=sk.rotate(root)
    assert result['orphan_count']==1 and orphan.read_text()=='{}\n'


def test_partial_hook_attribution_has_specific_safe_reason(tmp_path,monkeypatch,capsys):
    import record_session_event as hook
    root=_root(tmp_path,monkeypatch)
    assert hook.record_project(root,'session_start',{'session_id':'fixture','role':'private-role'},False)==0
    output=capsys.readouterr().out
    assert '"reason": "invalid_attribution"' in output
    assert 'private-role' not in output
