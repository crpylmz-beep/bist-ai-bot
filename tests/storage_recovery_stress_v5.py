"""Opt-in real 280/270 MiB V5 recovery in an owned synthetic volume only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import atomik_depolama as atomic
from ana_motor import worker_lock
from disk_forensik import inspect_atomic_temps
from recovery_journal import RecoveryJournal
from storage_recovery import RECOVERED
from veri_yollari import DataPaths


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def fixture(path,count,extra=0):
    padding='x'*2880
    with path.open('w') as handle:
        handle.write('{"kayitlar":[\n')
        for i in range(count+extra):
            key=str(i) if i<count else 'UNIQUE-'+str(i-count)
            row={'kayit_id':key,'score':70,'padding':padding}
            if i:handle.write(',\n')
            handle.write(json.dumps(row,indent=2))
        handle.write('],"toplam_kayit":'+str(count+extra)+',"guncelleme":"2026-10-08T11:00:00+03:00"}')


def run():
    with tempfile.TemporaryDirectory(prefix='bist-v5-stress-') as folder,patch.dict(os.environ,{'BIST_DATA_DIR':folder,'BIST_RUNTIME_DIR':'','BIST_USER_DATA_DIR':'','STORAGE_RECOVERY_DELETE_ENABLED':'false'}):
        location=DataPaths();location.ensure();final=location.runtime/'ai_ogrenme_gecmisi.json';temp=location.runtime/'.user-v5-synthetic.tmp'
        fixture(final,100000);fixture(temp,96500,7);os.utime(temp,(0,0))
        initial=final.stat().st_size;source=temp.stat().st_size;original=digest(final)
        assert initial>=280*1024**2 and source>=270*1024**2,(initial,source)
        journal=RecoveryJournal(final);allocations=[];allocate=atomic.tempfile.mkstemp
        from storage_izleme import WriteTrace
        finish=WriteTrace.finish;maximum={'new_bytes':0,'new_files':0,'all_bytes':source,'all_files':1};writes=[]
        def capture_write(trace):
            finish(trace);writes.append((trace.path,trace.physical))
            maximum['new_bytes']=max(maximum['new_bytes'],trace.physical)
            maximum['all_bytes']=max(maximum['all_bytes'],source+trace.physical)
        def allocate_temp(**kwargs):
            answer=allocate(**kwargs);allocations.append(kwargs.get('prefix',''))
            live=list(location.runtime.glob('.user-*.tmp'))
            maximum['new_files']=max(maximum['new_files'],len(live)-1);maximum['all_files']=max(maximum['all_files'],len(live))
            return answer
        usage=shutil._ntuple_diskusage(5*1024**3,4700*1024**2,420*1024**2)
        rounds=0;started=time.monotonic()
        with patch('atomik_temp_temizligi.foreign_open',return_value=False),patch('shutil.disk_usage',return_value=usage),patch.object(atomic.tempfile,'mkstemp',side_effect=allocate_temp),patch.object(WriteTrace,'finish',capture_write),worker_lock(location.runtime):
            while rounds<20:
                rounds+=1;result=inspect_atomic_temps(location,cleanup=True,resumable=True,budget_seconds=180)
                if result['classifications'][RECOVERED]:break
            assert result['classifications'][RECOVERED]==1,result
            operations=journal.operations();assert len(operations)==7
            assert {op['record']['kayit_id'] for op in operations.values()}=={'UNIQUE-'+str(i) for i in range(7)}
            wal=journal.path.stat().st_size
            replay_rounds=0
            while replay_rounds<20:
                replay_rounds+=1
                repeated=inspect_atomic_temps(location,cleanup=True,resumable=True,budget_seconds=180)
                if repeated['classifications'][RECOVERED]:break
            assert repeated['classifications'][RECOVERED]==1,repeated
            assert journal.path.stat().st_size==wal and len(journal.operations())==7
            assert digest(final)==original and temp.exists()
            assert not any(path==final for path,_ in writes) and maximum['new_bytes']<=256*1024
            assert not any(prefix.startswith('.user-v2-'+hashlib.sha256(final.name.encode()).hexdigest()[:24]) for prefix in allocations)
        return dict(final_bytes=initial,orphan_bytes=source,final_mib=round(initial/1024**2,2),orphan_mib=round(source/1024**2,2),final_records=100000,orphan_records=96507,recovered_records=7,journal_bytes=wal,full_json_rewrites=0,new_large_temp_files=0,new_large_temp_bytes=0,max_new_metadata_temp_files=maximum['new_files'],max_new_metadata_temp_bytes=maximum['new_bytes'],max_total_temp_files=maximum['all_files'],max_total_temp_bytes=maximum['all_bytes'],max_existing_orphan_files=1,max_existing_orphan_bytes=source,source_retained=True,duplicate_journal_growth_bytes=0,rounds=rounds,replay_rounds=replay_rounds,seconds=round(time.monotonic()-started,2))


if __name__=='__main__':print(json.dumps(run(),indent=2))
