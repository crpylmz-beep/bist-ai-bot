"""Pure outcomes/reports for frozen V1 signals; driven by GunIciPerformans."""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
import copy
import hashlib
import json
import math

from ai_karar_motoru import ISTANBUL, number, stamp, locked
from kullanici_kayitlari import atomic_json, RecordError
from performans_motoru import business_day, sessions_after, session_closed, normalize_bars as daily_bars
from sinyal_performansi import Stats, reliability, RELIABILITY, score_band, frozen_feature_issue, unique_records
from veri_yollari import paths

VERSION='INTRADAY_SIGNAL_PERFORMANCE_V1'
HORIZONS=('30m','60m','120m','SEANS','D1','D3')
PERIODS={'7d':7,'30d':30,'90d':90,'all_time':None}
STATES={'YENI_AL','YENI_SAT','SAT_DONUS','TOPARLANIYOR','AL_DEVAM','SAT_DEVAM','ZAYIFLIYOR','IZLE'}
CONFIDENCE_FILTERS=(0,50,60,70,80,90,100)
COMBINATIONS=(('VWAP','EMA'),('VWAP','VOLUME'),('EMA','MACD'),('MACD','VOLUME'),
              ('VWAP','EMA','VOLUME'),('VWAP','EMA','MACD'),('VWAP','EMA','MACD','VOLUME'))
CONDITIONS={name:{'AL','SAT','NEUTRAL'} for name in ('VWAP','EMA','RSI','MACD','VOLUME','OBV','BOLLINGER','MOMENTUM','CANDLE')}
CONDITIONS.update({'RSI_BUCKET':{'<30','30-49','50-69','70+'},'ATR_VOLATILITY':{'<1%','1-2%','2%+'},
    'VOLUME_RATIO':{'<100','<130','<200','200+'},'RISK_REWARD':{'<1','<1.5','<2','2+'},
    'EXTENSION':{'<1','<10','<30','30+'},'BREAKOUT':{'CONFIRMED','WEAK_CONFIRMATION','WAITING'},
    'MACD_HISTOGRAM':{'POSITIVE','NEGATIVE','ZERO'}})
CONDITIONS.update({'+'.join(combo):{'AL','SAT','MIXED'} for combo in COMBINATIONS})
FROZEN_FIELDS=('symbol','signal','signal_state','timestamp','prediction_price','price','technical_score','confidence_score',
    'confirmation_count','confirmation_total','confirmation_level','VWAP','EMA9','EMA21','RSI','MACD','MACD_histogram',
    'OBV','Bollinger','ATR','volume_ratio','momentum','candle_summary','buy_zone_low','buy_zone_high','take_profit',
    'stop_loss','risk_reward_ratio','breakout_status','extended_move_penalty','data_quality','liquidity_status',
    'reasons','warnings','timeframe','engine_version','model','indicator_snapshot','confirmations')


def fingerprint(row):return hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()
def prediction_price(row):return number(row.get('prediction_price'),number(row.get('price')))
def side(row):return 'AL' if row.get('signal')=='AL_ADAYI' else 'SAT' if row.get('signal')=='SAT_ADAYI' else None


