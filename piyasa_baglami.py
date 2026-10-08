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


    def measurement(self):
        from kullanici_kayitlari import RecordError
        current=self.clock().astimezone(ISTANBUL)
        if not regime_enabled():return {'enabled':False,'engine_version':MEASUREMENT_VERSION}
        try:
            raw=json.loads((self.location.public/'market_context.json').read_text(encoding='utf-8'))
            return dict(self.context(),**measurement_view(raw,current),enabled=True)
        except (OSError,ValueError,TypeError,KeyError):
            raise RecordError('Piyasa durumu henüz alınamıyor.',503) from None

    def refresh_measurement(self,universe=None,index=None,holiday=None):
        if not regime_enabled():return {'enabled':False}
        from performans_motoru import bist_holiday
        from teknik_gostergeler import calculate
        current=self.clock().astimezone(ISTANBUL);holiday=holiday or bist_holiday
        target=self.location.public/'market_context.json'
        with locked(target):
            data=load(self.location.public/'bist_data.json',{})
            if not isinstance(data,dict) or not isinstance(data.get('hisseler',[]),list):raise ValueError('Market source format')
            universe_path=self.location.runtime/'market_context_universe.json'
            if universe is None:
                saved=load(universe_path,{})
                at=stamp(saved.get('created_at'))
                if saved.get('source')=='XUTUM' and at and at<=current and at.date()==current.date():universe=saved['symbols']
                else:
                    import bist_bot
                    universe=bist_bot.bist_hisseleri_getir()
                    if not universe:
                        from gorev_hatalari import TaskIssue
                        raise TaskIssue({'code':'EMPTY_UNIVERSE'})
                    with locked(universe_path):atomic_json(universe_path,{'source':'XUTUM','created_at':current.isoformat(),'symbols':universe})
            day=expected_session(current,holiday)
            history=self.location.runtime/'market_context'/f'{day.isoformat()}.json'
            if history.exists():
                doc=json.loads(history.read_text(encoding='utf-8'))
                measurement_view(doc,current,holiday)
                if not doc.get('final') or stamp(doc.get('as_of')).date()!=day:raise ValueError('Market archive identity')
                old=load(target,{})
                if old!=doc:atomic_json(target,doc)
                return measurement_view(doc,current,holiday)
            # Reuse a compact index observation once per reference session, not a history copy.
            index_issue=None
            if index is None:
                idx_path=self.location.runtime/'market_context_index.json';index=load(idx_path,{})
                if not closed_observation(index,current,holiday):
                    import bist_bot
                    try:
                        daily=bist_bot.bp.Index('XU100').history(period='6mo')
                        index={'sembol':'XU100','teknik_gostergeler':calculate(daily,current,'TOMORROW')}
                        if closed_observation(index,current,holiday):
                            with locked(idx_path):atomic_json(idx_path,index)
                        else:index_issue={'code':'PROVIDER_DATA'}
                    except Exception as error:
                        from gorev_hatalari import describe,log_source
                        log_source(error,'PROVIDER');index_issue=describe(error,'PROVIDER');index={}
            doc=build_measurement(data.get('hisseler',[]),universe,index,current,holiday)
            # Knowledge time is after provider/calculation completion, not request start.
            completed=max(current,self.clock().astimezone(ISTANBUL))
            doc['created_at']=completed.isoformat()
            if doc['final']:
                history.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with locked(history):
                    if history.exists():doc=json.loads(history.read_text(encoding='utf-8'))
                    else:atomic_json(history,doc)
            previous=load(target,{})
            # No repeated write of identical observations while the market is closed.
            def content(value):return {k:v for k,v in value.items() if k not in ('created_at','market_open')}
            if content(previous)!=content(doc):atomic_json(target,doc)
            elif previous:doc=previous
            if index_issue:
                from gorev_hatalari import TaskIssue
                raise TaskIssue(index_issue,doc['valid_stock_count'],{'index_unavailable':True,'valid_stock_count':doc['valid_stock_count']})
            return measurement_view(doc,completed,holiday)


    def sectors(self,query=None):
        from kullanici_kayitlari import RecordError
        from saglayici_sembolleri import bist_symbol
        query=query or {}
        if set(query)-{'sector','symbol'} or len(query)>1 or any(not isinstance(v,list) or len(v)!=1 or not v[0].strip() or len(v[0])>100 for v in query.values()):
            raise RecordError('Sektör sorgusu geçersiz.',400)
        if 'symbol' in query:
            try:stock=bist_symbol(query['symbol'][0])
            except (ValueError,TypeError):raise RecordError('Hisse sorgusu geçersiz.',400) from None
        if not sector_enabled():return {'enabled':False,'engine_version':SECTOR_VERSION,'sectors':[]}
        try:
            doc=sector_view(load(self.location.public/'sector_context.json',{}),self.clock().astimezone(ISTANBUL))
        except (OSError,ValueError,TypeError,KeyError,AttributeError):raise RecordError('Sektör verisi henüz alınamıyor.',503) from None
        if 'sector' in query:
            rows=[v for v in doc['sectors'] if v['sector_code']==query['sector'][0] or v['sector_name']==query['sector'][0]]
            if not rows:raise RecordError('Sektör bulunamadı.',400)
            doc['sectors']=rows;doc.pop('stocks',None)
        elif 'symbol' in query:
            if stock not in doc['stocks']:raise RecordError('Hisse sektör verisi bulunamadı.',400)
            return {'enabled':True,'as_of':doc['as_of'],'stale':doc['stale'],'stock_sector_context':doc['stocks'][stock]}
        else:doc.pop('stocks',None)
        return dict(doc,enabled=True)

    def refresh_sectors(self,universe=None,index=None,official=None,holiday=None,discover=True,enqueue=None):
        """Bootstrap missing observations via the normal queue; retain real failures."""
        if not sector_enabled():return {'enabled':False}
        from gorev_hatalari import TaskIssue,strongest,public_issue
        current=self.clock().astimezone(ISTANBUL);day=expected_session(current,holiday)
        target=self.location.public/'sector_context.json';history=self.location.runtime/'sector_context'/f'{day.isoformat()}.json'
        with locked(target):
            issues=[];mapping=sektor_eslestirmesi(self.location)
            if universe is None:
                saved=load(self.location.runtime/'market_context_universe.json',{})
                at=stamp(saved.get('created_at'))
                if saved.get('source')=='XUTUM' and at and at<=current and at.date()==current.date():universe=saved.get('symbols')
                else:
                    import bist_bot
                    universe=bist_bot.bist_hisseleri_getir()
                    if universe:
                        path=self.location.runtime/'market_context_universe.json'
                        with locked(path):atomic_json(path,{'source':'XUTUM','created_at':current.isoformat(),'symbols':universe})
                if not universe:
                    sector_trace('UNIVERSE',{},universe or [],mapping,{'code':'EMPTY_UNIVERSE'})
                    raise TaskIssue({'code':'EMPTY_UNIVERSE'})
            universe=sector_universe(universe)
            if official is None:
                official={}
                if discover:official,issues=sector_indices(self.location,universe,mapping,current,holiday)
            bootstrap_count=0;benchmark_issue=None
            if history.exists():
                doc=load(history,{})
                sector_view(doc,current,holiday)
                if not doc.get('final') or stamp(doc['as_of']).date()!=day:raise ValueError('Sector archive identity')
            else:
                data=load(self.location.public/'bist_data.json',{})
                if not isinstance(data,dict) or not isinstance(data.get('hisseler',[]),list):raise ValueError('Sector source format')
                if index is None:
                    if any(mapping.get(s) not in (None,'','UNKNOWN','BILINMIYOR') for s in universe):index,benchmark_issue=sector_benchmark(self.location,current,holiday)
                    else:index=load(self.location.runtime/'market_context_index.json',{})
                market=load(self.location.public/'market_context.json',{})
                doc=build_sectors(data.get('hisseler',[]),universe,mapping,index,current,official,market,holiday)
                if enqueue is not None:
                    bootstrap_count=sector_bootstrap(self.location,data.get('hisseler',[]),universe,mapping,current,enqueue,holiday)
                doc['created_at']=max(current,self.clock().astimezone(ISTANBUL)).isoformat()
                doc['final']=doc['final'] and any(v['data_status']=='COMPLETE' and v['sector_state'] is not None for v in doc['sectors'])
                if doc['final']:
                    with locked(history):
                        if history.exists():doc=load(history,{})
                        else:atomic_json(history,doc)
            # Optional discovery failures remain explicit, but working synthetic
            # measurements are a successful fallback, not a failed batch.
            source_issues=[dict(v,**public_issue(v)) for v in issues]
            if benchmark_issue:source_issues.append(dict(benchmark_issue,**public_issue(benchmark_issue)))
            public=dict(doc,source_issues=source_issues)
            if source_issues:public['warnings']=list(doc['warnings'])+['Kaynak: '+v['message'] for v in source_issues]
            before=load(target,{})
            if {k:v for k,v in before.items() if k!='created_at'}!={k:v for k,v in public.items() if k!='created_at'}:atomic_json(target,public)
            elif before:public=before
            valid=sum(v['data_status']=='COMPLETE' and v['sector_state'] is not None for v in doc['sectors'])
            unavailable=len(doc['sectors'])-valid
            code_issues=[v for v in source_issues if v.get('category') in ('CODE','STORAGE','CONFIG','UNKNOWN')]
            code_issues.extend(v['issue'] for v in doc.get('failures',[]))
            if code_issues:
                issue=strongest(code_issues);sector_trace('SYSTEM_ERROR',doc,universe,mapping,issue)
                raise TaskIssue(issue,sum(v['valid_member_count'] for v in doc['sectors']),{'successful':valid,'failed':len(code_issues)},isolated=True)
            if not valid:
                issue=benchmark_issue or {'code':'PROVIDER_DATA'}
                stage='BENCHMARK_HISTORY' if benchmark_issue else 'MAPPING' if not any(mapping.get(s) not in (None,'','UNKNOWN','BILINMIYOR') for s in universe) else 'MEMBER_HISTORY' if bootstrap_count else 'COVERAGE'
                sector_trace(stage,doc,universe,mapping,issue,bootstrap_count)
                raise TaskIssue(issue,sum(v['valid_member_count'] for v in doc['sectors']),{'successful':0,'failed':len(source_issues)},isolated=True)
            result=sector_view(public,self.clock().astimezone(ISTANBUL),holiday)
            result['diagnostics']={'successful':valid,'skipped':unavailable+len(source_issues),'failed':0,
                'reasons':[{'symbol':v['symbol'],'reason':v} for v in source_issues if v.get('symbol')]}
            sector_trace('PARTIAL_FALLBACK' if source_issues or unavailable else 'COMPLETE',doc,universe,mapping,
                         strongest(source_issues) if source_issues else {'code':'PROVIDER_DATA'} if unavailable else None,bootstrap_count)
            return result


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
# Closed-daily observation layer of the existing central engine. Legacy effects
# above retain their original vocabulary, weights and cache; these fields never
# enter investment scores.
MEASUREMENT_VERSION='MARKET_REGIME_V1'
BREADTH_WEIGHTS={'advances':.30,'sma20':.20,'sma50':.20,'high_low':.15,'volume':.15}
REGIME_WEIGHTS={'breadth':.50,'index_trend':.25,'index_momentum':.15,'volatility':.10}
STATE_CUTS=(80,60,40,20)
MIN_OBSERVATION_STOCKS=30
MIN_OBSERVATION_COVERAGE=.60
MIN_VOLUME_COVERAGE=.60
VOLATILITY_CUTS=(.75,1.5,2.5)


