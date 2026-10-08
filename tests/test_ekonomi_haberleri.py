import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from email.utils import format_datetime

from ekonomi_haberleri import EconomyNews, SOURCES, read_bounded, LIMIT
from gorev_hatalari import TaskIssue
from haber_tekillestirme import prepare


class FeedTests(unittest.TestCase):
    def setUp(self):self.enterContext(patch.object(EconomyNews,'_health'))
    def feed(self, host, title='THYAO yeni yatırım açıkladı'):
        date=format_datetime(datetime.now(timezone.utc))
        return f'<rss><channel><item><title>{title}</title><link>https://{host}/haber</link><pubDate>{date}</pubDate><description>THYAO yatırım</description></item></channel></rss>'.encode()

    def test_order_filter_and_minimal_payload(self):
        calls=[]; news=Mock()
        def fetch(url):
            calls.append(url)
            if url.endswith('robots.txt'):return b'User-agent: *\nAllow: /'
            return self.feed(url.split('/')[2])
        result=EconomyNews(lambda:['THYAO'],Mock(),fetch,news).one_round()
        self.assertEqual(result['processed'],3)
        self.assertEqual([url for url in calls if not url.endswith('robots.txt')],[row[2] for row in SOURCES])
        self.assertEqual(news.process.call_args_list[0].args[0]['kaynak'],'EKONOMIM')

    def test_robots_fail_closed_other_sources_continue(self):
        news=Mock()
        def fetch(url):
            if url.endswith('robots.txt'):
                return b'User-agent: *\nDisallow: /' if 'ekonomim' in url else b'User-agent: *\nAllow: /'
            return self.feed(url.split('/')[2])
        with self.assertRaises(TaskIssue):EconomyNews(lambda:['THYAO'],Mock(),fetch,news).one_round()
        self.assertEqual(news.process.call_count,2)

    def test_irrelevant_content_not_saved(self):
        news=Mock()
        fetch=lambda url:b'User-agent: *\nAllow: /' if url.endswith('robots.txt') else self.feed(url.split('/')[2],'Genel ekonomi haberi') .replace(b'THYAO yat',b'Genel yat')
        EconomyNews(lambda:['THYAO'],Mock(),fetch,news).one_round()
        news.process.assert_not_called()

    def test_access_error_not_hidden(self):
        with self.assertRaises(TaskIssue):EconomyNews(lambda:['THYAO'],Mock(),Mock(side_effect=ConnectionError()),Mock()).one_round()

    def test_source_identity_preserved(self):
        self.assertEqual(prepare({'sembol':'THYAO','kaynak':'EKONOMIM','baslik':'yatırım haberi'})['kaynak'],'EKONOMIM')

    def test_response_limit(self):
        response=Mock();response.status_code=200;response.iter_content.return_value=[b'x'*(LIMIT+1)]
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('ekonomi_haberleri.requests.get',return_value=response):
            with self.assertRaisesRegex(ValueError,'SOURCE_RESPONSE_TOO_LARGE'):read_bounded('https://example.org/feed')

