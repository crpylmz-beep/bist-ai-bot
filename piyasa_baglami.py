"""One provider-free market context shared by intraday, tomorrow and common AI."""
from datetime import datetime,timedelta,time
from statistics import mean,median
import hashlib
import json
import os

from ai_karar_motoru import ISTANBUL,number,stamp,load,locked,clamp
from ana_motor import market_open
from kullanici_kayitlari import atomic_json
from sektor_haritasi import sektor_eslestirmesi
from veri_yollari import paths

MODEL='BIST_CONTEXT_V1'
REGIMES=('GUCLU_YUKSELIS','YUKSELIS','YATAY','DUSUS','GUCLU_DUSUS','BELIRSIZ')


def config(name,default,low,high):
    value=number(os.environ.get(name,str(default)))
    if value is None or not low<=value<=high:raise ValueError(name+' geçersiz')
    return value


def effect_limits():
    return {'piyasa_duzeltmesi':config('MARKET_REGIME_MAX_EFFECT',.75,0,2),
            'breadth_duzeltmesi':config('BREADTH_MAX_EFFECT',.75,0,2),
            'sektor_duzeltmesi':config('SECTOR_RS_MAX_EFFECT',1,0,2)}


def optional(path,default):
    try:return load(path,default)
    except (OSError,ValueError):return default


def quote_time(row,fallback,source):
    if source=='INTRADAY' and stamp(row.get('veri_tarihi')):
        return stamp(row['veri_tarihi'])+timedelta(minutes=5)
    return stamp(row.get('canli_guncelleme') or row.get('quote_updated_at') or row.get('updated_at') or fallback)


def breadth_label(score):
    return 'COK_POZITIF' if score>=55 else 'POZITIF' if score>=20 else 'COK_NEGATIF' if score<=-55 else 'NEGATIF' if score<=-20 else 'NOTR'


def sector_label(score):
    return 'COK_GUCLU' if score>=50 else 'GUCLU' if score>=15 else 'COK_ZAYIF' if score<=-50 else 'ZAYIF' if score<=-15 else 'NOTR'


