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

# Prospective indicator evidence around the existing tomorrow ranking only.
TOP10_LEARNING_VERSION='TOP10_INDICATOR_V1'
TOP10_MAX_ADJUSTMENT=3.0
TOP10_FAMILY_CAP=.75
TOP10_COMBINATION_CAP=1.0
TOP10_HORIZON_WEIGHTS={1:.80,3:.15,5:.05}
TOP10_CONFIDENCE_SCALE={'INSUFFICIENT':0.,'LOW':.25,'MEDIUM':.60,'HIGH':1.}
TOP10_FALLBACK_SCALE=.5
TOP10_WIN_EDGE_SCALE=.20
TOP10_RETURN_EDGE_SCALE=2.0
TOP10_EDGE_WEIGHTS={'win':.4,'mean':.3,'median':.3}
TOP10_MAX_CACHE_AGE_DAYS=7
TOP10_FAMILIES={
    'momentum':('RSI','MACD_SIGN','MACD_SIGNAL','HIST_SIGN','HIST_TREND','MOMENTUM'),
    'trend':('PRICE_SMA20','PRICE_SMA50','SMA_TREND','EMA_TREND'),
    'volume':('VOLUME','OBV'), 'price_position':('VWAP','BOLLINGER','BOLL_BREAKOUT'),
    'volatility':('ATR','BOLL_SQUEEZE'), 'confirmation':('CONFIRMATIONS','CONFIRMATION_COUNT')}
TOP10_COMBO_FAMILIES={
    'COMBO_RSI_MACD':('momentum',), 'COMBO_MACD_VOLUME':('momentum','volume'),
    'COMBO_RSI_VOLUME':('momentum','volume'), 'COMBO_VWAP_OBV':('price_position','volume'),
    'COMBO_TREND_VOLUME':('trend','volume'), 'COMBO_RSI_MACD_VOLUME':('momentum','volume')}


def top10_learning_enabled():
    return os.environ.get('TOP10_LEARNING_ENABLED','true').lower().strip() in ('1','true','yes','on')


def _learning_clip(value,limit):return max(-limit,min(limit,value))


def top10_learning_context(location,current):
    """One cached lookup per batch; failures do not affect the base ranker."""
    from sinyal_performansi import read_report,VERSION,RELIABILITY
    try:
        if not top10_learning_enabled():return {'status':'DISABLED'}
        report=read_report(location);at=stamp(report.get('updated_at'))
        if report.get('version')!=VERSION or report.get('analysis_only') is not True or report.get('reliability_thresholds')!=RELIABILITY:
            return {'status':'NO_VERIFIED_REPORT'}
        if not at or at>current:return {'status':'FUTURE_OR_MISSING_REPORT'}
        if (current-at).total_seconds()>TOP10_MAX_CACHE_AGE_DAYS*86400:return {'status':'STALE_REPORT'}
        indicators=report['indicator_analysis']
        if stamp(indicators.get('updated_at'))!=at or indicators.get('analysis_only') is not True:return {'status':'INCONSISTENT_REPORT'}
        index={}
        for row in indicators['rows']:
            if row['period']!='ALL' or row['horizon'] not in TOP10_HORIZON_WEIGHTS:continue
            key=(row['indicator'],row['condition'],row['signal_type'],row['horizon'])
            if key in index:raise ValueError('Duplicate evidence')
            index[key]=row
        overall=report['periods'].get('ALL',{})
        return {'status':'READY','asof':at.isoformat(),'index':index,
                'baselines':{'YARIN_TOP10':overall.get('signals',{}).get('YARIN_TOP10',{}),
                             'ALL':overall.get('overall',{}).get('ALL',{})}}
    except Exception as error:
        print('[TOP10_LEARNING] cache kullanılamadı:',type(error).__name__)
        return {'status':'CACHE_ERROR'}


def _verified_stat(row):
    """Derived cache rows must agree with their verified sample counters."""
    if not isinstance(row,dict):return False
    count=number(row.get('sample_size'));completed=number(row.get('completed'))
    values=[number(row.get(k)) for k in ('positive','negative','neutral')]
    from sinyal_performansi import RELIABILITY
    if row.get('legacy_unverified') or row.get('unverified'):return False
    if count is None or count<RELIABILITY['LOW'] or count!=int(count) or completed!=count or any(v is None or v<0 or v!=int(v) for v in values):return False
    if sum(values)!=count:return False
    rate=number(row.get('success_rate'))
    return rate is not None and 0<=rate<=1 and abs(rate-values[0]/count)<.0001 and all(number(row.get(k)) is not None for k in ('mean_return','median_return'))


