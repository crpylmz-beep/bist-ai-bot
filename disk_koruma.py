"""Bound derived daily-price caches; never prune archives, history or user data."""
import json
import logging
import os
from pathlib import Path
import shutil
import time
import errno
import math
from datetime import date,timedelta,datetime

RESERVE=1024*1024
CACHE_LIMIT=4*1024*1024
PUBLIC_SCRATCH_NAMES=('bist_data.json','gun_ici_top10.json','gun_ici_tum.json','yarin_top10.json','sektor_haritasi.json','sirket_site_haritasi.json')


def disk_health(location):
    """Metadata only, never traverse private data or read payloads."""
    usage=shutil.disk_usage(location.root)
    percent=usage.used/usage.total*100 if usage.total else 100
    status='CRITICAL' if percent>=90 else 'WARNING' if percent>=80 else 'WATCH' if percent>=75 else 'NORMAL'
    count=size=0
    for path in location.runtime.glob('.user-*'):
        try:
            if path.is_symlink() or not path.is_file():continue
            count+=1;size+=path.stat().st_size
        except OSError:continue
    result=dict(capacity=usage.total,used=usage.used,free=usage.free,percent_used=round(percent,2),status=status,temp_count=count,temp_bytes=size)
    logging.info('[DISK_HEALTH] %s',result)
    return result


def report(location):
    root=location.root
    if not root:return {}
    usage=shutil.disk_usage(root);groups={k:{'bytes':0,'files':0} for k in ('public','private','runtime','archives','other')};largest=[];seen=set()
    folders=(('public',location.public),('private',location.users),('runtime',location.runtime),('archives',location.archives))
    temp_summary={'count':0,'total_bytes':0,'oldest_age':None,'newest_age':None}
    known_runtime={'ai_ogrenme_gecmisi.json','tahmin_gecmisi.json','gun_ici_mumlar.json','gun_ici_performans_durum.json','performans_fiyat_cache.json','yarin_top10_sonuclar.json','karar_hata_gunlugu.json','yarin_kalibrasyon.json','gun_ici_agirliklari.json'}
    for directory,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if not (Path(directory)/d).is_symlink())
        for name in files:
            path=Path(directory)/name
            try:
                if path.is_symlink():continue
                stat=path.stat();inode=(stat.st_dev,stat.st_ino)
                label=next((label for label,folder in folders if path.is_relative_to(folder)),'other')
                groups[label]['files']+=1
                if inode not in seen:groups[label]['bytes']+=stat.st_size;seen.add(inode)
                if label=='runtime' and name.startswith('.user-'):
                    age=max(0,time.time()-stat.st_mtime);temp_summary['count']+=1;temp_summary['total_bytes']+=stat.st_size
                    temp_summary['oldest_age']=max(temp_summary['oldest_age'] or 0,age)
                    temp_summary['newest_age']=min(temp_summary['newest_age'] if temp_summary['newest_age'] is not None else age,age)
                safe=name if (label=='public' and path.parent==location.public and name.endswith('.json')) or (label=='runtime' and name in known_runtime) else label+' file'
                if name.startswith(('.user-','.snapshot-','.migration-')):safe=label+'/'+name.split('-',1)[0]+'-* (temporary; unverified)'
                largest.append((stat.st_size,safe))
            except OSError:continue
    logging.info('[DISK_TEMP_INVENTORY] %s',temp_summary)
    logging.info('[DISK] capacity=%d used=%d free=%d groups=%s largest=%s',usage.total,usage.used,usage.free,groups,sorted(largest,reverse=True)[:15])
    logging.info('[DISK] directory_MiB=%s largest_file_MiB=%s',{k:round(v['bytes']/1024**2,2) for k,v in groups.items()},[(round(size/1024**2,2),label) for size,label in sorted(largest,reverse=True)[:30]])
    if usage.free<10*1024*1024:logging.warning('[DISK] Kritik boş alan. Kalıcı geçmiş silinmeyecek; Railway volume kapasitesini artırın.')
    return {'total':usage.total,'used':usage.used,'free':usage.free,'groups':groups,'atomic_temps':temp_summary}


def trim_price_cache(cache,today=None):
    """Daily provider replay cache only; intraday historical bars are NOT disposable."""
    today=today or date.today();cutoff=today-timedelta(days=3);result={};size=2
    for symbol,value in sorted(cache.items(),key=lambda item:str(item[1].get('day','')) if isinstance(item[1],dict) else '',reverse=True):
        if not isinstance(value,dict):continue
        try:day=date.fromisoformat(value.get('day',''))
        except (ValueError,TypeError):continue
        if not cutoff<=day<=today:continue
        # Account conservatively for the existing pretty JSON writer.
        amount=len(json.dumps({symbol:value},ensure_ascii=False,indent=2).encode())+64
        if size+amount<=CACHE_LIMIT:result[symbol]=value;size+=amount
    return result


