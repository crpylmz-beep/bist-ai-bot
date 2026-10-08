"""Metadata-only writer lifecycle, shutdown gate and bounded growth observations."""
from collections import OrderedDict
from datetime import datetime
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from zoneinfo import ZoneInfo

LARGE=1024*1024
_shutdown=threading.Event()
_bound_worker=None
_stats=OrderedDict()
_mutex=threading.Lock()

class StoragePendingError(OSError):
    storage_code='STORAGE_PENDING'
    def __init__(self):super().__init__(errno.EAGAIN,'STORAGE_PENDING: WAL durable; canonical commit bekliyor')


def bind_shutdown(event):
    global _bound_worker
    _bound_worker=event

def sidecar_name(temp_name):
    return '.atomic-meta-'+hashlib.sha256(temp_name.encode()).hexdigest()[:32]+'.json'


def shutdown_writes(event=None):
    if event is not None and event is not _bound_worker:return
    _shutdown.set()
    logging.info('[STORAGE_SHUTDOWN] accepting_large_writes=false')

def check_shutdown(size):
    if size>=LARGE and _shutdown.is_set():
        raise OSError(errno.ECANCELED,'STORAGE_SHUTDOWN: büyük yazım iptal edildi; mevcut final korunuyor')

def caller():
    frame=sys._getframe(2)
    while frame:
        name=Path(frame.f_code.co_filename).name
        if name not in ('storage_izleme.py','atomik_depolama.py','kullanici_kayitlari.py') and frame.f_code.co_name not in ('json_atomik_yaz',):
            return name+':'+frame.f_code.co_name
        frame=frame.f_back
    return 'atomic_write_json'

