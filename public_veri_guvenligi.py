"""Bounded live projections only. Damaged originals remain byte-for-byte intact.

No history, user, recovery or database files are admitted by this helper.
A regenerated projection is published as one bounded pending file until the
original can be recovered independently. No automatic deletion/repair occurs.
"""
import json
import hashlib
import errno
import logging
from pathlib import Path

NAMES={'bist_data.json','gun_ici_tum.json','borsa_fiyatlari.json','gun_ici_top10.json'}
MAX_BYTES=16*1024*1024

def record_key(path):
    name=Path(path).name.replace('.pending.json','.json')
    return 'top10' if name=='gun_ici_top10.json' else 'hisseler'



def pending_path(path):
    path=Path(path)
    if path.name not in NAMES:raise ValueError('Not a live public projection')
    return path.with_name(path.stem+'.pending.json')


def _read(path):
    if Path(path).is_symlink():raise PermissionError(errno.EPERM,'Projection symlink is not permitted')
    with Path(path).open('rb') as stream:
        raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Projection exceeds bounded read limit')
    doc=json.loads(raw);key=record_key(path)
    if isinstance(doc,list):doc={key:doc}
    if not isinstance(doc,dict) or not isinstance(doc.get(key),list):
        raise ValueError('Invalid live projection shape')
    if any(not isinstance(row,dict) for row in doc[key]):
        raise ValueError('Invalid live projection row')
    return doc


def read_public(path):
    path=Path(path);candidate=pending_path(path)
    try:return _read(path),False
    except FileNotFoundError:return {record_key(path):[]},False
    except (ValueError,UnicodeError):
        logging.warning('[PUBLIC_JSON] code=PUBLIC_JSON_CORRUPT file=%s original_preserved=true',path.name)
    try:return _read(candidate),True
    except FileNotFoundError:return {record_key(path):[]},True
    # A damaged candidate is not silently overwritten either.


def write_public(path,doc):
    from kullanici_kayitlari import atomic_json
    from atomik_depolama import thread_guard
    from ai_karar_motoru import locked
    path=Path(path)
    pending_path(path)  # Reject histories/users before even creating a lock file.
    with thread_guard(path),locked(path):
        previous,damaged=read_public(path)
        from fiyat_guncelligi import preserve_newer_price
        key=record_key(path)
        def identity(row):
            stock=row.get('sembol') or row.get('symbol') or row.get('kod')
            if isinstance(stock,str) and stock.strip():return stock.strip().upper()
            # Keep unidentifiable public rows intact, without inventing a stock identity.
            return 'UNIDENTIFIED:'+hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        prices={}
        for row in previous[key]:
            stock=identity(row);prices[stock]=preserve_newer_price(prices.get(stock,{}),row)
        rows={}
        if path.name in ('bist_data.json','gun_ici_tum.json'):rows.update(prices)
        for row in doc[key]:
            stock=identity(row)
            rows[stock]=preserve_newer_price(prices.get(stock,{}),row)
        doc={**doc,key:list(rows.values())}
        target=pending_path(path) if damaged else path
        atomic_json(target,doc)
    return {'original_preserved':damaged,'pending':damaged,'filename':target.name}


def serving_path(path):
    path=Path(path)
    try:
        _,damaged=read_public(path)
        candidate=pending_path(path)
        if damaged:return candidate if candidate.is_file() else path.parent/'.not-served'
    except (OSError,ValueError,UnicodeError):return path.parent/'.not-served'
    return path
