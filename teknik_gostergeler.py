"""Provider-free closed-candle indicator definitions, frozen evidence and shadow-only effects."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import copy
import math
import os
import pandas as pd

ISTANBUL=ZoneInfo('Europe/Istanbul')
MODEL='STD_TECH_V1'
CRITERIA=('VWAP_USTU','VWAP_RECLAIM','OBV_POZITIF_TREND','OBV_KIRILIM','OBV_POZITIF_UYUMSUZLUK',
          'OBV_NEGATIF_UYUMSUZLUK','BOLLINGER_SIKISMA_KIRILIM','BOLLINGER_BANDA_DONUS',
          'MOMENTUM_GUCLENME','MOMENTUM_ZAYIFLAMA')


def finite(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def aware(value):
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value)
        except ValueError:return None
    return value.astimezone(ISTANBUL) if isinstance(value,datetime) and value.tzinfo else None


def ema(close,span):return close.ewm(span=span,adjust=False).mean()


def rsi(close,period=14,zero_policy='STANDARD'):
    delta=close.diff();gain=delta.clip(lower=0).rolling(period).mean();loss=(-delta.clip(upper=0)).rolling(period).mean()
    result=100-100/(1+gain/loss.replace(0,float('nan')))
    if zero_policy=='STANDARD':
        result=result.mask((loss==0)&(gain>0),100).mask((loss==0)&(gain==0),50)
    return result


def macd(close):
    line=ema(close,12)-ema(close,26);signal=ema(line,9)
    return line,signal,line-signal


def bollinger_series(close):
    middle=close.rolling(20).mean();std=close.rolling(20).std(ddof=1)
    return middle,middle+2*std,middle-2*std


def obv_series(close,volume):
    delta=close.diff();signed=volume*0.0
    signed[delta>0]=volume[delta>0];signed[delta<0]=-volume[delta<0]
    return signed.cumsum()


def vwap_series(frame,window=None):
    typical=(frame['High']+frame['Low']+frame['Close'])/3
    pv=typical*frame['Volume'];volume=frame['Volume']
    total=pv.rolling(window).sum() if window else pv.cumsum()
    denominator=volume.rolling(window).sum() if window else volume.cumsum()
    return total/denominator.replace(0,float('nan'))


def momentum_series(close,period=3):return (close/close.shift(period)-1)*100


def closed_frame(data,asof,mode='INTRADAY'):
    """5m timestamps are bar starts; daily timestamps become available at 18:10."""
    current=aware(asof)
    if current is None:raise ValueError('Aware signal time required')
    if mode not in ('INTRADAY','TOMORROW'):raise ValueError('Unknown indicator mode')
    if data is None or not isinstance(data,pd.DataFrame) or data.empty:return pd.DataFrame()
    frame=data.copy()
    if not isinstance(frame.index,pd.DatetimeIndex):return pd.DataFrame()
    index=frame.index.tz_localize(ISTANBUL) if frame.index.tz is None else frame.index.tz_convert(ISTANBUL)
    frame.index=index
    available=index+pd.Timedelta(minutes=5) if mode=='INTRADAY' else index.normalize()+pd.Timedelta(hours=18,minutes=10)
    allowed=available<=current
    if 'available_at' in frame:
        observed=pd.to_datetime(frame['available_at'],utc=True,errors='coerce')
        allowed=allowed & (observed<=current)
    frame=frame.loc[allowed].sort_index(kind='stable')
    frame=frame.loc[~frame.index.duplicated(keep='first')]
    for name in ('Open','High','Low','Close','Volume'):
        frame[name]=pd.to_numeric(frame[name],errors='coerce') if name in frame else float('nan')
    frame=frame.replace([float('inf'),float('-inf')],float('nan'))
    # Do not remove gaps and compress the time axis; quality is per indicator.
    frame['_available_at']=frame.index+pd.Timedelta(minutes=5) if mode=='INTRADAY' else frame.index.normalize()+pd.Timedelta(hours=18,minutes=10)
    if 'available_at' in frame:
        observed=pd.to_datetime(frame['available_at'],utc=True,errors='coerce').dt.tz_convert(ISTANBUL)
        frame['_available_at']=frame['_available_at'].where(frame['_available_at']>=observed,observed)

    return frame


def stale_at(data_time,current,mode):
    observed=aware(data_time);current=aware(current)
    if observed is None or current is None or observed>current:return True
    if mode=='INTRADAY':return (current-observed).total_seconds()>1200
    expected=current.date()
    if current.time()<time(18,10):expected-=timedelta(days=1)
    while expected.weekday()>4:expected-=timedelta(days=1)
    return observed.date()<expected


def calculate(data,asof,mode='INTRADAY'):
    current=aware(asof);frame=closed_frame(data,asof,mode)
    observed=frame['_available_at'].iloc[-1].to_pydatetime() if len(frame) else None
    stale=stale_at(observed,current,mode)
    close=frame.get('Close',pd.Series(dtype=float));volume=frame.get('Volume',pd.Series(dtype=float))
    count=len(frame);price=finite(close.iloc[-1]) if count else None
    def group(ok,reason,**values):
        return dict(status='OK' if ok else 'UNKNOWN',reason=None if ok else reason,
                    confidence=(35 if stale else 100) if ok else 0,stale=stale,**values)
    obv_ok=count>=4 and close.notna().all() and volume.notna().all() and (volume>=0).all() and volume.sum()>0
    obv=obv_series(close,volume) if obv_ok else pd.Series(dtype=float)
    delta=finite(obv.iloc[-1]-obv.iloc[-4]) if obv_ok else None
    tolerance=float(volume.tail(4).mean())*.005 if obv_ok else 0
    trend='OBV_YUKSELEN' if delta is not None and delta>tolerance else 'OBV_DUSEN' if delta is not None and delta<-tolerance else 'OBV_YATAY' if obv_ok else 'UNKNOWN'
    breakout=None;divergence=None
    if obv_ok:
        divergence='POZITIF_UYUMSUZLUK' if close.iloc[-1]<close.iloc[-4] and delta>tolerance else 'NEGATIF_UYUMSUZLUK' if close.iloc[-1]>close.iloc[-4] and delta<-tolerance else 'YOK'
        if count>=21:
            previous=obv.iloc[-21:-1]
            breakout='OBV_KIRILIM_POZITIF' if obv.iloc[-1]>previous.max() else 'OBV_KIRILIM_NEGATIF' if obv.iloc[-1]<previous.min() else 'YOK'
    obv_result=group(obv_ok,'VOLUME_MISSING_OR_TOO_FEW_BARS',value=finite(obv.iloc[-1]) if obv_ok else None,
                     trend=trend,short_slope=delta/3 if delta is not None else None,breakout=breakout,divergence=divergence)
    session=frame.loc[frame.index.date==frame.index[-1].date()] if count else frame
    contiguous=len(session)>=2 and session.index[0].time()==time(10) and all((session.index[i]-session.index[i-1]).total_seconds()==300 for i in range(1,len(session)))
    vwap_ok=contiguous and mode=='INTRADAY' and len(session)>=2 and session[['High','Low','Close','Volume']].notna().all().all() and (session['Volume']>=0).all() and session['Volume'].sum()>0
    vwap=vwap_series(session) if vwap_ok else pd.Series(dtype=float)
    vw=finite(vwap.iloc[-1]) if vwap_ok else None
    distance=(price/vw-1)*100 if price is not None and vw and vw>0 else None
    position='VWAP_YAKIN' if distance is not None and abs(distance)<=.1 else 'VWAP_USTU' if distance is not None and distance>0 else 'VWAP_ALTI' if distance is not None else 'UNKNOWN'
    transition='VWAP_RECLAIM' if vwap_ok and session['Close'].iloc[-2]<=vwap.iloc[-2] and price>vw else 'VWAP_KAYBI' if vwap_ok and session['Close'].iloc[-2]>=vwap.iloc[-2] and price<vw else 'YOK' if vwap_ok else None
    reference=finite(vwap_series(frame,20).iloc[-1]) if count>=20 and frame[['High','Low','Close','Volume']].tail(20).notna().all().all() and (volume.tail(20)>=0).all() else None
    vwap_result=group(vwap_ok,'INTRADAY_REQUIRED' if mode=='TOMORROW' else 'VOLUME_MISSING_OR_SESSION_INCOMPLETE',
                      session_value=vw,position=position,distance_pct=distance,transition=transition,
                      slope=finite(vwap.iloc[-1]-vwap.iloc[-2]) if vwap_ok else None,reference_20=reference,
                      reference_type='20_BAR_VOLUME_WEIGHTED_REFERENCE_NOT_SESSION')
    bb_ok=count>=20 and close.tail(21).notna().all() and price is not None and price>0
    middle,upper,lower=bollinger_series(close)
    mid=finite(middle.iloc[-1]) if bb_ok else None;up=finite(upper.iloc[-1]) if bb_ok else None;low=finite(lower.iloc[-1]) if bb_ok else None
    width=(up-low)/mid*100 if mid and mid>0 else None
    prev_up=finite(upper.iloc[-2]) if count>=21 else None;prev_low=finite(lower.iloc[-2]) if count>=21 else None
    prev_mid=finite(middle.iloc[-2]) if count>=21 else None
    prev_width=(prev_up-prev_low)/prev_mid*100 if prev_mid and prev_mid>0 else None
    upper_break=bool(price>up and close.iloc[-2]<=prev_up) if bb_ok and prev_up is not None else None
    lower_break=bool(price<low and close.iloc[-2]>=prev_low) if bb_ok and prev_low is not None else None
    inside=bool(low<=price<=up and (close.iloc[-2]>prev_up or close.iloc[-2]<prev_low)) if bb_ok and prev_up is not None else None
    bb_result=group(bb_ok,'TOO_FEW_BARS_OR_MISSING_CLOSE',upper=up,middle=mid,lower=low,width_pct=width,
                    squeeze=bool(width<=5) if width is not None else None,expansion=bool(width>prev_width*1.1) if prev_width is not None else None,
                    upper_break=upper_break,lower_break=lower_break,return_inside=inside,
                    middle_position='USTUNDE' if mid is not None and price>mid else 'ALTINDA' if mid is not None and price<mid else 'ESIT' if mid is not None else 'UNKNOWN')
    mom_ok=count>=5 and close.tail(5).notna().all() and (close.tail(5)>0).all()
    momentum=momentum_series(close,3)
    short=finite(momentum.iloc[-1]) if mom_ok else None;previous=finite(momentum.iloc[-2]) if mom_ok else None
    acceleration=short-previous if mom_ok else None
    direction='POZITIF' if short is not None and short>.05 else 'NEGATIF' if short is not None and short<-.05 else 'NOTR' if mom_ok else 'UNKNOWN'
    state='GUCLENIYOR' if mom_ok and acceleration>.05 else 'ZAYIFLIYOR' if mom_ok and acceleration<-.05 else 'NOTR' if mom_ok else 'UNKNOWN'
    candle=frame.iloc[-1] if count else {}
    high,low_price,opening=(finite(candle.get(k)) for k in ('High','Low','Open'))
    close_position=(price-low_price)/(high-low_price)*100 if price is not None and high is not None and low_price is not None and high>low_price else None
    mom_result=group(mom_ok,'TOO_FEW_BARS_OR_MISSING_CLOSE',short_pct=short,period_bars=3,direction=direction,state=state,
                     slope=(price-close.iloc[-4])/3 if mom_ok else None,acceleration=acceleration,
                     positive_turn=bool(previous<=0<short) if mom_ok else None,negative_turn=bool(previous>=0>short) if mom_ok else None,
                     last_candle='POZITIF' if price is not None and opening is not None and price>opening else 'NEGATIF' if price is not None and opening is not None and price<opening else 'NOTR' if price is not None and opening is not None else 'UNKNOWN',close_position_pct=close_position)
    ratio=float(volume.iloc[-1]/volume.iloc[-21:-1].mean()*100) if count>=21 and volume.iloc[-21:].notna().all() and volume.iloc[-21:-1].mean()>0 else None
    combo=bool(prev_width<=5 and upper_break and ratio>=130 and short>0) if prev_width is not None and upper_break is not None and ratio is not None and short is not None else None
    # Closing summary reuses this already filtered OHLCV window; no second provider call.
    closing={}
    if mode=='TOMORROW' and count>=2:
        last_volume=finite(volume.iloc[-1]);previous_volume=finite(volume.iloc[-2])
        closing={'turnover_tl':price*last_volume if price and last_volume is not None else None,
                 'volume_acceleration':last_volume/previous_volume-1 if previous_volume and last_volume is not None else None,
                 'return_3d':short,'ema9':finite(ema(close,9).iloc[-1]),'ema21':finite(ema(close,21).iloc[-1]),
                 'open':opening,'high':high,'low':low_price,'close':price,
                 'previous_close':finite(close.iloc[-2])}
    # Additional closed-daily observations only: existing shadow/score groups unchanged.
    if mode=='TOMORROW' and count>=2:
        previous_highs=frame['High'].iloc[-21:-1];previous_lows=frame['Low'].iloc[-21:-1]
        true_range=pd.concat([frame['High']-frame['Low'],(frame['High']-close.shift(1)).abs(),(frame['Low']-close.shift(1)).abs()],axis=1).max(axis=1)
        atr_series=true_range.rolling(14,min_periods=14).mean()
        atr_percent=atr_series/close*100
        _,_,histogram=macd(close)
        avg20=close.rolling(20,min_periods=20).mean()
        closing.update(volume=finite(volume.iloc[-1]) if finite(volume.iloc[-1]) is not None and volume.iloc[-1]>=0 else None,
            sma20=finite(avg20.iloc[-1]),sma50=finite(close.rolling(50,min_periods=50).mean().iloc[-1]),
            sma20_slope=finite(avg20.iloc[-1]-avg20.iloc[-4]) if count>=23 else None,
            previous20_high=finite(previous_highs.max()) if len(previous_highs)==20 and previous_highs.notna().all() else None,
            previous20_low=finite(previous_lows.min()) if len(previous_lows)==20 and previous_lows.notna().all() else None,
            atr14=finite(atr_series.iloc[-1]),atr_pct=finite(atr_percent.iloc[-1]),
            atr_pct_baseline=finite(atr_percent.iloc[-61:-1].median()) if count>=40 else None,
            rsi=finite(rsi(close).iloc[-1]) if count>=15 else None,
            macd_histogram=finite(histogram.iloc[-1]) if count>=35 else None)
    bb_result['squeeze_volume_momentum_break']=combo
    groups={'obv':obv_result,'vwap':vwap_result,'bollinger':bb_result,'momentum':mom_result}
    available=[g['confidence'] for g in groups.values() if g['status']=='OK']
    return dict(model=MODEL,mode=mode,asof=current.isoformat(),data_time=observed.isoformat() if observed else None,
                stale=stale,confidence=sum(available)/len(available) if available else 0,bar_count=count,
                volume_ratio=ratio,closing=closing,**groups)


def snapshot(record):
    for obj in (record,record.get('analiz') or {},record.get('kriterler') or {},record.get('girdiler') or {},record.get('tahmin') or {}):
        if isinstance(obj,dict) and isinstance(obj.get('teknik_gostergeler'),dict):return obj['teknik_gostergeler']
    return {}


def view(record,current):
    result=copy.deepcopy(snapshot(record));at=aware(result.get('asof'));current=aware(current)
    if not result:return {}
    if at is None or current is None or at>current or stale_at(result.get('data_time'),current,result.get('mode')):
        result['stale']=True;result['confidence']=min(35,result.get('confidence',0))
        for name in ('obv','vwap','bollinger','momentum'):
            if isinstance(result.get(name),dict):result[name].update(stale=True,confidence=min(35,result[name].get('confidence',0)))
    return result


def features(record):
    doc=snapshot(record);signal=record.get('sinyal_zamani') or record.get('zaman') or (record.get('tahmin') or {}).get('tahmin_zamani') or doc.get('asof')
    current=aware(signal);at=aware(doc.get('asof'))
    unknown={k:None for k in CRITERIA}
    if not current or not at or at>current or doc.get('stale') or stale_at(doc.get('data_time'),current,doc.get('mode')):return unknown
    def ok(name):return doc.get(name,{}).get('status')=='OK' and doc[name].get('confidence',0)>=50
    vw,obv,bb,mom=(doc.get(k,{}) for k in ('vwap','obv','bollinger','momentum'))
    return {'VWAP_USTU':vw.get('position')=='VWAP_USTU' if ok('vwap') else None,
            'VWAP_RECLAIM':vw.get('transition')=='VWAP_RECLAIM' if ok('vwap') else None,
            'OBV_POZITIF_TREND':obv.get('trend')=='OBV_YUKSELEN' if ok('obv') else None,
            'OBV_KIRILIM':obv.get('breakout')=='OBV_KIRILIM_POZITIF' if ok('obv') and obv.get('breakout') is not None else None,
            'OBV_POZITIF_UYUMSUZLUK':obv.get('divergence')=='POZITIF_UYUMSUZLUK' if ok('obv') else None,
            'OBV_NEGATIF_UYUMSUZLUK':obv.get('divergence')=='NEGATIF_UYUMSUZLUK' if ok('obv') else None,
            'BOLLINGER_SIKISMA_KIRILIM':bb.get('squeeze_volume_momentum_break') if ok('bollinger') else None,
            'BOLLINGER_BANDA_DONUS':bb.get('return_inside') if ok('bollinger') else None,
            'MOMENTUM_GUCLENME':mom.get('state')=='GUCLENIYOR' if ok('momentum') else None,
            'MOMENTUM_ZAYIFLAMA':mom.get('state')=='ZAYIFLIYOR' if ok('momentum') else None}


def shadow(row,raw,current,mode):
    doc=view(row,current);result={k:0.0 for k in ('vwap','obv','bollinger','momentum')}
    prefix='INTRADAY' if mode=='INTRADAY' else 'TOMORROW'
    for name in result:
        weight=float(os.environ.get(prefix+'_'+name.upper()+'_WEIGHT','0' if name=='vwap' and mode=='TOMORROW' else '.25'))
        if not 0<=weight<=1:raise ValueError('Unsafe indicator weight')
        group=doc.get(name,{})
        if doc.get('mode')!=mode or doc.get('stale',True) or group.get('confidence',0)<50:continue
        sign=(1 if group.get('position')=='VWAP_USTU' else -1 if group.get('position')=='VWAP_ALTI' else 0) if name=='vwap' else (1 if group.get('trend')=='OBV_YUKSELEN' else -1 if group.get('trend')=='OBV_DUSEN' else 0) if name=='obv' else (1 if group.get('squeeze_volume_momentum_break') else -1 if group.get('lower_break') else 0) if name=='bollinger' else (1 if group.get('state')=='GUCLENIYOR' and group.get('direction')=='POZITIF' else -1 if group.get('state')=='ZAYIFLIYOR' else 0)
        result[name]=sign*weight
    rr=finite(row.get('gun_ici_rr' if mode=='INTRADAY' else 'karar_rr',row.get('risk_getiri')))
    price=finite(row.get('fiyat'));stop=finite(row.get('gun_ici_stop' if mode=='INTRADAY' else 'yarin_stop',row.get('stop')))
    change=finite(row.get('acilisa_gore_degisim' if mode=='INTRADAY' else 'degisim'))
    unsafe=(raw<(45 if mode=='INTRADAY' else 55) or bool(row.get('_durum')) or
            any((finite(row.get(k)) or 0)<0 for k in ('haber_puani','makro_puani','sektor_puani')) or
            (rr is not None and rr<(1.4 if mode=='INTRADAY' else 1.5)) or (price is not None and stop is not None and price<=stop) or
            (change is not None and (change<-3.5 or change>(5 if mode=='INTRADAY' else 4))) or
            (finite(row.get('rsi5' if mode=='INTRADAY' else 'rsi')) or 0)>=70)
    total=max(-2,min(2,sum(result.values())))
    if unsafe:total=min(0,total)
    return {'teknik_katkilar':result,'teknik_shadow_duzeltmesi':total,'teknik_shadow_puan':max(0,min(100,raw+total)),
            'teknik_ana_skor_etkisi':0,'teknik_safety_blok':unsafe,'teknik_learning_enabled':False,'teknik_model_version':MODEL}


def reasons(record,current):
    doc=view(record,current)
    if not doc or doc.get('stale'):return [],['Standart teknik veri eski veya yetersiz'] if doc else []
    positive=[];negative=[]
    flags=features(dict(record,zaman=aware(current).isoformat()))
    if flags['VWAP_USTU']:positive.append('Fiyat seans VWAP üzerinde')
    if doc.get('vwap',{}).get('position')=='VWAP_ALTI':negative.append('Fiyat seans VWAP altında')
    if flags['VWAP_RECLAIM']:positive.append('Fiyat seans VWAP seviyesini geri aldı')
    if flags['OBV_POZITIF_TREND']:positive.append('OBV yükselen trendde')
    if doc.get('obv',{}).get('trend')=='OBV_DUSEN':negative.append('OBV zayıflıyor')
    if flags['OBV_NEGATIF_UYUMSUZLUK']:negative.append('Negatif OBV uyumsuzluğu')
    if flags['OBV_POZITIF_UYUMSUZLUK']:positive.append('Pozitif OBV uyumsuzluğu')
    if flags['BOLLINGER_SIKISMA_KIRILIM']:positive.append('Bollinger sıkışması sonrası hacimli kırılım')
    if flags['MOMENTUM_GUCLENME']:positive.append('Kısa momentum güçleniyor')
    if flags['MOMENTUM_ZAYIFLAMA']:negative.append('Momentum aşağı dönüyor')
    return positive,negative


def performance_report(records,current,mode,minimum=40):
    """Frozen criteria vs closed outcomes; separate time units and fixed stock/day sampling."""
    from performans_motoru import robust, wilson
    current=aware(current)
    horizons=(5,15,30,60,'SEANS') if mode=='INTRADAY' else (1,3,5,10,20,60)
    selected={}
    for record in sorted(records,key=lambda r:r.get('sinyal_zamani') or r.get('zaman') or ''):
        if mode=='INTRADAY' and record.get('karar')!='AL':continue
        if mode=='TOMORROW' and record.get('model')!='YARIN_TOP10':continue
        stamp=record.get('sinyal_zamani') or record.get('zaman');at=aware(stamp)
        if not at or at>current:continue
        selected.setdefault((record.get('sembol'),at.date().isoformat()),record)
    def stats(pairs):
        gains=[finite(result.get('getiri_yuzde')) for _,result in pairs]
        wins=sum(result.get('durum')=='BASARILI' for _,result in pairs)
        days={str(record.get('sinyal_zamani') or record.get('zaman'))[:10] for record,_ in pairs}
        return {**robust(gains),'sample_count':len(pairs),'success_rate':wins/len(pairs) if pairs else None,
                'median_return':robust(gains)['medyan'],'trimmed_mean':robust(gains)['trimmed_ortalama'],
                'success_confidence_interval':wilson(wins,len(pairs)),
                'confidence':'YETERLI' if len(pairs)>=max(40,minimum) and len(days)>=5 else 'DUSUK','independent_days':len(days)}
    reports={}
    for h in horizons:
        pairs=[]
        for record in selected.values():
            result=(record.get('sonuclar') or {}).get(str(h),{}) if mode=='INTRADAY' else record.get('sonuc_'+str(h)+'g') or {}
            observed=aware(result.get('observed_at'))
            completed=result.get('tamamlandi') if mode=='INTRADAY' else result.get('degerlendirme_tamamlandi')
            eligible=result.get('egitime_uygun') if mode=='INTRADAY' else not result.get('kalite_uyarilari')
            signal=aware(record.get('sinyal_zamani') or record.get('zaman'))
            if not completed or not eligible or not observed or observed>current or observed<signal or finite(result.get('getiri_yuzde')) is None:continue
            if result.get('durum') not in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP'):continue
            pairs.append((record,result))
        criteria={}
        for key in CRITERIA:
            yes=[p for p in pairs if snapshot(p[0]).get('mode')==mode and features(p[0])[key] is True]
            no=[p for p in pairs if snapshot(p[0]).get('mode')==mode and features(p[0])[key] is False]
            criteria[key]={'varken':stats(yes),'yokken':stats(no),'bilinmeyen':len(pairs)-len(yes)-len(no),
                           'confidence':'YETERLI' if stats(yes)['confidence']==stats(no)['confidence']=='YETERLI' else 'DUSUK'}
        reports[str(h)]=criteria
    return {'model':MODEL,'mode':mode,'unit':'DAKIKA' if mode=='INTRADAY' else 'ISLEM_GUNU',
            'vadeler':reports,'learning_enabled':False,'score_applied':False,'sample_unit':'FIRST_STOCK_DAY_SIGNAL',
            'success_definition':'BASARILI; kısmi başarı ayrıca sonuç kaydındadır','updated_at':current.isoformat()}
