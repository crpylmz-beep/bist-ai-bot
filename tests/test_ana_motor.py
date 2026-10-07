import json
import os
import signal
import subprocess
import sys
import urllib.request
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from concurrent.futures import Future
from zoneinfo import ZoneInfo

import ana_motor as engine
from ana_motor_gorevleri import WorkerTasks
from sirket_site_motoru import SirketSiteMotoru


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.current=datetime(2026,10,6,12,tzinfo=engine.ISTANBUL);self.mono=0

    def motor(self,callbacks,**kwargs):
        instance=engine.AnaMotor(callbacks,self.root,clock=lambda:self.current,monotonic=lambda:self.mono,
                                 snapshot_exists=kwargs.pop('snapshot_exists',lambda day:False),**kwargs)
        self.addCleanup(instance.shutdown)
        return instance

    def complete(self,motor):
        for task in motor.tasks.values():
            if task.future:task.future.result(timeout=2) if not task.future.exception(timeout=2) else None
        motor.tick()

    def test_periods_single_flight_and_health(self):
        alarm,push=Mock(return_value=1),Mock(return_value=1)
        motor=self.motor({'alarm':alarm,'push':push})
        motor.tick();self.complete(motor)
        self.mono=19;motor.tick();self.assertEqual((alarm.call_count,push.call_count),(1,1))
        self.mono=20;motor.tick();self.complete(motor);self.assertEqual(push.call_count,2)
        self.mono=30;motor.tick();self.complete(motor);self.assertEqual(alarm.call_count,2)
        state=json.loads((self.root/'ana_motor_durum.json').read_text())
        self.assertIn('last_alarm_check',state);self.assertIn('last_push_check',state)
        self.assertTrue(state['updated_at'].endswith('+03:00'))
        with patch.object(engine,'istanbul_now',return_value=self.current):self.assertTrue(engine.health_snapshot(self.root)['healthy'])

    def test_failure_isolation_and_backoff(self):
        bad=Mock(side_effect=RuntimeError('secret'));good=Mock()
        motor=self.motor({'kap':bad,'alarm':good});motor.tick();self.complete(motor)
        self.assertEqual(good.call_count,1);self.assertEqual(bad.call_count,1)
        self.assertEqual(motor.tasks['kap'].next_due,60)
        self.mono=60;motor.tick();self.complete(motor)
        self.assertEqual(bad.call_count,2);self.assertEqual(motor.tasks['kap'].next_due,180)
        self.assertNotIn('secret',(self.root/'ana_motor_durum.json').read_text())

    def test_long_job_does_not_block_other_job_and_never_overlaps(self):
        gate=threading.Event();self.addCleanup(gate.set)
        started=threading.Event()
        def long():started.set();gate.wait(2)
        fast=Mock();motor=self.motor({'kap':long,'push':fast})
        motor.tick();self.assertTrue(started.wait(1));self.mono=1000;motor.tick()
        self.assertEqual(motor.state['tasks']['kap']['status'],'RUNNING')
        if motor.tasks['push'].future:motor.tasks['push'].future.result(timeout=1)
        self.assertGreaterEqual(fast.call_count,1)
        gate.set();self.complete(motor)

    def test_closed_market_weekend_and_holiday(self):
        callback=Mock();self.current=datetime(2026,10,6,19,tzinfo=engine.ISTANBUL)
        motor=self.motor({'intraday_top10':callback,'full_scan':callback});motor.tick();callback.assert_not_called()
        self.current=datetime(2026,10,10,12,tzinfo=engine.ISTANBUL);motor.tick();callback.assert_not_called()
        self.current=datetime(2026,10,6,12,tzinfo=engine.ISTANBUL)
        self.assertFalse(engine.market_open(self.current,lambda day:True))
        self.assertFalse(engine.market_open(datetime(2026,10,6,18,10,tzinfo=engine.ISTANBUL)))

    def test_utc_close_once_and_restart_snapshot_guard(self):
        self.current=datetime(2026,10,6,15,15,tzinfo=ZoneInfo('UTC'))
        self.assertTrue(engine.after_close(self.current));self.assertFalse(engine.market_open(self.current))
        callback=Mock(return_value=10);motor=self.motor({'yarin_top10':callback})
        motor.tick();self.complete(motor);self.mono=100000;motor.tick();callback.assert_called_once()
        motor.shutdown()
        restarted=self.motor({'yarin_top10':callback});restarted.tick();callback.assert_called_once()
        restarted.shutdown()
        (self.root/'ana_motor_durum.json').unlink()
        guarded=self.motor({'yarin_top10':callback},snapshot_exists=lambda day:True);guarded.tick();callback.assert_called_once()

    def test_technical_tasks_are_serialized(self):
        gate=threading.Event();self.addCleanup(gate.set)
        full=Mock(side_effect=lambda:gate.wait(2));intraday=Mock()
        motor=self.motor({'full_scan':full,'intraday_top10':intraday})
        motor.tick();self.assertIsNone(motor.tasks['intraday_top10'].future)
        gate.set();self.complete(motor);self.complete(motor);intraday.assert_called_once()

    def test_shutdown_and_single_process_lock(self):
        motor=self.motor({'alarm':Mock()});motor.tick();motor.request_stop(None,None);motor.shutdown()
        self.assertEqual(json.loads((self.root/'ana_motor_durum.json').read_text())['motor_durumu'],'STOPPED')
        with engine.worker_lock(self.root):
            with self.assertRaises(RuntimeError):
                with engine.worker_lock(self.root):pass


    def test_real_sigterm_shutdown(self):
        script="""import signal,time
from ana_motor import AnaMotor
motor=AnaMotor({'alarm':lambda:time.sleep(.02)})
signal.signal(signal.SIGTERM,motor.request_stop)
motor.run()
"""
        directory=self.root/'subprocess'
        child=subprocess.Popen([sys.executable,'-c',script],env=dict(os.environ,BIST_RUNTIME_DIR=str(directory)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.addCleanup(lambda:child.poll() is None and child.kill())
        path=directory/'ana_motor_durum.json'
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if path.exists() and json.loads(path.read_text()).get('tasks',{}):break
            time.sleep(.01)
        self.assertTrue(path.exists());child.send_signal(signal.SIGTERM)
        _,error=child.communicate(timeout=3)
        self.assertEqual(child.returncode,0,error.decode())
        self.assertEqual(json.loads(path.read_text())['motor_durumu'],'STOPPED')

    def test_http_health_has_no_private_data(self):
        from web_server import create_server
        from kullanici_kayitlari import UserRecords
        motor=self.motor({'alarm':Mock()});motor.tick();self.complete(motor)
        from veri_yollari import DataPaths
        location=DataPaths({'BIST_DATA_DIR':str(self.root/'volume')}, self.root/'repo')
        location.ensure()
        (location.runtime/'ana_motor_durum.json').write_bytes((self.root/'ana_motor_durum.json').read_bytes())
        server=create_server('127.0.0.1',0,UserRecords(self.root/'private',self.root/'web'),data_paths=location)
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        with patch.dict(os.environ,{'BIST_RUNTIME_DIR':str(self.root)}),patch.object(engine,'istanbul_now',return_value=self.current):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/health') as response:data=json.load(response)
        self.assertEqual(data['web'],'OK');self.assertTrue(data['ana_motor']['healthy'])
        for field in ('kullanicilar','pending_notifications','endpoint','keys'):
            self.assertNotIn(field,json.dumps(data))
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/.local/runtime/ana_motor_durum.json')
        self.assertEqual(error.exception.code,404)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.enterContext(patch.dict('os.environ',{'BIST_RUNTIME_DIR':str(self.root)}))
        self.ai = self.enterContext(patch('ai_karar_motoru.ai_batch_guncelle',return_value={'hisseler':{},'hatalar':{}}))

    def adapter(self):
        adapter=WorkerTasks();self.addCleanup(adapter.close);return adapter

    def test_events_enqueue_and_persist_without_recalculating_inline(self):
        import canli_motor
        original=canli_motor.oncelikli_hisse_guncelle
        adapter=self.adapter()
        adapter.original_priority=Mock(return_value={'sembol':'THYAO'})
        canli_motor.oncelikli_hisse_guncelle('THYAO');canli_motor.oncelikli_hisse_guncelle('THYAO')
        adapter.original_priority.assert_not_called();self.assertEqual(len(adapter.events),1)
        self.assertEqual(json.loads(adapter.queue_path.read_text())['THYAO'],2)
        adapter.priority();adapter.original_priority.assert_called_once_with('THYAO',gun_ici_yenile=False)
        self.assertEqual(len(adapter.events),0)
        # Restore actual function even though test substituted execution callback.
        adapter.original_priority=original

    def test_kap_macro_hooks_and_alarm_push_single_round(self):
        import kap_canli,makro_ai,canli_motor
        adapter=self.adapter()
        from haber_tekillestirme import CanonicalNews
        isolated=CanonicalNews(self.root/'dedup',self.root/'public/news.json',self.root/'history.json')
        with patch('haber_tekillestirme.CanonicalNews',return_value=isolated):
            kap_canli.kap_bildirim_isle({'sembol':'THYAO','ham_metin':'test'})
        with patch.object(makro_ai,'makro_etki_analiz_et',return_value={'kategori':'TEST','genel_puan':0}), \
             patch.object(makro_ai,'etkilenen_hisseleri_bul',return_value={'ASELS':{}}), \
             patch.object(makro_ai,'canli_makro_etki_yaz'):
            makro_ai.makro_haber_isle('test')
        self.assertEqual(set(adapter.events),{'THYAO','ASELS'})
        with patch('ana_motor_gorevleri.market_open',return_value=True), patch('fiyat_alarm_motoru.alarmlari_kontrol_et',return_value={}) as alarm,patch('push_bildirim_motoru.bildirimleri_gonder',return_value={}) as push:
            jobs=adapter.callbacks();jobs['alarm']();jobs['push']();alarm.assert_called_once_with();push.assert_called_once_with()

    def test_canonical_queue_event_id_is_durable_and_idempotent(self):
        adapter=WorkerTasks();adapter.enqueue('THYAO',event_id='canonical-one')
        before=adapter.queue_path.read_bytes()
        adapter.enqueue('THYAO',event_id='canonical-one')
        self.assertEqual(adapter.queue_path.read_bytes(),before)
        adapter.close()
        reopened=self.adapter();reopened.enqueue('THYAO',event_id='canonical-one')
        self.assertEqual(reopened.events['THYAO'],1)

    def test_new_event_during_analysis_is_not_lost(self):
        adapter=self.adapter();original=adapter.original_priority
        adapter.enqueue('THYAO')
        def analyze(stock,**kwargs):adapter.enqueue(stock);return {'sembol':stock}
        adapter.original_priority=analyze;adapter.priority();self.assertIn('THYAO',adapter.events)
        adapter.original_priority=original

    def test_kap_batch_does_not_mark_unprocessed_or_failed_events_seen(self):
        import kap_canli
        path=self.root/'kap.json';path.write_text('[]')
        events=[{'sembol':'THYAO','ham_metin':str(index)} for index in range(35)]
        def process(event):
            if event['ham_metin']=='0':raise RuntimeError('queue unavailable')
        with patch.object(kap_canli,'DURUM_DOSYA',path),patch.object(kap_canli,'kap_sayfa_oku',return_value='html'), \
             patch.object(kap_canli,'kap_bildirimleri_ayir',return_value=events),patch.object(kap_canli,'kap_bildirim_isle',side_effect=process):
            with self.assertRaises(RuntimeError):kap_canli.kap_kontrol()
            seen=set(json.loads(path.read_text()))
            self.assertEqual(len(seen),29)
            self.assertNotIn(kap_canli.kayit_id(events[0]),seen)
            self.assertNotIn(kap_canli.kayit_id(events[30]),seen)

    def test_queue_survives_worker_restart(self):
        adapter=WorkerTasks();adapter.enqueue('THYAO');adapter.close()
        reopened=self.adapter();self.assertEqual(reopened.events['THYAO'],1)

    def test_bounded_full_batch_preserves_other_stocks_and_retries_failures(self):
        adapter=self.adapter();adapter.batch_size=2
        path=self.root/'live.json';path.write_text(json.dumps({'hisseler':[{'sembol':'KEEP','fiyat':10}]}))
        with patch.object(adapter.bot,'DATA_FILE',str(path)),patch.object(adapter.bot,'bist_hisseleri_getir',return_value=['AAA','BBB','CCC']), \
             patch.object(adapter.live,'tek_hisse_guncelle',side_effect=lambda stock:(stock,{'sembol':stock,'fiyat':100}) if stock!='BBB' else (stock,None)), \
             patch.object(adapter.bot,'web_verisi_kaydet') as write,patch.object(adapter,'market_context',return_value={}) as market:
            from gorev_hatalari import TaskIssue
            with self.assertRaises(TaskIssue) as failure:adapter.full_scan()
            self.assertEqual(failure.exception.completed,1)
            self.assertEqual({row['sembol'] for row in write.call_args.args[0]},{'AAA','KEEP'})
            self.assertEqual(adapter.cursor,2);self.assertIn('BBB',adapter.events)
            market.assert_called_once_with()

    def test_incomplete_closing_scan_does_not_freeze(self):
        adapter=self.adapter()
        with patch.object(adapter.bot,'bist_hisseleri_getir',return_value=['AAA','BBB']), \
             patch.object(adapter.live,'tek_hisse_guncelle',return_value=('AAA',None)), \
             patch.object(adapter.bot,'yarin_top10_kilitli_kaydet') as freeze:
            with self.assertRaises(RuntimeError):adapter.tomorrow()
            freeze.assert_not_called()

    def test_company_small_rotating_batch_baseline_change_and_failure(self):
        mapping=self.root/'map.json';mapping.write_text(json.dumps({'hisseler':{
            'THYAO':{'siteler':['https://a.example']},'ASELS':{'siteler':['https://b.example']}}}))
        enqueue=Mock();clock=[1000]
        def fetch(url):
            if url.endswith('/robots.txt'):return 'User-agent: *\nAllow: /'
            return '<article><a href="/news/item-1">Yeni yatırım sözleşmesi duyurusu</a></article>'
        monitor=SirketSiteMotoru(self.root,enqueue,mapping,fetch,batch_size=1,
                                public_path=self.root/'public/news.json',analyzer=Mock(return_value={}),clock=lambda:clock[0])
        monitor.tek_tur();monitor.tek_tur();enqueue.assert_not_called()
        clock[0]+=1000
        def changed(url):
            if url.endswith('/robots.txt'):return 'User-agent: *\nAllow: /'
            return '<article><a href="/news/item-2">Yeni yatırım sözleşmesi duyurusu</a></article>'
        monitor.fetch=changed
        self.assertEqual(monitor.tek_tur(),1);enqueue.assert_called_once()
        monitor.fetch=Mock(side_effect=OSError());monitor.tek_tur()
        state=json.loads(monitor.path.read_text());self.assertIn('error',state['sites']['THYAO'])
        self.assertFalse((self.root/'webapp/data').exists())



if __name__=='__main__':unittest.main()
