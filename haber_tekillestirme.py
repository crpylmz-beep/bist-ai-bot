"""Conservative, deterministic canonical company-news ledger and effect gate."""
from difflib import SequenceMatcher
from decimal import Decimal
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import fcntl
import hashlib
import inspect
import json
import os
import re
import uuid

from kullanici_kayitlari import atomic_json, now, symbol
from veri_yollari import paths, data_file, public_file
from sirket_site_icerik import canonical, published_time

STOP={'a','s','as','anonim','sirketi','sirket','yeni','tutarinda','tutarli','bir','ile','ve','imzaladi','imzalandi','imzalanmasi','yapildi','hakkinda','aciklama','ozel','durum'}
GENERIC={'sozlesme','ihale','yatirim','finansal','sonuc','duyuru','haber','imza'}


def normalize(value,stock=''):
    text=str(value or '').casefold().translate(str.maketrans('çğıöşü','cgiosu')).replace('i̇','i')
    text=re.sub(r'\b'+re.escape(stock.lower())+r'\b',' ',text) if stock else text
    return ' '.join(re.findall(r'[a-z0-9]+',text))


def tokens(value,stock=''):
    return {t for t in normalize(value,stock).split() if t not in STOP}


def amounts(value):
    text=str(value or '').lower().translate(str.maketrans('çğıöşü','cgiosu'))
    result=set()
    for match in re.finditer(r'(\d+(?:[.,]\d+)*)\s*(milyon|milyar|million|billion)?\s*(tl|try|usd|dolar|eur|euro|%|adet)\b',text):
        number,scale,unit=match.groups()
        if ',' in number:number=number.replace('.','').replace(',','.')
        elif number.count('.')>1 or ('.' in number and len(number.rsplit('.',1)[-1])==3):number=number.replace('.','')
        value=Decimal(number)*({'milyon':10**6,'million':10**6,'milyar':10**9,'billion':10**9}.get(scale,1))
        unit={'try':'tl','dolar':'usd','euro':'eur'}.get(unit,unit)
        result.add((unit,str(value.normalize())))
    return result


def prepare(event):
    row=dict(event);row['sembol']=symbol(row['sembol'])
    row['kaynak']='KAP' if row.get('kaynak')=='KAP' else 'SIRKET_SITE'
    row['baslik']=str(row.get('baslik','')).strip()[:500]
    row['metin']=str(row.get('metin',''))[:12000]
    row['discovered_at']=row.get('discovered_at') or now()
    row['published_at']=published_time(row.get('published_at'))
    row['event_time']=(row['published_at'] if row.get('published_precision')!='day' else None) or row['discovered_at']
    date=datetime.fromisoformat(row['event_time'])
    if date.tzinfo is None:raise ValueError('Haber zamanı aware datetime olmalı')
    row['url']=row.get('url') or ''
    row['normalized_title']=normalize(row['baslik'],row['sembol'])
    row['normalized_text']=normalize(row['metin'],row['sembol'])
    row['content_hash']=hashlib.sha256(row['normalized_text'].encode()).hexdigest()
    if not row['baslik']:raise ValueError('Haber başlığı gerekiyor')
    return row


