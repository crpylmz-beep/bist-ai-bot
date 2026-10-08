"""Bounded durable AI-history deltas; failed large commits remain explicit failures.

No reader monkeypatch, no asynchronous false acknowledgement. Legacy readers keep
using canonical JSON. Pending intent is merged under the same transaction locks
when headroom is restored. Every committed WAL line has sequence+checksum+fsync.
"""
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import time
import atomik_temp_temizligi as proof
from atomik_depolama import target_lock_name

MAX_WAL=32*1024*1024
MAX_TRANSACTION=8*1024*1024

class JournalError(OSError):
    def __init__(self,code):
        self.storage_code='WAL_CONFLICT' if 'CONFLICT' in code else 'WAL_CORRUPT' if any(k in code for k in ('CHECKSUM','SEQUENCE','CORRUPT','INCOMPLETE','INVALID')) else 'STORAGE_IO'
        super().__init__(errno.EIO,code)


def identity(row):
    result=next((row[k] for k in ('kayit_id','prediction_id','signal_id','result_id','id') if isinstance(row.get(k),str) and row[k]),None)
    if result is None:raise JournalError('WAL_MISSING_STABLE_ID')
    return proof.canonical(result)


def field_patch(old,new):
    result=[]
    for key,value in new.items():
        if key not in old or proof.canonical(old[key])!=proof.canonical(value):
            result.append({'field':key,'before':proof.canonical([key in old,old.get(key)]),'after':value})
    # Never infer deletions. Omitted historical fields/rows are preserved.
    return result


def apply_fields(row,patches,root=False):
    row=dict(row)
    for patch in patches:
        key=patch['field'];after=patch['after']
        before=proof.canonical([key in row,row.get(key)])
        if key in row and proof.canonical(row[key])==proof.canonical(after):continue
        if root and key=='guncelleme':
            if key not in row or proof.history_time(after)>=proof.history_time(row[key]):row[key]=after
            continue
        if root and key=='toplam_kayit':continue  # recomputed from actual retained records
        if before!=patch['before']:raise JournalError('WAL_CONFLICT: unique intent retained')
        row[key]=after
    return row

def apply_chain(row,patches,root=False):
    """Validate CAS chains and resume at the latest already-applied value."""
    row=dict(row);groups={}
    for patch in patches:groups.setdefault(patch['field'],[]).append(patch)
    for key,chain in groups.items():
        if root and key in ('guncelleme','toplam_kayit'):
            row=apply_fields(row,chain,root=True);continue
        previous=None
        for item in chain:
            if previous is not None and item['before']!=proof.canonical([True,previous['after']]) and proof.canonical(item['after'])!=proof.canonical(previous['after']):
                raise JournalError('WAL_CONFLICT: incompatible queued intents retained')
            previous=item
        current=proof.canonical([key in row,row.get(key)])
        if current==chain[0]['before']:start=0
        else:
            applied=[i for i,item in enumerate(chain) if current==proof.canonical([True,item['after']])]
            if not applied:raise JournalError('WAL_CONFLICT: canonical value differs')
            start=max(applied)+1
        if start<len(chain):row[key]=chain[-1]['after']
    return row


