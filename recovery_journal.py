"""Private, bounded recovery payload WAL. No automatic compaction or full rewrite."""
import hashlib
import json
import logging
import os
from pathlib import Path
import stat
from history_journal import HistoryJournal,JournalError
import atomik_temp_temizligi as proof
from storage_schemas import SCHEMAS,identity,relation


class RecoveryJournal(HistoryJournal):
    def __init__(self,target):
        super().__init__(target)
        if self.target.name not in SCHEMAS:raise ValueError('Recovery schema unsupported')
        token=hashlib.sha256(self.target.name.encode()).hexdigest()[:24]
        self.path=self.target.parent/('.storage-recovery-v5-'+token+'.wal')
        self.lock=self.target.parent/('.storage-recovery-v5-'+token+'.lock')

    def operations(self):
        with self.locked():return self._operations_unlocked()

    def _operations_unlocked(self):
        result={}
        for transaction in self.transactions():
            if transaction['root']:raise JournalError('WAL_INVALID_RECOVERY_ROOT')
            for op in transaction['rows']:
                if not isinstance(op,dict) or not isinstance(op.get('record'),dict) or op.get('dataset')!=self.target.name:raise JournalError('WAL_INVALID_RECOVERY_OPERATION')
                key=proof.canonical(identity(op['record'],self.target.name))
                if op.get('id')!=key or op.get('kind') not in ('TEMP_ONLY','TEMP_NEWER_SAFE'):raise JournalError('WAL_INVALID_RECOVERY_ID')
                if key in result and proof.canonical(result[key])!=proof.canonical(op):raise JournalError('WAL_CONFLICT: recovery payload differs')
                result[key]=op
        return result

    def stage(self,row,kind,base=None):
        op={'dataset':self.target.name,'id':proof.canonical(identity(row,self.target.name)),
            'kind':kind,'record':row,'base_hash':proof.canonical(base) if base is not None else None}
        with self.locked():
            existing=self._operations_unlocked()
            if op['id'] in existing:
                previous=existing[op['id']]
                if proof.canonical(previous['record'])!=proof.canonical(row):raise JournalError('WAL_CONFLICT: recovered versions differ')
                # Re-fsync a complete line after a previous ambiguous fsync failure.
                fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
                try:os.fsync(fd)
                finally:os.close(fd)
                self.sync_directory()
                return False
            self._append_locked({'rows':[op],'root':[]})
            return True

    def sync_directory(self):
        fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

    def flush(self):raise ValueError('Recovery WAL only merges through a normal guarded producer commit')

    def overlay(self,document):
        if not self.path.exists():return document
        operations=self.operations();field,mapping=SCHEMAS[self.target.name]
        collection=document.get(field)
        if not isinstance(collection,dict if mapping else list):raise JournalError('WAL_INVALID_FINAL_SCHEMA')
        result=dict(document);rows=dict(collection) if mapping else list(collection)
        indexes={}
        for position,row in (rows.items() if mapping else enumerate(rows)):
            key=proof.canonical(identity(row,self.target.name))
            if key in indexes:raise JournalError('WAL_INVALID_DUPLICATE_FINAL_ID')
            indexes[key]=position
        conflicts=0
        for key,op in operations.items():
            position=indexes.get(key);current=rows[position] if position is not None else None
            status=relation(op['record'],current,self.target.name)
            if status=='TEMP_ONLY':
                if op['kind']!='TEMP_ONLY':conflicts+=1;continue
                if mapping:position=identity(op['record'],self.target.name);rows[position]=op['record']
                else:position=len(rows);rows.append(op['record'])
                indexes[key]=position
            elif status in ('IDENTICAL','FINAL_NEWER_SAFE'):continue
            elif status=='TEMP_NEWER_SAFE' and proof.canonical(current)==op['base_hash']:rows[position]=op['record']
            else:conflicts+=1  # Canonical and WAL both remain; never pick a conflict.
        if conflicts:logging.warning('[STORAGE_RECOVERY] dataset=%s overlay_conflicts=%d payload_retained=true',self.target.name,conflicts)
        result[field]=rows
        if 'toplam_kayit' in result:result['toplam_kayit']=len(rows)
        return result


def apply_overlay(path,document):
    path=Path(path)
    if path.name not in SCHEMAS:return document
    from veri_yollari import paths
    location=paths()
    expected=location.runtime_file(path.name) if path.name in ('ai_ogrenme_gecmisi.json','tahmin_gecmisi.json') else location.runtime/path.name
    if not location.root or path.absolute()!=expected.absolute():return document
    journal=RecoveryJournal(path)
    return journal.overlay(document)


def read_document(path,default=None):
    from v6_storage.backend import read
    handled,document=read(path)
    if handled:return document
    path=Path(path)
    if not path.exists():return default
    with path.open(encoding='utf-8') as handle:document=json.load(handle,object_pairs_hook=proof.strict_object)
    return apply_overlay(path,document)


def read_handle(handle):
    from v6_storage.backend import read
    handled,document=read(handle.name)
    if handled:return document
    document=json.load(handle)
    return apply_overlay(handle.name,document)
