"""Opt-in Web Push storage and one-round outbox delivery; no scheduler."""
import base64
import copy
import hashlib
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit
from requests.exceptions import RequestException

from kullanici_kayitlari import RecordError, atomic_json, now

SUBSCRIPTIONS = 'push_subscriptions.json'
OUTBOX = 'fiyat_alarmlari.json'


def normalize_public_key(value):
    """Return canonical uncompressed P-256 base64url; never expose private key."""
    import re
    from cryptography.hazmat.primitives.asymmetric import ec
    key=value.strip()
    if key.startswith('VAPID_PUBLIC_KEY='):
        key=key.split('=',1)[1].strip()
    key=key.strip('\"\'')
    key=''.join(key.split())
    if not re.fullmatch(r'[A-Za-z0-9_+/\-]+={0,2}',key):
        raise ValueError('Invalid public key')
    raw=base64.b64decode(key.replace('-','+').replace('_','/')+'='*(-len(key)%4),validate=True)
    if len(raw)!=65 or raw[0]!=4:
        raise ValueError('Invalid P-256 length/prefix')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),raw)
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def public_config():
    value=os.environ.get('VAPID_PUBLIC_KEY','')
    recovered=False
    try:
        key=normalize_public_key(value) if value.strip() else ''
        if not key:raise ValueError('Missing public key')
    except (ValueError,TypeError):
        # Recover the PUBLIC half from the existing private key; never rotate keys.
        # This also repairs accidentally pasting the private/string label as public.
        try:
            from py_vapid import Vapid
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            vapid=Vapid.from_string(os.environ.get('VAPID_PRIVATE_KEY','').strip())
            if not isinstance(vapid.public_key.curve,ec.SECP256R1):raise ValueError('Wrong curve')
            raw=vapid.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
            key=normalize_public_key(base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii'))
            recovered=True
        except (ValueError,TypeError,AttributeError):
            return {'public_key':'','configured':False,'public_key_error':bool(value.strip())}
    result={'public_key':key, 'configured':bool(key and os.environ.get('VAPID_PRIVATE_KEY') and os.environ.get('VAPID_SUBJECT'))}
    if recovered:result['public_key_recovered']=True
    return result


def validate_endpoint(endpoint):
    """Reject non-HTTPS/private destinations before persisting or sending."""
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or '').lower()
    allowed = ('fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com',
               'web.push.apple.com', 'notify.windows.com')
    if not any(host == domain or host.endswith('.' + domain) for domain in allowed):
        raise RecordError('Desteklenmeyen push sağlayıcısı.')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.port not in (None, 443)
            or len(endpoint) > 4096):
        raise RecordError('Geçersiz push endpoint.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except (OSError, ValueError):
        raise RecordError('Push endpoint genel HTTPS adresi olmalı.') from None
    return endpoint


def subscription_save(records, user, payload):
    try:
        endpoint = validate_endpoint(str(payload['endpoint']))
        keys = payload['keys']
        for name, size in (('p256dh', 65), ('auth', 16)):
            value = keys[name]
            decoded = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            if len(decoded) != size or (name == 'p256dh' and decoded[0] != 4):
                raise ValueError()
        browser = str(payload['browser_id'])
        if not browser or len(browser) > 128:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise RecordError('Geçersiz subscription kaydı.') from None
    identifier = hashlib.sha256(endpoint.encode()).hexdigest()
    with records.locked(SUBSCRIPTIONS) as (path, data):
        # One endpoint belongs to one browser session, never to multiple owners.
        for owner, subscriptions in data['kullanicilar'].items():
            if owner != user and identifier in subscriptions:
                raise RecordError('Subscription başka kullanıcıya ait.', 409)
        subscriptions = data['kullanicilar'].setdefault(user, {})
        old = subscriptions.get(identifier, {})
        subscriptions[identifier] = {'id': identifier, 'endpoint': endpoint, 'keys': {k: keys[k] for k in ('p256dh', 'auth')},
                                    'user_id': user, 'browser_id': browser, 'created_at': old.get('created_at', now()),
                                    'updated_at': now(), 'active': True}
        atomic_json(path, data)
    return {'id': identifier, 'active': True}


def subscription_disable(records, user, identifier):
    with records.locked(SUBSCRIPTIONS) as (path, data):
        sub = data['kullanicilar'].get(user, {}).get(identifier)
        if not sub:
            raise RecordError('Subscription bulunamadı.', 404)
        sub.update(active=False, updated_at=now())
        atomic_json(path, data)
    return {'id': identifier, 'active': False}


def notification_payload(event):
    stock = event['sembol']
    if not stock.isalnum() or len(stock) > 12:
        raise RecordError('Geçersiz bildirim sembolü.')
    ai = event.get('kaynak') == 'AI'
    return {'id': event['id'], 'title': f"{'🤖' if ai else '🚨'} {stock} {'AI ' if ai else ''}Alarmı",
            'body': f"Fiyat {float(event['triggered_price']):.2f} TL seviyesine ulaştı. Kaynak: {'AI Alarmı' if ai else 'Manuel Alarm'}",
            'url': '/?stock=' + stock}


def web_push_sender(subscription, payload):
    from pywebpush import webpush
    config = public_config()
    if not config['configured']:
        raise RuntimeError('VAPID yapılandırması eksik')
    validate_endpoint(subscription['endpoint'])
    webpush(subscription_info={'endpoint': subscription['endpoint'], 'keys': subscription['keys']},
            data=json.dumps(payload, ensure_ascii=False), vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],
            vapid_claims={'sub': os.environ['VAPID_SUBJECT']}, timeout=15, ttl=3600)


