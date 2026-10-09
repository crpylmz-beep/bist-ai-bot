"""Verified KAP corporate equities; never substitute an issuer/index universe.

Refresh is bounded, once daily in memory, and retains the verified seed on failure.
No user, archive or production data is written by this module.
"""
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = 'https://www.kap.org.tr/tr/Pazarlar'
MARKETS = {1, 2, 3, 4, 16}
MAX_BYTES = 4 * 1024 * 1024
_lock = threading.RLock()
_values = None
_attempt_day = None
_refreshing = False


def validate(groups):
    found = set(); stocks = set()
    for group in groups:
        meta = group.get('metadata', group)
        if str(meta.get('financialMarketNo')) != '1':
            continue
        number = int(meta.get('marketNo', -1))
        if number not in MARKETS:
            continue
        if number in found:
            raise ValueError('Duplicate KAP market')
        found.add(number)
        content = group.get('content', group.get('marketDetailContentList'))
        if not isinstance(content, list) or not content:
            raise ValueError('Incomplete KAP market')
        for row in content:
            code = row.get('stockCode', '')
            if not re.fullmatch('[A-Z0-9]{2,12}', code) or code == 'KTEST' or row.get('fundOid'):
                raise ValueError('Invalid corporate equity entry')
            if 'IGS' not in str(row.get('types','')).split(',') or code in stocks:
                raise ValueError('Conflicting corporate equity entry')
            stocks.add(code)
    if found != MARKETS or not 500 <= len(stocks) <= 800:
        raise ValueError('Incomplete KAP equity universe')
    return sorted(stocks)


def parse_page(page):
    from bs4 import BeautifulSoup
    parts = []
    for script in BeautifulSoup(page, 'html.parser').find_all('script'):
        match = re.fullmatch(r'self\.__next_f\.push\((.*)\)', script.string or '', re.S)
        if match:
            value = json.loads(match.group(1))
            if len(value) > 1 and isinstance(value[1], str):parts.append(value[1])
    groups = []; nodes = 0
    def walk(value, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 40 or nodes > 100000:raise ValueError('KAP parse limit')
        if isinstance(value, dict):
            if {'financialMarketNo', 'marketNo'} <= value.keys() and ('content' in value or 'marketDetailContentList' in value):
                groups.append(value);return
            for item in value.values():walk(item, depth+1)
        elif isinstance(value, list):
            for item in value:walk(item, depth+1)
        elif isinstance(value,str) and value.startswith(('[','{')):
            try: decoded=json.loads(value)
            except ValueError:return
            walk(decoded,depth+1)
    for line in ''.join(parts).splitlines():
        if ':' not in line:continue
        try: value=json.JSONDecoder().raw_decode(line.split(':',1)[1])[0]
        except ValueError:continue
        walk(value)
    return validate(groups)


def refresh():
    """Public read-only source refresh. Failure is visible; last verified list survives."""
    import requests
    global _values
    try:
        with requests.get(SOURCE, timeout=(5,15), stream=True) as response:
            response.raise_for_status()
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>MAX_BYTES:raise ValueError('KAP response too large')
                chunks.append(chunk)
        candidate=parse_page(b''.join(chunks).decode('utf-8'))
        with _lock:
            old=_seed()
            if len(set(old)^set(candidate)) > max(20,len(old)//10):
                raise ValueError('KAP membership change requires review')
            _values=candidate
        logging.info('[KAP_UNIVERSE] verified count=%d',len(candidate))
        return True
    except Exception as error:
        logging.warning('[KAP_UNIVERSE] refresh_failed type=%s retained_verified=true',type(error).__name__)
        return False


def _seed():
    global _values
    if _values is None:
        _values=validate(json.loads(Path(__file__).with_name('kap_pay_evreni.json').read_text())['groups'])
    return _values


def _background():
    global _refreshing
    try:refresh()
    finally:
        with _lock:_refreshing=False


def symbols(refresh_daily=True):
    global _attempt_day,_refreshing
    with _lock:
        result=list(_seed())
        day=datetime.now(ZoneInfo('Europe/Istanbul')).date()
        if refresh_daily and day != _attempt_day and not _refreshing:
            _attempt_day=day;_refreshing=True
            threading.Thread(target=_background,name='kap-universe-refresh',daemon=True).start()
        return result
