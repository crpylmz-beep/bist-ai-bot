"""Startup-only removal of PROVEN redundant atomic scratch, never unique recovery.

Legacy random names cannot identify a destination. Age/name alone are insufficient:
require an exact current final copy, or a fully parsed ai history subset whose frozen
records and every non-null historical outcome still exist unchanged in the final.
"""
import errno,fcntl,hashlib,json,logging,os,re,shutil,sqlite3,stat,tempfile,time
from datetime import datetime
from contextvars import ContextVar
from pathlib import Path
from atomik_depolama import target_lock_name

inspection_stop=ContextVar('disk_inspection_stop',default=None)

def check_deadline(deadline):
    stop=inspection_stop.get()
    if (stop is not None and stop.is_set()) or time.monotonic()>deadline:
        raise TimeoutError('Inspection time limit')


MIN_AGE=30*60
SAFE_FINALS={'ai_ogrenme_gecmisi.json','tahmin_gecmisi.json','gun_ici_mumlar.json',
             'ana_motor_durum.json','performans_fiyat_cache.json','yarin_top10_sonuclar.json',
             'gun_ici_performans_durum.json','indicator_performance_state.json'}
TEMP_PATTERN=re.compile(r'^\.user-(?:v2-[0-9a-f]{24}-)?[a-zA-Z0-9_-]+\.tmp$')


def fingerprint(fd):
    s=os.fstat(fd);return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)


def digest_fd(fd,deadline=float("inf")):
    os.lseek(fd,0,os.SEEK_SET);h=hashlib.sha256()
    while True:
        check_deadline(deadline)
        chunk=os.read(fd,1024*1024)
        if not chunk:break
        h.update(chunk)
    return h.digest()