class HistoryJournal:
    def __init__(self,target):
        self.target=Path(target)
        from veri_yollari import paths
        location=paths()
        if self.target.absolute().is_relative_to(location.public.absolute()) or self.target.absolute().is_relative_to((location.repo/'webapp').absolute()):raise ValueError('WAL public web root altında tutulamaz')
        self.path=self.target.parent/'.ai-history-pending-v4.wal'
        self.lock=self.target.parent/'.ai-history-pending-v4.lock'

    @contextmanager
    def locked(self):
        fd=os.open(self.lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX);yield
        finally:os.close(fd)

    def transactions(self):
        if not self.path.exists():return
        fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            if os.fstat(fd).st_size>MAX_WAL:raise JournalError('WAL_CAPACITY_EXCEEDED')
            with os.fdopen(os.dup(fd),'rb') as stream:
                expected=1
                while True:
                    line=stream.readline(MAX_TRANSACTION+1)
                    if not line:break
                    if len(line)>MAX_TRANSACTION or not line.endswith(b'\n'):raise JournalError('WAL_INCOMPLETE_TRANSACTION')
                    try:entry=json.loads(line,object_pairs_hook=proof.strict_object)
                    except ValueError:raise JournalError('WAL_CORRUPT_JSON') from None
                    if entry.get('sequence')!=expected or entry.get('checksum')!=proof.canonical(entry.get('payload')):raise JournalError('WAL_CHECKSUM_OR_SEQUENCE')
                    payload=entry['payload']
                    if not isinstance(payload,dict) or not isinstance(payload.get('rows'),list) or not isinstance(payload.get('root'),list):raise JournalError('WAL_INVALID_SCHEMA')
                    yield payload;expected+=1
        finally:os.close(fd)

    def _append_locked(self,payload):
        count=sum(1 for _ in self.transactions())
        entry={'sequence':count+1,'payload':payload,'checksum':proof.canonical(payload)}
        encoded=(json.dumps(entry,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(encoded)>MAX_TRANSACTION:raise OSError(errno.ENOSPC,'WAL transaction limit; intent not acknowledged')
        existing=self.path.stat().st_size if self.path.exists() else 0
        if existing+len(encoded)>MAX_WAL or shutil.disk_usage(self.path.parent).free<len(encoded)+65536:
            raise OSError(errno.ENOSPC,'WAL headroom insufficient; prior pending intent retained')
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            view=memoryview(encoded)
            while view:
                written=os.write(fd,view)
                if written<=0:raise OSError(errno.EIO,'WAL short write')
                view=view[written:]
            os.fsync(fd)
        finally:os.close(fd)
        folder=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(folder)
        finally:os.close(folder)
        logging.info('[STORAGE_WAL] sequence=%d pending_bytes=%d acknowledged_as_canonical=false',count+1,existing+len(encoded))
        return len(encoded)

    def append(self,rows,root=None):
        """Explicit delta API for a controlled batch; fsync before returning."""
        with self.locked():return self._append_locked({'rows':rows,'root':root or []})

    def queue_state(self,value):
        """Stream old history; encode only changed fields and genuinely new rows."""
        if not isinstance(value,dict) or not isinstance(value.get('kayitlar'),list):raise JournalError('WAL_UNSUPPORTED_HISTORY')
        new={};order=[]
        for row in value['kayitlar']:
            key=identity(row)
            if key in new:raise JournalError('WAL_DUPLICATE_STABLE_ID')
            new[key]=row;order.append(key)
        rows=[];seen=set();root={};omitted=0;encoded_bound=0
        fd=os.open(self.target,os.O_RDONLY|os.O_NOFOLLOW)
        stamp=proof.fingerprint(fd);stream=proof.HistoryStream(fd,float('inf'))
        try:
            for field,row in stream.entries():
                from storage_izleme import check_shutdown
                check_shutdown(stamp[2])
                if field is not None:root[field]=row;continue
                key=identity(row)
                if key in seen:raise JournalError('WAL_DUPLICATE_STABLE_ID')
                seen.add(key)
                if key not in new:omitted+=1;continue
                patches=field_patch(row,new[key])
                if patches:
                    op={'id':key,'fields':patches};encoded_bound+=len(json.dumps(op,ensure_ascii=False).encode())
                    if encoded_bound>MAX_TRANSACTION-65536:raise OSError(errno.ENOSPC,'WAL delta exceeds transaction bound; intent not acknowledged')
                    rows.append(op)
            for key in order:
                if key not in seen:
                    op={'id':key,'add':new[key]};encoded_bound+=len(json.dumps(op,ensure_ascii=False).encode())
                    if encoded_bound>MAX_TRANSACTION-65536:raise OSError(errno.ENOSPC,'WAL delta exceeds transaction bound; intent not acknowledged')
                    rows.append(op)
            after=self.target.lstat()
            if stamp!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise JournalError('WAL_SOURCE_CHANGED')
        finally:stream.close();os.close(fd)
        if omitted:logging.warning('[STORAGE_WAL] omitted_history_rows=%d retained=true',omitted)
        with self.locked():return self._append_locked({'rows':rows,'root':field_patch(root,{k:v for k,v in value.items() if k!='kayitlar'})})

    def flush(self):
        """One atomic merge for all committed deltas; remove WAL only after fsync."""
        if not self.path.exists():return 0
        from storage_izleme import critical_storage,StoragePendingError
        if critical_storage(self.target.parent):
            logging.warning('[CRITICAL_STORAGE_MODE] wal_merge=false pending_retained=true')
            raise StoragePendingError()
        from atomik_depolama import _atomic_write_json
        from storage_izleme import WriteTrace
        business=os.open(str(self.target)+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        atomic=os.open(self.target.parent/target_lock_name(self.target.name),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(business,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(atomic,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.locked():
                transactions=list(self.transactions())
                if not transactions:return 0
                merge=StreamingMerge(self.target,transactions);trace=WriteTrace(self.target)
                trace.reason='WAL_COALESCED_COMMIT'
                trace.logical=sum(len(json.dumps(op,ensure_ascii=False,separators=(',',':')).encode()) for tx in transactions for op in tx['rows']+tx['root'])
                try:
                    _atomic_write_json(self.target,merge,trace=trace,lock_already_held=True,journal_merge=True)
                    folder=os.open(self.target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                    try:os.fsync(folder);os.unlink(self.path);os.fsync(folder)
                    finally:os.close(folder)
                    trace.success=True
                    return len(transactions)
                finally:merge.close();trace.finish()
        finally:os.close(atomic);os.close(business)

class StreamingMerge:
    def __init__(self,target,transactions):
        self.target=target;self.transactions=transactions
        self.fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW);self.stamp=proof.fingerprint(self.fd)
        self.operations={};self.root=[]
        for transaction in transactions:
            self.root.extend(transaction['root'])
            for op in transaction['rows']:self.operations.setdefault(op['id'],[]).append(op)
    def iterencode(self,options):
        from storage_izleme import check_shutdown
        encoder=json.JSONEncoder(**options);stream=proof.HistoryStream(self.fd,float('inf'));metadata={};seen=set();count=0
        yield '{\n  "kayitlar": ['
        try:
            for key,row in stream.entries():
                check_shutdown(self.stamp[2])
                if key is not None:metadata[key]=row;continue
                identity_key=identity(row)
                if identity_key in seen:raise JournalError('WAL_DUPLICATE_STABLE_ID')
                seen.add(identity_key)
                operations=self.operations.get(identity_key,[])
                if operations and 'add' in operations[0]:
                    expected=operations[0]['add']
                    patches=[]
                    for op in operations[1:]:
                        if 'add' in op:
                            if proof.canonical(expected)!=proof.canonical(op['add']):raise JournalError('WAL_ADD_CONFLICT')
                        else:patches.extend(op['fields'])
                    expected=apply_chain(expected,patches)
                    from disk_forensik import contained
                    if not contained(expected,row):raise JournalError('WAL_ADD_CONFLICT')
                else:
                    if any('add' in op for op in operations):raise JournalError('WAL_ADD_CONFLICT')
                    row=apply_chain(row,[patch for op in operations for patch in op['fields']])
                if count:yield ','
                yield '\n    '
                for part in encoder.iterencode(row):yield part.replace('\n','\n    ')
                count+=1
            for identity_key,operations in self.operations.items():
                if identity_key in seen:continue
                if 'add' not in operations[0]:raise JournalError('WAL_ROW_NOT_IN_FINAL')
                row=operations[0]['add']
                if identity(row)!=identity_key:raise JournalError('WAL_ADD_ID_MISMATCH')
                patches=[]
                for op in operations[1:]:
                    if 'add' in op:
                        if proof.canonical(row)!=proof.canonical(op['add']):raise JournalError('WAL_ADD_CONFLICT')
                    else:patches.extend(op['fields'])
                row=apply_chain(row,patches)
                if count:yield ','
                yield '\n    '
                for part in encoder.iterencode(row):yield part.replace('\n','\n    ')
                count+=1
            yield '\n  ]'
            metadata=apply_chain(metadata,self.root,root=True);metadata['toplam_kayit']=count
            for key,value in metadata.items():
                yield ',\n  '+json.dumps(key,ensure_ascii=False)+': '
                for part in encoder.iterencode(value):yield part.replace('\n','\n  ')
            yield '\n}'
            after=self.target.lstat()
            if self.stamp!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise JournalError('WAL_SOURCE_CHANGED')
        finally:stream.close()
    def close(self):os.close(self.fd)
