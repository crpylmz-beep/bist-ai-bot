"""Bounded official-site discovery and announcement identity parsing."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup

TOPICS = ('yatirimci','investor','duyuru','announcement','haber','news','basin',
          'press','finansal','financial','faaliyet','presentation','sunum','sozlesme','ihale','yatirim')


def normalized(text):
    return re.sub(r'\s+',' ',str(text).lower().translate(str.maketrans('çğıöşü','cgiosu'))).strip()


def canonical(url, base=None):
    parsed=urlsplit(urljoin(base or '',url))
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Geçersiz şirket URL')
    if parsed.port not in (None,80,443):raise ValueError('Geçersiz şirket port')
    host=parsed.hostname.lower().removeprefix('www.')
    query=urlencode(sorted((k,v) for k,v in parse_qsl(parsed.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')))
    # HTTP/HTTPS and www variants share an identity; transport retains actual URL.
    return urlunsplit(('https',host,parsed.path.rstrip('/') or '/',query,''))


def official(url, home):
    try:
        target=urlsplit(canonical(url)).hostname
        origin=urlsplit(canonical(home)).hostname
        return target==origin or target.endswith('.'+origin)
    except (ValueError,AttributeError):return False


def relevant(text):
    value=normalized(text)
    return any(word in value for word in TOPICS)


def published_time(value):
    if not value:return None
    try:date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError:
        try:date=parsedate_to_datetime(str(value))
        except (ValueError,TypeError):return None
    if date.tzinfo is None:date=date.replace(tzinfo=ZoneInfo('Europe/Istanbul'))
    return date.astimezone(ZoneInfo('Europe/Istanbul')).isoformat(timespec='seconds')


def clean_text(html):
    soup=BeautifulSoup(html or '', 'html.parser')
    for tag in soup(['script','style','noscript','nav','header','footer']):tag.decompose()
    return ' '.join(soup.get_text(' ',strip=True).split())


def discover(html, url, home):
    soup=BeautifulSoup(html or '', 'html.parser')
    feeds=[];pages=[]
    for tag in soup.find_all('link',href=True):
        if tag.get('type','').split(';')[0] in ('application/rss+xml','application/atom+xml'):
            link=urljoin(url,tag['href'])
            if official(link,home):feeds.append(link)
    for tag in soup.find_all('a',href=True):
        link=urljoin(url,tag['href'])
        text=tag.get_text(' ',strip=True)
        if official(link,home) and relevant(text+' '+link) and not urlsplit(link).path.lower().endswith(('.pdf','.jpg','.png','.zip')):
            pages.append(link)
        if official(link,home) and any(word in normalized(text+' '+link) for word in ('rss','atom','feed')):feeds.append(link)
    # Investor relations gets visited first, without expanding an entire site graph.
    pages=sorted(set(pages),key=lambda u:not any(x in normalized(u) for x in ('investor','yatirimci')))
    return list(dict.fromkeys(feeds))[:3],pages[:8]


def xml_kind(text):
    try:return ET.fromstring(text).tag.rsplit('}',1)[-1].lower()
    except ET.ParseError:return None


def sitemap_links(text,home):
    try:root=ET.fromstring(text)
    except ET.ParseError:return [],[]
    if root.tag.rsplit('}',1)[-1]=='sitemapindex':
        maps=[node.text.strip() for node in root.iter() if node.tag.rsplit('}',1)[-1]=='loc' and node.text and official(node.text.strip(),home)]
        return [],maps[:2]
    pages=[node.text.strip() for node in root.iter() if node.tag.rsplit('}',1)[-1]=='loc' and node.text and official(node.text.strip(),home) and relevant(node.text)]
    return list(dict.fromkeys(pages))[:8],[]


def record(stock,home,url,title,published,text):
    precision='day' if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(published or '')) else 'time'
    published=published_time(published)
    title=' '.join(clean_text(title).split())[:240]
    text=clean_text(text)[:2000]
    if not title or not official(url,home):return None
    content_hash=hashlib.sha256((title+'\n'+text).encode()).hexdigest()
    identity={'sembol':stock,'url':canonical(url),'title':title,'published':published or '', 'hash':content_hash}
    identifier=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'id':identifier,'content_id':identifier,'story_key':hashlib.sha256((stock+'|'+canonical(url)).encode()).hexdigest(),
            'sembol':stock,'kaynak':'SIRKET_SITESI','company_url':home,'url':url,'canonical_url':canonical(url),
            'baslik':title,'published_at':published or None,'published_precision':precision if published else None,
            'metin':text,'content_hash':content_hash}


def extract(text,url,stock,home):
    kind=xml_kind(text)
    rows=[]
    if kind in ('rss','feed','rdf'):
        root=ET.fromstring(text)
        for node in root.iter():
            if node.tag.rsplit('}',1)[-1] not in ('item','entry'):continue
            fields={child.tag.rsplit('}',1)[-1]:child for child in node}
            def value(*names):
                for name in names:
                    if name in fields:return ''.join(fields[name].itertext()).strip()
                return ''
            link=value('link')
            for child in node:
                if child.tag.rsplit('}',1)[-1]=='link' and child.get('rel','alternate')=='alternate':link=child.get('href') or link
            if link:
                row=record(stock,home,urljoin(url,link),value('title'),value('pubDate','published','updated'),value('description','summary','content','encoded'))
                if row:rows.append(row)
    else:
        soup=BeautifulSoup(text,'html.parser')
        for tag in soup.select('article a[href], main a[href], .news a[href], .duyurular a[href], a[href]'):
            if tag.find_parent(['nav','header','footer']):continue
            link=urljoin(url,tag['href']);title=tag.get_text(' ',strip=True)
            if not official(link,home) or canonical(link)==canonical(url) or len(title)<12:continue
            # Navigation/category links alone are not announcements.
            path=urlsplit(link).path.lower().rstrip('/')
            if path.split('/')[-1] in ('news','haberler','duyurular','announcements','investor-relations','yatirimci-iliskileri','press-releases'):continue
            container=tag.find_parent('article') or tag.find_parent('li') or tag.parent
            if not (tag.find_parent('article') or relevant(title+' '+link) or relevant(url)):continue
            date=container.find('time') if container else None
            published=(date.get('datetime') or date.get_text(' ',strip=True)) if date else None
            row=record(stock,home,link,title,published,str(container))
            if row:rows.append(row)
    # Baseline every item present in the bounded response, including long feeds.
    return list({row['story_key']:row for row in rows}.values())
