"""Bounded-memory atomic JSON commits. No history migration or deletion."""
import errno
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile


def target_lock_name(name):
    return '.atomic-'+hashlib.sha256(name.encode()).hexdigest()[:24]+'.lock'


def space_guard(directory,required):
    reserve=1024*1024 if required>=1024*1024 else 4096
    free=shutil.disk_usage(directory).free
    if free<required+reserve:
        logging.warning('[DISK_SPACE_GUARD] required_bytes=%d reserve_bytes=%d free_bytes=%d',required,reserve,free)
        raise OSError(errno.ENOSPC,'DISK_SPACE_GUARD: atomic rewrite için boş alan yetersiz')


class BufferedJSON:
    """Buffer small encoder tokens, without allocating a second whole dataset."""
    def __init__(self,stream):self.stream=stream;self.parts=[];self.size=0
    def write(self,value):
        self.parts.append(value);self.size+=len(value)
        if self.size>=65536:self.flush()
    def flush(self):
        if self.parts:self.stream.write(''.join(self.parts));self.parts=[];self.size=0


def atomic_write_json(path,value,*,overwrite=True,prefix='.user-',default=None):
    path=Path(path)
    if path.name.startswith('.user-'):raise ValueError('Reserved atomic temporary namespace')
    options=dict(ensure_ascii=False,indent=2,allow_nan=False)
    if default is not None:options['default']=default
    # Separate I/O lock: existing caller read/modify/write locks remain intact;
    # reacquiring their .lock with another fd would deadlock.
    with (path.parent/target_lock_name(path.name)).open('a') as target_lock:
        fcntl.flock(target_lock,fcntl.LOCK_EX)
        if not overwrite and path.exists():raise FileExistsError(errno.EEXIST,'Immutable target exists')
        # Exact preflight, streamed: serialization failures allocate no temp and
        # large rewrites reserve their full additional copy before mkstemp.
        required=0;encoded_digest=hashlib.sha256()
        for part in json.JSONEncoder(**options).iterencode(value):
            data=part.encode('utf-8');required+=len(data);encoded_digest.update(data)
        if required>=1024*1024 and unchanged_large_file(path,required,encoded_digest.digest()):return
        space_guard(path.parent,required)
        token=hashlib.sha256(path.name.encode()).hexdigest()[:24]
        temp_prefix='.user-v2-'+token+'-' if prefix=='.user-' else prefix
        fd,tmp=tempfile.mkstemp(prefix=temp_prefix,suffix='.tmp',dir=path.parent)
        owned_fd=fd
        try:
            # Lease is kept even after closing the stream, until commit/cleanup.
            fcntl.flock(fd,fcntl.LOCK_EX)
            duplicate_fd=os.dup(fd)
            try:stream=os.fdopen(duplicate_fd,'w',encoding='utf-8')
            except BaseException:
                os.close(duplicate_fd);raise
            with stream:
                buffered=BufferedJSON(stream)
                json.dump(value,buffered,**options);buffered.flush()
                stream.flush();os.fsync(stream.fileno())
            if overwrite:os.replace(tmp,path)
            else:os.link(tmp,path)
            directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            # Do not mask the original ENOSPC/serialization/replace exception.
            try:os.unlink(tmp)
            except FileNotFoundError:pass
            except OSError as error:logging.warning('[DISK] Atomic temp cleanup failed errno=%s',error.errno)
            os.close(owned_fd)


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
