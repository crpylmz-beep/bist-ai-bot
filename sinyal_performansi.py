"""Read-only, descriptive analysis of the existing frozen prediction histories.

No quotes, scoring, weight updates or raw-history writes are allowed here.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean, median, pstdev
from functools import lru_cache
import math
import hashlib
import json

from ai_karar_motoru import HORIZONS, ISTANBUL, number, stamp, load, locked
from kullanici_kayitlari import atomic_json
from veri_yollari import paths

VERSION = 'SIGNAL_ANALYSIS_V1'
# Counts of independently recorded, verified outcomes, not a statistical guarantee.
RELIABILITY = {'LOW': 30, 'MEDIUM': 100, 'HIGH': 300}
PERIODS = (7, 30, 90, None)
UP = {'AL', 'GUCLU_AL', 'AGRESIF_ALIS', 'ASIRI_SATIM'}
DOWN = {'SAT', 'GUCLU_SAT', 'AGRESIF_SATIS'}
FEATURES = ('rsi', 'macd', 'signal', 'hacim_orani', 'sma20', 'sma50',
            'vwap20_durum', 'obv_durum', 'boll_durum', 'momentum15',
            'teknik_skor', 'confidence', 'continuation_probability',
            'early_move_score', 'sustainability_score', 'extended_move_penalty',
            'future_opportunity_score')


def reliability(count):
    return next((name for name in ('HIGH', 'MEDIUM', 'LOW') if count >= RELIABILITY[name]), 'INSUFFICIENT')


def signal(row):
    if row.get('model') == 'YARIN_TOP10' or row.get('yarin_top10'): return 'YARIN_TOP10'
    return str(row.get('sinyal') or row.get('sinyal_sinifi') or row.get('karar') or 'BILINMIYOR')


def direction(row):
    if signal(row) == 'YARIN_TOP10': return 1
    # Explicit decision takes precedence. Overbought alone is not a sell forecast.
    decision = str(row.get('karar'))
    if decision in UP: return 1
    if decision in DOWN: return -1
    if signal(row) in UP or row.get('guclu_tepki') or row.get('tepki_top10'): return 1
    if signal(row) in DOWN: return -1
    return None


def features(row):
    """Whitelist only frozen inputs; outcome/MFE/MAE never become input features."""
    source = row.get('kriterler') or row.get('girdiler') or {}
    raw = dict(source) if isinstance(source, dict) else {}
    raw.update({key: value for key, value in row.items() if key not in raw})
    snapshot = row.get('indicator_snapshot') or {}
    if isinstance(snapshot,dict) and isinstance(snapshot.get('inputs'),dict):
        raw.update(snapshot['inputs'])
    opportunity = row.get('positive_opportunity') or {}
    if not isinstance(opportunity, dict): opportunity = {}
    for key in FEATURES:
        if raw.get(key) is None and opportunity.get(key) is not None: raw[key] = opportunity[key]
    if raw.get('teknik_skor') is None: raw['teknik_skor'] = raw.get('teknik_puan', raw.get('puan', raw.get('ai_score')))
    if raw.get('confidence') is None: raw['confidence'] = raw.get('guven', raw.get('guven_skoru'))
    result = {}
    for key in FEATURES:
        value = raw.get(key)
        if key in ('vwap20_durum', 'obv_durum', 'boll_durum'):
            if isinstance(value, str): result[key] = value
        elif number(value) is not None: result[key] = number(value)
    return result


def score_band(value):
    value = number(value)
    if value is None or not 0 <= value <= 100: return None
    if value < 50: return '0-49'
    lower = min(90, int(value // 10) * 10)
    return f'{lower}-{100 if lower == 90 else lower + 9}'


def buckets(frozen):
    groups = {}
    rsi = number(frozen.get('rsi'))
    if rsi is not None and 0 <= rsi <= 100:
        groups['RSI'] = '<30' if rsi < 30 else '30-49' if rsi < 50 else '50-69' if rsi < 70 else '70+'
    macd, sig = number(frozen.get('macd')), number(frozen.get('signal'))
    if macd is not None and sig is not None: groups['MACD'] = 'USTUNDE' if macd > sig else 'ALTINDA_VEYA_ESIT'
    volume = number(frozen.get('hacim_orani'))
    if volume is not None and volume >= 0: groups['HACIM'] = '<100' if volume < 100 else '100-149' if volume < 150 else '150+'
    a, b = number(frozen.get('sma20')), number(frozen.get('sma50'))
    if a is not None and b is not None: groups['SMA_TREND'] = 'USTUNDE' if a > b else 'ALTINDA_VEYA_ESIT'
    for key in ('vwap20_durum', 'obv_durum', 'boll_durum'):
        if frozen.get(key) in ('USTUNDE', 'ALTINDA', 'YUKSELEN', 'DUSEN', 'POZITIF', 'NEGATIF', 'YATAY', 'BANT_ICINDE', 'UST_BANT', 'ALT_BANT'):
            groups[key] = frozen[key]
    momentum = number(frozen.get('momentum15'))
    if momentum is not None: groups['MOMENTUM'] = 'POZITIF' if momentum > 0 else 'NEGATIF_VEYA_SIFIR'
    for key in FEATURES[10:]:
        band = score_band(frozen.get(key))
        if band is not None: groups[key] = band
    return groups


@lru_cache(maxsize=16384)
def end_session(day, horizon, holiday):
    from performans_motoru import sessions_after
    return sessions_after(day, horizon, holiday)[-1]


def frozen_feature_issue(row, at):
    """Shared provenance guard for learning outcomes and new rank candidates."""
    if not isinstance(row,dict):return 'MALFORMED'
    if any(row.get(key) is not None and not isinstance(row[key],dict) for key in ('kriterler','girdiler','teknik_gostergeler','criteria_snapshot','positive_opportunity','indicator_snapshot')):return 'MALFORMED'
    snapshot_value=row.get('indicator_snapshot')
    if isinstance(snapshot_value,dict) and (not stamp(snapshot_value.get('captured_at')) or not isinstance(snapshot_value.get('inputs'),dict)):
        return 'UNVERIFIED_FEATURES'
    indicator_snapshot=snapshot_value or {}
    technical=indicator_snapshot.get('technical') or {}
    if not isinstance(technical,dict):return 'MALFORMED'
    for source in (technical,row, row.get('kriterler') or {}, row.get('girdiler') or {}, row.get('teknik_gostergeler') or {}, row.get('criteria_snapshot') or {}, row.get('indicator_snapshot') or {}, row.get('positive_opportunity') or {}):
        for key in ('captured_at', 'asof', 'feature_timestamp'):
            recorded = stamp(source.get(key))
            if recorded and recorded > at: return 'FUTURE_FEATURES'
    return None


def quality(row, horizon, current, holiday=None):
    """Return one exclusion reason; never repair or invent an old label."""
    from performans_motoru import session_closed
    if not isinstance(row, dict): return 'MALFORMED'
    if any(row.get(key) is not None and not isinstance(row[key], dict) for key in ('kriterler', 'girdiler', 'teknik_gostergeler', 'criteria_snapshot', 'positive_opportunity', 'indicator_snapshot')): return 'MALFORMED'
    at = stamp(row.get('zaman') or row.get('tarih'))
    if not at or not isinstance(row.get('sembol'), str) or not row['sembol'].strip(): return 'MALFORMED'
    if at > current: return 'FUTURE_SIGNAL'
    if row.get('egitim_durumu') == 'REFERANS': return 'UNVERIFIED'
    if row.get('analysis_only') or any(word in str(row.get('model', '')) for word in ('SHADOW', 'BACKTEST', 'BASELINE')):
        return 'NON_LIVE'
    if row.get('performance_source') not in (None, 'LIVE'): return 'NON_LIVE'
    if any(row.get(key) for key in ('lookahead_suspected', 'legacy_unverified', 'unverified')): return 'UNVERIFIED'
    feature_error=frozen_feature_issue(row,at)
    if feature_error:return feature_error
    base = number(row.get('referans_fiyat'), number(row.get('fiyat')))
    if base is None or base <= 0: return 'MISSING_BASE_PRICE'
    target = number(row.get('hedef'), number(row.get('hedef1')))
    if target is None or target <= 0: return 'MISSING_TARGET_PRICE'
    sign = direction(row)
    if sign is None: return 'UNKNOWN_DIRECTION'
    if (target - base) * sign <= 0: return 'INVALID_TARGET_DIRECTION'
    result = row.get(f'sonuc_{horizon}g')
    if result is None: return 'PENDING'
    if not isinstance(result, dict): return 'MALFORMED_RESULT'
    if result.get('performance_source') not in (None, 'LIVE'): return 'NON_LIVE'
    if result.get('legacy_unverified') or result.get('degerlendirme_tamamlandi') is None: return 'UNVERIFIED'
    if result.get('degerlendirme_tamamlandi') is not True: return 'PENDING'
    day = end_session(at.date(), horizon, holiday)
    if not session_closed(day, current): return 'FUTURE_OUTCOME'
    observed = stamp(result.get('observed_at'))
    if not observed or observed > current or not session_closed(day, observed): return 'UNVERIFIED_TIME'
    if str(result.get('tarih', '')) != day.isoformat(): return 'INVALID_SESSION_DATE'
    close, change = number(result.get('fiyat')), number(result.get('getiri_yuzde'))
    if close is None or close <= 0 or change is None: return 'INVALID_RESULT_PRICE'
    if number(result.get('baslangic_fiyati')) != base or not math.isclose(change, (close/base-1)*100, abs_tol=.001):
        return 'BASE_OR_RETURN_MISMATCH'
    warnings = result.get('kalite_uyarilari') or []
    if not isinstance(warnings, list): return 'MALFORMED_RESULT'
    if 'OHLC_EKSIK' in warnings: return 'INCOMPLETE_OHLC'
    return None


def duplicate_key(row):
    identity = row.get('kayit_id') or row.get('id')
    if not identity: return None
    # Source/model distinguish independent forecasts; IDs alone cannot inflate
    # identical observations imported twice under different IDs.
    at = row.get('zaman') or row.get('tarih')
    return (str(row.get('sembol')), str(at), str(signal(row)),
            str(row.get('kaynak') or 'LEGACY'),str(row.get('model') or 'LEGACY'), bool(row.get('guclu_tepki')))


def unique_records(records):
    rows = {}; fingerprints = {}; conflicts = set(); ids = {}; duplicates = malformed = 0
    for row in records:
        if not isinstance(row, dict): malformed += 1; continue
        key = duplicate_key(row)
        if key is None: malformed += 1; continue
        # Compare complete frozen observation/labels, ignoring import IDs only.
        payload = {k: v for k, v in row.items() if k not in ('id', 'kayit_id', 'sinyal_id')}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        identity = str(row.get('kayit_id') or row.get('id'))
        if identity in ids and ids[identity] != key: conflicts.update((ids[identity], key))
        ids[identity] = key
        if key in rows:
            duplicates += 1
            if fingerprints[key] != fingerprint: conflicts.add(key)
        else: rows[key] = row; fingerprints[key] = fingerprint
    return [(row, key in conflicts) for key, row in rows.items()], duplicates, malformed


def excursions(row, horizon):
    result = row[f'sonuc_{horizon}g']
    directional = direction(row)*number(result.get('getiri_yuzde'))
    recorded = number(result.get('yon_getirisi'))
    if recorded is None or not math.isclose(recorded, directional, abs_tol=.001): return None, None
    mfe, mae = number(result.get('mfe_pct')), number(result.get('mae_pct'))
    return (mfe if mfe is not None and mfe >= 0 else None, mae if mae is not None and mae <= 0 else None)


def clean_dataset(records, current, holiday=None):
    """Yield verified learning examples without copying/writing raw histories."""
    rows, _, _ = unique_records(records)
    for row, conflict in rows:
        if conflict: continue
        for h in HORIZONS:
            if quality(row, h, current, holiday): continue
            result = row[f'sonuc_{h}g']; sign = direction(row)
            mfe, mae = excursions(row, h)
            yield {'id': row.get('kayit_id') or row.get('id'), 'sembol': row['sembol'], 'signal': signal(row), 'horizon': h,
                   'signal_at': row.get('zaman') or row.get('tarih'),
                   'features': {**features(row),'indicator_conditions':indicator_conditions(row)},
                   'outcome': {'return_pct': number(result['getiri_yuzde']), 'directional_return_pct': sign*number(result['getiri_yuzde']),
                               'mfe_pct': mfe, 'mae_pct': mae}}


class Stats:
    def __init__(self):
        self.total = self.pending = 0; self.excluded = Counter()
        self.raw = []; self.returns = []; self.mfe = []; self.mae = []
    def add(self, row, h, reason):
        self.total += 1
        if reason:
            if reason == 'PENDING': self.pending += 1
            else: self.excluded[reason] += 1
            return
        result = row[f'sonuc_{h}g']; sign = direction(row)
        self.raw.append(number(result['getiri_yuzde'])); self.returns.append(sign*number(result['getiri_yuzde']))
        mfe, mae = excursions(row, h)
        if mfe is not None: self.mfe.append(mfe)
        if mae is not None: self.mae.append(mae)
    def export(self):
        values = self.returns; wins = [x for x in values if x > 0]; losses = [x for x in values if x < 0]
        avg_win = mean(wins) if wins else None; avg_loss = mean(losses) if losses else None
        return {'total': self.total, 'completed': len(values), 'pending': self.pending, 'excluded': dict(sorted(self.excluded.items())),
                'sample_size': len(values), 'positive': len(wins), 'negative': len(losses), 'neutral': sum(x == 0 for x in values),
                'success_rate': len(wins)/len(values) if values else None, 'success_definition': 'DIRECTIONAL_RETURN_GT_ZERO',
                'reliability': reliability(len(values)), 'sufficient': len(values) >= RELIABILITY['LOW'],
                'mean_return': mean(values) if values else None, 'median_return': median(values) if values else None,
                'best_return': max(values) if values else None, 'worst_return': min(values) if values else None,
                'stddev': pstdev(values) if len(values) > 1 else None, 'mean_raw_price_return': mean(self.raw) if self.raw else None,
                'median_mfe': median(self.mfe) if self.mfe else None,
                'mean_mfe': mean(self.mfe) if self.mfe else None, 'mfe_samples': len(self.mfe),
                'median_mae': median(self.mae) if self.mae else None,
                'mean_mae': mean(self.mae) if self.mae else None, 'mae_samples': len(self.mae),
                'mean_positive_return': avg_win, 'mean_negative_return': avg_loss,
                'payoff_ratio': number(avg_win/abs(avg_loss)) if avg_win is not None and avg_loss else None,
                'profit_factor': number(sum(wins)/abs(sum(losses))) if losses else None}


def aggregate(records, current=None, holiday=None):
    current = (current or datetime.now(ISTANBUL)).astimezone(ISTANBUL)
    groups = defaultdict(Stats)
    rows, duplicates, malformed = unique_records(records)
    for row, conflict in rows:
        at = stamp(row.get('zaman') or row.get('tarih')); frozen = features(row)
        classification = signal(row); score = score_band(frozen.get('teknik_skor')); conditions = buckets(frozen)
        for h in HORIZONS:
            reason = 'DUPLICATE_CONFLICT' if conflict else quality(row, h, current, holiday)
            for days in PERIODS:
                # Cohort is prediction date, not completion date. Pending is counted
                # but never included in success denominators.
                if days is not None and (not at or not current-timedelta(days=days) <= at <= current): continue
                period = 'ALL' if days is None else str(days)
                keys = [('overall', 'ALL'), ('signals', classification)]
                if score: keys.append(('scores', score))
                keys += [('criteria', key+':'+value) for key, value in conditions.items()]
                for kind, name in keys: groups[(period, kind, name, str(h))].add(row, h, reason)
    periods = {}
    for (period, kind, name, h), stats in sorted(groups.items()):
        periods.setdefault(period, {}).setdefault(kind, {}).setdefault(name, {})[h] = stats.export()
    return {'version': VERSION, 'updated_at': current.isoformat(), 'analysis_only': True,
            'reliability_thresholds': RELIABILITY, 'time_filter': 'SIGNAL_TIMESTAMP',
            'return_basis': 'DIRECTIONAL; raw price return is separately reported',
            'duplicates': duplicates, 'malformed_records': malformed, 'periods': periods}


def publish(location, records, current):
    """Called only when the existing performance report is due; bounded derived data."""
    report = aggregate(records, current)
    report['indicator_analysis'] = aggregate_indicators(records,current)
    target = location.public_file('sinyal_performansi.json')
    with locked(target): atomic_json(target, report)
    return report


def read_report(location=None):
    """O(report size) service API; never parse large histories on web requests."""
    location = location or paths()
    return load(location.public_file('sinyal_performansi.json'),
                {'version': VERSION, 'status': 'PENDING_FIRST_REPORT', 'periods': {}})

# Real input names used by bist_bot/teknik_gostergeler; no provider calls.
INDICATOR_FIELDS = ('rsi','macd','signal','hist','hist_onceki','sma20','sma50',
                    'fiyat','hacim','hacim_orani','atr14','destek','direnc',
                    'risk_getiri','vwap20','vwap20_durum','obv_durum','boll_durum',
                    'ema9','ema21','momentum15','kapanis_pozisyonu','degisim')
CONDITIONS = {
 'RSI': ('0-29','30-39','40-49','50-59','60-69','70-100'),
 'MACD_SIGN': ('POSITIVE','NEGATIVE','ZERO'), 'MACD_SIGNAL': ('ABOVE','BELOW','EQUAL'),
 'HIST_SIGN': ('POSITIVE','NEGATIVE','ZERO'), 'HIST_TREND': ('IMPROVING','WORSENING','EQUAL'),
 'VOLUME': ('<80','80-119','120-149','150-199','200+'),
 'PRICE_SMA20': ('ABOVE','BELOW','EQUAL'), 'PRICE_SMA50': ('ABOVE','BELOW','EQUAL'),
 'SMA_TREND': ('ABOVE','BELOW','EQUAL'), 'EMA_TREND': ('ABOVE','BELOW','EQUAL'),
 'VWAP': ('ABOVE','BELOW','EQUAL'), 'OBV': ('POSITIVE','NEGATIVE','NEUTRAL'),
 'BOLLINGER': ('BELOW_LOWER','NEAR_LOWER','INSIDE','NEAR_UPPER','ABOVE_UPPER'),
 'BOLL_SQUEEZE': ('YES','NO'), 'BOLL_BREAKOUT': ('YES','NO'),
 'CONFIRMATION_COUNT': tuple(f'{n}/6' for n in range(7)),
 'ATR': ('<2%','2-4%','4%+'), 'MOMENTUM': ('POSITIVE','NEGATIVE','ZERO'),
 'CONFIRMATIONS': ('0-24%','25-49%','50-74%','75-100%'),
 'COMBO_RSI_MACD': ('CONFIRMED','NOT_CONFIRMED'),
 'COMBO_MACD_VOLUME': ('CONFIRMED','NOT_CONFIRMED'),
 'COMBO_RSI_VOLUME': ('CONFIRMED','NOT_CONFIRMED'),
 'COMBO_VWAP_OBV': ('CONFIRMED','NOT_CONFIRMED'),
 'COMBO_TREND_VOLUME': ('CONFIRMED','NOT_CONFIRMED'),
 'COMBO_RSI_MACD_VOLUME': ('CONFIRMED','NOT_CONFIRMED')}


def capture_indicators(row, at):
    """Called only for new predictions. Copy actual inputs, never fill defaults."""
    import copy
    inputs = {k: copy.deepcopy(row[k]) for k in INDICATOR_FIELDS if row.get(k) is not None}
    final = row.get('nihai_karar') or {}
    if isinstance(final, dict):
        for key in ('teyit_sayisi','teyit_toplam'):
            if final.get(key) is not None: inputs[key] = final[key]
    snapshot={'version':'INDICATOR_INPUTS_V1','captured_at':at,'inputs':inputs}
    if isinstance(row.get('teknik_gostergeler'),dict): snapshot['technical']=copy.deepcopy(row['teknik_gostergeler'])
    if indicator_enabled(): snapshot['feature_evidence']=safe_feature_capture(row,at)
    return snapshot


def indicator_inputs(row):
    snapshot = row.get('indicator_snapshot')
    if isinstance(snapshot,dict):
        values=dict(snapshot.get('inputs') or {}) if isinstance(snapshot.get('inputs'),dict) else {}
        return structured_inputs(values,snapshot.get('technical') or {})
    # Old explicit frozen fields are usable; absent ones remain unavailable.
    values = dict(row.get('kriterler') or {}) if isinstance(row.get('kriterler'),dict) else {}
    values.update({k:row[k] for k in INDICATOR_FIELDS if row.get(k) is not None})
    final = row.get('nihai_karar') or {}
    if isinstance(final,dict):
        for key in ('teyit_sayisi','teyit_toplam'):
            if final.get(key) is not None: values[key]=final[key]
    return structured_inputs(values,row.get('teknik_gostergeler') or {})


def structured_inputs(values,technical):
    if not isinstance(technical,dict): return values
    for name in ('obv','vwap','bollinger'):
        group=technical.get(name) or {}
        if not isinstance(group,dict) or group.get('status')!='OK':continue
        if name=='obv':
            values.setdefault('obv_durum',{'OBV_YUKSELEN':'YUKSELEN','OBV_DUSEN':'DUSEN','OBV_YATAY':'YATAY'}.get(group.get('trend')))
        if name=='vwap':values.setdefault('vwap20',group.get('session_value'))
        if name=='bollinger':
            price=number(values.get('fiyat'));upper,lower=number(group.get('upper')),number(group.get('lower'))
            if price is not None and upper is not None and lower is not None:values.setdefault('boll_durum','UST_BANT_USTU' if price>upper else 'ALT_BANT_ALTI' if price<lower else 'BANT_ICINDE')
            if isinstance(group.get('squeeze'),bool):values['boll_squeeze']=group['squeeze']
            if isinstance(group.get('upper_break'),bool):values['boll_upper_break']=group['upper_break']
    return values


def indicator_conditions(row):
    values=indicator_inputs(row); found={}
    def n(key): return number(values.get(key))
    def compare(name,a,b):
        if a is not None and b is not None: found[name]='ABOVE' if a>b else 'BELOW' if a<b else 'EQUAL'
    def sign(name,value):
        if value is not None: found[name]='POSITIVE' if value>0 else 'NEGATIVE' if value<0 else 'ZERO'
    rsi=n('rsi')
    if rsi is not None and 0<=rsi<=100:
        found['RSI']='0-29' if rsi<30 else '30-39' if rsi<40 else '40-49' if rsi<50 else '50-59' if rsi<60 else '60-69' if rsi<70 else '70-100'
    sign('MACD_SIGN',n('macd'));compare('MACD_SIGNAL',n('macd'),n('signal'))
    sign('HIST_SIGN',n('hist'))
    if n('hist') is not None and n('hist_onceki') is not None:
        found['HIST_TREND']='IMPROVING' if n('hist')>n('hist_onceki') else 'WORSENING' if n('hist')<n('hist_onceki') else 'EQUAL'
    volume=n('hacim_orani')
    if volume is not None and volume>=0:
        found['VOLUME']='<80' if volume<80 else '80-119' if volume<120 else '120-149' if volume<150 else '150-199' if volume<200 else '200+'
    price=n('fiyat')
    for name,key in (('PRICE_SMA20','sma20'),('PRICE_SMA50','sma50')): compare(name,price,n(key))
    compare('SMA_TREND',n('sma20'),n('sma50'));compare('EMA_TREND',n('ema9'),n('ema21'))
    compare('VWAP',price,n('vwap20'))
    if 'VWAP' not in found and values.get('vwap20_durum') in ('USTUNDE','ALTINDA','ESIT'):
        found['VWAP']={'USTUNDE':'ABOVE','ALTINDA':'BELOW','ESIT':'EQUAL'}[values['vwap20_durum']]
    obv=values.get('obv_durum')
    if obv in ('YUKSELEN','POZITIF'):found['OBV']='POSITIVE'
    elif obv in ('DUSEN','NEGATIF'):found['OBV']='NEGATIVE'
    elif obv=='YATAY':found['OBV']='NEUTRAL'
    bb={'ALT_BANT_ALTI':'BELOW_LOWER','ALT_BANDA_YAKIN':'NEAR_LOWER','BANT_ICINDE':'INSIDE',
        'UST_BANDA_YAKIN':'NEAR_UPPER','UST_BANT_USTU':'ABOVE_UPPER'}
    if isinstance(values.get('boll_durum'),str) and values['boll_durum'] in bb:found['BOLLINGER']=bb[values['boll_durum']]
    for key,name in (('boll_squeeze','BOLL_SQUEEZE'),('boll_upper_break','BOLL_BREAKOUT')):
        if isinstance(values.get(key),bool):found[name]='YES' if values[key] else 'NO'
    if n('atr14') is not None and n('atr14')>0 and price is not None and price>0:
        atr=100*n('atr14')/price;found['ATR']='<2%' if atr<2 else '2-4%' if atr<4 else '4%+'
    sign('MOMENTUM',n('momentum15'))
    count,total=n('teyit_sayisi'),n('teyit_toplam')
    if count is not None and total is not None and total>0 and 0<=count<=total:
        if total==6 and count==int(count):found['CONFIRMATION_COUNT']=str(int(count))+'/6'
        fraction=count/total;found['CONFIRMATIONS']='0-24%' if fraction<.25 else '25-49%' if fraction<.5 else '50-74%' if fraction<.75 else '75-100%'
    checks={'RSI':None if rsi is None or not 0<=rsi<=100 else 30<=rsi<70,
            'MACD':None if 'MACD_SIGNAL' not in found else found['MACD_SIGNAL']=='ABOVE',
            'VOLUME':None if volume is None or volume<0 else volume>=150,
            'VWAP':None if 'VWAP' not in found else found['VWAP']=='ABOVE',
            'OBV':None if 'OBV' not in found else found['OBV']=='POSITIVE',
            'TREND':None if 'SMA_TREND' not in found else found['SMA_TREND']=='ABOVE'}
    for name,keys in (('RSI_MACD',('RSI','MACD')),('MACD_VOLUME',('MACD','VOLUME')),
                      ('RSI_VOLUME',('RSI','VOLUME')),('VWAP_OBV',('VWAP','OBV')),
                      ('TREND_VOLUME',('TREND','VOLUME')),('RSI_MACD_VOLUME',('RSI','MACD','VOLUME'))):
        if all(checks[k] is not None for k in keys):found['COMBO_'+name]='CONFIRMED' if all(checks[k] for k in keys) else 'NOT_CONFIRMED'
    return found


def aggregate_indicators(records,current,holiday=None):
    rows,duplicates,malformed=unique_records(records);groups=defaultdict(Stats);missing=Counter()
    for row,conflict in rows:
        found=indicator_conditions(row);at=stamp(row.get('zaman') or row.get('tarih'))
        for indicator in CONDITIONS:
            if indicator not in found:missing[indicator]+=1
        for h in HORIZONS:
            reason='DUPLICATE_CONFLICT' if conflict else quality(row,h,current,holiday)
            for period in PERIODS:
                if period is not None and (not at or not current-timedelta(days=period)<=at<=current):continue
                for indicator,condition in found.items():
                    for kind in ('ALL',signal(row)):
                        groups[(indicator,condition,kind,h,'ALL' if period is None else str(period))].add(row,h,reason)
    output=[]
    for (indicator,condition,kind,h,period),stats in sorted(groups.items()):
        result=stats.export();output.append({'indicator':indicator,'condition':condition,'signal_type':kind,'horizon':h,'period':period,
            **result,'wins':result['positive'],'losses':result['negative'],'failures':result['negative']+result['neutral'],'sample_count':result['sample_size']})
    return {'rows':output,'unavailable':dict(missing),'unavailable_scope':'ALL_INPUT_RECORDS','duplicates':duplicates,'malformed_records':malformed,
            'reliability_thresholds':RELIABILITY,'analysis_only':True,'updated_at':current.isoformat()}


def indicator_report(query,location=None):
    """Validate filters before reading the small shared report cache."""
    if not set(query)&{'condition','signal_type','period'}:
        return advanced_indicator_report(query,location)
    from kullanici_kayitlari import RecordError
    allowed={'indicator','condition','signal_type','horizon','period'}
    if set(query)-allowed or any(len(v)!=1 for v in query.values()):raise RecordError('Geçersiz analiz sorgusu.')
    params={k:v[0] for k,v in query.items()}
    if 'indicator' in params and params['indicator'] not in CONDITIONS:raise RecordError('Geçersiz indikatör.')
    if 'condition' in params and params['condition'] not in {v for values in CONDITIONS.values() for v in values}:raise RecordError('Geçersiz koşul.')
    if 'indicator' in params and 'condition' in params and params['condition'] not in CONDITIONS[params['indicator']]:raise RecordError('Koşul indikatörle uyumsuz.')
    if 'horizon' in params and params['horizon'] not in {str(h) for h in HORIZONS}:raise RecordError('Geçersiz vade.')
    if 'period' in params and params['period'] not in ('7','30','90','ALL'):raise RecordError('Geçersiz dönem.')
    if 'signal_type' in params and params['signal_type'] not in UP|DOWN|{'ALL','YARIN_TOP10','ASIRI_ALIM','NOTR','NÖTR','BILINMIYOR'}:raise RecordError('Geçersiz sinyal türü.')
    try:cached=read_report(location)
    except (json.JSONDecodeError,UnicodeError):raise RecordError('Analiz önbelleği yeniden hazırlanmalı.',503) from None
    if not isinstance(cached,dict):raise RecordError('Analiz önbelleği geçersiz.',503)
    report=cached.get('indicator_analysis',{})
    if not isinstance(report,dict) or not isinstance(report.get('rows',[]),list) or any(not isinstance(r,dict) for r in report.get('rows',[])):
        raise RecordError('Analiz önbelleği geçersiz.',503)
    rows=[r for r in report.get('rows',[]) if all(str(r.get(k))==v for k,v in params.items())]
    return {**report,'rows':rows,'status':'READY' if report else 'PENDING_FIRST_REPORT'}

# Versioned observation/candidate extension of this existing central analysis.
# None of these weights is read by a scoring engine.
INDICATOR_VERSION='INDICATOR_PERFORMANCE_V1'
FEATURE_SCHEMA='INDICATOR_FEATURES_V1'
WEIGHT_VERSION='INDICATOR_WEIGHT_CANDIDATE_V1'
SAMPLE_LIMITS={'EARLY':30,'USABLE':100,'STRONG_SAMPLE':300}
INDICATOR_IDS=('RSI','MACD','MACD_HISTOGRAM','SMA20','SMA50','SMA20_SMA50','VOLUME','VWAP','OBV','BOLLINGER','MOMENTUM','CANDLE_CONFIRMATION','SUPPORT_RESISTANCE','RISK_REWARD','MARKET_REGIME','SECTOR_STRENGTH')
INDICATOR_NAMES={'RSI':'RSI','MACD':'MACD','MACD_HISTOGRAM':'MACD Histogramı','SMA20':'SMA20','SMA50':'SMA50','SMA20_SMA50':'SMA20/SMA50 Trendi','VOLUME':'Hacim','VWAP':'VWAP','OBV':'OBV','BOLLINGER':'Bollinger','MOMENTUM':'Momentum','CANDLE_CONFIRMATION':'Mum Teyidi','SUPPORT_RESISTANCE':'Destek/Direnç','RISK_REWARD':'Risk/Getiri','MARKET_REGIME':'Piyasa Rejimi','SECTOR_STRENGTH':'Sektör Gücü'}
INDICATOR_COMBINATIONS=(('RSI','MACD'),('MACD','VOLUME'),('VWAP','OBV'),('RSI','BOLLINGER'),('SMA20_SMA50','VOLUME'))
INDICATOR_FAMILIES=('TOMORROW_TOP10','INTRADAY_BUY','INTRADAY_SELL','AGGRESSIVE_BUY','AGGRESSIVE_SELL','OVERSOLD_REACTION','TREND')
INDICATOR_HORIZONS=tuple(str(h) for h in HORIZONS)+('30m','60m','120m','SEANS')
RETURN_CLIP=10.0
SHRINKAGE_PRIOR=100


def indicator_enabled():
    import os
    return os.environ.get('INDICATOR_PERFORMANCE_ENABLED','true').strip().lower() in ('true','1','yes','on')


def capture_feature_evidence(row,at,intraday=False,location=None):
    """New-record hook only: preserve actual votes, never infer active from a value."""
    import copy
    from performans_motoru import business_day,session_closed
    current=stamp(at);tech=row.get('indicator_snapshot') if intraday else row.get('teknik_gostergeler')
    tech=tech if isinstance(tech,dict) else {};known=stamp(tech.get('asof'));bar=stamp(tech.get('data_time'))
    mode='INTRADAY' if intraday or tech.get('mode')=='INTRADAY' else 'TOMORROW'
    valid=bool(current and known and bar and known<=current and bar<=known and tech.get('mode')==mode)
    if valid and mode=='TOMORROW':
        close_at=bar.replace(hour=18,minute=15,second=0,microsecond=0)
        valid=business_day(bar.date()) and session_closed(bar.date(),current) and known>=close_at and (bar.hour,bar.minute)>=(18,10)
    if valid and mode=='INTRADAY':valid=bar+timedelta(minutes=5)<=known
    closing=tech.get('closing') or {}
    if not isinstance(closing,dict):closing={}
    flags=(row.get('criteria_snapshot') or {}).get('flags',{}) if isinstance(row.get('criteria_snapshot'),dict) else {}
    votes=row.get('confirmations') or {};votes=votes if isinstance(votes,dict) else {}
    criterion_at=stamp((row.get('criteria_snapshot') or {}).get('captured_at'))
    model_at=stamp((row.get('criteria_snapshot') or {}).get('model_created_at'))
    if not criterion_at or not current or criterion_at>current or model_at and model_at>current:flags={}
    final=row.get('nihai_karar') or {};final=final if isinstance(final,dict) else {}
    final_at=stamp(final.get('updated_at'))
    final_flags=final.get('kullanilan_kriterler',{}) if final_at and current and final_at<=current else {}
    final_keys={'SMA20_SMA50':'trend','VOLUME':'volume','OBV':'obv','BOLLINGER':'bollinger','MOMENTUM':'momentum','SUPPORT_RESISTANCE':'price','RISK_REWARD':'risk'}
    mapping={'RSI':'RSI','MACD':'MACD','MACD_HISTOGRAM':'MACD','SMA20_SMA50':'SMA_TREND','VOLUME':'HACIM','VWAP':'VWAP','OBV':'OBV_TREND','BOLLINGER':'BOLLINGER_KIRILIM','MOMENTUM':'MOMENTUM','SUPPORT_RESISTANCE':'DESTEK_DIRENC','RISK_REWARD':'RISK_GETIRI'}
    raw={'RSI':row.get('RSI') if intraday else closing.get('rsi',row.get('rsi5') if mode=='INTRADAY' else row.get('rsi')),
        'MACD':row.get('MACD') if intraday else row.get('macd5') if mode=='INTRADAY' else row.get('macd'),
        'MACD_HISTOGRAM':row.get('MACD_histogram') if intraday else closing.get('macd_histogram',row.get('hist')),
        'SMA20':closing.get('sma20',row.get('sma20')),'SMA50':closing.get('sma50',row.get('sma50')),
        'SMA20_SMA50':number(closing.get('sma20',row.get('sma20')))-number(closing.get('sma50',row.get('sma50'))) if number(closing.get('sma20',row.get('sma20'))) is not None and number(closing.get('sma50',row.get('sma50'))) is not None else None,
        'VOLUME':row.get('volume_ratio') if intraday else row.get('hacim3_orani') if mode=='INTRADAY' else row.get('hacim_orani'),
        'VWAP':row.get('VWAP') if intraday else (tech.get('vwap') or {}).get('session_value'),
        'OBV':row.get('OBV') if intraday else (tech.get('obv') or {}).get('value'),
        'BOLLINGER':(tech.get('bollinger') or {}).get('middle'),'MOMENTUM':(tech.get('momentum') or {}).get('short_pct'),
        'CANDLE_CONFIRMATION':(row.get('candle_summary') or {}).get('close_position_pct') if intraday else (tech.get('momentum') or {}).get('close_position_pct'),
        'SUPPORT_RESISTANCE':row.get('support') if intraday else row.get('destek'),'RISK_REWARD':row.get('risk_reward_ratio') if intraday else row.get('risk_getiri',row.get('karar_rr'))}
    features={}
    for key in INDICATOR_IDS[:-2]:
        value=number(raw.get(key));available=valid and value is not None
        vote=votes.get('CANDLE' if key=='CANDLE_CONFIRMATION' else 'MACD' if key=='MACD_HISTOGRAM' else key)
        flag=flags.get(mapping.get(key)) if isinstance(flags,dict) else None
        active=vote in ('AL','SAT') if vote in ('AL','SAT','NEUTRAL') else flag if isinstance(flag,bool) else None
        existing=final_flags.get(final_keys.get(key)) if isinstance(final_flags,dict) else None
        if active is None and existing in (-1,0,1) and not isinstance(existing,bool):active=existing!=0
        state='POSITIVE' if vote=='AL' else 'NEGATIVE' if vote=='SAT' else 'NEUTRAL' if vote=='NEUTRAL' else 'POSITIVE' if flag is True else 'NEUTRAL' if flag is False else 'POSITIVE' if existing==1 else 'NEGATIVE' if existing==-1 else 'NEUTRAL' if existing==0 else 'UNKNOWN'
        features[key]={'available':available,'value':value if available else None,'state':state if available else 'UNAVAILABLE',
                       'active':active if available else None,'confirmed':(vote==('SAT' if row.get('signal')=='SAT_ADAYI' else 'AL') if vote in ('AL','SAT','NEUTRAL') else active) if available else None}
    market={};sector={}
    if current and indicator_enabled():
        from piyasa_baglami import frozen_market_context,frozen_sector_context
        location=location or paths()
        market=frozen_market_context(indicator_context_file(location.public/'market_context.json'),current)
        sector=frozen_sector_context(indicator_context_file(location.public/'sector_context.json'),row.get('symbol') or row.get('sembol'),current)
    for key,context,field in (('MARKET_REGIME',market,'market_regime'),('SECTOR_STRENGTH',sector,'sector_state')):
        value=context.get(field);features[key]={'available':value is not None,'value':value,'state':'NEUTRAL' if value else 'UNAVAILABLE','active':None,'confirmed':None,'feature_type':'CONTEXT_FEATURE'}
    return {'schema_version':FEATURE_SCHEMA,'captured_at':at,'feature_as_of':known.isoformat() if valid else None,'mode':mode,
            'features':copy.deepcopy(features),'market_context':market,'sector_context':sector,'production_applied':False}


def indicator_family(row):
    if row.get('model')=='GUNLUK_AL_SAT_V1':return 'INTRADAY_BUY' if row.get('signal')=='AL_ADAYI' else 'INTRADAY_SELL' if row.get('signal')=='SAT_ADAYI' else None
    kind=signal(row)
    return 'TOMORROW_TOP10' if kind=='YARIN_TOP10' else 'AGGRESSIVE_BUY' if kind=='AGRESIF_ALIS' else 'AGGRESSIVE_SELL' if kind=='AGRESIF_SATIS' else 'OVERSOLD_REACTION' if kind=='ASIRI_SATIM' else 'TREND' if direction(row) else None


def evidence_snapshot(row):
    containers=[row.get('indicator_snapshot'),row.get('kriterler')]
    snapshot=row.get('indicator_evidence') or next((v.get('feature_evidence') or v.get('indicator_evidence') for v in containers if isinstance(v,dict) and (v.get('feature_evidence') or v.get('indicator_evidence'))),None)
    return snapshot if isinstance(snapshot,dict) else {}


def feature_capture_issue(snapshot,at):
    known=stamp(snapshot.get('feature_as_of'));captured=stamp(snapshot.get('captured_at'))
    if snapshot.get('schema_version')!=FEATURE_SCHEMA or not known or not captured:return 'FEATURE_NOT_CAPTURED'
    if not at or known>at or captured>at or not isinstance(snapshot.get('features'),dict):return 'FUTURE_FEATURES'
    for context in (snapshot.get('market_context'),snapshot.get('sector_context')):
        if context is not None and not isinstance(context,dict):return 'MALFORMED_FEATURES'
        if isinstance(context,dict):
            for key in ('as_of','created_at','context_as_of','context_created_at'):
                when=stamp(context.get(key))
                if when and when>at:return 'FUTURE_FEATURES'
    return None


def indicator_examples(records,current,holiday=None):
    """Share the existing direction, validation, Stats and excursion semantics."""
    unique,duplicates,malformed=unique_records(records);output=[];excluded=Counter()
    for row,conflict in unique:
        at=stamp(row.get('zaman') or row.get('tarih'));family=indicator_family(row)
        if conflict or not at or not family:excluded['DUPLICATE_OR_UNKNOWN']+=1;continue
        snap=evidence_snapshot(row);capture_issue=feature_capture_issue(snap,at)
        if capture_issue:excluded[capture_issue]+=1;continue
        if at>current:excluded['FUTURE_SIGNAL']+=1;continue
        for h in HORIZONS:
            reason=quality(row,h,current,holiday)
            if reason not in (None,'PENDING'):excluded[reason]+=1;continue
            stat=Stats();stat.add(row,h,reason);value=stat.export()
            output.append({'id':str(row.get('kayit_id') or row.get('id')),'symbol':row['sembol'],'at':at.isoformat(),'family':family,
                'direction':'BUY' if direction(row)==1 else 'SELL','horizon':str(h),'features':compact_features(snap['features']),
                'regime':(snap.get('market_context') or {}).get('market_regime'),'sector':(snap.get('sector_context') or {}).get('sector_state'),
                'pending':reason=='PENDING','return':value['mean_return'],'raw_return':value['mean_raw_price_return'],
                'mfe':value['mean_mfe'],'mae':value['mean_mae'],'success':bool(value['positive']) if reason is None else None})
    return output,dict(excluded,malformed=malformed,duplicates=duplicates)


def _indicator_stats(examples,current):
    resolved=[v for v in examples if not v['pending']];returns=[v['return'] for v in resolved if number(v['return']) is not None]
    raw=[v['raw_return'] for v in resolved if number(v['raw_return']) is not None]
    wins=sum(v['success'] is True for v in resolved);losses=sum(v['return']<0 for v in resolved);neutral=sum(v['return']==0 for v in resolved)
    positive=[v for v in returns if v>0];negative=[v for v in returns if v<0]
    count=len(resolved);status=next((k for k in ('STRONG_SAMPLE','USABLE','EARLY') if count>=SAMPLE_LIMITS[k]),'INSUFFICIENT')
    maturity=count/len(examples) if examples else 0
    completeness=sum(v['raw_return'] is not None and v['mfe'] is not None and v['mae'] is not None for v in resolved)/count if count else 0
    times=[stamp(v['at']) for v in examples];latest=max(times) if times else None
    resolved_latest=max((stamp(v['at']) for v in resolved),default=None)
    freshness=1 if resolved_latest and (current-resolved_latest).days<=90 else .5 if resolved_latest else 0
    confidence=min(100,100*count/(count+SHRINKAGE_PRIOR))*maturity*(.75+.25*completeness)*freshness
    return {'sample_count':len(examples),'eligible_sample_count':count,'success_count':wins,'failure_count':count-wins,
        'neutral_count':neutral,'success_rate':wins/count if count else None,'avg_return':mean(returns) if returns else None,
        'median_return':median(returns) if returns else None,'best_return':max(returns) if returns else None,'worst_return':min(returns) if returns else None,
        'avg_raw_return':mean(raw) if raw else None,'avg_favorable_excursion':mean([v['mfe'] for v in resolved if v['mfe'] is not None]) if any(v['mfe'] is not None for v in resolved) else None,
        'avg_adverse_excursion':mean([v['mae'] for v in resolved if v['mae'] is not None]) if any(v['mae'] is not None for v in resolved) else None,
        'win_loss_ratio':mean(positive)/abs(mean(negative)) if positive and negative else None,'confidence':round(confidence,2),'data_status':status,
        'first_sample_at':min(times).isoformat() if times else None,'last_sample_at':latest.isoformat() if latest else None,
        'clipped_avg_return':mean(max(-RETURN_CLIP,min(RETURN_CLIP,v)) for v in returns) if returns else None,'pending_count':len(examples)-count}


def aggregate_indicator_evidence(examples,current):
    groups=defaultdict(list)
    invalid=0
    for example in examples:
        try:
            if (example['family'] not in INDICATOR_FAMILIES or example['direction'] not in ('BUY','SELL') or
                example['horizon'] not in INDICATOR_HORIZONS or not stamp(example['at']) or stamp(example['at'])>current or
                not isinstance(example['features'],dict) or not isinstance(example['pending'],bool) or
                not example['pending'] and (number(example['return']) is None or not isinstance(example['success'],bool))):raise ValueError('Invalid indicator projection')
            groups[(example['family'],example['direction'],example['horizon'])].append(example)
        except (KeyError,TypeError,ValueError):invalid+=1
    rows=[];combos=[];errors=[]
    for (family,side,horizon),base in sorted(groups.items()):
        baseline=_indicator_stats(base,current)
        for indicator in INDICATOR_IDS:
            try:
                captured=[v for v in base if isinstance(v['features'].get(indicator),dict) and v['features'][indicator].get('available') is True and v['features'][indicator].get('state') in ('POSITIVE','NEGATIVE','NEUTRAL')]
                with_feature=[v for v in captured if v['features'][indicator].get('active') is True]
                without=[v for v in captured if v['features'][indicator].get('active') is False]
                stats=_indicator_stats(captured,current);active=_indicator_stats(with_feature,current);inactive=_indicator_stats(without,current)
                delta=active['success_rate']-baseline['success_rate'] if active['success_rate'] is not None and baseline['success_rate'] is not None else None
                confidence=min(active['confidence'],inactive['confidence']);n=active['eligible_sample_count'];m=inactive['eligible_sample_count']
                candidate=None;weight_status='INSUFFICIENT_DATA';warnings=[]
                if n<SAMPLE_LIMITS['EARLY'] or m<SAMPLE_LIMITS['EARLY']:warnings.append('LOW_SAMPLE')
                else:
                    # Observational candidate only; conservative fixed shrinkage,
                    # median/clipped returns, recent and regime agreement below.
                    observed_delta=candidate_effect(active,inactive)
                    recent=sorted(with_feature,key=lambda v:v['at'])[-50:];recent_stats=_indicator_stats(recent,current)
                    consistency=1 if recent_stats['success_rate'] is not None and candidate_effect(recent_stats,inactive)*observed_delta>=0 else .5
                    quality_factor=min(1,abs(active['median_return'])/max(1,abs(active['clipped_avg_return']))) if active['median_return'] is not None else 0
                    candidate=max(-1,min(1,observed_delta*(n/(n+SHRINKAGE_PRIOR))*(m/(m+SHRINKAGE_PRIOR))*(confidence/100)*(.5+.5*quality_factor)*consistency))
                    weight_status='CANDIDATE' if min(n,m)>=SAMPLE_LIMITS['USABLE'] else 'EARLY'
                if stats['confidence']<50:warnings.append('LOW_CONFIDENCE')
                if len(captured)<len(base):warnings.append('FEATURE_NOT_CAPTURED')
                if stats['last_sample_at'] and (current-stamp(stats['last_sample_at'])).days>90:warnings.append('STALE_DATA')
                if stats['avg_return'] is not None and abs(stats['avg_return']-stats['clipped_avg_return'])>1:warnings.append('OUTLIER_SENSITIVE')
                breakdown={}
                for field,label in (('regime','market_regime'),('sector','sector_strength')):
                    names=sorted({v[field] for v in captured if isinstance(v.get(field),str)})
                    breakdown[label]={}
                    for name in names:
                        subset=[v for v in captured if v[field]==name]
                        stat=_indicator_stats(subset,current)
                        yes=_indicator_stats([v for v in subset if v['features'][indicator].get('active') is True],current)
                        no=_indicator_stats([v for v in subset if v['features'][indicator].get('active') is False],current)
                        stat['delta_with_without']=yes['success_rate']-no['success_rate'] if min(yes['eligible_sample_count'],no['eligible_sample_count'])>=SAMPLE_LIMITS['EARLY'] else None
                        stat['candidate_effect']=candidate_effect(yes,no) if stat['delta_with_without'] is not None else None
                        breakdown[label][name]=stat
                    if not names or any(v['eligible_sample_count']<SAMPLE_LIMITS['EARLY'] for v in breakdown[label].values()):warnings.append('REGIME_SAMPLE_LOW' if field=='regime' else 'SECTOR_SAMPLE_LOW')
                rows.append(dict(stats,indicator_id=indicator,indicator_name=INDICATOR_NAMES[indicator],feature_type='CONTEXT_FEATURE' if indicator in ('MARKET_REGIME','SECTOR_STRENGTH') else 'TECHNICAL_INDICATOR',
                    signal_family=family,direction=side,horizon=horizon,engine_version=INDICATOR_VERSION,baseline=baseline,
                    with_feature=active,without_feature=inactive,delta_success_rate=delta,
                    with_feature_success_rate=active['success_rate'],without_feature_success_rate=inactive['success_rate'],
                    learned_weight_candidate=candidate,weight_status=weight_status,production_applied=False,breakdown=breakdown,
                    states={state:_indicator_stats([v for v in captured if v['features'][indicator].get('state')==state],current) for state in ('POSITIVE','NEGATIVE','NEUTRAL','UNKNOWN')},
                    recency={f'last_{n}':_indicator_stats(sorted(captured,key=lambda v:v['at'])[-n:],current) for n in (20,50)},
                    updated_at=current.isoformat(),reasons=[f'{active["eligible_sample_count"]} teyitli örnek; baseline farkı {delta*100:+.2f} puan'] if delta is not None else [],warnings=warnings))
            except Exception as error:
                from gorev_hatalari import describe,log_source
                log_source(error,'INDICATOR_PERFORMANCE');errors.append({'indicator':indicator,'issue':describe(error)})
        for combo in INDICATOR_COMBINATIONS:
            chosen=[v for v in base if all(isinstance(v['features'].get(k),dict) and v['features'][k].get('available') is True and v['features'][k].get('active') is True for k in combo)]
            if sum(not v['pending'] for v in chosen)>=SAMPLE_LIMITS['EARLY']:combos.append(dict(_indicator_stats(chosen,current),indicator_id='+'.join(combo),signal_family=family,direction=side,horizon=horizon,production_applied=False))
    # Confidence in a candidate additionally requires independent horizon and
    # actual frozen-regime consistency. Absence is not invented agreement.
    for row in rows:
        peers=[v for v in rows if v['indicator_id']==row['indicator_id'] and v['signal_family']==row['signal_family'] and v['direction']==row['direction'] and v['learned_weight_candidate'] is not None]
        sign=lambda v:1 if v>0 else -1 if v<0 else 0
        signs={sign(v['learned_weight_candidate']) for v in peers}
        if len(signs)>1:
            row['warnings'].append('INCONSISTENT_HORIZONS')
            if row['learned_weight_candidate'] is not None:row['learned_weight_candidate']*=.5
        regimes=row['breakdown']['market_regime'];sufficient=[s for s in regimes.values() if s.get('candidate_effect') is not None]
        if row['learned_weight_candidate'] is not None:
            regime_agrees=all(sign(s['candidate_effect'])==sign(row['learned_weight_candidate']) for s in sufficient)
            if len(sufficient)<2 or not regime_agrees:
                row['learned_weight_candidate']*=.5
                row['warnings'].append('REGIME_SAMPLE_LOW' if len(sufficient)<2 else 'INCONSISTENT_REGIMES')
            if len(peers)<2:row['learned_weight_candidate']*=.5
            if min(row['with_feature']['eligible_sample_count'],row['without_feature']['eligible_sample_count'])>=SAMPLE_LIMITS['STRONG_SAMPLE'] and min(row['with_feature']['confidence'],row['without_feature']['confidence'])>=70 and len(peers)>=2 and len(signs)==1 and len(sufficient)>=2 and regime_agrees:row['weight_status']='STABLE'
            row['learned_weight_candidate']=round(row['learned_weight_candidate'],6)
    return {'engine_version':INDICATOR_VERSION,'feature_schema_version':FEATURE_SCHEMA,'weight_model_version':WEIGHT_VERSION,'updated_at':current.isoformat(),
            'production_applied':False,'analysis_only':True,'rows':rows,'combinations':combos,'errors':errors,
            'invalid_projection_count':invalid,'summary':{'resolved_sample_count':sum(not v['pending'] for group in groups.values() for v in group),'tracked_indicator_count':len(INDICATOR_IDS),'usable_indicator_count':len({r['indicator_id'] for r in rows if r['data_status'] in ('USABLE','STRONG_SAMPLE')})},
            'minimum_samples':SAMPLE_LIMITS,'enabled':True}


def advanced_indicator_report(query,location=None):
    from kullanici_kayitlari import RecordError
    allowed={'indicator':set(INDICATOR_IDS),'family':set(INDICATOR_FAMILIES)|{'ALL'},'direction':{'BUY','SELL'},'horizon':set(INDICATOR_HORIZONS)}
    if set(query)-set(allowed) or any(not isinstance(v,list) or len(v)!=1 or v[0] not in allowed[k] for k,v in query.items()):raise RecordError('Geçersiz indikatör sorgusu.',400)
    if not indicator_enabled():return {'enabled':False,'production_applied':False,'rows':[]}
    try:
        doc=load((location or paths()).public/'indicator_performance.json',{})
        if doc.get('engine_version')!=INDICATOR_VERSION or doc.get('feature_schema_version')!=FEATURE_SCHEMA or doc.get('weight_model_version')!=WEIGHT_VERSION or doc.get('production_applied') is not False or not isinstance(doc.get('rows'),list) or not isinstance(doc.get('summary'),dict) or not stamp(doc.get('updated_at')):raise ValueError('Indicator cache schema')
        if stamp(doc['updated_at'])>datetime.now(ISTANBUL) or any(not isinstance(r,dict) or r.get('indicator_id') not in INDICATOR_IDS or r.get('signal_family') not in INDICATOR_FAMILIES or r.get('direction') not in ('BUY','SELL') or r.get('horizon') not in INDICATOR_HORIZONS or r.get('production_applied') is not False for r in doc['rows']):raise ValueError('Indicator cache rows')
    except (OSError,ValueError,TypeError,AttributeError):raise RecordError('İndikatör performansı henüz alınamıyor.',503) from None
    if not isinstance(doc.get('combinations',[]),list) or any(not isinstance(r,dict) for r in doc.get('combinations',[])):raise RecordError('İndikatör önbelleği geçersiz.',503)
    filters={k:v[0] for k,v in query.items() if not (k=='family' and v[0]=='ALL')};names={'indicator':'indicator_id','family':'signal_family'}
    return dict(doc,stale=(datetime.now(ISTANBUL)-stamp(doc['updated_at'])).total_seconds()>86400,rows=[r for r in doc['rows'] if all(str(r.get(names.get(k,k)))==v for k,v in filters.items())],
                combinations=[r for r in doc.get('combinations',[]) if all(str(r.get(names.get(k,k)))==v for k,v in filters.items())])


def safe_feature_capture(row,at,intraday=False,location=None):
    """Supplementary capture must not prevent the existing signal from being saved."""
    try:return capture_feature_evidence(row,at,intraday,location)
    except Exception as error:
        from gorev_hatalari import log_source
        log_source(error,'INDICATOR_CAPTURE')
        return {'schema_version':FEATURE_SCHEMA,'captured_at':at,'feature_as_of':None,
                'features':{},'status':'FEATURE_NOT_CAPTURED','production_applied':False}


def compact_features(features):
    return {k:{field:v.get(field) for field in ('available','active','state','confirmed')}
            for k,v in features.items() if k in INDICATOR_IDS and isinstance(v,dict)
            and isinstance(v.get('available'),bool) and v.get('active') in (True,False,None)}


def intraday_indicator_examples(records,results,current,holiday=None):
    from intraday_sinyal_performansi import observations,result_issue,fingerprint,HORIZONS as horizons,side
    observed,duplicates,malformed=observations(records,current);examples=[];excluded=Counter()
    for row,issue in observed:
        at=stamp(row.get('timestamp'));snap=evidence_snapshot(row)
        issue=issue or feature_capture_issue(snap,at)
        if issue:excluded[issue]+=1;continue
        stored=results.get(row['event_id'],{})
        if stored and stored.get('source_hash')!=fingerprint(row):excluded['SOURCE_HASH_CONFLICT']+=1;continue
        for h in horizons:
            result=stored.get('outcomes',{}).get(h)
            reason=result_issue(row,result,current,h,holiday)
            if reason not in (None,'PENDING'):excluded[reason]+=1;continue
            pending=reason=='PENDING';result=result or {};buy=side(row)=='AL'
            examples.append({'id':row['event_id'],'symbol':row['symbol'],'at':at.isoformat(),
                'family':'INTRADAY_BUY' if buy else 'INTRADAY_SELL','direction':'BUY' if buy else 'SELL',
                'horizon':{'D1':'1','D3':'3'}.get(h,h),'features':compact_features(snap['features']),
                'regime':(snap.get('market_context') or {}).get('market_regime'),'sector':(snap.get('sector_context') or {}).get('sector_state'),
                'pending':pending,'return':None if pending else result['direction_return'],
                'raw_return':None if pending else result['raw_return'],'mfe':None if pending else result['MFE'],
                'mae':None if pending else result['MAE'],'success':None if pending else result['direction_return']>0})
    return examples,dict(excluded,duplicates=duplicates,malformed=malformed)


def refresh_indicator_performance(location=None,current=None,holiday=None):
    """No provider calls or source writes. Reproject changed source/result pairs only.

    Small scalar projections survive restarts. A date change revalidates time and
    recency; future-dated records use a five-minute gate until they mature.
    """
    from gorev_hatalari import describe,log_source,TaskIssue
    from performans_motoru import legacy_record,legacy_signal,session_closed,business_day
    if not indicator_enabled():return {'disabled':True}
    location=location or paths();current=current or datetime.now(ISTANBUL)
    target=location.runtime_file('indicator_performance_state.json');public=location.public/'indicator_performance.json'
    with locked(target):
        try:state=load(target,{})
        except (ValueError,OSError) as error:
            log_source(error,'INDICATOR_CACHE');state={}
        if not isinstance(state,dict) or state.get('version')!=INDICATOR_VERSION or not isinstance(state.get('sources',{}),dict):state={}
        old=state.get('sources',{});sources={};errors=[];changed=0
        pairs=[('daily',location.runtime_file('ai_ogrenme_gecmisi.json'),None),
               ('legacy',location.runtime_file('tahmin_gecmisi.json'),None)]
        pairs += [('intraday',p,location.runtime_file('intraday_signal_results')/p.name)
                  for p in sorted(location.runtime_file('gunluk_al_sat_gecmisi').glob('????-??-??.json'))]
        for kind,source,result_path in pairs:
            if not source.exists():continue
            key=kind+':'+source.name
            try:
                from v6_storage.backend import file_signature
                signature=[file_signature(p) if p and p.exists() else None for p in (source,result_path)]
                signature=json.loads(json.dumps(signature));previous=old.get(key,{})
                if not isinstance(previous,dict):previous={}
                gate=current.date().isoformat()
                if previous.get('time_sensitive'):gate+=':'+str(int(current.timestamp()//300))
                if previous.get('signature')==signature and previous.get('gate')==gate and isinstance(previous.get('observations'),list) and previous.get('projection_hash')==indicator_digest(previous['observations']):
                    sources[key]=previous;continue
                with locked(source):doc=load(source,{})
                if not isinstance(doc,dict):raise ValueError('Indicator source shape')
                if kind=='intraday':
                    if not isinstance(doc.get('events'),dict):raise ValueError('Indicator events shape')
                    records=[]
                    for identity,row in doc['events'].items():
                        if not isinstance(row,dict) or row.get('event_id')!=identity:raise ValueError('Indicator source identity')
                        records.append(row)
                    results={}
                    if result_path.exists():
                        with locked(result_path):result_doc=load(result_path,{})
                        results=result_doc.get('events',{})
                        if not isinstance(results,dict):raise ValueError('Indicator results shape')
                    projected,excluded=intraday_indicator_examples(records,results,current,holiday)
                else:
                    records=doc.get('kayitlar' if kind=='daily' else 'tahminler',[])
                    if not isinstance(records,list):raise ValueError('Indicator history shape')
                    if kind=='legacy':records=[legacy_record(r) for r in records if isinstance(r,dict) and legacy_signal(r)]
                    projected,excluded=indicator_examples(records,current,holiday)
                sensitive=any('FUTURE' in code or 'UNFINISHED' in code for code,count in excluded.items() if count)
                if sensitive:gate=current.date().isoformat()+':'+str(int(current.timestamp()//300))
                packed=pack_indicator_examples(projected)
                sources[key]={'projection_hash':indicator_digest(packed),'signature':signature,'gate':gate,'time_sensitive':sensitive,'observations':packed,'excluded':excluded};changed+=1
            except Exception as error:
                log_source(error,'INDICATOR_PERFORMANCE');errors.append(describe(error))
                # Never pretend stale cached source evidence is current valid input.
        if sources==old and public.exists() and not errors:
            try:
                cached=load(public,{})
                valid=state.get('report_hash')==indicator_digest(cached)
                if valid:return {'unchanged':True,'sources_read':0}
            except (ValueError,OSError,AttributeError):pass
        # Cross-file duplicate/conflict check prevents imported live records being
        # counted twice; conflicting verified projections are explicitly excluded.
        unique={};conflicts=set();excluded=Counter()
        for source in sources.values():
            excluded.update(source['excluded'])
            for example in unpack_indicator_examples(source['observations']):
                key=(example['symbol'],example['at'],example['family'],example['direction'],example['horizon'])
                if key in unique and unique[key]!=dict(example,id=unique[key]['id']):conflicts.add(key)
                else:unique[key]=example
        examples=[v for k,v in unique.items() if k not in conflicts]
        excluded['CROSS_SOURCE_CONFLICT']=len(conflicts)
        report=aggregate_indicator_evidence(examples,current);report['excluded']=dict(excluded)
        report['source_errors']=errors;report['status']='DEGRADED' if errors or report['errors'] else 'READY'
        atomic_json(public,report)
        atomic_json(target,{'version':INDICATOR_VERSION,'sources':sources,'report_hash':indicator_digest(report),'updated_at':current.isoformat()})
        archive=location.runtime_file('indicator_performance')/(current.date().isoformat()+'.json')
        if business_day(current.date(),holiday) and session_closed(current.date(),current) and not errors and not report['errors'] and examples:
            with locked(archive):
                if not archive.exists():
                    keys=('indicator_id','signal_family','direction','horizon','eligible_sample_count','success_rate','avg_return','median_return','avg_favorable_excursion','avg_adverse_excursion','confidence','weight_status','learned_weight_candidate')
                    atomic_json(archive,{'engine_version':INDICATOR_VERSION,'feature_schema_version':FEATURE_SCHEMA,'weight_model_version':WEIGHT_VERSION,
                        'updated_at':current.isoformat(),'final':True,'production_applied':False,'summary':report['summary'],
                        'rows':[{k:r.get(k) for k in keys} for r in report['rows']]})
        if errors or report['errors']:raise TaskIssue(errors[0] if errors else report['errors'][0]['issue'],len(examples))
        return {'examples':len(examples),'sources_read':changed,'production_applied':False}


def pack_indicator_examples(examples):
    """One compact feature vector per observation, shared by its horizon outcomes.

    This derived ledger contains no raw prices, technical histories or forecasts.
    """
    output={}
    for sample in examples:
        key=(sample['id'],sample['symbol'],sample['at'],sample['family'],sample['direction'])
        if key not in output:
            output[key]={'identity':list(key),'regime':sample['regime'],'sector':sample['sector'],
                'features':{k:[v.get('available'),v.get('active'),v.get('state'),v.get('confirmed')] for k,v in sample['features'].items()},'outcomes':{}}
        output[key]['outcomes'][sample['horizon']]=[sample[k] for k in ('pending','return','raw_return','mfe','mae','success')]
    return list(output.values())


def unpack_indicator_examples(observations):
    for observed in observations:
        identity=observed['identity'];features={k:dict(zip(('available','active','state','confirmed'),v)) for k,v in observed['features'].items()}
        for horizon,result in observed['outcomes'].items():
            yield dict(zip(('id','symbol','at','family','direction'),identity),features=features,
                regime=observed['regime'],sector=observed['sector'],horizon=horizon,
                **dict(zip(('pending','return','raw_return','mfe','mae','success'),result)))


def indicator_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def candidate_effect(active,inactive):
    """Association in both hit rate and return quality; not a production score."""
    clip=lambda v:max(-RETURN_CLIP,min(RETURN_CLIP,v))
    return (.6*(active['success_rate']-inactive['success_rate'])+
            .25*(active['clipped_avg_return']-inactive['clipped_avg_return'])/(2*RETURN_CLIP)+
            .15*(clip(active['median_return'])-clip(inactive['median_return']))/(2*RETURN_CLIP))


def indicator_context_file(path):
    try:
        info=path.stat()
        return _indicator_context_file(str(path),info.st_mtime_ns,info.st_size)
    except FileNotFoundError:return {}


@lru_cache(maxsize=4)
def _indicator_context_file(path,mtime,size):
    from piyasa_baglami import optional
    return optional(__import__('pathlib').Path(path),{})
