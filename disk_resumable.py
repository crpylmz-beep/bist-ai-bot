"""Checksummed bounded progress metadata; record indexes contain hashes/offsets only.

Indexes live off-volume in /tmp. Missing/corrupt indexes invalidate semantic progress;
no checkpoint ever authorizes deletion without current fd/lease/lock verification.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import logging
import atomik_temp_temizligi as proof

MAX_BYTES=256*1024
MAX_FILES=128
MAX_INDEX_BYTES=256*1024*1024
SUPPORTED={'ai_ogrenme_gecmisi.json':'kayitlar','tahmin_gecmisi.json':'tahminler','gun_ici_sonuclar.json':'kayitlar'}


def values(row,dataset):
    if dataset=='ai_ogrenme_gecmisi.json':return proof.record_values(row)
    identity=next((row[k] for k in ('kayit_id','prediction_id','signal_id','result_id','id') if isinstance(row.get(k),str) and row[k]),None)
    if identity is None:raise ValueError('Missing record identity')
    outcomes={k:v for k,v in row.items() if re.fullmatch(r'sonuc_\d+g',k)}
    return identity,{k:v for k,v in row.items() if k not in outcomes},{k:v for k,v in outcomes.items() if v is not None}


def safe_field(key):
    return key if key in ('guncelleme','son_guncelleme','toplam_kayit') else 'field:'+proof.canonical(key)


def metadata(key,value,dataset):
    clock=(dataset=='ai_ogrenme_gecmisi.json' and key=='guncelleme') or (dataset=='tahmin_gecmisi.json' and key=='son_guncelleme')
    if clock:
        if not isinstance(value,str) or len(value)>128:raise ValueError('Invalid root clock')
        return {'kind':'clock','value':value}
    if key=='toplam_kayit':
        if type(value) is not int:raise ValueError('Invalid record count')
        return {'kind':'count','value':value}
    return {'kind':'hash','value':proof.canonical(value)}


class ResumableProof:
    def __init__(self,location):
        self.location=location;self.path=location.runtime/'disk_forensic_checkpoint.json'
        self.data={'version':4,'files':{},'finals':{}};self.dbs={};self.dirty=False
        if self.path.exists() or self.path.is_symlink():
            try:
                fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
                try:
                    if os.fstat(fd).st_size>MAX_BYTES:raise ValueError('Checkpoint too large')
                    raw=os.read(fd,MAX_BYTES+1)
                finally:os.close(fd)
                envelope=json.loads(raw,object_pairs_hook=proof.strict_object)
                payload=envelope['checkpoint']
                if envelope['checksum']!=proof.canonical(payload) or payload.get('version')!=4:raise ValueError('Checksum')
                if not isinstance(payload.get('files'),dict) or len(payload['files'])>MAX_FILES or not isinstance(payload.get('finals'),dict) or len(payload['finals'])>8:raise ValueError('Checkpoint bounds')
                self.data=payload
            except (OSError,ValueError,KeyError,TypeError) as error:
                # Unknown/symlink files are never overwritten as housekeeping.
                if 'envelope' not in locals() or not isinstance(envelope,dict) or not isinstance(envelope.get('checkpoint'),dict) or envelope['checkpoint'].get('version')!=4:
                    raise ValueError('Unrecognized checkpoint preserved') from error
                logging.warning('[DISK_CHECKPOINT] invalid; progress will be revalidated from zero')
        root_hash=hashlib.sha256(str(location.runtime.absolute()).encode()).hexdigest()[:24]
        self.index_dir=Path('/tmp')/('bist-proof-v4-'+str(os.getuid())+'-'+root_hash)
        self.index_dir.mkdir(mode=0o700,exist_ok=True)
        stat=self.index_dir.lstat()
        if self.index_dir.is_symlink() or stat.st_uid!=os.getuid():raise ValueError('Unsafe index directory')
        os.chmod(self.index_dir,0o700)

    def save(self):
        if not self.dirty:return
        from kullanici_kayitlari import atomic_json
        for identifier,item in self.data['files'].items():
            if item.get('completed') and item.get('index') in self.dbs:
                self.dbs[item['index']].execute('DELETE FROM seen WHERE temp=?',(identifier,))
        for key,db in self.dbs.items():
            active=[identifier for identifier,item in self.data['files'].items() if item.get('index')==key and not item.get('completed')]
            if active:db.execute('DELETE FROM seen WHERE temp NOT IN ('+','.join('?' for _ in active)+')',active)
            else:db.execute('DELETE FROM seen')
        for db in self.dbs.values():db.commit()
        while len(self.data['files'])>MAX_FILES:
            key=min(self.data['files'],key=lambda k:(not self.data['files'][k].get('completed',False),self.data['files'][k].get('touched',0)))
            self.data['files'].pop(key)
        payload=self.data;envelope={'checkpoint':payload,'checksum':proof.canonical(payload)}
        if len(json.dumps(envelope,ensure_ascii=False,indent=2).encode())>MAX_BYTES:
            logging.warning('[DISK_CHECKPOINT] metadata bound reached; no unsafe deletion')
            raise ValueError('Checkpoint size limit')
        atomic_json(self.path,envelope);self.dirty=False

    def close(self):
        try:self.save()
        finally:
            for db in self.dbs.values():db.close()
            live=set(self.data['finals'])
            for path in self.index_dir.glob('*.sqlite'):
                if re.fullmatch(r'[0-9a-f]{40}\.sqlite',path.name) and path.stem not in live and not path.is_symlink():
                    try:
                        check=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
                        try:owned=check.execute('SELECT marker FROM ownership').fetchall()==[('BIST_FORENSIC_HASH_INDEX_V4',)]
                        finally:check.close()
                        if owned:path.unlink()
                    except sqlite3.Error:pass

    def _index_bound(self):
        size=sum(p.stat().st_size for p in self.index_dir.glob('*') if not p.is_symlink() and p.is_file())
        if size>=MAX_INDEX_BYTES:raise ValueError('PROOF_INDEX_CAPACITY')

    def _db(self,key):
        if key in self.dbs:return self.dbs[key]
        self._index_bound()
        path=self.index_dir/(key+'.sqlite')
        if path.is_symlink():raise ValueError('Unsafe index path')
        # This database contains only indexes, never history payloads or backups.
        existed=path.exists()
        db=sqlite3.connect(path)
        if existed:
            try:
                if db.execute('SELECT marker FROM ownership').fetchall()!=[('BIST_FORENSIC_HASH_INDEX_V4',)]:raise ValueError('Unowned proof index')
            except (sqlite3.Error,ValueError):db.close();raise ValueError('Unowned proof index') from None
        else:
            db.execute('CREATE TABLE ownership(marker TEXT)');db.execute('INSERT INTO ownership VALUES(?)',('BIST_FORENSIC_HASH_INDEX_V4',));db.commit()
        db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA synchronous=FULL');db.execute('PRAGMA max_page_count=16384')
        db.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,frozen TEXT,outcomes TEXT,offset INTEGER,length INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS seen(temp TEXT,id TEXT,ordinal INTEGER,PRIMARY KEY(temp,id))')
        self.dbs[key]=db
        return db

    def _final(self,fd,dataset,deadline):
        stamp=list(proof.fingerprint(fd));key=proof.canonical([dataset,stamp])[:40]
        state=self.data['finals'].get(key)
        existed=(self.index_dir/(key+'.sqlite')).is_file()
        db=self._db(key)
        if state is None or not existed:
            state={'stamp':stamp,'dataset':dataset,'parser':None,'count':0,'metadata':{},'completed':False}
            self.data['finals'][key]=state
            db.execute('DELETE FROM records');db.execute('DELETE FROM seen')
            # Dependent compare progress cannot survive loss of its index.
            for item in self.data['files'].values():
                if item.get('index')==key:
                    item.update(stage='SEMANTIC',parser=None,count=0,metadata={},metrics=self._metrics(),reason=None,completed=False)
            self.dirty=True
        if len(self.data['finals'])>8:
            # Eviction only discards reproducible proof metadata, never payload files.
            for stale in list(self.data['finals']):
                if stale!=key:self.data['finals'].pop(stale)
                if len(self.data['finals'])<=8:break
        count=db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        if count!=state['count']:
            if count>state['count'] and state['parser']:
                db.execute('DELETE FROM records WHERE offset+length>?',(state['parser']['offset'],))
            if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]!=state['count']:
                state.update(parser=None,count=0,metadata={},completed=False);db.execute('DELETE FROM records');db.execute('DELETE FROM seen')
                for item in self.data['files'].values():
                    if item.get('index')==key:item.update(stage='SEMANTIC',parser=None,count=0,metadata={},metrics=self._metrics(),reason=None,completed=False)
                self.dirty=True
        if not state['completed']:
            stream=proof.HistoryStream(fd,deadline,SUPPORTED[dataset],resume=state['parser'])
            try:
                for field,row in stream.entries():
                    if field is None:
                        if state['count']%256==0:self._index_bound()
                        identity,frozen,outcomes=values(row,dataset)
                        db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(proof.canonical(identity),proof.canonical(frozen),proof.canonical(outcomes),*stream.last_span));state['count']+=1
                    else:state['metadata'][safe_field(field)]=metadata(field,row,dataset)
                    state['parser']=dict(stream.checkpoint);self.dirty=True
                state['completed']=True;state['parser']=dict(stream.checkpoint);self.dirty=True
            finally:stream.close();db.commit()
        return key,state,db

    @staticmethod
    def _metrics():return dict(unique_record_count=0,changed_record_count=0,missing_record_count=0,final_extra_record_count=0,matched_count=0)

    def prove(self,temp_fd,final_fd,dataset,identifier,deadline):
        ts=list(proof.fingerprint(temp_fd));fs=list(proof.fingerprint(final_fd))
        state=self.data['files'].get(identifier)
        if state is None or state.get('temp_stamp')!=ts or state.get('final_stamp')!=fs or state.get('dataset')!=dataset:
            state={'temp_stamp':ts,'final_stamp':fs,'dataset':dataset,'stage':'EXACT' if ts[2]==fs[2] else 'PREFIX' if ts[2]<fs[2] else 'SEMANTIC','offset':0,'parser':None,'count':0,'metadata':{},'metrics':self._metrics(),'reason':None,'completed':False}
            self.data['files'][identifier]=state;self.dirty=True
        state['touched']=time.time()
        try:
            if state['completed']:return state['classification'],state['reason'],self._details(state)
            while state['stage'] in ('EXACT','PREFIX','SUFFIX'):
                offset=state['offset']
                while offset<ts[2]:
                    proof.check_deadline(deadline)
                    amount=min(1024*1024,ts[2]-offset)
                    other=offset+(fs[2]-ts[2] if state['stage']=='SUFFIX' else 0)
                    if os.pread(temp_fd,amount,offset)!=os.pread(final_fd,amount,other):
                        state.update(stage='SUFFIX' if state['stage']=='PREFIX' else 'SEMANTIC',offset=0);self.dirty=True;break
                    offset+=amount;state['offset']=offset;self.dirty=True
                else:
                    return self._complete(state,'PROVEN_REDUNDANT','RESUMED_BYTE_'+state['stage'])
            if dataset not in SUPPORTED:
                if ts[2]>8*1024**2:return self._complete(state,'UNKNOWN','STREAM_ADAPTER_REQUIRED')
                return None
            state['index']=proof.canonical([dataset,fs])[:40];state['stage']='BUILD_FINAL'
            key,target,db=self._final(final_fd,dataset,deadline)
            state['index']=key;state['stage']='COMPARE_TEMP';self.dirty=True
            # A committed index may be ahead of the last persisted checkpoint.
            db.execute('DELETE FROM seen WHERE temp=? AND ordinal>=?',(identifier,state['count']))
            if db.execute('SELECT COUNT(*) FROM seen WHERE temp=?',(identifier,)).fetchone()[0]!=state['count']:
                state.update(parser=None,count=0,metadata={},metrics=self._metrics(),reason=None)
                db.execute('DELETE FROM seen WHERE temp=?',(identifier,))
            stream=proof.HistoryStream(temp_fd,deadline,SUPPORTED[dataset],resume=state['parser'])
            try:
                for field,row in stream.entries():
                    if field is None:
                        if state['count']%256==0:self._index_bound()
                        if state['count']%256==0:self._index_bound()
                        identity,frozen,outcomes=values(row,dataset);identity=proof.canonical(identity)
                        db.execute('INSERT INTO seen VALUES(?,?,?)',(identifier,identity,state['count']))
                        state['count']+=1
                        current=db.execute('SELECT frozen,outcomes,offset,length FROM records WHERE id=?',(identity,)).fetchone()
                        if current is None:
                            state['metrics']['unique_record_count']+=1;state['metrics']['missing_record_count']+=1;state['reason']=state['reason'] or 'UNIQUE_RECORD'
                        else:
                            state['metrics']['matched_count']+=1
                            if (proof.canonical(frozen),proof.canonical(outcomes))!=current[:2]:
                                final_row=json.loads(os.pread(final_fd,current[3],current[2]),object_pairs_hook=proof.strict_object)
                                _,new_frozen,new_outcomes=values(final_row,dataset)
                                from disk_forensik import contained
                                if not contained(frozen,new_frozen):state['reason']='CHANGED_FROZEN_FIELD';state['metrics']['changed_record_count']+=1
                                elif not contained(outcomes,new_outcomes):state['reason']=state['reason'] or 'CHANGED_RESULT';state['metrics']['changed_record_count']+=1
                    else:state['metadata'][safe_field(field)]=metadata(field,row,dataset)
                    state['parser']=dict(stream.checkpoint);self.dirty=True
                state['metrics']['final_extra_record_count']=target['count']-state['metrics']['matched_count']
                if state['reason']:return self._complete(state,'UNIQUE_RECOVERY_CANDIDATE',state['reason'])
                for field,value in state['metadata'].items():
                    other=target['metadata'].get(field)
                    if other is None:return self._complete(state,'UNIQUE_RECOVERY_CANDIDATE','ROOT_METADATA_NOT_IN_FINAL')
                    if value['kind']=='clock':
                        if proof.history_time(value['value'])>proof.history_time(other['value']):return self._complete(state,'UNKNOWN','FUTURE_HISTORY_TIMESTAMP')
                    elif value['kind']=='count':
                        if value['value']!=state['count'] or other['value']!=target['count']:return self._complete(state,'UNKNOWN','INVALID_RECORD_COUNT')
                    elif value!=other:return self._complete(state,'UNIQUE_RECOVERY_CANDIDATE','ROOT_METADATA_DIFFERS')
                return self._complete(state,'PROVEN_SUBSET_OF_FINAL' if target['count']>state['count'] else 'PROVEN_OLDER_COMPLETE_COPY','RESUMED_COMPLETE_SEMANTIC_PROOF')
            finally:stream.close();db.commit()
        except TimeoutError:
            self.dirty=True
            progress=self.data['finals'].get(state.get('index'),{}) if state['stage']=='BUILD_FINAL' else state
            logging.info('[DISK_CHECKPOINT] masked_file=%s stage=%s offset=%s records=%d completed=false',identifier,state['stage'],progress.get('parser',{}).get('offset') if progress.get('parser') else state['offset'],progress.get('count',0))
            raise
        except (ValueError,UnicodeError,sqlite3.IntegrityError) as error:
            reason='PROOF_INDEX_CAPACITY' if str(error)=='PROOF_INDEX_CAPACITY' else 'PROOF_INDEX_UNVERIFIED' if str(error)=='Unowned proof index' else 'DUPLICATE_RECORD_ID' if isinstance(error,sqlite3.IntegrityError) else 'JSON_TRUNCATED_OR_UNSUPPORTED_SCHEMA'
            return self._complete(state,'UNKNOWN',reason)

    def _complete(self,state,classification,reason):
        state.update(completed=True,classification=classification,reason=reason);self.dirty=True
        return classification,reason,self._details(state)

    def _details(self,state):
        fields={k:v for k,v in state['metrics'].items() if k!='matched_count'}
        if state['stage'] in ('EXACT','PREFIX','SUFFIX'):fields={k:None for k in fields}
        fields.update(comparison_method='RESUMABLE_'+state['stage'],schema=state['dataset'],checkpoint_stage=state['stage'],checkpoint_offset=state.get('parser',{}).get('offset') if state.get('parser') else state['offset'])
        return fields