def build_context(rows,universe,index,sector_map,current,source='DAILY',fallback=None):
    current=current.astimezone(ISTANBUL)
    index=index or {}
    minimum=config('BREADTH_MIN_COVERAGE',.6,.5,1)
    min_stocks=int(config('BREADTH_MIN_STOCKS',30,30,1000))
    sector_min=int(config('SECTOR_RS_MIN_STOCKS',5,5,100))
    symbols=set(universe or sector_map or [r.get('sembol') for r in rows if r.get('sembol')]);total=len(symbols)
    valid={};stale=missing=future=0;ages=[]
    for row in rows:
        symbol=row.get('sembol')
        if symbol not in symbols:continue
        at=quote_time(row,fallback,source)
        price=number(row.get('fiyat'));change=number(row.get('acilisa_gore_degisim') if source=='INTRADAY' else row.get('degisim'))
        if not at or not price or price<=0 or change is None:missing+=1;continue
        age=(current-at).total_seconds()/60
        if age<0:future+=1;continue
        if age>20 or at.date()!=current.date():stale+=1;continue
        if symbol in valid and quote_time(valid[symbol],fallback,source)>=at:continue
        valid[symbol]=dict(row,_at=at.isoformat(),_return=change,_age=age)
    ages=[r['_age'] for r in valid.values()]
    rows=list(valid.values());count=len(rows);coverage=count/total if total else 0
    rising=[r for r in rows if r['_return']>.01];falling=[r for r in rows if r['_return']<-.01]
    unchanged=count-len(rising)-len(falling)
    volume=lambda r:number(r.get('hacim3_orani') if source=='INTRADAY' else r.get('hacim_orani'))
    supported_up=sum(volume(r) is not None and volume(r)>=120 for r in rising)
    supported_down=sum(volume(r) is not None and volume(r)>=120 for r in falling)
    breadth_score=100*(len(rising)-len(falling))/count if count else None
    enough=count>=min_stocks and coverage>=minimum
    freshness=.7 if ages and max(ages)>10 else 1
    confidence=round(100*coverage*freshness,2) if enough else round(min(40,100*coverage)*freshness,2)
    breadth={'updated_at':current.isoformat(),'score':round(breadth_score,2) if enough else None,
        'sinif':breadth_label(breadth_score) if enough else 'BELIRSIZ','confidence':confidence,'yeterli_veri':enough,
        'izlenen':total,'gecerli':count,'coverage':coverage,'minimum_coverage':minimum,'minimum_hisse':min_stocks,
        'yukselen':len(rising),'dusen':len(falling),'degismeyen':unchanged,
        'yukselen_dusen_orani':len(rising)/len(falling) if falling else None,
        'pozitif_yuzde':100*len(rising)/count if count else None,'negatif_yuzde':100*len(falling)/count if count else None,
        'guclu_yukselen':sum(r['_return']>=3 for r in rows),'guclu_dusen':sum(r['_return']<=-3 for r in rows),
        'hacim_destekli_yukselen':supported_up,'hacim_destekli_dusen':supported_down,
        'stale_hisse':stale,'eksik_hisse':missing,'gelecek_hisse':future,'stale':not enough,
        'getiri_bazi':'GUN_ACILISI' if source=='INTRADAY' else 'ONCEKI_KAPANIS'}
    index_at=stamp(index.get('updated_at') or index.get('guncelleme'))
    index_fresh=bool(index_at and index_at<=current and index_at.date()==current.date() and (current-index_at).total_seconds()<=1200)
    index_return=number(index.get('degisim')) if index_fresh else None
    if source=='INTRADAY':
        price,opening=number(index.get('fiyat')),number(index.get('acilis'))
        index_return=(price/opening-1)*100 if index_fresh and price and opening and opening>0 else None
    reference=index_return if index_return is not None else median([r['_return'] for r in rows]) if enough else None
    groups={};expected={}
    for symbol in symbols:expected[sector_map.get(symbol,'BILINMIYOR')]=expected.get(sector_map.get(symbol,'BILINMIYOR'),0)+1
    for r in rows:groups.setdefault(sector_map.get(r['sembol'],'BILINMIYOR'),[]).append(r)
    sectors={}
    def trend(r,long=False):
        average=number(r.get(('ema21_5' if long else 'ema9_5') if source=='INTRADAY' else ('sma50' if long else 'sma20')))
        price=number(r.get('fiyat'))
        if not average or average<=0 or not price:return None
        return 1 if price>average else -1 if price<average else 0
    for name in expected:
        members=groups.get(name,[]);returns=[r['_return'] for r in members];n=len(members);sector_coverage=n/expected[name]
        eligible=enough and name!='BILINMIYOR' and n>=sector_min and sector_coverage>=minimum
        med=median(returns) if returns else None;relative=med-reference if eligible else None
        score=clamp(relative*25,-100,100) if relative is not None else None
        trend_values=[trend(r) for r in members if trend(r) is not None]
        available_volume=[r for r in members if volume(r) is not None]
        sectors[name]={'updated_at':current.isoformat(),'hisse_sayisi':n,'izlenen':expected[name],'coverage':sector_coverage,
            'pozitif_oran':sum(v>0 for v in returns)/n if n else None,'ortalama_getiri':mean(returns) if returns else None,
            'medyan_getiri':med,'hacim_destegi':sum(volume(r)>=120 for r in available_volume)/len(available_volume) if available_volume else None,
            'trend_score':100*mean(trend_values) if trend_values else None,'relatif_getiri':relative,'rs_score':round(score,2) if score is not None else None,
            'sinif':sector_label(score) if score is not None else 'NOTR','confidence':round(100*sector_coverage*freshness,2) if eligible else 0,'yeterli_veri':eligible}
    components={};weights={'bist100':.25,'breadth':.25,'kisa_trend':.12,'orta_trend':.12,'momentum':.1,'hacim':.08,'sektor_dagilimi':.08}
    if index_return is not None:components['bist100']=clamp(index_return/3*100,-100,100)
    if enough:components['breadth']=breadth_score
    for key,long in (('kisa_trend',False),('orta_trend',True)):
        samples=[trend(r,long) for r in rows if trend(r,long) is not None]
        if len(samples)>=min_stocks and len(samples)/max(total,1)>=minimum:components[key]=100*mean(samples)
    momenta=[number(r.get('momentum15')) for r in rows if number(r.get('momentum15')) is not None]
    if len(momenta)>=min_stocks and len(momenta)/max(total,1)>=minimum:components['momentum']=clamp(median(momenta)*50,-100,100)
    volume_rows=[r for r in rows if volume(r) is not None]
    if len(volume_rows)>=min_stocks and len(volume_rows)/max(total,1)>=minimum:components['hacim']=100*(supported_up-supported_down)/len(volume_rows)
    eligible_sectors=[v for v in sectors.values() if v['yeterli_veri']]
    if len(eligible_sectors)>=3:components['sektor_dagilimi']=100*mean([1 if v['medyan_getiri']>0 else -1 if v['medyan_getiri']<0 else 0 for v in eligible_sectors])
    enough_regime=enough and len(components)>=3 and any(k in components for k in ('bist100','kisa_trend','orta_trend'))
    score=sum(components[k]*weights[k] for k in components)/sum(weights[k] for k in components) if enough_regime else None
    volatility=number(index.get('volatilite')) if index_fresh else None
    if volatility is None and index_fresh:
        hi,lo,price=number(index.get('yuksek')),number(index.get('dusuk')),number(index.get('fiyat'))
        volatility=(hi-lo)/price*100 if hi and lo and price and hi>=lo else None
    regime_conf=confidence*(.7+.3*len(components)/len(weights)) if enough_regime else min(confidence,25)
    if volatility is not None and volatility>5:regime_conf*=.75
    regime='BELIRSIZ' if score is None or regime_conf<50 else 'GUCLU_YUKSELIS' if score>=55 else 'YUKSELIS' if score>=20 else 'GUCLU_DUSUS' if score<=-55 else 'DUSUS' if score<=-20 else 'YATAY'
    ordered=sorted([dict(sektor=k,**v) for k,v in sectors.items() if v['yeterli_veri']],key=lambda v:v['rs_score'],reverse=True)
    closed=not market_open(current)
    doc={'model':MODEL,'etki_limitleri':effect_limits(),'updated_at':current.isoformat(),'seans_tarihi':current.date().isoformat(),'kaynak':source,
        'piyasa_acik':not closed,'veri_etiketi':'SON_BILINEN_SEANS' if closed else 'CANLI_SEANS',
        'piyasa_rejimi':regime,'rejim_score':round(score,2) if score is not None else None,'rejim_confidence':round(regime_conf,2),
        'kullanilan_veri_sayisi':len(components),'rejim_bilesenleri':components,'volatilite_yuzde':volatility,
        'veri_tazeligi':{'en_eski_yas_dk':max(ages) if ages else None,'en_yeni_yas_dk':min(ages) if ages else None,'bist100_updated_at':index_at.isoformat() if index_at else None},
        'stale':not enough,'breadth':breadth,'sektorler':sectors,'sektor_siralamasi':ordered,
        'en_guclu_sektorler':[v['sektor'] for v in ordered if v['rs_score']>0][:3],
        'en_zayif_sektorler':[v['sektor'] for v in reversed(ordered) if v['rs_score']<0][:3],
        'hisse_sektorleri':sector_map,'piyasa_getirisi':reference,'piyasa_getiri_kaynagi':'BIST100' if index_return is not None else 'IZLENEN_MEDYAN' if reference is not None else 'YOK'}
    doc['version']=MODEL+'_'+hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()[:16]
    return doc


