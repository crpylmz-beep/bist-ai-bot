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


def quality(row, horizon, current, holiday=None):
    """Return one exclusion reason; never repair or invent an old label."""
    from performans_motoru import session_closed
    if not isinstance(row, dict): return 'MALFORMED'
    if any(row.get(key) is not None and not isinstance(row[key], dict) for key in ('kriterler', 'girdiler', 'teknik_gostergeler', 'criteria_snapshot', 'positive_opportunity')): return 'MALFORMED'
    at = stamp(row.get('zaman') or row.get('tarih'))
    if not at or not isinstance(row.get('sembol'), str) or not row['sembol'].strip(): return 'MALFORMED'
    if at > current: return 'FUTURE_SIGNAL'
    if row.get('egitim_durumu') == 'REFERANS': return 'UNVERIFIED'
    if row.get('analysis_only') or any(word in str(row.get('model', '')) for word in ('SHADOW', 'BACKTEST', 'BASELINE')):
        return 'NON_LIVE'
    if row.get('performance_source') not in (None, 'LIVE'): return 'NON_LIVE'
    if any(row.get(key) for key in ('lookahead_suspected', 'legacy_unverified', 'unverified')): return 'UNVERIFIED'
    for source in (row, row.get('kriterler') or {}, row.get('girdiler') or {}, row.get('teknik_gostergeler') or {}, row.get('criteria_snapshot') or {}, row.get('positive_opportunity') or {}):
        for key in ('captured_at', 'asof', 'feature_timestamp'):
            recorded = stamp(source.get(key))
            if recorded and recorded > at: return 'FUTURE_FEATURES'
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
            str(row.get('kaynak') or row.get('model') or 'LEGACY'), bool(row.get('guclu_tepki')))


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
                   'signal_at': row.get('zaman') or row.get('tarih'), 'features': features(row),
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
                'mean_mfe': mean(self.mfe) if self.mfe else None, 'mfe_samples': len(self.mfe),
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
    target = location.public_file('sinyal_performansi.json')
    with locked(target): atomic_json(target, report)
    return report


def read_report(location=None):
    """O(report size) service API; never parse large histories on web requests."""
    location = location or paths()
    return load(location.public_file('sinyal_performansi.json'),
                {'version': VERSION, 'status': 'PENDING_FIRST_REPORT', 'periods': {}})
