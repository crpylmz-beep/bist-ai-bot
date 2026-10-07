"""Independent intraday decisions over existing, genuinely closed 5m OHLCV."""
from collections import OrderedDict
from datetime import timedelta
import copy
import hashlib
import json
import os
import threading
import pandas as pd

from ai_karar_motoru import ISTANBUL, number, stamp, load, locked
from kullanici_kayitlari import atomic_json, RecordError
from teknik_gostergeler import closed_frame, calculate, ema, rsi, macd
from veri_yollari import paths

MODEL = 'GUNLUK_AL_SAT_V1'
TIMEFRAME = '5m'
INTERVAL_SECONDS = 300
MIN_BARS = 35
STALE_SECONDS = 600
DETAIL_BATCH = 30
ROTATION_BATCH = 10
CACHE_SYMBOLS = 2000
CACHE_BARS = 300
MIN_CONFIRMATIONS = 6
MIN_FAMILIES = 3
MIN_CONFIDENCE = 60
VOLUME_CONFIRMATION = 130
MIN_BAR_TURNOVER = 100000
EXTENSION_ATR = 3
MIN_RISK_REWARD = 1.2
CONFIRMATION_LEVELS = ((8, 'COK_GUCLU'), (6, 'GUCLU'), (4, 'ORTA'), (0, 'ZAYIF'))
CRITERIA = ('VWAP', 'EMA', 'RSI', 'MACD', 'VOLUME', 'OBV', 'BOLLINGER', 'MOMENTUM', 'CANDLE')
FAMILIES = {'VWAP':'POSITION','EMA':'TREND','RSI':'MOMENTUM','MACD':'MOMENTUM',
            'MOMENTUM':'MOMENTUM','VOLUME':'FLOW','OBV':'FLOW','BOLLINGER':'POSITION','CANDLE':'CANDLE'}
SCORE_CHANGE = 10
_cache = OrderedDict()
_cache_lock = threading.Lock()


def enabled():
    return os.environ.get('INTRADAY_SIGNAL_ENGINE_ENABLED', 'false').lower() in ('true', '1', 'yes', 'on')


def observe_frames(frames):
    """Reuse the existing stream; bounded RAM only, never duplicate disk OHLCV."""
    if not enabled(): return
    with _cache_lock:
        for symbol, frame in frames.items():
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                _cache[symbol] = frame.tail(CACHE_BARS).copy()
                _cache.move_to_end(symbol)
        while len(_cache) > CACHE_SYMBOLS: _cache.popitem(last=False)


def cached(symbols):
    with _cache_lock: return {s: _cache[s].copy() for s in symbols if s in _cache}


def levels(price, vwap, atr, support, resistance):
    missing = dict(buy_zone_low=None, buy_zone_high=None, take_profit=None, stop_loss=None,
                   risk_reward_ratio=None, level_reason='INTRADAY_LEVEL_DATA_MISSING')
    if any(v is None or v <= 0 for v in (price, vwap, atr, support, resistance)): return missing
    anchor = min(price, max(vwap, support))
    low, high = max(support, anchor - atr * .35), min(price, anchor + atr * .25)
    stop = min(support, low) - atr * .25
    target = min(resistance, high + atr * 2) if resistance>high else high+atr*2
    entry = (low + high) / 2
    if not 0 < stop < low <= high < target or entry <= stop:
        return dict(missing, level_reason='INTRADAY_LEVEL_STRUCTURE_INVALID')
    return dict(buy_zone_low=round(low,4), buy_zone_high=round(high,4), take_profit=round(target,4),
                stop_loss=round(stop,4), risk_reward_ratio=round((target-entry)/(entry-stop),4), level_reason=None)


def lifecycle(signal, previous, current):
    at = stamp((previous or {}).get('signal_started_at'))
    if at is None or at > current or at.date() != current.date(): previous = None
    old = (previous or {}).get('active_side', 'IZLE')
    if signal == 'AL_ADAYI': state = 'AL_DEVAM' if old == 'AL' else 'TOPARLANIYOR' if old == 'SAT' else 'YENI_AL'; side = 'AL'
    elif signal == 'SAT_ADAYI': state = 'SAT_DONUS' if old == 'AL' else 'SAT_DEVAM' if old == 'SAT' else 'YENI_SAT'; side = 'SAT'
    else: state = 'ZAYIFLIYOR' if old == 'AL' else 'TOPARLANIYOR' if old == 'SAT' else 'IZLE'; side = old
    started = at if previous and old == side else current
    return {'signal_state':state, 'active_side':side, 'previous_state':(previous or {}).get('signal_state'),
            'signal_started_at':started.isoformat(), 'last_updated_at':current.isoformat(),
            'signal_age_minutes':round(max(0,(current-started).total_seconds()/60),2)}