def usable_context(doc,current,mode='AI'):
    doc=dict(doc or {});at=stamp(doc.get('updated_at'))
    if not at or at>current:return {}
    closed=not market_open(current)
    stale=(current-at).total_seconds()>1200 or doc.get('stale',True) or doc.get('seans_tarihi')!=current.date().isoformat()
    oldest=number(doc.get('veri_tazeligi',{}).get('en_eski_yas_dk'))
    if oldest is not None and oldest+(current-at).total_seconds()/60>20:stale=True
    index_at=stamp(doc.get('veri_tazeligi',{}).get('bist100_updated_at'))
    if 'bist100' in doc.get('rejim_bilesenleri',{}) and (not index_at or index_at>current or (current-index_at).total_seconds()>1200):stale=True
    # Intraday applies live context only. Closing forecasts may use that session's final context.
    if mode=='INTRADAY' and closed:stale=True
    factor=0 if stale else .7 if oldest is not None and oldest<=10 and oldest+(current-at).total_seconds()/60>10 else 1
    previous=number(doc.get('tazelik_guven_carpani'),1)
    scale=factor/previous if previous else 0
    if scale!=1:
        doc['rejim_confidence']=doc.get('rejim_confidence',0)*scale
        doc['breadth']=dict(doc.get('breadth',{}),confidence=doc.get('breadth',{}).get('confidence',0)*scale)
        doc['sektorler']={k:dict(v,confidence=v.get('confidence',0)*scale) for k,v in doc.get('sektorler',{}).items()}
        doc['sektor_siralamasi']=[dict(v,confidence=v.get('confidence',0)*scale) for v in doc.get('sektor_siralamasi',[])]
    doc['breadth']=dict(doc.get('breadth',{}),stale=stale)
    doc['tazelik_guven_carpani']=factor
    doc.update(stale=stale,piyasa_acik=not closed,veri_etiketi='SON_BILINEN_SEANS' if closed else 'ESKI_VERI' if stale else 'CANLI_SEANS')
    return doc


