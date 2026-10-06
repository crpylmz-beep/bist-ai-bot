import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor
import requests

from sirket_site_motoru import SirketSiteMotoru,AccessBlocked
from sirket_site_icerik import canonical, record, extract, discover
from veri_yollari import paths


class CompanyMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.clock=[1791284400]
        self.mapping=self.root/'mapping.json'
        self.mapping.write_text(json.dumps({'hisseler':{'AAA':{'siteler':['https://a.example/']}}}))
        self.fixture={'https://a.example/robots.txt':'User-agent: *\nAllow: /',
                      'https://a.example/':'<a href="/investor-relations">Investor Relations</a>',
                      'https://a.example/investor-relations':'<link rel="alternate" type="application/rss+xml" href="/rss.xml">',
                      'https://a.example/rss.xml':self.rss('old')}
        self.calls=[];self.enqueue=Mock();self.analyzer=Mock(return_value={'etki_puani':3,'yon':'POZITIF','guven':70,'onem':80,'gerekce':'sözleşme','sembol':'AAA'})

    def rss(self,key):
        return f'<rss><channel><item><title>Yeni yatırım sözleşmesi {key}</title><link>https://a.example/news/{key}</link><description>Yeni sözleşme kazanıldı</description></item></channel></rss>'

    def fetch(self,url):
        self.calls.append(url)
        result=self.fixture.get(url,'<html><body></body></html>')
        if isinstance(result,Exception):raise result
        return result

    def monitor(self,**kwargs):
        return SirketSiteMotoru(self.root/'runtime',self.enqueue,self.mapping,self.fetch,
            public_path=self.root/'public/news.json',analyzer=self.analyzer,clock=lambda:self.clock[0],**kwargs)

    def advance(self,monitor,seconds=1000):
        self.clock[0]+=seconds;return monitor.tek_tur()

    def state(self,monitor):return json.loads(monitor.path.read_text())

    def test_investor_feed_discovery_and_quiet_first_sync(self):
        monitor=self.monitor();self.assertEqual(monitor.tek_tur(),0)
        self.assertIn('https://a.example/investor-relations',self.calls)
        self.assertIn('https://a.example/rss.xml',self.calls)
        self.enqueue.assert_not_called();self.analyzer.assert_not_called()
        self.assertEqual(len(self.state(monitor)['sites']['AAA']['seen']),1)
        self.assertFalse(monitor.public_path.exists())

    def test_new_feed_item_ai_queue_and_duplicate_prevention(self):
        monitor=self.monitor();monitor.tek_tur()
        self.fixture['https://a.example/rss.xml']=self.rss('new')
        self.assertEqual(self.advance(monitor),1);self.assertEqual(self.advance(monitor),0)
        self.enqueue.assert_called_once();self.assertEqual(self.enqueue.call_args.args[0],'AAA');self.assertFalse(self.enqueue.call_args.kwargs['gun_ici_yenile'])
        self.analyzer.assert_called_once()
        event=json.loads(monitor.public_path.read_text())['haberler'][0]
        for key in ('content_id','content_hash','company_url','url','published_at','discovered_at','metin','analiz'):self.assertIn(key,event)
        self.assertTrue(event['discovered_at'].endswith('+03:00'))
        self.assertNotIn('seen',event)

    def test_sitemap_bounded_discovery_and_quiet_source_baseline(self):
        self.fixture['https://a.example/']='<main>Şirket resmi sitesi</main>'
        self.fixture['https://a.example/sitemap.xml']='''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://a.example/announcements</loc></url><url><loc>https://a.example/contact</loc></url><url><loc>https://evil.example/news</loc></url></urlset>'''
        self.fixture['https://a.example/announcements']='<article><a href="/news/old">Eski yatırım sözleşmesi</a></article>'
        monitor=self.monitor();monitor.tek_tur();self.analyzer.assert_not_called()
        self.assertIn('https://a.example/announcements',self.calls)
        self.assertNotIn('https://a.example/contact',self.calls)
        self.assertNotIn('https://evil.example/news',self.calls)
        self.fixture['https://a.example/announcements']='<article><a href="/news/new">Yeni yatırım sözleşmesi</a></article>'
        self.assertEqual(self.advance(monitor),1)

    def test_sitemap_index_followed_on_later_bounded_round(self):
        self.fixture['https://a.example/']='Home'
        self.fixture['https://a.example/sitemap.xml']='<sitemapindex><sitemap><loc>https://a.example/news-map.xml</loc></sitemap></sitemapindex>'
        self.fixture['https://a.example/news-map.xml']='<urlset><url><loc>https://a.example/news/list</loc></url></urlset>'
        monitor=self.monitor(request_budget=3);monitor.tek_tur()
        self.advance(monitor);self.assertIn('https://a.example/news-map.xml',self.calls)
        self.enqueue.assert_not_called()

    def test_batch_cursor_restart_and_backoff_do_not_starve_other_sites(self):
        self.mapping.write_text(json.dumps({'hisseler':{s:{'siteler':['https://'+s.lower()+'.example/']} for s in ('AAA','BBB','CCC')}}))
        monitor=self.monitor(batch_size=1);monitor.tek_tur()
        self.assertEqual(self.state(monitor)['cursor'],1)
        resumed=self.monitor(batch_size=1);resumed.tek_tur();self.assertEqual(self.state(resumed)['cursor'],2)
        state=self.state(resumed);state['sites']['CCC']={'next_check_at':self.clock[0]+100000}
        resumed.path.write_text(json.dumps(state));resumed.tek_tur();self.assertEqual(self.state(resumed)['cursor'],0)

    def test_timeout_isolated_next_company_continues(self):
        self.mapping.write_text(json.dumps({'hisseler':{'AAA':{'siteler':['https://a.example/']},'BBB':{'siteler':['https://b.example/']}}}))
        self.fixture['https://a.example/robots.txt']=requests.Timeout()
        self.fixture['https://b.example/robots.txt']='User-agent: *\nAllow: /'
        self.fixture['https://b.example/']='Healthy company'
        monitor=self.monitor(batch_size=2);monitor.tek_tur()
        state=self.state(monitor)['sites']
        self.assertEqual(state['AAA']['status'],'BACKOFF');self.assertEqual(state['BBB']['status'],'OK')

    def test_403_429_retry_after_and_no_aggressive_retry(self):
        for status in (403,429):
            with self.subTest(status=status):
                directory=self.root/str(status)
                self.fixture['https://a.example/robots.txt']=AccessBlocked(status,'7200')
                monitor=SirketSiteMotoru(directory,self.enqueue,self.mapping,self.fetch,
                    public_path=directory/'public.json',analyzer=self.analyzer,clock=lambda:self.clock[0])
                monitor.tek_tur();before=len(self.calls);self.clock[0]+=100;monitor.tek_tur()
                self.assertEqual(len(self.calls),before)
                self.assertGreaterEqual(self.state(monitor)['sites']['AAA']['next_check_at'],self.clock[0]+7100)

    def test_robots_disallow_blocks_homepage(self):
        self.fixture['https://a.example/robots.txt']='User-agent: *\nDisallow: /'
        monitor=self.monitor();monitor.tek_tur()
        self.assertNotIn('https://a.example/',self.calls)
        self.assertEqual(self.state(monitor)['sites']['AAA']['http_status'],403)

    def test_atom_and_canonical_hash_identity(self):
        atom='<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>İhale sözleşmesi</title><link href="/news/a"/><published>2026-10-06T12:00:00+03:00</published><summary>Yeni sözleşme</summary></entry></feed>'
        rows=extract(atom,'https://a.example/feed.xml','AAA','https://a.example/')
        self.assertEqual(len(rows),1)
        a=record('AAA','https://a.example/','http://www.a.example/news/a/?utm_source=x','İhale sözleşmesi',None,'Yeni sözleşme')
        b=record('AAA','https://a.example/','https://a.example/news/a','İhale sözleşmesi',None,'Yeni   sözleşme')
        self.assertEqual(a['id'],b['id'])
        c=record('AAA','https://a.example/','https://a.example/news/a','İhale sözleşmesi',None,'İçerik değişti')
        self.assertNotEqual(a['content_hash'],c['content_hash']);self.assertEqual(a['story_key'],c['story_key'])

    def test_menu_changes_do_not_create_news(self):
        self.fixture['https://a.example/']='<nav><a href="/news">Haberler menüsü</a></nav>'
        monitor=self.monitor();monitor.tek_tur()
        self.fixture['https://a.example/']='<nav>Yeni Menü <a href="/news">Haberler menüsü</a></nav>'
        self.advance(monitor);self.enqueue.assert_not_called()

    def test_pending_retry_keeps_id_timestamp_and_does_not_repeat_ai(self):
        monitor=self.monitor();monitor.tek_tur();self.fixture['https://a.example/rss.xml']=self.rss('new')
        self.enqueue.side_effect=OSError();self.advance(monitor)
        site=self.state(monitor)['sites']['AAA'];event=next(iter(site['pending'].values()))
        first=event['id'];stamp=event['discovered_at'];self.enqueue.side_effect=None
        self.advance(monitor);self.analyzer.assert_called_once()
        saved=json.loads(monitor.public_path.read_text())['haberler'][0]
        self.assertEqual((saved['id'],saved['discovered_at']),(first,stamp))
        self.assertEqual(self.state(monitor)['sites']['AAA']['pending'],{})

    def test_dynamic_site_flag_and_malformed_html(self):
        self.fixture['https://a.example/']='<script>render()</script><div id="app">'
        monitor=self.monitor();monitor.tek_tur()
        self.assertIn('ikinci_yontem_gerekli',self.state(monitor)['sites']['AAA']['status'])

    def test_domain_pacing_and_request_budget(self):
        sleeps=[]
        def sleeper(seconds):sleeps.append(seconds);self.clock[0]+=seconds
        monitor=self.monitor(min_interval=2,sleep=sleeper,request_budget=3)
        monitor.tek_tur();self.assertLessEqual(len(self.calls),3);self.assertTrue(sleeps)
        self.assertTrue(all(value>=2 for value in sleeps))

    def test_real_ai_bridge_locked_history_and_metadata(self):
        import haber_zeka
        history=self.root/'runtime/history.json'
        event=record('AAA','https://a.example/','https://a.example/news/a','Yeni sözleşme kazanıldı',None,'İhale sözleşmesi')
        event['discovered_at']='2026-10-06T12:00:00+03:00'
        from haber_tekillestirme import CanonicalNews
        ledger=CanonicalNews(self.root/'runtime/dedup',self.root/'public/canonical.json',history)
        queue=Mock()
        output=ledger.process(event,enqueue=queue,analyze=SirketSiteMotoru.analyze)['analiz']
        self.assertGreater(output['etki_puani'],0)
        for key in ('yon','guven','onem','gerekce','sembol'):self.assertIn(key,output)
        with ThreadPoolExecutor(3) as pool:list(pool.map(lambda _:ledger.process(event,queue,analyze=SirketSiteMotoru.analyze),range(3)))
        rows=json.loads(history.read_text())['haberler'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['content_id'],event['id'])

    def test_long_feed_initial_sync_marks_every_item_seen(self):
        items=''.join(f'<item><title>Eski yatırım duyurusu {i}</title><link>https://a.example/news/{i}</link></item>' for i in range(150))
        self.fixture['https://a.example/rss.xml']='<rss><channel>'+items+'</channel></rss>'
        monitor=self.monitor();monitor.tek_tur()
        self.assertEqual(len(self.state(monitor)['sites']['AAA']['seen']),150)
        self.analyzer.assert_not_called()

    def test_later_old_dated_content_remains_quiet(self):
        monitor=self.monitor();monitor.tek_tur()
        self.fixture['https://a.example/rss.xml']=self.rss('archive').replace('</item>','<pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate></item>')
        self.advance(monitor);self.enqueue.assert_not_called();self.analyzer.assert_not_called()

    def test_date_only_same_day_new_url_is_not_discarded_as_old(self):
        monitor=self.monitor();monitor.tek_tur()
        from datetime import datetime
        from zoneinfo import ZoneInfo
        day=datetime.fromtimestamp(self.clock[0],ZoneInfo('Europe/Istanbul')).date().isoformat()
        self.fixture['https://a.example/rss.xml']=self.rss('new-day').replace('</item>',f'<pubDate>{day}</pubDate></item>')
        self.assertEqual(self.advance(monitor),1);self.enqueue.assert_called_once()

    def test_newly_discovered_source_primed_without_historical_alerts(self):
        monitor=self.monitor();monitor.tek_tur()
        state=self.state(monitor);site=state['sites']['AAA']
        site['feeds'].append('https://a.example/other.xml');site['feed_cursor']=1
        monitor.path.write_text(json.dumps(state))
        self.fixture['https://a.example/other.xml']=self.rss('other-old')
        self.advance(monitor);self.enqueue.assert_not_called()

    def test_robots_crawl_delay_respected(self):
        self.fixture['https://a.example/robots.txt']='User-agent: *\nAllow: /\nCrawl-delay: 5'
        sleeps=[]
        def sleeper(seconds):sleeps.append(seconds);self.clock[0]+=seconds
        monitor=self.monitor(min_interval=2,sleep=sleeper)
        monitor.tek_tur();self.assertTrue(sleeps)
        self.assertTrue(all(value>=5 for value in sleeps))

    def test_redirect_normalization_and_external_domain_block(self):
        class Response:
            encoding='utf-8'
            def __init__(self,redirect=None):
                self.is_redirect=bool(redirect);self.status_code=302 if redirect else 200
                self.headers={'Location':redirect} if redirect else {'Content-Type':'text/html'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_content(self,size):yield b'<html>official</html>'
        with patch('sirket_site_motoru.socket.getaddrinfo',return_value=[(0,0,0,'',('8.8.8.8',443))]), \
             patch('sirket_site_motoru.requests.get',side_effect=[Response('https://a.example/'),Response()]) as fetch:
            result=SirketSiteMotoru.read_page('http://www.a.example/',allowed=lambda url:'a.example' in url)
            self.assertEqual(result['url'],'https://a.example/');self.assertEqual(fetch.call_count,2)
        from sirket_site_icerik import official
        with patch('sirket_site_motoru.socket.getaddrinfo',return_value=[(0,0,0,'',('8.8.8.8',443))]), \
             patch('sirket_site_motoru.requests.get',return_value=Response('https://evil.example/')) as fetch:
            with self.assertRaises(ValueError):SirketSiteMotoru.read_page('https://a.example/',allowed=lambda url:official(url,'https://a.example/'))
            self.assertEqual(fetch.call_count,1)

    def test_shutdown_stops_new_network_work(self):
        monitor=self.monitor(stop=lambda:True)
        self.assertEqual(monitor.tek_tur(),0)
        self.assertEqual(self.calls,[])
        self.enqueue.assert_not_called()

    def test_shared_data_root_paths(self):
        with patch.dict('os.environ',{'BIST_DATA_DIR':str(self.root/'volume'),'BIST_RUNTIME_DIR':''}):
            monitor=SirketSiteMotoru(enqueue=self.enqueue)
            self.assertEqual(monitor.path,paths().runtime/'sirket_site_durum.json')
            self.assertEqual(monitor.public_path,paths().public/'sirket_haberleri.json')
            self.assertEqual(monitor.mapping,paths().public/'sirket_site_haritasi.json')


if __name__=='__main__':unittest.main()
