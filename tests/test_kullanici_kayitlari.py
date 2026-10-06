import copy
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kullanici_kayitlari import UserRecords, RecordError, MANUAL_TYPES, AI_TYPES
from web_server import create_server


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.web = self.root / 'webapp'
        (self.web / 'data').mkdir(parents=True)
        self.row = {'sembol':'THYAO', 'karar_giris_alt':290.05, 'karar_giris_ust':292.25,
                    'karar_hedef':296.24, 'karar_stop':287.76, 'destek':280, 'direnc':300,
                    'yarin_kirilim':294, 'karar_rr':1.5, 'karar':'AL',
                    'nihai_ai_puan':80, 'guven_skoru':75}
        self.source = self.web / 'data' / 'bist_data.json'
        self.write_source()
        self.records = UserRecords(self.root / 'private', self.web)
        self.levels = {'manuel_al':289, 'manuel_sat':300, 'manuel_stop':284, 'manuel_hedef':305}

    def write_source(self):
        self.source.write_text(json.dumps({'hisseler':[self.row], 'updated_at':'2026-10-06T12:00:00+03:00'}))

    def ai_body(self, kind='AI_HEDEF'):
        a = self.records.automatic('THYAO')
        return {'kaynak':'AI', 'alarm_turu':kind, 'model':'GUNLUK', 'analiz_kimligi':a['analiz_kimligi']}

    def test_levels_survive_reload_and_keep_users_and_stocks_separate(self):
        before = self.source.read_bytes()
        first = self.records.save_levels('u1', 'THYAO', self.levels)
        self.records.save_levels('u1', 'EREGL', dict(self.levels, manuel_al=24))
        self.records.save_levels('u2', 'THYAO', dict(self.levels, manuel_al=100))
        reopened = UserRecords(self.root / 'private', self.web)
        self.assertEqual(reopened.levels('u1','THYAO')['manuel_al'],289)
        self.assertEqual(reopened.levels('u1','EREGL')['manuel_al'],24)
        self.assertEqual(reopened.levels('u2','THYAO')['manuel_al'],100)
        second = reopened.save_levels('u1','THYAO',dict(self.levels,manuel_al=290))
        self.assertEqual(first['created_at'],second['created_at'])
        self.assertTrue(second['updated_at'].endswith('+03:00'))
        self.assertEqual(self.source.read_bytes(),before)

    def test_missing_files_are_created_safely_and_auto_values_are_exact(self):
        self.assertIsNone(self.records.levels('u1','THYAO'))
        self.assertEqual(self.records.alarms('u1','THYAO'),[])
        self.assertTrue((self.root/'private'/'kullanici_seviyeleri.json').exists())
        self.assertTrue((self.root/'private'/'fiyat_alarmlari.json').exists())
        a=self.records.automatic('THYAO')
        self.assertEqual((a['alim_alt'],a['alim_ust'],a['hedef'],a['stop']),(290.05,292.25,296.24,287.76))
        self.assertEqual(a['nihai_ai_puan'],80)
        self.assertIsNone(self.records.automatic('NONE')['hedef'])

    def test_each_manual_alarm_type_and_explicit_direction(self):
        self.records.save_levels('u1','THYAO',self.levels)
        for kind,(operator,field) in MANUAL_TYPES.items():
            alarm,created=self.records.create_alarm('u1','THYAO',{'kaynak':'MANUEL','alarm_turu':kind,'hedef_fiyat':295})
            self.assertTrue(created)
            self.assertEqual(alarm['kaynak'],'MANUEL')
            self.assertEqual(alarm['operator'],operator)
            self.assertEqual(alarm['hedef_fiyat'],self.levels[field] if field else 295)
            self.assertIsNone(alarm['triggered_at'])
            self.assertTrue(alarm['created_at'].endswith('+03:00'))

    def test_ai_types_freeze_levels_and_later_analysis_does_not_rewrite(self):
        for kind,(operator,field) in AI_TYPES.items():
            body=self.ai_body(kind)
            alarm,_=self.records.create_alarm('u1','THYAO',dict(body,hedef_fiyat=1))
            self.assertEqual(alarm['kaynak'],'AI')
            self.assertEqual(alarm['operator'],operator)
            self.assertEqual(alarm['hedef_fiyat'],self.records.automatic('THYAO')[field])
            if kind=='AI_ALIM_BOLGESI':self.assertEqual(alarm['hedef_fiyat_ust'],292.25)
        original=copy.deepcopy(self.records.alarms('u1','THYAO'))
        self.row['karar_hedef']=999
        self.write_source()
        self.assertEqual(self.records.alarms('u1','THYAO'),original)
        with self.assertRaises(RecordError) as error:
            self.records.create_alarm('u1','THYAO',body)
        self.assertEqual(error.exception.status,409)

    def test_duplicate_requests_and_concurrency_create_one_alarm(self):
        body={'kaynak':'MANUEL','alarm_turu':'FIYAT_USTU','hedef_fiyat':300}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.records.create_alarm('u1','THYAO',body),range(4)))
        self.assertEqual(sum(created for _,created in results),1)
        self.assertEqual(len({a['id'] for a,_ in results}),1)
        self.assertEqual(len(self.records.alarms('u1','THYAO')),1)

    def test_deactivate_delete_and_ownership(self):
        alarm,_=self.records.create_alarm('u1','THYAO',{'kaynak':'MANUEL','alarm_turu':'FIYAT_ALTI','hedef_fiyat':280})
        with self.assertRaises(RecordError):self.records.change_alarm('u2',alarm['id'],delete=True)
        self.records.change_alarm('u1',alarm['id'])
        self.assertFalse(self.records.alarms('u1','THYAO')[0]['aktif'])
        self.records.change_alarm('u1',alarm['id'],delete=True)
        self.assertEqual(self.records.alarms('u1','THYAO'),[])

    def test_validation_and_corrupt_store_do_not_destroy_previous_values(self):
        self.records.save_levels('u1','THYAO',self.levels)
        for value in [-1,0,'bad',float('nan'),float('inf'),True]:
            with self.assertRaises(RecordError):self.records.save_levels('u1','THYAO',dict(self.levels,manuel_al=value))
        self.assertEqual(self.records.levels('u1','THYAO')['manuel_al'],289)
        with self.assertRaises(RecordError):self.records.save_levels('u1','THYAO',{'karar_hedef':500})
        self.records.save_levels('u1','THYAO',dict(self.levels,manuel_al=None))
        self.assertIsNone(self.records.levels('u1','THYAO')['manuel_al'])
        with self.assertRaises(RecordError):self.records.create_alarm('u1','THYAO',{'kaynak':'MANUEL','alarm_turu':'MANUEL_AL'})
        store=self.root/'private'/'kullanici_seviyeleri.json'
        store.write_text('{broken')
        with self.assertRaises(RecordError):self.records.save_levels('u1','THYAO',self.levels)
        self.assertEqual(store.read_text(),'{broken')
        self.assertFalse(list((self.root/'private').glob('.user-*.tmp')))

    def test_intraday_auto_reads_own_levels_without_changing_source(self):
        path=self.web/'data'/'gun_ici_tum.json'
        path.write_text(json.dumps({'hisseler':[{'sembol':'THYAO','gun_ici_alim_alt':10,
          'gun_ici_alim_ust':11,'gun_ici_kar_al':13,'gun_ici_stop':9,'gun_ici_rr':2}],
          'updated_at':'2026-10-06T12:00:00+03:00'}))
        before=path.read_bytes()
        a=self.records.automatic('THYAO','GUN_ICI')
        self.assertEqual(a['hedef'],13)
        self.assertEqual(self.records.automatic('THYAO')['hedef'],296.24)
        self.assertEqual(path.read_bytes(),before)

    def test_http_end_to_end_reload_cookie_isolation_and_private_files(self):
        server=create_server('127.0.0.1',0,self.records)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        jar=http.cookiejar.CookieJar()
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        def request(path,method='GET',body=None,headers=None,opener=client):
            payload=json.dumps(body).encode() if body is not None else None
            req=urllib.request.Request(base+path,data=payload,method=method,
                headers=headers or {'Content-Type':'application/json','X-Bist-Request':'1'})
            with opener.open(req) as r:return r.status,json.load(r)
        _,initial=request('/api/stocks/THYAO')
        self.assertIsNone(initial['manuel'])
        self.assertTrue(jar)
        request('/api/stocks/THYAO/levels','PUT',self.levels)
        reload_client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        _,loaded=request('/api/stocks/THYAO',opener=reload_client)
        self.assertEqual(loaded['manuel']['manuel_al'],289)
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        _,isolated=request('/api/stocks/THYAO',opener=other)
        self.assertIsNone(isolated['manuel'])
        body={'kaynak':'AI','alarm_turu':'AI_HEDEF','model':'GUNLUK',
              'analiz_kimligi':loaded['otomatik']['analiz_kimligi']}
        status,created=request('/api/stocks/THYAO/alarms','POST',body)
        self.assertEqual(status,201)
        status,duplicate=request('/api/stocks/THYAO/alarms','POST',body)
        self.assertEqual(status,200)
        self.assertEqual(created['alarm']['id'],duplicate['alarm']['id'])
        from fiyat_alarm_motoru import alarmlari_kontrol_et
        result=alarmlari_kontrol_et(self.records,lambda _:300)
        self.assertEqual(result['tetiklenen_alarm'],1)
        triggered=request('/api/stocks/THYAO')[1]['alarmlar'][0]
        self.assertEqual(triggered['status'],'TRIGGERED')
        self.assertEqual(triggered['triggered_price'],300)
        self.assertTrue(triggered['triggered_at'].endswith('+03:00'))
        request('/api/alarms/'+created['alarm']['id'],'PATCH',{'aktif':False})
        request('/api/alarms/'+created['alarm']['id'],'DELETE')
        self.assertEqual(request('/api/stocks/THYAO')[1]['alarmlar'],[])
        with self.assertRaises(urllib.error.HTTPError) as error:
            request('/api/stocks/THYAO/levels','PUT',self.levels,
                    headers={'Content-Type':'application/json','Origin':'https://other.example','X-Bist-Request':'1'})
        self.assertEqual(error.exception.code,403)
        for path in ['/data/kullanici_seviyeleri.json','/../.local/user-data/kullanici_seviyeleri.json']:
            with self.assertRaises(urllib.error.HTTPError):client.open(base+path)
        with client.open(base+'/') as response:
            self.assertEqual(response.status,200)
            self.assertIn(b'userLevelsSection', response.read())


if __name__=='__main__':unittest.main()