def prefix_matches(temp_fd,final_fd,deadline=float("inf")):
    """Every byte of an incomplete temp must already exist in committed final."""
    os.lseek(temp_fd,0,0);os.lseek(final_fd,0,0)
    while True:
        check_deadline(deadline)
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
    def __init__(self,fd,deadline,record_key='kayitlar'):
        self.record_key=record_key
        os.lseek(fd,0,0);self.stream=os.fdopen(os.dup(fd),'r',encoding='utf-8',newline='');self.buffer='';self.ended=False;self.deadline=deadline;self.offset=0;self.last_span=None
    def fill(self):
        check_deadline(self.deadline)
        chunk=self.stream.read(65536);self.buffer+=chunk;self.ended=not chunk
    def consume(self,n):
        self.offset+=len(self.buffer[:n].encode('utf-8'));self.buffer=self.buffer[n:]
    def white(self):
        self.consume(len(self.buffer)-len(self.buffer.lstrip()))
        while not self.buffer and not self.ended:
            self.fill();self.consume(len(self.buffer)-len(self.buffer.lstrip()))
    def token(self,character):
        self.white()
        if not self.buffer.startswith(character):raise ValueError('Invalid history JSON')
        self.consume(1)
    def value(self):
        self.white()
        while True:
            check_deadline(self.deadline)
            try:
                value,end=json.JSONDecoder(object_pairs_hook=strict_object,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON'))).raw_decode(self.buffer)
                if end==len(self.buffer) and not self.ended:
                    self.fill();continue
                self.last_span=(self.offset,len(self.buffer[:end].encode('utf-8')));self.consume(end);return value
            except json.JSONDecodeError:
                if self.ended or len(self.buffer)>8*1024*1024:raise ValueError('Incomplete/oversized history entry')
                self.fill()
    def entries(self):
        self.token('{');seen=set();self.white()
        while not self.buffer.startswith('}'):
            key=self.value()
            if not isinstance(key,str) or key in seen:raise ValueError('Duplicate root key')
            seen.add(key)
            if len(seen)>64:raise ValueError('Too many root fields')
            self.token(':')
            if key==self.record_key:
                self.token('[');self.white()
                if not self.buffer.startswith(']'):
                    while True:
                        row=self.value()
                        if not isinstance(row,dict):raise ValueError('Invalid record')
                        yield None,row
                        self.white()
                        if self.buffer.startswith(']'):break
                        self.token(',')
                self.token(']')
            else:yield key,self.value()
            self.white()
            if self.buffer.startswith('}'):break
            self.token(',')
        self.token('}');self.white()
        if self.buffer or not self.ended or self.record_key not in seen:raise ValueError('Trailing/incomplete history')
    def close(self):self.stream.close()


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def record_values(row):
    identity=next((row[k] for k in ('kayit_id','prediction_id','signal_id','result_id','id') if isinstance(row.get(k),str) and row[k]),None)
    if identity is None:raise ValueError('Missing record identity')
    outcomes={k:v for k,v in row.items() if re.fullmatch(r'sonuc_\d+g',k)}
    frozen={k:v for k,v in row.items() if k not in outcomes}
    # Exact legacy schema: bist_bot.ai_ogrenme_kaydet / ai_sonuclari_guncelle.
    # Only the empty pending bundle may advance. Completed bundles remain exact.
    if row.get('model')=='GUN_ICI' and row.get('egitim_durumu') in ('EGITIM','TAMAMLANDI') and row.get('sonuc') in ('BEKLIYOR','BASARILI','BASARISIZ'):
        fields=('sonuc','sonuc_fiyat','sonuc_zaman','getiri_yuzde','hedef_vurdu','stop_vurdu','sat_hedef','sat_stop')
        bundle={k:row[k] for k in fields if k in row}
        pending=row['sonuc']=='BEKLIYOR' and row['egitim_durumu']=='EGITIM'
        if pending:
            defaults={'sonuc':'BEKLIYOR','sonuc_fiyat':None,'sonuc_zaman':None,'getiri_yuzde':None,'hedef_vurdu':False,'stop_vurdu':False}
            if not all(k in bundle and type(bundle[k]) is type(v) and bundle[k]==v for k,v in defaults.items()):raise ValueError('Nonempty legacy pending outcome')
            if ('sat_hedef' in bundle)!=('sat_stop' in bundle):raise ValueError('Incomplete legacy levels')
        else:
            if row['egitim_durumu']!='TAMAMLANDI' or any(k not in bundle for k in fields[:6]):raise ValueError('Incomplete completed legacy outcome')
            outcomes['legacy_result']=bundle
        if 'sat_hedef' in bundle and 'sat_stop' in bundle:
            outcomes['legacy_levels']={k:bundle[k] for k in fields[-2:]}
        frozen={k:v for k,v in frozen.items() if k not in fields}
        frozen['egitim_durumu']='EGITIM'
    return identity,frozen,{k:v for k,v in outcomes.items() if v is not None}


def record_parts(row):
    identity,frozen,outcomes=record_values(row)
    return identity,canonical(frozen),{k:canonical(v) for k,v in outcomes.items()}


def history_time(value):
    # This adapter is ONLY for the AI-history writer, whose naive timestamps
    # are explicitly generated in Europe/Istanbul in the repository.
    from zoneinfo import ZoneInfo
    parsed=datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=ZoneInfo('Europe/Istanbul')) if parsed.tzinfo is None else parsed