def regime_enabled():
    return os.environ.get('MARKET_REGIME_ENABLED','true').strip().lower() in ('true','1','yes','on')


def expected_session(current,holiday=None):
    from performans_motoru import business_day,session_closed
    day=current.date()
    if not session_closed(day,current):day-=timedelta(days=1)
    while not business_day(day,holiday):day-=timedelta(days=1)
    return day


def classification(score,labels):
    if score is None:return None
    return next((label for cut,label in zip(STATE_CUTS,labels) if score>=cut),labels[-1])


def weighted_observation(values,weights):
    available={k:v for k,v in values.items() if number(v) is not None}
    denominator=sum(weights[k] for k in available)
    if not denominator:return None,{}
    contributions={k:{'value':v,'weight':weights[k]/denominator,'contribution':v*weights[k]/denominator} for k,v in available.items()}
    return sum(v['contribution'] for v in contributions.values()),contributions


def closed_observation(row,current,holiday=None):
    """Reject open/future candles, mismatched provenance and invalid actual OHLC."""
    from performans_motoru import business_day,session_closed
    from saglayici_sembolleri import bist_symbol
    try:
        if not isinstance(row.get('sembol'),str) or not row['sembol'].strip():return None
        stock=bist_symbol(row['sembol'])
        doc=row.get('teknik_gostergeler') or {}
        at=stamp(doc.get('data_time'));observed=stamp(doc.get('asof'))
        raw=doc.get('closing') or {}
        if doc.get('mode')!='TOMORROW' or not at or not observed or at>current or observed>current:return None
        if not business_day(at.date(),holiday) or not session_closed(at.date(),current):return None
        if at.time().replace(tzinfo=None)<time(18,10) or observed<at or observed<datetime.combine(at.date(),time(18,15),ISTANBUL):return None
        if at.date()!=expected_session(current,holiday):return None
        close,previous,opening,hi,lo=(number(raw.get(k)) for k in ('close','previous_close','open','high','low'))
        if any(v is None or v<=0 for v in (close,previous,opening,hi,lo)) or not lo<=min(opening,close)<=max(opening,close)<=hi:return None
        return dict(raw,symbol=stock,as_of=datetime.combine(at.date(),time(18,15),ISTANBUL).isoformat(),
                    close=close,previous_close=previous,observed_at=observed.isoformat())
    except (ValueError,TypeError,AttributeError):return None


