"""Read-only forensic classification; unlink only proven redundant runtime scratch."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import errno
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from zoneinfo import ZoneInfo
import atomik_temp_temizligi as proof
from atomik_depolama import target_lock_name

SAFE_FINALS=proof.SAFE_FINALS | {
    'gun_ici_sonuclar.json','performans_durum.json','sinyal_performansi.json',
    'indicator_performance_state.json','intraday_signal_performance_state.json',
    'haber_zeka_gecmisi.json','makro_ai_gecmisi.json','kap_son_gorulen.json',
    'makro_gorulen.json','canli_motor_durum.json','gun_ici_gecersiz_semboller.json',
    'ai_agirliklari.json','yarin_kalibrasyon.json','gun_ici_agirliklari.json',
    'ai_fiyat_teyit.json','haber_dedup.json','karar_hata_gunlugu.json'}
PROVEN={'PROVEN_REDUNDANT','PROVEN_SUBSET_OF_FINAL','PROVEN_OLDER_COMPLETE_COPY'}
CLASSES=PROVEN | {'ACTIVE_OR_RECENT','UNIQUE_RECOVERY_CANDIDATE','UNKNOWN'}
SMALL_LIMIT=8*1024*1024
ROOT_WRITE_CLOCKS={'performans_durum.json','indicator_performance_state.json','intraday_signal_performance_state.json','canli_motor_durum.json','gun_ici_performans_durum.json'}
TARGET_FREE=1024**3
_worker_scope=ContextVar('disk_worker_scope',default=None)


@contextmanager
def worker_cleanup_scope(directory):
    token=_worker_scope.set(str(Path(directory).absolute()))
    try:yield
    finally:_worker_scope.reset(token)


def worker_scope_matches(location):
    return _worker_scope.get()==str(Path(location.runtime).absolute())


def same_entry(folder,name,stamp):
    current=os.stat(name,dir_fd=folder,follow_symlinks=False)
    return (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns)==stamp


def suffix_matches(temp_fd,final_fd,deadline=float("inf")):
    os.lseek(temp_fd,0,0)
    os.lseek(final_fd,os.fstat(final_fd).st_size-os.fstat(temp_fd).st_size,0)
    while True:
        proof.check_deadline(deadline)
        chunk=os.read(temp_fd,1024*1024)
        if not chunk:return True
        if os.read(final_fd,len(chunk))!=chunk:return False


def small_json(fd):
    if os.fstat(fd).st_size>SMALL_LIMIT:raise ValueError('STREAM_ADAPTER_REQUIRED')
    os.lseek(fd,0,0)
    data=b''
    while len(data)<=SMALL_LIMIT:
        chunk=os.read(fd,min(65536,SMALL_LIMIT+1-len(data)))
        if not chunk:break
        data+=chunk
    if len(data)>SMALL_LIMIT:raise ValueError('STREAM_ADAPTER_REQUIRED')
    return json.loads(data,object_pairs_hook=proof.strict_object,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def contained(old,new):
    """Strict recursive containment. No outcome/score tolerances or truthy defaults."""
    if type(old) is not type(new):return False
    if isinstance(old,dict):return all(k in new and contained(v,new[k]) for k,v in old.items())
    if isinstance(old,list):
        if not old:return True
        keys=('kayit_id','prediction_id','signal_id','result_id','id','timestamp')
        identity=next((k for k in keys if all(isinstance(v,dict) and isinstance(v.get(k),str) and v[k] for v in old+new)),None)
        if identity:
            target={v[identity]:v for v in new}
            if len(target)!=len(new) or len({v[identity] for v in old})!=len(old):raise ValueError('DUPLICATE_STABLE_ID')
            return all(v[identity] in target and contained(v,target[v[identity]]) for v in old)
        # Lists without proven stable identities require complete exact values.
        return proof.canonical(old)==proof.canonical(new)
    return proof.canonical(old)==proof.canonical(new)


def semantic_small(temp_fd,final_fd,dataset):
    old,new=small_json(temp_fd),small_json(final_fd)
    if type(old) is not type(new):return 'UNKNOWN','ROOT_SCHEMA_MISMATCH'
    # For non-AI datasets even outcome changes remain unique. Only explicit
    # root write clocks can advance; no arbitrary record-field exclusions.
    if isinstance(old,dict):
        old=dict(old);new=dict(new)
        for key in (('updated_at','guncelleme') if dataset in ROOT_WRITE_CLOCKS else ()):
            if key not in old:continue
            if key not in new:return 'UNIQUE_RECOVERY_CANDIDATE','ROOT_FIELD_NOT_IN_FINAL'
            if proof.canonical(old[key])!=proof.canonical(new[key]):
                try:
                    a=datetime.fromisoformat(str(old[key]));b=datetime.fromisoformat(str(new[key]))
                    if a.tzinfo is None or b.tzinfo is None or a>b:return 'UNKNOWN','UNPROVEN_ROOT_TIMESTAMP'
                except ValueError:return 'UNKNOWN','UNPROVEN_ROOT_TIMESTAMP'
            old.pop(key);new.pop(key)
    if contained(old,new):return 'PROVEN_SUBSET_OF_FINAL','ALL_STRUCTURAL_VALUES_CONTAINED'
    return 'UNIQUE_RECOVERY_CANDIDATE','VALUE_OR_RECORD_NOT_IN_FINAL'


def classify_locked(temp_fd,final_fd,dataset,indexes,hashes,deadline,identified=False,details=None):
    """Both descriptors are read-only. Return class/reason without copying payloads."""
    if details is not None:details.update(comparison_method='BYTE_PROOF',schema='UNVERIFIED',unique_record_count=None,changed_record_count=None,missing_record_count=None,final_extra_record_count=None)
    ts,fs=proof.fingerprint(temp_fd),proof.fingerprint(final_fd)
    if ts[2]==fs[2]:
        tk=('temp',ts);fk=('final',fs)
        if tk not in hashes:hashes[tk]=proof.digest_fd(temp_fd,deadline)
        if fk not in hashes:hashes[fk]=proof.digest_fd(final_fd,deadline)
        if hashes[tk]==hashes[fk]:return 'PROVEN_REDUNDANT','SHA256_AND_SIZE_EQUAL'
    if ts[2]<fs[2] and (proof.prefix_matches(temp_fd,final_fd,deadline) or suffix_matches(temp_fd,final_fd,deadline)):
        return 'PROVEN_REDUNDANT','EVERY_SCRATCH_BYTE_ALREADY_IN_FINAL'
    if dataset in ('ai_ogrenme_gecmisi.json','tahmin_gecmisi.json','gun_ici_sonuclar.json'):
        if dataset=='gun_ici_sonuclar.json':
            stream=proof.HistoryStream(temp_fd,deadline)
            try:
                first=next((value for key,value in stream.entries() if key is None),None)
                if not isinstance(first,dict) or not {'id','sembol','sinyal_zamani','giris_fiyati','sonuclar'}<=first.keys():return 'UNKNOWN','LEGACY_SCHEMA_UNSUPPORTED'
            finally:stream.close()
        key=(dataset,fs)
        if key not in indexes:indexes[key]=proof.HistoryIndex(final_fd,deadline,record_key='tahminler' if dataset=='tahmin_gecmisi.json' else 'kayitlar',ai_legacy=dataset=='ai_ogrenme_gecmisi.json')
        answer=indexes[key].assess(temp_fd,deadline)
        if details is not None:details.update(indexes[key].metrics,comparison_method='STREAM_SQLITE_FROZEN_OUTCOME',schema={'ai_ogrenme_gecmisi.json':'AI_HISTORY','tahmin_gecmisi.json':'PREDICTION_HISTORY','gun_ici_sonuclar.json':'INTRADAY_HISTORY'}[dataset])
        return answer
    if not identified:
        if dataset in ('indicator_performance_state.json','sinyal_performansi.json'):
            old,new=small_json(temp_fd),small_json(final_fd)
            version='INDICATOR_PERFORMANCE_V1' if dataset=='indicator_performance_state.json' else 'SIGNAL_ANALYSIS_V1'
            if not isinstance(old,dict) or not isinstance(new,dict) or old.get('version')!=version or new.get('version')!=version:return 'UNKNOWN','LEGACY_SCHEMA_UNSUPPORTED'
        else:return 'UNKNOWN','LEGACY_DATASET_NOT_IDENTIFIED'
    if details is not None:details.update(comparison_method='STRICT_STRUCTURAL_CONTAINMENT',schema='ROUTED_JSON')
    return semantic_small(temp_fd,final_fd,dataset)


def write_manifest(location,entries):
    if not entries:return True
    from kullanici_kayitlari import atomic_json
    target=location.runtime/'disk_cleanup_manifest.json'
    # Fixed bounded last-run manifest; never append unlimited history/backups.
    value={'version':2,'cleanup_timestamp':datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(),
           'removed_count':len(entries),'removed_bytes':sum(e['size'] for e in entries),
           'retained_entries':min(256,len(entries)),'entries':entries[-256:]}
    try:atomic_json(target,value);return True
    except OSError as error:
        logging.warning('[DISK_FORENSIC] manifest_write_failed errno=%s',error.errno);return False


def inspect_atomic_temps(location,*,cleanup=False,clock=time.time,budget_seconds=180,require_worker_lock=True,skip_identifiers=None,release_locks_during_proof=False):
    result=dict(scanned=0,eligible=0,removed=0,freed_bytes=0,skipped_recent=0,skipped_active=0,
                skipped_unverified=0,skipped_unique=0,skipped_unknown=0,errors=0)
    class_bytes={key:0 for key in CLASSES};counts={key:0 for key in CLASSES};reasons={};eligible_bytes=0;entries=[];findings=[]
    indexes={};hashes={};root_fd=folder_fd=None
    if not location.root:return result
    if cleanup and worker_scope_matches(location):
        from disk_koruma import report
        report(location)
    before=shutil.disk_usage(location.root).free;deadline=time.monotonic()+budget_seconds
    try:
        root_fd=os.open(location.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        folder_fd=os.open('runtime',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root_fd)
        names=[entry.name for entry in os.scandir(folder_fd)]
        finals=sorted(n for n in names if n in SAFE_FINALS)
        candidates=[]
        for name in names:
            if not name.startswith('.user-'):continue
            try:size=os.stat(name,dir_fd=folder_fd,follow_symlinks=False).st_size
            except OSError:size=0
            candidates.append((size,name))
        for size,name in sorted(candidates,key=lambda v:(-v[0],v[1])):
            masked=hashlib.sha256(name.encode()).hexdigest()[:16]
            if skip_identifiers and masked in skip_identifiers:continue
            details=dict(masked_file=masked,age_seconds=None,probable_target_final=None,schema='UNVERIFIED',comparison_method='NONE',unique_record_count=None,changed_record_count=None,missing_record_count=None,final_extra_record_count=None)
            result['scanned']+=1;temp_fd=None;classification='UNKNOWN';reason='UNRECOGNIZED_TEMP';matched=None
            try:
                if not proof.TEMP_PATTERN.fullmatch(name):raise ValueError('UNRECOGNIZED_TEMP')
                if time.monotonic()>deadline:raise TimeoutError('BUDGET_EXHAUSTED')
                temp_fd=proof.open_regular(folder_fd,name);stamp=proof.fingerprint(temp_fd);info=os.fstat(temp_fd);details['age_seconds']=max(0,int(clock()-info.st_mtime))
                if info.st_nlink!=1:raise ValueError('HARDLINK_OR_RECOVERY_ALIAS')
                if clock()-info.st_mtime<proof.MIN_AGE:
                    classification='ACTIVE_OR_RECENT';reason='MINIMUM_AGE';result['skipped_recent']+=1
                else:
                    try:fcntl.flock(temp_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:classification='ACTIVE_OR_RECENT';reason='ACTIVE_FD_LEASE'
                    if classification!='ACTIVE_OR_RECENT':
                        opened=proof.foreign_open(temp_fd)
                        if opened is True:classification='ACTIVE_OR_RECENT';reason='OPEN_BY_ANOTHER_PROCESS'
                        elif opened is None:reason='PROCESS_AUDIT_UNCERTAIN'
                        elif cleanup and require_worker_lock and not worker_scope_matches(location):reason='WORKER_LOCK_REQUIRED'
                        else:
                            # v2 destination tokens are routing hints, not proof.
                            token=re.match(r'^\.user-v2-([0-9a-f]{24})-',name)
                            routed=[f for f in finals if not token or hashlib.sha256(f.encode()).hexdigest()[:24]==token[1]]
                            reason='FINAL_MISSING_OR_DATASET_UNKNOWN'
                            if token:
                                known=[f for f in SAFE_FINALS if hashlib.sha256(f.encode()).hexdigest()[:24]==token[1]]
                                details['probable_target_final']=known[0] if len(known)==1 else None
                            best=None
                            for final in routed:
                                business=atomic=final_fd=None
                                try:
                                    if time.monotonic()>deadline:raise TimeoutError('BUDGET_EXHAUSTED')
                                    for lock_name in (final+'.lock',target_lock_name(final)):
                                        try:
                                            flags=os.O_RDONLY|os.O_NOFOLLOW if not cleanup else os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW
                                            lock=os.open(lock_name,flags,0o600,dir_fd=folder_fd)
                                        except FileNotFoundError:continue  # read-only diagnostic: do not create anything
                                        if business is None:business=lock
                                        else:atomic=lock
                                        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                                    final_fd=proof.open_regular(folder_fd,final);final_stamp=proof.fingerprint(final_fd)
                                    if release_locks_during_proof:
                                        # Background indexing reads held descriptors. Atomic
                                        # writers remain free to replace the final meanwhile;
                                        # any replacement invalidates proof at the restat below.
                                        for fd in (atomic,business):
                                            if fd is not None:os.close(fd)
                                        atomic=business=None
                                    candidate=classify_locked(temp_fd,final_fd,final,indexes,hashes,deadline,identified=bool(token),details=details)
                                    if release_locks_during_proof and cleanup and candidate[0] in PROVEN:
                                        if cleanup and ('temp',stamp) not in hashes:
                                            hashes[('temp',stamp)]=proof.digest_fd(temp_fd,deadline)
                                        for lock_name in (final+'.lock',target_lock_name(final)):
                                            lock=os.open(lock_name,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=folder_fd)
                                            if business is None:business=lock
                                            else:atomic=lock
                                            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                                    if not same_entry(folder_fd,final,final_stamp) or not same_entry(folder_fd,name,stamp):
                                        candidate=('UNKNOWN','FILE_CHANGED_DURING_PROOF')
                                    if candidate[0] in PROVEN:
                                        classification,reason=candidate;matched=final
                                        details['probable_target_final']=final
                                        eligible_bytes+=stamp[2];result['eligible']+=1
                                        if cleanup:
                                            # All target locks and scratch lease are still held.
                                            digest=hashes.get(('temp',stamp)) or proof.digest_fd(temp_fd,deadline)
                                            if not same_entry(folder_fd,final,final_stamp) or not same_entry(folder_fd,name,stamp):
                                                eligible_bytes-=stamp[2];result['eligible']-=1;classification='UNKNOWN';reason='FILE_CHANGED_BEFORE_UNLINK';matched=None
                                            else:
                                                free_before=shutil.disk_usage(location.root).free
                                                try:os.unlink(name,dir_fd=folder_fd)
                                                except OSError as error:
                                                    result['errors']+=1;reason='UNLINK_FAILED'
                                                    logging.warning('[DISK_FORENSIC] unlink_failed errno=%s',error.errno)
                                                    break
                                                result['removed']+=1;result['freed_bytes']+=stamp[2]
                                                os.close(temp_fd);temp_fd=None
                                                entries.append({'timestamp':datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(),'masked_file':masked,'classification':classification,'size':stamp[2],'hash_prefix':digest.hex()[:16],'reason':reason,'dataset':matched,'free_before':free_before,'free_after':shutil.disk_usage(location.root).free})  # release unlinked blocks before measuring space
                                                logging.info('[DISK_FORENSIC] removed_class=%s size=%d free_bytes=%d',classification,stamp[2],shutil.disk_usage(location.root).free)
                                        break
                                    # Unique classification only belongs to a known schema;
                                    # same-shape JSON from unrelated datasets is not sufficient.
                                    if candidate[0]=='UNIQUE_RECOVERY_CANDIDATE' and (final in ('ai_ogrenme_gecmisi.json','tahmin_gecmisi.json','gun_ici_sonuclar.json','indicator_performance_state.json','sinyal_performansi.json') or token):best=(candidate,final,dict(details))
                                    elif best is None and reason in ('FINAL_MISSING_OR_DATASET_UNKNOWN','LEGACY_DATASET_NOT_IDENTIFIED'):reason=candidate[1]
                                except BlockingIOError:reason='FINAL_LOCK_BUSY'
                                except TimeoutError:reason='BUDGET_EXHAUSTED';break
                                except (ValueError,UnicodeError,json.JSONDecodeError,sqlite3.IntegrityError) as error:
                                    reason='STREAM_ADAPTER_REQUIRED' if str(error)=='STREAM_ADAPTER_REQUIRED' else ('DUPLICATE_RECORD_ID' if 'Duplicate record identity' in str(error) or isinstance(error,sqlite3.IntegrityError) else 'JSON_TRUNCATED_OR_UNSUPPORTED_SCHEMA')
                                except Exception as error:
                                    # SQLite/index storage failure remains visible; no deletion.
                                    result['errors']+=1;reason='PROOF_IO_ERROR'
                                    logging.warning('[DISK_FORENSIC] proof_error type=%s errno=%s',type(error).__name__,getattr(error,'errno',None))
                                finally:
                                    for fd in (final_fd,atomic,business):
                                        if fd is not None:os.close(fd)
                            if classification=='UNKNOWN' and best is not None and reason!='BUDGET_EXHAUSTED':
                                (classification,reason),matched,best_details=best;details.update(best_details)
                    if classification=='ACTIVE_OR_RECENT':result['skipped_active']+=1
            except TimeoutError:reason='BUDGET_EXHAUSTED'
            except (ValueError,UnicodeError) as error:reason=str(error) if str(error) in ('UNRECOGNIZED_TEMP','HARDLINK_OR_RECOVERY_ALIAS') else 'INVALID_OR_UNSUPPORTED_SCHEMA'
            except OSError as error:
                reason='UNSAFE_PATH' if error.errno in (errno.ELOOP,errno.ENOENT) else 'INSPECTION_IO_ERROR'
                if reason=='INSPECTION_IO_ERROR':result['errors']+=1
            finally:
                if temp_fd is not None:os.close(temp_fd)
            counts[classification]+=1;class_bytes[classification]+=size;reasons[reason]=reasons.get(reason,0)+1
            if classification=='UNKNOWN':result['skipped_unknown']+=1;result['skipped_unverified']+=1
            elif classification=='UNIQUE_RECOVERY_CANDIDATE':result['skipped_unique']+=1;result['skipped_unverified']+=1
            # Returned diagnostic records contain only whitelisted dataset labels,
            # never private filenames or payloads. Bounded optional read-only report.
            details.update(classification=classification,reason=reason,reason_code=reason,size=size,dataset=matched,eligible_for_cleanup=classification in PROVEN)
            if matched:details['probable_target_final']=matched
            if len(findings)<256:findings.append(details)
            logging.info('[DISK_FORENSIC_FILE] %s',details)
    except OSError as error:
        result['errors']+=1;logging.warning('[DISK_FORENSIC] inspection_error errno=%s',error.errno)
    finally:
        for index in indexes.values():index.close()
        for fd in (folder_fd,root_fd):
            if fd is not None:os.close(fd)
    if cleanup and not write_manifest(location,entries):result['errors']+=1
    result.update(before_free=before,after_free=shutil.disk_usage(location.root).free,eligible_bytes=eligible_bytes,
                  classifications=counts,reasons=reasons,findings=findings,target_free=TARGET_FREE)
    logging.info('[DISK_FORENSIC] scanned=%d proven_redundant=%d proven_subset=%d proven_old_copy=%d recent=%d unique_recovery=%d unknown=%d eligible_bytes=%d reasons=%s',
                 result['scanned'],counts['PROVEN_REDUNDANT'],counts['PROVEN_SUBSET_OF_FINAL'],counts['PROVEN_OLDER_COMPLETE_COPY'],counts['ACTIVE_OR_RECENT'],counts['UNIQUE_RECOVERY_CANDIDATE'],counts['UNKNOWN'],eligible_bytes,reasons)
    from disk_koruma import disk_health
    health=disk_health(location)
    result.update(classification_bytes=class_bytes,percent_used=health['percent_used'],target_1gib_reached=health['free']>=1024**3,target_2gib_reached=health['free']>=2*1024**3)
    logging.info('[DISK_FORENSIC_SUMMARY] %s',{k:{'file_count':counts[k],'total_bytes':class_bytes[k]} for k in sorted(CLASSES)})
    logging.info('[DISK_TEMP_CLEANUP] scanned=%d classified=%d proven_redundant=%d proven_subset=%d proven_older_complete=%d unique_recovery=%d unknown=%d recent=%d active=%d removed=%d freed_bytes=%d before_free=%d after_free=%d percent_used=%.2f target_1gib_reached=%s target_2gib_reached=%s',result['scanned'],sum(counts.values()),counts['PROVEN_REDUNDANT'],counts['PROVEN_SUBSET_OF_FINAL'],counts['PROVEN_OLDER_COMPLETE_COPY'],counts['UNIQUE_RECOVERY_CANDIDATE'],counts['UNKNOWN'],result['skipped_recent'],result['skipped_active'],result['removed'],result['freed_bytes'],before,result['after_free'],health['percent_used'],result['target_1gib_reached'],result['target_2gib_reached'])
    if cleanup and result['after_free']<TARGET_FREE:logging.warning('[DISK_FORENSIC] target_free_bytes=%d unmet; unique/unknown data preserved',TARGET_FREE)
    return result
