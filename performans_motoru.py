"""Frozen signal outcomes and descriptive calibration, sharing the existing history."""
from datetime import datetime, timedelta, time
from pathlib import Path
from statistics import mean, median
import hashlib
import json
import math
import os

from ai_karar_motoru import (HORIZONS, ISTANBUL, DEFAULT_WEIGHTS, LIMITS, number,
                             stamp, load, locked, normalize_weights)
from kullanici_kayitlari import atomic_json
from veri_yollari import paths


def minimum_samples():
    value=int(os.environ.get('MIN_LEARNING_SAMPLES','40'))
    if not 30<=value<=10000:raise ValueError('MIN_LEARNING_SAMPLES: 30–10000')
    return value


def business_day(day, holiday=None):
    return day.weekday()<5 and not (holiday and holiday(day))


def sessions_after(day, count, holiday=None):
    result=[]
    while len(result)<count:
        day+=timedelta(days=1)
        if business_day(day,holiday):result.append(day)
    return result


def session_closed(day, current):
    return day<current.date() or (day==current.date() and current.time().replace(tzinfo=None)>=time(18,15))


def normalize_bars(bars, current, holiday=None):
    """Reject inconsistent duplicates/OHLC; never let a missing session slide a horizon."""
    result={};invalid=set()
    for row in bars:
        date=stamp(row.get('timestamp') or row.get('date'))
        if not date or not business_day(date.date(),holiday) or not session_closed(date.date(),current) or row.get('complete') is False:continue
        day=date.date();bar={k:number(row.get(k)) for k in ('open','high','low','close')}
        if any(v is not None and v<=0 for v in bar.values()) or bar['close'] is None:
            invalid.add(day);continue
        if bar['high'] is not None and bar['low'] is not None:
            if bar['high']<bar['low'] or any(v is not None and not bar['low']<=v<=bar['high'] for k,v in bar.items() if k in ('open','close')):
                invalid.add(day);continue
        if day in result and result[day]!=bar:invalid.add(day)
        result[day]=bar
    for day in invalid:result.pop(day,None)
    return result


def outcome(record, bars, horizon, current, holiday=None, require_ohlc=True):
    start=stamp(record.get('zaman') or record.get('tarih'));base=number(record.get('referans_fiyat'),number(record.get('fiyat'),0))
    empty={'durum':'VERI_YETERSIZ','degerlendirme_tamamlandi':False,'observed_at':current.isoformat()}
    if not start or base<=0:return dict(empty,neden='REFERANS_EKSIK')
    days=sessions_after(start.date(),horizon,holiday)
    if not session_closed(days[-1],current):return None
    data=normalize_bars(bars,current,holiday)
    if any(day not in data for day in days):return dict(empty,neden='ISLEM_GUNU_EKSIK',eksik_gunler=[d.isoformat() for d in days if d not in data])
    window=[data[day] for day in days]
    full=all(all(bar[k] is not None for k in ('open','high','low','close')) for bar in window)
    if require_ohlc and not full:return dict(empty,neden='OHLC_EKSIK')
    target=number(record.get('hedef'));stop=number(record.get('stop'))
    short=record.get('karar') in ('SAT','GUCLU_SAT') and not str(record.get('model','')).startswith('YARIN')
    if short and record.get('model')=='GUN_ICI':
        target=number(record.get('sat_hedef'),base-abs(target-base) if target is not None else None)
        stop=number(record.get('sat_stop'),base+abs(stop-base) if stop is not None else None)
    valid_levels=target is not None and stop is not None and ((target<base<stop) if short else (stop<base<target))
    target_hit=stop_hit=None;first=None;first_target=first_stop=None
    if full and valid_levels:
        target_hit=stop_hit=False
        for i,bar in enumerate(window):
            th=bar['low']<=target if short else bar['high']>=target
            sh=bar['high']>=stop if short else bar['low']<=stop
            if th and first_target is None:first_target=i
            if sh and first_stop is None:first_stop=i
            target_hit|=th;stop_hit|=sh
            if first is None and (th or sh):
                opened_target=bar['open']<=target if short else bar['open']>=target
                opened_stop=bar['open']>=stop if short else bar['open']<=stop
                first='HEDEF' if opened_target else 'STOP' if opened_stop else 'BELIRSIZ' if th and sh else 'HEDEF' if th else 'STOP'
    close=window[-1]['close'];change=(close/base-1)*100
    max_price=max(b['high'] for b in window) if full else None
    min_price=min(b['low'] for b in window) if full else None
    directional=-change if short else change
    risk=abs(base-stop)/base*100 if valid_levels else None
    reward=abs(target-base)/base*100 if valid_levels else None
    drawdown=(min_price/base-1)*100 if min_price is not None else None
    potential=(max_price/base-1)*100 if max_price is not None else None
    if first=='STOP':status='STOP'
    elif first=='BELIRSIZ' or not full or not valid_levels:status='VERI_YETERSIZ'
    elif first=='HEDEF':status='BASARILI'
    elif directional>=risk and (abs(min(0,drawdown or 0)) if not short else max(0,potential or 0))<risk:status='BASARILI'
    elif directional>0 and directional>=risk*.5:status='KISMEN_BASARILI'
    else:status='BASARISIZ'
    return {'durum':status,'degerlendirme_tamamlandi':True,'baslangic_fiyati':base,'fiyat':close,
        'kapanis_fiyati':close,'getiri_yuzde':round(change,4),'yon_getirisi':round(directional,4),
        'maksimum_yukselis':round(potential,4) if potential is not None else None,
        'maksimum_dusus':round(drawdown,4) if drawdown is not None else None,
        'hedefe_ulasti':target_hit,'stop_oldu':stop_hit,'ilk_temas':first or 'YOK',
        'hedef_once':True if first=='HEDEF' else False if first=='STOP' else None,
        'stop_once':True if first=='STOP' else False if first=='HEDEF' else None,
        'en_iyi_fiyat':min_price if short else max_price,'en_kotu_fiyat':max_price if short else min_price,
        'risk_yuzde':risk,'risk_getiri':reward/risk if risk else None,
        'ertesi_gun_acilis':window[0]['open'],'ertesi_gun_kapanis':window[0]['close'],
        'ertesi_gun_yuksek':window[0]['high'],'ertesi_gun_dusuk':window[0]['low'],
        'tarih':days[-1].isoformat(),'observed_at':current.isoformat(),
        'kalite_uyarilari':(['TEMAS_SIRASI_BELIRSIZ'] if first=='BELIRSIZ' else [])+([] if full else ['OHLC_EKSIK'])+([] if valid_levels else ['SEVIYELER_EKSIK_VEYA_GECERSIZ'])}


