"""Versioned bounded calibration around, never inside, the existing tomorrow score."""
from datetime import datetime
import hashlib
import json
import os

from ai_karar_motoru import ISTANBUL,load,locked,number,stamp
from performans_motoru import criterion_report,minimum_samples,robust,summarize
from kullanici_kayitlari import atomic_json
from veri_yollari import paths

CRITERIA=('RSI','MACD','SMA_TREND','HACIM','MOMENTUM','DESTEK_DIRENC','RISK_GETIRI','HABER','MAKRO','SEKTOR','FIYAT_TEYIDI')
BASE={k:1/len(CRITERIA) for k in CRITERIA}


def bounded(values,baseline):
    lower={k:max(BASE[k]*.5,baseline[k]-.005) for k in BASE}
    upper={k:min(BASE[k]*1.5,baseline[k]+.005) for k in BASE}
    low,high=-1.,1.
    for _ in range(80):
        shift=(low+high)/2
        result={k:max(lower[k],min(upper[k],values[k]+shift)) for k in BASE}
        if sum(result.values())<1:low=shift
        else:high=shift
    return {k:round(v,12) for k,v in result.items()}


def features(record):
    row=dict(record.get('kriterler') or record)
    def pair(a,b):
        x,y=number(row.get(a)),number(row.get(b));return x>y if x is not None and y is not None else None
    def value(key,test):
        n=number(row.get(key));return test(n) if n is not None else None
    price,resistance=number(row.get('fiyat')),number(row.get('direnc'))
    room=(resistance/price-1)*100 if price and resistance else None
    return {'RSI':value('rsi',lambda v:45<=v<=64),'MACD':pair('macd','signal'),'SMA_TREND':pair('sma20','sma50'),
        'HACIM':value('hacim_orani',lambda v:v>=150),'MOMENTUM':value('degisim',lambda v:0<v<=4),
        'DESTEK_DIRENC':3<=room<=25 if room is not None else None,'RISK_GETIRI':value('risk_getiri',lambda v:v>=1.5),
        'HABER':value('haber_puani',lambda v:v>0),'MAKRO':value('makro_puani',lambda v:v>0),
        'SEKTOR':value('sektor_puani',lambda v:v>0),'FIYAT_TEYIDI':value('yarin_haber_fiyat_teyidi',lambda v:v>0)}


def evidence(records,asof):
    eligible=[]
    for record in records:
        if record.get('model')!='YARIN_TOP10' or record.get('egitim_durumu')=='REFERANS':continue
        result=record.get('sonuc_1g') or {}
        available=stamp(result.get('observed_at'));predicted=stamp(record.get('zaman'))
        if not available or not predicted or available>asof or predicted>=asof:continue
        if not result.get('degerlendirme_tamamlandi') or result.get('durum')=='VERI_YETERSIZ':continue
        outcome_day=stamp(result.get('tarih'))
        if not outcome_day or outcome_day.date()>asof.date() or outcome_day.weekday()>=5:continue
        # Independent-day count uses completed outcome sessions, not arbitrary weekend timestamps.
        copy=dict(record,zaman=outcome_day.isoformat())
        eligible.append(copy)
    return eligible


def adjustments(report,previous,baseline):
    proposed=dict(previous);approved={}
    for key in CRITERIA:
        entry=report['kriterler'][key]
        direction=entry['onerilen_agirlik_yonu']
        interval=entry['fark_guven_araligi']
        valid=entry['yeterli_veri'] and entry['guven']=='YETERLI' and min(entry['bagimsiz_gunler'])>=5
        valid=valid and min(entry['varken']['ornek'],entry['yokken']['ornek'])>=max(40,minimum_samples())
        valid=valid and interval[0] is not None and (interval[0]>0 if direction=='ARTIR' else interval[1]<0 if direction=='AZALT' else False)
        if valid:
            proposed[key]+=.0025 if direction=='ARTIR' else -.0025
            approved[key]={'yon':direction,'ornek':[entry['varken']['ornek'],entry['yokken']['ornek']],
                'gunler':entry['bagimsiz_gunler'],'guven':entry['guven'],'performans_farki':entry['basari_farki'],
                'medyan_farki':entry['varken']['medyan']-entry['yokken']['medyan']}
    weights=bounded(proposed,baseline) if approved else dict(previous)
    return weights,approved


def correction(row,weights,allowed):
    flags=features(row);parts={k:round((weights[k]-BASE[k])*100,6) if flags[k] is True and k in allowed else 0 for k in BASE}
    limit=float(os.environ.get('YARIN_CALIBRATION_MAX_POINTS','3'))
    if not 0<=limit<=5:raise ValueError('YARIN_CALIBRATION_MAX_POINTS: 0–5')
    result=max(-limit,min(limit,sum(parts.values())))
    # Never counteract negative-event or excessive-rise penalties with a positive bonus.
    unsafe=number(row.get('degisim'),0)>4 or number(row.get('rsi'),50)>=64 or any(number(row.get(k),0)<0 for k in ('haber_puani','makro_puani','sektor_puani'))
    if unsafe:result=min(0,result)
    return round(result,6),parts,unsafe


