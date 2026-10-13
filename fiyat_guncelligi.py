"""Provider observation time, independent of file rewrite/analysis time."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo('Europe/Istanbul')
PRICE_FIELDS = ('fiyat','degisim','gunluk_degisim','price','change','fiyat_zamani',
                'fiyat_kaynagi','fiyat_turu','fiyat_alinma_zamani')


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
    return result


def price_metadata(index, daily=False, now=None):
    now = now or datetime.now(IST)
    value = index.to_pydatetime() if hasattr(index, 'to_pydatetime') else index
    if not isinstance(value, datetime):
        return {'fiyat_kaynagi': 'borsapy', 'fiyat_zamani': None}
    value = value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)
    closed = daily and (value.date() < now.date() or now.time() >= time(18, 15))
    if closed:
        value = datetime.combine(value.date(), time(18, 10), IST)
    return {'fiyat_kaynagi': 'borsapy', 'fiyat_zamani': value.isoformat(),
            'fiyat_turu': 'SESSION_CLOSE' if closed else 'DAILY' if daily else 'INTRADAY'}