def stock_context(doc,row):
    name=doc.get('hisse_sektorleri',{}).get(row.get('sembol'),'BILINMIYOR')
    sector=doc.get('sektorler',{}).get(name,{})
    return {'model':doc.get('model',MODEL),'version':doc.get('version'),'updated_at':doc.get('updated_at'),
        'seans_tarihi':doc.get('seans_tarihi'),'kaynak':doc.get('kaynak'),'piyasa_rejimi':doc.get('piyasa_rejimi','BELIRSIZ'),
        'rejim_score':doc.get('rejim_score'),'rejim_confidence':doc.get('rejim_confidence',0),
        'breadth_score':doc.get('breadth',{}).get('score'),'breadth_confidence':doc.get('breadth',{}).get('confidence',0),
        'sektor':name,'sektor_rs_score':sector.get('rs_score'),'sektor_sinifi':sector.get('sinif','NOTR'),
        'sektor_confidence':sector.get('confidence',0),'stale':doc.get('stale',True),
        'piyasa_acik':doc.get('piyasa_acik',False),'veri_etiketi':doc.get('veri_etiketi'),'coverage':doc.get('breadth',{}).get('coverage',0),
        'etki_limitleri':doc.get('etki_limitleri') or effect_limits(),
        'veri_tazeligi':doc.get('veri_tazeligi',{}),'bist100_kullanildi':'bist100' in doc.get('rejim_bilesenleri',{})}


def annotate(rows,doc):
    for row in rows:
        context=stock_context(doc,row)
        row.update(piyasa_baglami=context,piyasa_rejimi=context['piyasa_rejimi'] if not context['stale'] and context['rejim_confidence']>=50 else 'BELIRSIZ',breadth_score=context['breadth_score'],
            piyasa_sektoru=context['sektor'],
            sektor_rs_score=context['sektor_rs_score'],sektor_rs_sinifi=context['sektor_sinifi'],sektor_rs_confidence=context['sektor_confidence'],
            piyasa_model_version=context['version'])
    return rows