def _indicator_edge(row,baseline):
    from sinyal_performansi import reliability,RELIABILITY
    count=min(row['sample_size'],baseline['sample_size'])
    confidence=reliability(count);factor=TOP10_CONFIDENCE_SCALE[confidence]
    win=_learning_clip((row['success_rate']-baseline['success_rate'])/TOP10_WIN_EDGE_SCALE,1.)
    average=_learning_clip((row['mean_return']-baseline['mean_return'])/TOP10_RETURN_EDGE_SCALE,1.)
    middle=_learning_clip((row['median_return']-baseline['median_return'])/TOP10_RETURN_EDGE_SCALE,1.)
    edge=TOP10_EDGE_WEIGHTS['win']*win+TOP10_EDGE_WEIGHTS['mean']*average+TOP10_EDGE_WEIGHTS['median']*middle
    risk_scale=1.
    mae=number(row.get('median_mae'),number(row.get('mean_mae')));mfe=number(row.get('median_mfe'),number(row.get('mean_mfe')))
    if edge>0 and mae is not None and mfe is not None and number(row.get('mae_samples'),0)>=RELIABILITY['LOW'] and number(row.get('mfe_samples'),0)>=RELIABILITY['LOW']:
        risk_scale=max(0,min(1.,max(0,mfe)/max(.5,abs(mae))))
    return edge*factor*risk_scale,confidence,factor,risk_scale


