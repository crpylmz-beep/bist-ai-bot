"""Bound derived daily-price caches; never prune archives, history or user data."""
import json
import logging
import os
from pathlib import Path
import shutil
import time
import errno
from datetime import date,timedelta

RESERVE=1024*1024
CACHE_LIMIT=4*1024*1024
PUBLIC_SCRATCH_NAMES=('bist_data.json','gun_ici_top10.json','gun_ici_tum.json','yarin_top10.json','sektor_haritasi.json','sirket_site_haritasi.json')


def report(location):
    root=location.root
    if not root:return {}
    usage=shutil.disk_usage(root);groups={k:{'bytes':0,'files':0} for k in ('public','private','runtime','archives','other')};largest=[];seen=set()
    folders=(('public',location.public),('private',location.users),('runtime',location.runtime),('archives',location.archives))
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
                safe=name if (label=='public' and path.parent==location.public and name.endswith('.json')) or (label=='runtime' and name in known_runtime) else label+' file'
                largest.append((stat.st_size,safe))
            except OSError:continue
    logging.info('[DISK] capacity=%d used=%d free=%d groups=%s largest=%s',usage.total,usage.used,usage.free,groups,sorted(largest,reverse=True)[:15])
    if usage.free<10*1024*1024:logging.warning('[DISK] Kritik boş alan. Kalıcı geçmiş silinmeyecek; Railway volume kapasitesini artırın.')
    return {'total':usage.total,'used':usage.used,'free':usage.free,'groups':groups}


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