def index_observation(raw):
    raw=raw or {};price=number(raw.get('close'));short=number(raw.get('sma20'));long=number(raw.get('sma50'))
    trend='POSITIVE' if price and short and long and price>short>long else 'NEGATIVE' if price and short and long and price<short<long else 'NEUTRAL' if price and short and long else None
    votes={}
    for key in ('return_3d','sma20_slope','macd_histogram'):
        value=number(raw.get(key))
        if value is not None:votes[key]=1 if value>0 else -1 if value<0 else 0
    strength=number(raw.get('rsi'))
    if strength is not None:votes['rsi']=1 if strength>55 else -1 if strength<45 else 0
    momentum=None
    if len(votes)>=2:
        score=mean(votes.values());momentum='POSITIVE' if score>=.5 else 'NEGATIVE' if score<=-.5 else 'NEUTRAL'
    atr=number(raw.get('atr_pct'));baseline=number(raw.get('atr_pct_baseline'))
    ratio=atr/baseline if atr is not None and baseline and baseline>0 and atr>=0 else None
    volatility='LOW' if ratio is not None and ratio<VOLATILITY_CUTS[0] else 'NORMAL' if ratio is not None and ratio<=VOLATILITY_CUTS[1] else 'HIGH' if ratio is not None and ratio<=VOLATILITY_CUTS[2] else 'EXTREME' if ratio is not None else None
    return {'index_trend':trend,'index_momentum':momentum,'index_volatility':volatility,
            'index_atr_pct':atr,'index_volatility_ratio':ratio,'index_components':votes,'benchmark':'XU100'}


def risk_class(volatility,breadth,declining_pct,momentum):
    if volatility=='EXTREME' or (breadth is not None and breadth<20 and declining_pct is not None and declining_pct>=80):return 'EXTREME'
    if volatility=='HIGH' or (breadth is not None and breadth<40) or (momentum=='NEGATIVE' and declining_pct is not None and declining_pct>=60):return 'HIGH'
    if volatility=='LOW' and breadth is not None and breadth>=60 and momentum=='POSITIVE':return 'LOW'
    return 'NORMAL' if any(v is not None for v in (volatility,breadth,declining_pct,momentum)) else None


