import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import http.cookiejar
from pathlib import Path
from unittest.mock import patch

from veri_yollari import DataPaths, migrate
from web_server import create_server


class SharedDataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.volume=self.root/'volume'
        self.location=DataPaths({'BIST_DATA_DIR':str(self.volume)})
        self.location.ensure()

    def child(self,script):
        env=dict(os.environ)
        for key in ('BIST_DATA_DIR','BIST_RUNTIME_DIR','BIST_USER_DATA_DIR'):env.pop(key,None)
        env.update(BIST_DATA_DIR=str(self.volume),PYTHONDONTWRITEBYTECODE='1')
        return subprocess.check_output([sys.executable,'-c',script],env=env,text=True)

    def test_no_environment_keeps_all_legacy_paths(self):
        repo=self.root/'repo';local=DataPaths({},repo)
        self.assertEqual(local.public,repo/'webapp/data')
        self.assertEqual(local.users,repo/'.local/user-data')
        self.assertEqual(local.runtime,repo/'.local/runtime')
        self.assertEqual(local.archives,repo/'webapp/data/yarin_top10_arsiv')
        self.assertEqual(local.runtime_file('kap_son_gorulen.json'),repo/'kap_son_gorulen.json')
        self.assertEqual(local.runtime_file('ai_ogrenme_gecmisi.json'),repo/'webapp/data/ai_ogrenme_gecmisi.json')
        custom=DataPaths({'BIST_USER_DATA_DIR':str(self.root/'users'),'BIST_RUNTIME_DIR':str(self.root/'state')},repo)
        self.assertEqual(custom.users,self.root/'users');self.assertEqual(custom.runtime,self.root/'state')

    def test_all_active_modules_follow_shared_volume_in_fresh_process(self):
        script="""
import json
import bist_bot,canli_motor,kap_canli,makro_ai,makro_kaynak,haber_zeka,sektor_haritasi,sirket_site_haritasi
from fiyat_alarm_motoru import default_records
from ana_motor import runtime_dir
from veri_yollari import paths
r=default_records()
print(json.dumps({
'public':[str(bist_bot.DATA_FILE),str(bist_bot.YARIN_TOP10_FILE),str(bist_bot.YARIN_TOP10_CANLI_FILE),str(makro_ai.CANLI_MAKRO_DOSYA),str(makro_kaynak.DURUM_DOSYA),str(sektor_haritasi.DOSYA),str(sirket_site_haritasi.DOSYA),str(r.public_dir)],
'runtime':[str(bist_bot.TAHMIN_GECMISI_FILE),str(bist_bot.GUN_ICI_GECERSIZ_FILE),str(canli_motor.DURUM_DOSYA),str(kap_canli.DURUM_DOSYA),str(makro_kaynak.GORULEN_DOSYA),str(haber_zeka.HABER_FILE),str(makro_ai.MAKRO_GECMIS),str(runtime_dir())],
'archives':str(bist_bot.YARIN_TOP10_ARSIV_DIR),'users':str(r.data_dir)}))
"""
        result=json.loads(self.child(script))
        for category in ('public','runtime'):
            for value in result[category]:self.assertTrue(Path(value).is_relative_to(self.volume/category),value)
        self.assertEqual(Path(result['archives']),self.location.archives)
        self.assertEqual(Path(result['users']),self.location.users)

    def server(self):
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_web_and_worker_share_alarm_and_pending_event_cross_process(self):
        (self.location.public/'bist_data.json').write_text(json.dumps({'hisseler':[{'sembol':'THYAO'}]}))
        base=self.server();jar=http.cookiejar.CookieJar()
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        with client.open(base+'/api/stocks/THYAO') as response:json.load(response)
        body=json.dumps({'kaynak':'MANUEL','alarm_turu':'FIYAT_USTU','hedef_fiyat':300}).encode()
        headers={'Content-Type':'application/json','X-Bist-Request':'1'}
        with client.open(urllib.request.Request(base+'/api/stocks/THYAO/alarms',data=body,headers=headers)) as response:
            alarm=json.load(response)['alarm']
        result=json.loads(self.child("from fiyat_alarm_motoru import alarmlari_kontrol_et;import json;print(json.dumps(alarmlari_kontrol_et(fiyat_saglayici=lambda stock:300)))"))
        self.assertEqual(result['tetiklenen_alarm'],1)
        with client.open(base+'/api/stocks/THYAO') as response:result=json.load(response)
        self.assertEqual(result['alarmlar'][0]['id'],alarm['id']);self.assertEqual(result['alarmlar'][0]['status'],'TRIGGERED')
        stored=json.loads((self.location.users/'fiyat_alarmlari.json').read_text())
        self.assertEqual(len(stored['pending_notifications']),1)
        self.assertFalse((self.location.public/'fiyat_alarmlari.json').exists())

    def test_public_archive_routes_and_private_runtime_isolation(self):
        (self.location.public/'bist_data.json').write_text('{"volume":true}')
        archive=self.location.archives/'2026-10-06.json';archive.write_text('{"immutable":true}')
        private=self.location.users/'fiyat_alarmlari.json';private.write_text('{"secret":"private"}')
        runtime=self.location.runtime/'ana_motor_durum.json';runtime.write_text('{"internal":true}')
        (self.location.public/'leak.json').symlink_to(private)
        base=self.server()
        for route,field in (('/data/bist_data.json','volume'),('/data/yarin_top10_arsiv/2026-10-06.json','immutable')):
            with urllib.request.urlopen(base+route) as response:self.assertTrue(json.load(response)[field])
        for route in ('/data/fiyat_alarmlari.json','/data/push_subscriptions.json','/data/makro_gorulen.json',
                      '/data/leak.json','/data/../private/user-data/fiyat_alarmlari.json',
                      '/runtime/ana_motor_durum.json','/private/user-data/fiyat_alarmlari.json',
                      '/.local/runtime/ana_motor_durum.json','/data/%2e%2e/private/file.json','//data/fiyat_alarmlari.json'):
            with self.subTest(route=route),self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+route)
            self.assertEqual(error.exception.code,404)
        self.assertEqual(archive.read_text(),'{"immutable":true}')

    def test_offline_migration_is_atomic_repeatable_and_never_overwrites(self):
        repo=self.root/'legacy';local=DataPaths({},repo);local.ensure()
        for directory,name,value in ((local.public,'bist_data.json',b'{"old":1}'),(local.public,'makro_gorulen.json',b'{"seen":1}'),
                  (local.users,'push_subscriptions.json',b'{"user":"private"}'),(local.runtime,'ana_motor_durum.json',b'{"runtime":1}'),
                  (local.archives,'2026-10-06.json',b'{"frozen":1}')):
            (directory/name).write_bytes(value)
        (repo/'kap_son_gorulen.json').write_text('[]')
        (local.public/'fiyat_alarmlari.json').write_text('{"should_not_publish":true}')
        dest=DataPaths({'BIST_DATA_DIR':str(self.volume)},repo)
        self.assertEqual(migrate(dest),6)
        original=(dest.archives/'2026-10-06.json').read_bytes()
        (local.archives/'2026-10-06.json').write_text('{"changed":1}')
        self.assertEqual(migrate(dest),0)
        self.assertEqual((dest.archives/'2026-10-06.json').read_bytes(),original)
        self.assertTrue((local.users/'push_subscriptions.json').exists())
        self.assertTrue((dest.runtime/'makro_gorulen.json').exists())
        self.assertFalse((dest.public/'fiyat_alarmlari.json').exists())
        self.assertEqual((dest.users/'push_subscriptions.json').stat().st_mode & 0o777,0o600)

    def test_unsafe_roots_and_conflicting_overrides_are_rejected(self):
        repo=self.root/'repo';(repo/'webapp').mkdir(parents=True)
        for env in ({'BIST_DATA_DIR':str(repo/'webapp/data')},
                    {'BIST_DATA_DIR':'relative-volume'},
                    {'BIST_USER_DATA_DIR':str(repo/'webapp/private')},
                    {'BIST_DATA_DIR':str(self.volume),'BIST_RUNTIME_DIR':str(self.root/'other')}):
            with self.assertRaises(ValueError):DataPaths(env,repo)
        (self.volume/'public').rmdir();(self.volume/'public').symlink_to(self.volume/'runtime',target_is_directory=True)
        with self.assertRaises(ValueError):DataPaths({'BIST_DATA_DIR':str(self.volume)},repo)


if __name__=='__main__':unittest.main()
