"""Storage decomposition uses actual producer fields; no trading calculations."""
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from storage_schemas import SCHEMAS
from atomik_temp_temizligi import record_values

ISTANBUL=ZoneInfo('Europe/Istanbul')
LEGACY_FIELDS=('sonuc','sonuc_fiyat','sonuc_zaman','getiri_yuzde','hedef_vurdu','stop_vurdu','sat_hedef','sat_stop')


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(value):
    hashed=hashlib.sha256()
    for token in json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).iterencode(value):hashed.update(token.encode())
    return hashed.hexdigest()
def now():return datetime.now(ISTANBUL).isoformat()


@dataclass(frozen=True)
class Shape:
    dataset:str
    fields:dict
    kind:str='prediction'


def shape_for(path,location):
    path=Path(path).absolute()
    if path.name in SCHEMAS and path.name!='haber_dedup.json' and path==location.runtime_file(path.name).absolute():
        field,mapping=SCHEMAS[path.name];fields={field:'mapping' if mapping else 'list'}
        if path.name=='gun_ici_sonuclar.json':fields['listeler']='list'
        if path.name=='tahmin_gecmisi.json':fields['ogrenme_gecmisi']='list'
        return Shape('runtime/'+path.name,fields,'learning' if path.name=='ai_ogrenme_gecmisi.json' else 'prediction')
    parent=path.parent.name
    if path.parent.parent==location.runtime.absolute() and re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',path.name):
        if parent=='gunluk_al_sat_gecmisi':return Shape('runtime/'+parent+'/'+path.name,{'events':'mapping'},'signal')
        if parent=='intraday_signal_results':return Shape('runtime/'+parent+'/'+path.name,{'events':'mapping'},'signal_outcome')
    if path.parent==location.archives.absolute() and re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',path.name):
        return Shape('archives/yarin_top10_arsiv/'+path.name,{key:'list' for key in ('top10','ham_top10','shadow_top10','controlled_shadow_top10','base_top10','pozitif_havuz.adaylar')},'tomorrow_snapshot')
    return None


def identity(row,mapping_key=None):
    if not isinstance(row,dict):raise ValueError('STORAGE_RECORD_SCHEMA')
    key=next((row[k] for k in ('kayit_id','event_id','prediction_id','signal_id','result_id','id','canonical_id') if isinstance(row.get(k),str) and row[k]),mapping_key)
    if not isinstance(key,str) or not key or len(key)>512 or mapping_key is not None and key!=mapping_key:raise ValueError('STORAGE_RECORD_ID')
    return key


def completed(value):
    if value is None:return False
    if isinstance(value,dict):
        for flag in ('degerlendirme_tamamlandi','tamamlandi','completed'):
            if flag in value:return value[flag] is True
    return True


def split(row,dataset):
    """Immutable forecast fields, mutable lifecycle and independently frozen outcomes."""
    frozen=copy.deepcopy(row);state={};outcomes={}
    for key in list(frozen):
        if re.fullmatch(r'sonuc_\d+g',key):
            value=frozen.pop(key)
            if completed(value):outcomes[key]=value
            else:state[key]=value
    name=dataset.split('#')[0].split('/')[-1]
    if name=='ai_ogrenme_gecmisi.json' and row.get('model')=='GUN_ICI' and row.get('egitim_durumu') in ('EGITIM','TAMAMLANDI') and row.get('sonuc') in ('BEKLIYOR','BASARILI','BASARISIZ'):
        # Validate the exact legacy shape with the existing V5 adapter first.
        _,_,legacy=record_values(row)
        for key in LEGACY_FIELDS+('egitim_durumu',):
            if key in frozen:state[key]=frozen.pop(key)
        outcomes.update(legacy)
    if name=='tahmin_gecmisi.json' and 'takip' in frozen:state['takip']=frozen.pop('takip')
    if name=='gun_ici_sonuclar.json' and '#kayitlar' in dataset:
        for key in ('durum','sinyal_yasi_dk','retry_at'):
            if key in frozen:state[key]=frozen.pop(key)
        values=frozen.pop('sonuclar',{})
        if not isinstance(values,dict):raise ValueError('STORAGE_OUTCOME_SCHEMA')
        state['sonuclar']={}
        for horizon,value in values.items():
            if completed(value):outcomes['sonuclar:'+horizon]=value
            else:state['sonuclar'][horizon]=value
    if '/intraday_signal_results/' in dataset:
        for key in ('retry_at',):
            if key in frozen:state[key]=frozen.pop(key)
        values=frozen.pop('outcomes',{})
        if not isinstance(values,dict):raise ValueError('STORAGE_OUTCOME_SCHEMA')
        state['outcomes']={}
        for horizon,value in values.items():
            if completed(value):outcomes['outcomes:'+horizon]=value
            else:state['outcomes'][horizon]=value
    return frozen,state,outcomes


def assemble(frozen,extensions,state,outcomes):
    row=copy.deepcopy(frozen);row.update(copy.deepcopy(extensions));row.update(copy.deepcopy(state))
    for key,value in outcomes.items():
        if key in ('legacy_result','legacy_levels'):row.update(copy.deepcopy(value))
        elif ':' in key:
            field,horizon=key.split(':',1);row.setdefault(field,{})[horizon]=copy.deepcopy(value)
        else:row[key]=copy.deepcopy(value)
    return row


def row_time(row):
    value=next((row.get(k) for k in ('sinyal_zamani','timestamp','zaman','tahmin_zamani','analiz_zamani') if row.get(k)),None)
    if value is None and isinstance(row.get('tahmin'),dict):return row_time(row['tahmin'])
    if value is None:return None
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.replace(tzinfo=ISTANBUL) if parsed.tzinfo is None else parsed.astimezone(ISTANBUL)
    except (ValueError,TypeError):return None


def get_field(document,field):
    value=document
    for part in field.split('.'):
        if not isinstance(value,dict) or part not in value:return None
        value=value[part]
    return value


def set_field(document,field,value):
    parts=field.split('.');target=document
    for part in parts[:-1]:target=target.setdefault(part,{})
    target[parts[-1]]=value


def document_parts(shape,document):
    if not isinstance(document,dict):raise ValueError('STORAGE_DOCUMENT_SCHEMA')
    metadata=dict(document);collections={};rows={}
    for field,mode in shape.fields.items():
        value=get_field(document,field)
        if value is None:continue
        if not isinstance(value,dict if mode=='mapping' else list):raise ValueError('STORAGE_COLLECTION_SCHEMA')
        collections[field]=mode;rows[field]=value
        parts=field.split('.');target=metadata
        for part in parts[:-1]:
            target[part]=dict(target[part]);target=target[part]
        target.pop(parts[-1])
    if not collections:raise ValueError('STORAGE_COLLECTION_MISSING')
    return Shape(shape.dataset,collections,shape.kind),metadata,rows


def row_key(shape,field,row,mapping_key=None):
    try:return identity(row,mapping_key)
    except ValueError:
        if mapping_key is not None:raise
        symbol=row.get('sembol') or row.get('symbol') if isinstance(row,dict) else None
        if shape.kind=='tomorrow_snapshot' and isinstance(symbol,str) and symbol:return shape.dataset.split('/')[-1]+':'+symbol
        if field=='ogrenme_gecmisi' and isinstance(row,dict):return 'content:'+digest(row)
        raise