def build_measurement(rows,universe,index,current,holiday=None):
    """XUTUM members only; no provider calls and no raw series in the output."""
    from saglayici_sembolleri import bist_symbol
    from performans_motoru import bist_holiday
    holiday=holiday or bist_holiday
    symbols=set()
    for value in universe:
        if not isinstance(value,str) or not value.strip():continue
        try:symbols.add(bist_symbol(value))
        except ValueError:continue
    valid={};invalid=0;duplicates=set()
    for row in rows:
        observation=closed_observation(row,current,holiday)
        if not observation or observation['symbol'] not in symbols:invalid+=1;continue
        key=observation['symbol']
        if key in valid and valid[key]!=observation:duplicates.add(key)
        else:valid[key]=observation
    for key in duplicates:valid.pop(key,None)
    observations=list(valid.values());n=len(observations);coverage=n/len(symbols) if symbols else 0
    advancing=sum(r['close']>r['previous_close'] for r in observations)
    declining=sum(r['close']<r['previous_close'] for r in observations)
    unchanged=n-advancing-declining
    samples={};percent={};values={}
    if n:values['advances']=100*(advancing+.5*unchanged)/n
    for length in (20,50):
        rows_with=[r for r in observations if number(r.get('sma'+str(length))) is not None and r['sma'+str(length)]>0]
        samples['sma'+str(length)]=len(rows_with)
        percent['above_sma'+str(length)+'_pct']=100*sum(r['close']>r['sma'+str(length)] for r in rows_with)/len(rows_with) if rows_with else None
        if rows_with:values['sma'+str(length)]=percent['above_sma'+str(length)+'_pct']
    highs=[r for r in observations if number(r.get('previous20_high')) is not None and number(r.get('previous20_low')) is not None and 0<r['previous20_low']<=r['previous20_high']]
    new_high=sum(r['high']>r['previous20_high'] for r in highs) if highs else None
    new_low=sum(r['low']<r['previous20_low'] for r in highs) if highs else None
    samples['high_low']=len(highs)
    if highs:values['high_low']=50+50*(new_high-new_low)/len(highs)
    volumes=[r for r in observations if number(r.get('volume')) is not None and r['volume']>=0]
    samples['volume']=len(volumes);volume_coverage=len(volumes)/n if n else 0
    total_volume=sum(r['volume'] for r in volumes)
    up_volume=sum(r['volume'] for r in volumes if r['close']>r['previous_close'])
    down_volume=sum(r['volume'] for r in volumes if r['close']<r['previous_close'])
    up_pct=100*up_volume/total_volume if total_volume else None;down_pct=100*down_volume/total_volume if total_volume else None
    if total_volume and volume_coverage>=MIN_VOLUME_COVERAGE:values['volume']=50+50*(up_volume-down_volume)/total_volume
    breadth,debug=weighted_observation(values,BREADTH_WEIGHTS)
    enough=n>=MIN_OBSERVATION_STOCKS and coverage>=MIN_OBSERVATION_COVERAGE
    index_valid=closed_observation(index,current,holiday) if index else None
    idx=index_observation(index_valid)
    regime_values={}
    if breadth is not None:regime_values['breadth']=breadth
    for field in ('index_trend','index_momentum'):
        value=idx[field]
        if value is not None:regime_values[field]={'POSITIVE':100,'NEUTRAL':50,'NEGATIVE':0}[value]
    if idx['index_volatility'] is not None:regime_values['volatility']={'LOW':100,'NORMAL':75,'HIGH':25,'EXTREME':0}[idx['index_volatility']]
    regime,regime_debug=weighted_observation(regime_values,REGIME_WEIGHTS)
    warnings=[];reasons=[]
    conflict=(idx['index_trend']=='POSITIVE' and breadth is not None and breadth<40) or (idx['index_trend']=='NEGATIVE' and breadth is not None and breadth>=60)
    if conflict:warnings.append('Endeks pozitif ancak piyasa katılımı zayıf' if idx['index_trend']=='POSITIVE' else 'Endeks zayıf ancak piyasa genişliği toparlanıyor')
    if not enough:warnings.append('Geçerli hisse coverage düşük')
    if volume_coverage<MIN_VOLUME_COVERAGE:warnings.append('Hacim teyidi yetersiz')
    if idx['index_volatility'] in ('HIGH','EXTREME'):warnings.append('Volatilite yüksek')
    if not index_valid:warnings.append('Tamamlanmış endeks teknik verisi eksik')
    if breadth is not None and breadth<40:warnings.append('Piyasa katılımı zayıf')
    if n:reasons.append(f'Geçerli XUTUM hisselerinin %{100*advancing/n:.1f}\'i yükseliyor')
    for length in (20,50):
        value=percent['above_sma'+str(length)+'_pct']
        if value is not None:reasons.append(f'Hisselerin %{value:.1f}\'i SMA{length} üzerinde')
    if up_pct is not None:reasons.append(f'Yükselen hacim toplam hacmin %{up_pct:.1f}\'i')
    if new_high is not None and new_high>new_low:reasons.append('Yeni yüksekler yeni düşüklerden fazla')
    if idx['index_trend']=='POSITIVE':reasons.append('Endeks SMA20/SMA50 üzerinde')
    component_coverage=sum(BREADTH_WEIGHTS[k]*(n if k=='advances' else samples.get(k,0))/max(n,1) for k in values)
    index_coverage=sum(REGIME_WEIGHTS[k] for k in regime_values if k!='breadth')/(1-REGIME_WEIGHTS['breadth'])
    confidence=100*coverage*component_coverage*(.5+.5*index_coverage)*( .75 if conflict else 1)
    if not enough:confidence=min(confidence,35)
    day=expected_session(current,holiday)
    asof=datetime.combine(day,time(18,15),ISTANBUL).isoformat() if n else None
    return dict(engine_version=MEASUREMENT_VERSION,as_of=asof,created_at=current.isoformat(),
        market_open=market_open(current,holiday),data_status='GOOD' if enough and index_valid and len(values)==5 and component_coverage>=.8 else 'LIMITED' if n else 'INSUFFICIENT',
        regime=classification(regime,('STRONG_BULL','BULL','NEUTRAL','BEAR','STRONG_BEAR')) if enough and len(values)>=2 and len(regime_values)>=2 and confidence>=50 else None,
        regime_score=round(regime,2) if regime is not None else None,regime_confidence=round(confidence,2),
        breadth_score=round(breadth,2) if breadth is not None else None,
        breadth_state=classification(breadth,('VERY_STRONG','STRONG','NEUTRAL','WEAK','VERY_WEAK')) if enough and len(values)>=2 else None,
        advancing_count=advancing,declining_count=declining,unchanged_count=unchanged,valid_stock_count=n,
        universe_count=len(symbols),universe_source='XUTUM',coverage=coverage,
        advance_decline_ratio=advancing/declining if declining else None,advance_decline_net=advancing-declining,
        new_high_count=new_high,new_low_count=new_low,up_volume_pct=up_pct,down_volume_pct=down_pct,volume_coverage=volume_coverage,
        **percent,**idx,sample_counts=samples,breadth_components=debug,regime_components=regime_debug,
        risk_state=risk_class(idx['index_volatility'],breadth,100*declining/n if n else None,idx['index_momentum']) if enough else None,
        reasons=reasons,warnings=warnings,excluded_count=invalid+len(duplicates),final=enough and len(values)>=2 and len(regime_values)>=2 and confidence>=50)


def measurement_view(doc,current,holiday=None):
    import copy
    from performans_motoru import bist_holiday
    holiday=holiday or bist_holiday
    doc=copy.deepcopy(doc);at=stamp(doc.get('as_of'));created=stamp(doc.get('created_at'))
    if doc.get('engine_version')!=MEASUREMENT_VERSION or not created or created>current or (at and at>current):raise ValueError('Invalid/future market cache')
    if not isinstance(doc.get('warnings'),list) or not isinstance(doc.get('reasons'),list):raise ValueError('Market cache lists')
    for field in ('valid_stock_count','advancing_count','declining_count','unchanged_count'):
        if type(doc.get(field)) is not int or doc[field]<0:raise ValueError('Market cache counts')
    for field in ('regime_score','regime_confidence','breadth_score'):
        if doc.get(field) is not None and (number(doc[field]) is None or not 0<=doc[field]<=100):raise ValueError('Market cache score')
    stale=not at or at.date()!=expected_session(current,holiday)
    doc.update(market_open=market_open(current,holiday),stale=stale,data_age=(current-at).total_seconds()/60 if at else None)
    if stale:
        doc['regime_confidence']=0
        doc['warnings'].append('Veri güncelliği sınırlı')
    return doc


def frozen_market_context(doc,prediction_time):
    """Metadata only; refuse retrospectively constructed or future contexts."""
    current=stamp(prediction_time);at=stamp((doc or {}).get('as_of'));created=stamp((doc or {}).get('created_at'))
    if not current or not at or not created or at>current or created>current or doc.get('engine_version')!=MEASUREMENT_VERSION or not doc.get('final'):return {}
    if at.date()!=expected_session(current):return {}
    return {'market_regime':doc.get('regime'),'market_regime_score':doc.get('regime_score'),
        'market_breadth_score':doc.get('breadth_score'),'market_risk_state':doc.get('risk_state'),
        'market_context_as_of':doc['as_of'],'market_context_created_at':doc['created_at']}

# Sector observations extend this central context only; never feed effects().
SECTOR_VERSION='SECTOR_STRENGTH_V1'
SECTOR_HORIZONS=(1,5,20)
SECTOR_RS_WEIGHTS={1:.20,5:.35,20:.45}
SECTOR_RS_SCALES={1:2,5:5,20:10}
SECTOR_STATES=('LEADING','STRONG','NEUTRAL','WEAK','LAGGING')
RRG_STRENGTH_CUT=50
RRG_MOMENTUM_CUT=0
SECTOR_MIN_MEMBERS=5
SECTOR_MIN_COVERAGE=.60