def compare(a,b,window_seconds=21600):
    if a['sembol']!=b['sembol']:return 'DIFFERENT_EVENT'
    delta=abs((datetime.fromisoformat(a['event_time'])-datetime.fromisoformat(b['event_time'])).total_seconds())
    if delta>window_seconds:return 'DIFFERENT_EVENT'
    for action in ('iptal','fesih','sonlandir','yenile','uzat'):
        if (action in a['normalized_title']) != (action in b['normalized_title']):
            return 'DIFFERENT_EVENT'
    ta,tb=tokens(a['baslik'],a['sembol']),tokens(b['baslik'],b['sembol'])
    aa,ab=amounts(a['baslik']+' '+a['metin']),amounts(b['baslik']+' '+b['metin'])
    for unit in {u for u,_ in aa}&{u for u,_ in ab}:
        if {v for u,v in aa if u==unit}!={v for u,v in ab if u==unit}:return 'DIFFERENT_EVENT'
    # Differing explicit identifiers/counterparties must not disappear in fuzzy matching.
    facts_a={t for t in ta if any(c.isdigit() for c in t)}
    facts_b={t for t in tb if any(c.isdigit() for c in t)}
    if facts_a and facts_b and facts_a!=facts_b and aa!=ab:return 'DIFFERENT_EVENT'
    body_a,body_b=a['normalized_text'],b['normalized_text']
    shared=ta&tb;informative=shared-GENERIC
    same_title=a['normalized_title']==b['normalized_title']
    same_body=bool(body_a and body_b and a['content_hash']==b['content_hash'])
    try:same_url=bool(a['url'] and b['url'] and canonical(a['url'])==canonical(b['url']))
    except ValueError:same_url=False
    if same_title:
        same_source_entry=a['kaynak']==b['kaynak'] and same_url and same_body
        if len(ta)<3 and not (same_body and len(body_a)>=60) and not same_source_entry:return 'DIFFERENT_EVENT'
        if body_a and body_b and not same_body and SequenceMatcher(None,body_a,body_b).ratio()<.65:return 'DIFFERENT_EVENT'
        return 'EXACT_DUPLICATE'
    residual_a=ta-tb-GENERIC-{'milyon','milyar','tl','usd','eur'}
    residual_b=tb-ta-GENERIC-{'milyon','milyar','tl','usd','eur'}
    if residual_a and residual_b:return 'DIFFERENT_EVENT'
    if same_body and len(body_a)>=60 and len(shared)>=2:return 'EXACT_DUPLICATE'
    title_score=SequenceMatcher(None,' '.join(sorted(ta)),' '.join(sorted(tb))).ratio()
    overlap=len(shared)/max(1,min(len(ta),len(tb)))
    body_score=SequenceMatcher(None,body_a,body_b).ratio() if body_a and body_b else 0
    if same_url and title_score>=.8 and overlap>=.8 and len(shared)>=3:return 'EXACT_DUPLICATE'
    strong_fact=bool(aa and aa==ab)
    # Amount+event example matches despite company-prefix/verb differences.
    if strong_fact and overlap>=.75 and len(shared)>=3:return 'LIKELY_DUPLICATE'
    if title_score>=.88 and overlap>=.8 and len(informative)>=2 and (body_score>=.75 or not body_a or not body_b):return 'LIKELY_DUPLICATE'
    return 'DIFFERENT_EVENT'


