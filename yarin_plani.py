"""Selected-stock next-session plan. Independent presentation model; no TOP10 scoring.

Reuse the central daily provider, XIST calendar and closed-bar indicator helpers.
Only small immutable plan records are saved; never copy price histories.
"""
import copy
import json
from collections import OrderedDict
from datetime import datetime, time, timedelta
from threading import RLock

import pandas as pd
from ai_karar_motoru import ISTANBUL, locked
from kullanici_kayitlari import atomic_json, symbol
from veri_yollari import paths
from teknik_gostergeler import closed_frame, finite, rsi, macd, ema, calculate
from performans_motoru import business_day, sessions_after, session_closed
# Existing central intraday safety/volume constants, reused without changing that engine.
from gunluk_al_sat import VOLUME_CONFIRMATION, EXTENSION_ATR, MIN_RISK_REWARD

VERSION='TOMORROW_PLAN_V1'
FIELDS=('reference_price','buy_zone_low','buy_zone_high','take_profit_low','take_profit_high',
        'stop_loss','volume_breakout_level','breakout_target','support','resistance',
        'risk_reward_ratio','atr','volume_ratio','rsi','confidence_score')
LEVELS=('buy_zone_low','buy_zone_high','take_profit_low','take_profit_high','stop_loss','risk_reward_ratio')
_cache=OrderedDict()
_guard=RLock()
MAX_CACHE=128


def empty(stock,reason):
    return dict.fromkeys(FIELDS)|{'symbol':stock,'as_of':None,'plan_session':None,
        'engine_version':VERSION,'plan_status':'YETERSIZ_VERI','confirmation_count':0,
        'confirmation_total':8,'volume_breakout_status':None,'macd_state':None,'trend_state':None,
        'reasons':[],'warnings':[reason],'entry_reference':None,'entry_method':'BUY_ZONE_MIDPOINT'}


def plan_levels(price,atr,support,resistance,sma20,ema21):
    """ATR buffers around real support/trend; midpoint entry, conservative lower target."""
    missing=dict.fromkeys(LEVELS)|{'entry_reference':None}
    values=(price,atr,support,resistance,sma20,ema21)
    if any(finite(v) is None or v<=0 for v in values) or support>=price or resistance<=support:
        return missing
    anchor=min(price,max(support,min(sma20,ema21)))
    low=max(support,anchor-atr*.23)
    high=min(price,anchor+atr*.03,resistance-atr*.10)
    stop=support-atr*.25
    if not 0<stop<low<=high:return missing
    # A close resistance is respected, not replaced by an invented fixed-% target.
    profit_low=min(resistance,price+atr*.50)
    profit_high=min(resistance+atr*.25,price+atr*.80)
    entry=(low+high)/2
    if not high<profit_low<=profit_high:return missing
    return dict(buy_zone_low=low,buy_zone_high=high,take_profit_low=profit_low,
        take_profit_high=profit_high,stop_loss=stop,risk_reward_ratio=(profit_low-entry)/(entry-stop),
        entry_reference=entry)


