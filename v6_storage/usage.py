"""Read-only filesystem measurement and bounded daily growth metadata; no cleanup."""
from datetime import datetime
import os
from pathlib import Path
import shutil
from .records import ISTANBUL


def disk_report(root,limit=20):
    root=Path(root);usage=shutil.disk_usage(root);top=[];total=0;files=0;errors=0
    for directory,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[name for name in dirs if not (Path(directory)/name).is_symlink()]
        for name in names:
            path=Path(directory)/name
            try:
                if path.is_symlink() or not path.is_file():continue
                size=path.stat().st_size;total+=size;files+=1
                # Paths replaced by category and opaque token: never expose user identity.
                import hashlib
                relative=path.relative_to(root);category=relative.parts[0] if len(relative.parts)>1 else 'root'
                top.append({'category':category,'file_token':hashlib.sha256(str(relative).encode()).hexdigest()[:12],'bytes':size});top.sort(key=lambda row:row['bytes'],reverse=True);del top[limit:]
            except OSError:errors+=1
    return {'filesystem_total_bytes':usage.total,'filesystem_used_bytes':usage.used,'filesystem_free_bytes':usage.free,'tree_bytes':total,'files':files,'errors':errors,'largest':top,'measured_at':datetime.now(ISTANBUL).isoformat()}


def growth(current,previous,threshold=100*1024*1024):
    difference=current['tree_bytes']-previous['tree_bytes'] if previous else None
    return {'growth_bytes':difference,'alert':difference is not None and difference>threshold,'comparable':previous is not None}


def measure(root,state_path,store=None,r2=None):
    from recovery_journal import read_document
    from atomik_depolama import atomic_write_json
    day=datetime.now(ISTANBUL).date().isoformat();current=disk_report(root)
    state=read_document(state_path,{'days':{}});days=state.get('days',{})
    previous=next((days[key]['disk'] for key in sorted(days,reverse=True) if key<day),None)
    sample={'disk':current,'growth':growth(current,previous)}
    if store:
        sample['postgres']={'bytes':store.size()};store.record_usage(day,'disk',sample['disk']);store.record_usage(day,'postgres',sample['postgres'])
    if r2:sample['r2']=r2.usage()
    days[day]=sample;state={'days':{key:days[key] for key in sorted(days)[-32:]}}
    atomic_write_json(state_path,state)
    return sample
