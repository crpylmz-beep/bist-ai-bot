"""Startup-only removal of PROVEN redundant atomic scratch, never unique recovery.

Legacy random names cannot identify a destination. Age/name alone are insufficient:
require an exact current final copy, or a fully parsed ai history subset whose frozen
records and every non-null historical outcome still exist unchanged in the final.
"""
import errno,fcntl,hashlib,json,logging,os,re,shutil,sqlite3,stat,tempfile,time
from datetime import datetime
from pathlib import Path
from atomik_depolama import target_lock_name

MIN_AGE=30*60
SAFE_FINALS={'ai_ogrenme_gecmisi.json','tahmin_gecmisi.json','gun_ici_mumlar.json',
             'ana_motor_durum.json','performans_fiyat_cache.json','yarin_top10_sonuclar.json',
             'gun_ici_performans_durum.json','indicator_performance_state.json'}
TEMP_PATTERN=re.compile(r'^\.user-(?:v2-[0-9a-f]{24}-)?[a-zA-Z0-9_-]+\.tmp$')


def fingerprint(fd):
    s=os.fstat(fd);return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)


def digest_fd(fd):
    os.lseek(fd,0,os.SEEK_SET);h=hashlib.sha256()
    while True:
        chunk=os.read(fd,1024*1024)
        if not chunk:break
        h.update(chunk)
    return h.digest()


def prefix_matches(temp_fd,final_fd):
    """Every byte of an incomplete temp must already exist in committed final."""
    os.lseek(temp_fd,0,0);os.lseek(final_fd,0,0)
    while True:
        chunk=os.read(temp_fd,1024*1024)
        if not chunk:return True
        if os.read(final_fd,len(chunk))!=chunk:return False


def open_regular(folder_fd,name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=folder_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):os.close(fd);raise ValueError('Not regular')
    return fd


def foreign_open(fd,processes=None):
    """Protect legacy writers which predate fd leases. Permission failure is unsafe."""
    identity=fingerprint(fd)[:2];own=str(os.getpid())
    if not Path('/proc').is_dir():return None
    for process in (processes if processes is not None else Path('/proc').iterdir()):
        if not process.name.isdecimal() or process.name==own:continue
        try:
            # cloud_baslat launches both application children without setuid.
            # Other OS users are not application writers; inaccessible same-user
            # processes remain unverified and block deletion.
            if process.stat().st_uid!=os.getuid():continue
            for link in (process/'fd').iterdir():
                try:
                    info=link.stat()
                    if (info.st_dev,info.st_ino)==identity:return True
                except FileNotFoundError:pass
        except (FileNotFoundError,ProcessLookupError):pass
        except PermissionError:return None
    return False


def strict_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON object key')
        result[key]=value
    return result


class HistoryStream:
    """Bounded record-at-a-time JSON parser; incomplete/trailing files are rejected."""
    def __init__(self,fd,deadline):
        os.lseek(fd,0,0);self.stream=os.fdopen(os.dup(fd),'r',encoding='utf-8');self.buffer='';self.ended=False;self.deadline=deadline
    def fill(self):
        if time.monotonic()>self.deadline:raise TimeoutError('Inspection time limit')
        chunk=self.stream.read(65536);self.buffer+=chunk;self.ended=not chunk
    def white(self):
        self.buffer=self.buffer.lstrip()
        while not self.buffer and not self.ended:self.fill();self.buffer=self.buffer.lstrip()
    def token(self,character):
        self.white()
        if not self.buffer.startswith(character):raise ValueError('Invalid history JSON')
        self.buffer=self.buffer[1:]
    def value(self):
        self.white()
        while True:
            if time.monotonic()>self.deadline:raise TimeoutError('Inspection time limit')
            try:value,end=json.JSONDecoder(object_pairs_hook=strict_object).raw_decode(self.buffer);self.buffer=self.buffer[end:];return value
            except json.JSONDecodeError:
                if self.ended or len(self.buffer)>8*1024*1024:raise ValueError('Incomplete/oversized history entry')
                self.fill()
    def entries(self):
        self.token('{');seen=set();self.white()
        while not self.buffer.startswith('}'):
            key=self.value()
            if not isinstance(key,str) or key in seen:raise ValueError('Duplicate root key')
            seen.add(key);self.token(':')
            if key=='kayitlar':
                self.token('[');self.white()
                if not self.buffer.startswith(']'):
                    while True:
                        row=self.value()
                        if not isinstance(row,dict):raise ValueError('Invalid record')
                        yield 'record',row
                        self.white()
                        if self.buffer.startswith(']'):break
                        self.token(',')
                self.token(']')
            else:yield key,self.value()
            self.white()
            if self.buffer.startswith('}'):break
            self.token(',')
        self.token('}');self.white()
        if self.buffer or not self.ended or 'kayitlar' not in seen:raise ValueError('Trailing/incomplete history')
    def close(self):self.stream.close()


def record_parts(row):
    identity=row.get('kayit_id') or row.get('id')
    if not isinstance(identity,str) or not identity:raise ValueError('Missing record identity')
    outcomes={k:v for k,v in row.items() if re.fullmatch(r'sonuc_\d+g',k)}
    frozen={k:v for k,v in row.items() if k not in outcomes}
    canonical=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return identity,canonical(frozen),{k:canonical(v) for k,v in outcomes.items() if v is not None}


