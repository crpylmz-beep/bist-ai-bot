import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import datetime
import threading
import urllib.request

from cloud_bootstrap import bootstrap_public, PUBLIC_SEEDS
from veri_yollari import DataPaths
from ana_motor_gorevleri import WorkerTasks
from ana_motor import AnaMotor, ISTANBUL
from web_server import create_server


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.location=DataPaths({'BIST_DATA_DIR':str(self.root/'volume')},self.root/'repo')
        self.seed=self.root/'seed';self.seed.mkdir()
        self.stock={'sembol':'THYAO','fiyat':300,'sinyal':'AGRESIF_ALIS','karar':'AL'}
        self.daily={'hisseler':[self.stock],'bist100':{'fiyat':12000},'updated_at':'2026-10-05T17:00:00+03:00'}
        (self.seed/'bist_data.json').write_text(json.dumps(self.daily))
        (self.seed/'gun_ici_top10.json').write_text(json.dumps({'top10':[self.stock],'updated_at':self.daily['updated_at']}))
        (self.seed/'gun_ici_tum.json').write_text(json.dumps({'hisseler':[self.stock]}))
        (self.seed/'yarin_top10.json').write_text(json.dumps({'top10':[self.stock],'analiz_tarihi':'2026-10-05'}))

    def test_empty_volume_uses_historical_seed_without_fresh_timestamp(self):
        bootstrap_public(self.location,self.seed)
        for name in PUBLIC_SEEDS:self.assertTrue((self.location.public/name).exists())
        self.assertEqual(json.loads((self.location.public/'bist_data.json').read_text()),self.daily)
        self.assertTrue((self.location.archives/'2026-10-05.json').exists())
        self.assertFalse(list(self.location.users.glob('*.json')))

    def test_existing_files_archives_private_and_runtime_never_overwritten(self):
        bootstrap_public(self.location,self.seed)
        paths=[self.location.public/'bist_data.json',self.location.archives/'2026-10-05.json',self.location.users/'fiyat_alarmlari.json',self.location.runtime/'oncelik_kuyrugu.json']
        paths[2].write_text('{"private":true}');paths[3].write_text('{"queue":true}')
        original=[p.read_bytes() for p in paths]
        self.assertEqual(bootstrap_public(self.location,self.seed)['created'],0)
        self.assertEqual([p.read_bytes() for p in paths],original)

    def test_latest_archive_selected_without_mutating_snapshot(self):
        self.location.ensure()
        archive=self.location.archives/'2026-10-06.json'
        archive.write_text(json.dumps({'analiz_tarihi':'2026-10-06','top10':[self.stock]}))
        frozen=archive.read_bytes()
        bootstrap_public(self.location,self.seed)
        self.assertEqual(json.loads((self.location.public/'yarin_top10.json').read_text())['analiz_tarihi'],'2026-10-06')
        self.assertEqual(archive.read_bytes(),frozen)

    def test_no_seed_creates_explicit_waiting_documents_without_prices(self):
        empty=self.root/'empty';empty.mkdir()
        bootstrap_public(self.location,empty)
        self.assertEqual(json.loads((self.location.public/'bist_data.json').read_text())['bootstrap_status'],'WAITING_FOR_PROVIDER')
        self.assertEqual(json.loads((self.location.public/'gun_ici_top10.json').read_text())['top10'],[])

    def test_invalid_seed_does_not_crash_or_copy_private_files(self):
        (self.seed/'bist_data.json').write_text('invalid')
        (self.seed/'push_subscriptions.json').write_text('{"secret":true}')
        bootstrap_public(self.location,self.seed)
        self.assertFalse((self.location.public/'push_subscriptions.json').exists())
        self.assertEqual(json.loads((self.location.public/'bist_data.json').read_text())['hisseler'],[])

    def test_bootstrap_adapter_uses_one_existing_batch_then_records_completion(self):
        self.location.ensure()
        adapter=WorkerTasks.__new__(WorkerTasks);adapter.directory=self.location.runtime
        adapter.full_scan=Mock(side_effect=[{'cycle_complete':False},{'cycle_complete':True}])
        adapter.bootstrap();self.assertFalse((adapter.directory/'public_bootstrap_complete.json').exists())
        adapter.bootstrap();self.assertTrue((adapter.directory/'public_bootstrap_complete.json').exists())
        self.assertEqual(adapter.full_scan.call_count,2)

    def test_closed_market_schedules_bootstrap_but_not_full_scan_or_intraday(self):
        current=datetime(2026,10,10,12,tzinfo=ISTANBUL)
        bootstrap,scan,intra=Mock(),Mock(),Mock()
        motor=AnaMotor({'bootstrap':bootstrap,'full_scan':scan,'intraday_top10':intra},directory=self.root/'runtime',clock=lambda:current)
        self.addCleanup(motor.shutdown)
        motor.tick();motor.tasks['bootstrap'].future.result(timeout=2)
        bootstrap.assert_called_once();scan.assert_not_called();intra.assert_not_called()

    def test_http_reads_volume_stock_api_and_vapid_config(self):
        bootstrap_public(self.location,self.seed)
        server=create_server(port=0,data_paths=self.location)
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base='http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(base+'/data/bist_data.json') as response:
            self.assertEqual(json.load(response)['bist100']['fiyat'],12000)
        with urllib.request.urlopen(base+'/api/stocks/THYAO') as response:
            self.assertEqual(json.load(response)['otomatik']['karar'],'AL')
        from vapid_uret import generate
        key=generate('test@example.com')['VAPID_PUBLIC_KEY']
        with patch.dict('os.environ',{'VAPID_PUBLIC_KEY':key,'VAPID_PRIVATE_KEY':'private','VAPID_SUBJECT':'mailto:test@example.com'}):
            with urllib.request.urlopen(base+'/api/push/config') as response:
                doc=json.load(response);self.assertEqual(doc['public_key'],key);self.assertTrue(doc['configured'])
                self.assertNotIn('private',json.dumps(doc))


if __name__=='__main__':unittest.main()
