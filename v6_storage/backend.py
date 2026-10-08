"""Opt-in history routing. Legacy remains the default and imports no DB driver."""
import hashlib
import logging
import os
from pathlib import Path
import threading
from .config import Settings,StorageError
from .records import shape_for,document_parts,row_key,digest,Shape

_lock=threading.RLock()
_store=None
_store_settings=None
_known={}
_active_ids={}


def store(settings=None):
    global _store,_store_settings
    settings=settings or Settings.from_env()
    with _lock:
        if _store is None or _store_settings!=settings:
            if _store is not None:_store.close()
            from .postgres import PostgresStore
            _store=PostgresStore(settings);_store_settings=settings
        return _store


def shape(path):
    from veri_yollari import paths
    return shape_for(path,paths())


def guard(settings,selected):
    if not settings.cutover_ack:raise StorageError('POSTGRES_CUTOVER_NOT_APPROVED')
    database=store(settings);database.ready()
    if not database.verified_source(selected):raise StorageError('POSTGRES_SOURCE_NOT_VERIFIED')
    return database


def read(path):
    settings=Settings.from_env()
    if settings.mode!='postgres':
        guard_rollback(path)
        return False,None
    selected=shape(path)
    if selected is None or selected.kind=='tomorrow_snapshot':return False,None
    if selected.kind in ('signal','signal_outcome') and not Path(path).exists():
        if not settings.cutover_ack:raise StorageError('POSTGRES_CUTOVER_NOT_APPROVED')
        database=store(settings);database.ready()
        if not database.verified_source(selected):return False,None
    database=guard(settings,selected);document=database.document(selected)
    actual,_,collections=document_parts(selected,document)
    for field,mode in actual.fields.items():
        rows=collections[field];items=rows.items() if mode=='mapping' else ((None,row) for row in rows)
        _known[actual.dataset+'#'+field]={row_key(actual,field,row,key):digest(row) for key,row in items}
        _active_ids[actual.dataset+'#'+field]=list(_known[actual.dataset+'#'+field])
    return True,document


def write_document(database,selected,value):
    actual,meta,collections=document_parts(selected,value)
    members={}
    for field,mode in actual.fields.items():
        dataset=actual.dataset+'#'+field;items=collections[field].items() if mode=='mapping' else ((None,row) for row in collections[field])
        batch=[];seen=set();known=database.hashes(dataset);members[field]=[]
        for key,row in items:
            key=row_key(actual,field,row,key)
            if key in seen:raise StorageError('STORAGE_DUPLICATE_SOURCE_ID')
            seen.add(key);members[field].append(key)
            if known.get(key)==digest(row):continue
            batch.append((key,row))
            if len(batch)>=database.settings.batch_size:
                from storage_izleme import check_shutdown
                check_shutdown(sum(len(str(item[1])) for item in batch))
                if database.put_rows(dataset,batch,actual.kind).conflicts:raise StorageError('IMMUTABLE_RECORD_CONFLICT')
                batch=[]
        if batch and database.put_rows(dataset,batch,actual.kind).conflicts:raise StorageError('IMMUTABLE_RECORD_CONFLICT')
    database.publish_document(actual,meta,members=members)
    for field in actual.fields:
        dataset=actual.dataset+'#'+field
        _known[dataset]=database.hashes(dataset);_active_ids[dataset]=members[field]


def queue_pending(selected,value):
    """Only deltas based on a previously successful read; bounded V5-proven WAL."""
    from history_journal import HistoryJournal
    from veri_yollari import paths
    actual,meta,collections=document_parts(selected,value)
    root=paths().runtime;root.mkdir(mode=0o700,parents=True,exist_ok=True)
    journal=HistoryJournal(root/'v6-history')
    token=hashlib.sha256(actual.dataset.encode()).hexdigest()[:24]
    journal.path=root/('.v6-pending-'+token+'.wal');journal.lock=root/('.v6-pending-'+token+'.lock')
    count=0;deltas={}
    for field,mode in actual.fields.items():
        dataset=actual.dataset+'#'+field
        previous=_active_ids.get(dataset,list(_known.get(dataset,{})))
        items=collections[field].items() if mode=='mapping' else ((None,row) for row in collections[field])
        current=[row_key(actual,field,row,key) for key,row in items]
        old=set(previous);new=set(current)
        if [key for key in previous if key in new]!=[key for key in current if key in old]:raise StorageError('OUTBOX_PROJECTION_REORDER_REQUIRES_RETRY')
        additions=[];anchor=None
        for key in current:
            if key not in old:additions.append({'id':key,'after':anchor})
            anchor=key
        deltas[field]={'before':digest(previous),'after':digest(current),'removed':[key for key in previous if key not in new],'added':additions}
    def append_unique(rows):
        payload={'rows':rows,'root':[{'dataset':actual.dataset,'fields':actual.fields,'kind':actual.kind,'metadata':meta,'membership_deltas':deltas}]}
        with journal.locked():
            checksum=digest(payload)
            if any(digest(previous)==checksum for previous in journal.transactions()):return False
            journal._append_locked(payload);return True
    for field,mode in actual.fields.items():
        dataset=actual.dataset+'#'+field
        if dataset not in _known:raise StorageError('POSTGRES_UNAVAILABLE_NO_VERIFIED_BASELINE')
        items=collections[field].items() if mode=='mapping' else ((None,row) for row in collections[field]);batch=[]
        for key,row in items:
            key=row_key(actual,field,row,key)
            if _known[dataset].get(key)==digest(row):continue
            batch.append({'dataset':dataset,'id':key,'record':row,'kind':actual.kind})
            if len(batch)>=100:append_unique(batch);count+=len(batch);batch=[]
        if batch:append_unique(batch);count+=len(batch)
    if count==0:
        key='metadata:'+digest(meta)
        append_unique([{'dataset':actual.dataset+'#@metadata','id':key,'record':{'id':key,'metadata':meta},'kind':'metadata'}])
    logging.error('[STORAGE_V6] code=POSTGRES_PENDING rows=%d canonical_ack=false',count)