def bildirimleri_gonder(records=None, sender=None):
    """Single round. Durable SENDING claims prevent concurrent/ambiguous resend.

    After an interrupted send, SENDING requires manual reconciliation; it is
    intentionally not retried automatically because delivery may have succeeded.
    Explicit sender errors become FAILED and can retry on the next round.
    """
    if records is None:
        from fiyat_alarm_motoru import default_records
        records = default_records()
    if sender is None:
        if not public_config()['configured']:
            raise RecordError('VAPID environment değişkenleri eksik.', 503)
        sender = web_push_sender
    counts = {'sent': 0, 'failed': 0, 'invalid': 0}
    # Common lock order with opt-in/out. A disable waits for an in-flight send.
    with records.locked(SUBSCRIPTIONS) as (sub_path, subscriptions):
        with records.locked(OUTBOX) as (_, data):
            events = [(user, event['id']) for user, rows in data.get('pending_notifications', {}).items()
                      for event in rows if event.get('status') in ('PENDING', 'FAILED')]
        for user, event_id in events:
            active = [s for s in subscriptions['kullanicilar'].get(user, {}).values() if s.get('active')]
            for sub in active:
                with records.locked(OUTBOX) as (path, data):
                    event = next((e for e in data.get('pending_notifications', {}).get(user, []) if e['id'] == event_id), None)
                    if not event or event.get('status') == 'SENT':
                        continue
                    deliveries = event.setdefault('deliveries', {})
                    delivery = deliveries.setdefault(sub['id'], {'status': 'PENDING', 'retry_count': 0})
                    if delivery['status'] in ('SENT', 'SENDING', 'INVALID'):
                        continue
                    payload = notification_payload(event)
                    delivery.update(status='SENDING', attempted_at=now())
                    atomic_json(path, data)
                try:
                    sender(copy.deepcopy(sub), payload)
                    status, error = 'SENT', None
                except Exception as exc:
                    response = getattr(exc, 'response', None)
                    invalid = getattr(response, 'status_code', None) in (404, 410)
                    # Network disconnect/timeout may occur after server acceptance.
                    # Keep the claim instead of risking a duplicate delivery.
                    uncertain = isinstance(exc, (RequestException, TimeoutError)) and response is None
                    status = 'SENDING' if uncertain else ('INVALID' if invalid else 'FAILED')
                    error = type(exc).__name__
                with records.locked(OUTBOX) as (path, data):
                    event = next(e for e in data['pending_notifications'][user] if e['id'] == event_id)
                    delivery = event['deliveries'][sub['id']]
                    delivery['status'] = status
                    if status == 'SENT':
                        delivery['sent_at'] = now()
                        counts['sent'] += 1
                        delivery.pop('error', None)
                    else:
                        delivery['error'] = error  # Never persist endpoint/auth in exception text.
                        delivery['retry_count'] += 1
                        event['retry_count'] = event.get('retry_count', 0) + 1
                        event['error'] = error
                        counts['failed'] += 1
                    if status == 'INVALID':
                        sub.update(active=False, updated_at=now())
                        atomic_json(sub_path, subscriptions)
                        counts['invalid'] += 1
                    remaining = [s['id'] for s in active if s.get('active')]
                    if remaining and all(event['deliveries'].get(i, {}).get('status') == 'SENT' for i in remaining):
                        event.update(status='SENT', sent_at=now())
                        event.pop('error', None)
                    elif any(d.get('status') == 'FAILED' for d in event['deliveries'].values()):
                        event['status'] = 'FAILED'
                    atomic_json(path, data)
    return counts


if __name__ == '__main__':
    print(json.dumps(bildirimleri_gonder(), ensure_ascii=False))