def sector_enabled():
    return os.environ.get('SECTOR_STRENGTH_ENABLED','true').strip().lower() in ('true','1','yes','on')


def sector_universe(universe):
    from saglayici_sembolleri import bist_symbol
    output=set()
    for symbol in universe or []:
        if not isinstance(symbol,str):continue
        try:output.add(bist_symbol(symbol))
        except ValueError:continue
    return output


def sector_returns(raw):
    # Multi-session returns are calculated once from real, continuous closed bars.
    return {h:number((raw or {}).get(f'return_{h}d')) for h in SECTOR_HORIZONS}


def relative_score(values):
    # Fixed weights: missing long horizons never increase the 1d weight.
    # Null until both 5/20 session observations exist; 1d is at most 10 points.
    if any(number(values.get(h)) is None for h in (5,20)):return None,{}
    parts={str(h):SECTOR_RS_WEIGHTS[h]*clamp(values[h]/SECTOR_RS_SCALES[h],-1,1)*50
           for h in SECTOR_HORIZONS if number(values.get(h)) is not None}
    return round(clamp(50+sum(parts.values()),0,100),2),parts


def rrg_quadrant(score,momentum):
    if score is None or momentum is None:return None
    if score>=RRG_STRENGTH_CUT:return 'LEADING' if momentum>=RRG_MOMENTUM_CUT else 'WEAKENING'
    return 'IMPROVING' if momentum>=RRG_MOMENTUM_CUT else 'LAGGING'


def alignment(stock_score,sector,market):
    if stock_score is None or not sector or not market:return None
    if stock_score>=60 and sector in ('LEADING','STRONG') and market in ('BULL','STRONG_BULL'):
        return 'STRONG_ALIGNMENT' if stock_score>=80 and sector=='LEADING' and market=='STRONG_BULL' else 'POSITIVE_ALIGNMENT'
    if stock_score<40 and sector in ('WEAK','LAGGING') and market in ('BEAR','STRONG_BEAR'):return 'NEGATIVE_ALIGNMENT'
    return 'MIXED'


def sector_metrics(name,members,expected,index,current,official=None,holiday=None):
    n=len(members);coverage=n/expected if expected else 0
    sample={h:[sector_returns(r)[h] for r in members if sector_returns(r)[h] is not None] for h in SECTOR_HORIZONS}
    returns={h:mean(sample[h]) if len(sample[h])>=SECTOR_MIN_MEMBERS and len(sample[h])/max(expected,1)>=SECTOR_MIN_COVERAGE else None for h in SECTOR_HORIZONS}
    source='SYNTHETIC_MEMBERS';sector_benchmark=None
    if official:
        returns=sector_returns(official);source='OFFICIAL_INDEX';sector_benchmark=official['symbol']
    benchmark=sector_returns(index)
    relative={h:returns[h]-benchmark[h] if returns[h] is not None and benchmark[h] is not None else None for h in SECTOR_HORIZONS}
    score,components=relative_score(relative)
    sma={h:[r for r in members if number(r.get('sma'+str(h))) is not None and r['sma'+str(h)]>0] for h in (20,50)}
    above={h:100*sum(r['close']>r['sma'+str(h)] for r in sma[h])/len(sma[h]) if sma[h] else None for h in (20,50)}
    daily=[r for r in members if sector_returns(r)[1] is not None]
    up=sum(sector_returns(r)[1]>.01 for r in daily);down=sum(sector_returns(r)[1]<-.01 for r in daily)
    breadth=100*(up+.5*(len(daily)-up-down))/len(daily) if daily else None
    trend_samples=[index_observation(r)['index_trend'] for r in members]
    trend_samples=[v for v in trend_samples if v]
    trend_votes=[(1 if v=='POSITIVE' else -1 if v=='NEGATIVE' else 0) for v in trend_samples]
    if relative[20] is not None:trend_votes.append(1 if relative[20]>0 else -1 if relative[20]<0 else 0)
    trend_mean=mean(trend_votes) if len(trend_samples)>=2 else None
    trend='POSITIVE' if trend_mean is not None and trend_mean>=.35 else 'NEGATIVE' if trend_mean is not None and trend_mean<=-.35 else 'NEUTRAL' if trend_mean is not None else None
    # Per-session short vs long RS velocity. Independent SMA/breadth evidence
    # confirms momentum without claiming licensed JdK ratios.
    velocity=relative[5]/5-relative[20]/20 if relative[5] is not None and relative[20] is not None else None
    slopes=[number(r.get('sma20_slope'))/r['close']*100 for r in members if number(r.get('sma20_slope')) is not None]
    momentum_values=[]
    if velocity is not None:momentum_values.append(clamp(velocity/1,-1,1))
    if slopes:momentum_values.append(clamp(mean(slopes),-1,1))
    if breadth is not None:momentum_values.append((breadth-50)/50)
    momentum=mean(momentum_values) if velocity is not None and len(momentum_values)>=2 else None
    momentum_state=('STRONG' if score is not None and score>=60 else 'IMPROVING') if momentum is not None and momentum>.1 else ('WEAK' if score is not None and score<40 else 'WEAKENING') if momentum is not None and momentum<-.1 else 'NEUTRAL' if momentum is not None else None
    volume_rows=[r for r in daily if number(r.get('volume')) is not None and r['volume']>=0]
    total_volume=sum(r['volume'] for r in volume_rows)
    up_volume=sum(r['volume'] for r in volume_rows if sector_returns(r)[1]>.01)
    down_volume=sum(r['volume'] for r in volume_rows if sector_returns(r)[1]<-.01)
    volume_score=50+50*(up_volume-down_volume)/total_volume if total_volume>0 and len(volume_rows)>=SECTOR_MIN_MEMBERS and len(volume_rows)/max(expected,1)>=SECTOR_MIN_COVERAGE else None
    volume='STRONG' if volume_score is not None and volume_score>=60 else 'WEAK' if volume_score is not None and volume_score<40 else 'NORMAL' if volume_score is not None else None
    values={'rs':score,'trend':100 if trend=='POSITIVE' else 0 if trend=='NEGATIVE' else 50 if trend else None,
            'momentum':50+50*momentum if momentum is not None else None,'breadth':breadth,'volume':volume_score}
    state_score,state_components=weighted_observation(values,{'rs':.45,'trend':.20,'momentum':.15,'breadth':.15,'volume':.05})
    sma_coverage=min(len(sma[20]),len(sma[50]))/max(expected,1)
    horizon_coverage=min(len(sample[h]) for h in SECTOR_HORIZONS)/max(expected,1)
    confidence=100*(.40*coverage+.20*sma_coverage+.15*len(volume_rows)/max(expected,1)+.15*horizon_coverage+.10*sum(v is not None for v in benchmark.values())/3)
    conflict=score is not None and trend in ('POSITIVE','NEGATIVE') and ((score>=60 and trend=='NEGATIVE') or (score<40 and trend=='POSITIVE'))
    if conflict:confidence*=.8
    enough=n>=SECTOR_MIN_MEMBERS and coverage>=SECTOR_MIN_COVERAGE and horizon_coverage>=SECTOR_MIN_COVERAGE and name!='UNKNOWN' and score is not None and len(state_components)>=3
    if not enough:confidence=min(confidence,40)
    state=classification(state_score,SECTOR_STATES) if enough and confidence>=50 else None
    reasons=[];warnings=[]
    for h in SECTOR_HORIZONS:
        if relative[h] is not None:reasons.append(f'Sektör son {h} seansta XU100\'e göre {relative[h]:+.2f} puan')
    if above[20] is not None:reasons.append(f'Sektör üyelerinin %{above[20]:.1f}\'i SMA20 üzerinde')
    if momentum_state in ('IMPROVING','STRONG'):reasons.append('Relatif momentum iyileşiyor')
    if momentum_state in ('WEAKENING','WEAK'):warnings.append('Sektör momentumu zayıflıyor')
    if not enough:warnings.append('Sektör ölçüm kapsamı yetersiz')
    if any(v is None for v in benchmark.values()):warnings.append('Benchmark verisi eksik')
    if volume is None:warnings.append('Hacim teyidi yetersiz')
    if conflict:warnings.append('Trend ve relatif güç çelişiyor')
    if name=='UNKNOWN':warnings.append('Sektör eşleşmesi bulunamadı')
    result={'sector_code':sector_code(name),'sector_name':name,'benchmark':'XU100','sector_benchmark':sector_benchmark,
        'benchmark_source':source,'as_of':datetime.combine(expected_session(current,holiday),time(18,15),ISTANBUL).isoformat(),
        'data_status':'COMPLETE' if enough else 'INSUFFICIENT','member_count':expected,'valid_member_count':n,'coverage_pct':round(100*coverage,2),
        'relative_strength_score':score,'relative_strength_components':components,'momentum_state':momentum_state,'relative_momentum':momentum,
        'trend_state':trend,'breadth_state':classification(breadth,('VERY_STRONG','STRONG','NEUTRAL','WEAK','VERY_WEAK')),
        'above_sma20_pct':above[20],'above_sma50_pct':above[50],'advancing_count':up if daily else None,
        'declining_count':down if daily else None,'unchanged_count':len(daily)-up-down if daily else None,'volume_strength':volume,
        'sector_state':state,'sector_state_score':state_score,'sector_state_components':state_components,'sector_confidence':round(min(100,confidence),2),
        'rrg_quadrant':rrg_quadrant(score,momentum) if enough else None,'reasons':reasons,'warnings':warnings,'engine_version':SECTOR_VERSION,
        'sample_counts':{'sma20':len(sma[20]),'sma50':len(sma[50]),'daily':len(daily),'volume':len(volume_rows),**{f'return_{h}d':len(sample[h]) for h in SECTOR_HORIZONS}}}
    for h in SECTOR_HORIZONS:result.update({f'sector_return_{h}d':returns[h],f'benchmark_return_{h}d':benchmark[h],f'relative_strength_{h}d':relative[h]})
    return result