class CanonicalFeedTests(unittest.TestCase):
    def setUp(self):self.enterContext(patch.object(EconomyNews,'_health'))
    def test_repeat_no_disk_write_and_kap_primary(self):
        import tempfile
        from pathlib import Path
        from haber_tekillestirme import CanonicalNews
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            news=CanonicalNews(root/'runtime',root/'public.json',root/'history.json')
            ai=Mock(return_value={'etki_puani':5})
            enqueue=Mock()
            event={'sembol':'THYAO','kaynak':'EKONOMIM','baslik':'THYAO yeni uçak yatırım sözleşmesi','metin':'yeni uçak yatırım sözleşmesi','url':'https://www.ekonomim.com/a','published_at':datetime.now(timezone.utc).isoformat()}
            first=news.process(event,enqueue,analyze=ai)
            before=news.path.stat().st_mtime_ns
            news.process(event,enqueue,analyze=ai)
            self.assertEqual(before,news.path.stat().st_mtime_ns)
            event.update(kaynak='KAP',url='https://kap.org.tr/a')
            second=news.process(event,enqueue,analyze=ai)
            self.assertEqual(first['canonical_id'],second['canonical_id'])
            self.assertEqual(second['kaynak_etiketi'],'KAP + EKONOMIM')
            ai.assert_called_once();enqueue.assert_called_once()

    def test_worker_no_continuous_company_site(self):
        from ana_motor_gorevleri import WorkerTasks
        worker=object.__new__(WorkerTasks)
        worker.bot=Mock();worker.enqueue=Mock()
        with patch('gunluk_al_sat.enabled',return_value=False):
            callbacks=worker.callbacks()
        self.assertNotIn('company_site',callbacks)
        self.assertIn('kap',callbacks)
        self.assertIn('economy_news',callbacks)

    def test_source_codes_not_unknown(self):
        from gorev_hatalari import public_issue
        for code in ('SOURCE_ACCESS_RESTRICTED','SOURCE_ROBOTS_DENIED','SOURCE_INVALID_FEED','SOURCE_CRAWL_DELAY','SOURCE_RESPONSE_TOO_LARGE'):
            self.assertEqual(public_issue({'code':code})['code'],code)

    def test_empty_universe_not_false_ok(self):
        with self.assertRaises(TaskIssue):EconomyNews(lambda:[],Mock(),Mock(),Mock()).one_round()

    def test_malformed_feed_classified(self):
        fetch=lambda url:b'User-agent: *\nAllow: /' if url.endswith('robots.txt') else b'<rss><broken'
        with self.assertRaises(TaskIssue) as caught:EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock()).one_round()
        self.assertEqual(caught.exception.issue['code'],'SOURCE_INVALID_FEED')

    def test_entity_and_encoded_xml_rejected(self):
        for payload in (b'<!DOCTYPE rss [<!ENTITY x "attack">]><rss/>', '<!DOCTYPE rss><rss/>'.encode('utf-16')):
            fetch=lambda url:b'User-agent: *\nAllow: /' if url.endswith('robots.txt') else payload
            with self.assertRaises(TaskIssue) as caught:EconomyNews(lambda:['THYAO'],Mock(),fetch,Mock()).one_round()
            self.assertEqual(caught.exception.issue['code'],'SOURCE_INVALID_FEED')

    def test_missing_public_projection_repaired_without_second_effect(self):
        import tempfile
        from pathlib import Path
        from haber_tekillestirme import CanonicalNews
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            news=CanonicalNews(root/'runtime',root/'public.json',root/'history.json')
            event={'sembol':'THYAO','kaynak':'EKONOMIM','baslik':'THYAO yeni uçak yatırım sözleşmesi','metin':'yeni uçak yatırım sözleşmesi','url':'https://www.ekonomim.com/a'}
            ai=Mock(return_value={'etki_puani':5});enqueue=Mock()
            news.process(event,enqueue,analyze=ai)
            news.public_path.unlink()
            news.process(event,enqueue,analyze=ai)
            self.assertTrue(news.public_path.exists())
            ai.assert_called_once();enqueue.assert_called_once()

    def test_seeded_projection_without_ledger_bootstraps(self):
        import tempfile
        from pathlib import Path
        from haber_tekillestirme import CanonicalNews
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'public.json').write_text('{}');(root/'history.json').write_text('{"surum":1,"haberler":[]}')
            news=CanonicalNews(root/'runtime',root/'public.json',root/'history.json')
            event={'sembol':'THYAO','kaynak':'EKONOMIM','baslik':'THYAO yeni yatırım sözleşmesi','metin':'yatırım'}
            self.assertTrue(news.process(event,Mock(),analyze=Mock(return_value={'etki_puani':5}))['created'])
