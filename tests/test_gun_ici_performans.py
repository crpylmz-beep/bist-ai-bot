import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime,timedelta
from unittest.mock import Mock,patch

from ai_karar_motoru import ISTANBUL
from kullanici_kayitlari import atomic_json
from veri_yollari import DataPaths
from gun_ici_performans import GunIciPerformans,HORIZONS,BASE,outcome,features,bounded,apply_score,normalize_bars


class IntradayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'GUN_ICI_LEARNING_ENABLED':'false'}))
        self.current=datetime(2026,10,6,11,tzinfo=ISTANBUL)
        self.provider=Mock(return_value=[])
        self.engine=GunIciPerformans(self.location,clock=lambda:self.current,provider=self.provider)
        self.row={'sembol':'THYAO','fiyat':100,'gun_ici_puan':75,'gun_ici_karar':'AL',
            'gun_ici_alim_alt':99,'gun_ici_alim_ust':100,'gun_ici_kar_al':102,'gun_ici_stop':99,
            'veri_tarihi':(self.current-timedelta(minutes=5)).isoformat(),'seans_vwap':99,'hacim3_orani':180,
            'ema9_5':99,'ema21_5':98,'rsi5':55,'macd5':2,'signal5':1,'obv_degisim_15dk':1,
            'momentum15':1,'kirilim':True,'haber_puani':0,'makro_puani':0,'sektor_puani':0,
            'gun_ici_nihai_ai_puan':76,'gun_ici_guven':80,'makro_sektor':'ULASTIRMA'}

    def record(self,row=None):
        self.engine.record([row or self.row]);return self.engine.state()['kayitlar'][-1]

    def bars(self,start=None,count=12,high=101,low=99.5,close=100.5):
        start=start or datetime(2026,10,6,11,tzinfo=ISTANBUL)
        return [dict(timestamp=(start+timedelta(minutes=i*5)).isoformat(),open=100,high=high,low=low,close=close) for i in range(count)]

    def seed(self,count=40,days=5,duplicate=False,future=False,outlier=False):
        records=[]
        for yes in (True,False):
            for i in range(count):
                at=datetime(2026,9,7,11,tzinfo=ISTANBUL)+timedelta(days=i%days)
                analysis=dict(self.row,hacim3_orani=180 if yes else 80)
                observed=at+timedelta(hours=1) if not future else self.current+timedelta(days=1)
                records.append({'id':str(yes)+str(i),'sembol':'DUP' if duplicate else str(yes)+str(i),'sinyal_zamani':at.isoformat(),
                    'karar':'AL','skor':75,'analiz':analysis,'sonuclar':{'60':{'getiri_yuzde':10000 if outlier and i==0 else 2 if yes else -2,
                        'durum':'BASARILI' if yes else 'STOP','egitime_uygun':True,'tamamlandi':True,'observed_at':observed.isoformat(),
                        'sonuc_zamani':(at+timedelta(hours=1)).isoformat(),'ilk_temas':'HEDEF' if yes else 'STOP'}}})
        state={'kayitlar':records,'listeler':[]};atomic_json(self.engine.file,state);return state

    def test_new_signal_frozen_fields_and_timezone(self):
        r=self.record();self.assertEqual(r['giris_fiyati'],100);self.assertEqual(r['confidence'],80)
        self.assertEqual(r['durum'],'YENI_AL');self.assertTrue(r['sinyal_zamani'].endswith('+03:00'))
        self.assertEqual(r['analiz']['ema9_5'],99);self.assertEqual(r['sonuclar'],{})

    def test_duplicate_no_new_signal(self):
        first=self.record();self.current+=timedelta(minutes=5)
        self.assertEqual(self.engine.record([dict(self.row,veri_tarihi=(self.current-timedelta(minutes=5)).isoformat())]),[])
        self.assertEqual(len(self.engine.state()['kayitlar']),1)
        self.assertEqual(self.engine.state()['kayitlar'][0]['analiz'],first['analiz'])

    def test_meaningful_price_change(self):
        self.record();self.current+=timedelta(minutes=5)
        self.assertEqual(len(self.engine.record([dict(self.row,fiyat=102,veri_tarihi=(self.current-timedelta(minutes=5)).isoformat())])),1)

    def test_same_candle_cannot_duplicate_changed_score(self):
        self.record();self.assertEqual(self.engine.record([dict(self.row,gun_ici_puan=90)]),[])

    def test_decision_change_and_state(self):
        self.record();self.current+=timedelta(minutes=5)
        self.engine.record([dict(self.row,gun_ici_karar='SAT',veri_tarihi=(self.current-timedelta(minutes=5)).isoformat())])
        self.assertEqual([r['durum'] for r in self.engine.state()['kayitlar']],['SAT_DONDU','SAT_DONDU'])

    def test_weakening_state(self):
        self.record();self.current+=timedelta(minutes=5)
        self.engine.record([],rows=[dict(self.row,gun_ici_karar='IZLE')])
        self.assertEqual(self.engine.state()['kayitlar'][0]['durum'],'ZAYIFLIYOR')

    def test_target_first_then_stop(self):
        r=self.record();bars=self.bars();bars[0]['high']=103;bars[1]['low']=98
        result=outcome(r,bars,60,self.current+timedelta(hours=1))
        self.assertEqual(result['ilk_temas'],'HEDEF');self.assertEqual(result['durum'],'BASARILI')
        self.assertTrue(result['stop_temasi']);self.assertTrue(result['hedef_temasi'])

    def test_stop_first_then_target(self):
        r=self.record();bars=self.bars();bars[0]['low']=98;bars[1]['high']=103
        result=outcome(r,bars,60,self.current+timedelta(hours=1))
        self.assertEqual(result['ilk_temas'],'STOP');self.assertEqual(result['durum'],'STOP')

    def test_same_bar_ambiguous(self):
        result=outcome(self.record(),self.bars(high=103,low=98),60,self.current+timedelta(hours=1))
        self.assertEqual(result['ilk_temas'],'BELIRSIZ');self.assertFalse(result['egitime_uygun'])

    def test_positive_close_not_full_success(self):
        result=outcome(self.record(),self.bars(close=100.1),60,self.current+timedelta(hours=1))
        self.assertEqual(result['durum'],'BASARISIZ');self.assertGreater(result['getiri_yuzde'],0)

    def test_sell_not_fake_short(self):
        r=self.record(dict(self.row,gun_ici_karar='SAT'))
        self.assertEqual(outcome(r,self.bars(),60,self.current+timedelta(hours=1))['durum'],'REFERANS')

    def test_session_end_and_terminal_state(self):
        self.current=self.current.replace(hour=17,minute=55);self.row['veri_tarihi']=(self.current-timedelta(minutes=5)).isoformat()
        r=self.record();self.provider.return_value=self.bars(start=self.current,count=3)
        self.current=self.current.replace(hour=18,minute=15);self.engine.one_round()
        stored=self.engine.state()['kayitlar'][0]
        self.assertTrue(stored['sonuclar']['SEANS']['tamamlandi']);self.assertEqual(stored['durum'],'SONLANDI')
        self.assertEqual(stored['sonuclar']['SEANS']['kullanim_suresi_dk'],15)

    def test_each_horizon(self):
        r=self.record()
        for minutes in (5,15,30,60):
            result=outcome(r,self.bars(),minutes,self.current+timedelta(hours=1))
            self.assertTrue(result['tamamlandi']);self.assertEqual(result['kullanim_suresi_dk'],minutes)

    def test_arbitrary_second_signal_uses_next_full_candle(self):
        self.current+=timedelta(seconds=13)
        r=self.record();bars=self.bars()
        result=outcome(r,bars,5,self.current+timedelta(minutes=10))
        self.assertTrue(result['tamamlandi'])
        self.assertEqual(result['sonuc_zamani'],'2026-10-06T11:10:00+03:00')
        self.assertAlmostEqual(result['kullanim_suresi_dk'],9+47/60)

    def test_missing_bar_does_not_slide(self):
        r=self.record();self.assertFalse(outcome(r,self.bars()[1:],15,self.current+timedelta(hours=1))['tamamlandi'])

    def test_future_and_incomplete_bars_rejected(self):
        data=self.bars(count=2);data[0]['complete']=False
        self.assertEqual(normalize_bars(data,self.current+timedelta(minutes=7)),[])

    def test_pre_signal_high_not_credited(self):
        r=self.record();bars=self.bars(start=self.current-timedelta(minutes=5),count=13);bars[0]['high']=150
        result=outcome(r,bars,60,self.current+timedelta(hours=1));self.assertFalse(result['hedef_temasi'])

    def test_signal_no_future_or_stale_source(self):
        self.assertEqual(self.engine.record([dict(self.row,veri_tarihi=self.current.isoformat())]),[])
        self.assertEqual(self.engine.record([dict(self.row,veri_tarihi=(self.current-timedelta(hours=1)).isoformat())]),[])

    def test_provider_once_for_same_symbol(self):
        self.record();self.current+=timedelta(minutes=5)
        self.engine.record([dict(self.row,fiyat=101.1,veri_tarihi=(self.current-timedelta(minutes=5)).isoformat())])
        self.current+=timedelta(minutes=65);self.provider.return_value=self.bars(count=14)
        self.engine.one_round();self.provider.assert_called_once_with('THYAO')

    def test_cache_avoids_provider_and_immutable_result(self):
        self.record();self.current+=timedelta(hours=1);self.engine.cache_bars({'THYAO':self.bars()})
        self.engine.one_round();before=copy.deepcopy(self.engine.state()['kayitlar'][0]['sonuclar'])
        self.engine.one_round();self.provider.assert_not_called();self.assertEqual(self.engine.state()['kayitlar'][0]['sonuclar'],before)

    def test_provider_failure_other_symbol_continues(self):
        self.engine.record([self.row,dict(self.row,sembol='ASELS')]);self.current+=timedelta(hours=1)
        self.provider.side_effect=lambda s:(_ for _ in ()).throw(ValueError('fake')) if s=='THYAO' else self.bars()
        result=self.engine.one_round();self.assertEqual(result['guncellenen_sinyal'],1);self.assertIn('THYAO',result['hatalar'])

    def test_batch_limit(self):
        self.engine.record([dict(self.row,sembol=str(i)) for i in range(20)]);self.current+=timedelta(hours=1)
        with patch.dict(os.environ,{'GUN_ICI_PERFORMANCE_BATCH_SIZE':'2'}):self.engine.one_round()
        self.assertEqual(self.provider.call_count,2)

    def test_learning_disabled_preserves_raw_and_computes_shadow(self):
        state=self.seed();self.engine.publish_and_learn(state,self.current)
        row=dict(self.row);top=self.engine.rank([row]);self.assertEqual(top[0]['gun_ici_final_puan'],75)
        self.assertGreater(row['gun_ici_shadow_puan'],75);self.assertEqual(row['gun_ici_kalibrasyon_duzeltmesi'],0)

    def test_enabled_bounded_and_not_shared_flag(self):
        state=self.seed();self.engine.publish_and_learn(state,self.current)
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):self.assertEqual(self.engine.rank([dict(self.row)])[0]['gun_ici_final_puan'],75)
        with patch.dict(os.environ,{'GUN_ICI_LEARNING_ENABLED':'true'}):
            result=self.engine.rank([dict(self.row)])[0];self.assertGreater(result['gun_ici_final_puan'],75);self.assertLessEqual(result['gun_ici_final_puan'],78)

    def test_minimum_forty(self):
        self.engine.publish_and_learn(self.seed(count=39),self.current);self.assertEqual(self.engine.model()['approved'],{})

    def test_five_independent_days(self):
        self.engine.publish_and_learn(self.seed(days=4),self.current);self.assertEqual(self.engine.model()['approved'],{})

    def test_no_confident_performance_difference_no_change(self):
        state=self.seed()
        for r in state['kayitlar']:
            r['sonuclar']['60'].update(durum='BASARILI',getiri_yuzde=2)
        self.engine.publish_and_learn(state,self.current)
        self.assertEqual(self.engine.model()['approved'],{})

    def test_repeated_stock_day_not_inflate(self):
        self.engine.publish_and_learn(self.seed(duplicate=True),self.current);self.assertEqual(self.engine.model()['approved'],{})
        report=json.loads((self.location.public/'gun_ici_performans.json').read_text())
        self.assertLessEqual(report['kriterler']['kriterler']['HACIM']['varken']['ornek'],5)

    def test_outlier_robust(self):
        self.engine.publish_and_learn(self.seed(outlier=True),self.current)
        entry=self.engine.model()['approved']['HACIM']['varken'];self.assertEqual(entry['medyan'],2);self.assertEqual(entry['trimmed_ortalama'],2)

    def test_future_results_no_learning(self):
        self.engine.publish_and_learn(self.seed(future=True),self.current);self.assertEqual(self.engine.model()['approved'],{})

    def test_missing_first_signal_does_not_select_later_winner(self):
        state=self.seed()
        first=state['kayitlar'][0]
        later=copy.deepcopy(first);later['id']='later';later['sinyal_zamani']=(datetime.fromisoformat(first['sinyal_zamani'])+timedelta(minutes=5)).isoformat()
        first['sonuclar']={};state['kayitlar'].append(later)
        self.engine.publish_and_learn(state,self.current)
        report=json.loads((self.location.public/'gun_ici_performans.json').read_text())
        self.assertEqual(report['kriterler']['kriterler']['HACIM']['varken']['ornek'],39)
        self.assertEqual(self.engine.model()['approved'],{})

    def test_shadow_prospective_performance_is_separate(self):
        rows=[dict(self.row,sembol=str(i),gun_ici_puan=90-i,gun_ici_shadow_puan=90-i) for i in range(10)]
        extra=dict(self.row,sembol='EXTRA',gun_ici_puan=79,gun_ici_shadow_puan=95)
        self.engine.record(rows,rows+[extra]);self.current+=timedelta(hours=1)
        self.provider.side_effect=lambda s:self.bars(high=106,close=105) if s=='EXTRA' else self.bars()
        with patch.dict(os.environ,{'GUN_ICI_PERFORMANCE_BATCH_SIZE':'25'}):self.engine.one_round()
        report=json.loads((self.location.public/'gun_ici_performans.json').read_text())
        pair=report['shadow_karsilastirmasi'][0]
        self.assertGreater(pair['shadow']['ortalama'],pair['mevcut']['ortalama'])
        self.assertGreater(pair['shadow']['top3']['ortalama'],pair['mevcut']['top3']['ortalama'])

    def test_learning_never_overrides_eligibility_or_negative_event(self):
        model={'weights':dict(BASE,HACIM=BASE['HACIM']+.1),'approved':{'HACIM':{}},'asof':self.current.isoformat()}
        with patch.dict(os.environ,{'GUN_ICI_LEARNING_ENABLED':'true'}):
            self.assertEqual(apply_score(dict(self.row,gun_ici_puan=44),model,self.current)['gun_ici_final_puan'],44)
            self.assertEqual(apply_score(dict(self.row,haber_puani=-5),model,self.current)['gun_ici_final_puan'],75)
            result=apply_score(self.row,model,self.current)
            self.assertLessEqual(result['gun_ici_kalibrasyon_duzeltmesi'],3)

    def test_future_model_not_applied(self):
        model={'weights':dict(BASE,HACIM=BASE['HACIM']+.01),'approved':{'HACIM':{}},'asof':(self.current+timedelta(days=1)).isoformat()}
        with patch.dict(os.environ,{'GUN_ICI_LEARNING_ENABLED':'true'}):self.assertEqual(apply_score(self.row,model,self.current)['gun_ici_final_puan'],75)

    def test_daily_limit_minmax_and_once(self):
        self.engine.publish_and_learn(self.seed(),self.current);before=self.engine.weights_file.read_bytes()
        self.engine.publish_and_learn(self.seed(),self.current);self.assertEqual(self.engine.weights_file.read_bytes(),before)
        weights=BASE
        for _ in range(100):
            prior=weights;weights=bounded(dict(weights,HACIM=weights['HACIM']+1),weights)
            self.assertAlmostEqual(sum(weights.values()),1,places=10)
            for k in BASE:
                self.assertLessEqual(abs(weights[k]-prior[k]),.005000001)
                self.assertTrue(BASE[k]*.5-1e-10<=weights[k]<=BASE[k]*1.5+1e-10)

    def test_unknown_indicators_not_fabricated(self):
        self.assertIsNone(features(self.row)['BOLLINGER']);self.assertIsNone(features(self.row)['REJIM'])
        self.assertTrue(all(v is None for v in features({}).values()))

    def test_daily_metrics_and_top_groups(self):
        self.engine.publish_and_learn(self.seed(),self.current)
        report=json.loads((self.location.public/'gun_ici_performans.json').read_text())
        day=next(iter(report['gunler'].values()))
        for name in ('pozitif_aday','hedef','stop','medyan','top3','top5','top10','en_iyi','en_kotu','skor_getiri_korelasyonu'):self.assertIn(name,day)
        self.assertEqual(day['top3']['ornek'],3)

    def test_tomorrow_files_byte_unchanged(self):
        files=[self.location.archives/'2026-10-06.json',self.location.runtime/'yarin_kalibrasyon.json',self.location.runtime/'ai_ogrenme_gecmisi.json']
        for file in files:file.write_bytes(b'{"sentinel":true}')
        self.record();self.current+=timedelta(hours=1);self.provider.return_value=self.bars();self.engine.one_round()
        for file in files:self.assertEqual(file.read_bytes(),b'{"sentinel":true}')
        self.assertFalse((self.location.public/'gun_ici_sonuclar.json').exists())

    def test_shadow_can_choose_outside_primary(self):
        rows=[dict(self.row,sembol=str(i),gun_ici_puan=90-i,gun_ici_shadow_puan=90-i) for i in range(10)]
        extra=dict(self.row,sembol='EXTRA',gun_ici_puan=79,gun_ici_shadow_puan=95)
        self.engine.record(rows,rows+[extra]);state=self.engine.state();byid={r['id']:r for r in state['kayitlar']}
        self.assertEqual(byid[state['listeler'][0]['shadow'][0]]['sembol'],'EXTRA')
        self.assertNotIn('EXTRA',[byid[i]['sembol'] for i in state['listeler'][0]['uyeler']])

    def test_worker_task_independent_callback(self):
        from ana_motor_gorevleri import WorkerTasks
        with patch('gun_ici_performans.bekleyen_gun_ici_sonuclari_guncelle',return_value={'ok':True}) as callback, \
             patch('gun_ici_performans.GunIciPerformans.signal_round',return_value={}) as signal_callback:
            self.assertEqual(WorkerTasks.intraday_performance(None),{'ok':True});callback.assert_called_once_with()
            signal_callback.assert_called_once_with()

    def test_real_scan_wires_capture_and_atomic_web_output(self):
        import bist_bot as bot
        stubs={'bist_hisseleri_getir':['THYAO'],'gun_ici_gecersiz_oku':set(),
            'gun_ici_stream_verileri_getir':({},['THYAO']),
            'gun_ici_analiz_hesapla':dict(self.row),'yarin_top10_snapshot_oku':None}
        for name,value in stubs.items():self.enterContext(patch.object(bot,name,return_value=value))
        self.enterContext(patch.object(bot,'gun_ici_sinyal_durumlarini_guncelle',side_effect=lambda rows:rows))
        for name in ('ai_sinyal_sonuc_guncelle','ai_ogrenme_kaydet','ai_ogrenme_ozeti_yaz','ai_ogrenilmis_agirliklari_hesapla','gun_ici_gecersiz_yaz'):
            self.enterContext(patch.object(bot,name))
        self.enterContext(patch('gun_ici_performans.GunIciPerformans',return_value=self.engine))
        top,_,_=bot.gun_ici_top10_tara()
        self.assertEqual(top[0]['gun_ici_final_puan'],75)
        self.assertEqual(len(self.engine.state()['kayitlar']),1)
        exported=json.loads((self.location.public/'gun_ici_top10.json').read_text())
        self.assertEqual(exported['top10'][0]['gun_ici_ham_puan'],75)
        self.assertTrue(exported['updated_at'].endswith('+03:00'))

    def test_scheduler_does_not_block_alarm_when_performance_waits(self):
        from ana_motor import AnaMotor
        gate=threading.Event();self.addCleanup(gate.set)
        alarm=Mock();worker=AnaMotor({'intraday_performance':lambda:gate.wait(2),'alarm':alarm},directory=self.location.runtime,clock=lambda:self.current)
        try:
            worker.tick();worker.tasks['alarm'].future.result(timeout=1);alarm.assert_called_once()
        finally:gate.set();worker.shutdown()

    def test_public_http_and_private_isolation(self):
        from web_server import create_server
        self.engine.publish_and_learn(self.seed(),self.current)
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/data/gun_ici_performans.json') as response:
            self.assertEqual(json.load(response)['ana_vade_dk'],60)


if __name__=='__main__':unittest.main()
