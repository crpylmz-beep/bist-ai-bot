"""One-shot price alarm checks. No push sending or automatic cloud registration."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo
import argparse
import copy
import json
import os

from kullanici_kayitlari import UserRecords, RecordError, atomic_json, price, symbol

ISTANBUL = ZoneInfo('Europe/Istanbul')
MAX_PRICE_AGE_SECONDS = 600


def istanbul_now():
    return datetime.now(ISTANBUL)


def aware_time(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Saat dilimi olmayan fiyat zamanı')
    return result.astimezone(ISTANBUL)


@dataclass(frozen=True)
class FiyatVerisi:
    fiyat: float
    observed_at: datetime
    kaynak: str


class MevcutFiyatSaglayici:
    """Read existing price outputs once per round; fall back to borsapy quotes."""
    def __init__(self, web_dir, not_before=None, clock=istanbul_now,
                 fallback=None, max_age_seconds=MAX_PRICE_AGE_SECONDS, public_dir=None):
        self.clock = clock
        self.max_age_seconds = max_age_seconds
        self.not_before = not_before or {}
        self.fallback = fallback or self.borsapy_fiyati
        self.cached = {}
        root = Path(public_dir) if public_dir is not None else Path(web_dir) / 'data'
        for filename in ('bist_data.json', 'gun_ici_tum.json', 'yarin_top10_canli.json'):
            try:
                data = json.loads((root / filename).read_text(encoding='utf-8'))
                rows = data.get('top10', []) if filename == 'yarin_top10_canli.json' else data.get('hisseler', [])
                for row in rows:
                    try:
                        current = row.get('canli', {}) if filename == 'yarin_top10_canli.json' else row
                        stamp = current.get('updated_at')
                        # Daily incremental output can contain mixed-age rows:
                        # never apply a global refresh time to all daily stocks.
                        if not stamp and filename == 'gun_ici_tum.json':
                            stamp = data.get('updated_at')
                        observed = aware_time(stamp)
                        if current.get('fiyat_tarihi') and current['fiyat_tarihi'] != observed.date().isoformat():
                            continue
                        stock = symbol(row.get('sembol'))
                        sample = FiyatVerisi(price(current.get('fiyat')), observed, filename)
                        previous = self.cached.get(stock)
                        if previous is None or observed > previous.observed_at:
                            self.cached[stock] = sample
                    except (ValueError, TypeError, AttributeError, RecordError):
                        continue
            except (OSError, ValueError, AttributeError, TypeError):
                continue

    @staticmethod
    def borsapy_fiyati(stock):
        import borsapy as bp
        # Reuse the project's provider; do not run technical analysis or write
        # any market, intraday, KAP, macro or snapshot output.
        return bp.Ticker(stock).fast_info.last_price

    def __call__(self, stock):
        sample = self.cached.get(stock)
        now = aware_time(self.clock())
        if sample is not None:
            age = (now - sample.observed_at).total_seconds()
            earliest = self.not_before.get(stock)
            if 0 <= age <= self.max_age_seconds and (earliest is None or sample.observed_at >= earliest):
                return sample
        result = self.fallback(stock)
        if isinstance(result, FiyatVerisi):
            return result
        return FiyatVerisi(price(result), aware_time(self.clock()), 'borsapy.fast_info.last_price')


def eligible(alarm):
    return (isinstance(alarm, dict) and alarm.get('aktif') is True
            and not alarm.get('triggered_at')
            and alarm.get('status') not in ('TRIGGERED', 'DISABLED'))


def alarm_kosulu_saglandi(alarm, current_price):
    """Use the recorded target, including frozen AI range boundaries."""
    target = price(alarm.get('hedef_fiyat'))
    if alarm.get('operator') == '>=':
        matched = current_price >= target
    elif alarm.get('operator') == '<=':
        matched = current_price <= target
    else:
        raise ValueError('Geçersiz alarm operatörü')
    if alarm.get('alarm_turu') == 'AI_ALIM_BOLGESI':
        upper = price(alarm.get('hedef_fiyat_ust'))
        if upper < target or alarm.get('operator') != '>=':
            raise ValueError('Geçersiz AI alım bölgesi')
        matched = matched and current_price <= upper
    return matched


def default_records():
    from veri_yollari import paths
    location = paths()
    return UserRecords(location.users, location.web, public_dir=location.public)


def alarmlari_kontrol_et(records=None, fiyat_saglayici=None, clock=istanbul_now,
                        max_price_age_seconds=MAX_PRICE_AGE_SECONDS):
    """One scheduler round: one quote per symbol, locked atomic trigger/outbox commit."""
    records = records or default_records()
    summary = {'aktif_alarm': 0, 'fiyat_okunan_sembol': 0, 'kontrol_edilen_alarm': 0,
               'tetiklenen_alarm': 0, 'gecersiz_alarm': 0, 'fiyat_hatalari': {}}
    with records.locked('fiyat_alarmlari.json') as (_, data):
        candidates = {}
        for user, alarms in data['kullanicilar'].items():
            if not isinstance(alarms, list):
                summary['gecersiz_alarm'] += 1
                continue
            for alarm in alarms:
                if not eligible(alarm):
                    continue
                try:
                    stock = symbol(alarm.get('sembol'))
                    if alarm.get('kaynak') not in ('AI', 'MANUEL'):
                        raise ValueError('Geçersiz alarm kaynağı')
                    created = aware_time(alarm.get('created_at'))
                    if created > aware_time(clock()):
                        raise ValueError('Alarm oluşturma zamanı gelecekte')
                    if not isinstance(alarm.get('id'), str) or not alarm['id']:
                        raise ValueError('Alarm ID eksik')
                    # Validate before asking for a quote. Bad records never stop
                    # valid alarms, even those on the same stock.
                    alarm_kosulu_saglandi(alarm, 1)
                    candidates[(user, alarm['id'])] = (copy.deepcopy(alarm), stock, created)
                except (ValueError, TypeError, RecordError):
                    summary['gecersiz_alarm'] += 1
    summary['aktif_alarm'] = len(candidates)
    if not candidates:
        return summary

    earliest = {}
    for _, stock, created in candidates.values():
        earliest[stock] = max(created, earliest.get(stock, created))
    provider = fiyat_saglayici if fiyat_saglayici is not None else MevcutFiyatSaglayici(
        records.web_dir, not_before=earliest, clock=clock, max_age_seconds=max_price_age_seconds,
        public_dir=records.public_dir)
    quotes = {}
    # No user-data lock is held while a provider performs network I/O.
    for stock in sorted(earliest):
        try:
            quote = provider(stock)
            if not isinstance(quote, FiyatVerisi):
                quote = FiyatVerisi(price(quote), aware_time(clock()), 'injected_provider')
            observed = aware_time(quote.observed_at)
            age = (aware_time(clock()) - observed).total_seconds()
            if not 0 <= age <= max_price_age_seconds or observed < earliest[stock]:
                raise ValueError('Fiyat eski, gelecekte veya alarmdan önce alınmış')
            quotes[stock] = FiyatVerisi(price(quote.fiyat), observed, str(quote.kaynak))
            summary['fiyat_okunan_sembol'] += 1
        except Exception as error:
            # Symbol-level isolation, without logging user IDs or provider secrets.
            summary['fiyat_hatalari'][stock] = type(error).__name__

    if not quotes:
        return summary
    with records.locked('fiyat_alarmlari.json') as (path, data):
        changed = False
        condition_fields = ('sembol', 'kaynak', 'alarm_turu', 'hedef_fiyat',
                            'operator', 'hedef_fiyat_ust', 'created_at')
        for user, alarms in data['kullanicilar'].items():
            if not isinstance(alarms, list):
                continue
            for alarm in alarms:
                if not eligible(alarm):
                    continue
                original = candidates.get((user, alarm.get('id')))
                if original is None:
                    continue  # Deleted/new/deactivated alarms aren't resurrected.
                old_alarm, stock, _ = original
                if any(alarm.get(k) != old_alarm.get(k) for k in condition_fields):
                    continue
                quote = quotes.get(stock)
                if quote is None:
                    continue
                # A slow provider for another stock must not turn an old quote
                # into a fresh trigger by the time the commit lock is obtained.
                if not 0 <= (aware_time(clock()) - quote.observed_at).total_seconds() <= max_price_age_seconds:
                    summary['fiyat_hatalari'][stock] = 'StalePriceAtCommit'
                    continue
                try:
                    summary['kontrol_edilen_alarm'] += 1
                    if not alarm_kosulu_saglandi(alarm, quote.fiyat):
                        continue
                except (ValueError, TypeError, RecordError):
                    summary['gecersiz_alarm'] += 1
                    continue
                triggered_at = aware_time(clock()).isoformat(timespec='seconds')
                alarm.update(aktif=False, status='TRIGGERED', triggered_at=triggered_at,
                             triggered_price=quote.fiyat, updated_at=triggered_at,
                             triggered_quote_at=quote.observed_at.isoformat(timespec='seconds'),
                             triggered_price_source=quote.kaynak)
                # Alarm and notification event share one atomic transaction/file.
                # Future push workers can consume PENDING events per user.
                events = data.setdefault('pending_notifications', {}).setdefault(user, [])
                event_id = 'price_alarm:' + alarm['id']
                if not any(e.get('id') == event_id for e in events):
                    events.append({'id': event_id, 'event_type': 'PRICE_ALARM_TRIGGERED',
                                   'alarm_id': alarm['id'], 'sembol': stock,
                                   'kaynak': alarm.get('kaynak'), 'alarm_turu': alarm.get('alarm_turu'),
                                   'hedef_fiyat': alarm['hedef_fiyat'], 'operator': alarm['operator'],
                                   'hedef_fiyat_ust': alarm.get('hedef_fiyat_ust'),
                                   'triggered_at': triggered_at, 'triggered_price': quote.fiyat,
                                   'created_at': triggered_at, 'status': 'PENDING'})
                changed = True
                summary['tetiklenen_alarm'] += 1
        if changed:
            atomic_json(path, data)
    return summary


def surekli_izle(bekleme_saniye=30, records=None, fiyat_saglayici=None, stop_event=None):
    """Opt-in loop; no cloud/central-worker registration and no push delivery."""
    if bekleme_saniye <= 0:
        raise ValueError('Bekleme süresi pozitif olmalı')
    stop_event = stop_event or Event()
    records = records or default_records()
    while not stop_event.is_set():
        try:
            alarmlari_kontrol_et(records, fiyat_saglayici)
        except Exception as error:
            print('Fiyat alarm turu tamamlanamadı:', type(error).__name__, flush=True)
        stop_event.wait(bekleme_saniye)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fiyat alarmlarını tek tur kontrol eder; --watch ile izler.')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=30)
    args = parser.parse_args()
    if args.watch:
        surekli_izle(args.interval)
    else:
        print(json.dumps(alarmlari_kontrol_et(), ensure_ascii=False))