class HistoryIndex:
    def __init__(self,fd,deadline,record_key='kayitlar',ai_legacy=True):
        self.record_key=record_key;self.ai_legacy=ai_legacy;self.metrics={}
        self.temp=tempfile.TemporaryDirectory(prefix='bist-atomic-proof-',dir='/tmp');self.db=None;self.final_fd=None;self.metadata={};self.count=0
        try:
            self.final_fd=os.dup(fd)
            self.db=sqlite3.connect(str(Path(self.temp.name)/'proof.sqlite'))
            self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('CREATE TABLE records(id TEXT PRIMARY KEY, frozen TEXT, outcomes TEXT, offset INTEGER, length INTEGER)')
            stream=HistoryStream(fd,deadline,self.record_key)
            try:
                for key,value in stream.entries():
                    if key is not None:self.metadata[key]=value;continue
                    identity,frozen,outcomes=self.parts(value)
                    self.db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(identity,frozen,json.dumps(outcomes),*stream.last_span));self.count+=1
                self.db.commit()
            finally:stream.close()
        except BaseException:self.close();raise
    def values(self,row):
        if self.ai_legacy:return record_values(row)
        identity=next((row[k] for k in ('kayit_id','prediction_id','signal_id','result_id','id') if isinstance(row.get(k),str) and row[k]),None)
        if identity is None:raise ValueError('Missing record identity')
        outcomes={k:v for k,v in row.items() if re.fullmatch(r'sonuc_\d+g',k)}
        # Only documented null horizon placeholders may advance. Empty arbitrary
        # dictionaries and partial/completed results remain meaningful values.
        return identity,{k:v for k,v in row.items() if k not in outcomes},{k:v for k,v in outcomes.items() if v is not None}
    def parts(self,row):
        identity,frozen,outcomes=self.values(row)
        return identity,canonical(frozen),{k:canonical(v) for k,v in outcomes.items()}
    def assess(self,fd,deadline):
        stream=HistoryStream(fd,deadline,self.record_key);count=0;metadata={};unique=False
        self.metrics={'unique_record_count':0,'changed_record_count':0,'missing_record_count':0,'final_extra_record_count':0};change_reason=None
        self.db.execute('CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY)');self.db.execute('DELETE FROM seen')
        try:
            for key,value in stream.entries():
                if key is not None:metadata[key]=value;continue
                identity,frozen,outcomes=self.parts(value)
                try:self.db.execute('INSERT INTO seen VALUES(?)',(identity,))
                except sqlite3.IntegrityError:raise ValueError('Duplicate record identity')
                count+=1
                current=self.db.execute('SELECT frozen,outcomes,offset,length FROM records WHERE id=?',(identity,)).fetchone()
                if not current:
                    unique=True;self.metrics['unique_record_count']+=1;self.metrics['missing_record_count']+=1;continue
                if current[0]!=frozen:
                    # Indexed byte ranges refer to the held final descriptor; no
                    # second full history copy or per-field megabyte index.
                    final_row=json.loads(os.pread(self.final_fd,current[3],current[2]),object_pairs_hook=strict_object)
                    from disk_forensik import contained
                    if not contained(self.values(value)[1],self.values(final_row)[1]):
                        unique=True;self.metrics['changed_record_count']+=1;change_reason='CHANGED_FROZEN_FIELD';continue
                target_outcomes=json.loads(current[1])
                if any(target_outcomes.get(k)!=v for k,v in outcomes.items()):
                    final_row=json.loads(os.pread(self.final_fd,current[3],current[2]),object_pairs_hook=strict_object)
                    from disk_forensik import contained
                    if not contained(self.values(value)[2],self.values(final_row)[2]):
                        unique=True;self.metrics['changed_record_count']+=1;change_reason=change_reason or 'CHANGED_RESULT'
            # Finish parsing before calling anything unique: invalid/truncated
            # files are UNKNOWN, not valid complete recovery records.
            self.metrics['final_extra_record_count']=self.db.execute('SELECT COUNT(*) FROM records WHERE id NOT IN (SELECT id FROM seen)').fetchone()[0]
            if unique:return 'UNIQUE_RECOVERY_CANDIDATE',change_reason or 'UNIQUE_RECORD'
            for key,value in metadata.items():
                if key not in self.metadata:return 'UNIQUE_RECOVERY_CANDIDATE','ROOT_METADATA_NOT_IN_FINAL'
                target=self.metadata[key]
                if (key=='guncelleme' and self.ai_legacy) or (key=='son_guncelleme' and self.record_key=='tahminler'):
                    if history_time(value)>history_time(target):return 'UNKNOWN','FUTURE_HISTORY_TIMESTAMP'
                elif key=='toplam_kayit':
                    if type(value) is not int or type(target) is not int or value!=count or target!=self.count:return 'UNKNOWN','INVALID_RECORD_COUNT'
                elif canonical(value)!=canonical(target):return 'UNIQUE_RECOVERY_CANDIDATE','ROOT_METADATA_DIFFERS'
            if self.count>count:return 'PROVEN_SUBSET_OF_FINAL','ALL_FROZEN_RECORDS_AND_RESULTS_CONTAINED'
            return 'PROVEN_OLDER_COMPLETE_COPY','SAME_COMPLETE_RECORD_SET_NO_RESULT_LOSS'
        finally:stream.close()
    def covers(self,fd,deadline):
        return self.assess(fd,deadline)[0].startswith('PROVEN_')
    def close(self):
        if self.db is not None:self.db.close()
        if self.final_fd is not None:os.close(self.final_fd)
        self.temp.cleanup()


def cleanup_atomic_temps(location,clock=time.time,budget_seconds=180,require_worker_lock=True):
    from disk_forensik import inspect_atomic_temps
    return inspect_atomic_temps(location,cleanup=True,clock=clock,budget_seconds=budget_seconds,require_worker_lock=require_worker_lock)