def effects(row,raw,current,mode='AI'):
    ctx=row.get('piyasa_baglami') or {};at=stamp(ctx.get('updated_at'))
    valid=bool(at and at<=current and (current-at).total_seconds()<=1200 and ctx.get('seans_tarihi')==current.date().isoformat() and not ctx.get('stale',True))
    oldest=number(ctx.get('veri_tazeligi',{}).get('en_eski_yas_dk'))
    if valid and oldest is not None and oldest+(current-at).total_seconds()/60>20:valid=False
    index_at=stamp(ctx.get('veri_tazeligi',{}).get('bist100_updated_at'))
    if valid and ctx.get('bist100_kullanildi') and (not index_at or index_at>current or (current-index_at).total_seconds()>1200):valid=False
    if mode=='INTRADAY' and not market_open(current):valid=False
    threshold=55 if mode=='YARIN' else 45 if mode=='INTRADAY' else 70
    values={};reasons=[];negative=[]
    maxima=ctx.get('etki_limitleri') or effect_limits()
    for field,score_key,confidence_key in (('piyasa_duzeltmesi','rejim_score','rejim_confidence'),('breadth_duzeltmesi','breadth_score','breadth_confidence'),('sektor_duzeltmesi','sektor_rs_score','sektor_confidence')):
        score=number(ctx.get(score_key));confidence=number(ctx.get(confidence_key),0)
        amount=score/100*maxima[field]*confidence/100 if valid and confidence>=50 and score is not None and raw>=threshold else 0
        unsafe=raw<(65 if mode=='INTRADAY' else 70) or any(number(row.get(k),0)<0 for k in ('haber_puani','makro_puani','sektor_puani')) or number(row.get('rsi5' if mode=='INTRADAY' else 'rsi'),50)>=70
        excessive=number(row.get('acilisa_gore_degisim' if mode=='INTRADAY' else 'degisim'),0)>(5 if mode=='INTRADAY' else 4)
        if unsafe or excessive:amount=min(0,amount)
        values[field]=round(amount,6)
        if amount:
            text={'piyasa_duzeltmesi':('Genel piyasa yükseliş rejiminde','Genel piyasa düşüş rejiminde'),
                'breadth_duzeltmesi':('BIST genişliği güçlü','Piyasa genişliği zayıf'),
                'sektor_duzeltmesi':(ctx.get('sektor','Sektör')+' sektörü piyasadan güçlü','Sektör relatif gücü negatif')}[field][0 if amount>0 else 1]
            (reasons if amount>0 else negative).append(text)
    total=sum(values.values());bounded=clamp(total,-3,3)
    if total and total!=bounded:values={k:round(v*bounded/total,6) for k,v in values.items()}
    return dict(values,piyasa_baglami_etkisi=round(sum(values.values()),6),
        piyasa_reasons_positive=reasons,piyasa_reasons_negative=negative,
        piyasa_confidence_duzeltmesi=-10 if valid and ctx.get('piyasa_rejimi')=='GUCLU_DUSUS' and number(ctx.get('breadth_score'),0)<-20 else 0)


class PiyasaBaglami:
    def __init__(self,location=None,clock=None):
        self.location=location or paths();self.clock=clock or (lambda:datetime.now(ISTANBUL))
        self.file=self.location.public/'piyasa_durumu.json'

    def context(self,mode='AI'):
        return usable_context(optional(self.file,{}),self.clock().astimezone(ISTANBUL),mode)

    def refresh(self,rows=None,universe=None,index=None,source='DAILY',fallback=None,force=False):
        current=self.clock().astimezone(ISTANBUL)
        with locked(self.file):
            old=optional(self.file,{})
            at=stamp(old.get('updated_at'))
            if rows is None and old.get('kaynak')=='INTRADAY' and not usable_context(old,current).get('stale',True):
                return usable_context(old,current)
            if not force and at and 0<=(current-at).total_seconds()<300 and old.get('kaynak')==source:
                return usable_context(old,current)
            data=optional(self.location.public/'bist_data.json',{})
            if rows is None:
                rows=data.get('hisseler',[]);fallback=data.get('updated_at') or data.get('guncelleme')
            if index is None:index=data.get('bist100',{})
            sector_map=sektor_eslestirmesi(self.location)
            if universe is None:universe=set(sector_map)|{r.get('sembol') for r in data.get('hisseler',[]) if r.get('sembol')}
            result=build_context(rows,universe,index,sector_map,current,source,fallback)
            self.location.public.mkdir(parents=True,exist_ok=True)
            atomic_json(self.file,result)
            return usable_context(result,current)


def intraday_quotes(veri_map,analyses,current):
    """Reuse stream OHLC also for filtered stocks, without adding technical indicators."""
    output={r['sembol']:dict(r) for r in analyses if r.get('sembol')}
    for symbol,frame in veri_map.items():
        if frame is None or frame.empty or not {'Open','Close'}.issubset(frame.columns):continue
        dates=frame.index
        if getattr(dates,'tz',None) is None:dates=dates.tz_localize(ISTANBUL)
        closed=frame[(dates+timedelta(minutes=5)<=current)&(dates.date==current.date())]
        if closed.empty:continue
        price=number(closed['Close'].iloc[-1]);opening=number(closed['Open'].iloc[0])
        if not price or not opening:continue
        row=output.setdefault(symbol,{'sembol':symbol})
        row.update(fiyat=price,acilisa_gore_degisim=(price/opening-1)*100,veri_tarihi=str(closed.index[-1]))
    return list(output.values())