def sector_code(name):return 'UNKNOWN' if name=='UNKNOWN' else 'S_'+hashlib.sha256(name.encode('utf-8')).hexdigest()[:12].upper()


def build_sectors(rows,universe,mapping,index,current,official=None,market=None,holiday=None):
    current=current.astimezone(ISTANBUL);universe=sector_universe(universe);valid={};duplicates=set();groups={}
    for symbol in sorted(universe):
        name=mapping.get(symbol) or 'UNKNOWN'
        if name in ('BILINMIYOR','UNKNOWN'):name='UNKNOWN'
        groups.setdefault(name,[]).append(symbol)
    for row in rows:
        if not isinstance(row,dict):continue
        raw=closed_observation(row,current,holiday)
        if not raw or raw['symbol'] not in universe:continue
        raw.update({k:number(raw.get(k)) for k in ('sma20','sma50','sma20_slope','volume','return_1d','return_5d','return_20d','return_3d','macd_histogram','rsi')})
        symbol=raw['symbol']
        if symbol in valid and raw!=valid[symbol]:duplicates.add(symbol)
        valid[symbol]=raw
    for symbol in duplicates:valid.pop(symbol,None)
    idx=closed_observation(index or {},current,holiday) or {}
    if idx.get('symbol')!='XU100':idx={}
    market_ref=frozen_market_context(market or {},current)
    sectors=[];stocks={};failures=[]
    for name,symbols in sorted(groups.items()):
        members=[valid[s] for s in symbols if s in valid]
        try:
            official_row=(official or {}).get(name) or {}
            official_raw=closed_observation(official_row.get('observation',{}),current,holiday)
            official_members=sector_universe(official_row.get('members',[]))
            if not official_row.get('verified') or official_members!=set(symbols) or not sector_history_usable(official_raw):official_raw=None
            sector=sector_metrics(name,members,len(symbols),idx,current,official_raw,holiday)
            sectors.append(sector)
            for symbol in symbols:
                raw=valid.get(symbol,{});returns=sector_returns(raw)
                differences={h:returns[h]-sector[f'sector_return_{h}d'] if returns[h] is not None and sector[f'sector_return_{h}d'] is not None else None for h in SECTOR_HORIZONS}
                score,components=relative_score(differences) if name!='UNKNOWN' else (None,{})
                context={'symbol':symbol,'sector_code':sector['sector_code'],'sector_name':name,'as_of':sector['as_of'],
                    'stock_relative_strength_score':score,'relative_strength_components':components,'sector_state':sector['sector_state'],
                    'sector_relative_strength_score':sector['relative_strength_score'],'sector_rrg_quadrant':sector['rrg_quadrant'],
                    'alignment_state':alignment(score,sector['sector_state'],market_ref.get('market_regime')),
                    'reasons':[],'warnings':list(sector['warnings'])}
                for h in SECTOR_HORIZONS:context.update({f'stock_return_{h}d':returns[h],f'sector_return_{h}d':sector[f'sector_return_{h}d'],f'vs_sector_{h}d':differences[h]})
                if differences[5] is not None:context['reasons'].append(f'Hisse son 5 seansta sektörüne göre {differences[5]:+.2f} puan')
                if score is not None and score<40 and sector['sector_state'] in ('LEADING','STRONG'):context['warnings'].append('Sektör güçlü ancak hisse sektörün gerisinde')
                stocks[symbol]=context
            ranked=sorted([stocks[s] for s in symbols if stocks[s]['stock_relative_strength_score'] is not None],key=lambda v:(-v['stock_relative_strength_score'],v['symbol']))
            sector['top_stocks']=[{'symbol':v['symbol'],'score':v['stock_relative_strength_score']} for v in ranked[:5]]
            sector['lagging_stocks']=[{'symbol':v['symbol'],'score':v['stock_relative_strength_score']} for v in sorted(ranked,key=lambda v:(v['stock_relative_strength_score'],v['symbol']))[:5]]
        except Exception as error:
            from gorev_hatalari import log_source,describe
            log_source(error,'SECTOR_STRENGTH');failures.append({'sector_code':sector_code(name),'issue':describe(error,'SECTOR_STRENGTH')})
    sectors.sort(key=lambda s:(s['relative_strength_score'] is None,-(s['relative_strength_score'] or 0),SECTOR_STATES.index(s['sector_state']) if s['sector_state'] in SECTOR_STATES else 5,-s['sector_confidence'],s['sector_code']))
    return {'engine_version':SECTOR_VERSION,'as_of':datetime.combine(expected_session(current,holiday),time(18,15),ISTANBUL).isoformat(),
        'created_at':current.isoformat(),'universe_source':'XUTUM','universe_count':len(universe),'sectors':sectors,'stocks':stocks,
        'market_context':market_ref,'failures':failures,'warnings':['Bir veya daha fazla sektör ölçülemedi'] if failures else [],
        'final':bool(sectors) and not failures and all(s['data_status']=='COMPLETE' for s in sectors if s['sector_name']!='UNKNOWN' and s['member_count']>=SECTOR_MIN_MEMBERS)
                and any(s['data_status']=='COMPLETE' for s in sectors)}