class HistoryIndex:
    def __init__(self,fd,deadline):
        self.temp=tempfile.TemporaryDirectory(prefix='bist-atomic-proof-',dir='/tmp');self.db=None;self.metadata={};self.count=0
        try:
            self.db=sqlite3.connect(str(Path(self.temp.name)/'proof.sqlite'))
            self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('CREATE TABLE records(id TEXT PRIMARY KEY, frozen TEXT, outcomes TEXT)')
            stream=HistoryStream(fd,deadline)
            try:
                for key,value in stream.entries():
                    if key!='record':self.metadata[key]=value;continue
                    identity,frozen,outcomes=record_parts(value)
                    self.db.execute('INSERT INTO records VALUES(?,?,?)',(identity,frozen,json.dumps(outcomes)));self.count+=1
                self.db.commit()
            finally:stream.close()
        except BaseException:self.close();raise
    def covers(self,fd,deadline):
        stream=HistoryStream(fd,deadline);count=0;metadata={}
        self.db.execute('CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY)');self.db.execute('DELETE FROM seen')
        try:
            for key,value in stream.entries():
                if key!='record':metadata[key]=value;continue
                identity,frozen,outcomes=record_parts(value)
                try:self.db.execute('INSERT INTO seen VALUES(?)',(identity,))
                except sqlite3.IntegrityError:return False
                count+=1
                current=self.db.execute('SELECT frozen,outcomes FROM records WHERE id=?',(identity,)).fetchone()
                if not current or current[0]!=frozen:return False
                target_outcomes=json.loads(current[1])
                if any(target_outcomes.get(k)!=v for k,v in outcomes.items()):return False
            for key,value in metadata.items():
                if key not in self.metadata:return False
                target=self.metadata[key]
                if key=='guncelleme':
                    old,new=datetime.fromisoformat(str(value)),datetime.fromisoformat(str(target))
                    if old.tzinfo is None or new.tzinfo is None or old>new:return False
                elif key=='toplam_kayit':
                    if isinstance(value,bool) or not isinstance(value,int) or value!=count or target!=self.count:return False
                elif value!=target:return False
            return True
        finally:stream.close()
    def close(self):
        if self.db is not None:self.db.close()
        self.temp.cleanup()


def cleanup_atomic_temps(location,clock=time.time,budget_seconds=90):
    counters=dict(scanned=0,eligible=0,removed=0,freed_bytes=0,skipped_recent=0,skipped_unverified=0,skipped_active=0,errors=0)
    if not location.root:return counters
    deadline=time.monotonic()+budget_seconds;root_fd=folder_fd=None;indexes={}
    before=shutil.disk_usage(location.root).free
    try:
        root_fd=os.open(location.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        # Anchored directly below /data: never scan private/public/archive or links.
        folder_fd=os.open('runtime',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root_fd)
        names=sorted(entry.name for entry in os.scandir(folder_fd))
        finals=[n for n in names if n in SAFE_FINALS]
        for name in names:
            if not name.startswith('.user-'):continue
            counters['scanned']+=1;temp_fd=None
            try:
                if not TEMP_PATTERN.fullmatch(name) or time.monotonic()>deadline:
                    counters['skipped_unverified']+=1;continue
                temp_fd=open_regular(folder_fd,name);info=os.fstat(temp_fd)
                if info.st_nlink!=1:counters['skipped_unverified']+=1;continue
                if clock()-info.st_mtime<MIN_AGE:counters['skipped_recent']+=1;continue
                try:fcntl.flock(temp_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:counters['skipped_active']+=1;continue
                opened=foreign_open(temp_fd)
                if opened is not False:
                    counters['skipped_active' if opened is True else 'skipped_unverified']+=1;continue
                temp_stamp=fingerprint(temp_fd);temp_digest=None;proven=False
                for final in finals:
                    business=atomic=final_fd=None
                    try:
                        business=os.open(final+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=folder_fd)
                        fcntl.flock(business,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        atomic=os.open(target_lock_name(final),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=folder_fd)
                        fcntl.flock(atomic,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        final_fd=open_regular(folder_fd,final);final_stamp=fingerprint(final_fd)
                        if final_stamp[2]==temp_stamp[2]:
                            temp_digest=temp_digest or digest_fd(temp_fd)
                            proven=temp_digest==digest_fd(final_fd)
                        if not proven and temp_stamp[2]<final_stamp[2]:proven=prefix_matches(temp_fd,final_fd)
                        if not proven and final=='ai_ogrenme_gecmisi.json':
                            key=(final,final_stamp)
                            if key not in indexes:indexes[key]=HistoryIndex(final_fd,deadline)
                            proven=indexes[key].covers(temp_fd,deadline)
                        # Check both directory entries, not just held descriptors.
                        current=os.stat(final,dir_fd=folder_fd,follow_symlinks=False)
                        original=os.stat(name,dir_fd=folder_fd,follow_symlinks=False)
                        unchanged=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns)==final_stamp and (original.st_dev,original.st_ino,original.st_size,original.st_mtime_ns)==temp_stamp
                        if not unchanged:proven=False
                        if proven and unchanged:
                            counters['eligible']+=1;os.unlink(name,dir_fd=folder_fd)
                            counters['removed']+=1;counters['freed_bytes']+=temp_stamp[2];break
                    except BlockingIOError:continue
                    except (ValueError,UnicodeError,sqlite3.Error,TimeoutError):continue
                    finally:
                        for fd in (final_fd,atomic,business):
                            if fd is not None:os.close(fd)
                if not proven:counters['skipped_unverified']+=1
            except (OSError,ValueError) as error:
                if isinstance(error,OSError) and error.errno not in (errno.ELOOP,errno.ENOENT):counters['errors']+=1
                counters['skipped_unverified']+=1
            finally:
                if temp_fd is not None:os.close(temp_fd)
    except OSError:counters['errors']+=1
    finally:
        for index in indexes.values():index.close()
        for fd in (folder_fd,root_fd):
            if fd is not None:os.close(fd)
    counters.update(before_free=before,after_free=shutil.disk_usage(location.root).free)
    logging.info('[DISK_TEMP_CLEANUP] %s',counters)
    return counters