def source_issue(row,current):
    if not isinstance(row,dict):return 'MALFORMED'
    at=stamp(row.get('timestamp'));data_at=stamp(row.get('data_timestamp'))
    if row.get('model')!='GUNLUK_AL_SAT_V1' or not isinstance(row.get('event_id'),str) or not isinstance(row.get('symbol'),str):return 'UNVERIFIED_SOURCE'
    if not isinstance(row.get('signal_state'),str) or not isinstance(row.get('signal'),str):return 'MALFORMED'
    if not at or not data_at:return 'UNVERIFIED_TIME'
    if at>current or data_at>at:return 'FUTURE_TIMESTAMP'
    if row.get('legacy_unverified') or row.get('unverified') or row.get('lookahead_suspected'):return 'UNVERIFIED'
    if row.get('engine_version') not in (None,'GUNLUK_AL_SAT_V1'):return 'UNVERIFIED_ENGINE'
    guard=dict(row);indicators=guard.pop('indicator_snapshot',None)
    if indicators is not None:
        if not isinstance(indicators,dict):return 'UNVERIFIED_FEATURES'
        indicator_at=stamp(indicators.get('data_time'))
        if indicator_at and indicator_at>at:return 'FUTURE_TIMESTAMP'
        guard['teknik_gostergeler']=indicators
    if frozen_feature_issue(guard,at):return 'FUTURE_OR_UNVERIFIED_FEATURES'
    if row.get('timeframe')!='5m' or row.get('data_quality') not in ('GOOD','LIMITED') or row.get('liquidity_status')!='GOOD':return 'INSUFFICIENT_SOURCE'
    if prediction_price(row) is None or prediction_price(row)<=0:return 'MISSING_PREDICTION_PRICE'
    if row.get('prediction_price') is not None and number(row.get('price'))!=prediction_price(row):return 'CONFLICTING_PREDICTION_PRICE'
    if not side(row) or row.get('signal_state') not in STATES-{'IZLE','ZAYIFLIYOR'}:return 'CONTEXT_ONLY'
    if row.get('signal_state') in ('YENI_SAT','SAT_DONUS','SAT_DEVAM') and side(row)!='SAT':return 'STATE_DIRECTION_MISMATCH'
    if row.get('signal_state') in ('YENI_AL','AL_DEVAM') and side(row)!='AL':return 'STATE_DIRECTION_MISMATCH'
    if row.get('signal_state')=='TOPARLANIYOR' and side(row)!='AL':return 'CONTEXT_ONLY'
    return None


def load_sources(location,current):
    records=[];errors={}
    for path in sorted(location.runtime_file('gunluk_al_sat_gecmisi').glob('????-??-??.json')):
        try:
            with locked(path):value=json.loads(path.read_bytes())
            if value.get('model')!='GUNLUK_AL_SAT_V1' or not isinstance(value.get('events'),dict):raise ValueError('Source')
            for identity,row in value['events'].items():
                if not isinstance(row,dict):errors[path.name]='MALFORMED';continue
                if row.get('event_id')!=identity:errors[path.name]='SOURCE_ID_MISMATCH';continue
                records.append(row)
        except Exception as error:errors[path.name]=type(error).__name__
    return records,errors


def observations(records,current):
    adapted=[]
    for row in records:
        if not isinstance(row,dict):continue
        adapted.append({'id':row.get('event_id'),'sembol':row.get('symbol'),'zaman':row.get('timestamp'),
                        'sinyal':row.get('signal_state'),'model':'GUNLUK_AL_SAT_V1','frozen':row})
    unique,duplicates,malformed=unique_records(adapted)
    result=[];previous={}
    for item,conflict in sorted(unique,key=lambda pair:str(pair[0].get('zaman',''))):
        row=item['frozen'];issue='CONFLICTING_DUPLICATE' if conflict else source_issue(row,current)
        at=stamp(row.get('timestamp'));key=(str(row.get('symbol')),at.date() if at else None)
        old=previous.get(key)
        if not issue and row.get('signal_state') in ('AL_DEVAM','SAT_DEVAM'):
            if not old:issue='UNVERIFIED_CONTINUATION'
            elif max(abs(number(row.get('technical_score'),0)-number(old.get('technical_score'),0)),
                     abs(number(row.get('confidence_score'),0)-number(old.get('confidence_score'),0)))<10:issue='INSIGNIFICANT_CONTINUATION'
        if not issue:previous[key]=row
        result.append((row,issue))
    return result,duplicates,malformed


def first_bar(at):
    start=at.replace(second=0,microsecond=0)+timedelta(minutes=(-at.minute)%5)
    return start+timedelta(minutes=5) if start<at else start


def due_at(row,horizon,holiday=None):
    at=stamp(row['timestamp'])
    if horizon in ('D1','D3'):
        day=sessions_after(at.date(),int(horizon[1:]),holiday)[-1]
        return datetime.combine(day,time(18,15),ISTANBUL)
    return datetime.combine(at.date(),time(18,10),ISTANBUL) if horizon=='SEANS' else first_bar(at)+timedelta(minutes=int(horizon[:-1]))


