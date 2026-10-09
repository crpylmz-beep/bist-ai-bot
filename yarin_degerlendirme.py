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


def evaluate(value, bars, horizon, current):
    """Daily bars only; reject gaps and ambiguous/invalid OHLC, never use future bars."""
    from datetime import date
    if horizon not in due(value, current): return None
    signal = instant(value['signal_time'])
    if not value.get('reference_time') or instant(value['reference_time']) > signal:
        return None
    end = date.fromisoformat(value['evaluation_dates'][str(horizon)])
    first = date.fromisoformat(value['evaluation_dates']['1'])
    days = [first] + sessions_after(first, horizon - 1)
    if days[-1] != end: raise ValueError('Inconsistent evaluation calendar')
    rows = {}
    for bar in bars:
        day = date.fromisoformat(str(bar['timestamp'])[:10])
        if day not in days: continue
        opening = bist_calendar(day.year).session_open(day.isoformat()).to_pydatetime()
        if opening <= signal: return None
        numbers = [finite(bar.get(k)) for k in ('open','high','low','close')]
        if any(v is None or v <= 0 for v in numbers): return None
        o,h,l,c = numbers
        if not l <= min(o,c) <= max(o,c) <= h: return None
        if day in rows and rows[day] != numbers: raise ValueError('Conflicting OHLC bars')
        rows[day] = numbers
    if set(rows) != set(days): return None
    price = value['reference_price']; target = value['daily_target']; stop = value['daily_stop']
    target_day = next((d for d in days if rows[d][1] >= target), None)
    stop_day = next((d for d in days if rows[d][2] <= stop), None)
    order = ('UNKNOWN_SAME_BAR' if target_day == stop_day else
             'TARGET_FIRST' if target_day < stop_day else 'STOP_FIRST') if target_day and stop_day else None
    close = rows[end][3]; low = min(rows[d][2] for d in days)
    return {'horizon':horizon,'evaluation_date':end.isoformat(),
        'return_pct':100*(close/price-1),'hit':close > price,
        'target_hit':target_day is not None,'stop_hit':stop_day is not None,
        'target_stop_order':order,'mae_pct':min(0.,100*(low/price-1)),
        'lowest_price':low,'highest_price':max(rows[d][1] for d in days),
        'evaluated_at':instant(current).isoformat(timespec='seconds')}


def daily_history(symbol):
    # Existing provider, explicitly unadjusted to match the frozen nominal levels.
    import bist_bot
    frame = bist_bot.bp.Ticker(symbol).history(period='1y', interval='1d', adjust=False, auto_adjust=False)
    if frame is None or frame.empty: return []
    return [{'timestamp':str(day), **{k:row.get(v) for k,v in
             (('open','Open'),('high','High'),('low','Low'),('close','Close'))}}
            for day,row in frame.iterrows()]


def evaluate_round(location=None, history_provider=None, current=None, batch_size=20):
    """Prospective archives read-only; compact append-only SQLite outcomes, no backfill."""
    import sqlite3
    from contextlib import closing
    from veri_yollari import paths
    location = location or paths()
    current = instant(current or datetime.now(IST))
    provider = history_provider or daily_history
    database = location.runtime_file('yarin_dated_outcomes.sqlite3')
    database.parent.mkdir(parents=True, exist_ok=True)
    result = {'completed':0,'missing':0,'symbols':0,'deferred':0}
    errors = []
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS outcomes (prediction_id TEXT NOT NULL, horizon INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(prediction_id,horizon))')
        connection.execute('CREATE TABLE IF NOT EXISTS attempts (symbol TEXT PRIMARY KEY, retry_after TEXT NOT NULL)')
        cache = {}
        for archive in sorted(location.archives.glob('*.json')):
            with archive.open(encoding='utf-8') as stream: snapshot = json.load(stream)
            records = (snapshot.get('dated_evaluations') or {}).get('records', {})
            for key,value in records.items():
                pending = [h for h in due(value,current) if not connection.execute(
                    'SELECT 1 FROM outcomes WHERE prediction_id=? AND horizon=?',(key,h)).fetchone()]
                if not pending: continue
                symbol = value['symbol']
                if symbol not in cache:
                    if len(cache) >= batch_size: continue
                    retry = connection.execute('SELECT retry_after FROM attempts WHERE symbol=?',(symbol,)).fetchone()
                    if retry and instant(retry[0]) > current:
                        result['deferred'] += len(pending)
                        continue
                    connection.execute('INSERT OR REPLACE INTO attempts VALUES (?,?)',(symbol,(current+timedelta(hours=6)).isoformat()))
                    try: cache[symbol] = provider(symbol)
                    except Exception as error:
                        cache[symbol] = None
                        errors.append(error)
                if cache[symbol] is None: continue
                for horizon in pending:
                    outcome = evaluate(value,cache[symbol],horizon,current)
                    if outcome is None:
                        result['missing'] += 1
                        continue
                    cursor = connection.execute('INSERT OR IGNORE INTO outcomes VALUES (?,?,?)',
                        (key,horizon,json.dumps(outcome,separators=(',',':'),allow_nan=False)))
                    result['completed'] += cursor.rowcount
            # Small durable commits preserve earlier successes on interruption.
            connection.commit()
        result['symbols'] = len(cache)
    if errors: raise errors[0]
    if result['missing']: raise ValueError('Dated TOP10 outcome: required OHLC unavailable')
    return result
