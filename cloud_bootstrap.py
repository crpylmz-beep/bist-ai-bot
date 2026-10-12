"""Create public startup data only; preserve timestamps, archives and private files."""
import fcntl
import json
from pathlib import Path
import re
import errno
import logging

from veri_yollari import paths, copy_new

PUBLIC_SEEDS = ('bist_data.json','gun_ici_top10.json','gun_ici_tum.json','yarin_top10.json')
BASIC = {
    'bist_data.json': {'hisseler':[], 'bist100':{}, 'bootstrap_status':'WAITING_FOR_PROVIDER'},
    'gun_ici_top10.json': {'top10':[], 'bootstrap_status':'WAITING_FOR_SESSION'},
    'gun_ici_tum.json': {'hisseler':[], 'bootstrap_status':'WAITING_FOR_SESSION'},
    'yarin_top10.json': {'top10':[], 'bootstrap_status':'WAITING_FOR_PREDICTION'},
}


def valid_document(path):
    try:
        doc=json.loads(path.read_text(encoding='utf-8'))
        return doc if isinstance(doc,dict) else None
    except (OSError,ValueError):
        return None


def bootstrap_public(location=None, seed=None):
    try:return _bootstrap_public(location,seed)
    except OSError as error:
        if error.errno not in (errno.ENOSPC,errno.EDQUOT):raise
        logging.warning('[DISK] Public bootstrap alan yetersizliği nedeniyle ertelendi; mevcut veri korunuyor')
        return {'created':0,'storage_status':'INSUFFICIENT_SPACE'}


def _bootstrap_public(location=None, seed=None):
    location=location or paths()
    location.ensure()
    # Deployed Docker seeds or existing local repo public data.
    seed=Path(seed) if seed is not None else location.repo/'seed-public'
    if not seed.is_dir():seed=location.repo/'webapp/data'
    copied=0
    with (location.runtime/'public_bootstrap.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for name in ('sektor_haritasi.json','sirket_site_haritasi.json',*PUBLIC_SEEDS):
            source=seed/name;target=location.public_file(name)
            if valid_document(source) is not None and source.resolve()!=target.resolve():
                copied+=copy_new(source,target)
        for source in sorted((seed/'yarin_top10_arsiv').glob('*.json')):
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',source.name) and valid_document(source):
                target=location.archives/source.name
                if source.resolve()!=target.resolve():copied+=copy_new(source,target)
        # Legacy frozen prediction: create a byte-identical dated archive only once.
        pointer=valid_document(location.public/'yarin_top10.json') or {}
        day=pointer.get('analiz_tarihi','')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(day)) and pointer.get('top10'):
            copied+=copy_new(location.public/'yarin_top10.json',location.archives/(day+'.json'))
        # Public view may advance to the latest existing archive; archives never change.
        archives=[p for p in sorted(location.archives.glob('*.json'),reverse=True)
                  if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',p.name) and valid_document(p)
                  and valid_document(p).get('analiz_tarihi') == p.stem and valid_document(p).get('top10')]
        if archives and (not pointer.get('top10') or archives[0].stem > str(day)):
            from kullanici_kayitlari import atomic_json
            atomic_json(location.public/'yarin_top10.json',valid_document(archives[0]))
            copied+=1
        # No fabricated market prices or predictions when no historical source exists.
        for name,doc in BASIC.items():
            target=location.public_file(name)
            if not target.exists():
                import tempfile
                with tempfile.TemporaryDirectory() as directory:
                    source=Path(directory)/name
                    source.write_text(json.dumps(doc),encoding='utf-8')
                    copied+=copy_new(source,target)
    return {'created':copied}
