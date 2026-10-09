"""Compact prospective evaluation metadata; never backfills or reads live prices."""
import hashlib
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from performans_motoru import bist_calendar, business_day, sessions_after

IST = ZoneInfo('Europe/Istanbul')


def instant(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Aware prediction time required')
    return value.astimezone(IST)


def finite(value):
    if isinstance(value, bool): return None
    try: value = float(value)
    except (TypeError, ValueError, OverflowError): return None
    return value if math.isfinite(value) else None


def schedule(signal):
    day = signal.date()
    # Before today's opening, today's session is still wholly in the future.
    if business_day(day) and signal < bist_calendar(day.year).session_open(day.isoformat()).to_pydatetime():
        first = day
    else:
        first = sessions_after(day, 1)[0]
    days = [first] + sessions_after(first, 4)
    dates = {}; after = {}
    for horizon in (1, 3, 5):
        target = days[horizon - 1]
        dates[str(horizon)] = target.isoformat()
        close = bist_calendar(target.year).session_close(target.isoformat()).to_pydatetime()
        after[str(horizon)] = (close.astimezone(IST) + timedelta(minutes=15)).isoformat(timespec='seconds')
    return dates, after


def record(row, signal_time, analysis_date, dates, after):
    signal = instant(signal_time)
    symbol = row.get('sembol')
    if not isinstance(symbol, str) or not 1 <= len(symbol) <= 20:
        raise ValueError('Prediction symbol required')
    frozen = row.get('tahmin') or {}
    price = finite(frozen.get('fiyat'))
    # These snapshot fields originate only in ai_yarin_* / yarin_* levels.
    # Never substitute generic stop/hedef1, current quotes or reconstructed levels.
    target = finite(frozen.get('hedef')); stop = finite(frozen.get('stop'))
    model = (row.get('positive_opportunity') or {}).get('model_version') or 'YARIN_TOP10_V1'
    versions = [model, row.get('calibration_version') or 'BASE', row.get('learning_version') or 'BASE']
    if any(not isinstance(v, str) or len(v) > 96 for v in versions):
        raise ValueError('Invalid prediction model version')
    model = '|'.join(versions)
    key = hashlib.sha256(json.dumps([analysis_date,symbol,model],ensure_ascii=True,separators=(',',':')).encode()).hexdigest()[:32]
    status = 'READY'
    if price is None or target is None or stop is None:
        status = 'MISSING_LEVELS'
    elif not 0 < stop < price < target:
        status = 'INVALID_LEVELS'
    data_time = (row.get('teknik_gostergeler') or {}).get('data_time')
    reference_time = None
    if data_time:
        try:
            observed = instant(data_time)
            if observed > signal: status = 'FUTURE_REFERENCE'
            else: reference_time = observed.isoformat(timespec='seconds')
        except (ValueError, TypeError):
            if status == 'READY': status = 'REFERENCE_TIME_UNKNOWN'
    elif status == 'READY': status = 'REFERENCE_TIME_UNKNOWN'
    return key, {'symbol':symbol,'signal_time':signal.isoformat(timespec='seconds'),
        'reference_price':price,'reference_time':reference_time,'daily_target':target,'daily_stop':stop,
        'level_horizon':'NEXT_SESSION','model_version':model,'evaluation_dates':dict(dates),
        'evaluate_after':dict(after),'status':status}


def attach_new(snapshot):
    """Called ONLY on new snapshot creation, never on legacy conversion or reads."""
    signal = instant(snapshot['tahmin_zamani'])
    dates, after = schedule(signal)
    records = {}
    if len(snapshot['top10']) > 10: raise ValueError('TOP10 record limit exceeded')
    for row in snapshot['top10']:
        key, value = record(row, signal, snapshot['analiz_tarihi'], dates, after)
        if key in records and records[key] != value:
            raise ValueError('Conflicting duplicate prediction')
        records.setdefault(key, value)
        row['evaluation_id'] = key
    snapshot['dated_evaluations'] = {'schema_version':1,'records':records}
    # Small bounded addition inside the existing archive: no new history file/WAL.
    if len(json.dumps(snapshot['dated_evaluations'],ensure_ascii=True,separators=(',',':')).encode()) > 16384:
        raise ValueError('Evaluation metadata bound exceeded')
    return snapshot


def due(value, current):
    """Read-only scheduling helper; future/incomplete/reference-unknown records skip."""
    if value.get('status') != 'READY': return []
    now = instant(current)
    return [int(h) for h, at in value['evaluate_after'].items() if instant(at) <= now]