def evaluate(symbol, data, current, previous=None):
    if previous:
        started=stamp(previous.get('signal_started_at'));updated=stamp(previous.get('last_updated_at'))
        if not started or started>current or started.date()!=current.date() or not updated or updated>current:previous=None
    frame = closed_frame(data, current, 'INTRADAY')
    base = dict(symbol=symbol, timestamp=current.isoformat(), model=MODEL, timeframe=TIMEFRAME,
                price=None, signal='IZLE', technical_score=0, confidence_score=0,
                confirmation_count=0, confirmation_total=len(CRITERIA), confirmation_level='ZAYIF',
                VWAP=None, EMA9=None, EMA21=None, RSI=None, MACD=None, MACD_histogram=None,
                OBV=None, Bollinger=None, ATR=None, volume_ratio=None, momentum=None,
                candle_summary=None, breakout_status='WAITING', breakout_level=None,
                extended_move_penalty=0, data_quality='INSUFFICIENT', liquidity_status='INSUFFICIENT',
                reasons=[], warnings=[], data_timestamp=None, missing_indicators=list(CRITERIA),
                **levels(None,None,None,None,None))
    if frame.empty:
        base['warnings'].append('Gerçek kapalı 5dk mum verisi yok.')
        return dict(base, **lifecycle('IZLE',previous,current))
    # Reject daily/coarse bars masquerading as intraday and impossible OHLCV.
    observed = frame['_available_at'].iloc[-1].to_pydatetime()
    session = frame.loc[frame.index.date == current.date()]
    valid = frame[['Open','High','Low','Close','Volume']].notna().all().all()
    valid = valid and bool((frame[['Open','High','Low','Close']] > 0).all().all())
    valid = valid and bool((frame['Volume'] >= 0).all())
    valid = valid and all(10<=t.hour<=18 and t.minute%5==0 and t.second==0 for t in frame.index)
    valid = valid and bool((frame['High'] >= frame[['Open','Close','Low']].max(axis=1)).all())
    valid = valid and bool((frame['Low'] <= frame[['Open','Close','High']].min(axis=1)).all())
    spacing = len(session) >= 2 and all((session.index[i]-session.index[i-1]).total_seconds()==300 for i in range(1,len(session)))
    fresh = observed.date() == current.date() and (current-observed).total_seconds() <= STALE_SECONDS
    base.update(price=number(frame['Close'].iloc[-1]), data_timestamp=observed.isoformat())
    if not valid or not spacing or not fresh or len(frame) < MIN_BARS:
        base['warnings'].append('Eksik/eski/uyumsuz intraday mumlar; güçlü sinyal üretilmedi.')
        return dict(base, **lifecycle('IZLE',previous,current))
    indicators = calculate(frame, current, 'INTRADAY')
    close = frame['Close']; last = frame.iloc[-1]; previous_bar = frame.iloc[-2]
    ema9, ema21 = number(ema(close,9).iloc[-1]), number(ema(close,21).iloc[-1])
    strength = number(rsi(close).iloc[-1]); line, macd_signal, hist = macd(close)
    mac, histogram, old_hist = number(line.iloc[-1]), number(hist.iloc[-1]), number(hist.iloc[-2])
    tr = pd.concat([frame['High']-frame['Low'], (frame['High']-close.shift(1)).abs(), (frame['Low']-close.shift(1)).abs()],axis=1).max(axis=1)
    atr = number(tr.rolling(14).mean().iloc[-1])
    vwap = indicators['vwap']['session_value'] if indicators['vwap']['status']=='OK' else None
    obv = indicators['obv']; bb = indicators['bollinger']; momentum = indicators['momentum']['short_pct']
    ratio = indicators['volume_ratio']; price = base['price']
    pos = indicators['momentum']['close_position_pct']
    body = number(last['Close']-last['Open']); candle_direction = 'POSITIVE' if body>0 else 'NEGATIVE' if body<0 else 'NEUTRAL'
    engulfing = bool(last['Close']>previous_bar['Open'] and last['Open']<=previous_bar['Close'] and body>0 and previous_bar['Close']<previous_bar['Open'])
    candle = {'direction':candle_direction,'close_position_pct':pos,'bullish_engulfing':engulfing,
              'near_high':pos>=75 if pos is not None else None,'near_low':pos<=25 if pos is not None else None}
    support = number(frame['Low'].iloc[-6:-1].min()); resistance = number(frame['High'].iloc[-21:-1].max())
    evidence = {}
    def vote(name, available, buy, sell): evidence[name] = 'AL' if available and buy else 'SAT' if available and sell else 'NEUTRAL' if available else 'MISSING'
    vote('VWAP',vwap is not None, price>vwap if vwap else False, price<vwap if vwap else False)
    vote('EMA',ema9 is not None and ema21 is not None, ema9>ema21, ema9<ema21)
    vote('RSI',strength is not None, 45<=strength<=70 if strength is not None else False, 30<=strength<=55 if strength is not None else False)
    vote('MACD',histogram is not None and old_hist is not None, histogram>0 and histogram>old_hist, histogram<0 and histogram<old_hist)
    vote('VOLUME',ratio is not None, ratio>=VOLUME_CONFIRMATION and body>0 if ratio is not None else False, ratio>=VOLUME_CONFIRMATION and body<0 if ratio is not None else False)
    vote('OBV',obv['status']=='OK', obv['trend']=='OBV_YUKSELEN', obv['trend']=='OBV_DUSEN')
    vote('BOLLINGER',bb['status']=='OK', bb['middle']<price<=bb['upper'] if bb['middle'] else False, bb['lower']<=price<bb['middle'] if bb['middle'] else False)
    vote('MOMENTUM',momentum is not None, momentum>.05 if momentum is not None else False, momentum<-.05 if momentum is not None else False)
    vote('CANDLE',pos is not None, body>0 and pos>=65 if pos is not None else False, body<0 and pos<=35 if pos is not None else False)
    buy = sum(v=='AL' for v in evidence.values()); sell = sum(v=='SAT' for v in evidence.values())
    side = 'AL' if buy>sell else 'SAT' if sell>buy else 'IZLE'; count = max(buy,sell)
    coverage = sum(v!='MISSING' for v in evidence.values()) / len(CRITERIA)
    turnover = price * number(last['Volume'],0)
    liquidity = 'GOOD' if turnover>=MIN_BAR_TURNOVER and ratio is not None else 'LIMITED' if turnover>0 else 'INSUFFICIENT'
    confidence = 100 * coverage * (count/len(CRITERIA)) * (1-min(buy,sell)/len(CRITERIA))
    if liquidity != 'GOOD': confidence *= .5 if liquidity=='LIMITED' else 0
    distance = abs(price-vwap)/atr if vwap and atr and atr>0 else None
    penalty = min(40,max(0,distance-EXTENSION_ATR)*10) if distance is not None else 0
    confidence = max(0,confidence-penalty)
    level_data = levels(price,vwap,atr,support,resistance)
    if side=='AL' and (level_data['risk_reward_ratio'] is None or level_data['risk_reward_ratio']<MIN_RISK_REWARD): confidence *= .6
    family_count = len({FAMILIES[k] for k,v in evidence.items() if v==side})
    signal = 'AL_ADAYI' if side=='AL' else 'SAT_ADAYI' if side=='SAT' else 'IZLE'
    if count<MIN_CONFIRMATIONS or family_count<MIN_FAMILIES or confidence<MIN_CONFIDENCE or liquidity!='GOOD': signal='IZLE'
    breakout = 'CONFIRMED' if resistance and price>resistance and ratio is not None and ratio>=VOLUME_CONFIRMATION else 'WEAK_CONFIRMATION' if resistance and price>resistance else 'WAITING'
    base.update(signal=signal, technical_score=round(count/len(CRITERIA)*100,2), confidence_score=round(min(100,confidence),2),
        confirmation_count=count,confirmation_level=next(label for threshold,label in CONFIRMATION_LEVELS if count>=threshold),
        VWAP=vwap,EMA9=ema9,EMA21=ema21,RSI=strength,MACD=mac,MACD_histogram=histogram,
        OBV=obv['value'],Bollinger=copy.deepcopy(bb),ATR=atr,volume_ratio=ratio,momentum=momentum,
        candle_summary=candle,breakout_status=breakout,breakout_level=resistance,extended_move_penalty=round(penalty,2),
        data_quality='GOOD' if coverage==1 else 'LIMITED',liquidity_status=liquidity,
        missing_indicators=[k for k,v in evidence.items() if v=='MISSING'],
        confirmations=evidence, intraday_high=number(session['High'].max()),intraday_low=number(session['Low'].min()),
        session_open=number(session['Open'].iloc[0]),opening_return_pct=(price/session['Open'].iloc[0]-1)*100,
        indicator_snapshot=copy.deepcopy(indicators), **level_data)
    base['reasons']=[f'{k}: {v}' for k,v in evidence.items() if v in ('AL','SAT')]+[f'{count}/{len(CRITERIA)} teyit']
    if strength is not None and (strength>70 or strength<30):base['warnings'].append('RSI aşırı bölgede; tek başına sinyal değildir.')
    if penalty:base['warnings'].append('Hareket VWAP/ATR ölçüsüne göre uzamış.')
    if base['level_reason']:base['warnings'].append(base['level_reason'])
    if liquidity!='GOOD':base['warnings'].append('Likidite teyidi sınırlı.')
    life=lifecycle(signal,previous,current)
    if previous and previous.get('data_timestamp')==base['data_timestamp'] and previous.get('signal')==signal:
        life['signal_state']=previous['signal_state']
    return dict(base, **life)