def top10_learning_adjustment(row,model,current):
    """Use only completed historical evidence and currently known candidate inputs."""
    from sinyal_performansi import indicator_conditions,frozen_feature_issue
    if not isinstance(model,dict):model={'status':'MALFORMED_CONTEXT'}
    empty={'learning_adjustment':0.,'learning_version':TOP10_LEARNING_VERSION,
           'learning_uncapped_adjustment':0.,'learning_total_cap':TOP10_MAX_ADJUSTMENT,
           'learning_reasons':[],'learning_confidence_summary':{},'learning_status':model.get('status','UNAVAILABLE')}
    try:
        if not top10_learning_enabled():return dict(empty,learning_status='DISABLED')
        if model.get('status')!='READY':return empty
        asof=stamp(model.get('asof'))
        if not asof or asof>current:return dict(empty,learning_status='FUTURE_OR_MISSING_REPORT')
        if (current-asof).total_seconds()>TOP10_MAX_CACHE_AGE_DAYS*86400:
            return dict(empty,learning_status='STALE_REPORT')
        feature_error=frozen_feature_issue(row,current)
        if feature_error:return dict(empty,learning_status=feature_error)
        if number(row.get('fiyat'),0)<=0:return dict(empty,learning_status='MISSING_PRICE')
        conditions=indicator_conditions(row);parts=[]
        for indicator,condition in conditions.items():
            if indicator not in {i for values in TOP10_FAMILIES.values() for i in values}|set(TOP10_COMBO_FAMILIES):continue
            details=[];delta=0.;main=False
            for horizon,weight in TOP10_HORIZON_WEIGHTS.items():
                selected=None
                for source in ('YARIN_TOP10','ALL'):
                    entry=model['index'].get((indicator,condition,source,horizon))
                    baseline=model['baselines'][source].get(str(horizon))
                    if not _verified_stat(entry) or not _verified_stat(baseline):continue
                    if entry['sample_size']>baseline['sample_size']:continue
                    selected=(entry,baseline,source);break
                if not selected:continue
                entry,baseline,source=selected
                if horizon==1:main=True
                edge,confidence,factor,risk_scale=_indicator_edge(entry,baseline)
                fallback=TOP10_FALLBACK_SCALE if source=='ALL' else 1.
                contribution=edge*weight*fallback
                delta+=contribution
                details.append({'horizon':horizon,'weight':weight,'source':source,'fallback_scale':fallback,
                    'sample_count':entry['sample_size'],'baseline_count':baseline['sample_size'],
                    'confidence':confidence,'confidence_scale':factor,'risk_scale':risk_scale,
                    'win_rate':entry['success_rate'],'baseline_win_rate':baseline['success_rate'],
                    'mean_return':entry['mean_return'],'baseline_mean_return':baseline['mean_return'],
                    'median_return':entry['median_return'],'baseline_median_return':baseline['median_return'],
                    'weighted_edge':round(contribution,6)})
            if not main:continue  # Auxiliary horizons cannot enable a bonus alone.
            family=next((f for f,values in TOP10_FAMILIES.items() if indicator in values),'combination')
            parts.append({'indicator':indicator,'condition':condition,'family':family,'evidence':details,'edge':delta})
        families={}
        for family in TOP10_FAMILIES:
            subset=[p for p in parts if p['family']==family]
            if not subset:continue
            # Correlated indicators share one averaged family budget, never sum.
            families[family]=_learning_clip(sum(p['edge'] for p in subset)/len(subset)*TOP10_FAMILY_CAP,TOP10_FAMILY_CAP)
            for part in subset:part['contribution']=families[family]/len(subset)
        def main_strength(part):
            return next((e['confidence_scale']*e['fallback_scale'] for e in part['evidence'] if e['horizon']==1),0.)
        combos=[p for p in parts if p['family']=='combination' and p['edge']!=0
                and main_strength(p)>=max((main_strength(single) for single in parts
                    if single['family'] in TOP10_COMBO_FAMILIES[p['indicator']]),default=0.)]
        combination=0.
        if combos:
            chosen=max(combos,key=lambda p:(abs(p['edge']),p['indicator']))
            combination=_learning_clip(chosen['edge']*TOP10_COMBINATION_CAP,TOP10_COMBINATION_CAP)
            # Replace related families instead of stacking their full contributions.
            replaced=TOP10_COMBO_FAMILIES[chosen['indicator']]
            for family in replaced:families.pop(family,None)
            for part in parts:
                if part['family'] in replaced:part.update(contribution=0.,suppressed_by=chosen['indicator'])
                elif part['family']=='combination':part['contribution']=combination if part is chosen else 0.
        uncapped=sum(families.values())+combination
        adjustment=round(_learning_clip(uncapped,TOP10_MAX_ADJUSTMENT),6)
        global_scale=abs(adjustment/uncapped) if uncapped else 1.
        for part in parts:
            part['contribution']=part.get('contribution',0)*global_scale
            part.pop('edge');part['contribution']=round(part.get('contribution',0),6)
        confidence={}
        for part in parts:
            if part.get('contribution')==0:continue
            for entry in part['evidence']:confidence[entry['confidence']]=confidence.get(entry['confidence'],0)+1
        return dict(empty,learning_adjustment=adjustment,learning_reasons=parts,
                    learning_uncapped_adjustment=round(uncapped,6),learning_total_cap=TOP10_MAX_ADJUSTMENT,
                    learning_confidence_summary=confidence,learning_status='APPLIED' if adjustment else 'NO_EDGE')
    except Exception as error:
        print('[TOP10_LEARNING] katkı hesaplanamadı:',type(error).__name__)
        return dict(empty,learning_status='CALCULATION_ERROR')


def rank_with_learning(base_order,model,current):
    """Preserve stable base tie order and eligibility; rank the same candidates."""
    try:
        for rank,(base,row) in enumerate(base_order,1):
            row.update(top10_learning_adjustment(row,model,current))
            delta=row['learning_adjustment']
            row.update(base_score=base,base_rank=rank,
                final_ranking_score=max(0,min(100,base+delta)) if delta else base)
            row['applied_learning_adjustment']=round(row['final_ranking_score']-base,6)
        ranked=sorted(base_order,key=lambda pair:pair[1]['final_ranking_score'],reverse=True)
        for rank,(_,row) in enumerate(ranked,1):row.update(learned_rank=rank,rank_change=row['base_rank']-rank)
        return [(row['final_ranking_score'],row) for _,row in ranked]
    except Exception as error:
        print('[TOP10_LEARNING] sıralama düzeltmesi uygulanamadı:',type(error).__name__)
        for rank,(base,row) in enumerate(base_order,1):
            row.update(base_score=base,base_rank=rank,learned_rank=rank,rank_change=0,
                final_ranking_score=base,learning_adjustment=0.,applied_learning_adjustment=0.,
                learning_reasons=[],learning_confidence_summary={},learning_status='RANKING_ERROR',learning_version=TOP10_LEARNING_VERSION)
        return base_order
