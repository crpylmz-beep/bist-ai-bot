"""Descriptor-anchored, metadata-only inventory. No writes, cleanup or connections."""
import hashlib
import math
import os
from pathlib import Path
import stat
from .records import now

CATEGORIES=('prediction_history','learning_data','signal_outcomes','temporary_files',
            'recovery_records','private_user_data','reproducible_cache_review','other_preserve')


def category(name,parts):
    value=name.casefold()
    if value.startswith(('.user-','.migration-','.atomic-')) and not value.endswith('.lock') or value.endswith(('.tmp','.temp','.partial')):
        return 'temporary_files'
    if 'user-data' in parts or 'private' in parts or value in ('kullanici_seviyeleri.json','fiyat_alarmlari.json','push_subscriptions.json','pending_notifications.json'):
        return 'private_user_data'
    if value.endswith('.lock'):return 'other_preserve'
    if name.endswith('.json') and any(part in ('gunluk_al_sat_gecmisi','intraday_signal_results') for part in parts):return 'signal_outcomes'
    if value=='performans_fiyat_cache.json':return 'reproducible_cache_review'
    if 'recovery' in value or value.endswith('.wal') or 'forensic' in value:
        return 'recovery_records'
    if any(word in value for word in ('ogren','learning','hafiza','haber_zeka_gecmisi','makro_ai_gecmisi')):
        return 'learning_data'
    if 'tahmin' in value or 'prediction' in value or 'yarin_top10_arsiv' in parts or value=='yarin_top10.json':
        return 'prediction_history'
    if any(word in value for word in ('sonuc','performance','performans','signal','sinyal','mumlar')):
        return 'signal_outcomes'
    if 'user-data' in parts or value in ('kullanici_seviyeleri.json','fiyat_alarmlari.json','push_subscriptions.json','pending_notifications.json'):
        return 'private_user_data'
    if 'cache' in value:return 'reproducible_cache_review'
    return 'other_preserve'


