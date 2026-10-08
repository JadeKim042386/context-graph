#!/usr/bin/env python3
"""Local synthetic evaluator and counterbalanced microbenchmark; no host/network calls."""
import argparse
import hashlib
import itertools
import json
import math
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/knowledge-engineering/scripts'
sys.path.insert(0,str(SCRIPTS))
import consolidate_knowledge as ck
import session_knowledge as sk


def hashfile(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def put(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(ck.canonical(value)+'\n');return p


def synthetic_inputs(root):
    """Deterministic source fixture, contains no labels; evaluator gold is never read here."""
    rows=[];paths=[]
    for i in range(60):
        group=i//3 if i<30 else 100+(i-30)//2 if i<50 else i+200
        pointer=f'sources/source-{group}.txt'; p=root/pointer;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('Value is twelve metres.\n')
        h=hashfile(p); rights=f'rights/{group}.json'
        proof=put(root,rights,{'record_type':'Source','status':'accepted','content_sha256':h,'rights':{'status':'rights_verified'}})
        refs=[{'pointer':pointer,'sha256':h,'locator':'line:1','quote':'twelve metres','rights_ref':{'pointer':rights,'sha256':hashfile(proof)}}]
        session='s'+str(group%2);fp=hashlib.sha256(str(group if i<30 else i).encode()).hexdigest()
        event={'event_id':f'SEV-{i}','record_type':'SessionLifecycleEvent','session_id':session,'event_type':'post_compact','content_fingerprint':fp,'artifact_pointers':refs}
        event_hash=hashlib.sha256((ck.canonical(event)+'\n').encode()).hexdigest(); src=f'events/SEV-{i}.json'
        put(root,src,dict(event,record_sha256=event_hash));paths.extend([src,pointer,rights])
        rows.append({'schema_version':1,'record_type':'SessionKnowledgeOverlay','overlay_id':f'item-{i}','source_event_id':f'SEV-{i}',
                     'source_store':'explicit','source_pointer':src,'source_revision_sha256':event_hash,'session_key':session,
                     'runtime':'codex' if group%2 else 'claude-code','event_type':'post_compact','content_fingerprint':fp,
                     'artifact_pointers':refs,'promotion_state':'review_required','status':'provisional'})
    p=root/ck.OVERLAY;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(ck.canonical(r)+'\n' for r in rows))
    context={'root':root,'policy':{'revision':1,'roles':{'reviewer':{'scope_ids':['s']}}},'binding':{'task_scope_ids':['s'],'assignment_scope_ids':['s']},
             'session_role':'reviewer','agent_role':'reviewer','catalog':{'artifacts':{p:{'scope_ids':['s']} for p in paths}}}
    return context


def pairs(groups): return {tuple(sorted(p)) for g in groups for p in itertools.combinations(g,2)}


def ratio(n,d): return n/d if d else None


def evaluate_local_gold(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    context=synthetic_inputs(root)
    sealed=Path(__file__).resolve().parent/'fixtures/sealed_metacognitive'
    gate={'active':True,'reads':0}
    def audit(event,args):
        if gate['active'] and event=='open' and args and isinstance(args[0],(str,bytes)) and str(sealed) in str(args[0]):
            gate['reads']+=1;raise RuntimeError('sealed_gold_access')
    sys.addaudithook(audit)
    try: ck.compact(root,context)
    finally: gate['active']=False
    frozen=(root/ck.PROJECTION).read_bytes(); output_hash=hashlib.sha256(frozen).hexdigest()
    # Freeze bytes and digest BEFORE evaluator sidecar is opened.
    gold_raw=(sealed/'gold.json').read_bytes();gold=json.loads(gold_raw);manifest=json.loads((sealed/'manifest.json').read_bytes())
    assert hashlib.sha256(gold_raw).hexdigest()==manifest['gold_sha256']
    projection=json.loads(frozen)
    predicted=pairs([p['candidate_overlay_ids'] for p in projection['review_queue'] if p['kind']=='exact_duplicate'])
    conflicts=pairs([p['candidate_overlay_ids'] for p in projection['review_queue'] if p['kind']=='conflict'])
    expected=pairs(gold['duplicate_groups']); expected_conflicts=pairs(gold['conflict_groups'])
    excluded=set(projection['excluded_exact_duplicates']);allowed={i for group in gold['duplicate_groups'] for i in sorted(group)[1:]}
    held={i['overlay_id'] for i in projection['held_items']}
    return {'fixture_kind':gold['fixture_kind'],'input_count':60,'input_sha256':hashfile(root/ck.OVERLAY),'frozen_output_sha256':output_hash,'gold_sha256':manifest['gold_sha256'],
            'gold_opened_after_output_freeze':True,'gold_runtime_reads':gate['reads'],'duplicate_precision':ratio(len(predicted&expected),len(predicted)),
            'duplicate_recall':ratio(len(predicted&expected),len(expected)),'conflict_recall':ratio(len(conflicts&expected_conflicts),len(expected_conflicts)),
            'false_exclusion_count':len(excluded-allowed),'exclusions':len(excluded),'held_exact':held==set(gold['expected_held']),
            'locator_eligible_count':len(projection['items']),'conflict_provenance_count':len(projection['held_items']),
            'limits':'Proposal pair accuracy on synthetic local cases, no reviewed suppression; not real-host precision/recall or independent semantic gold.'}


def fixture(root,n):
    root.mkdir(parents=True,exist_ok=True);rows=[]
    for i in range(n):
        rows.append({'schema_version':1,'record_type':'SessionKnowledgeOverlay','overlay_id':f'item-{i}','source_event_id':f'SEV-{i}',
            'source_store':'explicit','source_pointer':f'events/SEV-{i}.json','source_revision_sha256':'a'*64,'session_key':f's{i%2}',
            'event_type':'post_compact','content_fingerprint':str(i//10),'artifact_pointers':[],
            'promotion_state':'review_required','status':'provisional'})
    p=root/ck.OVERLAY;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(ck.canonical(r)+'\n' for r in rows));return p


def operation(root,op):
    if op=='split':return sk.split(root)
    if op=='plan':return ck.plan(root)
    return ck.compact(root)


def rss():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform=='darwin' else value*1024


def measure(base,sizes=(100,1000,5000),repetitions=30):
    base=Path(base);output=[];unchanged=True
    for n in sizes:
        root=base/str(n);raw=fixture(root,n);before=hashfile(raw)
        samples={op:[] for op in ['split','plan','compact']}
        for op in samples:operation(root,op)
        for rep in range(repetitions):
            for op in (list(samples) if rep%2==0 else list(reversed(samples))):
                start=time.perf_counter_ns();operation(root,op);samples[op].append((time.perf_counter_ns()-start)/1e6)
        for condition in ['warm_in_process','fresh_interpreter','fresh_file_proxy']:
            data=samples if condition=='warm_in_process' else {op:[] for op in samples};peak={op:0 for op in samples}
            if condition!='warm_in_process':
                for rep in range(repetitions):
                    for op in (list(samples) if rep%2==0 else list(reversed(samples))):
                        # New pathname proxy does NOT flush page cache or libraries.
                        with tempfile.TemporaryDirectory(prefix='consolidation-proxy-') as tmp:
                            selected=root
                            if condition=='fresh_file_proxy':
                                selected=Path(tmp);p=selected/ck.OVERLAY;p.parent.mkdir(parents=True);p.write_bytes(raw.read_bytes())
                            start=time.perf_counter_ns()
                            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--child',op,'--root',str(selected)],capture_output=True,check=True,timeout=15)
                            data[op].append((time.perf_counter_ns()-start)/1e6);peak[op]=max(peak[op],json.loads(result.stdout)['rss_peak_bytes'])
            for op,values in data.items():
                tracemalloc.start();result=operation(root,op);_,allocation=tracemalloc.get_traced_memory();tracemalloc.stop()
                output.append({'items':n,'condition':condition,'operation':op,'p50_ms':round(statistics.median(values),3),
                    'p95_ms':round(sorted(values)[max(0,math.ceil(.95*len(values))-1)],3),'rss_peak_bytes':peak[op] or rss(),
                    'python_peak_bytes':allocation,'raw_bytes':raw.stat().st_size,'fixture_sha256':before,
                    'projection_bytes':(root/ck.PROJECTION).stat().st_size,'proposal_count':result.get('proposal_count'),
                    'representative_count':result.get('projection_count'),'calls_per_run':1})
        unchanged &= before==hashfile(raw)
    return {'fixture_kind':'synthetic_missing_evidence_fail_closed','runtime':sys.version,'platform':platform.platform(),
            'repetitions':repetitions,'warmups':1,'order':'alternating forward/reverse split,plan,compact',
            'os_cold':'unverified_not_flushed','cold_proxy_limit':'fresh pathname is immediately written and may be cached; not OS-cold; no cache purge performed',
            'rss_limit':'warm RSS is cumulative process high-water; fresh series reports maximum per-child RSS including imports; not incremental memory',
            'tokenizer':'none_bytes_only','raw_hashes_preserved':unchanged,'rows':output}


def main():
    p=argparse.ArgumentParser();p.add_argument('--child',choices=['split','plan','compact']);p.add_argument('--root',type=Path);p.add_argument('--output',type=Path);p.add_argument('--repetitions',type=int,default=30);args=p.parse_args()
    if args.child:
        operation(args.root,args.child);print(json.dumps({'rss_peak_bytes':rss()}));return
    if not 1<=args.repetitions<=100:raise ValueError('repetition_bound')
    with tempfile.TemporaryDirectory(prefix='metacognitive-eval-') as tmp:
        root=Path(tmp);result={'performance':measure(root/'performance',repetitions=args.repetitions),'quality':evaluate_local_gold(root/'gold-fixture'),
            'module_hashes':{p.name:hashfile(p) for p in SCRIPTS.glob('*.py') if p.name in ['session_knowledge.py','session_archive.py','consolidate_knowledge.py','locator_replay.py','session_storage.py']}}
    raw=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(raw)
    else:print(raw)

if __name__=='__main__':main()
