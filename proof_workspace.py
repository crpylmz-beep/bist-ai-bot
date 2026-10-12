"""Content-free SQLite diagnostics and bounded record-offset RAM fallback."""
import errno
import hashlib
import json
import logging
import os
import shutil
import sqlite3
from collections import OrderedDict
import atomik_temp_temizligi as proof
from storage_schemas import stream,identity

RESERVE=8*1024*1024
MAX_ENTRIES=180000
_cache=OrderedDict()  # At most one final-index; payloads are never cached.


class WorkspaceDeferred(ValueError):pass


def sqlite_issue(error,stage):
    number=getattr(error,'sqlite_errorcode',None)
    base=number&255 if isinstance(number,int) else None
    code={sqlite3.SQLITE_FULL:'PROOF_DEFERRED_LOW_WORKSPACE',
          sqlite3.SQLITE_BUSY:'PROOF_INDEX_LOCKED',sqlite3.SQLITE_LOCKED:'PROOF_INDEX_LOCKED',
          sqlite3.SQLITE_CANTOPEN:'PROOF_WORKSPACE_UNAVAILABLE',
          sqlite3.SQLITE_IOERR:'PROOF_WORKSPACE_IO',
          sqlite3.SQLITE_CORRUPT:'PROOF_INDEX_CORRUPT',
          sqlite3.SQLITE_NOTADB:'PROOF_INDEX_CORRUPT'}.get(base,'PROOF_SQLITE_ERROR')
    if getattr(error,'storage_code',None) in ('WAL_CORRUPT','WAL_CONFLICT'):code='RECOVERY_JOURNAL_'+error.storage_code[4:]
    elif getattr(error,'proof_code',None) in ('RECOVERY_DEFERRED_JOURNAL_SPACE','RECOVERY_JOURNAL_IO'):code=error.proof_code
    elif getattr(error,'errno',None) in (errno.EMFILE,errno.ENFILE):code='PROOF_DESCRIPTOR_LIMIT'
    elif getattr(error,'errno',None) in (errno.ENOSPC,errno.EDQUOT):code='PROOF_DEFERRED_LOW_WORKSPACE'
    elif getattr(error,'errno',None) in (errno.EACCES,errno.ENOENT):code='PROOF_WORKSPACE_UNAVAILABLE'
    elif isinstance(error,OSError):code='PROOF_WORKSPACE_IO'
    logging.warning('[DISK_FORENSIC] proof_error code=%s stage=%s sqlite_code=%s errno=%s payload_logged=false',code,stage,number,getattr(error,'errno',None))
    return code


def headroom(directory):
    if shutil.disk_usage(directory).free<RESERVE:raise WorkspaceDeferred('PROOF_DEFERRED_LOW_WORKSPACE')


class MemoryIndex:
    """<=180k hashed identity -> byte offset/length, one cached final, no JSON copy.

    The conservative per-entry allowance is 256 bytes (<46 MiB). Completed index
    is reusable; evictions/restarts invalidate fallback parser progress safely.
    """
    def __init__(self,fd,dataset,deadline):
        self.fd=fd;self.dataset=dataset;key=(dataset,proof.fingerprint(fd))
        self.state=_cache.get(key)
        if self.state is None:
            _cache.clear();self.state={'rows':{},'parser':None,'metadata':{},'completed':False};_cache[key]=self.state
        if not self.state['completed']:
            parser=stream(fd,dataset,deadline,self.state['parser'])
            try:
                for field,row in parser.entries():
                    if field is None:
                        key=hashlib.sha256(identity(row,dataset).encode()).digest()
                        if key in self.state['rows']:raise ValueError('Duplicate record identity')
                        if len(self.state['rows'])>=MAX_ENTRIES:raise WorkspaceDeferred('PROOF_DEFERRED_LOW_WORKSPACE')
                        self.state['rows'][key]=parser.last_span
                    else:
                        from disk_resumable import metadata,safe_field
                        self.state['metadata'][safe_field(field)]=metadata(field,row,dataset)
                    self.state['parser']=dict(parser.checkpoint)
                self.state['completed']=True
            finally:parser.close()
        self.count=len(self.state['rows']);self.metadata=self.state['metadata']

    def lookup(self,key):
        entry=self.state['rows'].get(hashlib.sha256(key.encode()).digest())
        if entry is None:return None
        return json.loads(os.pread(self.fd,entry[1],entry[0]),object_pairs_hook=proof.strict_object)


class SqlIndex:
    def __init__(self,session,fd,dataset,deadline):
        self.fd=fd;self.key,self.state,self.db=session._final(fd,dataset,deadline)
        self.count=self.state['count'];self.metadata=self.state['metadata']
    def resume_seen(self,state,identifier):
        self.db.execute('DELETE FROM seen WHERE temp=? AND ordinal>=?',(identifier,state['count']))
        count=self.db.execute('SELECT COUNT(*) FROM seen WHERE temp=?',(identifier,)).fetchone()[0]
        if count!=state['count']:
            self.db.execute('DELETE FROM seen WHERE temp=?',(identifier,));return False
        return True
    def mark_seen(self,identifier,key,ordinal):
        self.db.execute('INSERT INTO seen VALUES(?,?,?)',(identifier,proof.canonical(key),ordinal))
    def lookup(self,key):
        entry=self.db.execute('SELECT offset,length FROM records WHERE id=?',(proof.canonical(key),)).fetchone()
        if entry is None:return None
        return json.loads(os.pread(self.fd,entry[1],entry[0]),object_pairs_hook=proof.strict_object)


def index(session,fd,dataset,deadline):
    try:
        if getattr(session,'workspace_error',None):raise session.workspace_error
        headroom(session.index_dir)
        return SqlIndex(session,fd,dataset,deadline)
    except TimeoutError:
        # Preserve index/checkpoint progress on an ordinary maintenance budget.
        raise
    except (sqlite3.Error,OSError,WorkspaceDeferred,ValueError) as error:
        if isinstance(error,ValueError) and not isinstance(error,WorkspaceDeferred) and str(error)!='PROOF_INDEX_CAPACITY':raise
        if isinstance(error,(sqlite3.Error,OSError)):sqlite_issue(error,'BUILD_FINAL')
        else:logging.warning('[DISK_FORENSIC] proof_error code=PROOF_DEFERRED_LOW_WORKSPACE stage=BUILD_FINAL fallback=RAM_OFFSETS')
        for db in session.dbs.values():
            try:db.rollback()
            except sqlite3.Error:pass
        # In-memory progress cannot outlive rolled-back database contents.
        for item in session.data['finals'].values():
            item.update(parser=None,count=0,metadata={},completed=False)
        logging.info('[DISK_FORENSIC] fallback=RAM_OFFSETS dataset=%s',dataset)
        return MemoryIndex(fd,dataset,deadline)
