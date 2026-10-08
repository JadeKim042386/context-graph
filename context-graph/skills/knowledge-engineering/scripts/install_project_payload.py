#!/usr/bin/env python3
"""Project-local immutable worktree payloads; never registers or changes shared hosts."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from session_storage import safe_path

EXCLUDED = ['tests', '__pycache__', '.pytest_cache', '.git']
BASE = '.context-graph/plugins/context-graph'
MAX_BYTES = 64*1024*1024


def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'))


def inventory(source, filtered=True):
    if source.is_symlink(): raise ValueError('unsafe_path')
    entries=[];total=0
    for current,dirs,files in os.walk(source,followlinks=False):
        if filtered: dirs[:]=[d for d in dirs if d not in EXCLUDED]
        for name in dirs+files:
            if (Path(current)/name).is_symlink(): raise ValueError('unsafe_path')
        for name in sorted(files):
            path=Path(current)/name
            if filtered and path.suffix=='.pyc':continue
            size=path.stat().st_size;total+=size
            if size>16*1024*1024 or total>MAX_BYTES or len(entries)>=2000:raise ValueError('snapshot_limit')
            entries.append({'path':str(path.relative_to(source)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':size})
    return sorted(entries,key=lambda x:x['path'])


def payload_id(entries): return hashlib.sha256(canonical(entries).encode()).hexdigest()


def verify(snapshot):
    snapshot=Path(snapshot)
    try:
        if snapshot.is_symlink():raise ValueError('unsafe_path')
        p=safe_path(snapshot,'manifest.json')
        if not p.is_file():return {'status':'missing'}
        if p.stat().st_size>1024*1024:raise ValueError('snapshot_limit')
        manifest=json.loads(p.read_bytes());entries=inventory(safe_path(snapshot,'context-graph'),filtered=False)
        if (set(manifest)!={'schema_version','record_type','payload_id','source','created_at','files','file_count','total_bytes','tool_version','excluded_globs','immutable'}
            or manifest['schema_version']!=1 or manifest['record_type']!='ProjectPluginSnapshot' or manifest['immutable'] is not True
            or entries!=manifest['files'] or payload_id(entries)!=manifest['payload_id'] or snapshot.name!=manifest['payload_id']
            or len(entries)!=manifest['file_count'] or sum(x['bytes'] for x in entries)!=manifest['total_bytes']
            or set(x.name for x in snapshot.iterdir())!={'manifest.json','context-graph'}):raise ValueError('snapshot_conflict')
        return {'status':'verified','payload_id':manifest['payload_id'],'file_count':len(entries),'total_bytes':manifest['total_bytes']}
    except (OSError,ValueError,KeyError,TypeError):return {'status':'tampered'}


def install(root):
    root=Path(root).resolve();source=safe_path(root,'context-graph')
    if not (source/'.claude-plugin/plugin.json').is_file():raise ValueError('plugin_missing')
    entries=inventory(source);identity=payload_id(entries)
    parent=safe_path(root,BASE);destination=safe_path(root,BASE+'/'+identity)
    if destination.exists():
        if verify(destination)['status']!='verified':raise ValueError('snapshot_conflict')
        return {'status':'duplicate','payload_id':identity,'snapshot':str(destination),'plugin_root':str(destination/'context-graph')}
    parent.mkdir(parents=True,exist_ok=True)
    head=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True)
    dirty=subprocess.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True)
    manifest={'schema_version':1,'record_type':'ProjectPluginSnapshot','payload_id':identity,
        'source':{'kind':'worktree','commit_sha':None,'head_sha':head.stdout.strip() if head.returncode==0 else None,'worktree_dirty':bool(dirty.stdout) or dirty.returncode!=0},
        'created_at':datetime.now(timezone.utc).isoformat(),'files':entries,'file_count':len(entries),'total_bytes':sum(x['bytes'] for x in entries),
        'tool_version':1,'excluded_globs':EXCLUDED+['*.pyc'],'immutable':True}
    with tempfile.TemporaryDirectory(prefix='.pending-',dir=parent) as temporary:
        stage=Path(temporary)/identity;payload=stage/'context-graph';payload.mkdir(parents=True)
        for entry in entries:
            data=safe_path(source,entry['path']).read_bytes()
            if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('source_changed')
            target=safe_path(payload,entry['path']);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        if verify(stage)['status']!='verified':raise ValueError('snapshot_conflict')
        try:os.rename(stage,destination)
        except FileExistsError:
            if verify(destination)['status']!='verified':raise ValueError('snapshot_conflict')
    return {'status':'installed','payload_id':identity,'snapshot':str(destination),'plugin_root':str(destination/'context-graph')}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('command',choices=['install','verify']);p.add_argument('--snapshot',type=Path);args=p.parse_args()
    try:
        result=install(args.root) if args.command=='install' else verify(args.snapshot)
    except (ValueError,OSError,TypeError):result={'status':'blocked','reason':'snapshot_invalid'}
    print(json.dumps(result,sort_keys=True));return 0 if result['status'] in ['installed','duplicate','verified'] else 2

if __name__=='__main__':raise SystemExit(main())
