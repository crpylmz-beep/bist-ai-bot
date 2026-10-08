"""Pooled, parameterized, transactional row store. No startup schema mutation."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
from .config import Settings,StorageError
from .records import split,assemble,digest,identity,row_time,now


@dataclass
class WriteResult:
    inserted:int=0
    updated:int=0
    duplicates:int=0
    conflicts:int=0

    def add(self,other):
        for key in self.__dict__:setattr(self,key,getattr(self,key)+getattr(other,key))
        return self


class PostgresStore:
    def __init__(self,settings=None,pool=None):
        self.settings=settings or Settings.from_env();self.settings.require_database()
        if pool is None:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
            pool=ConnectionPool(self.settings.dsn,min_size=0,max_size=self.settings.pool_size,timeout=self.settings.timeout,open=False,kwargs={'row_factory':dict_row,'connect_timeout':self.settings.timeout,'options':'-c timezone=Europe/Istanbul -c synchronous_commit=on'},reconnect_timeout=self.settings.timeout)
            pool.open()
        self.pool=pool

    def close(self):self.pool.close()

    @contextmanager
    def transaction(self):
        try:
            with self.pool.connection(timeout=self.settings.timeout) as connection:
                with connection.transaction():yield connection
        except StorageError:raise
        except Exception as error:
            logging.error('[STORAGE_V6] code=POSTGRES_OPERATION_FAILED type=%s sqlstate=%s',type(error).__name__,getattr(error,'sqlstate',None))
            raise StorageError('POSTGRES_OPERATION_FAILED') from None

    @staticmethod
    def json(value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    def migrate(self):
        applied=[]
        with self.transaction() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext('bist-v6-schema'))")
            db.execute('CREATE SCHEMA IF NOT EXISTS bist_v6')
            db.execute('CREATE TABLE IF NOT EXISTS bist_v6.schema_migrations(version text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())')
            known={r['version']:r['checksum'] for r in db.execute('SELECT version,checksum FROM bist_v6.schema_migrations')}
            for path in sorted((Path(__file__).parent/'migrations').glob('*.sql')):
                sql=path.read_text();checksum=hashlib.sha256(sql.encode()).hexdigest()
                if path.name in known:
                    if known[path.name]!=checksum:raise StorageError('SCHEMA_MIGRATION_CHECKSUM_MISMATCH')
                    continue
                db.execute(sql,prepare=False)
                db.execute('INSERT INTO bist_v6.schema_migrations(version,checksum) VALUES(%s,%s)',(path.name,checksum));applied.append(path.name)
        return applied

    def ready(self):
        with self.transaction() as db:
            row=db.execute("SELECT to_regclass('bist_v6.schema_migrations') AS name").fetchone()
            if row['name'] is None:raise StorageError('SCHEMA_MIGRATION_REQUIRED')
            versions={r['version']:r['checksum'] for r in db.execute('SELECT version,checksum FROM bist_v6.schema_migrations')}
            for path in (Path(__file__).parent/'migrations').glob('*.sql'):
                if versions.get(path.name)!=hashlib.sha256(path.read_bytes()).hexdigest():raise StorageError('SCHEMA_MIGRATION_REQUIRED')
        return True

    def hashes(self,dataset):
        with self.transaction() as db:return {r['record_id']:r['current_hash'] for r in db.execute('SELECT record_id,current_hash FROM bist_v6.records WHERE dataset=%s',(dataset,))}

    def _rows(self,db,dataset,ids=None):
        query='SELECT * FROM bist_v6.records WHERE dataset=%s';params=[dataset]
        if ids is not None:query+=' AND record_id=ANY(%s)';params.append(ids)
        records=list(db.execute(query+' ORDER BY ordinal,record_id',params));keys=[r['record_id'] for r in records]
        extensions={};states={};outcomes={}
        if keys:
            for r in db.execute('SELECT * FROM bist_v6.record_extensions WHERE dataset=%s AND record_id=ANY(%s)',(dataset,keys)):extensions.setdefault(r['record_id'],{})[r['field']]=r['payload']
            for r in db.execute('SELECT * FROM bist_v6.row_states WHERE dataset=%s AND record_id=ANY(%s)',(dataset,keys)):states[r['record_id']]=r['payload']
            for r in db.execute('SELECT * FROM bist_v6.outcomes WHERE dataset=%s AND record_id=ANY(%s)',(dataset,keys)):outcomes.setdefault(r['record_id'],{})[r['horizon']]=r['payload']
        return {r['record_id']:(r,extensions.get(r['record_id'],{}),states.get(r['record_id'],{}),outcomes.get(r['record_id'],{})) for r in records}

    def read_rows(self,dataset):
        return [row for _,row in self.read_pairs(dataset)]

    def read_pairs(self,dataset):
        import uuid
        with self.transaction() as db:
            with db.cursor(name='v6_'+uuid.uuid4().hex) as cursor:
                cursor.itersize=self.settings.batch_size
                cursor.execute('''SELECT r.record_id,r.frozen,s.payload AS state,
                  (SELECT jsonb_object_agg(field,payload) FROM bist_v6.record_extensions e WHERE e.dataset=r.dataset AND e.record_id=r.record_id) AS ext,
                  (SELECT jsonb_object_agg(horizon,payload) FROM bist_v6.outcomes o WHERE o.dataset=r.dataset AND o.record_id=r.record_id) AS outs
                  FROM bist_v6.records r LEFT JOIN bist_v6.row_states s USING(dataset,record_id) WHERE r.dataset=%s ORDER BY r.ordinal,r.record_id''',(dataset,))
                for row in cursor:yield row['record_id'],assemble(row['frozen'],row['ext'] or {},row['state'] or {},row['outs'] or {})

    def put_rows(self,dataset,rows,kind='prediction',receipt=None,conservative=False,outbox_receipt=None):
        rows=list(rows)
        if len(rows)>self.settings.batch_size:raise StorageError('STORAGE_BATCH_LIMIT')
        keyed={identity(item[1],item[0]) if isinstance(item,tuple) else identity(item):item[1] if isinstance(item,tuple) else item for item in rows}
        if len(keyed)!=len(rows):raise StorageError('STORAGE_DUPLICATE_SOURCE_ID')
        report=WriteResult()
        with self.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(dataset,))
            if outbox_receipt:
                old=db.execute('SELECT checksum FROM bist_v6.outbox_receipts WHERE journal_id=%s AND sequence=%s',outbox_receipt[:2]).fetchone()
                if old:
                    if old['checksum']!=outbox_receipt[2]:raise StorageError('OUTBOX_CHECKSUM_CONFLICT')
                    return WriteResult(duplicates=len(rows))
            existing=self._rows(db,dataset,list(keyed))
            ordinal=db.execute('SELECT COALESCE(MAX(ordinal),-1) AS n FROM bist_v6.records WHERE dataset=%s',(dataset,)).fetchone()['n']
            inserts=[];states_to_save=[];extensions=[];outcomes=[];hash_updates=[]
            for key,incoming in keyed.items():
                frozen,state,new_outcomes=split(incoming,dataset);before=existing.get(key);new_hash=digest(incoming)
                if before and before[0]['current_hash']==new_hash:report.duplicates+=1;continue
                old_frozen={};old_states={};old_outcomes={};ext={}
                if before:
                    record,ext,old_states,old_outcomes=before;old_frozen={**record['frozen'],**ext}
                    conflict=bool(set(frozen)-set(old_frozen)) or any(k in frozen and digest(v)!=digest(frozen[k]) for k,v in old_frozen.items()) or any(k in new_outcomes and digest(v)!=digest(new_outcomes[k]) for k,v in old_outcomes.items())
                    if conservative and old_states!=state:
                        from storage_schemas import SCHEMAS,relation
                        name=dataset.split('#')[0].split('/')[-1]
                        if name in SCHEMAS:
                            status=relation(incoming,assemble(record['frozen'],ext,old_states,old_outcomes),name)
                            if status in ('IDENTICAL','FINAL_NEWER_SAFE'):report.duplicates+=1;continue
                            conflict=conflict or status not in ('TEMP_ONLY','TEMP_NEWER_SAFE')
                        else:conflict=True
                    if conflict:
                        if receipt:db.execute('INSERT INTO bist_v6.import_conflicts VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(receipt['source_id'],receipt['field'],key,new_hash))
                        db.execute('INSERT INTO bist_v6.conflicts(dataset,record_id,incoming_hash,incoming,reason) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(dataset,key,new_hash,self.json(incoming),'IMMUTABLE_OR_COMPLETED_OUTCOME_CONFLICT'));report.conflicts+=1;continue
                    frozen={**old_frozen,**frozen};state={**old_states,**state};new_outcomes={**old_outcomes,**new_outcomes}
                    merged=assemble(frozen,{},state,new_outcomes);new_hash=digest(merged)
                    if record['current_hash']==new_hash:report.duplicates+=1;continue
                    report.updated+=1
                else:
                    ordinal+=1;symbol=incoming.get('sembol') or incoming.get('symbol');symbol=symbol if isinstance(symbol,str) and 0<len(symbol)<=32 else None
                    model=incoming.get('model_version') or incoming.get('engine_version');model=str(model) if model is not None else None
                    at=row_time(incoming)
                    inserts.append((dataset,key,kind,symbol,at,model,self.json(frozen),digest(frozen),new_hash,ordinal))
                    if symbol:db.execute('INSERT INTO bist_v6.symbols(symbol) VALUES(%s) ON CONFLICT DO NOTHING',(symbol,))
                    report.inserted+=1
                states_to_save.append((dataset,key,self.json(state)))
                for horizon,value in new_outcomes.items():
                    if horizon in old_outcomes:continue
                    match=re.fullmatch(r'sonuc_(\d+)g',horizon);sessions=int(match[1]) if match else None
                    outcomes.append((dataset,key,horizon,sessions,self.json(value),digest(value)))
                if before:hash_updates.append((new_hash,dataset,key))
            with db.cursor() as cursor:
                if inserts:cursor.executemany('INSERT INTO bist_v6.records(dataset,record_id,record_kind,symbol,predicted_at,model_version,frozen,frozen_hash,current_hash,ordinal) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',inserts)
                if extensions:cursor.executemany('INSERT INTO bist_v6.record_extensions VALUES(%s,%s,%s,%s,%s)',extensions)
                if outcomes:cursor.executemany('INSERT INTO bist_v6.outcomes(dataset,record_id,horizon,horizon_sessions,payload,checksum) VALUES(%s,%s,%s,%s,%s,%s)',outcomes)
                if states_to_save:cursor.executemany('INSERT INTO bist_v6.row_states VALUES(%s,%s,%s) ON CONFLICT(dataset,record_id) DO UPDATE SET payload=EXCLUDED.payload WHERE bist_v6.row_states.payload IS DISTINCT FROM EXCLUDED.payload',states_to_save)
                if hash_updates:cursor.executemany('UPDATE bist_v6.records SET current_hash=%s WHERE dataset=%s AND record_id=%s',hash_updates)
            if report.inserted or report.updated:
                db.execute('INSERT INTO bist_v6.dataset_versions VALUES(%s,1) ON CONFLICT(dataset) DO UPDATE SET revision=bist_v6.dataset_versions.revision+1',(dataset.split('#')[0],))
            if receipt:
                source_id=receipt['source_id']
                db.execute("INSERT INTO bist_v6.import_sources(source_id,dataset,fingerprint,raw_sha256,cursor,status) VALUES(%s,%s,%s,%s,%s,'IMPORTING') ON CONFLICT(source_id) DO UPDATE SET cursor=COALESCE(bist_v6.import_sources.cursor,'{}'::jsonb) || EXCLUDED.cursor,updated_at=now()",(source_id,receipt['dataset'],self.json(receipt['fingerprint']),receipt['sha256'],self.json({receipt['field']:receipt['position']})))
                for ordinal,(key,row) in enumerate(keyed.items(),receipt['position']-len(keyed)):
                    db.execute('INSERT INTO bist_v6.import_proofs(source_id,collection,record_id,checksum,ordinal) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(source_id,receipt['field'],key,digest(row),ordinal))
            if outbox_receipt and not report.conflicts:db.execute('INSERT INTO bist_v6.outbox_receipts VALUES(%s,%s,%s)',outbox_receipt)
        return report

    def publish_document(self,shape,metadata,source_hash=None,conservative=False,members=None,source_id=None,member_deltas=None):
        with self.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(shape.dataset,))
            if conservative:
                previous=db.execute('SELECT metadata FROM bist_v6.documents WHERE dataset=%s',(shape.dataset,)).fetchone()
                if previous:
                    for key,value in previous['metadata'].items():
                        if key in metadata and value!=metadata[key] and key not in ('guncelleme','updated_at','toplam_kayit'):raise StorageError('OUTBOX_ROOT_METADATA_CONFLICT')
                    metadata={**previous['metadata'],**metadata}
                    for key in ('guncelleme','updated_at'):
                        if key in previous['metadata'] and key in metadata and str(previous['metadata'][key])>str(metadata[key]):metadata=dict(metadata,**{key:previous['metadata'][key]})
            if shape.kind=='tomorrow_snapshot':
                db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(shape.dataset,))
                existing=db.execute('SELECT metadata FROM bist_v6.documents WHERE dataset=%s',(shape.dataset,)).fetchone()
                if existing is not None and digest(existing['metadata'])!=digest(metadata):raise StorageError('IMMUTABLE_SNAPSHOT_METADATA_CONFLICT')
            for field in shape.fields:
                ids=members.get(field) if members is not None else None
                if member_deltas and field in member_deltas:
                    delta=member_deltas[field]
                    previous=db.execute('SELECT ids FROM bist_v6.document_projections WHERE dataset=%s AND collection=%s',(shape.dataset,field)).fetchone()
                    ids=previous['ids'] if previous else []
                    checksum=digest(ids)
                    if checksum!=delta['after']:
                        if checksum!=delta['before']:raise StorageError('OUTBOX_PROJECTION_CONFLICT')
                        removed=set(delta['removed']);ids=[key for key in ids if key not in removed]
                        for addition in delta['added']:
                            anchor=addition['after'];position=0 if anchor is None else ids.index(anchor)+1
                            ids.insert(position,addition['id'])
                        if digest(ids)!=delta['after']:raise StorageError('OUTBOX_PROJECTION_CHECKSUM_MISMATCH')
                if source_id:
                    ids=[row['record_id'] for row in db.execute('SELECT record_id FROM bist_v6.import_proofs WHERE source_id=%s AND collection=%s ORDER BY ordinal,record_id',(source_id,field))]
                if ids is None:continue
                checksum=digest(ids)
                previous=db.execute('SELECT checksum FROM bist_v6.document_projections WHERE dataset=%s AND collection=%s',(shape.dataset,field)).fetchone()
                if previous and previous['checksum']==checksum:continue
                if previous and shape.kind=='tomorrow_snapshot':raise StorageError('IMMUTABLE_SNAPSHOT_MEMBERSHIP_CONFLICT')
                db.execute('INSERT INTO bist_v6.document_projections VALUES(%s,%s,%s,%s) ON CONFLICT(dataset,collection) DO UPDATE SET ids=EXCLUDED.ids,checksum=EXCLUDED.checksum',(shape.dataset,field,self.json(ids),checksum))
            db.execute('INSERT INTO bist_v6.documents(dataset,metadata,collections,source_hash) VALUES(%s,%s,%s,%s) ON CONFLICT(dataset) DO UPDATE SET metadata=EXCLUDED.metadata,collections=EXCLUDED.collections,source_hash=EXCLUDED.source_hash,updated_at=now() WHERE bist_v6.documents.metadata IS DISTINCT FROM EXCLUDED.metadata OR bist_v6.documents.source_hash IS DISTINCT FROM EXCLUDED.source_hash OR bist_v6.documents.collections IS DISTINCT FROM EXCLUDED.collections',(shape.dataset,self.json(metadata),self.json(shape.fields),source_hash))

    def document(self,shape):
        from .records import set_field
        with self.transaction() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            row=db.execute('SELECT * FROM bist_v6.documents WHERE dataset=%s',(shape.dataset,)).fetchone()
            if row is None:raise StorageError('POSTGRES_DATASET_NOT_MIGRATED')
            result=dict(row['metadata'])
            for field,mode in row['collections'].items():
                projection=db.execute('SELECT ids FROM bist_v6.document_projections WHERE dataset=%s AND collection=%s',(shape.dataset,field)).fetchone()
                if projection is None:raise StorageError('POSTGRES_PROJECTION_NOT_VERIFIED')
                values={} if mode=='mapping' else [];ids=projection['ids']
                for offset in range(0,len(ids),self.settings.batch_size):
                    keys=ids[offset:offset+self.settings.batch_size];records=self._rows(db,shape.dataset+'#'+field,keys)
                    for key in keys:
                        if key not in records:raise StorageError('POSTGRES_PROJECTION_RECORD_MISSING')
                        record,ext,state,outs=records[key];value=assemble(record['frozen'],ext,state,outs)
                        if mode=='mapping':values[key]=value
                        else:values.append(value)
                set_field(result,field,values)
            if 'toplam_kayit' in result:result['toplam_kayit']=len(result.get('kayitlar',[]))
        return result

    def verified_source(self,shape):
        with self.transaction() as db:
            return bool(db.execute("SELECT 1 FROM bist_v6.import_sources WHERE dataset=%s AND status IN ('VERIFIED','POSTGRES_NATIVE') LIMIT 1",(shape.dataset,)).fetchone())

    def size(self):
        with self.transaction() as db:return int(db.execute('SELECT pg_database_size(current_database()) AS bytes').fetchone()['bytes'])

    def import_cursor(self,source_id,field):
        with self.transaction() as db:
            row=db.execute('SELECT cursor FROM bist_v6.import_sources WHERE source_id=%s',(source_id,)).fetchone()
        return int((row['cursor'] if row else {}).get(field,0))

    def import_conflicts(self,source_id):
        with self.transaction() as db:return int(db.execute('SELECT count(*) AS n FROM bist_v6.import_conflicts WHERE source_id=%s',(source_id,)).fetchone()['n'])

    def finish_import(self,source_id,dataset,fingerprint,raw,status):
        with self.transaction() as db:
            db.execute("INSERT INTO bist_v6.import_sources(source_id,dataset,fingerprint,raw_sha256,status,records_verified) VALUES(%s,%s,%s,%s,%s,(SELECT count(*) FROM bist_v6.import_proofs WHERE source_id=%s)) ON CONFLICT(source_id) DO UPDATE SET status=EXCLUDED.status,records_verified=EXCLUDED.records_verified,updated_at=now()",(source_id,dataset,self.json(fingerprint),raw,status,source_id))

    def record_job(self,job_id,payload):
        with self.transaction() as db:db.execute('INSERT INTO bist_v6.job_states VALUES(%s,%s,now()) ON CONFLICT(job_id) DO UPDATE SET payload=EXCLUDED.payload,updated_at=now() WHERE bist_v6.job_states.payload IS DISTINCT FROM EXCLUDED.payload',(job_id,self.json(payload)))

    def record_usage(self,day,backend,sample):
        with self.transaction() as db:db.execute('INSERT INTO bist_v6.storage_usage VALUES(%s,%s,%s,now()) ON CONFLICT(day,backend) DO UPDATE SET sample=EXCLUDED.sample,measured_at=now()',(day,backend,self.json(sample)))

    def record_archive(self,archive_id,manifest):
        with self.transaction() as db:db.execute('INSERT INTO bist_v6.archives VALUES(%s,%s,%s,%s,%s,%s,now()) ON CONFLICT(archive_id) DO NOTHING',(archive_id,manifest['raw_sha256'],manifest['compressed_sha256'],manifest['raw_size'],manifest['compressed_size'],self.json(manifest)))

    def record_error(self,job_id,error):
        from gorev_hatalari import describe
        from .records import ISTANBUL
        from datetime import datetime
        issue=describe(error)
        day=datetime.now(ISTANBUL).date()
        checksum=digest({'code':issue['code'],'type':type(error).__name__})
        with self.transaction() as db:db.execute('INSERT INTO bist_v6.task_errors(job_id,day,error_code,error_hash,safe_payload) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(job_id,day,error_hash) DO UPDATE SET occurrences=bist_v6.task_errors.occurrences+1',(job_id,day,issue['code'],checksum,self.json(issue)))

    def record_quality(self,dataset,record_id,flags):
        allowed={'missing','stale','unverified','coverage','source','data_timestamp','reason_code'}
        if not isinstance(flags,dict) or set(flags)-allowed:raise StorageError('QUALITY_FIELDS_INVALID')
        with self.transaction() as db:db.execute('INSERT INTO bist_v6.record_quality VALUES(%s,%s,%s) ON CONFLICT(dataset,record_id) DO UPDATE SET flags=EXCLUDED.flags',(dataset,record_id,self.json(flags)))

    def register_source(self,source_id,metadata):
        if not isinstance(metadata,dict) or set(metadata)-{'provider','exchange','timeframe','format','version'}:raise StorageError('SOURCE_METADATA_FIELDS_INVALID')
        with self.transaction() as db:db.execute('INSERT INTO bist_v6.data_sources VALUES(%s,%s) ON CONFLICT(source_id) DO UPDATE SET metadata=EXCLUDED.metadata',(source_id,self.json(metadata)))

    def revision(self,dataset):
        with self.transaction() as db:
            row=db.execute('SELECT revision FROM bist_v6.dataset_versions WHERE dataset=%s',(dataset,)).fetchone()
            return int(row['revision']) if row else 0

    def projected_pairs(self,dataset,ids):
        with self.transaction() as db:
            for offset in range(0,len(ids),self.settings.batch_size):
                keys=ids[offset:offset+self.settings.batch_size];records=self._rows(db,dataset,keys)
                for key in keys:
                    if key not in records:raise StorageError('POSTGRES_PROJECTION_RECORD_MISSING')
                    row,ext,state,outs=records[key]
                    yield key,assemble(row['frozen'],ext,state,outs)
