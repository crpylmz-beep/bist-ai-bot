"""Explicit existing JSON shapes; no inference from unrelated JSON collections."""
import re
import atomik_temp_temizligi as proof

SCHEMAS={'ai_ogrenme_gecmisi.json':('kayitlar',False),
         'tahmin_gecmisi.json':('tahminler',False),
         'gun_ici_sonuclar.json':('kayitlar',False),
         'haber_dedup.json':('haberler',False),
         'yarin_top10_sonuclar.json':('sonuclar',True)}


def stream(fd,dataset,deadline,resume=None):
    field,mapping=SCHEMAS[dataset]
    return proof.HistoryStream(fd,deadline,field,resume,mapping=mapping)


def identity(row,dataset):
    if not isinstance(row,dict):raise ValueError('Unsupported record')
    keys=('canonical_id',) if dataset=='haber_dedup.json' else ('kayit_id','prediction_id','signal_id','result_id','id')
    result=next((row[k] for k in keys if isinstance(row.get(k),str) and row[k]),None)
    if result is None or len(result)>512:raise ValueError('Missing stable record identity')
    if dataset=='haber_dedup.json' and not {'canonical_id','sembol','ana_baslik','ilk_gorulme','variants','effects'}<=row.keys():raise ValueError('Unsupported news schema')
    if dataset=='haber_dedup.json' and (not isinstance(row['variants'],list) or not row['variants'] or not all(isinstance(v,dict) for v in row['variants']) or not isinstance(row['effects'],dict)):raise ValueError('Unsupported news lifecycle')
    if dataset=='gun_ici_sonuclar.json' and not {'id','sembol','sinyal_zamani','giris_fiyati','sonuclar'}<=row.keys():raise ValueError('Unsupported intraday schema')
    return result


def parts(row,dataset):
    key=identity(row,dataset)
    if dataset=='ai_ogrenme_gecmisi.json':return proof.record_values(row)
    if dataset in ('tahmin_gecmisi.json','yarin_top10_sonuclar.json'):
        outcomes={k:v for k,v in row.items() if re.fullmatch(r'sonuc_\d+g',k)}
        return key,{k:v for k,v in row.items() if k not in outcomes},{k:v for k,v in outcomes.items() if v is not None}
    # News effects/lifecycle and intraday lifecycle are never normalized away.
    return key,row,{}


def relation(old,new,dataset):
    from disk_forensik import contained
    _,frozen,outcomes=parts(old,dataset)
    if new is None:return 'TEMP_ONLY'
    _,target,target_outcomes=parts(new,dataset)
    if proof.canonical(old)==proof.canonical(new):return 'IDENTICAL'
    if contained(frozen,target) and contained(outcomes,target_outcomes):return 'FINAL_NEWER_SAFE'
    if proof.canonical(frozen)==proof.canonical(target) and contained(target_outcomes,outcomes):return 'TEMP_NEWER_SAFE'
    # Any differing common immutable value or completed outcome is a conflict.
    if any(k in target and not contained(v,target[k]) for k,v in frozen.items()):return 'CONFLICT'
    if any(k in target_outcomes and not contained(v,target_outcomes[k]) for k,v in outcomes.items()):return 'CONFLICT'
    return 'UNRESOLVED'