class CanonicalNews:
    def __init__(self,directory=None,public_path=None,history_path=None,window_seconds=None):
        directory=Path(directory) if directory else paths().runtime
        self.path=directory/'haber_dedup.json';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.public_path=Path(public_path) if public_path else public_file('canonical_haberler.json')
        self.history_path=Path(history_path) if history_path else data_file('haber_zeka_gecmisi.json')
        self.window=float(window_seconds if window_seconds is not None else os.environ.get('NEWS_DEDUP_WINDOW_SECONDS','21600'))
        if not 60<=self.window<=604800:raise ValueError('Dedup zaman penceresi 60–604800 saniye')

    def _publish(self,data):
        rows=[]
        for record in data['haberler']:
            if 'analiz' not in record:continue
            analysis=record['analiz'];alarm=record.get('alarm',{})
            rows.append({'canonical_id':record['canonical_id'],'id':record['canonical_id'],
                         'sembol':record['sembol'],'baslik':record['ana_baslik'],'tarih':record['ilk_gorulme'],
                         'kaynak_etiketi':record['kaynak_etiketi'],'kaynaklar':record['kaynaklar'],
                         'kap_url':record.get('kap_url'),'sirket_url':record.get('sirket_url'),
                         'duplicate_status':record['duplicate_status'],
                         **{k:analysis.get(k) for k in ('etki_puani','etki_sinifi','guven','onem','fiyatlandi_riski')},
                         'alarm_seviyesi':alarm.get('seviye','YOK')})
        self.public_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic_json(self.public_path,{'surum':1,'guncelleme':now(),'alarmlar':rows[-500:][::-1]})

    def _history(self,record):
        import haber_zeka
        analysis=dict(record['analiz'],canonical_id=record['canonical_id'],kaynak=record['kaynak_etiketi'],
                      kaynaklar=record['kaynaklar'],baslik=record['ana_baslik'],kap_url=record.get('kap_url'),sirket_url=record.get('sirket_url'))
        haber_zeka.haber_kaydet(analysis,tarih=record['ilk_gorulme'],store_path=self.history_path)
        # Enrich the existing canonical record without adding another score/history row.
        with Path(str(self.history_path)+'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            data=json.loads(self.history_path.read_text())
            for row in data['haberler']:
                if row.get('canonical_id')==record['canonical_id']:
                    row.update(kaynak=record['kaynak_etiketi'],kaynaklar=record['kaynaklar'],baslik=record['ana_baslik'],kap_url=record.get('kap_url'),sirket_url=record.get('sirket_url'))
            atomic_json(self.history_path,data)

    def process(self,event,enqueue,analyze=None,alarm_writer=None,notification_writer=None):
        import haber_zeka
        event=prepare(event)
        with Path(str(self.path)+'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            from recovery_journal import read_document
            data=read_document(self.path,{'surum':1,'haberler':[]})
            match=None;status='DIFFERENT_EVENT'
            for record in reversed(data['haberler']):
                anchor=record['variants'][0]
                if event['sembol']!=record['sembol'] or abs((datetime.fromisoformat(event['event_time'])-datetime.fromisoformat(anchor['event_time'])).total_seconds())>self.window:
                    continue
                for variant in record['variants']:
                    level=compare(event,variant,self.window)
                    if level!='DIFFERENT_EVENT':match=record;status=level;break
                if match:break
            created=match is None
            if created:
                match={'canonical_id':uuid.uuid4().hex,'sembol':event['sembol'],'ana_baslik':event['baslik'],
                       'ilk_gorulme':event['discovered_at'],'son_gorulme':event['discovered_at'],
                       'kaynaklar':[],'hashler':[],'variants':[],'effects':{}}
                data['haberler'].append(match)
            source={'kaynak':event['kaynak'],'url':event['url'],'published_at':event['published_at']}
            if source not in match['kaynaklar']:match['kaynaklar'].append(source)
            if event['content_hash'] not in match['hashler']:match['hashler'].append(event['content_hash'])
            if not any(v['normalized_title']==event['normalized_title'] and v['content_hash']==event['content_hash'] for v in match['variants']):match['variants'].append(event)
            sources={s['kaynak'] for s in match['kaynaklar']}
            match['kaynak_etiketi']='KAP + ŞİRKET_SITE' if len(sources)>1 else ('KAP' if 'KAP' in sources else 'ŞİRKET_SITE')
            if event['kaynak']=='KAP':
                match.update(ana_baslik=event['baslik'],ana_kaynak='KAP',kap_url=event['url'] or None)
            else:
                match.setdefault('ana_kaynak','SIRKET_SITE');match['sirket_url']=event['url'] or None
            match.update(son_gorulme=event['discovered_at'],duplicate_status=status)
            atomic_json(self.path,data)
            if 'analiz' not in match:
                match['analiz']=analyze(event) if analyze else haber_zeka.kap_haber_analiz_et(event['sembol'],event['baslik'],event['metin'],kaynak=event['kaynak'])
                match['analiz'].update(sembol=event['sembol'],baslik=event['baslik'],metin=event['metin'],content_id=event.get('content_id',match['canonical_id']))
                score=match['analiz'].get('etki_puani',0)
                match['analiz'].setdefault('yon','POZITIF' if score>0 else 'NEGATIF' if score<0 else 'NOTR')
                match['analiz'].setdefault('gerekce','; '.join(match['analiz'].get('nedenler',[])) or 'Belirgin haber kriteri bulunamadı.')
                atomic_json(self.path,data)
            self._history(match)
            if 'alarm' not in match:
                match['alarm']=haber_zeka.kap_alarm_uret(match['analiz'])
                atomic_json(self.path,data)
            for stage,callback in (('alarm',alarm_writer),('notification',notification_writer),('enqueue',enqueue)):
                if match['effects'].get(stage) in ('DONE','SKIPPED'):continue
                if stage=='alarm' and not match['alarm'].get('alarm'):match['effects'][stage]='DONE';continue
                if callback is None:match['effects'][stage]='SKIPPED';continue
                # Every effect carries a durable canonical idempotency key.
                if stage=='enqueue':
                    signature=inspect.signature(callback)
                    kw={'gun_ici_yenile':False}
                    if 'event_id' in signature.parameters or any(p.kind==p.VAR_KEYWORD for p in signature.parameters.values()):kw['event_id']=match['canonical_id']
                    callback(event['sembol'],**kw)
                else:callback(dict(match['analiz'],canonical_id=match['canonical_id'],kaynak_etiketi=match['kaynak_etiketi']),match['alarm'])
                match['effects'][stage]='DONE';atomic_json(self.path,data)
            atomic_json(self.path,data)
            self._publish(data)
            return {'canonical_id':match['canonical_id'],'duplicate_status':status,'created':created,
                    'analiz':match['analiz'],'alarm':match['alarm'],'kaynak_etiketi':match['kaynak_etiketi']}