def score(row,raw,model):
    if raw<55:
        delta=shadow_delta=0;parts={};unsafe=True
    else:
        active=model.get('active') or {'general':BASE}
        shadow=model.get('shadow') or {'general':BASE}
        def select(variant):
            coefficients=dict(variant['general'])
            allowed=set(variant.get('approved',{}))
            # Scope deltas are small; unknown or under-sampled scope falls back to general.
            for field,pool in (('makro_sektor','sectors'),('piyasa_rejimi','regimes')):
                scoped=variant.get(pool,{}).get(row.get(field))
                if scoped:
                    coefficients={k:coefficients[k]*.85+scoped[k]*.15 for k in BASE}
                    allowed.update(variant.get('scope_approved',{}).get(pool,{}).get(row.get(field),{}))
            return coefficients,allowed
        shadow_delta,_,shadow_unsafe=correction(row,*select(shadow))
        delta,parts,unsafe=correction(row,*select(active)) if model.get('learning_enabled') else (0,{},shadow_unsafe)
    final=max(0,min(95,raw+delta)) if raw>=0 else raw
    shadow_score=max(0,min(95,raw+shadow_delta)) if raw>=0 else raw
    return {'ham_puan':raw,'kalibrasyon_duzeltmesi':round(final-raw,6),'final_puan':round(final,6),
        'shadow_puan':round(shadow_score,6),'kalibrasyon_katkilari':parts,'kalibrasyon_guvenlik_engeli':unsafe,
        'calibration_version':model.get('active_version','BASE') if model.get('learning_enabled') else 'BASE',
        'shadow_version':model.get('shadow_version','BASE'),'learning_enabled':bool(model.get('learning_enabled'))}


