"""Deterministic candidate hygiene; existing score formulas remain authoritative."""
import json

from ai_karar_motoru import number, stamp
from saglayici_sembolleri import bist_symbol

CANDIDATE_LIMIT = 60
NUMERIC_INPUTS = ('fiyat', 'rsi', 'rsi5', 'macd', 'signal', 'hist', 'sma20',
                  'sma50', 'hacim_orani', 'risk_getiri', 'degisim', 'atr14',
                  'hacim3_orani', 'momentum15')


def valid_candidate(row, current, mode='TOMORROW'):
    """Legacy rows remain usable; supplied provenance must be valid and fresh."""
    from sinyal_performansi import frozen_feature_issue
    from teknik_gostergeler import stale_at
    if not isinstance(row, dict) or number(row.get('fiyat'), 0) <= 0:
        return False
    if not isinstance(row.get('sembol'), str) or not row['sembol'].strip():
        return False
    if any(key in row and number(row[key]) is None for key in NUMERIC_INPUTS):
        return False
    if any(key in row and isinstance(row[key], bool) for key in NUMERIC_INPUTS):
        return False
    for key in ('rsi', 'rsi5'):
        if key in row and not 0 <= number(row[key]) <= 100:
            return False
    if any(key in row and number(row[key]) < 0 for key in ('hacim_orani', 'hacim3_orani', 'atr14')):
        return False
    if any(key in row and number(row[key]) <= 0 for key in ('sma20', 'sma50')):
        return False
    if frozen_feature_issue(row, current):
        return False
    for source in (row, row.get('teknik_gostergeler') or {}, row.get('criteria_snapshot') or {}, row.get('indicator_snapshot') or {}):
        for key in ('captured_at', 'asof', 'feature_timestamp'):
            if source.get(key) is not None and (stamp(source[key]) is None or stamp(source[key]) > current):
                return False
    for key in ('canli_guncelleme', 'calculated_at', 'feature_timestamp'):
        if row.get(key) is not None:
            at = stamp(row[key])
            if at is None or at > current or stale_at(at, current, mode):
                return False
    doc = row.get('teknik_gostergeler')
    if doc is not None:
        if doc.get('mode') != mode or doc.get('stale'):
            return False
        observed, asof = stamp(doc.get('data_time')), stamp(doc.get('asof'))
        if observed is None or asof is None or asof > current or stale_at(observed, current, mode):
            return False
        closing = doc.get('closing')
        if closing is not None and not isinstance(closing, dict):
            return False
        if closing:
            close = number(closing.get('close'))
            if close is None or close <= 0 or abs(close-number(row['fiyat'])) > max(.01, close*.0001):
                return False
            ohlc = [number(closing.get(k)) for k in ('open', 'high', 'low')]
            if any(k in closing for k in ('open', 'high', 'low')):
                opening, high, low = ohlc
                if any(v is None or v <= 0 for v in ohlc) or not low <= min(opening, close) <= max(opening, close) <= high:
                    return False
            for key in ('volume', 'turnover_tl', 'previous_close'):
                if key in closing and (number(closing[key]) is None or number(closing[key]) < 0 or
                                       (key == 'previous_close' and number(closing[key]) == 0)):
                    return False
    return True


def prepare_candidates(rows, current, mode='TOMORROW', keep_invalid=False):
    """Canonical symbols; newest valid duplicate wins, ties use stable content."""
    selected = {}
    for row in rows:
        valid = valid_candidate(row, current, mode)
        if not valid and not keep_invalid:
            continue
        if not isinstance(row, dict) or not isinstance(row.get('sembol'), str):
            continue
        try:
            symbol = bist_symbol(row.get('sembol', ''))
        except ValueError:
            continue
        doc = row.get('teknik_gostergeler') or {}
        if not isinstance(doc, dict):
            doc = {}
        at = stamp(doc.get('data_time') or row.get('canli_guncelleme') or row.get('calculated_at') or row.get('feature_timestamp'))
        canonical = dict(row, sembol=symbol)
        identity = (valid, at.timestamp() if at else float('-inf'),
                    json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str))
        if symbol not in selected or identity > selected[symbol][0]:
            selected[symbol] = (identity, row)
    result = []
    for symbol in sorted(selected):
        row = selected[symbol][1]
        row['sembol'] = symbol
        result.append(row)
    return result


def ranking_key(score, row, secondary=('hacim_orani', 'risk_getiri')):
    return (-score, *(-number(row.get(key), 0) for key in secondary), row['sembol'])


def select_candidates(scored, secondary=('hacim_orani', 'risk_getiri')):
    """Select at most 60 finite base scores before learned reranking."""
    valid = []
    for score, row in scored:
        if number(score) is None or not isinstance(row, dict) or not isinstance(row.get('sembol'), str):
            continue
        try:
            row['sembol'] = bist_symbol(row['sembol'])
        except ValueError:
            continue
        valid.append((number(score), row))
    selected, seen = [], set()
    for pair in sorted(valid, key=lambda pair: ranking_key(pair[0], pair[1], secondary)):
        if pair[1]['sembol'] in seen:
            continue
        seen.add(pair[1]['sembol'])
        selected.append(pair)
        if len(selected) == CANDIDATE_LIMIT:
            break
    return selected


def intraday_candidates(rows, current):
    clean = prepare_candidates(rows, current, 'INTRADAY')
    eligible = [(number(row.get('gun_ici_final_puan', row.get('gun_ici_puan'))), row)
                for row in clean if number(row.get('gun_ici_puan'), 0) >= 45]
    return select_candidates(eligible, secondary=('hacim3_orani', 'momentum15'))