def direction_return(base,price,direction):
    return (price/base-1)*100 if direction=='AL' else (base/price-1)*100


def outcome(row,intraday,daily,horizon,current,holiday=None):
    from gun_ici_performans import normalize_bars
    at=stamp(row['timestamp']);due=due_at(row,horizon,holiday)
    empty={'status':'PENDING','completed':False,'horizon':horizon,'observed_at':current.isoformat(),
           'end_at':due.isoformat(),'prediction_price':prediction_price(row),'measurement_version':VERSION}
    if current<due:return dict(empty,reason='NOT_DUE')
    session_end=datetime.combine(at.date(),time(18,10),ISTANBUL)
    intraday_end=session_end if horizon in ('D1','D3') else due
    if intraday_end>session_end:return dict(empty,reason='HORIZON_EXCEEDS_SESSION')
    expected=[];cursor=first_bar(at)
    while cursor+timedelta(minutes=5)<=intraday_end:
        expected.append(cursor);cursor+=timedelta(minutes=5)
    if not expected:return dict(empty,reason='NO_POST_SIGNAL_FULL_BAR')
    # Normalize at horizon's end: later bars cannot affect even quality checks.
    mapping={stamp(b['timestamp']):b for b in normalize_bars(intraday,min(current,intraday_end)) if business_day(stamp(b['timestamp']).date(),holiday)}
    if any(t not in mapping for t in expected):return dict(empty,reason='MISSING_5M_BAR')
    used=[mapping[t] for t in expected];resolution='5m'
    if horizon in ('D1','D3'):
        days=sessions_after(at.date(),int(horizon[1:]),holiday)
        values=daily_bars(daily,min(current,due),holiday)
        if any(day not in values or any(values[day][k] is None for k in ('open','high','low','close')) for day in days):
            return dict(empty,reason='MISSING_DAILY_OHLC')
        used += [dict(values[day],timestamp=datetime.combine(day,time(18,15),ISTANBUL).isoformat()) for day in days]
        resolution='5m_SIGNAL_SESSION_PLUS_DAILY'
    base=prediction_price(row);direction=side(row)
    if base is None or base<=0 or not direction:return dict(empty,reason='INVALID_SOURCE')
    close=used[-1]['close'];hi=max(b['high'] for b in used);lo=min(b['low'] for b in used)
    mfe=max(0,direction_return(base,hi if direction=='AL' else lo,direction))
    mae=min(0,direction_return(base,lo if direction=='AL' else hi,direction))
    target=number(row.get('take_profit'));stop=number(row.get('stop_loss'))
    valid=target is not None and stop is not None and (stop<base<target if direction=='AL' else target<base<stop)
    first=None;target_hit=stop_hit=False;target_at=stop_at=None
    for b in used:
        th=valid and (b['high']>=target if direction=='AL' else b['low']<=target)
        sh=valid and (b['low']<=stop if direction=='AL' else b['high']>=stop)
        if th and target_at is None:target_at=b['timestamp']
        if sh and stop_at is None:stop_at=b['timestamp']
        target_hit|=bool(th);stop_hit|=bool(sh)
        if first is None and (th or sh):first='AMBIGUOUS' if th and sh else 'TARGET_HIT' if th else 'STOP_HIT'
    zone_low=number(row.get('buy_zone_low'));zone_high=number(row.get('buy_zone_high'));entry_index=None
    if direction=='AL' and zone_low is not None and zone_high is not None and 0<zone_low<=zone_high:
        entry_index=next((i for i,b in enumerate(used) if b['low']<=zone_high and b['high']>=zone_low),None)
    # Entry-bar extrema may predate entry; report only subsequent complete bars.
    after=used[entry_index+1:] if entry_index is not None else []
    entry_price=base if after else None
    return dict(empty,status='COMPLETED',completed=True,reason=None,close_price=close,
        raw_return=(close/base-1)*100,direction_return=direction_return(base,close,direction),direction=direction,
        MFE=mfe,MAE=mae,high_price=hi,low_price=lo,resolution=resolution,
        target_stop_status=first or 'NEITHER',target_hit=target_hit if valid else None,stop_hit=stop_hit if valid else None,
        target_first_at=target_at,stop_first_at=stop_at,levels_available=bool(valid),
        buy_zone_entered=entry_index is not None if zone_low is not None and zone_high is not None else None,
        buy_zone_entry_at=used[entry_index]['timestamp'] if entry_index is not None else None,
        post_entry_reference_price=base if after else None,
        post_entry_MFE=max(0,(max(b['high'] for b in after)/entry_price-1)*100) if after else None,
        post_entry_MAE=min(0,(min(b['low'] for b in after)/entry_price-1)*100) if after else None,
        buy_zone_entry_resolution=resolution)


