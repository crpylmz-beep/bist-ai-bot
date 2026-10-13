"""Provider observation time, independent of file rewrite/analysis time."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import math

IST = ZoneInfo('Europe/Istanbul')
QUOTE_VERSION = 'PREVIOUS_SESSION_CLOSE_V2'
PRICE_FIELDS = ('fiyat','degisim','gunluk_degisim','price','change','fiyat_zamani',
                'fiyat_kaynagi','fiyat_turu','fiyat_alinma_zamani',
                'onceki_kapanis','onceki_kapanis_tarihi','gunluk_degisim_kaynagi',
                'onceki_kapanis_beklenen_tarih','sonraki_islem_tarihi')


def daily_change(price, previous_close):
    try:
        price=float(price);previous_close=float(previous_close)
        if not math.isfinite(price) or not math.isfinite(previous_close) or price<=0 or previous_close<=0:
            return None
        return (price / previous_close - 1) * 100
    except (TypeError, ValueError): return None


def preserve_newer_price(previous, incoming):
    result = dict(incoming)
    def stamp(row):
        try:
            value = datetime.fromisoformat(row.get('fiyat_zamani') or '')
            return value.replace(tzinfo=IST) if value.tzinfo is None else value
        except (ValueError, TypeError): return None
    old = stamp(previous); new = stamp(incoming)
    if old and (new is None or new < old):
        for key in PRICE_FIELDS:
            if key in previous: result[key] = previous[key]
            else: result.pop(key, None)
    value=daily_change(result.get('fiyat'),result.get('onceki_kapanis'))
    if value is not None:
        result.update(degisim=value,gunluk_degisim=value,gunluk_degisim_kaynagi='PREVIOUS_SESSION_CLOSE')
    return result


def session_close_time(day):
    """XIST continuous-session close plus the closing auction (also half days)."""
    from performans_motoru import bist_calendar
    return bist_calendar(day.year).session_close(day.isoformat()).tz_convert(IST).to_pydatetime()+timedelta(minutes=10)


def session_confirmation_time(day):
    # Conservative allowance for the anonymous delayed feed, not a realtime promise.
    return session_close_time(day)+timedelta(minutes=20)


def price_metadata(index, daily=False, now=None):
    now = now or datetime.now(IST)
    value = index.to_pydatetime() if hasattr(index, 'to_pydatetime') else index
    if not isinstance(value, datetime):
        return {'fiyat_kaynagi': 'borsapy', 'fiyat_zamani': None}
    value = value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)
    closed=False
    if daily:
        try:
            closed=value.date()<now.date() or now>=session_confirmation_time(value.date())
            if closed:value=session_close_time(value.date())
        except (ValueError,KeyError,ImportError):closed=False
    previous = following = None
    try:
        from performans_motoru import bist_calendar
        calendar=bist_calendar(value.year)
        previous=calendar.previous_session(value.date().isoformat()).date().isoformat()
        following=calendar.next_session(value.date().isoformat()).date().isoformat()
    except (ValueError, KeyError, ImportError):
        pass
    return {'fiyat_kaynagi': 'borsapy', 'fiyat_zamani': value.isoformat(),
            'fiyat_turu': 'SESSION_CLOSE' if closed else 'DAILY' if daily else 'INTRADAY',
            'onceki_kapanis_beklenen_tarih':previous,'sonraki_islem_tarihi':following}