def build(stock,data,current,holiday=None):
    result=empty(stock,'Tamamlanmış günlük teknik veri yetersiz.')
    if not isinstance(data,pd.DataFrame) or not isinstance(data.index,pd.DatetimeIndex) or data.empty:return result
    # Restrict the information set before every normalization/indicator calculation.
    frame=closed_frame(data,current,'TOMORROW')
    if 'complete' in frame:frame=frame.loc[frame['complete']!=False]
    frame=frame.loc[[business_day(d.date(),holiday) and session_closed(d.date(),current) for d in frame.index]]
    if frame.empty:return result
    if len(set(frame.index.date))!=len(frame):return result
    last=frame.index[-1].date()
    asof=max(frame['_available_at'].iloc[-1].to_pydatetime(),datetime.combine(last,time(18,15),ISTANBUL))
    result.update(as_of=asof.isoformat(),plan_session=sessions_after(last,1,holiday)[0].isoformat())
    if len(frame)<51:return result
    tail=frame.tail(51)
    o,h,l,c=(tail[k] for k in ('Open','High','Low','Close'))
    valid=tail[['Open','High','Low','Close']].notna().all().all() and (l>0).all() and (h>=pd.concat([o,c],axis=1).max(axis=1)).all() and (l<=pd.concat([o,c],axis=1).min(axis=1)).all()
    if not valid:return result
    # No silent compression of missing sessions into a shorter moving-average horizon.
    expected=[];day=tail.index[0].date()
    while day<=last:
        if business_day(day,holiday):expected.append(day)
        day+=timedelta(days=1)
    if expected!=list(tail.index.date):return result
    price=float(c.iloc[-1]);previous=float(c.iloc[-2]);sma20=float(c.tail(20).mean());sma50=float(c.tail(50).mean())
    ema21=finite(ema(frame['Close'],21).iloc[-1])
    prev_close=frame['Close'].shift(1)
    tr=pd.concat([frame['High']-frame['Low'],(frame['High']-prev_close).abs(),(frame['Low']-prev_close).abs()],axis=1).max(axis=1)
    atr=finite(tr.tail(14).mean())
    if not atr or atr<=0:return result
    support=float(frame['Low'].iloc[-6:-1].min());resistance=float(frame['High'].iloc[-6:-1].max())
    strength=finite(rsi(frame['Close']).iloc[-1]);_,_,hist=macd(frame['Close']);now_hist=finite(hist.iloc[-1]);old_hist=finite(hist.iloc[-2])
    ratio=calculate(frame,current,'TOMORROW')['volume_ratio']
    volumes=frame['Volume'].tail(21)
    if volumes.isna().any() or (volumes<0).any():ratio=None
    trend='POSITIVE' if price>sma20>sma50 else 'NEGATIVE' if price<sma20<sma50 else 'NEUTRAL'
    macd_state=('POSITIVE' if now_hist>0 and now_hist>=old_hist else 'IMPROVING' if now_hist>old_hist else 'WEAKENING' if now_hist>0 else 'NEGATIVE') if now_hist is not None and old_hist is not None else None
    positive=price>float(frame['Open'].iloc[-1])
    breakout=('CONFIRMED' if ratio is not None and ratio>=VOLUME_CONFIRMATION and positive else 'WEAK_CONFIRMATION') if price>resistance else 'WAITING'
    levels=plan_levels(price,atr,support,resistance,sma20,ema21)
    rr=levels['risk_reward_ratio'];drop=(price/previous-1)*100
    extended=abs(price-ema21)/atr>EXTENSION_ATR
    close_resistance=0<resistance-price<=atr*.25
    criteria={
        'Fiyat SMA20 üzerinde':price>sma20,
        'SMA20/SMA50 trend uyumu olumlu':sma20>sma50,
        'RSI dengeli güç bölgesinde':strength is not None and 45<=strength<=70,
        'MACD momentum olumlu':macd_state=='POSITIVE',
        'Hacim teyidi var':ratio is not None and ratio>=VOLUME_CONFIRMATION,
        'Destek ve alım yapısı geçerli':levels['stop_loss'] is not None,
        'Risk/getiri uygun':rr is not None and rr>=MIN_RISK_REWARD,
        'Kapanış mumu pozitif':positive,
    }
    count=sum(criteria.values());confidence=count/len(criteria)*100
    warnings=[]
    if ratio is None:warnings.append('Hacim verisi eksik.');confidence*=.75
    elif ratio<VOLUME_CONFIRMATION:warnings.append('Hacim teyidi zayıf.')
    if close_resistance:warnings.append('Güçlü dirence yakın.');confidence-=15
    if rr is None:warnings.append('Geçerli alım/stop/hedef yapısı yok.')
    elif rr<MIN_RISK_REWARD:warnings.append('Risk/getiri kısa vadeli giriş için zayıf.');confidence-=15
    if strength is not None and strength>=70:warnings.append('RSI yüksek.');confidence-=10
    if extended:warnings.append('Günlük hareket aşırı uzamış; fiyatı takip ederek alım riski.');confidence-=25
    if trend=='NEGATIVE':warnings.append('Negatif trend devam ediyor.')
    if drop<=-7+1e-9:warnings.append('Günlük düşüş en az %7; otomatik tepki AL planı verilmez.')
    expected_last=current.date()
    if not session_closed(expected_last,current):expected_last-=timedelta(days=1)
    while not business_day(expected_last,holiday):expected_last-=timedelta(days=1)
    stale=last<expected_last
    if stale:warnings.append('Son tamamlanmış seans verisi güncel değil.')
    blocked=trend=='NEGATIVE' or drop<=-7+1e-9 or extended or stale or rr is None
    if blocked:
        levels=dict.fromkeys(LEVELS)|{'entry_reference':None}
        confidence=min(confidence,35)
    confidence=round(max(0,min(100,confidence)),2)
    status='BEKLE' if blocked else 'UYGUN' if count>=6 and confidence>=70 and rr>=MIN_RISK_REWARD and ratio is not None else 'TEMKINLI'
    reasons=[name for name,passed in criteria.items() if passed]
    if ratio is not None:reasons.append(f'Hacim ortalamanın %{ratio:.0f}\'ı.')
    result.update(reference_price=price,atr=atr,support=support,resistance=resistance,
        volume_breakout_level=resistance,volume_breakout_status=breakout,
        breakout_target=resistance+atr*.60 if resistance>0 and resistance+atr*.60>price else None,
        volume_ratio=ratio,rsi=strength,macd_state=macd_state,trend_state=trend,
        confidence_score=confidence,confirmation_count=count,confirmation_total=len(criteria),
        confirmations=criteria,reasons=reasons,warnings=warnings,plan_status=status,
        sma20=sma20,sma50=sma50,ema21=ema21,daily_return_pct=drop,**levels)
    return result