class YarinKalibrasyon:
    def __init__(self,location=None,clock=None):
        self.location=location or paths();self.clock=clock or (lambda:datetime.now(ISTANBUL))
        self.path=self.location.runtime/'yarin_kalibrasyon.json'
        self.history=self.location.runtime/'yarin_agirlik_gecmisi.json'

    def state(self):
        return load(self.path,{'versions':{},'active_version':'BASE','shadow_version':'BASE','days':{}})

    @staticmethod
    def variant(state,version):
        return state['versions'].get(version,{'general':dict(BASE),'sectors':{},'regimes':{},'approved':{},'asof':None})

    def context(self,use_frozen=True):
        state=self.state()
        asof=self.clock().astimezone(ISTANBUL)
        frozen=state.get('days',{}).get(asof.date().isoformat())
        if use_frozen and frozen:
            if all(not stamp(frozen[v].get('asof')) or stamp(frozen[v]['asof'])<=asof for v in ('active','shadow')):
                return dict(frozen,learning_enabled=frozen['learning_enabled'] and os.environ.get('LEARNING_ENABLED','false').lower()=='true')
        def available(version,prefix):
            variant=self.variant(state,version);at=stamp(variant.get('asof'))
            if at is None or at<=asof:return version
            candidates=[(stamp(v.get('asof')),k) for k,v in state['versions'].items() if k.startswith(prefix) and stamp(v.get('asof')) and stamp(v['asof'])<=asof]
            return max(candidates)[1] if candidates else 'BASE'
        active=available(state['active_version'],'ACTIVE');shadow=available(state['shadow_version'],'SHADOW')
        return {'active':self.variant(state,active),'shadow':self.variant(state,shadow),
            'active_version':active,'shadow_version':shadow,
            'learning_enabled':os.environ.get('LEARNING_ENABLED','false').lower()=='true'}

    def refresh(self,force=False):
        current=self.clock().astimezone(ISTANBUL);day=current.date().isoformat()
        with locked(self.path):
            state=self.state()
            if state.get('refresh_day')==day and not force:
                with locked(self.location.runtime_file('ai_ogrenme_gecmisi.json')):
                    records=load(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':[]})['kayitlar']
                self.publish(state,records)
                return self.context()
            with locked(self.location.runtime_file('ai_ogrenme_gecmisi.json')):
                records=load(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':[]})['kayitlar']
            rows=evidence(records,current)
            safe_context=self.context(use_frozen=False)
            previous=safe_context['shadow']
            if state.get('refresh_day')!=day:
                state['day_baseline_shadow']=previous
                state['day_baseline_active']=safe_context['active']
            baseline=state['day_baseline_shadow']
            report=criterion_report(rows,feature_fn=features)
            general,approved=adjustments(report,previous['general'],baseline['general'])
            shadow={'general':general,'approved':approved,'sectors':{},'regimes':{},'scope_approved':{'sectors':{},'regimes':{}},'asof':current.isoformat(),'ornek':len(rows)}
            for field,pool in (('sektor','sectors'),('piyasa_rejimi','regimes')):
                for name in sorted({r.get(field) for r in rows if r.get(field) not in (None,'','BILINMIYOR')}):
                    sub=criterion_report([r for r in rows if r.get(field)==name],feature_fn=features)
                    old=previous.get(pool,{}).get(name,BASE);base=baseline.get(pool,{}).get(name,BASE)
                    scoped,valid=adjustments(sub,old,base)
                    if valid:shadow[pool][name]=scoped;shadow['scope_approved'][pool][name]=valid
            def save_variant(variant,prefix):
                digest=hashlib.sha256(json.dumps(variant,sort_keys=True).encode()).hexdigest()[:16]
                version=prefix+'_'+day+'_'+digest;state['versions'][version]=variant;return version
            state['shadow_version']=save_variant(shadow,'SHADOW')
            frozen_today=state.get('days',{}).get(day)
            enabled=os.environ.get('LEARNING_ENABLED','false').lower()=='true' and (frozen_today is None or frozen_today['learning_enabled'])
            if enabled:
                target=self.variant(state,state['rollback_target']) if state.get('rollback_target') else shadow
                active_base=state['day_baseline_active']
                active={'general':bounded(target['general'],active_base['general']),'sectors':{},'regimes':{},'approved':target.get('approved',{}),'scope_approved':target.get('scope_approved',{}),'asof':current.isoformat(),'rollback_of':state.get('rollback_target')}
                for pool in ('sectors','regimes'):
                    for name,weights in target.get(pool,{}).items():active[pool][name]=bounded(weights,active_base.get(pool,{}).get(name,BASE))
                state['active_version']=save_variant(active,'ACTIVE')
            state.update(refresh_day=day,last_refresh=current.isoformat(),report=report)
            atomic_json(self.path,state)
            atomic_json(self.history,{'versions':state['versions'],'active_version':state['active_version'],'rollback_target':state.get('rollback_target')})
            self.publish(state,records)
            return self.context()

    def freeze_day(self):
        day=self.clock().astimezone(ISTANBUL).date().isoformat()
        with locked(self.path):
            state=self.state()
            if day in state['days']:
                existing=state['days'][day]
                if any(stamp(existing[v].get('asof')) and stamp(existing[v]['asof'])>self.clock() for v in ('active','shadow')):
                    raise ValueError('Gelecekte sabitlenmiş model geçmiş tahmine uygulanamaz')
                return existing
        self.refresh(force=True)
        with locked(self.path):
            state=self.state()
            if day not in state['days']:
                state['days'][day]={'active':self.variant(state,state['active_version']),'shadow':self.variant(state,state['shadow_version']),
                    'active_version':state['active_version'],'shadow_version':state['shadow_version'],
                    'learning_enabled':os.environ.get('LEARNING_ENABLED','false').lower()=='true'}
                atomic_json(self.path,state)
            return state['days'][day]

    def rollback(self,version):
        with locked(self.path):
            state=self.state()
            if version!='BASE' and version not in state['versions']:raise ValueError('Bilinmeyen kalibrasyon sürümü')
            state['rollback_target']=version;atomic_json(self.path,state)
        return {'rollback_target':version,'uygulama':'SONRAKI_GUN_GUNLUK_LIMIT_ICINDE','otomatik_aktivasyon':False}

    def publish(self,state,records):
        groups={}
        for record in records:
            if record.get('model') not in ('YARIN_BASELINE','YARIN_SHADOW'):continue
            groups.setdefault(record.get('snapshot_tarihi'),{}).setdefault(record['model'],[]).append(record)
        pairs=[]
        for day,models in sorted(groups.items()):
            base=models.get('YARIN_BASELINE',[]);shadow=models.get('YARIN_SHADOW',[])
            a,b=summarize(base),summarize(shadow)
            if base and shadow and a['degerlendirilen']==len(base) and b['degerlendirilen']==len(shadow):
                pairs.append({'tarih':day,'mevcut':a,'shadow':b})
        enough=state.get('report',{}).get('kriterler',{})
        sufficient={k:bool(v.get('yeterli_veri')) and min(v['varken']['ornek'],v['yokken']['ornek'])>=max(40,minimum_samples()) for k,v in enough.items()}
        applied=self.context()
        self.location.public.mkdir(parents=True,exist_ok=True)
        atomic_json(self.location.public/'kalibrasyon_durumu.json',{'learning_enabled':applied['learning_enabled'],
            'configured_learning_enabled':os.environ.get('LEARNING_ENABLED','false').lower()=='true',
            'active_version':state['active_version'],'shadow_version':state['shadow_version'],
            'applied_version':applied['active_version'] if applied['learning_enabled'] else 'BASE',
            'yeterli_kriter_sayisi':sum(sufficient.values()),
            'yetersiz_kriterler':[k for k,v in sufficient.items() if not v],
            'onerilen_degisiklikler':self.variant(state,state['shadow_version']).get('approved',{}),
            'son_hesaplama':state.get('last_refresh'),'shadow_karsilastirmasi':pairs[-20:],
            'mevcut_top10':robust([p['mevcut']['ortalama'] for p in pairs[-20:]]),
            'shadow_top10':robust([p['shadow']['ortalama'] for p in pairs[-20:]]),'otomatik_aktivasyon':False})