def report(root,*,pg_factor_low=1.5,pg_factor_high=3.0,r2_ratio_low=.25,r2_ratio_high=.75,limit=20):
    factors=(pg_factor_low,pg_factor_high,r2_ratio_low,r2_ratio_high)
    if not all(math.isfinite(x) and x>0 for x in factors) or pg_factor_low>pg_factor_high or r2_ratio_low>r2_ratio_high or r2_ratio_high>1:
        raise ValueError('Invalid capacity assumptions')
    if not 0<=limit<=100:raise ValueError('Largest-file limit: 0–100')
    root=Path(root).absolute()
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    groups={name:{'files':0,'logical_bytes':0,'allocated_bytes':0,'private_logical_bytes':0,'json_logical_bytes':0,'private_json_bytes':0,'compressed_bytes':0,'private_compressed_bytes':0} for name in CATEGORIES}
    errors=0;links=0;aliases=0;unique=set();largest=[];physical=0
    def walk(folder,parts):
        nonlocal errors,links,aliases,physical
        try:
            with os.scandir(folder) as iterator:entries=list(iterator)
        except OSError:
            errors+=1;return
        for entry in entries:
            try:
                info=entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):links+=1;continue
                if stat.S_ISDIR(info.st_mode):
                    child=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=folder)
                    try:walk(child,parts+(entry.name,))
                    finally:os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    kind=category(entry.name,parts)
                    allocated=info.st_blocks*512
                    private='private' in parts or 'user-data' in parts or kind=='private_user_data'
                    if private:groups[kind]['private_logical_bytes']+=info.st_size
                    if entry.name.endswith(('.json','.jsonl')):
                        groups[kind]['json_logical_bytes']+=info.st_size
                        if private:groups[kind]['private_json_bytes']+=info.st_size
                    if entry.name.endswith(('.gz','.zip','.bz2','.xz','.zst')):
                        groups[kind]['compressed_bytes']+=info.st_size
                        if private:groups[kind]['private_compressed_bytes']+=info.st_size
                    groups[kind]['files']+=1;groups[kind]['logical_bytes']+=info.st_size;groups[kind]['allocated_bytes']+=allocated
                    identity=(info.st_dev,info.st_ino)
                    if identity in unique:aliases+=1
                    else:unique.add(identity);physical+=allocated
                    token=hashlib.sha256('/'.join(parts+(entry.name,)).encode()).hexdigest()[:16]
                    largest.append({'category':kind,'file_token':token,'logical_bytes':info.st_size,'allocated_bytes':allocated})
                    largest.sort(key=lambda row:row['logical_bytes'],reverse=True);del largest[limit:]
            except OSError:errors+=1
    try:
        walk(fd,())
        disk=os.fstatvfs(fd)
        filesystem={'total_bytes':disk.f_blocks*disk.f_frsize,'available_bytes':disk.f_bavail*disk.f_frsize,'used_bytes':(disk.f_blocks-disk.f_bfree)*disk.f_frsize}
    finally:os.close(fd)
    hot=sum(groups[key]['json_logical_bytes']-groups[key]['private_json_bytes'] for key in ('prediction_history','learning_data','signal_outcomes'))
    critical=sum(groups[key]['logical_bytes']-groups[key]['private_logical_bytes'] for key in ('prediction_history','learning_data','signal_outcomes'))
    hold=sum(groups[key]['logical_bytes']-groups[key]['private_logical_bytes'] for key in ('temporary_files','recovery_records','other_preserve'))
    archive=critical+hold
    compressed=sum(groups[key]['compressed_bytes']-groups[key]['private_compressed_bytes'] for key in ('prediction_history','learning_data','signal_outcomes','temporary_files','recovery_records','other_preserve'))
    pg={'raw_classified_bytes':hot,'estimated_bytes_low':math.ceil(hot*pg_factor_low),'estimated_bytes_high':math.ceil(hot*pg_factor_high),
        'overhead_factor_low':pg_factor_low,'overhead_factor_high':pg_factor_high,'measured_database_bytes':None,
        'wal_backups_replicas_bytes':None,'unique_record_count':None,
        'coverage':'CLASSIFIED_UNCOMPRESSED_JSON_ONLY','unresolved_source_bytes':hold,'estimated_total_cutover_bytes':None}
    r2={'raw_preservation_bytes':archive,'unresolved_preservation_bytes':hold,
        'already_compressed_filename_bytes':compressed,
        'estimated_compressed_bytes_low':compressed+math.ceil((archive-compressed)*r2_ratio_low),'estimated_compressed_bytes_high':compressed+math.ceil((archive-compressed)*r2_ratio_high),
        'compression_ratio_low':r2_ratio_low,'compression_ratio_high':r2_ratio_high,'compression_measured':False}
    return {'mode':'READ_ONLY_METADATA','generated_at':now(),'production_inspected':None,
        'scope':'EXPLICIT_OPERATOR_ROOT','live_scan_atomic_snapshot':False,'categories':groups,'largest':largest,
        'filesystem':filesystem,'tree_allocated_unique_bytes':physical,'hardlink_alias_paths':aliases,
        'symlinks_skipped':links,'errors':errors,'complete':errors==0,
        'postgresql_capacity_scenario':pg,'r2_capacity_scenario':r2,
        'notes':['Filename-based classification is advisory; every source is preserved.',
                 'Logical category bytes may include aliases/duplicate records; estimates are not deduplicated migration measurements.',
                 'Temporary/recovery/unknown files may contain unique records; no deletion or migration eligibility is inferred.',
                 'Private user data is excluded from R2 scenario; encryption/access review required before any future archive.',
                 'PG factors and R2 compression ratios are operator assumptions, not measured storage or verified prices.',
                 'Concurrent writes can change sizes during this read-only scan; unreadable entries make the report incomplete.'],
        'source_deleted':False,'source_moved':False,'source_content_read':False,'external_connections':False}