def save_price_cache(path,cache):
    """Optional replay cache must not consume critical-write headroom."""
    from kullanici_kayitlari import atomic_json
    try:
        needed=len(json.dumps(cache,ensure_ascii=False,indent=2).encode())+RESERVE
        if shutil.disk_usage(path.parent).free<needed:
            logging.warning('[DISK] Replay cache yazımı ertelendi; kalıcı işlemler için boş alan korunuyor')
            return False
        atomic_json(path,cache)
        return True
    except OSError as error:
        if error.errno not in (errno.ENOSPC,errno.EDQUOT):raise
        logging.warning('[DISK] Replay cache yazılamadı; mevcut cache ve kalıcı veriler korundu')
        return False


def cleanup_startup(location,clock=time.time):
    """Only aged public bootstrap scratch files and verified replay cache under pressure."""
    if not location.root:return 0
    reclaimed=0
    # Never traverse private/runtime/archive for scratch cleanup: these may need recovery.
    for path in location.public.glob('.migration-*'):
        try:
            if not any(path.name.startswith('.migration-'+name+'-') for name in PUBLIC_SCRATCH_NAMES):continue
            if path.is_symlink() or not path.is_file() or clock()-path.stat().st_mtime<86400:continue
            size=path.stat().st_size;path.unlink();reclaimed+=size
        except OSError:logging.warning('[DISK] Eski public kopya geçicisi temizlenemedi')
    cache=location.runtime/'performans_fiyat_cache.json'
    if shutil.disk_usage(location.root).free<10*1024*1024 and cache.exists() and not cache.is_symlink():
        try:
            if cache.stat().st_size>32*1024*1024:
                logging.warning('[DISK] Large replay cache preserved pending bounded inspection')
                return reclaimed
            doc=json.loads(cache.read_text())
            # A known provider-cache schema is required, even though the filename is fixed.
            if isinstance(doc,dict) and doc and all(isinstance(v,dict) and set(v)<={'day','closed','bars'} and isinstance(v.get('bars'),list) for v in doc.values()):
                from ai_karar_motoru import locked
                with locked(cache):
                    # Do not remove a cache changed since inspection.
                    if json.loads(cache.read_text())==doc:
                        size=cache.stat().st_size;cache.unlink();reclaimed+=size
        except (OSError,ValueError):logging.warning('[DISK] Cache korunuyor; temizlik güvenle doğrulanamadı')
    logging.info('[DISK] safe_cleanup_bytes=%d; history/users/archives korunuyor',reclaimed)
    return reclaimed


def _fingerprint(path):
    stat=path.stat()
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)


def _digest(path):
    import hashlib
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.digest()


def _replay_schema(path):
    """Validate one symbol at a time; a large legacy replay cache cannot exhaust RAM."""
    decoder=json.JSONDecoder()
    with path.open('r',encoding='utf-8') as stream:
        buffer='';ended=False
        def fill():
            nonlocal buffer,ended
            chunk=stream.read(65536);buffer+=chunk;ended=not chunk
        def whitespace():
            nonlocal buffer
            buffer=buffer.lstrip()
            while not buffer and not ended:fill();buffer=buffer.lstrip()
        def token(char):
            nonlocal buffer
            whitespace()
            if not buffer.startswith(char):raise ValueError('cache schema')
            buffer=buffer[1:]
        def value():
            nonlocal buffer
            whitespace()
            while True:
                try:result,end=decoder.raw_decode(buffer);buffer=buffer[end:];return result
                except json.JSONDecodeError:
                    if ended or len(buffer)>4*1024*1024:raise ValueError('cache entry limit')
                    fill()
        token('{');whitespace()
        if buffer.startswith('}'):return False
        while True:
            key=value();token(':');entry=value()
            if not isinstance(key,str) or not isinstance(entry,dict) or not set(entry)<={'day','closed','bars'} or not isinstance(entry.get('bars'),list):return False
            if not isinstance(entry.get('closed'),bool):return False
            try:date.fromisoformat(entry.get('day',''))
            except (ValueError,TypeError):return False
            allowed={'timestamp','date','open','high','low','close','complete'}
            if any(not isinstance(bar,dict) or not set(bar)<=allowed for bar in entry['bars']):return False
            for bar in entry['bars']:
                try:datetime.fromisoformat(bar.get('timestamp') or bar.get('date'))
                except (ValueError,TypeError):return False
                for field in ('open','high','low','close'):
                    number=bar.get(field)
                    if number is not None and (not isinstance(number,(int,float)) or isinstance(number,bool) or not math.isfinite(number)):return False
            whitespace()
            if buffer.startswith('}'):token('}');break
            token(',')
        whitespace()
        return not buffer and ended