class GunlukAlSat:
    def __init__(self,location=None,clock=None,universe=None,provider=None):
        from ana_motor import istanbul_now
        self.location=location or paths();self.clock=clock or istanbul_now
        self.universe=universe;self.provider=provider
        self.state_path=self.location.runtime_file('gunluk_al_sat_state.json')
        self.public_path=self.location.public_file('gunluk_al_sat.json')

    def persist(self,row,state):
        old=state['signals'].get(row['symbol'])
        transition=not old or old['signal_state']!=row['signal_state'] and row['signal_state'] not in ('AL_DEVAM','SAT_DEVAM')
        important=row['data_quality']!='INSUFFICIENT' and row['signal_state']!='IZLE' and (transition or abs(row['technical_score']-old['technical_score'])>=SCORE_CHANGE)
        if important:
            identity=hashlib.sha256((row['symbol']+'|'+str(row['data_timestamp'])+'|'+row['signal_state']).encode()).hexdigest()
            target=self.location.runtime_file('gunluk_al_sat_gecmisi')/(stamp(row['timestamp']).date().isoformat()+'.json')
            with locked(target):
                history=load(target,{'model':MODEL,'events':{}})
                if identity not in history['events']:
                    history['events'][identity]=copy.deepcopy(dict(row,event_id=identity,analysis_only=True))
                    atomic_json(target,history)
        state['signals'][row['symbol']]=row

    def one_round(self):
        from ana_motor import market_open
        from gorev_hatalari import remember,describe,TaskIssue,strongest
        from saglayici_sembolleri import bist_symbol
        current=self.clock().astimezone(ISTANBUL)
        if not enabled():return {'disabled':True}
        if not market_open(current):return {'skipped':True,'reason':'MARKET_CLOSED'}
        if self.universe is None:
            import bist_bot
            universe=bist_bot.bist_hisseleri_getir()
        else:universe=self.universe()
        stocks=sorted({bist_symbol(s) for s in universe})
        if not stocks:raise TaskIssue({'code':'EMPTY_UNIVERSE'})
        frames=cached(stocks);failures=[];skipped=[]
        with locked(self.state_path):
            state=load(self.state_path,{'signals':{},'cursor':0})
            cursor=state.get('cursor',0)%len(stocks)
            rotated=[stocks[(cursor+i)%len(stocks)] for i in range(min(ROTATION_BATCH,len(stocks)))]
            state['cursor']=(cursor+ROTATION_BATCH)%len(stocks)
            unsupported=load(self.location.runtime_file('provider_unsupported.json'),{})
            candidates=[]
            for stock,frame in frames.items():
                closed=closed_frame(frame,current,'INTRADAY')
                if len(closed)>=MIN_BARS and stamp(closed['_available_at'].iloc[-1].isoformat()).date()==current.date():
                    move=abs(number(closed['Close'].iloc[-1]/closed['Close'].iloc[-4]-1,0))
                    candidates.append((move,stock))
            chosen=list(dict.fromkeys(rotated+[s for _,s in sorted(candidates,reverse=True)]))[:DETAIL_BATCH]
            successful=0
            for stock in chosen:
                try:
                    cached_frame=frames.get(stock)
                    closed=closed_frame(cached_frame,current,'INTRADAY')
                    fresh=len(closed) and (current-closed['_available_at'].iloc[-1].to_pydatetime()).total_seconds()<=STALE_SECONDS
                    if not fresh:
                        prior_skip=unsupported.get(stock,{})
                        skip_time=stamp(prior_skip.get('updated_at'))
                        if prior_skip.get('code')=='PROVIDER_UNSUPPORTED' and skip_time and current-skip_time<timedelta(hours=6):
                            skipped.append({'symbol':stock,'code':'PROVIDER_UNSUPPORTED'});continue
                        if self.provider is None:
                            import borsapy
                            cached_frame=borsapy.Ticker(stock).history(period='1d',interval=TIMEFRAME)
                        else:cached_frame=self.provider(stock)
                        observe_frames({stock:cached_frame})
                    row=evaluate(stock,cached_frame,current,state['signals'].get(stock))
                    self.persist(row,state);successful+=1
                except Exception as error:
                    remember(error,'GUNLUK_AL_SAT',stock);issue=describe(error)
                    if issue['code']=='PROVIDER_UNSUPPORTED':
                        skipped.append({'symbol':stock,**issue});unsupported[stock]={'code':issue['code'],'updated_at':current.isoformat()}
                    else:failures.append({'symbol':stock,**issue})
            atomic_json(self.state_path,state)
            if skipped:
                target=self.location.runtime_file('provider_unsupported.json')
                with locked(target):atomic_json(target,{**load(target,{}),**unsupported})
            rows=[]
            for stock in stocks:
                if stock not in state['signals']:continue
                row=copy.deepcopy(state['signals'][stock]);at=stamp(row.get('data_timestamp'))
                row['stale']=not at or at.date()!=current.date() or (current-at).total_seconds()>STALE_SECONDS
                rows.append(row)
            diagnostics={'processed':len(chosen),'successful':successful,'skipped':len(skipped),'failed':len(failures),
                         'universe_size':len(stocks),'cached_symbols':len(frames),'candidate_count':len(candidates),'reasons':skipped+failures}
            with locked(self.public_path):atomic_json(self.public_path,{'model':MODEL,'updated_at':current.isoformat(),'timeframe':TIMEFRAME,'signals':rows,'diagnostics':diagnostics})
        if failures:raise TaskIssue(strongest(failures),successful,diagnostics)
        return {'diagnostics':diagnostics}


