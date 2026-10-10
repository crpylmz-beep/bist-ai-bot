"""Read-only source inventory and resumable bounded import. Default is DRY_RUN."""
import hashlib
import json
import os
from pathlib import Path
import stat
import ijson
from .config import StorageError
from .records import Shape,document_parts,row_key,digest

MAX_RECORD=8*1024*1024


def fingerprint(path):
    st=Path(path).lstat()
    if not stat.S_ISREG(st.st_mode):raise StorageError('SOURCE_NOT_REGULAR')
    return {'device':st.st_dev,'inode':st.st_ino,'size':st.st_size,'mtime_ns':st.st_mtime_ns}


def checksum(path):
    before=fingerprint(path);hashed=hashlib.sha256()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        while block:=source.read(1024*1024):hashed.update(block)
    if fingerprint(path)!=before:raise StorageError('SOURCE_CHANGED')
    return hashed.hexdigest()


def pairs(path,field,mode):
    # Streaming parser; repeated scans are intentional to avoid materializing history.
    with Path(path).open('rb') as source:
        items=ijson.kvitems(source,field,use_float=True) if mode=='mapping' else ((None,row) for row in ijson.items(source,field+'.item',use_float=True))
        for key,row in items:
            if not isinstance(row,dict) or len(json.dumps(row,ensure_ascii=False))>MAX_RECORD:raise StorageError('SOURCE_RECORD_INVALID')
            yield key,row


def metadata(path,shape):
    """Capture only scalar/container metadata, never materialize managed arrays."""
    from ijson.common import ObjectBuilder
    result={};actual={};builder=None;prefix_root=None;depth=0;builder_size=0
    keys=[]
    with Path(path).open('rb') as stream:
        for prefix,event,value in ijson.parse(stream,use_float=True):
            if event=='start_map':keys.append(set())
            elif event=='end_map':keys.pop()
            elif event=='map_key':
                if value in keys[-1]:raise StorageError('SOURCE_DUPLICATE_FIELD')
                keys[-1].add(value)
            if len(keys)>64:raise StorageError('SOURCE_DEPTH_LIMIT')
            excluded=next((field for field in shape.fields if prefix==field or prefix.startswith(field+'.')),None)
            if excluded:
                if prefix==excluded and event in ('start_array','start_map'):
                    expected='start_map' if shape.fields[excluded]=='mapping' else 'start_array'
                    if event!=expected:raise StorageError('SOURCE_COLLECTION_INVALID')
                    actual[excluded]=shape.fields[excluded]
                continue
            if prefix=='' or event=='map_key':continue
            if builder is None:
                if prefix=='pozitif_havuz':continue
                builder=ObjectBuilder();prefix_root=prefix;depth=0
            builder_size+=len(str(value).encode()) if value is not None else 1
            if builder_size>MAX_RECORD:raise StorageError('SOURCE_METADATA_LIMIT')
            builder.event(event,value)
            if event in ('start_map','start_array'):depth+=1
            elif event in ('end_map','end_array'):depth-=1
            if depth==0:
                from .records import set_field
                set_field(result,prefix_root,builder.value);builder=None;builder_size=0
    if not actual:raise StorageError('SOURCE_COLLECTION_MISSING')
    return Shape(shape.dataset,actual,shape.kind),result


class Migrator:
    def __init__(self,store=None,batch_size=100):self.store=store;self.batch_size=batch_size

    def run(self,path,shape,apply=False,budget_records=None,max_records=None):
        path=Path(path)
        if not path.exists():return {'mode':'APPLY' if apply else 'DRY_RUN','status':'UNRESOLVED','error':'SOURCE_NOT_FOUND','records':0,'source_changed':False}
        before=fingerprint(path);raw=checksum(path);source_id=digest({'dataset':shape.dataset,'sha256':raw})
        report={'mode':'APPLY' if apply else 'DRY_RUN','source_id':source_id,'sha256':raw,'size':before['size'],'records':0,'conflicts':0,'status':'SCANNING','source_changed':False}
        if apply and self.store is None:raise StorageError('POSTGRES_NOT_CONFIGURED')
        try:
            actual,meta=metadata(path,shape)
            for field,mode in actual.fields.items():
                dataset=shape.dataset+'#'+field;cursor=0
                if apply:cursor=self.store.import_cursor(source_id,field)
                batch=[];position=0;seen=set()
                for key,row in pairs(path,field,mode):
                    if max_records is not None and report['records']>=max_records:
                        raise StorageError('SOURCE_RECORD_LIMIT')
                    identity=row_key(shape,field,row,key)
                    if identity in seen:raise StorageError('SOURCE_DUPLICATE_ID')
                    seen.add(identity);position+=1;report['records']+=1
                    if position<=cursor:continue
                    batch.append((identity,row))
                    if len(batch)>=self.batch_size:
                        if fingerprint(path)!=before:raise StorageError('SOURCE_CHANGED')
                        if apply:
                            outcome=self.store.put_rows(dataset,batch,shape.kind,receipt={'source_id':source_id,'dataset':shape.dataset,'fingerprint':before,'sha256':raw,'field':field,'position':position},conservative=True)
                            report['conflicts']+=outcome.conflicts
                        batch=[]
                        if budget_records and report['records']>=budget_records:
                            report['status']='BUDGET_EXHAUSTED';return report
                if batch and apply:
                    outcome=self.store.put_rows(dataset,batch,shape.kind,receipt={'source_id':source_id,'dataset':shape.dataset,'fingerprint':before,'sha256':raw,'field':field,'position':position},conservative=True)
                    report['conflicts']+=outcome.conflicts
            if fingerprint(path)!=before or checksum(path)!=raw:raise StorageError('SOURCE_CHANGED')
            if apply:
                if self.store.import_conflicts(source_id):report['conflicts']=max(report['conflicts'],1)
                if report['conflicts']==0:
                    self.store.publish_document(actual,meta,raw,source_id=source_id)
                    self.store.finish_import(source_id,shape.dataset,before,raw,'VERIFIED')
                else:self.store.finish_import(source_id,shape.dataset,before,raw,'UNRESOLVED')
            report['status']='UNRESOLVED' if report['conflicts'] else 'VERIFIED'
        except (ValueError,ijson.JSONError,StorageError) as error:
            report['status']='UNRESOLVED';report['error']=getattr(error,'storage_code','SOURCE_JSON_INVALID')
            report['source_changed']=report['error']=='SOURCE_CHANGED'
        return report

    def recovery(self,target,shape,apply=False):
        """V5 journal read without creating its lock or changing source bytes."""
        from recovery_journal import RecoveryJournal
        journal=RecoveryJournal(target)
        if not journal.path.exists():return {'status':'ABSENT','records':0}
        raw=checksum(journal.path);operations=journal._operations_unlocked()
        rows=[op['record'] for op in operations.values()]
        field=next(iter(shape.fields));conflicts=0
        if apply:
            for offset in range(0,len(rows),self.batch_size):
                batch=[(row_key(shape,field,row),row) for row in rows[offset:offset+self.batch_size]]
                result=self.store.put_rows(shape.dataset+'#'+field,batch,shape.kind,conservative=True);conflicts+=result.conflicts
        if checksum(journal.path)!=raw:raise StorageError('SOURCE_CHANGED')
        return {'status':'UNRESOLVED' if conflicts else 'VERIFIED','records':len(rows),'conflicts':conflicts,'sha256':raw,'source_deleted':False}
