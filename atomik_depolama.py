"""Bounded-memory atomic JSON commits. No history migration or deletion."""
from contextlib import nullcontext,contextmanager
import errno
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import weakref
from storage_izleme import WriteTrace,check_shutdown,critical_storage,LARGE


_thread_locks=weakref.WeakValueDictionary()
_registry_lock=threading.Lock()
@contextmanager
def thread_guard(path):
    key=str(Path(path).absolute())
    with _registry_lock:
        lock=_thread_locks.get(key)
        if lock is None:lock=threading.RLock();_thread_locks[key]=lock
    with lock:yield


def target_lock_name(name):
    return '.atomic-'+hashlib.sha256(name.encode()).hexdigest()[:24]+'.lock'


def space_guard(directory,required):
    reserve=(40*1024*1024 if critical_storage(directory) else 1024*1024) if required>=1024*1024 else 4096
    free=shutil.disk_usage(directory).free
    if free<required+reserve:
        logging.warning('[DISK_SPACE_GUARD] required_bytes=%d reserve_bytes=%d free_bytes=%d',required,reserve,free)
        raise OSError(errno.ENOSPC,'DISK_SPACE_GUARD: atomic rewrite için boş alan yetersiz')


class BufferedJSON:
    """Buffer small encoder tokens, without allocating a second whole dataset."""
    def __init__(self,stream,required=0,trace=None):self.stream=stream;self.parts=[];self.size=0;self.required=required;self.trace=trace
    def write(self,value):
        self.parts.append(value);self.size+=len(value)
        if self.size>=65536:self.flush()
    def flush(self):
        if self.parts:
            check_shutdown(self.required)
            data=''.join(self.parts);self.stream.write(data)
            if self.trace:self.trace.physical+=len(data.encode('utf-8'))
            self.parts=[];self.size=0


def atomic_write_json(path,value,*,overwrite=True,prefix='.user-',default=None):
    trace=WriteTrace(path)
    try:
        with thread_guard(path):answer=_atomic_write_json(path,value,trace=trace,overwrite=overwrite,prefix=prefix,default=default)
        trace.success=True
        return answer
    except BaseException:
        if trace.state not in ('CLEANED','ORPHANED'):
            try:trace.transition('ABORTED')
            except OSError as error:logging.warning('[STORAGE_META] aborted_state_failed errno=%s',error.errno)
        raise
    finally:trace.finish()


def _atomic_write_json(path,value,*,trace,overwrite=True,prefix='.user-',default=None,lock_already_held=False,journal_merge=False):
    path=Path(path)
    if path.name.startswith('.user-'):raise ValueError('Reserved atomic temporary namespace')
    options=dict(ensure_ascii=False,indent=2,allow_nan=False)
    if default is not None:options['default']=default
    # Separate I/O lock: existing caller read/modify/write locks remain intact;
    # reacquiring their .lock with another fd would deadlock.
    try:old_size=path.stat().st_size
    except FileNotFoundError:old_size=0
    check_shutdown(old_size)
    with (nullcontext(None) if lock_already_held else (path.parent/target_lock_name(path.name)).open('a')) as target_lock:
        if target_lock is not None:fcntl.flock(target_lock,fcntl.LOCK_EX)
        check_shutdown(old_size)
        if not overwrite and path.exists():raise FileExistsError(errno.EEXIST,'Immutable target exists')
        # Exact preflight, streamed: serialization failures allocate no temp and
        # large rewrites reserve their full additional copy before mkstemp.
        if overwrite and old_size>=LARGE and path.name=='ai_ogrenme_gecmisi.json':
            same,logical=unchanged_history(path,value)
            trace.logical=logical
            if same:
                trace.reason='SKIP_UNCHANGED_WRITE';return
        required=0;checked=0;encoded_digest=hashlib.sha256()
        for part in encoded_parts(value,options):
            data=part.encode('utf-8');required+=len(data);encoded_digest.update(data)
            if required-checked>=65536:
                check_shutdown(required);checked=required
        if required>=1024*1024 and unchanged_large_file(path,required,encoded_digest.digest()):
            trace.reason='SKIP_UNCHANGED_WRITE';trace.logical=0;return
        check_shutdown(required)
        if not journal_merge and overwrite and required>=LARGE and path.name=='ai_ogrenme_gecmisi.json' and isinstance(value,dict) and isinstance(value.get('kayitlar'),list) and path.exists() and os.environ.get('BIST_DATA_DIR'):
            from history_journal import HistoryJournal
            from veri_yollari import paths
            if path.absolute()!=paths().runtime_file('ai_ogrenme_gecmisi.json').absolute():raise ValueError('Unexpected AI history target; canonical path required')
            journal=HistoryJournal(path)
            guard_error=None
            try:space_guard(path.parent,required)
            except OSError as error:
                if error.errno not in (errno.ENOSPC,errno.EDQUOT):raise
                guard_error=error
            pressure=critical_storage(path.parent) or guard_error is not None
            if pressure or journal.path.exists():
                journal.queue_state(value)
                trace.reason='DURABLE_PENDING_STORAGE_PRESSURE'
                logging.warning('[CRITICAL_STORAGE_MODE] enabled=%s full_rewrite=false pending_intent=true',pressure)
                if guard_error is not None:raise guard_error
                from storage_izleme import StoragePendingError
                raise StoragePendingError()
        space_guard(path.parent,required)
        token=hashlib.sha256(path.name.encode()).hexdigest()[:24]
        temp_prefix='.user-v2-'+token+'-' if prefix=='.user-' else prefix
        fd,tmp=tempfile.mkstemp(prefix=temp_prefix,suffix='.tmp',dir=path.parent)
        owned_fd=fd
        trace.temp=tmp
        try:
            trace.create_metadata(fd);trace.transition('CREATED')
            # Lease is kept even after closing the stream, until commit/cleanup.
            fcntl.flock(fd,fcntl.LOCK_EX)
            duplicate_fd=os.dup(fd)
            try:stream=os.fdopen(duplicate_fd,'w',encoding='utf-8')
            except BaseException:
                os.close(duplicate_fd);raise
            with stream:
                trace.transition('WRITING')
                buffered=BufferedJSON(stream,required,trace)
                if hasattr(value,'iterencode'):
                    for part in value.iterencode(options):buffered.write(part)
                else:json.dump(value,buffered,**options)
                buffered.flush()
                stream.flush();check_shutdown(required);os.fsync(stream.fileno())
                trace.transition('FSYNCED')
            check_shutdown(required);trace.transition('READY_TO_RENAME')
            if overwrite:os.replace(tmp,path)
            else:os.link(tmp,path)
            trace.transition('RENAMED')
            directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        except BaseException:
            try:trace.transition('ABORTED')
            except OSError as error:logging.warning('[STORAGE_META] aborted_state_failed errno=%s',error.errno)
            raise
        finally:
            # Do not mask the original ENOSPC/serialization/replace exception.
            try:os.unlink(tmp)
            except FileNotFoundError:pass
            except OSError as error:logging.warning('[DISK] Atomic temp cleanup failed errno=%s',error.errno)
            os.close(owned_fd)
            try:trace.transition('CLEANED' if not os.path.lexists(tmp) else 'ORPHANED')
            except OSError as error:logging.warning('[STORAGE_META] final_state_failed errno=%s',error.errno)