def read_report(location=None):
    location=location or paths()
    try:
        value=json.loads(location.public_file('gunluk_al_sat.json').read_bytes())
        if value['model']!=MODEL or not isinstance(value['signals'],list) or not stamp(value['updated_at']):raise ValueError('Cache')
        for row in value['signals']:
            if not isinstance(row,dict) or not isinstance(row.get('symbol'),str) or row.get('signal') not in ('AL_ADAYI','SAT_ADAYI','IZLE'):
                raise ValueError('Signal')
            score=number(row.get('confidence_score'))
            if score is None or not 0<=score<=100:raise ValueError('Confidence')
        return value
    except Exception:raise RecordError('Günlük AL/SAT verisi henüz kullanılamıyor.',503) from None


def api_report(query,location=None,current=None):
    from ana_motor import istanbul_now,market_open
    if set(query)-{'signal','limit','min_confidence'} or any(len(v)!=1 for v in query.values()):raise RecordError('Geçersiz filtre.',400)
    signal=query.get('signal',[None])[0]
    try:limit=int(query.get('limit',['100'])[0]);confidence=float(query.get('min_confidence',['0'])[0])
    except (ValueError,TypeError):raise RecordError('Geçersiz sınır/güven.',400) from None
    if signal not in (None,'AL','SAT','IZLE') or not 1<=limit<=1000 or not 0<=confidence<=100:raise RecordError('Geçersiz filtre.',400)
    if not enabled():return {'enabled':False,'groups':{'AL':[],'SAT':[],'IZLE':[]},'signals':[]}
    report=read_report(location);current=current or istanbul_now();groups={'AL':[],'SAT':[],'IZLE':[]};rows=[]
    for original in report['signals']:
        row=copy.deepcopy(original);at=stamp(row.get('data_timestamp'))
        row['stale']=not at or at>current or at.date()!=current.date() or (current-at).total_seconds()>STALE_SECONDS
        row['market_open']=market_open(current)
        category={'AL_ADAYI':'AL','SAT_ADAYI':'SAT'}.get(row['signal'],'IZLE')
        if row['stale'] or not row['market_open']:
            row['live_signal']=False;category='IZLE';row['recorded_signal']=row['signal'];row['signal']='IZLE'
        else:row['live_signal']=True
        if (signal is None or signal==category) and row['confidence_score']>=confidence:
            rows.append(row)
    rows=sorted(rows,key=lambda r:r['confidence_score'],reverse=True)[:limit]
    for row in rows:
        category='IZLE' if not row['live_signal'] else {'AL_ADAYI':'AL','SAT_ADAYI':'SAT'}.get(row['signal'],'IZLE')
        groups[category].append(row)
    return dict(report,enabled=True,signals=rows,groups=groups)


def stock_signal(stock,location=None):
    if not enabled():return None
    try:return next((row for row in api_report({'limit':['1000']},location)['signals'] if row['symbol']==stock),None)
    except RecordError:return None