def criteria(record):
    raw=dict(record.get('kriterler') or record.get('girdiler') or {})
    raw.update({k:v for k,v in record.items() if k not in raw})
    def threshold(key,test):
        val=number(raw.get(key));return test(val) if val is not None else None
    def pair(a,b,test):
        x,y=number(raw.get(a)),number(raw.get(b));return test(x,y) if x is not None and y is not None else None
    contribution=record.get('katkilar') or {}
    def effect(name,key):
        value=number(contribution.get(name),number(raw.get(key)))
        return abs(value)>.01 if value is not None else None
    news=record.get('haber_katkilari') or []
    kap=None
    if news:kap=any('KAP' in str(n.get('kaynak_etiketi') or n.get('kaynaklar')) for n in news)
    elif record.get('model')=='HABER':kap='KAP' in str(record.get('kaynak'))
    regime=record.get('piyasa_rejimi')
    return {'RSI':threshold('rsi',lambda v:30<=v<=65),'MACD':pair('macd','signal',lambda a,b:a>b) if raw.get('signal') is not None else threshold('hist',lambda v:v>0),
        'SMA_TREND':pair('sma20','sma50',lambda a,b:a>b),'HACIM':threshold('hacim_orani',lambda v:v>=150),
        'VWAP':raw.get('vwap20_durum')=='USTUNDE' if raw.get('vwap20_durum') in ('USTUNDE','ALTINDA') else None,
        'OBV':raw.get('obv_durum') in ('YUKSELEN','POZITIF') if raw.get('obv_durum') in ('YUKSELEN','DUSEN','POZITIF','NEGATIF','YATAY') else None,
        'BOLLINGER':raw.get('boll_durum')=='BANT_ICINDE' if raw.get('boll_durum') else None,
        'MOMENTUM':threshold('momentum15',lambda v:v>0),
        'DESTEK_DIRENC':pair('destek','direnc',lambda a,b:a<b),
        'RISK_GETIRI':threshold('risk_getiri',lambda v:v>=1.5),
        'HABER':effect('haber','haber_puani'),'KAP':kap,'MAKRO':effect('makro','makro_puani'),
        'SEKTOR':effect('sektor','sektor_puani'),'FIYAT_TEYIDI':effect('fiyat_teyidi','haber_fiyat_teyidi'),
        'PIYASA_REJIMI':regime in ('POZITIF','YUKSELIS','GUCLU_YUKSELIS') if regime in ('POZITIF','NEGATIF','YATAY','YUKSELIS','GUCLU_YUKSELIS','DUSUS','GUCLU_DUSUS') else None,
        'GECMIS_BASARI':effect('gecmis_basari','gecmis_basari')}


