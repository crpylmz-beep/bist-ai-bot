"""Streaming UNIQUE recovery under forensic leases; new deletion defaults OFF."""
import copy
import hashlib
import json
import logging
import os
import sqlite3
from collections import OrderedDict
import atomik_temp_temizligi as proof
from history_journal import JournalError
from recovery_journal import RecoveryJournal
from storage_schemas import identity,relation,stream
from proof_workspace import index,WorkspaceDeferred,MAX_ENTRIES,MemoryIndex,SqlIndex,sqlite_issue

RECOVERED='PROVEN_RECOVERED_REDUNDANT'
_seen=OrderedDict()  # At most two bounded hash sets; no record payload.


def deletion_enabled():return os.environ.get('STORAGE_RECOVERY_DELETE_ENABLED','false').strip().lower()=='true'


def stats():
    return dict(temp_only=0,identical=0,final_newer=0,temp_newer=0,final_matches=0,conflicts=0,unresolved=0,journal_added=0,journal_duplicate=0)


def recover(session,temp_fd,final_fd,dataset,identifier,state,deadline):
    from disk_resumable import safe_field,metadata
    target=session.location.runtime/dataset;journal=RecoveryJournal(target)
    temp_stamp=proof.fingerprint(temp_fd);final_stamp=proof.fingerprint(final_fd)
    before=state.get('classification','UNIQUE_RECOVERY_CANDIDATE')
    state.pop('last_recovery',None)  # Never report a previous round's journal adds.
    if state.get('recovery_version')!=5 or 'final_matches' not in state.get('recovery',{}):
        state.update(parser=None,count=0,metadata={},recovery=stats(),recovery_version=5,completed=False,reason=None)
    state['stage']='RECOVERY_BUILD_FINAL';state['index']=proof.canonical([dataset,list(final_stamp)])[:40];session.dirty=True
    target_index=MemoryIndex(final_fd,dataset,deadline) if state.get('fallback_mode') else index(session,final_fd,dataset,deadline)
    if isinstance(target_index,SqlIndex):state['index']=target_index.key
    state['stage']='RECOVERY_COMPARE_TEMP'
    cache_key=(dataset,temp_stamp,final_stamp)
    seen=None
    if isinstance(target_index,SqlIndex):
        try:
            if not target_index.resume_seen(state,identifier):state.update(parser=None,count=0,metadata={},recovery=stats(),reason=None)
        except sqlite3.Error as error:
            sqlite_issue(error,'RESUME_SEEN');target_index.db.rollback()
            state.update(fallback_mode=True,parser=None,count=0,metadata={},recovery=stats(),completed=False)
            session.dirty=True
            raise WorkspaceDeferred('PROOF_SQLITE_FALLBACK_PENDING') from error
    else:
        seen=_seen.get(cache_key)
        if seen is None or len(seen)!=state['count']:
            seen=set();_seen[cache_key]=seen
            state.update(parser=None,count=0,metadata={},recovery=stats(),reason=None)
        _seen.move_to_end(cache_key)
        while len(_seen)>2:_seen.popitem(last=False)
    counters=state['recovery'];start=dict(counters);changed=False;complete=False
    parser=stream(temp_fd,dataset,deadline,state['parser'])
    try:
        # Validation belongs inside the descriptor-owning try/finally.
        operations=journal.operations()
        for field,row in parser.entries():
            if field is not None:
                state['metadata'][safe_field(field)]=metadata(field,row,dataset)
                state['parser']=dict(parser.checkpoint);session.dirty=True;continue
            key=identity(row,dataset);hashed=hashlib.sha256(key.encode()).digest()
            if seen is not None:
                if hashed in seen:raise ValueError('Duplicate record identity')
                if len(seen)>=MAX_ENTRIES:raise WorkspaceDeferred('PROOF_DEFERRED_LOW_WORKSPACE')
            elif target_index.db.execute('SELECT 1 FROM seen WHERE temp=? AND id=?',(identifier,proof.canonical(key))).fetchone():raise ValueError('Duplicate record identity')
            current=target_index.lookup(key);kind=relation(row,current,dataset)
            if kind in ('TEMP_ONLY','TEMP_NEWER_SAFE'):
                # Never acknowledge recovery from an outdated/replaced source.
                from disk_forensik import same_entry
                folder=os.open(session.location.runtime,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:
                    if not same_entry(folder,dataset,final_stamp):raise WorkspaceDeferred('FILE_CHANGED_DURING_RECOVERY')
                finally:os.close(folder)
                try:
                    added=journal.stage(row,kind,current)
                    counters['journal_added' if added else 'journal_duplicate']+=1
                    # Decode/checksum and replay the staged record, not just metadata.
                    operations=journal.operations();op=operations[proof.canonical(key)]
                    if proof.canonical(op['record'])!=proof.canonical(row):raise JournalError('WAL_CONFLICT: replay verification failed')
                except JournalError as error:
                    if error.storage_code!='WAL_CONFLICT':raise
                    counters['conflicts']+=1;state['reason']='RECOVERY_JOURNAL_CONFLICT';kind='CONFLICT'
            if kind=='TEMP_ONLY':counters['temp_only']+=1
            elif kind=='IDENTICAL':counters['identical']+=1
            elif kind=='FINAL_NEWER_SAFE':counters['final_newer']+=1
            elif kind=='TEMP_NEWER_SAFE':counters['temp_newer']+=1
            elif kind=='CONFLICT':
                if state.get('reason')!='RECOVERY_JOURNAL_CONFLICT':counters['conflicts']+=1
                state['reason']='RECOVERY_CONFLICT'
            else:counters['unresolved']+=1;state['reason']='RECOVERY_UNRESOLVED'
            if current is not None:counters['final_matches']+=1
            if seen is not None:seen.add(hashed)
            else:target_index.mark_seen(identifier,key,state['count'])
            state['count']+=1;state['parser']=dict(parser.checkpoint);session.dirty=True
        complete=True
        for field,value in state['metadata'].items():
            other=target_index.metadata.get(field)
            if other is None:counters['unresolved']+=1;continue
            if value['kind']=='clock':
                if proof.history_time(value['value'])>proof.history_time(other['value']):counters['unresolved']+=1
            elif value['kind']=='count':
                if value['value']!=state['count'] or other['value']!=target_index.count:counters['unresolved']+=1
            elif value!=other:counters['unresolved']+=1
        # Journal replay is revalidated even when this source added nothing now.
        with journal.locked():
            journal._operations_unlocked()
            state['recovery_journal_stamp']=None
            if journal.path.exists():
                wal_fd=os.open(journal.path,os.O_RDONLY|os.O_NOFOLLOW)
                try:state['recovery_journal_stamp']=list(proof.fingerprint(wal_fd))
                finally:os.close(wal_fd)
        state['metrics'].update(unique_record_count=counters['temp_only'],changed_record_count=counters['conflicts'],missing_record_count=counters['temp_only'],final_extra_record_count=max(0,target_index.count-counters['final_matches']))
        if counters['conflicts'] or counters['unresolved']:return session._complete(state,'UNIQUE_RECOVERY_CANDIDATE','RECOVERY_CONFLICT' if counters['conflicts'] else 'RECOVERY_UNRESOLVED')
        if counters['temp_only'] or counters['temp_newer']:return session._complete(state,RECOVERED,'RECOVERY_REPLAY_VERIFIED')
        return session._complete(state,'PROVEN_SUBSET_OF_FINAL' if target_index.count>state['count'] else 'PROVEN_OLDER_COMPLETE_COPY','RECOVERY_ALL_RECORDS_IN_FINAL')
    except TimeoutError:
        # A round budget is resumable progress, never a failed source record.
        raise
    except OSError as error:
        # Failed journal I/O has not advanced the row checkpoint. A later
        # successful fsync/replay must not inherit a permanent data conflict.
        error.proof_code='RECOVERY_DEFERRED_JOURNAL_SPACE' if error.errno in (28,122) else 'RECOVERY_JOURNAL_IO'
        raise
    except sqlite3.IntegrityError:
        counters['unresolved']+=1
        return session._complete(state,'UNKNOWN','DUPLICATE_RECORD_ID')
    except sqlite3.Error as error:
        sqlite_issue(error,'COMPARE_TEMP');target_index.db.rollback()
        state.update(fallback_mode=True,parser=None,count=0,metadata={},recovery=stats(),completed=False)
        session.dirty=True
        raise WorkspaceDeferred('PROOF_SQLITE_FALLBACK_PENDING') from error
    except (ValueError,UnicodeError) as error:
        if isinstance(error,WorkspaceDeferred):raise
        state['reason']='DUPLICATE_RECORD_ID' if 'Duplicate' in str(error) else 'JSON_TRUNCATED_OR_UNSUPPORTED_SCHEMA'
        counters['unresolved']+=1
        return session._complete(state,'UNKNOWN',state['reason'])
    finally:
        parser.close()
        if isinstance(target_index,SqlIndex):
            if state.get('completed'):target_index.db.execute('DELETE FROM seen WHERE temp=?',(identifier,))
            target_index.db.commit()
        # Counts describe this source; added/duplicate figures here are this round.
        values=dict(counters);values['journal_added']-=start['journal_added'];values['journal_duplicate']-=start['journal_duplicate']
        values.update(dataset=dataset,temp_fingerprint=identifier,classification_before=before,journal_bytes=journal.path.stat().st_size if journal.path.exists() else 0,eligible_after_recovery=complete and not counters['conflicts'] and not counters['unresolved'],final_only=max(0,target_index.count-counters['final_matches']))
        state['last_recovery']=values
        logging.info('[STORAGE_RECOVERY] %s',values)