def reclaim_once(location,clock=time.time):
    """Run under the exclusive worker lock, before collectors start; no primary deletion."""
    if not location.root:return {'status':'LOCAL_SKIPPED'}
    from kullanici_kayitlari import atomic_json
    import fcntl
    marker=location.runtime/'disk_reclaim_v1.json'
    try:
        with (location.runtime/'disk_reclaim_v1.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if marker.exists() or marker.is_symlink():
                logging.info('[DISK_ONCE] Already attempted; no cleanup repeated')
                return {'status':'ALREADY_ATTEMPTED'}
            before=report(location);removed=[];target=150*1024*1024
            logging.info('[DISK_ONCE] BEFORE used_MiB=%.2f free_MiB=%.2f target_free_MiB=150',before['used']/1024**2,before['free']/1024**2)
            # Persist the one-shot gate before deletion. If even this fails, do not delete.
            atomic_json(marker,{'status':'STARTED','permanent_data_deleted':False})
            from atomik_temp_temizligi import cleanup_atomic_temps
            cleanup_atomic_temps(location)
            # The only replay cache is checked against its actual producer schema.
            cache=location.runtime/'performans_fiyat_cache.json'
            if before['free']<target and cache.is_file() and not cache.is_symlink():
                try:
                    stamp=_fingerprint(cache)
                    if _replay_schema(cache) and _fingerprint(cache)==stamp:
                        size=stamp[2];cache.unlink();removed.append(('runtime/performans_fiyat_cache.json',size))
                except (OSError,ValueError):logging.warning('[DISK_ONCE] Cache schema unverified; preserved')
            # Only exact redundant copies are removable, including old unnamed temps.
            # Private user directory is excluded entirely, even for apparent duplicates.
            for folder,label in ((location.public,'public'),(location.runtime,'runtime'),(location.archives,'archives')):
                files=[p for p in folder.iterdir() if p.is_file() and not p.is_symlink()]
                originals={}
                for p in files:
                    if p.name.endswith('.json') and not p.name.startswith('.'):
                        originals.setdefault(p.stat().st_size,[]).append(p)
                hashed={}
                for path in files:
                    if shutil.disk_usage(location.root).free>=target:break
                    name=path.name
                    if name.startswith('.user-'):continue  # handled by proven/leased startup cleanup
                    is_temp=name.startswith('.migration-') or (name.startswith(('.user-','.snapshot-')) and name.endswith('.tmp'))
                    source_name=name[:-4] if name.endswith('.json.bak') else name[:-7] if name.endswith('.json.backup') else None
                    if not is_temp and not source_name:continue
                    if clock()-path.stat().st_mtime<86400:continue
                    candidates=[folder/source_name] if source_name else originals.get(path.stat().st_size,[])
                    stamp=_fingerprint(path);digest=None
                    for source in candidates:
                        if not source.is_file() or source.is_symlink():continue
                        source_stamp=_fingerprint(source)
                        if source_stamp[2]!=stamp[2]:continue
                        digest=digest or _digest(path)
                        known=hashed.get(source)
                        if not known or known[0]!=source_stamp:hashed[source]=(source_stamp,_digest(source))
                        if digest!=hashed[source][1]:continue
                        if _fingerprint(path)!=stamp or _fingerprint(source)!=source_stamp:break
                        # Names of unknown/private recovery candidates never enter logs.
                        size=stamp[2]
                        if unlink_inactive(path,stamp):removed.append((label+'/verified-redundant-copy',size))
                        break
            after=report(location)
            result={'status':'COMPLETED','before_used':before['used'],'before_free':before['free'],
                    'after_used':after['used'],'after_free':after['free'],'freed_bytes':max(0,after['free']-before['free']),
                    'removed':removed,'target_met':after['free']>=target,'permanent_data_deleted':False}
            logging.info('[DISK_ONCE] AFTER used_MiB=%.2f free_MiB=%.2f freed_MiB=%.2f removed=%s permanent_data_deleted=false',after['used']/1024**2,after['free']/1024**2,result['freed_bytes']/1024**2,removed)
            if not result['target_met']:logging.warning('[DISK_ONCE] Safe space target not met; preserve all unique data and increase volume capacity')
            atomic_json(marker,result)
            return result
    except OSError as error:
        logging.warning('[DISK_ONCE] Inspection/cleanup stopped errno=%s; unique data preserved',error.errno)
        return {'status':'INCOMPLETE','errno':error.errno}


def unlink_inactive(path,expected):
    """Respect the same fd lease for old one-shot snapshot scratch cleanup."""
    import fcntl
    fd=None
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from atomik_temp_temizligi import foreign_open
        if foreign_open(fd) is not False:return False
        info=os.fstat(fd)
        if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=expected or _fingerprint(path)!=expected:return False
        path.unlink();return True
    except BlockingIOError:return False
    finally:
        if fd is not None:os.close(fd)