def before_write(path,value,overwrite=True):
    settings=Settings.from_env()
    if settings.mode!='postgres':
        guard_rollback(path)
        return False
    selected=shape(path)
    if selected is None or selected.kind=='tomorrow_snapshot':return False
    if not overwrite:raise StorageError('POSTGRES_CREATE_ONLY_NOT_SUPPORTED')
    from recovery_journal import apply_overlay
    value=apply_overlay(path,value)
    try:
        if selected.kind in ('signal','signal_outcome') and not Path(path).exists():
            if not settings.cutover_ack:raise StorageError('POSTGRES_CUTOVER_NOT_APPROVED')
            database=store(settings);database.ready()
            actual,meta,_=document_parts(selected,value)
            mark_cutover(path,selected)
            write_document(database,selected,value)
            database.finish_import('native:'+selected.dataset,selected.dataset,{},None,'POSTGRES_NATIVE')
            from atomik_depolama import _atomic_write_json
            from storage_izleme import WriteTrace
            from .records import set_field
            sentinel=dict(meta)
            for field,mode in actual.fields.items():set_field(sentinel,field,{} if mode=='mapping' else [])
            Path(path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            trace=WriteTrace(path)
            try:_atomic_write_json(path,sentinel,trace=trace,overwrite=False);trace.success=True
            finally:trace.finish()
        else:
            database=guard(settings,selected)
            mark_cutover(path,selected)
            write_document(database,selected,value)
    except StorageError as error:
        if error.storage_code=='POSTGRES_OPERATION_FAILED':queue_pending(selected,value)
        raise
    return True


def after_write(path,value):
    settings=Settings.from_env()
    if settings.mode=='legacy':return
    selected=shape(path)
    if selected is None:return
    if settings.mode=='postgres' and selected.kind!='tomorrow_snapshot':return
    from recovery_journal import apply_overlay,read_document
    value=read_document(path) if settings.mode=='shadow' else apply_overlay(path,value)
    database=store(settings);database.ready();write_document(database,selected,value)
    # Shadow compare is real assembled content, not a forced success flag.
    actual=database.document(selected)
    if digest(actual)!=digest(value):
        logging.error('[STORAGE_V6] code=SHADOW_MISMATCH dataset=%s',selected.dataset)
        raise StorageError('SHADOW_MISMATCH')
    logging.info('[STORAGE_V6] code=SHADOW_MATCH dataset=%s',selected.dataset)


def replay(journal,database):
    count=0
    for sequence,payload in enumerate(journal.transactions(),1):
        rows=payload['rows']
        datasets={row['dataset'] for row in rows}
        if len(datasets)!=1:raise StorageError('OUTBOX_DATASET_INVALID')
        dataset=next(iter(datasets));receipt=(journal.path.name,sequence,digest(payload))
        result=database.put_rows(dataset,[(row['id'],row['record']) for row in rows],rows[0]['kind'],conservative=True,outbox_receipt=receipt)
        if result.conflicts:raise StorageError('OUTBOX_IMMUTABLE_CONFLICT')
        for root in payload['root']:database.publish_document(Shape(root['dataset'],root['fields'],root['kind']),root['metadata'],conservative=True,member_deltas=root.get('membership_deltas'))
        count+=result.inserted+result.updated
    return count  # WAL retained; no automatic deletion or truncation.


def marker(path):
    token=hashlib.sha256(str(Path(path).absolute()).encode()).hexdigest()[:24]
    from veri_yollari import paths
    return paths().runtime/('.v6-cutover-'+token+'.json')


def mark_cutover(path,selected):
    from atomik_depolama import atomic_write_json
    target=marker(path)
    if not target.exists():atomic_write_json(target,{'dataset':selected.dataset,'status':'POSTGRES_ACTIVE'})


def guard_rollback(path):
    if Path(path).name.startswith('.v6-cutover-'):return
    target=marker(path)
    if not target.exists():return
    import json
    if json.loads(target.read_text()).get('status')!='LEGACY_ROLLBACK_VERIFIED':raise StorageError('LEGACY_ROLLBACK_REQUIRES_VERIFIED_EXPORT')


def certify_rollback(path,database):
    # Explicit operator call only, after adopting a verified export. Never alters source.
    import json
    selected=shape(path)
    if selected is None:raise StorageError('SOURCE_SCHEMA_UNSUPPORTED')
    with Path(path).open() as source:legacy=json.load(source)
    if digest(legacy)!=digest(database.document(selected)):raise StorageError('LEGACY_ROLLBACK_CHECKSUM_MISMATCH')
    from atomik_depolama import atomic_write_json
    atomic_write_json(marker(path),{'dataset':selected.dataset,'status':'LEGACY_ROLLBACK_VERIFIED','checksum':digest(legacy)})


def file_signature(path):
    settings=Settings.from_env();selected=shape(path)
    if settings.mode=='postgres' and selected and selected.kind!='tomorrow_snapshot':
        return ('postgres',guard(settings,selected).revision(selected.dataset))
    info=Path(path).stat()
    return (info.st_mtime_ns,info.st_size)