def daily_data(stock,location):
    """Reuse OHLCV cache if available; otherwise one central provider call for this stock."""
    from ai_karar_motoru import load
    cached=load(location.runtime_file('performans_fiyat_cache.json'),{}).get(stock,{})
    bars=cached.get('bars',[])
    if len(bars)>=51 and all(finite(b.get('volume')) is not None for b in bars[-51:]):
        frame=pd.DataFrame(bars).rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
        frame.index=pd.DatetimeIndex(pd.to_datetime(frame.pop('timestamp'),utc=True)).tz_convert(ISTANBUL)
        return frame
    # A detail request must not launch analysis for an unknown/unanalysed symbol.
    # Existing closed-daily technical provenance permits the selected-symbol fallback.
    public=load(location.public_file('bist_data.json'),{})
    row=next((r for r in public.get('hisseler',[]) if r.get('sembol')==stock),{})
    technical=row.get('teknik_gostergeler') or {}
    if technical.get('mode')!='TOMORROW' or not technical.get('data_time') or technical.get('bar_count',0)<51:
        return pd.DataFrame()
    import bist_bot
    from saglayici_sembolleri import bist_symbol
    return bist_bot.bp.Ticker(bist_symbol(stock)).history(period='6mo')


def read_frozen(path,current):
    if not path.exists():return None
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('engine_version')!=VERSION or not isinstance(value.get('as_of'),str):raise ValueError('Plan snapshot format')
    at=datetime.fromisoformat(value['as_of'])
    if at.tzinfo is None or at>current:raise ValueError('Future/naive plan snapshot')
    if value.get('symbol')!=path.parent.name or at.date().isoformat()!=path.stem:raise ValueError('Plan snapshot identity')
    if value.get('plan_status') not in ('UYGUN','TEMKINLI','BEKLE') or not set(FIELDS)<=set(value):raise ValueError('Plan snapshot fields')
    if finite(value['reference_price']) is None or value['reference_price']<=0:raise ValueError('Plan reference price')
    if finite(value['confidence_score']) is None or not 0<=value['confidence_score']<=100:raise ValueError('Plan confidence')
    if value.get('confirmation_total')!=8 or not isinstance(value.get('confirmation_count'),int) or not 0<=value['confirmation_count']<=8:raise ValueError('Plan confirmations')
    return value


def view(value,expected):
    value=copy.deepcopy(value)
    at=datetime.fromisoformat(value['as_of']).date() if value.get('as_of') else None
    value['is_current_reference']=at==expected
    value['view_status']=value['plan_status'] if at==expected else 'YETERSIZ_VERI' if at is None else 'BEKLE'
    return value


def get_plan(stock,location=None,current=None,provider=None,holiday=None):
    """Fail-safe HTTP adapter, immutable per symbol/reference session, bounded RAM cache."""
    location=location or paths();current=current or datetime.now(ISTANBUL);stock=symbol(stock)
    try:
        expected=current.date()
        if not session_closed(expected,current):expected-=timedelta(days=1)
        while not business_day(expected,holiday):expected-=timedelta(days=1)
        directory=location.runtime/'yarin_plan_arsivi'/stock
        expected_path=directory/(expected.isoformat()+'.json')
        value=read_frozen(expected_path,current)
        if value:return view(value,expected)
        key=(str(location.runtime),stock,expected)
        # Single flight for selected-stock requests; no network/price histories persisted.
        with _guard:
            cached=_cache.get(key)
            if cached and 0<=(current-cached[0]).total_seconds()<300:
                _cache.move_to_end(key);return view(cached[1],expected)
            value=build(stock,(provider(stock) if provider else daily_data(stock,location)),current,holiday)
            if value['as_of'] and value['plan_status']!='YETERSIZ_VERI':
                path=directory/(datetime.fromisoformat(value['as_of']).date().isoformat()+'.json')
                directory.mkdir(parents=True,exist_ok=True,mode=0o700)
                with locked(path):
                    old=read_frozen(path,current)
                    if old is not None:value=old
                    else:atomic_json(path,value)
            _cache[key]=(current,copy.deepcopy(value))
            while len(_cache)>MAX_CACHE:_cache.popitem(last=False)
            return view(value,expected)
    except Exception as error:
        from gorev_hatalari import log_source
        log_source(error,'ANALYSIS')
        # Source classifier emits the safe cause/type/frames; no raw payloads or secrets.
        return None