def result_issue(row,result,current,horizon,holiday=None):
    if not isinstance(result,dict) or result.get('completed') is not True:return 'PENDING'
    if result.get('measurement_version')!=VERSION:return 'UNVERIFIED_OUTCOME'
    observed=stamp(result.get('observed_at'));due=due_at(row,horizon,holiday)
    if not observed or observed>current or observed<due or current<due or stamp(result.get('end_at'))!=due:return 'FUTURE_OR_UNVERIFIED_OUTCOME'
    base=prediction_price(row);close=number(result.get('close_price'));change=number(result.get('direction_return'))
    if not close or close<=0 or number(result.get('prediction_price'))!=base or change is None:return 'INVALID_PRICE'
    if not math.isclose(change,direction_return(base,close,side(row)),abs_tol=.0001):return 'RETURN_MISMATCH'
    if result.get('target_stop_status')=='AMBIGUOUS':return 'AMBIGUOUS'
    mfe=number(result.get('MFE'));mae=number(result.get('MAE'))
    if mfe is None or mae is None or mfe<0 or mae>0:return 'INVALID_EXCURSIONS'
    high,low=number(result.get('high_price')),number(result.get('low_price'))
    raw=number(result.get('raw_return'))
    if not high or not low or not 0<low<=close<=high or raw is None or not math.isclose(raw,(close/base-1)*100,abs_tol=.0001):return 'INVALID_OHLC_SUMMARY'
    expected_mfe=max(0,direction_return(base,high if side(row)=='AL' else low,side(row)))
    expected_mae=min(0,direction_return(base,low if side(row)=='AL' else high,side(row)))
    if not math.isclose(mfe,expected_mfe,abs_tol=.0001) or not math.isclose(mae,expected_mae,abs_tol=.0001):return 'EXCURSION_MISMATCH'
    return None


def conditions(row):
    result={};votes=row.get('confirmations') or {}
    numeric=lambda key:number(row.get(key)) is not None
    bb=row.get('Bollinger');candle=row.get('candle_summary')
    available={'VWAP':numeric('VWAP') and prediction_price(row) is not None,'EMA':numeric('EMA9') and numeric('EMA21'),
        'RSI':numeric('RSI'),'MACD':numeric('MACD') and numeric('MACD_histogram'),'VOLUME':numeric('volume_ratio'),
        'OBV':numeric('OBV'),'BOLLINGER':isinstance(bb,dict) and all(number(bb.get(k)) is not None for k in ('middle','upper','lower')),
        'MOMENTUM':numeric('momentum'),'CANDLE':isinstance(candle,dict) and number(candle.get('close_position_pct')) is not None}
    if isinstance(votes,dict):
        for name in ('VWAP','EMA','RSI','MACD','VOLUME','OBV','BOLLINGER','MOMENTUM','CANDLE'):
            if available[name] and votes.get(name) in ('AL','SAT','NEUTRAL'):result[name]=votes[name]
    histogram=number(row.get('MACD_histogram'))
    if histogram is not None:result['MACD_HISTOGRAM']='POSITIVE' if histogram>0 else 'NEGATIVE' if histogram<0 else 'ZERO'
    value=number(row.get('RSI'))
    if value is not None and 0<=value<=100:result['RSI_BUCKET']='<30' if value<30 else '30-49' if value<50 else '50-69' if value<70 else '70+'
    atr=number(row.get('ATR'));price=prediction_price(row)
    if atr is not None and price and price>0:result['ATR_VOLATILITY']='<1%' if atr/price<.01 else '1-2%' if atr/price<.02 else '2%+'
    for name,key,bands in (('VOLUME_RATIO','volume_ratio',(100,130,200)),('RISK_REWARD','risk_reward_ratio',(1,1.5,2)),('EXTENSION','extended_move_penalty',(1,10,30))):
        value=number(row.get(key))
        if value is not None:result[name]=next((f'<{b}' for b in bands if value<b),f'{bands[-1]}+')
    if row.get('breakout_status') in ('CONFIRMED','WEAK_CONFIRMATION','WAITING'):result['BREAKOUT']=row['breakout_status']
    for combo in COMBINATIONS:
        if all(name in result for name in combo):result['+'.join(combo)]='AL' if all(result[name]=='AL' for name in combo) else 'SAT' if all(result[name]=='SAT' for name in combo) else 'MIXED'
    return result


