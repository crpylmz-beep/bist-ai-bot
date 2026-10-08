"""Bounded public-feed collector. No article scraping, paywall bypass or raw archive."""
import logging
import os
import re
import time
from html import unescape
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

import requests
from haber_tekillestirme import CanonicalNews
from kullanici_kayitlari import now

SOURCES = (
    ('EKONOMIM', 'www.ekonomim.com', 'https://www.ekonomim.com/rss'),
    ('BLOOMBERG_HT', 'www.bloomberght.com', 'https://www.bloomberght.com/rss'),
    ('ENSONHABER_EKONOMI', 'www.ensonhaber.com', 'https://www.ensonhaber.com/rss/ekonomi.xml'),
)
AGENT = 'BIST-Asistani-News/1.0'
LIMIT = 512_000


def read_bounded(url):
    with requests.get(url, headers={'User-Agent': AGENT}, timeout=(5, 15),
                      stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('SOURCE_ACCESS_RESTRICTED')
        data = bytearray()
        for chunk in response.iter_content(8192):
            data.extend(chunk)
            if len(data) > LIMIT:
                raise ValueError('SOURCE_RESPONSE_TOO_LARGE')
        return bytes(data)


class EconomyNews:
    def __init__(self, universe, enqueue, fetch=read_bounded, news=None):
        self.universe, self.enqueue, self.fetch = universe, enqueue, fetch
        self.news = news or CanonicalNews()

    def one_round(self):
        symbols = set(self.universe())
        if not symbols:
            from gorev_hatalari import TaskIssue
            raise TaskIssue({'code':'EMPTY_UNIVERSE'},0)
        result = {'processed': 0, 'ignored': 0, 'errors': {}}
        current = datetime.fromisoformat(now())
        for source, host, default_url in SOURCES:
            try:
                url = os.environ.get(source + '_RSS_URL', default_url)
                parts = urlsplit(url)
                if parts.scheme != 'https' or parts.hostname != host or parts.username or parts.password:
                    raise ValueError('SOURCE_ACCESS_RESTRICTED')
                robots = RobotFileParser()
                policy=self.fetch('https://' + host + '/robots.txt').decode('utf-8', errors='replace')
                if not re.search(r'^\s*user-agent\s*:',policy,re.I|re.M):
                    raise ValueError('SOURCE_ROBOTS_DENIED')
                robots.parse(policy.splitlines())
                if not robots.can_fetch(AGENT, url):
                    raise ValueError('SOURCE_ROBOTS_DENIED')
                delay=robots.crawl_delay(AGENT) or robots.crawl_delay('*') or 0
                rate=robots.request_rate(AGENT) or robots.request_rate('*')
                if rate:delay=max(delay,rate.seconds / rate.requests)
                if delay>15:raise ValueError('SOURCE_CRAWL_DELAY')
                if delay:time.sleep(delay)
                payload = self.fetch(url)
                try:
                    xml=payload.decode('utf-8-sig')
                    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
                        raise ValueError('SOURCE_INVALID_FEED')
                    root = ET.fromstring(xml)
                except (ET.ParseError, UnicodeError):
                    raise ValueError('SOURCE_INVALID_FEED') from None
                if root.tag != 'rss':
                    raise ValueError('SOURCE_INVALID_FEED')
                for item in root.findall('./channel/item')[:30]:
                    title = unescape(re.sub('<[^>]+>', '', item.findtext('title') or ''))[:500]
                    summary = unescape(re.sub('<[^>]+>', '', item.findtext('description') or ''))[:1200]
                    link = item.findtext('link') or ''
                    link_parts = urlsplit(link)
                    if link_parts.scheme != 'https' or link_parts.hostname != host:
                        result['ignored'] += 1
                        continue
                    try:
                        published = parsedate_to_datetime(item.findtext('pubDate') or '')
                        if published.tzinfo is None or not current - timedelta(days=2) <= published <= current:
                            raise ValueError('stale')
                    except (ValueError, TypeError, OverflowError):
                        result['ignored'] += 1
                        continue
                    # Explicit ticker only: uncertain company-name inference must not affect a stock.
                    mentioned = set(re.findall(r'\b[A-Z][A-Z0-9]{2,5}\b', title + ' ' + summary)) & symbols
                    if not mentioned:
                        result['ignored'] += 1
                    from kap_canli import web_alarm_kaydet
                    for stock in sorted(mentioned)[:10]:
                        self.news.process({'sembol': stock, 'kaynak': source, 'baslik': title,
                                           'metin': summary, 'url': link,
                                           'published_at': published.isoformat()}, enqueue=self.enqueue,
                                          alarm_writer=web_alarm_kaydet)
                        result['processed'] += 1
            except Exception as error:
                from gorev_hatalari import describe
                issue = describe(error)
                # Fixed short codes, never a response body or credential-bearing URL.
                if isinstance(error, ValueError) and str(error).startswith('SOURCE_'):
                    issue = {'code': str(error), 'category': 'SOURCE_DATA', 'retryable': True}
                result['errors'][source] = issue
                logging.warning('[NEWS_SOURCE] source=%s code=%s', source, issue.get('code'))
        if result['errors']:
            from gorev_hatalari import TaskIssue, strongest
            raise TaskIssue(strongest(result['errors'].values()), result['processed'])
        return result