def sector_view(doc,current,holiday=None):
    import copy
    doc=copy.deepcopy(doc);at=stamp(doc.get('as_of'));created=stamp(doc.get('created_at'))
    if doc.get('engine_version')!=SECTOR_VERSION or not at or not created or created<at or at>current or created>current:raise ValueError('Invalid sector cache time')
    if not isinstance(doc.get('sectors'),list) or not isinstance(doc.get('stocks'),dict) or not isinstance(doc.get('warnings'),list):raise ValueError('Invalid sector cache structure')
    for sector in doc['sectors']:
        for key in ('sector_code','sector_name','data_status'):
            if not isinstance(sector.get(key),str):raise ValueError('Invalid sector identity')
        for key in ('member_count','valid_member_count'):
            if type(sector.get(key)) is not int or sector[key]<0:raise ValueError('Invalid sector count')
        for key in ('relative_strength_score','sector_confidence'):
            if sector.get(key) is not None and (number(sector[key]) is None or not 0<=sector[key]<=100):raise ValueError('Invalid sector score')
        if not isinstance(sector.get('warnings'),list) or not isinstance(sector.get('reasons'),list):raise ValueError('Invalid sector explanations')
    codes={s['sector_code'] for s in doc['sectors']}
    for symbol,stock in doc['stocks'].items():
        if not isinstance(stock,dict) or stock.get('symbol')!=symbol or stock.get('sector_code') not in codes:raise ValueError('Invalid stock-sector cache')
        if not isinstance(stock.get('warnings'),list) or not isinstance(stock.get('reasons'),list):raise ValueError('Invalid stock-sector explanations')
        if stock.get('stock_relative_strength_score') is not None and (number(stock['stock_relative_strength_score']) is None or not 0<=stock['stock_relative_strength_score']<=100):raise ValueError('Invalid stock-sector score')
    stale=at.date()!=expected_session(current,holiday);doc['stale']=stale
    doc['data_age']=(current-at).total_seconds()/60
    if stale:
        doc['warnings'].append('Snapshot eski')
        for s in doc['sectors']:s['sector_confidence']=0;s['warnings'].append('Snapshot eski')
        for s in doc['stocks'].values():s['warnings'].append('Snapshot eski');s['alignment_state']=None
    return doc


def frozen_sector_context(doc,symbol,prediction_time):
    current=stamp(prediction_time);at=stamp((doc or {}).get('as_of'));created=stamp((doc or {}).get('created_at'))
    if not current or not at or not created or at>current or created>current or doc.get('engine_version')!=SECTOR_VERSION or not doc.get('final'):return {}
    if at.date()!=expected_session(current):return {}
    stock=doc.get('stocks',{}).get(symbol)
    if not stock or stock['sector_name']=='UNKNOWN':return {}
    return {'sector_code':stock['sector_code'],'sector_state':stock['sector_state'],
        'sector_relative_strength_score':stock['sector_relative_strength_score'],'sector_rrg_quadrant':stock['sector_rrg_quadrant'],
        'stock_vs_sector_score':stock['stock_relative_strength_score'],'market_sector_alignment':stock['alignment_state'],
        'sector_context_as_of':doc['as_of'],'sector_context_created_at':doc['created_at']}


def stock_sector_view(symbol,location=None,current=None):
    if not sector_enabled():return None
    from kullanici_kayitlari import RecordError
    try:
        doc=PiyasaBaglami(location,clock=(lambda:current) if current else None).sectors({'symbol':[symbol]})
        return dict(doc['stock_sector_context'],stale=doc['stale'])
    except RecordError:return None