class MeasurementStats(Stats):
    def __init__(self):super().__init__();self.targets=self.stops=self.levels=0
    def observe(self,result,issue):
        self.total+=1
        if issue:
            if issue=='PENDING':self.pending+=1
            else:self.excluded[issue]+=1
            return
        self.raw.append(result['raw_return']);self.returns.append(result['direction_return'])
        self.mfe.append(result['MFE']);self.mae.append(result['MAE'])
        if result['levels_available']:
            self.levels+=1;self.targets+=int(result['target_hit']);self.stops+=int(result['stop_hit'])
    def export(self):
        value=super().export()
        return dict(value,sample_count=self.total,completed_count=value['completed'],pending_count=self.pending,
            success_count=value['positive'],failure_count=value['negative'],mean_direction_return=value['mean_return'],
            median_direction_return=value['median_return'],mean_MFE=value['mean_mfe'],mean_MAE=value['mean_mae'],
            target_hit_rate=self.targets/self.levels if self.levels else None,stop_hit_rate=self.stops/self.levels if self.levels else None,
            levels_sample_count=self.levels,ambiguous_count=self.excluded['AMBIGUOUS'])


def clean_dataset(observed,results,current,holiday=None):
    for row,issue in observed:
        if issue:continue
        stored=results.get(row['event_id'],{})
        if stored.get('source_hash')!=fingerprint(row):continue
        for horizon in HORIZONS:
            result=stored.get('outcomes',{}).get(horizon)
            if result_issue(row,result,current,horizon,holiday):continue
            yield {'event_id':row['event_id'],'symbol':row['symbol'],'signal_at':row['timestamp'],
                'horizon':horizon,'features':{k:copy.deepcopy(row[k]) for k in FROZEN_FIELDS if k in row},
                'outcome':copy.deepcopy(result)}


def _aggregate_threshold(observed,results,current,threshold,holiday=None):
    groups={}
    for row,source_error in observed:
        at=stamp(row.get('timestamp'))
        if not at:continue
        stored=results.get(row.get('event_id'),{});conf=number(row.get('confidence_score'),0)
        features=conditions(row) if not source_error else {}
        for horizon in HORIZONS:
            result=stored.get('outcomes',{}).get(horizon)
            issue=source_error or ('SOURCE_HASH_CONFLICT' if stored and stored.get('source_hash')!=fingerprint(row) else result_issue(row,result,current,horizon,holiday))
            for period,days in PERIODS.items():
                if days is not None and at<current-timedelta(days=days):continue
                for threshold in (threshold,):
                    if conf<threshold:continue
                    state=row.get('signal_state');state=state if isinstance(state,str) and state in STATES else 'UNKNOWN'
                    key=(period,horizon,side(row) or 'IZLE',state,threshold)
                    group=groups.setdefault(key,{'summary':MeasurementStats(),'technical':{},'confidence':{},'confirmation':{},'indicators':{}})
                    group['summary'].observe(result,issue)
                    for field,value in (('technical',score_band(row.get('technical_score'))),('confidence',score_band(conf))):
                        if value is not None:group[field].setdefault(value,MeasurementStats()).observe(result,issue)
                    count,total=number(row.get('confirmation_count')),number(row.get('confirmation_total'))
                    if count is not None and total is not None and count==int(count) and total==int(total) and 0<=count<=total<=100 and total>0:
                        group['confirmation'].setdefault(f'{int(count)}/{int(total)}',MeasurementStats()).observe(result,issue)
                    for indicator,condition in features.items():group['indicators'].setdefault(indicator,{}).setdefault(condition,MeasurementStats()).observe(result,issue)
    output=[]
    for key,group in sorted(groups.items()):
        period,horizon,signal,state,threshold=key
        output.append({'period':period,'horizon':horizon,'signal':signal,'state':state,'min_confidence':threshold,
            'summary':group['summary'].export(),
            **{name:{k:v.export() for k,v in group[name].items()} for name in ('technical','confidence','confirmation')},
            'indicators':{k:{condition:stat.export() for condition,stat in values.items()} for k,values in group['indicators'].items()}})
    return output


