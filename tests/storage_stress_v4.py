"""Opt-in real ~280 MiB stress. Creates/removes only its owned temporary volume.

Run: PYTHONDONTWRITEBYTECODE=1 python tests/storage_stress_v4.py
No provider calls, production access or large committed fixtures.
The baseline 100 rewrites is an explicitly theoretical extrapolation of the
measured initial full commit; the 100 WAL transactions and merged write are real.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import atomik_depolama as atomic
from history_journal import HistoryJournal, field_patch, identity
from storage_izleme import WriteTrace
from veri_yollari import DataPaths


def run():
    with tempfile.TemporaryDirectory(prefix='bist-v4-stress-') as folder,patch.dict(os.environ,{'BIST_DATA_DIR':folder,'BIST_RUNTIME_DIR':'','BIST_USER_DATA_DIR':''}):
        location=DataPaths();location.ensure();target=location.runtime/'ai_ogrenme_gecmisi.json'
        # Shared immutable padding avoids 280 MiB of duplicated in-memory strings.
        padding='x'*2860
        value={'kayitlar':[{'kayit_id':str(i),'score':70,'padding':padding} for i in range(100000)],'toplam_kayit':100000,'guncelleme':'2026-10-08T11:00:00+03:00'}
        traces=[];original=WriteTrace.finish
        def capture(self):
            original(self)
            if self.path==target:traces.append({'physical':self.physical,'success':self.success})
        with patch.object(WriteTrace,'finish',capture):atomic.atomic_write_json(target,value)
        initial=target.stat().st_size
        assert initial>=280*1024**2,(initial,'fixture smaller than 280 MiB')
        baseline=traces.pop()['physical'];journal=HistoryJournal(target);logical=0
        for i in range(100):
            old=value['kayitlar'][i];new=dict(old,sonuc_1g={'getiri':i/100})
            operation={'id':identity(old),'fields':field_patch(old,new)}
            logical+=len(json.dumps(operation,separators=(',',':'),ensure_ascii=False).encode())
            journal.append([operation])
        wal=journal.path.stat().st_size
        allocations=[];maximum={'count':0,'bytes':0};allocate=atomic.tempfile.mkstemp;flush=atomic.BufferedJSON.flush
        def allocate_temp(**kwargs):
            answer=allocate(**kwargs);allocations.append(answer[1]);return answer
        def inspect_buffer(buffer):
            answer=flush(buffer)
            temps=list(location.runtime.glob('.user-*.tmp'))
            maximum['count']=max(maximum['count'],len(temps))
            # Trace counts bytes actually emitted including stream buffering.
            maximum['bytes']=max(maximum['bytes'],buffer.trace.physical if buffer.trace else 0)
            return answer
        with patch.object(WriteTrace,'finish',capture),patch.object(atomic.tempfile,'mkstemp',side_effect=allocate_temp),patch.object(atomic.BufferedJSON,'flush',inspect_buffer):
            assert journal.flush()==100
        # Streaming validation: do not allocate a second 280 MiB JSON string.
        import atomik_temp_temizligi as proof
        fd=os.open(target,os.O_RDONLY);stream=proof.HistoryStream(fd,float('inf'));updated=0;count=0
        try:
            for key,row in stream.entries():
                if key is None:
                    count+=1
                    if 'sonuc_1g' in row:updated+=1
        finally:stream.close();os.close(fd)
        assert updated==100 and count==100000
        assert len(allocations)==1 and maximum['count']==1
        assert not list(location.runtime.glob('.user-*.tmp')) and not journal.path.exists()
        physical=traces[-1]['physical']+wal
        return dict(initial_bytes=initial,logical_delta_bytes=logical,wal_bytes=wal,merge_temp_bytes=traces[-1]['physical'],physical_payload_bytes=physical,amplification=round(physical/logical,2),baseline_100_rewrites_theoretical_bytes=baseline*100,baseline_theoretical_amplification=round(baseline*100/logical,2),max_temp_files=maximum['count'],max_temp_bytes=maximum['bytes'],remaining_temp_files=0,updated_records=updated,retained_records=count,coalesced_transactions=100)


if __name__=='__main__':print(json.dumps(run(),indent=2))