def unchanged_large_file(path,size,digest):
    """Skip byte-identical large rewrites; never trust only size/mtime."""
    fd=None
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        info=os.fstat(fd)
        if info.st_size!=size:return False
        current=hashlib.sha256()
        while True:
            chunk=os.read(fd,1024*1024)
            if not chunk:break
            current.update(chunk)
        after=path.lstat()
        return current.digest()==digest and (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
    except OSError:return False
    finally:
        if fd is not None:os.close(fd)


def unchanged_history(path,value):
    """Strict content dirty check; only the documented root write clock is ignored.

    No row deletion, reordering, completed-result tolerance or outcome progression
    is applied here. Logical bytes measure entire changed record payloads, not
    bytewise edits; unknown/corrupt schema disables this optimization.
    """
    from atomik_temp_temizligi import HistoryStream,canonical
    if not isinstance(value,dict) or not isinstance(value.get('kayitlar'),list):return False,None
    fd=None;stream=None;count=0;metadata={};same=True;logical=0
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW);info=os.fstat(fd)
        stream=HistoryStream(fd,float('inf'))
        for key,row in stream.entries():
            check_shutdown(info.st_size)
            if key is not None:metadata[key]=row;continue
            if count>=len(value['kayitlar']):same=False
            elif canonical(row)!=canonical(value['kayitlar'][count]):
                same=False;logical+=len(json.dumps(value['kayitlar'][count],ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
            count+=1
        same=same and count==len(value['kayitlar'])
        for row in value['kayitlar'][count:]:logical+=len(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
        if not isinstance(metadata.get('guncelleme'),str) or not isinstance(value.get('guncelleme'),str):return False,logical
        if proof_clock(value['guncelleme'])<proof_clock(metadata['guncelleme']):return False,logical
        old={k:v for k,v in metadata.items() if k!='guncelleme'}
        new={k:v for k,v in value.items() if k not in ('kayitlar','guncelleme')}
        same=same and canonical(old)==canonical(new)
        after=path.lstat()
        same=same and (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
        return same,logical
    except (ValueError,UnicodeError,OSError):return False,None
    finally:
        if stream is not None:stream.close()
        if fd is not None:os.close(fd)


def encoded_parts(value,options):
    return value.iterencode(options) if hasattr(value,'iterencode') else json.JSONEncoder(**options).iterencode(value)


def proof_clock(value):
    from atomik_temp_temizligi import history_time
    return history_time(value)