def sector_indices(location,universe,mapping,current,holiday=None):
    """Bounded provider-catalogue discovery; verify exact equity membership.

    Names are not guessed/translated into index codes. Broad metadata sectors
    without an exact supported-index membership use synthetic returns.
    Two component requests per five-minute round; each entry cached seven days.
    Matched index history is read once per closed session, compact summary only.
    """
    from gorev_hatalari import log_source,describe
    from saglayici_sembolleri import bist_symbol
    from teknik_gostergeler import calculate
    import bist_bot
    target=location.runtime/'sector_index_discovery.json'
    issues=[];official={}
    with locked(target):
        doc=load(target,{'cursor':0,'entries':{}})
        if not isinstance(doc,dict) or not isinstance(doc.get('entries'),dict):raise ValueError('Sector index discovery format')
        catalogue=sorted(set(bist_bot.bp.indices()))[:64]
        # General equity indices are not sector benchmarks.
        catalogue=[s for s in catalogue if s not in ('XU100','XU050','XU030','XUTUM')]
        entries=doc['entries'];at=stamp(doc.get('checked_at'))
        if at and at>current:raise ValueError('Future sector catalogue cache')
        if len(entries)>64:raise ValueError('Sector catalogue bounds')
        if not at or (current-at).total_seconds()>=300:
            cursor=doc.get('cursor',0)
            if type(cursor) is not int:raise ValueError('Sector index cursor')
            for _ in range(min(2,len(catalogue))):
                code=catalogue[cursor%len(catalogue)];cursor+=1;cached=entries.get(code,{})
                checked=stamp(cached.get('verified_at'))
                if checked and 0<=(current-checked).total_seconds()<7*86400:continue
                try:
                    components=bist_bot.bp.Index(code).components
                    symbols=sorted({bist_symbol(r['symbol']) for r in components if isinstance(r,dict) and isinstance(r.get('symbol'),str)})
                    if symbols:entries[code]={'members':symbols,'verified_at':current.isoformat()}
                    else:issues.append({'code':'PROVIDER_DATA','symbol':code,'stage':'INDEX_MEMBERSHIP'})
                except Exception as error:log_source(error,'PROVIDER');issues.append(dict(describe(error,'PROVIDER'),symbol=code,stage='INDEX_MEMBERSHIP'))
            doc.update(cursor=cursor,checked_at=current.isoformat());atomic_json(target,doc)
        groups={}
        for symbol in universe:
            name=mapping.get(symbol)
            if name and name not in ('BILINMIYOR','UNKNOWN'):groups.setdefault(name,set()).add(symbol)
        history_requests=0
        for name,symbols in sorted(groups.items()):
            matches=[(code,entry) for code,entry in entries.items() if code in catalogue and len(symbols)>=SECTOR_MIN_MEMBERS
                and sector_universe(entry.get('members',[]))==symbols and stamp(entry.get('verified_at'))
                and 0<=(current-stamp(entry['verified_at'])).total_seconds()<7*86400]
            if not matches:continue
            code,entry=sorted(matches)[0];observation=entry.get('observation',{})
            if not sector_history_usable(closed_observation(observation,current,holiday)):
                if history_requests>=2:continue
                history_requests+=1
                try:
                    frame=bist_bot.bp.Index(code).history(period='6mo')
                    observation={'sembol':code,'teknik_gostergeler':calculate(frame,current,'TOMORROW')}
                    if not sector_history_usable(closed_observation(observation,current,holiday)):
                        issues.append({'code':'PROVIDER_DATA','symbol':code,'stage':'INDEX_HISTORY'});continue
                    entry['observation']=observation;atomic_json(target,doc)
                except Exception as error:log_source(error,'PROVIDER');issues.append(dict(describe(error,'PROVIDER'),symbol=code,stage='INDEX_HISTORY'));continue
            official[name]={'verified':True,'members':sorted(symbols),'observation':observation}
    return official,issues


def sector_history_usable(raw):
    return bool(raw) and all(number(raw.get(f'return_{h}d')) is not None for h in SECTOR_HORIZONS)


def sector_benchmark(location,current,holiday=None):
    """Upgrade legacy/missing XU100 summary once; reuse the same compact cache.

    Market Regime's final archive may already exist and therefore deliberately
    bypass its refresh path. This cache upgrade never touches that archive.
    """
    from gorev_hatalari import describe,log_source
    from teknik_gostergeler import calculate
    target=location.runtime/'market_context_index.json'
    with locked(target):
        index=load(target,{})
        raw=closed_observation(index,current,holiday)
        if raw and raw['symbol']=='XU100' and sector_history_usable(raw):return index,None
        import bist_bot
        try:
            frame=bist_bot.bp.Index('XU100').history(period='6mo')
            index={'sembol':'XU100','teknik_gostergeler':calculate(frame,current,'TOMORROW')}
            if not sector_history_usable(closed_observation(index,current,holiday)):
                return {},{'code':'PROVIDER_DATA','symbol':'XU100','stage':'BENCHMARK_HISTORY'}
        except Exception as error:
            log_source(error,'PROVIDER')
            return {},dict(describe(error,'PROVIDER'),symbol='XU100',stage='BENCHMARK_HISTORY')
        atomic_json(target,index)
        return index,None


def sector_bootstrap(location,rows,universe,mapping,current,enqueue,holiday=None):
    """At most ten rotating symbols, through existing priority queue/providers.

    No direct stock history request and no fabricated update of public analyses.
    The normal priority callback writes real analysis results. Recheck every round
    so permanent provider/data failures stay visible rather than becoming fake OK.
    """
    observations={}
    for row in rows:
        if not isinstance(row,dict):continue
        raw=closed_observation(row,current,holiday)
        if raw:observations[raw['symbol']]=raw
    missing=sorted(s for s in universe if mapping.get(s) not in (None,'','UNKNOWN','BILINMIYOR')
                   and not sector_history_usable(observations.get(s)))
    if not missing:return 0
    path=location.runtime/'sector_bootstrap_state.json'
    with locked(path):
        state=load(path,{'cursor':None})
        if not isinstance(state,dict):raise ValueError('Sector bootstrap state format')
        cursor=state.get('cursor');at=stamp(state.get('queued_at'))
        if at and at>current:raise ValueError('Future sector bootstrap state')
        if at and (current-at).total_seconds()<300:return 0
        if cursor is not None and not isinstance(cursor,str):raise ValueError('Sector bootstrap cursor')
        after=[s for s in missing if cursor is None or s>cursor]
        selected=(after+[s for s in missing if cursor is not None and s<=cursor])[:10]
        for symbol in selected:enqueue(symbol,gun_ici_yenile=False)
        atomic_json(path,{'cursor':selected[-1],'queued_at':current.isoformat()})
    return len(selected)


def sector_trace(stage,doc,universe,mapping,issue=None,queued=0):
    import logging
    sectors=doc.get('sectors',[])
    sources=','.join(sorted({v.get('benchmark_source','UNKNOWN') for v in sectors})) or 'NONE'
    logging.info('[SECTOR_TRACE] stage=%s benchmark_source=%s valid_sector_count=%d xutum_member_count=%d mapped_member_count=%d usable_history_count=%d code=%s queued=%d',
        stage,sources,sum(v.get('data_status')=='COMPLETE' and v.get('sector_state') is not None for v in sectors),len(universe),
        sum(mapping.get(s) not in (None,'','UNKNOWN','BILINMIYOR') for s in universe),
        sum(all(number(stock.get(f'stock_return_{h}d')) is not None for h in SECTOR_HORIZONS) for stock in doc.get('stocks',{}).values()),issue.get('code','NONE') if issue else 'NONE',queued)
