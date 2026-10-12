import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

from haber_tekillestirme import CanonicalNews,prepare,compare


def race_worker(root,event):
    root=Path(root)
    def marker(stage):
        with (root/'calls.txt').open('a') as stream:stream.write(stage+'\n')
    def analyze(event):
        marker('AI');return {'etki_puani':9,'guven':90,'onem':90,'etki_sinifi':'GUCLU_POZITIF'}
    CanonicalNews(root/'runtime',root/'public/news.json',root/'runtime/history.json').process(
        event,analyze=analyze,enqueue=lambda *a,**k:marker('QUEUE'),
        alarm_writer=lambda *a:marker('ALARM'),notification_writer=lambda *a:marker('PUSH'))


class CanonicalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.news=CanonicalNews(self.root/'runtime',self.root/'public/news.json',self.root/'runtime/history.json')
        self.time='2026-10-06T12:00:00+03:00'
        self.ai=Mock(return_value={'etki_puani':9,'guven':90,'onem':90,'etki_sinifi':'GUCLU_POZITIF'})
        self.queue=Mock();self.alarm=Mock();self.push=Mock()

    def event(self,title='XYZ A.Ş. 500 milyon TL tutarında sözleşme imzaladı',source='KAP',stock='XYZ',time=None,text=None):
        return {'sembol':stock,'baslik':title,'metin':text or title,'kaynak':source,
                'url':'https://kap.org.tr/a' if source=='KAP' else 'https://xyz.example/news/a',
                'published_at':time or self.time,'discovered_at':time or self.time}

    def process(self,event):return self.news.process(event,analyze=self.ai,enqueue=self.queue,alarm_writer=self.alarm,notification_writer=self.push)

    def test_exact_duplicate_and_single_effects(self):
        event=self.event();first=self.process(event);second=self.process(event)
        self.assertEqual(second['duplicate_status'],'EXACT_DUPLICATE');self.assertEqual(first['canonical_id'],second['canonical_id'])
        for effect in (self.ai,self.queue,self.alarm,self.push):effect.assert_called_once()
        self.assertEqual(len(json.loads(self.news.history_path.read_text())['haberler']),1)

    def test_requested_fuzzy_example_and_both_source_orders(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                root=self.root/str(reverse);news=CanonicalNews(root/'runtime',root/'public/news.json',root/'history.json')
                a=self.event();b=self.event('500 Milyon TL Tutarında Yeni Sözleşme','SIRKET_SITE')
                queue=Mock();ai=Mock(return_value={'etki_puani':9,'guven':90,'onem':90,'etki_sinifi':'GUCLU_POZITIF'});alarm=Mock();push=Mock()
                first,second=(b,a) if reverse else (a,b)
                initial=news.process(first,queue,ai,alarm,push);later=news.process(second,queue,ai,alarm,push)
                self.assertEqual(initial['canonical_id'],later['canonical_id'])
                self.assertEqual(later['duplicate_status'],'LIKELY_DUPLICATE')
                for effect in (ai,queue,alarm,push):effect.assert_called_once()
                record=json.loads(news.path.read_text())['haberler'][0]
                self.assertEqual(record['ana_kaynak'],'KAP');self.assertEqual(record['kaynak_etiketi'],'KAP + ŞİRKET_SITE')
                self.assertEqual(len(record['kaynaklar']),2)
                self.assertEqual(len(json.loads(news.public_path.read_text())['alarmlar']),1)
                self.assertEqual(len(json.loads(news.history_path.read_text())['haberler']),1)

    def test_different_amount_event_and_counterparty_not_merged(self):
        a=prepare(self.event('500 milyon TL sözleşme'))
        b=prepare(self.event('1,2 milyar TL yeni ihale'))
        self.assertEqual(compare(a,b),'DIFFERENT_EVENT')
        a=prepare(self.event('500 milyon TL Alfa ile sözleşme'))
        b=prepare(self.event('500 milyon TL Beta ile sözleşme'))
        self.assertEqual(compare(a,b),'DIFFERENT_EVENT')
        self.process(self.event('500 milyon TL sözleşme'))
        self.process(self.event('1,2 milyar TL yeni ihale'))
        self.assertEqual(len(json.loads(self.news.path.read_text())['haberler']),2)

    def test_contract_cancellation_is_separate_event(self):
        a=prepare(self.event('500 milyon TL sözleşme imzalandı'))
        b=prepare(self.event('500 milyon TL sözleşme iptal edildi'))
        self.assertEqual(compare(a,b),'DIFFERENT_EVENT')

    def test_generic_words_are_insufficient(self):
        a=prepare(self.event('Yeni sözleşme','KAP',text='Alfa şirketi ile savunma sistemleri teslimatı'))
        b=prepare(self.event('Yeni sözleşme','SIRKET_SITE',text='Beta müşterisi için gıda ürünleri satışı'))
        self.assertEqual(compare(a,b),'DIFFERENT_EVENT')
        a=prepare(self.event('Yeni sözleşme'))
        b=prepare(self.event('Yeni sözleşme','SIRKET_SITE'))
        self.assertEqual(compare(a,b),'DIFFERENT_EVENT')

    def test_date_only_publication_uses_discovery_time(self):
        event=self.event()
        event.update(published_at='2026-10-06',published_precision='day')
        self.assertEqual(prepare(event)['event_time'],self.time)

    def test_different_symbol_and_weeks_later(self):
        self.process(self.event());self.process(self.event(stock='ABC'))
        self.process(self.event(time='2026-10-26T12:00:00+03:00'))
        self.assertEqual(self.ai.call_count,3)

    def test_configurable_window(self):
        news=CanonicalNews(self.root/'other',self.root/'other-public.json',self.root/'other-history.json',window_seconds=60)
        a=self.event();b=self.event(time='2026-10-06T12:02:00+03:00')
        self.assertEqual(compare(prepare(a),prepare(b),news.window),'DIFFERENT_EVENT')
        with self.assertRaises(ValueError):CanonicalNews(window_seconds=0)

    def test_concurrent_threads_and_processes_produce_one_record(self):
        with ThreadPoolExecutor(6) as pool:list(pool.map(lambda _:self.process(self.event()),range(12)))
        self.ai.assert_called_once();self.queue.assert_called_once()
        root=self.root/'process';root.mkdir()
        context=multiprocessing.get_context('fork')
        children=[context.Process(target=race_worker,args=(str(root),self.event(source=source))) for source in ('KAP','SIRKET_SITE')]
        for child in children:child.start()
        for child in children:child.join(5);self.assertEqual(child.exitcode,0)
        stages=(root/'calls.txt').read_text().splitlines()
        for stage in ('AI','ALARM','QUEUE','PUSH'):self.assertEqual(stages.count(stage),1)
        self.assertEqual(len(json.loads((root/'public/news.json').read_text())['alarmlar']),1)

    def test_failed_enqueue_retry_keeps_ai_and_alarm_once(self):
        self.queue.side_effect=OSError()
        with self.assertRaises(OSError):self.process(self.event())
        self.queue.side_effect=None;self.process(self.event())
        self.ai.assert_called_once();self.alarm.assert_called_once();self.push.assert_called_once()

    def test_legacy_history_preserved_and_enrichment_no_second_row(self):
        self.news.history_path.parent.mkdir(parents=True,exist_ok=True)
        legacy={'id':'old','sembol':'AAA','baslik':'Legacy','etki_puani':1}
        self.news.history_path.write_text(json.dumps({'surum':1,'haberler':[legacy]}))
        self.process(self.event(source='SIRKET_SITE'));self.process(self.event())
        rows=json.loads(self.news.history_path.read_text())['haberler']
        self.assertEqual(rows[0],legacy);self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['kaynak'],'KAP + ŞİRKET_SITE')


if __name__=='__main__':unittest.main()
