import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from datetime import timedelta
from unittest.mock import patch, Mock

from ana_motor import health_snapshot, istanbul_now
from kullanici_kayitlari import atomic_json
from veri_yollari import DataPaths
from web_server import create_server
from cloud_baslat import supervise
from vapid_uret import generate


class CloudReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.location = DataPaths({'BIST_DATA_DIR':str(self.root/'volume')}, Path(__file__).resolve().parents[1])
        self.location.ensure()

    def heartbeat(self, seconds=0, **extra):
        atomic_json(self.location.runtime/'ana_motor_durum.json', {
            'motor_durumu':'RUNNING','updated_at':(istanbul_now()-timedelta(seconds=seconds)).isoformat(),
            'tasks':{'alarm':{'status':'OK','last_success':'time','endpoint':'secret'}}, **extra})

    def test_health_allowlist_and_age(self):
        for age, status in ((0,'AKTIF'),(45,'GECIKMIS'),(125,'DURMUS_OLABILIR')):
            self.heartbeat(age, secret='private', subscription={'auth':'secret'})
            result = health_snapshot(self.location.runtime)
            self.assertEqual(result['worker_status'],status)
            self.assertEqual(result['healthy'],age==0)
            self.assertNotIn('secret',json.dumps(result))

    def test_http_custom_volume_health_static_cache_pwa(self):
        self.heartbeat()
        server = create_server(port=0,data_paths=self.location)
        self.assertEqual(server.server_address[0],'0.0.0.0')
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base = 'http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(base+'/health') as response:
            result=json.load(response)
            self.assertTrue(result['ana_motor']['healthy'])
        for route in ('/','/service-worker.js','/manifest.webmanifest'):
            with urllib.request.urlopen(base+route) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                if route.endswith('.js'):self.assertEqual(response.headers['Service-Worker-Allowed'],'/')
        with patch.dict(os.environ, {'VAPID_PUBLIC_KEY':'','VAPID_PRIVATE_KEY':'','VAPID_SUBJECT':''}):
            with urllib.request.urlopen(base+'/api/push/config') as response:
                self.assertFalse(json.load(response)['configured'])

    def test_vapid_key_pair_and_no_private_files(self):
        from py_vapid import Vapid
        from cryptography.hazmat.primitives import serialization
        import base64
        before=list(self.root.rglob('*'))
        values=generate('user@example.com')
        vapid=Vapid.from_string(values['VAPID_PRIVATE_KEY'])
        public=vapid.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        self.assertEqual(base64.urlsafe_b64encode(public).rstrip(b'=').decode(),values['VAPID_PUBLIC_KEY'])
        self.assertEqual(list(self.root.rglob('*')),before)

    def test_web_restart_does_not_restart_worker(self):
        worker=Mock();worker.poll.return_value=None
        old_web=Mock();old_web.poll.return_value=1
        new_web=Mock();new_web.poll.return_value=None
        stop=Mock();stop.wait.side_effect=[False,True]
        with patch('cloud_baslat.stop_children') as cleanup:
            launch=Mock(side_effect=[worker,old_web,new_web])
            self.assertEqual(supervise(launch,stop),0)
        self.assertEqual([call.args[0] for call in launch.call_args_list],['ana_motor.py','web_server.py','web_server.py'])
        self.assertIs(cleanup.call_args.args[0]['worker'],worker)

    def test_worker_crash_causes_nonzero_exit_and_cleanup(self):
        worker=Mock();worker.poll.return_value=1
        web=Mock();web.poll.return_value=None
        stop=Mock();stop.wait.return_value=False
        with patch('cloud_baslat.stop_children') as cleanup:
            self.assertEqual(supervise(Mock(side_effect=[worker,web]),stop),1)
            cleanup.assert_called_once()

    def test_alarm_adapter_skips_provider_when_market_closed(self):
        from ana_motor_gorevleri import WorkerTasks
        with patch('ana_motor_gorevleri.market_open',return_value=False), patch('fiyat_alarm_motoru.alarmlari_kontrol_et') as provider:
            result=WorkerTasks.alarm(None)
            self.assertEqual(result['skipped'],'MARKET_CLOSED')
            provider.assert_not_called()

    def test_port_environment_at_import_without_bot_token(self):
        import subprocess,sys
        environment={**os.environ,'PORT':'18765','BIST_DATA_DIR':str(self.root/'other'),'PYTHONDONTWRITEBYTECODE':'1'}
        environment.pop('BOT_TOKEN',None)
        result=subprocess.run([sys.executable,'-c','import web_server; print(web_server.PORT)'],env=environment,capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'18765')


if __name__=='__main__':unittest.main()