class WriteTrace:
    def __init__(self,path):
        self.path=Path(path);self.target=hashlib.sha256(self.path.name.encode()).hexdigest()[:24]
        self.writer=caller();self.started=time.monotonic();self.at=datetime.now(ZoneInfo('Europe/Istanbul')).isoformat()
        self.before=shutil.disk_usage(self.path.parent).free;self.physical=0;self.logical=None
        self.reason='STATE_COMMIT';self.temp=None;self.state='PREFLIGHT';self.success=False;self.removed=True;self.meta_fd=None;self.meta_path=None;self.renamed=False
    def create_metadata(self,temp_fd):
        self.meta_path=str(Path(self.temp).parent/sidecar_name(Path(self.temp).name))
        self.meta_fd=os.open(self.meta_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        self.temp_inode=os.fstat(temp_fd).st_ino
    def transition(self,state):
        self.state=state
        if state=='RENAMED':self.renamed=True
        if self.meta_fd is not None:
            value=dict(version=4,target_hash=self.target,writer_type='ATOMIC_JSON',writer=self.writer,creation_timestamp=self.at,transaction_id=hashlib.sha256(self.temp.encode()).hexdigest()[:24],inode=self.temp_inode,state=state)
            encoded=json.dumps(value,separators=(',',':')).encode()
            if len(encoded)>4096:raise ValueError('Storage metadata exceeds limit')
            os.pwrite(self.meta_fd,encoded,0);os.ftruncate(self.meta_fd,len(encoded));getattr(os,'fdatasync',os.fsync)(self.meta_fd)
        logging.info('[STORAGE_TEMP_STATE] target=%s writer=%s state=%s',self.target,self.writer,state)
    def finish(self):
        if self.meta_fd is not None:
            os.close(self.meta_fd);self.meta_fd=None
            if self.temp is not None and not os.path.lexists(self.temp):
                try:os.unlink(self.meta_path)
                except FileNotFoundError:pass
                except OSError as error:logging.warning('[STORAGE_META] cleanup_failed errno=%s',error.errno)
        try:final_size=self.path.stat().st_size
        except OSError:final_size=None
        try:after=shutil.disk_usage(self.path.parent).free
        except OSError:after=None
        self.removed=self.temp is None or not os.path.lexists(self.temp)
        logging.info('[STORAGE_WRITE_TRACE] dataset=%s target=%s writer=%s reason=%s logical_changed_bytes=%s physical_temp_bytes=%d final_size=%s started_at=%s finished_at=%s duration_ms=%.2f success=%s temp_removed=%s free_before=%s free_after=%s',
            'AI_HISTORY' if self.path.name=='ai_ogrenme_gecmisi.json' else 'JSON',self.target,self.writer,self.reason,self.logical,self.physical,final_size,self.at,datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(),(time.monotonic()-self.started)*1000,self.success,self.removed,self.before,after)
        with _mutex:
            stat_key=(self.target,self.writer)
            value=_stats.setdefault(stat_key,{'writer':self.writer,'bytes':0,'transactions':0,'renames':0})
            value['bytes']+=self.physical;value['transactions']+=1;value['renames']+=int(self.success and self.renamed)
            _stats.move_to_end(stat_key)
            while len(_stats)>256:_stats.popitem(last=False)

def critical_storage(directory):
    usage=shutil.disk_usage(directory)
    critical=usage.total>0 and usage.used/usage.total>=.90
    return critical

class GrowthMonitor:
    def __init__(self):self.previous=None
    @staticmethod
    def meta(path,stamp):
        """Untrusted sidecar is only a diagnostic hint, never deletion proof."""
        fd=None
        try:
            fd=os.open(path.parent/sidecar_name(path.name),os.O_RDONLY|os.O_NOFOLLOW)
            import stat
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>4096:return {}
            value=json.loads(os.read(fd,4097))
            import re
            if value.get('version')!=4 or value.get('inode')!=stamp.st_ino or not re.fullmatch(r'[0-9a-f]{24}',value.get('target_hash','')):return {}
            writer=value.get('writer','UNKNOWN')
            if not isinstance(writer,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',writer):writer='UNKNOWN'
            return {'target':value['target_hash'],'writer':writer,'state':value.get('state')}
        except (OSError,ValueError,TypeError):return {}
        finally:
            if fd is not None:os.close(fd)
    def sample(self,location):
        from disk_koruma import disk_health
        now=time.time();health=disk_health(location);temps={}
        for path in location.runtime.glob('.user-*.tmp'):
            try:
                if path.is_symlink() or not path.is_file():continue
                st=path.stat();key=hashlib.sha256(path.name.encode()).hexdigest()[:16]
                temps[key]={'size':st.st_size,'age':max(0,now-st.st_mtime),**self.meta(path,st)}
            except OSError:continue
        previous=self.previous
        old=previous['temps'] if previous else {};new=set(temps)-set(old);removed=set(old)-set(temps)
        with _mutex:stats={k:dict(v) for k,v in _stats.items()}
        prior=previous['stats'] if previous else {}
        largest=max(stats,key=lambda k:stats[k]['bytes']-prior.get(k,{}).get('bytes',0),default=None)
        writer=stats[largest]['writer'] if largest else 'UNKNOWN'
        old_bytes=sum(v['size'] for v in old.values())
        summary=dict(free_now=health['free'],free_5m_ago=previous['free'] if previous else None,delta_free=health['free']-previous['free'] if previous else None,temp_count=len(temps),temp_bytes=sum(v['size'] for v in temps.values()),new_temp_count=len(new),new_temp_bytes=sum(temps[k]['size'] for k in new),removed_temp_count=len(removed),removed_temp_bytes=sum(old[k]['size'] for k in removed),largest_writer=writer,elapsed_seconds=round(now-previous['at'],2) if previous else None)
        logging.info('[STORAGE_GROWTH] %s',summary)
        if previous and (summary['temp_count']>len(old) or summary['temp_bytes']>old_bytes):
            for key,item in temps.items():
                growth=item['size']-old.get(key,{}).get('size',0)
                target=item.get('target','UNKNOWN')
                renames=sum(value['renames']-prior.get(key,{}).get('renames',0) for key,value in stats.items() if key[0]==target)
                # A fresh in-flight transaction is not an orphan/leak. A retained
                # growing path without a successful rename merits investigation.
                if growth>0 and item['age']>=300 and renames==0:
                    logging.warning('[STORAGE_LEAK_ALERT] writer=%s target_fingerprint=%s temp_growth=%d age=%.1f transaction_count=%d',item.get('writer','UNKNOWN'),target,growth,item['age'],sum(value['transactions']-prior.get(key,{}).get('transactions',0) for key,value in stats.items() if key[0]==target))
        self.previous={'at':now,'free':health['free'],'temps':temps,'stats':stats}
        return summary


def cleanup_proven_sidecar(folder_fd,temp_name,temp_stamp,dataset):
    """Only our tiny metadata paired with an already PROVEN removed scratch."""
    from atomik_temp_temizligi import open_regular,fingerprint
    name=sidecar_name(temp_name);fd=None
    try:
        fd=open_regular(folder_fd,name);stamp=fingerprint(fd);info=os.fstat(fd)
        if info.st_nlink!=1 or info.st_size>4096:return False
        value=json.loads(os.read(fd,4097))
        if value.get('version')!=4 or value.get('writer_type')!='ATOMIC_JSON' or value.get('inode')!=temp_stamp[1] or value.get('target_hash')!=hashlib.sha256(dataset.encode()).hexdigest()[:24]:return False
        current=os.stat(name,dir_fd=folder_fd,follow_symlinks=False)
        if stamp!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns):return False
        os.unlink(name,dir_fd=folder_fd);return True
    except (OSError,ValueError,TypeError):return False
    finally:
        if fd is not None:os.close(fd)
