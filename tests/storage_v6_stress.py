"""280 MiB streaming import + 100 row updates, owned local fixtures only."""
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
import uuid
import psycopg
from psycopg import sql
from v6_storage.config import Settings
from v6_storage.postgres import PostgresStore
from v6_storage.records import Shape,assemble
from v6_storage.migration import Migrator,checksum

def main():
    dsn=os.environ.get('BIST_V6_TEST_DSN','')
    if urlparse(dsn).hostname!='127.0.0.1':raise RuntimeError('Owned localhost fixture DSN required')
    name='v6_stress_'+uuid.uuid4().hex
    with psycopg.connect(dsn,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    store=PostgresStore(Settings(dsn=dsn.rsplit('/',1)[0]+'/'+name,batch_size=10));store.migrate()
    try:
        with tempfile.TemporaryDirectory(prefix='bist-v6-stress-owned-') as temp:
            path=Path(temp)/'history.json';padding='x'*(280*1024*1024//1000)
            with path.open('w') as sink:
                sink.write('{"version":1,"kayitlar":[')
                for i in range(1000):
                    if i:sink.write(',')
                    json.dump({'kayit_id':str(i),'price':100,'padding':padding,'sonuc_1g':None},sink,separators=(',',':'))
                sink.write(']}')
            before_hash=checksum(path);source_size=path.stat().st_size;assert source_size>=280*1024*1024
            shape=Shape('runtime/ai_ogrenme_gecmisi.json',{'kayitlar':'list'})
            result=Migrator(store,10).run(path,shape,True);assert result['status']=='VERIFIED',result
            db_before=store.size();max_temps=0
            for i in range(100):
                with store.transaction() as db:
                    record,ext,state,outs=store._rows(db,shape.dataset+'#kayitlar',[str(i)])[str(i)]
                row=assemble(record['frozen'],ext,state,outs);row['sonuc_1g']={'completed':True,'return':i/100}
                report=store.put_rows(shape.dataset+'#kayitlar',[row]);assert report.updated==1
                max_temps=max(max_temps,len(list(Path(temp).glob('.*tmp'))))
            assert checksum(path)==before_hash;assert max_temps==0
            with store.transaction() as db:
                count=db.execute('SELECT count(*) AS n FROM bist_v6.outcomes').fetchone()['n'];assert count==100
            print(json.dumps({'source_bytes':source_size,'source_mib':round(source_size/1048576,2),'records_imported':result['records'],'small_updates':100,'source_unchanged':True,'json_full_rewrites':0,'local_temp_peak':max_temps,'local_temp_bytes':0,'postgres_bytes_before_updates':db_before,'postgres_bytes_after_updates':store.size(),'test_scope':'LOCAL_STORE_AND_MIGRATION_NOT_PRODUCTION'}))
    finally:store.close()

if __name__=='__main__':main()
