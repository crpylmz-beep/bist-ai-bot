"""Durable, fail-closed news-source access restrictions; no automatic reactivation."""
import fcntl
import json
from pathlib import Path
from kullanici_kayitlari import atomic_json, now
from veri_yollari import runtime_file
from gorev_hatalari import describe, public_issue

SOURCES={'KAP','EKONOMIM','BLOOMBERG_HT','ENSONHABER_EKONOMI'}
RESTRICTED={'HTTP_AUTH','HTTP_BLOCKED','HTTP_RATE_LIMIT','SOURCE_ACCESS_RESTRICTED',
            'SOURCE_ROBOTS_DENIED','SOURCE_CRAWL_DELAY'}


def restriction(error):
    issue=describe(error)
    if isinstance(error,ValueError) and str(error) in RESTRICTED:
        issue=public_issue({'code':str(error)})
    if issue.get('http_status') in (402,451):issue=public_issue({'code':'SOURCE_ACCESS_RESTRICTED'})
    return issue if issue['code'] in RESTRICTED else None


class SourceRestrictions:
    def __init__(self,path=None,health_path=None):
        self._blocked={}
        self.path=Path(path) if path is not None else runtime_file('news_source_restrictions.json')
        self.health_path=Path(health_path) if health_path is not None else runtime_file('economy_news_health.json')

    def _read(self,path):
        try:
            with path.open('rb') as stream:raw=stream.read(8193)
        except FileNotFoundError:return None
        if len(raw)>8192:raise ValueError('News policy size bound')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('Invalid news policy')
        return value

    def load(self,*,seed_health=True):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with Path(str(self.path)+'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            value=self._read(self.path)
            if value is None:value={'version':1,'sources':{}}
            rows=value.get('sources')
            if value.get('version')!=1 or not isinstance(rows,dict) or not set(rows)<=SOURCES:
                raise ValueError('Invalid news policy; preserved')
            for row in rows.values():
                if not isinstance(row,dict) or row.get('code') not in RESTRICTED or not isinstance(row.get('disabled_at'),str):
                    raise ValueError('Invalid news restriction; preserved')
            # Previously recorded access denials must not be retried once after deploy.
            health=(self._read(self.health_path) or {}) if seed_health else {}
            previous=health.get('sources',{})
            changed=False
            if isinstance(previous,dict):
                for source,row in previous.items():
                    if source in SOURCES and source not in rows and isinstance(row,dict) and row.get('code') in RESTRICTED:
                        rows[source]={'code':row['code'],'disabled_at':now()};changed=True
            if changed:atomic_json(self.path,value)
            return {**self._blocked,**rows}

    def disable(self,source,issue):
        if source not in SOURCES or issue.get('code') not in RESTRICTED:raise ValueError('Unsupported news restriction')
        self._blocked.setdefault(source,{'code':issue['code'],'disabled_at':now()})
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with Path(str(self.path)+'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            value=self._read(self.path)
            if value is None:value={'version':1,'sources':{}}
            if value.get('version')!=1 or not isinstance(value.get('sources'),dict) or not set(value['sources'])<=SOURCES:
                raise ValueError('Invalid news policy; preserved')
            for row in value['sources'].values():
                if not isinstance(row,dict) or row.get('code') not in RESTRICTED or not isinstance(row.get('disabled_at'),str):
                    raise ValueError('Invalid news restriction; preserved')
            if source not in value['sources']:
                value['sources'][source]=self._blocked[source]
                atomic_json(self.path,value)
            return value['sources'][source]

    def call(self,source,callback):
        row=self.load(seed_health=source!='KAP').get(source)
        if row:
            return {'diagnostics':{'skipped':1,'successful':0},'restriction':row['code']}
        try:return callback()
        except Exception as error:
            issue=restriction(error)
            if issue:self.disable(source,issue)
            raise