def aggregate(observed,results,current,holiday=None):
    # Release sample arrays between thresholds instead of retaining seven copies.
    output=[]
    for threshold in CONFIDENCE_FILTERS:
        output.extend(_aggregate_threshold(observed,results,current,threshold,holiday))
    return {'version':VERSION,'updated_at':current.isoformat(),'analysis_only':True,'horizons':list(HORIZONS),
            'reliability_thresholds':RELIABILITY,'confidence_filters':list(CONFIDENCE_FILTERS),'groups':output,
            'snapshot_count':len(observed),'clean_example_count':sum(1 for _ in clean_dataset(observed,results,current,holiday)),
            'period_basis':'FROZEN_SIGNAL_TIME'}


def publish(location,observed,results,current,holiday=None,diagnostics=None):
    report=aggregate(observed,results,current,holiday);report['diagnostics']=diagnostics or {}
    target=location.public_file('intraday_signal_performance.json')
    with locked(target):atomic_json(target,report)
    return report


def api_report(query,location=None):
    if set(query)-{'signal','state','horizon','period','min_confidence','indicator','condition'} or any(len(v)!=1 for v in query.values()):raise RecordError('Geçersiz performans filtresi.',400)
    filters={k:v[0] for k,v in query.items()};h=filters.get('horizon','60m');period=filters.get('period','all_time')
    try:threshold=float(filters.get('min_confidence',0))
    except (ValueError,TypeError):raise RecordError('Geçersiz güven filtresi.',400) from None
    if h not in HORIZONS or period not in PERIODS or threshold not in CONFIDENCE_FILTERS or filters.get('signal') not in (None,'AL','SAT','IZLE') or filters.get('state') not in STATES|{None}:
        raise RecordError('Geçersiz vade/dönem/sinyal/güven.',400)
    known=set(CONDITIONS)
    if filters.get('indicator') is not None and filters['indicator'] not in known:raise RecordError('Geçersiz indikatör.',400)
    if 'condition' in filters and ('indicator' not in filters or filters['condition'] not in CONDITIONS[filters['indicator']]):raise RecordError('Geçersiz koşul.',400)
    try:
        report=json.loads((location or paths()).public_file('intraday_signal_performance.json').read_bytes())
        if report['version']!=VERSION or report['analysis_only'] is not True or not isinstance(report['groups'],list) or not stamp(report['updated_at']):raise ValueError('Cache')
        groups=[g for g in report['groups'] if g['horizon']==h and g['period']==period and g['min_confidence']==threshold
                and all(filters.get(k) is None or g[k]==filters[k] for k in ('signal','state'))]
        if 'indicator' in filters:
            groups=[dict(g,indicator_statistics={k:v for k,v in g['indicators'].get(filters['indicator'],{}).items() if 'condition' not in filters or k==filters['condition']}) for g in groups]
        return dict(report,groups=groups,filters=dict(filters,horizon=h,period=period,min_confidence=threshold))
    except Exception:raise RecordError('Günlük AL/SAT performansı henüz kullanılamıyor.',503) from None