def robust(values):
    values=sorted(values)
    if not values:return {'ornek':0,'ortalama':None,'medyan':None,'trimmed_ortalama':None}
    cut=int(len(values)*.1);trimmed=values[cut:-cut] if cut else values
    return {'ornek':len(values),'ortalama':mean(values),'medyan':median(values),'trimmed_ortalama':mean(trimmed)}


def wilson(successes,count):
    if not count:return [None,None]
    p=successes/count;z=1.96;den=1+z*z/count
    centre=(p+z*z/(2*count))/den;radius=z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/den
    return [max(0,centre-radius),min(1,centre+radius)]


def usable(record,horizon=1):
    result=record.get('sonuc_'+str(horizon)+'g')
    return isinstance(result,dict) and result.get('degerlendirme_tamamlandi',True) and number(result.get('getiri_yuzde')) is not None


def correlation(xs,ys):
    if len(xs)<3:return None
    xmean,ymean=mean(xs),mean(ys)
    den=math.sqrt(sum((x-xmean)**2 for x in xs)*sum((y-ymean)**2 for y in ys))
    return sum((x-xmean)*(y-ymean) for x,y in zip(xs,ys))/den if den else None


def summarize(records,horizon=1):
    rows=[r for r in records if usable(r,horizon)];key='sonuc_'+str(horizon)+'g'
    returns=[r[key]['getiri_yuzde'] for r in rows]
    labelled=[r for r in rows if r[key].get('durum') in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP')]
    successful=sum(r[key]['durum']=='BASARILI' for r in labelled)
    buys=lambda r:r.get('model')=='YARIN_TOP10' or r.get('karar') in ('AL','GUCLU_AL','GUCLU_AL_ADAYI')
    fp=sum(buys(r) and r[key]['getiri_yuzde']<=0 for r in rows);tn=sum(not buys(r) and r[key]['getiri_yuzde']<=0 for r in rows)
    fn=sum(not buys(r) and r[key]['getiri_yuzde']>0 for r in rows);tp=sum(buys(r) and r[key]['getiri_yuzde']>0 for r in rows)
    return {**robust(returns),'beklenen_kayit':len(records),'degerlendirilen':len(rows),'basari_etiketi_ornek':len(labelled),
        'basari_orani':successful/len(labelled) if labelled else None,'basari_guven_araligi':wilson(successful,len(labelled)),
        'pozitif':sum(v>0 for v in returns),'negatif':sum(v<0 for v in returns),'notr':sum(v==0 for v in returns),
        'hedef':sum(r[key].get('hedefe_ulasti') is True for r in rows),'stop':sum(r[key].get('stop_oldu') is True for r in rows),
        'yanlis_pozitif_orani':fp/(fp+tn) if fp+tn else None,'yanlis_negatif_orani':fn/(fn+tp) if fn+tp else None,
        'confusion':{'TP':tp,'FP':fp,'TN':tn,'FN':fn},'durumlar':{s:sum(r[key].get('durum','VERI_YETERSIZ')==s for r in rows) for s in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP','VERI_YETERSIZ')}}


def daily_report(records):
    ordered=sorted(records,key=lambda r:r.get('tahmin_sirasi',999));result=summarize(records)
    completed=[r for r in ordered if usable(r)]
    pairs=[(number(r.get('tahmin_skoru')),r['sonuc_1g']['getiri_yuzde']) for r in completed if number(r.get('tahmin_skoru')) is not None]
    ranks=[r for r in completed if number(r.get('tahmin_sirasi')) is not None]
    result.update(top3=summarize(ordered[:3]),top5=summarize(ordered[:5]),top10=summarize(ordered[:10]),
        skor_performans_korelasyonu=correlation([a for a,b in pairs],[b for a,b in pairs]),
        sira_performans_korelasyonu=correlation([r['tahmin_sirasi'] for r in ranks],[r['sonuc_1g']['getiri_yuzde'] for r in ranks]),
        en_iyi=max(({'sembol':r['sembol'],'getiri':r['sonuc_1g']['getiri_yuzde']} for r in completed),key=lambda r:r['getiri'],default=None),
        en_kotu=min(({'sembol':r['sembol'],'getiri':r['sonuc_1g']['getiri_yuzde']} for r in completed),key=lambda r:r['getiri'],default=None),
        tamamlandi=len(completed)==len(records) and bool(records))
    scored=sorted(completed,key=lambda r:number(r.get('tahmin_skoru'),-1),reverse=True)
    mid=len(scored)//2
    result['yuksek_skor_grubu']=summarize(scored[:mid]);result['dusuk_skor_grubu']=summarize(scored[mid:])
    result['sonuc_tarihi']=next((r['sonuc_1g'].get('tarih') for r in completed),None)
    result['tahmin_tarihi']=records[0].get('snapshot_tarihi') if records else None
    return result


def criterion_report(records,horizon=1,minimum=None,feature_fn=None):
    minimum=minimum or minimum_samples();rows=[r for r in records if usable(r,horizon) and r.get('egitim_durumu')!='REFERANS' and r['sonuc_'+str(horizon)+'g'].get('durum') in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP')]
    feature_fn=feature_fn or criteria
    keys=list(feature_fn({}));report={};features=[(r,feature_fn(r)) for r in rows]
    for key in keys:
        yes=[r for r,f in features if f[key] is True];no=[r for r,f in features if f[key] is False]
        yp,np=summarize(yes,horizon),summarize(no,horizon)
        days_y={r['zaman'][:10] for r in yes};days_n={r['zaman'][:10] for r in no}
        enough=len(yes)>=minimum and len(no)>=minimum and len(days_y)>=5 and len(days_n)>=5
        delta=yp['basari_orani']-np['basari_orani'] if yp['basari_orani'] is not None and np['basari_orani'] is not None else None
        interval=[yp['basari_guven_araligi'][0]-np['basari_guven_araligi'][1],yp['basari_guven_araligi'][1]-np['basari_guven_araligi'][0]] if yes and no else [None,None]
        direction='ARTIR' if enough and interval[0]>0 and yp['medyan']>np['medyan']+.25 else 'AZALT' if enough and interval[1]<0 and yp['medyan']<np['medyan']-.25 else 'SABIT'
        report[key]={'varken':yp,'yokken':np,'bilinmeyen':len(rows)-len(yes)-len(no),'basari_farki':delta,
            'fark_guven_araligi':interval,'minimum_her_grup':minimum,'yeterli_veri':enough,'bagimsiz_gunler':[len(days_y),len(days_n)],
            'guven':'YETERLI' if enough else 'DUSUK','onerilen_agirlik_yonu':direction}
    # Observable association only; not a causal attribution.
    combinations={}
    for name,condition in {'RSI_DUSUK_MACD_NEGATIF':lambda r:number(r.get('kriterler',{}).get('rsi'),50)<30 and criteria(r)['MACD'] is False,
                           'MAKRO_NEGATIF':lambda r:number(r.get('makro_etkisi'),0)<0}.items():
        combinations[name]=summarize([r for r in rows if condition(r)],horizon)
    return {'kriterler':report,'kombinasyonlar':combinations,'nedensellik_iddiasi':False}


def weight_proposals(report,current):
    groups={'RSI':'teknik','MACD':'teknik','SMA_TREND':'teknik','HACIM':'teknik','VWAP':'teknik','OBV':'teknik',
        'BOLLINGER':'teknik','MOMENTUM':'teknik','DESTEK_DIRENC':'teknik','RISK_GETIRI':'teknik','HABER':'haber','KAP':'haber',
        'MAKRO':'makro','SEKTOR':'sektor','FIYAT_TEYIDI':'fiyat_teyidi','PIYASA_REJIMI':'piyasa_rejimi','GECMIS_BASARI':'gecmis_basari'}
    raw=dict(current);reasons=[];votes={k:[] for k in current}
    for key,value in report['kriterler'].items():
        direction=value['onerilen_agirlik_yonu']
        if direction!='SABIT':votes[groups[key]].append(1 if direction=='ARTIR' else -1);reasons.append({'kriter':key,'yon':direction,'ornek':[value['varken']['ornek'],value['yokken']['ornek']]})
    if reasons:
        for key,items in votes.items():
            if items:raw[key]+=.0025*mean(items)
        bounds={k:(max(LIMITS[k][0],current[k]-.005),min(LIMITS[k][1],current[k]+.005)) for k in current}
        proposed=normalize_weights(raw,bounds)
    else:proposed=dict(current)
    return {'mevcut':current,'onerilen_agirliklar':proposed,'nedenler':reasons,'otomatik_uygulandi':False,
            'learning_enabled':os.environ.get('LEARNING_ENABLED','false').lower()=='true','minimum_ornek':minimum_samples()}


def provider_history(stock):
    # Same provider/history used by the technical engine; no independent data layer.
    import bist_bot
    frame=bist_bot.bp.Ticker(stock).history(period='1y')
    if frame is None or frame.empty:return []
    rows=[]
    for date,row in frame.iterrows():
        rows.append({'timestamp':str(date),**{key:number(row.get(column)) for key,column in
            (('open','Open'),('high','High'),('low','Low'),('close','Close'))}})
    return rows


class PerformansMotoru:
    def __init__(self,location=None,clock=None,history_provider=None,holiday=None,batch_size=None):
        self.location=location or paths();self.clock=clock or (lambda:datetime.now(ISTANBUL))
        self.provider=history_provider or provider_history;self.holiday=holiday
        self.batch_size=int(batch_size or os.environ.get('PERFORMANCE_BATCH_SIZE','10'))
        if not 1<=self.batch_size<=25:raise ValueError('PERFORMANCE_BATCH_SIZE: 1–25')
        self.history_path=self.location.runtime_file('ai_ogrenme_gecmisi.json')
        self.state_path=self.location.runtime/'performans_durum.json'
        self.cache_path=self.location.runtime/'performans_fiyat_cache.json'
        self.result_path=self.location.runtime/'yarin_top10_sonuclar.json'

    def snapshot_records(self,state):
        records=[]
        for path in sorted(self.location.archives.glob('????-??-??.json')):
            name=path.name
            if name in state.get('arsivler',{}):continue
            raw=path.read_bytes();snapshot=json.loads(raw);day=snapshot.get('analiz_tarihi',path.stem)
            snapshot_id=day+'_'+hashlib.sha256(raw).hexdigest()[:16]
            lists=[('YARIN_TOP10',snapshot.get('top10',[])),('YARIN_BASELINE',snapshot.get('ham_top10',[])),('YARIN_SHADOW',snapshot.get('shadow_top10',[]))]
            entries=[(model,rank,row) for model,rows in lists for rank,row in enumerate(rows,1)]
            for model,rank,row in entries:
                prediction=row.get('tahmin') or {}
                at=prediction.get('tahmin_zamani') or snapshot.get('tahmin_zamani') or day+'T18:15:00+03:00'
                stock=row.get('sembol') or prediction.get('sembol')
                if not stock:continue
                prefix='YARIN' if model=='YARIN_TOP10' else model
                record={'kayit_id':prefix+'_'+snapshot_id+'_'+stock,'model':model,'sembol':stock,'zaman':at,
                    'snapshot_id':snapshot_id,'snapshot_tarihi':day,'kaynak':'IMMUTABLE_YARIN_SNAPSHOT',
                    'tahmin_sirasi':rank,'tahmin_skoru':prediction.get('skor',row.get('yarin_top10_puani')),
                    'fiyat':prediction.get('fiyat',row.get('fiyat')),'ai_score':prediction.get('skor',row.get('yarin_top10_puani')),
                    'confidence':row.get('guven_skoru'),'karar':prediction.get('karar',row.get('karar','AL')),
                    'alim_alt':prediction.get('alim_alt',row.get('yarin_alim_alt')),'alim_ust':prediction.get('alim_ust',row.get('yarin_alim_ust')),
                    'hedef':prediction.get('hedef',row.get('yarin_kar_al')),'stop':prediction.get('stop',row.get('yarin_stop')),
                    'kriterler':dict(row,**(prediction.get('kriter_ozeti') or {})),
                    'teknik_skor':row.get('teknik_puan_yarin',row.get('al_puani')),'haber_etkisi':prediction.get('haber_puani',row.get('haber_puani')),
                    'makro_etkisi':prediction.get('makro_puani',row.get('makro_puani')),'sektor':row.get('makro_sektor','BILINMIYOR'),
                    'piyasa_rejimi':row.get('piyasa_rejimi','BILINMIYOR'),'katkilar':row.get('katkilar',{}),'egitim_durumu':'EGITIM',
                    'teknik_gostergeler':prediction.get('teknik_gostergeler',row.get('teknik_gostergeler')),
                    'nihai_karar':prediction.get('nihai_karar',row.get('nihai_karar')),
                    'teknik_katkilar':prediction.get('teknik_katkilar',row.get('teknik_katkilar')),
                    'teknik_shadow_puan':prediction.get('teknik_shadow_puan',row.get('teknik_shadow_puan')),
                    'piyasa_baglami':prediction.get('piyasa_baglami',row.get('piyasa_baglami')),
                    'ham_puan':prediction.get('ham_puan',row.get('ham_puan')),
                    'kalibrasyon_duzeltmesi':prediction.get('kalibrasyon_duzeltmesi',row.get('kalibrasyon_duzeltmesi')),
                    'final_puan':prediction.get('final_puan',row.get('final_puan')),
                    'calibration_version':prediction.get('calibration_version',row.get('calibration_version')),
                    'shadow_version':prediction.get('shadow_version',row.get('shadow_version')),
                    **{'sonuc_'+str(h)+'g':None for h in HORIZONS}}
                records.append(record)
            state.setdefault('arsivler',{})[name]=snapshot_id
        return records

    def event_records(self,history_ids):
        generated=[]
        baseline=load(self.location.runtime/'ai_fiyat_teyit.json',{})
        news=load(self.location.runtime/'haber_dedup.json',{'haberler':[]})
        for event in news.get('haberler',[]):
            canonical_id=event.get('canonical_id');stock=event.get('sembol')
            if not canonical_id or not stock:continue
            sid='HABER_'+canonical_id+'_'+stock
            if sid in history_ids:continue
            analysis=event.get('analiz',{});observed=baseline.get(stock+':'+canonical_id,{})
            price=number(analysis.get('ilk_fiyat'),observed.get('price'))
            at=event.get('ilk_gorulme') if number(analysis.get('ilk_fiyat')) else observed.get('timestamp',event.get('ilk_gorulme'))
            generated.append({'kayit_id':sid,'model':'HABER','sembol':stock,'zaman':at,'fiyat':price,'canonical_id':canonical_id,
                'kaynak':event.get('kaynak_etiketi'),'karar':'AL' if number(analysis.get('etki_puani'),0)>0 else 'SAT' if number(analysis.get('etki_puani'),0)<0 else 'IZLE',
                'confidence':analysis.get('guven'),'ai_score':None,'haber_etkisi':analysis.get('etki_puani'),'katkilar':{'haber':number(analysis.get('etki_puani'),0)},
                'kriterler':{},'egitim_durumu':'EGITIM' if price else 'REFERANS','referans_kaynagi':'HABER_FIYATI' if number(analysis.get('ilk_fiyat')) else 'ILK_AI_GOZLEMI',
                'haber_zamani':event.get('ilk_gorulme'),**{'sonuc_'+str(h)+'g':None for h in (1,3,5)}})
        macro=load(self.location.runtime_file('makro_ai_gecmisi.json'),{'olaylar':[]})
        for event in macro.get('olaylar',[]) if isinstance(macro,dict) else []:
            for stock,row in event.get('hisseler',{}).items():
                sid='MAKRO_'+event['event_id']+'_'+stock
                if sid in history_ids:continue
                generated.append({'kayit_id':sid,'model':'MAKRO','sembol':stock,'zaman':event['updated_at'],'fiyat':row.get('referans_fiyat'),
                    'kaynak':'MAKRO','karar':'AL' if number(row.get('makro_puani'),0)>0 else 'SAT' if number(row.get('makro_puani'),0)<0 else 'IZLE','confidence':None,'ai_score':None,
                    'makro_etkisi':row.get('makro_puani'),'katkilar':{'makro':number(row.get('makro_puani'),0)},'event_id':event['event_id'],
                    'sektor':row.get('sektor'),'piyasa_rejimi':'BILINMIYOR','kriterler':{},'egitim_durumu':'EGITIM' if row.get('referans_fiyat') else 'REFERANS',
                    'referans_kaynagi':'SON_CANLI_FIYAT','referans_fiyat_zamani':row.get('referans_fiyat_zamani'),
                    **{'sonuc_'+str(h)+'g':None for h in (1,3,5)}})
        return generated

    @staticmethod
    def enrich(record):
        if not record.get('kayit_id'):
            record['kayit_id']=record.get('id') or 'LEGACY_'+hashlib.sha256(json.dumps(
                [record.get('model'),record.get('sembol'),record.get('zaman') or record.get('tarih'),record.get('fiyat')]).encode()).hexdigest()[:24]
        record.setdefault('sinyal_id',record.get('kayit_id'));record.setdefault('sinyal_turu',record.get('model','LEGACY'))
        record.setdefault('referans_fiyat',record.get('fiyat'));record.setdefault('confidence',record.get('guven'))
        record.setdefault('ai_score',record.get('nihai_ai_puan'));record.setdefault('sektor','BILINMIYOR');record.setdefault('piyasa_rejimi','BILINMIYOR')
        record.setdefault('katkilar',{});record.setdefault('kaynak',record.get('model','LEGACY'));record.setdefault('snapshot_id',None)
        record.setdefault('kriterler',{k:record[k] for k in ('rsi','rsi5','macd','signal','hist','sma20','sma50','hacim_orani','vwap20_durum','obv_durum','boll_durum','momentum15','destek','direnc','risk_getiri','haber_puani','makro_puani','sektor_puani') if k in record})
        record.setdefault('teknik_skor',record.get('teknik_puan'));record.setdefault('haber_etkisi',record.get('haber_puani'));record.setdefault('makro_etkisi',record.get('makro_puani'))
        if number(record.get('referans_fiyat'),0)<=0:record['veri_kalitesi']='VERI_YETERSIZ'

    def reports(self,records,current):
        def grouping(field,rows):
            groups={}
            for r in rows:groups.setdefault(r.get(field) or 'BILINMIYOR',[]).append(r)
            return {k:summarize(v) for k,v in groups.items()}
        forecasts=[r for r in records if r.get('model')=='YARIN_TOP10']
        days={}
        for row in forecasts:days.setdefault(row['snapshot_tarihi'],[]).append(row)
        daily={day:daily_report(rows) for day,rows in sorted(days.items())}
        eligible=[r for r in records if r.get('egitim_durumu')!='REFERANS' and r.get('model') not in ('YARIN_BASELINE','YARIN_SHADOW')]
        complete_dates=sorted({v['sonuc_tarihi'] for v in daily.values() if v['tamamlandi'] and v['sonuc_tarihi']})[-20:]
        recent=[r for r in forecasts if usable(r) and r['sonuc_1g'].get('tarih') in complete_dates and daily[r['snapshot_tarihi']]['tamamlandi']]
        report={'updated_at':current.isoformat(),'vadeler':{str(h):summarize(eligible,h) for h in HORIZONS},
            'modeller':grouping('model',eligible),'sektorler':grouping('sektor',eligible),'rejimler':grouping('piyasa_rejimi',eligible),
            'yarin_top10':summarize(forecasts),'son20_gun':summarize(recent),
            'kriter_performansi':criterion_report(eligible),'yarin_kriter_performansi':criterion_report(forecasts),
            'sinirlamalar':['TATIL_TAKVIMI_ENJEKSIYONLA_DESTEKLENIR','YANLIS_NEGATIF_YALNIZCA_KAYITLI_SINYALLER','KRITER_ILISKISI_NEDENSELLIK_DEGIL']}
        report['sektor_kriterleri']={sector:criterion_report([r for r in eligible if (r.get('sektor') or 'BILINMIYOR')==sector]) for sector in report['sektorler']}
        report['rejim_kriterleri']={regime:criterion_report([r for r in eligible if (r.get('piyasa_rejimi') or 'BILINMIYOR')==regime]) for regime in report['rejimler']}
        report['son20_gun']['gun_sayisi']=len(complete_dates)
        full_lists=[v for v in daily.values() if v['tamamlandi'] and v['sonuc_tarihi'] in complete_dates]
        report['son20_gun']['tamamlanan_liste']=len(full_lists)
        report['son20_gun']['top3']=robust([v['top3']['ortalama'] for v in full_lists if v['top3']['ortalama'] is not None])
        report['son20_gun']['top10']=robust([v['top10']['ortalama'] for v in full_lists if v['top10']['ortalama'] is not None])
        report['son20_gun']['skor_performans_iliskisi']=robust([v['skor_performans_korelasyonu'] for v in full_lists if v['skor_performans_korelasyonu'] is not None])
        from teknik_gostergeler import performance_report
        report['standart_teknik_kriterler']=performance_report(forecasts,current,'TOMORROW',minimum_samples())
        from ai_karar_motoru import final_decision_report
        report['nihai_karar_performansi']=final_decision_report(eligible,current)
        report['kriter_vadeleri']={str(h):criterion_report(eligible,h) for h in (3,5)}
        current_weights=load(self.location.runtime/'ai_agirliklari.json',{}).get('agirliklar',DEFAULT_WEIGHTS)
        current_weights=normalize_weights(current_weights)
        proposal=weight_proposals(report['yarin_kriter_performansi'],current_weights)
        atomic_json(self.result_path,{'updated_at':current.isoformat(),'sonuclar':{r['kayit_id']:r for r in forecasts}})
        for name,value in (('performans_gunluk.json',{'updated_at':current.isoformat(),'gunler':daily}),
                           ('performans_ozeti.json',report),('onerilen_agirliklar.json',proposal)):
            self.location.public.mkdir(parents=True,exist_ok=True)
            atomic_json(self.location.public/name,value)

    def one_round(self):
        current=self.clock().astimezone(ISTANBUL);processed=changed=0;errors={}
        with locked(self.state_path):
            state=load(self.state_path,{'arsivler':{},'tekrar':{}});cache=load(self.cache_path,{})
            # Read/import under the shared history lock; provider calls never hold it.
            with locked(self.history_path):
                history=load(self.history_path,{'kayitlar':[]});records=history.setdefault('kayitlar',[])
                original_count=len(records)
                ids={r.get('kayit_id') for r in records}
                for record in self.snapshot_records(state)+self.event_records(ids):
                    if record['kayit_id'] not in ids:records.append(record);ids.add(record['kayit_id'])
                pending=[]
                for record in records:
                    if not isinstance(record,dict):continue
                    self.enrich(record)
                    if record.get('egitim_durumu')=='REFERANS':continue
                    start=stamp(record.get('zaman'))
                    if not start:continue
                    retry=stamp(state['tekrar'].get(record['sinyal_id']))
                    if retry and retry>current:continue
                    horizons=(1,3,5) if record.get('model') in ('HABER','MAKRO') else HORIZONS
                    due=[h for h in horizons if not (isinstance(record.get('sonuc_'+str(h)+'g'),dict) and record['sonuc_'+str(h)+'g'].get('degerlendirme_tamamlandi',True))
                         and session_closed(sessions_after(start.date(),h,self.holiday)[-1],current)]
                    if due:pending.append((dict(record),due))
                atomic_json(self.history_path,history)
            symbols=list(dict.fromkeys(r['sembol'] for r,hs in pending))[:self.batch_size]
            per_symbol=max(1,100//len(symbols)) if symbols else 0
            selected=[pair for stock in symbols for pair in [(r,hs) for r,hs in pending if r['sembol']==stock][:per_symbol]]
            prices={}
            for stock in symbols:
                try:
                    if not any(number(r.get('referans_fiyat'),0)>0 for r,hs in selected if r['sembol']==stock):
                        prices[stock]=[];continue
                    cached=cache.get(stock,{})
                    if cached.get('day')==current.date().isoformat() and cached.get('closed')==session_closed(current.date(),current):prices[stock]=cached['bars']
                    else:
                        prices[stock]=list(self.provider(stock))
                        cache[stock]={'day':current.date().isoformat(),'closed':session_closed(current.date(),current),'bars':prices[stock]}
                except Exception as error:errors[stock]=type(error).__name__
            updates={}
            for record,hs in selected:
                stock=record['sembol'];rid=record['sinyal_id'];processed+=1
                if stock not in prices:
                    state['tekrar'][rid]=(current+timedelta(hours=6)).isoformat();continue
                updates[rid]={}
                for horizon in hs:
                    try:result=outcome(record,prices[stock],horizon,current,self.holiday)
                    except (ValueError,TypeError,AttributeError):
                        result={'durum':'VERI_YETERSIZ','degerlendirme_tamamlandi':False,'neden':'GECERSIZ_FIYAT_GECMISI','observed_at':current.isoformat()}
                    if result is not None:updates[rid]['sonuc_'+str(horizon)+'g']=result
                state['tekrar'][rid]=(current+timedelta(hours=6)).isoformat()
            with locked(self.history_path):
                history=load(self.history_path,{'kayitlar':[]})
                for record in history['kayitlar']:
                    for key,result in updates.get(record.get('sinyal_id'),{}).items():
                        existing=record.get(key)
                        if isinstance(existing,dict) and existing.get('degerlendirme_tamamlandi',True):continue
                        record[key]=result;changed+=int(result['degerlendirme_tamamlandi'])
                history.update(guncelleme=current.isoformat(),toplam_kayit=len(history['kayitlar']))
                atomic_json(self.history_path,history)
                last_report=stamp(state.get('last_report'))
                if updates or len(history['kayitlar'])!=original_count or not last_report or (current-last_report).total_seconds()>=3600:
                    self.reports(history['kayitlar'],current);state['last_report']=current.isoformat()
            state['updated_at']=current.isoformat();atomic_json(self.state_path,state);atomic_json(self.cache_path,cache)
        return {'kontrol_edilen':processed,'tamamlanan_vade':changed,'sembol_sayisi':len(symbols),'hatalar':errors}


def bekleyen_sonuclari_guncelle(history_provider=None, **kwargs):
    return PerformansMotoru(history_provider=history_provider,**kwargs).one_round()
