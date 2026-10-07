"""Rotating official announcement monitor with source baselines and bounded discovery."""
from veri_yollari import public_file, paths
import fcntl
import ipaddress
import json
import logging
import os
import socket
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from kullanici_kayitlari import atomic_json
from sirket_site_icerik import canonical, official, discover, extract, sitemap_links, xml_kind, clean_text

from gorev_hatalari import ResponseLimitError,SiteUrlError

MAX_RESPONSE_BYTES=512000

AGENT='BIST-Asistani-SiteMonitor'


class Deferred(Exception):
    pass


class AccessBlocked(Exception):
    def __init__(self,status,retry_after=None):
        self.status=status;self.retry_after=retry_after


class SirketSiteMotoru:
    def __init__(self, directory=None, enqueue=None, mapping=None, fetch=None, batch_size=None,
                 public_path=None, analyzer=None, clock=time.time, sleep=time.sleep,
                 min_interval=None, request_budget=4, stop=None):
        directory=Path(directory) if directory else paths().runtime
        self.path=directory/'sirket_site_durum.json'
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.mapping=Path(mapping) if mapping else public_file('sirket_site_haritasi.json')
        self.public_path=Path(public_path) if public_path else public_file('sirket_haberleri.json')
        self.enqueue=enqueue;self.fetch=fetch;self.analyzer=analyzer or self.analyze
        self.clock=clock;self.sleep=sleep
        self.min_interval=(0 if fetch else float(os.environ.get('COMPANY_SITE_DOMAIN_DELAY_SECONDS','2'))) if min_interval is None else min_interval
        self.batch_size=batch_size if batch_size is not None else int(os.environ.get('COMPANY_SITE_BATCH_SIZE','15'))
        if not 1<=self.batch_size<=20:raise ValueError('Şirket batch boyutu 1–20')
        if not 0<=self.min_interval<=60 or not 1<=request_budget<=8:raise ValueError('Geçersiz crawler limiti')
        self.request_budget=request_budget
        self.stop=stop or (lambda:False)
        from haber_tekillestirme import CanonicalNews
        local_history = directory/'haber_zeka_gecmisi.json' if directory.resolve()!=paths().runtime.resolve() or self.public_path.parent.resolve()!=paths().public.resolve() else None
        self.news = CanonicalNews(directory,self.public_path.parent/'canonical_haberler.json',local_history)


    def stamp(self):
        return datetime.fromtimestamp(self.clock(),ZoneInfo('Europe/Istanbul')).isoformat(timespec='seconds')

    @staticmethod
    def read_page(url, allowed=None, redirect_guard=None):
        deadline=time.monotonic()+45
        for _ in range(4):
            try:
                parsed=urlsplit(url);port=parsed.port
            except ValueError as error:raise SiteUrlError('Geçersiz şirket URL') from error
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or port not in (None,80,443):
                raise SiteUrlError('Geçersiz şirket URL')
            if allowed and not allowed(url):raise SiteUrlError('Resmi domain dışına yönlendirme')
            addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise SiteUrlError('Özel ağ URL')
            with requests.get(url,timeout=(5,15),stream=True,allow_redirects=False,verify=True,headers={'User-Agent':AGENT+'/2.0'}) as response:
                if response.status_code in (403,429):raise AccessBlocked(response.status_code,response.headers.get('Retry-After'))
                if response.is_redirect:
                    target=urljoin(url,response.headers['Location'])
                    if redirect_guard:redirect_guard(target)
                    url=target;continue
                response.raise_for_status()
                length=response.headers.get('Content-Length','')
                if length.isdigit() and int(length)>MAX_RESPONSE_BYTES:
                    raise ResponseLimitError('Yanıt boyutu sınırı')
                content=bytearray()
                for part in response.iter_content(8192):
                    if len(content)+len(part)>MAX_RESPONSE_BYTES:raise ResponseLimitError('Yanıt boyutu sınırı')
                    if time.monotonic()>deadline:raise requests.Timeout('Şirket sitesi yanıt süresi sınırı')
                    content.extend(part)
                mime=response.headers.get('Content-Type','').lower()
                if mime and not any(t in mime for t in ('html','xml','text/plain')):raise SiteUrlError('Desteklenmeyen içerik türü')
                encoding=response.encoding or 'utf-8'
                try:text=content.decode(encoding,errors='replace')
                except LookupError:text=content.decode('utf-8',errors='replace')
                return {'text':text,'url':url,'content_type':mime}
        raise SiteUrlError('Çok fazla yönlendirme')

    @staticmethod
    def analyze(event):
        import haber_zeka
        return haber_zeka.kap_haber_analiz_et(event['sembol'],event['baslik'],event['metin'],kaynak='SIRKET_SITESI')

    def _pace(self,url,state):
        domain=urlsplit(url).hostname.lower().removeprefix('www.')
        slot=state.setdefault('domains',{}).setdefault(domain,{})
        delay=max(0,slot.get('next_request_at',0)-self.clock())
        if delay>10:raise Deferred('Domain crawl-delay bekleniyor')
        if delay:self.sleep(delay)
        slot['next_request_at']=self.clock()+max(self.min_interval,slot.get('crawl_delay',0))
        atomic_json(self.path,state)  # Persist before network activity/restart.

    def _raw(self,url,state,home,robots=False):
        if self.stop():raise Deferred('Motor kapanıyor')
        if self.remaining<=0:raise Deferred('Tur istek limiti')
        if not official(url,home):raise SiteUrlError('Resmi URL dışı')
        self.remaining-=1;self._pace(url,state)
        if self.fetch:
            result=self.fetch(url)
        else:
            def guard(target):
                if not official(target,home):raise SiteUrlError('Resmi domain dışına yönlendirme')
                if not robots:self._robots(target,state,home)
                if self.remaining<=0:raise Deferred('Redirect istek limiti')
                self.remaining-=1;self._pace(target,state)
            result=self.read_page(url,allowed=lambda u:official(u,home),redirect_guard=guard)
        page=result if isinstance(result,dict) else {'text':result,'url':url}
        if not official(page.get('url',url),home):raise SiteUrlError('Resmi domain dışı')
        return page

    def _robots(self,url,state,home):
        parsed=urlsplit(url);origin=parsed.scheme+'://'+parsed.netloc
        cached=state.setdefault('robots',{}).get(origin)
        if not cached or self.clock()-cached.get('checked_at',0)>86400:
            try:page=self._raw(origin+'/robots.txt',state,home,robots=True);text=page['text']
            except requests.HTTPError as error:
                if getattr(error.response,'status_code',None)!=404:raise
                text='User-agent: *\nAllow: /'
            cached={'text':text,'checked_at':self.clock()};state['robots'][origin]=cached
            atomic_json(self.path,state)
        rules=RobotFileParser();rules.parse(cached['text'].splitlines())
        if not rules.can_fetch(AGENT,url):raise AccessBlocked(403)
        delay=rules.crawl_delay(AGENT) or rules.crawl_delay('*')
        if delay:
            slot=state['domains'].setdefault(parsed.hostname.lower().removeprefix('www.'),{})
            slot['next_request_at']=max(slot.get('next_request_at',0),self.clock()+min(delay,86400)) if not slot.get('crawl_delay') else slot.get('next_request_at',0)
            slot['crawl_delay']=delay
        return rules

    def _get(self,url,state,home):
        rules=self._robots(url,state,home)
        page=self._raw(url,state,home)
        delay=rules.crawl_delay(AGENT) or rules.crawl_delay('*') or 0
        domain=urlsplit(url).hostname.lower().removeprefix('www.')
        state['domains'][domain]['next_request_at']=self.clock()+max(self.min_interval,delay)
        return page

    def _process(self,site,state,stock,home,url,page,public):
        feeds,pages=discover(page['text'],page['url'],home)
        for kind,links in (('feeds',feeds),('pages',pages)):
            for link in links:
                if canonical(link) not in {canonical(v) for v in site[kind]}:site[kind].append(link)
            site[kind]=site[kind][:8 if kind=='pages' else 3]
        rows=extract(page['text'],page['url'],stock,home)
        source=canonical(page['url'])
        baseline=source not in site['baselines']
        for event in rows:
            key=event['story_key']
            if key in site['seen']:continue
            if baseline:
                site['seen'][key]=event['id'];continue
            # Older dated articles appearing later (pagination/feed reorder) are
            # not newly published news, even if their URL was outside the first page.
            if event.get('published_at'):
                published=datetime.fromisoformat(event['published_at']).timestamp()
                first=datetime.fromisoformat(site['baselines'][source]).timestamp()
                older=(datetime.fromtimestamp(published,ZoneInfo('Europe/Istanbul')).date()<datetime.fromtimestamp(first,ZoneInfo('Europe/Istanbul')).date()
                       if event.get('published_precision')=='day' else published<=first)
                if older:
                    site['seen'][key]=event['id'];continue
            event.setdefault('discovered_at',self.stamp())
            site['pending'].setdefault(key,event)
        site['baselines'].setdefault(source,self.stamp())
        site['last_content_count']=len(rows)
        if not rows and len(clean_text(page['text']))<80 and BeautifulSoup(page['text'],'html.parser').find('script'):
            site['status']='dinamik_site / ikinci_yontem_gerekli'
        atomic_json(self.path,state)
        return self._deliver(site,state,public)

    def _deliver(self,site,state,public):
        count=0
        for key,event in list(site['pending'].items())[:20]:
            from kap_canli import web_alarm_kaydet
            # Custom test analyzers still use the same canonical ledger, with a
            # local history/output target; no private production records are touched.
            result=self.news.process(event,enqueue=self.enqueue,analyze=self.analyzer,
                                     alarm_writer=lambda a,b:web_alarm_kaydet(a,b,output_path=self.public_path.parent/"kap_alarmlar.json"))
            event['analiz']=result['analiz']
            event['canonical_id']=result['canonical_id']
            event['kaynak_etiketi']=result['kaynak_etiketi']
            safe={k:event[k] for k in ('id','content_id','sembol','kaynak','company_url','url','baslik','published_at','discovered_at','metin','content_hash','analiz')}
            safe.update(canonical_id=event['canonical_id'],kaynak_etiketi=event['kaynak_etiketi'])
            public['haberler']=[h for h in public['haberler'] if h.get('canonical_id',h['id'])!=event['canonical_id']]+[safe]
            public['haberler']=public['haberler'][-500:];public['updated_at']=self.stamp()
            self.public_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            atomic_json(self.public_path,public)
            site['seen'][key]=event['id'];del site['pending'][key]
            atomic_json(self.path,state);count+=1
        return count

    def _visit(self,stock,home,site,state,public):
        try:canonical(home)
        except ValueError as error:raise SiteUrlError('Geçersiz şirket URL') from error
        self.remaining=self.request_budget
        count=self._deliver(site,state,public)
        if not site.get('home_done'):
            page=self._get(home,state,home)
            site['home']=page['url']
            count+=self._process(site,state,stock,site['home'],home,page,public)
            site['home_done']=True
        home=site.get('home',home)
        # Investor/announcement discovery, feed preference, then bounded sitemap.
        while self.remaining>0:
            unvisited=[url for url in site['pages'] if canonical(url) not in site['baselines']]
            if site['feeds']:
                url=site['feeds'][site.get('feed_cursor',0)%len(site['feeds'])]
                page=self._get(url,state,home);count+=self._process(site,state,stock,home,url,page,public)
                site['feed_cursor']=site.get('feed_cursor',0)+1
                break
            if unvisited:
                url=unvisited[0];page=self._get(url,state,home)
                count+=self._process(site,state,stock,home,url,page,public)
                continue
            if not site.get('sitemap_done'):
                parsed=urlsplit(home);url=parsed.scheme+'://'+parsed.netloc+'/sitemap.xml'
                try:page=self._get(url,state,home)
                except requests.HTTPError as error:
                    if getattr(error.response,'status_code',None)!=404:raise
                    site['sitemap_done']=True;continue
                links,maps=sitemap_links(page['text'],home)
                site['pages']=list(dict.fromkeys(site['pages']+links))[:8]
                site['sitemaps']=maps;site['sitemap_done']=True
                continue
            if site.get('sitemaps'):
                url=site['sitemaps'][0];page=self._get(url,state,home)
                links,_=sitemap_links(page['text'],home)
                site['pages']=list(dict.fromkeys(site['pages']+links))[:8];site['sitemaps'].pop(0)
                continue
            candidates=site['pages'] or [home]
            url=candidates[site.get('page_cursor',0)%len(candidates)]
            page=self._get(url,state,home);count+=self._process(site,state,stock,home,url,page,public)
            site['page_cursor']=site.get('page_cursor',0)+1
            break
        return count

    def tek_tur(self):
        with self.path.with_suffix('.json.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            return self._round()

    def _round(self):
        self.last_round_issue=None
        self.last_round_details={'processed':0,'successful':0,'skipped':0,'unsupported':0,'failed':0,'tls_errors':0,'http_errors':0,'response_too_large':0,'systemic_errors':0,'reasons':[]}
        self.last_round_isolated=False;self.last_round_systemic=False
        issues=[];affected_hosts=set()
        mapping=json.loads(self.mapping.read_text())['hisseler']
        entries=sorted((stock,row['siteler'][0]) for stock,row in mapping.items() if row.get('siteler'))
        if not entries:return 0
        state=json.loads(self.path.read_text()) if self.path.exists() else {'cursor':0,'sites':{}}
        public=json.loads(self.public_path.read_text()) if self.public_path.exists() else {'surum':1,'haberler':[]}
        start=state['cursor']%len(entries);count=0
        for offset in range(min(self.batch_size,len(entries))):
            if self.stop():break
            stock,home=entries[(start+offset)%len(entries)]
            site=state['sites'].setdefault(stock,{})
            self.last_round_details['processed']+=1
            if self.clock()<site.get('next_check_at',0):
                self.last_round_details['skipped']+=1
                if site.get('error_code') and len(self.last_round_details['reasons'])<25:
                    self.last_round_details['reasons'].append({'symbol':stock,'code':site['error_code']})
                state.update(cursor=(start+offset+1)%len(entries),updated_at=self.stamp())
                atomic_json(self.path,state)
                continue
            for key,default in (('feeds',[]),('pages',[]),('seen',{}),('baselines',{}),('pending',{})):
                site.setdefault(key,default)
            try:
                count+=self._visit(stock,home,site,state,public)
                self.last_round_details['successful']+=1
                site.update(failures=0,checked_at=self.stamp(),next_check_at=self.clock()+900)
                if not site.get('status','').startswith('dinamik_site'):site['status']='OK'
                site.pop('error',None);site.pop('error_code',None)
            except Deferred:
                self.last_round_details['skipped']+=1
                site.update(checked_at=self.stamp(),status='KESIF_DEVAM_EDIYOR',next_check_at=self.clock()+60)
            except Exception as error:
                from gorev_hatalari import describe,strongest,log_source
                self.last_round_issue=strongest([self.last_round_issue,describe(error,'COMPANY_SITE')]) if self.last_round_issue else describe(error,'COMPANY_SITE')
                log_source(error,'COMPANY_SITE')
                issue=describe(error,'COMPANY_SITE');issues.append(issue)
                self.last_round_details['failed']+=1
                self.last_round_details['tls_errors']+=issue['code']=='NETWORK_TLS'
                self.last_round_details['http_errors']+=bool(issue.get('http_status'))
                self.last_round_details['response_too_large']+=issue['code']=='SOURCE_RESPONSE_TOO_LARGE'
                if issue['code'] in ('NETWORK_TLS','NETWORK_DNS','NETWORK_CONNECTION','NETWORK_TIMEOUT','HTTP_UNAVAILABLE','HTTP_RATE_LIMIT'):
                    affected_hosts.add((urlsplit(home).hostname or '').lower().removeprefix('www.'))
                if len(self.last_round_details['reasons'])<25:
                    self.last_round_details['reasons'].append({'symbol':stock,**describe(error,'COMPANY_SITE')})
                failures=site.get('failures',0)+1
                status=getattr(error,'status',getattr(getattr(error,'response',None),'status_code',None))
                delay=min(86400,300*2**min(failures-1,8))
                if status in (403,429):delay=max(delay,3600 if status==403 else 900)
                retry=getattr(error,'retry_after',None)
                if retry:
                    try:delay=max(delay,min(86400,float(retry)))
                    except ValueError:
                        try:delay=max(delay,min(86400,parsedate_to_datetime(retry).timestamp()-self.clock()))
                        except (ValueError,TypeError):pass
                site.update(failures=failures,error=type(error).__name__,error_code=describe(error,'COMPANY_SITE')['code'],http_status=status,checked_at=self.stamp(),next_check_at=self.clock()+delay,status='BACKOFF')
                if status in (403,429):
                    domain=urlsplit(site.get('home',home)).hostname.lower().removeprefix('www.')
                    state.setdefault('domains',{}).setdefault(domain,{})['next_request_at']=self.clock()+delay
                logging.warning('[%s] COMPANY_SITE %s ERROR %s',self.stamp()[11:19],stock,type(error).__name__)
            # Advance/checkpoint after every company, preserving completed work on restart.
            state.update(cursor=(start+offset+1)%len(entries),updated_at=self.stamp(),surum=2)
            atomic_json(self.path,state)
        source_codes={'NETWORK_TLS','NETWORK_DNS','NETWORK_CONNECTION','NETWORK_TIMEOUT',
                      'HTTP_UNAVAILABLE','HTTP_RATE_LIMIT','HTTP_BLOCKED',
                      'SOURCE_RESPONSE_TOO_LARGE','SOURCE_URL_INVALID'}
        network_codes={'NETWORK_TLS','NETWORK_DNS','NETWORK_CONNECTION','NETWORK_TIMEOUT',
                       'HTTP_UNAVAILABLE','HTTP_RATE_LIMIT'}
        network_count=sum(i['code'] in network_codes for i in issues)
        attempted=self.last_round_details['successful']+self.last_round_details['failed']
        self.last_round_systemic=(len(affected_hosts)>=3 and network_count>=3
                                  and network_count/max(1,attempted)>=0.6)
        self.last_round_isolated=bool(issues) and not self.last_round_systemic and all(
            i['code'] in source_codes or (i['code']=='HTTP_REQUEST' and i.get('http_status') in (404,410))
            for i in issues)
        if self.last_round_systemic:
            self.last_round_details['systemic_errors']=network_count
            critical=[i for i in issues if i['code'] not in source_codes
                and not (i['code']=='HTTP_REQUEST' and i.get('http_status') in (404,410))]
            self.last_round_issue=strongest(critical+[i for i in issues if i['code'] in network_codes])
        return count
