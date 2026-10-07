"""Browser-scoped manual levels and price alarm storage."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import uuid

LEVEL_FIELDS = ('manuel_al', 'manuel_sat', 'manuel_stop', 'manuel_hedef')
MANUAL_TYPES = {'FIYAT_USTU': ('>=', None), 'FIYAT_ALTI': ('<=', None),
                'MANUEL_AL': ('<=', 'manuel_al'), 'MANUEL_SAT': ('>=', 'manuel_sat'),
                'MANUEL_STOP': ('<=', 'manuel_stop'), 'MANUEL_HEDEF': ('>=', 'manuel_hedef')}
AI_TYPES = {'AI_ALIM_BOLGESI': ('>=', 'alim_alt'), 'AI_HEDEF': ('>=', 'hedef'),
            'AI_STOP': ('<=', 'stop')}


class RecordError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(timespec='seconds')


def symbol(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{2,12}', value):
        raise RecordError('Geçersiz hisse sembolü.')
    return value


def price(value, optional=False):
    if optional and (value is None or value == ''):
        return None
    if isinstance(value, bool):
        raise RecordError('Fiyat pozitif ve geçerli bir sayı olmalı.')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise RecordError('Fiyat pozitif ve geçerli bir sayı olmalı.') from None
    if not math.isfinite(result) or not 0 < result <= 1_000_000_000:
        raise RecordError('Fiyat pozitif ve geçerli bir sayı olmalı.')
    return result


def atomic_json(path, value):
    fd, tmp = tempfile.mkstemp(prefix='.user-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        # Persist the rename too, so a completed trigger/outbox transaction
        # survives a machine crash rather than just a process restart.
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class UserRecords:
    def __init__(self, data_dir, web_dir, public_dir=None):
        self.data_dir = Path(data_dir)
        self.web_dir = Path(web_dir)
        self.public_dir = Path(public_dir) if public_dir is not None else self.web_dir / 'data'

    @contextmanager
    def locked(self, name):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.data_dir / name
        with (self.data_dir / (name + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                    if data.get('surum') != 1 or not isinstance(data.get('kullanicilar'), dict):
                        raise ValueError('Invalid store')
                except (ValueError, AttributeError):
                    raise RecordError('Kayıt dosyası okunamadı; mevcut veri korunuyor.', 503) from None
            else:
                data = {'surum': 1, 'kullanicilar': {}}
                atomic_json(path, data)
            yield path, data

    def levels(self, user, stock):
        with self.locked('kullanici_seviyeleri.json') as (_, data):
            return copy.deepcopy(data['kullanicilar'].get(user, {}).get(stock))

    def save_levels(self, user, stock, body):
        if set(body) - set(LEVEL_FIELDS):
            raise RecordError('Yalnızca manuel seviye alanları kaydedilebilir.')
        values = {field: price(body.get(field), optional=True) for field in LEVEL_FIELDS}
        with self.locked('kullanici_seviyeleri.json') as (path, data):
            records = data['kullanicilar'].setdefault(user, {})
            previous = records.get(stock, {})
            record = {'sembol': stock, **values, 'created_at': previous.get('created_at', now()),
                      'updated_at': now()}
            records[stock] = record
            atomic_json(path, data)
            return copy.deepcopy(record)

    def automatic(self, stock, model='GUNLUK'):
        if model not in ('GUNLUK', 'GUN_ICI'):
            raise RecordError('Geçersiz analiz kaynağı.')
        path = self.public_dir / ('gun_ici_tum.json' if model == 'GUN_ICI' else 'bist_data.json')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            row = next((h for h in data.get('hisseler', []) if h.get('sembol') == stock), {})
        except (OSError, ValueError, AttributeError, TypeError):
            row, data = {}, {}
        def pick(*keys):
            return next((row[k] for k in keys if row.get(k) is not None), None)
        if model == 'GUN_ICI':
            values = {
                'alim_alt': pick('gun_ici_alim_alt'), 'alim_ust': pick('gun_ici_alim_ust'),
                'sat_kar_al': pick('gun_ici_kar_al'), 'stop': pick('gun_ici_stop'),
                'hedef': pick('gun_ici_kar_al'), 'destek': pick('destek'), 'direnc': pick('direnc'),
                'hacimli_kirilim': pick('gun_ici_kirilim'), 'risk_getiri': pick('gun_ici_rr'),
                'karar': pick('gun_ici_karar'), 'nihai_ai_puan': pick('gun_ici_nihai_ai_puan', 'gun_ici_puan'),
                'guven': pick('gun_ici_guven'),
            }
        else:
            values = {
                'alim_alt': pick('karar_giris_alt', 'giris_alt'),
                'alim_ust': pick('karar_giris_ust', 'giris_ust'),
                'sat_kar_al': pick('karar_hedef', 'hedef1'), 'stop': pick('karar_stop', 'stop'),
                'hedef': pick('karar_hedef', 'hedef1'), 'destek': pick('destek'), 'direnc': pick('direnc'),
                'hacimli_kirilim': pick('yarin_kirilim'), 'risk_getiri': pick('karar_rr', 'risk_getiri'),
                'karar': pick('karar'), 'nihai_ai_puan': pick('nihai_ai_puan', 'puan'),
                'guven': pick('guven_skoru'),
            }
        result = {**values, 'model': model, 'updated_at': data.get('updated_at'),
                  'eski_zaman_metni': data.get('guncelleme'), 'sembol': stock}
        result['analiz_kimligi'] = hashlib.sha256(
            json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        from teknik_gostergeler import view
        result['teknik_gostergeler']=view(row,now())
        result['teknik_katkilar']=copy.deepcopy(row.get('teknik_katkilar'))
        result['teknik_shadow_puan']=row.get('teknik_shadow_puan')
        result['teknik_shadow_duzeltmesi']=row.get('teknik_shadow_duzeltmesi')
        from ai_karar_motoru import decision_view,stamp
        result['nihai_karar']=decision_view(row.get('nihai_karar'),stamp(now()))
        return result

    def alarms(self, user, stock):
        with self.locked('fiyat_alarmlari.json') as (_, data):
            return copy.deepcopy([a for a in data['kullanicilar'].get(user, []) if a['sembol'] == stock])

    def create_alarm(self, user, stock, body):
        source, kind = body.get('kaynak'), body.get('alarm_turu')
        snapshot = None
        upper = None
        if source == 'AI' and kind in AI_TYPES:
            snapshot = self.automatic(stock, body.get('model', 'GUNLUK'))
            if body.get('analiz_kimligi') != snapshot['analiz_kimligi']:
                raise RecordError('Otomatik seviyeler değişti. Yeni değerleri inceleyip tekrar alarm kurun.', 409)
            operator, field = AI_TYPES[kind]
            target = price(snapshot.get(field))
            if kind == 'AI_ALIM_BOLGESI':
                upper = price(snapshot.get('alim_ust'))
                if upper < target:
                    raise RecordError('AI alım bölgesi geçersiz.')
        elif source == 'MANUEL' and kind in MANUAL_TYPES:
            operator, field = MANUAL_TYPES[kind]
            if field:
                levels = self.levels(user, stock) or {}
                target = price(levels.get(field))
                snapshot = {'manuel_updated_at': levels.get('updated_at'), field: target}
            else:
                target = price(body.get('hedef_fiyat'))
        else:
            raise RecordError('Geçersiz alarm kaynağı veya türü.')
        # Target is resolved by the server; requests cannot rewrite AI/manual levels.
        fingerprint = [stock, source, kind, operator, target, upper,
                       snapshot.get('model') if source == 'AI' else None]
        with self.locked('fiyat_alarmlari.json') as (path, data):
            records = data['kullanicilar'].setdefault(user, [])
            existing = next((a for a in records if a.get('aktif') and a.get('dedup') == fingerprint), None)
            if existing:
                return copy.deepcopy(existing), False
            record = {'id': uuid.uuid4().hex, 'sembol': stock, 'kaynak': source,
                      'alarm_turu': kind, 'hedef_fiyat': target, 'operator': operator,
                      'aktif': True, 'status': 'ACTIVE', 'created_at': now(),
                      'triggered_at': None, 'triggered_price': None,
                      'seviye_snapshot': snapshot, 'hedef_fiyat_ust': upper, 'dedup': fingerprint}
            records.append(record)
            atomic_json(path, data)
            return copy.deepcopy(record), True

    def change_alarm(self, user, alarm_id, delete=False):
        with self.locked('fiyat_alarmlari.json') as (path, data):
            records = data['kullanicilar'].get(user, [])
            alarm = next((a for a in records if a['id'] == alarm_id), None)
            if not alarm:
                raise RecordError('Alarm bulunamadı.', 404)
            if delete:
                records.remove(alarm)
            else:
                alarm['aktif'] = False
                if not alarm.get('triggered_at') and alarm.get('status') != 'TRIGGERED':
                    alarm['status'] = 'DISABLED'
                alarm['updated_at'] = now()
            atomic_json(path, data)
            return {'ok': True}
