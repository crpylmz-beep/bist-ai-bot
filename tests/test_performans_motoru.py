import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor

from ai_karar_motoru import AIKararMotoru,ISTANBUL,DEFAULT_WEIGHTS
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json
from performans_motoru import (PerformansMotoru,outcome,sessions_after,summarize,daily_report,
                              criterion_report,weight_proposals,robust,minimum_samples)


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.current=datetime(2026,10,12,19,tzinfo=ISTANBUL)
        self.signal={'kayit_id':'one','model':'ORTAK_AI','sembol':'XYZ','zaman':'2026-10-06T18:15:00+03:00',
            'fiyat':100,'hedef':110,'stop':95,'karar':'AL','egitim_durumu':'EGITIM','confidence':80,'ai_score':80,
            'sektor':'TEKNOLOJI','piyasa_rejimi':'POZITIF','katkilar':{'teknik':20,'haber':1},'kriterler':{'rsi':55,'macd':2,'signal':1,'hacim_orani':180}}
        self.bars=[self.bar('2026-10-07',106,109,98),self.bar('2026-10-08',107,109,99),self.bar('2026-10-09',108,109,99)]

    def bar(self,date,close=106,high=109,low=98,open=100,**extra):
        return {'timestamp':date+'T18:15:00+03:00','open':open,'high':high,'low':low,'close':close,**extra}

    def result(self,bars=None,horizon=1,record=None):
        return outcome(record or self.signal,bars or self.bars,horizon,self.current)

    def engine(self,provider=None,**kwargs):
        return PerformansMotoru(self.location,clock=lambda:self.current,history_provider=provider or Mock(return_value=self.bars),**kwargs)

    def seed(self,records=None):
        atomic_json(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':records or [dict(self.signal)]})

    def read(self):return json.loads(self.location.runtime_file('ai_ogrenme_gecmisi.json').read_text())['kayitlar']

    def snapshot(self,count=10,day='2026-10-06'):
        rows=[]
        for i in range(count):
            rows.append({'sembol':'S'+str(i),'makro_sektor':'TEKNOLOJI','piyasa_rejimi':'POZITIF',
                'rsi':55,'hacim_orani':180,'tahmin':{'fiyat':100,'skor':90-i,'karar':'AL','alim_alt':99,'alim_ust':100,
                'hedef':110,'stop':95,'tahmin_zamani':day+'T18:15:00+03:00'}})
        path=self.location.archives/(day+'.json');atomic_json(path,{'analiz_tarihi':day,'top10':rows})
        return path

    def test_positive_multi_metric_success(self):
        result=self.result();self.assertEqual(result['getiri_yuzde'],6)
        self.assertEqual(result['durum'],'BASARILI');self.assertEqual(result['maksimum_yukselis'],9)
        self.assertEqual(result['maksimum_dusus'],-2)

    def test_positive_close_alone_not_success(self):
        result=self.result([self.bar('2026-10-07',101,102,99)])
        self.assertEqual(result['durum'],'BASARISIZ')
        partial=self.result([self.bar('2026-10-07',103,104,99)])
        self.assertEqual(partial['durum'],'KISMEN_BASARILI')

    def test_negative_result(self):
        result=self.result([self.bar('2026-10-07',97,101,96)])
        self.assertEqual(result['getiri_yuzde'],-3);self.assertEqual(result['durum'],'BASARISIZ')

    def test_target_touch(self):
        result=self.result([self.bar('2026-10-07',109,112,98)])
        self.assertTrue(result['hedefe_ulasti']);self.assertTrue(result['hedef_once']);self.assertEqual(result['durum'],'BASARILI')

    def test_stop_touch(self):
        result=self.result([self.bar('2026-10-07',96,103,94)])
        self.assertTrue(result['stop_oldu']);self.assertTrue(result['stop_once']);self.assertEqual(result['durum'],'STOP')

    def test_target_first_across_sessions(self):
        bars=[self.bar('2026-10-07',109,112,98),self.bar('2026-10-08',96,103,94),self.bar('2026-10-09',100,102,97)]
        result=self.result(bars,3);self.assertTrue(result['hedef_once']);self.assertFalse(result['stop_once']);self.assertEqual(result['durum'],'BASARILI')

    def test_stop_first_across_sessions(self):
        bars=[self.bar('2026-10-07',96,103,94),self.bar('2026-10-08',109,112,98),self.bar('2026-10-09',109,112,98)]
        result=self.result(bars,3);self.assertTrue(result['stop_once']);self.assertEqual(result['durum'],'STOP')

    def test_same_bar_both_contacts_order_unknown(self):
        result=self.result([self.bar('2026-10-07',102,112,94)])
        self.assertEqual(result['ilk_temas'],'BELIRSIZ');self.assertIsNone(result['hedef_once']);self.assertIsNone(result['stop_once'])
        self.assertEqual(result['durum'],'VERI_YETERSIZ');self.assertTrue(result['degerlendirme_tamamlandi'])

    def test_gap_open_resolves_first_contact(self):
        result=self.result([self.bar('2026-10-07',102,113,94,open=112)])
        self.assertEqual(result['ilk_temas'],'HEDEF')

    def test_weekend_next_session(self):
        signal=dict(self.signal,zaman='2026-10-09T18:15:00+03:00')
        result=self.result([self.bar('2026-10-12')],record=signal)
        self.assertEqual(result['tarih'],'2026-10-12')

    def test_holiday_injection(self):
        signal=dict(self.signal,zaman='2026-10-09T18:15:00+03:00')
        current=self.current+timedelta(days=1)
        result=outcome(signal,[self.bar('2026-10-13')],1,current,holiday=lambda d:d.isoformat()=='2026-10-12')
        self.assertEqual(result['tarih'],'2026-10-13')

    def test_missing_session_does_not_shift_horizon(self):
        result=self.result([self.bar('2026-10-08')]);self.assertEqual(result['durum'],'VERI_YETERSIZ')
        self.assertFalse(result['degerlendirme_tamamlandi']);self.assertIn('2026-10-07',result['eksik_gunler'])

    def test_invalid_ohlc_missing_fields_and_duplicate_conflict(self):
        for bars in ([self.bar('2026-10-07',106,99,105)],
                     [{'timestamp':'2026-10-07','close':105}],
                     [self.bar('2026-10-07'),self.bar('2026-10-07',107)]):
            with self.subTest(bars=bars):self.assertEqual(self.result(bars)['durum'],'VERI_YETERSIZ')

    def test_incomplete_today_and_future_not_used(self):
        current=datetime(2026,10,7,15,tzinfo=ISTANBUL)
        self.assertIsNone(outcome(self.signal,self.bars,1,current))
        result=self.result([self.bar('2026-10-07',complete=False)]);self.assertFalse(result['degerlendirme_tamamlandi'])

    def test_short_direction_and_levels(self):
        record=dict(self.signal,karar='SAT',hedef=90,stop=105)
        result=self.result([self.bar('2026-10-07',92,103,89)],record=record)
        self.assertEqual(result['yon_getirisi'],8);self.assertEqual(result['durum'],'BASARILI')

    def test_missing_reference_price(self):
        result=self.result(record=dict(self.signal,fiyat=0));self.assertEqual(result['neden'],'REFERANS_EKSIK')

    def test_completed_results_immutable_duplicate_round(self):
        self.seed();provider=Mock(return_value=self.bars);engine=self.engine(provider)
        first=engine.one_round();saved=json.loads(json.dumps(self.read()[0]['sonuc_1g']))
        self.assertEqual(first['tamamlanan_vade'],2)
        second=engine.one_round();self.assertEqual(second['tamamlanan_vade'],0)
        self.assertEqual(self.read()[0]['sonuc_1g'],saved);self.assertEqual(provider.call_count,1)

    def test_no_due_records_no_provider_requests(self):
        self.seed([dict(self.signal,zaman=self.current.isoformat())]);provider=Mock()
        result=self.engine(provider).one_round();self.assertEqual(result['kontrol_edilen'],0);provider.assert_not_called()

    def test_same_symbol_price_once_and_batch_limit(self):
        self.seed([dict(self.signal,kayit_id=str(i),sembol=s) for i,s in enumerate(['XYZ','XYZ','ABC'])])
        provider=Mock(return_value=self.bars);result=self.engine(provider,batch_size=1).one_round()
        self.assertEqual(result['sembol_sayisi'],1);provider.assert_called_once_with('XYZ')
        self.assertEqual(result['kontrol_edilen'],2)

    def test_provider_failure_other_symbol_continues(self):
        self.seed([dict(self.signal,kayit_id='a',sembol='BAD'),dict(self.signal,kayit_id='b',sembol='XYZ')])
        def provider(stock):
            if stock=='BAD':raise RuntimeError('fake')
            return self.bars
        result=self.engine(provider).one_round();self.assertIn('BAD',result['hatalar']);self.assertEqual(result['tamamlanan_vade'],2)

    def test_snapshot_bytes_unchanged_and_single_import(self):
        path=self.snapshot(1);before=path.read_bytes();engine=self.engine()
        engine.one_round();engine.one_round()
        self.assertEqual(before,path.read_bytes());self.assertEqual(len(self.read()),1)
        record=self.read()[0];self.assertEqual(record['model'],'YARIN_TOP10');self.assertTrue(record['snapshot_id'])
        self.assertTrue(engine.result_path.exists());self.assertEqual(record['alim_alt'],99)

    def test_top3_top5_top10_daily_and_ranking(self):
        self.snapshot()
        def provider(stock):
            value=109-int(stock[1:])
            return [self.bar('2026-10-07',value,109,98)]
        self.engine(provider).one_round()
        report=json.loads((self.location.public/'performans_gunluk.json').read_text())['gunler']['2026-10-06']
        self.assertAlmostEqual(report['top3']['ortalama'],8)
        self.assertAlmostEqual(report['top5']['ortalama'],7)
        self.assertAlmostEqual(report['top10']['ortalama'],4.5)
        self.assertAlmostEqual(report['skor_performans_korelasyonu'],1)
        self.assertEqual(report['en_iyi']['sembol'],'S0');self.assertEqual(report['degerlendirilen'],10)

    def test_partial_list_coverage_visible(self):
        rows=[dict(self.signal,model='YARIN_TOP10',tahmin_sirasi=i,tahmin_skoru=90-i) for i in range(1,11)]
        rows[0]['sonuc_1g']=self.result();report=daily_report(rows)
        self.assertFalse(report['tamamlandi']);self.assertEqual(report['beklenen_kayit'],10);self.assertEqual(report['degerlendirilen'],1)

    def test_sector_regime_and_cumulative_report(self):
        self.seed();self.engine().one_round()
        report=json.loads((self.location.public/'performans_ozeti.json').read_text())
        self.assertIn('TEKNOLOJI',report['sektorler']);self.assertIn('POZITIF',report['rejimler'])
        self.assertEqual(set(report['vadeler']),{'1','3','5','10','20','60'})

    def calibration_records(self,count=40):
        rows=[]
        for present in (True,False):
            for i in range(count):
                result=dict(self.result(),durum='BASARILI' if present else 'BASARISIZ',getiri_yuzde=2 if present else -2)
                rows.append(dict(self.signal,kayit_id=str(present)+str(i),zaman=(datetime(2026,1,1,tzinfo=ISTANBUL)+timedelta(days=i)).isoformat(),
                    kriterler={'hacim_orani':180 if present else 80},sonuc_1g=result))
        return rows

    def test_criterion_present_absent_sample_confidence(self):
        report=criterion_report(self.calibration_records());entry=report['kriterler']['HACIM']
        self.assertTrue(entry['yeterli_veri']);self.assertEqual(entry['varken']['ornek'],40)
        self.assertEqual(entry['onerilen_agirlik_yonu'],'ARTIR');self.assertGreater(entry['basari_farki'],0)

    def test_minimum_samples_and_unknown_not_absent(self):
        report=criterion_report(self.calibration_records(5));self.assertFalse(report['kriterler']['HACIM']['yeterli_veri'])
        self.assertEqual(report['kriterler']['HACIM']['onerilen_agirlik_yonu'],'SABIT')
        self.assertEqual(report['kriterler']['RSI']['bilinmeyen'],10)

    def test_weight_recommendations_do_not_apply_even_learning_enabled(self):
        ai=AIKararMotoru(self.location);current=ai.weights();before=ai.weight_path.read_bytes()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            proposal=weight_proposals(criterion_report(self.calibration_records()),current)
        self.assertTrue(proposal['nedenler']);self.assertFalse(proposal['otomatik_uygulandi'])
        self.assertEqual(before,ai.weight_path.read_bytes())
        self.assertAlmostEqual(sum(proposal['onerilen_agirliklar'].values()),1)
        for key,val in current.items():self.assertLessEqual(abs(proposal['onerilen_agirliklar'][key]-val),.005000001)

    def test_learning_disabled_still_measures_and_reports(self):
        ai=AIKararMotoru(self.location);ai.weights();before=ai.weight_path.read_bytes();self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'false'}):self.engine().one_round()
        self.assertEqual(before,ai.weight_path.read_bytes());self.assertTrue((self.location.public/'onerilen_agirliklar.json').exists())

    def test_active_learning_without_samples_rejected(self):
        ai=AIKararMotoru(self.location)
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            self.assertEqual(ai.update_weights(DEFAULT_WEIGHTS)['reason'],'MINIMUM_SAMPLES')

    def test_min_samples_config_bounds(self):
        with patch.dict(os.environ,{'MIN_LEARNING_SAMPLES':'60'}):self.assertEqual(minimum_samples(),60)
        with patch.dict(os.environ,{'MIN_LEARNING_SAMPLES':'5'}):
            with self.assertRaises(ValueError):minimum_samples()

    def test_outlier_guard(self):
        report=robust([1]*39+[100]);self.assertEqual(report['medyan'],1);self.assertEqual(report['trimmed_ortalama'],1)
        rows=self.calibration_records();rows[0]['sonuc_1g']['getiri_yuzde']=1000
        self.assertEqual(criterion_report(rows)['kriterler']['HACIM']['varken']['medyan'],2)

    def test_news_canonical_single_import_and_three_horizons(self):
        event={'canonical_id':'canonical','sembol':'XYZ','ilk_gorulme':self.signal['zaman'],'kaynak_etiketi':'KAP + ŞİRKET_SITE','analiz':{'etki_puani':5,'ilk_fiyat':100,'guven':80}}
        atomic_json(self.location.runtime/'haber_dedup.json',{'haberler':[event,event]})
        engine=self.engine();engine.one_round();engine.one_round()
        records=self.read();self.assertEqual(len(records),1);self.assertEqual(records[0]['model'],'HABER')
        self.assertIn('sonuc_5g',records[0]);self.assertNotIn('sonuc_60g',records[0])

    def test_macro_event_history_single_symbol_tracking(self):
        atomic_json(self.location.runtime_file('makro_ai_gecmisi.json'),{'olaylar':[{'event_id':'macro','updated_at':self.signal['zaman'],
            'hisseler':{'XYZ':{'referans_fiyat':100,'makro_puani':-5,'sektor':'TEKNOLOJI'}}}]})
        self.engine().one_round();records=self.read();self.assertEqual(records[0]['model'],'MAKRO')
        self.assertEqual(records[0]['karar'],'SAT');self.assertIn('sonuc_1g',records[0])

    def test_existing_macro_writer_freezes_fresh_reference_once(self):
        import makro_ai
        at=datetime.now(ISTANBUL).isoformat()
        atomic_json(self.location.public/'bist_data.json',{'hisseler':[{'sembol':'XYZ','fiyat':100,'canli_guncelleme':at}]})
        with patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name}), \
             patch.object(makro_ai,'CANLI_MAKRO_DOSYA',self.location.public/'makro_canli_etki.json'), \
             patch.object(makro_ai,'MAKRO_GECMIS',self.location.runtime_file('makro_ai_gecmisi.json')):
            makro_ai.canli_makro_etki_yaz({'baslik':'faiz','kategori':'FAIZ'},{'XYZ':{'makro_puani':-5}})
            atomic_json(self.location.public/'bist_data.json',{'hisseler':[{'sembol':'XYZ','fiyat':101,'canli_guncelleme':at}]})
            makro_ai.canli_makro_etki_yaz({'baslik':'faiz','kategori':'FAIZ'},{'XYZ':{'makro_puani':-5}})
        events=json.loads(self.location.runtime_file('makro_ai_gecmisi.json').read_text())['olaylar']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['hisseler']['XYZ']['referans_fiyat'],100)

    def test_reference_rows_not_used_for_calibration(self):
        rows=self.calibration_records()
        for row in rows:row['egitim_durumu']='REFERANS'
        report=criterion_report(rows);self.assertEqual(report['kriterler']['HACIM']['varken']['ornek'],0)

    def test_controlled_batches_progress_to_next_symbol(self):
        self.seed([dict(self.signal,kayit_id='a',sembol='XYZ'),dict(self.signal,kayit_id='b',sembol='ABC')])
        provider=Mock(return_value=self.bars);engine=self.engine(provider,batch_size=1)
        engine.one_round();engine.one_round()
        self.assertEqual([call.args[0] for call in provider.call_args_list],['XYZ','ABC'])

    def test_open_gap_stop_first(self):
        result=self.result([self.bar('2026-10-07',102,112,92,open=93)])
        self.assertEqual(result['ilk_temas'],'STOP')

    def test_parallel_rounds_idempotent(self):
        self.seed();provider=Mock(return_value=self.bars)
        with ThreadPoolExecutor(3) as pool:list(pool.map(lambda _:self.engine(provider).one_round(),range(3)))
        self.assertEqual(len(self.read()),1);self.assertEqual(provider.call_count,1)

    def test_http_public_reports_private_results_not_served(self):
        from web_server import create_server
        self.snapshot(1);self.engine().one_round()
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(base+'/data/performans_ozeti.json') as response:self.assertIn('yarin_top10',json.load(response))
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+'/data/yarin_top10_sonuclar.json')

    def test_worker_performance_failure_isolated(self):
        from ana_motor import AnaMotor
        good=Mock();bad=Mock(side_effect=RuntimeError('fake'))
        engine=AnaMotor({'performance':bad,'alarm':good},self.location.runtime,clock=lambda:self.current)
        try:
            engine.tick()
            for task in engine.tasks.values():
                if task.future:
                    try:task.future.result(timeout=2)
                    except RuntimeError:pass
            engine.tick();good.assert_called_once();self.assertEqual(engine.state['tasks']['performance']['status'],'ERROR')
        finally:engine.shutdown()

    def test_insufficient_price_no_provider_request(self):
        self.seed([dict(self.signal,fiyat=None)]);provider=Mock()
        self.engine(provider).one_round();provider.assert_not_called()
        self.assertEqual(self.read()[0]['sonuc_1g']['neden'],'REFERANS_EKSIK')

    def test_old_close_only_outcome_not_overwritten(self):
        legacy={'tarih':'2026-10-07','fiyat':101,'getiri_yuzde':1}
        self.seed([dict(self.signal,sonuc_1g=legacy)]);self.engine().one_round()
        self.assertEqual(self.read()[0]['sonuc_1g'],legacy)

    def test_common_history_does_not_count_ambiguous_risk_as_success(self):
        from ai_karar_motoru import history_context
        rows=[dict(self.signal,sonuc_5g=dict(self.result(),durum='VERI_YETERSIZ')) for _ in range(50)]
        effect,info=history_context(rows,self.signal,'POZITIF',self.current)
        self.assertEqual(effect,0);self.assertEqual(info['ornek'],0)

    def test_shared_contribution_report_handles_incomplete_outcome(self):
        self.seed([dict(self.signal,sonuc_5g={'durum':'VERI_YETERSIZ','degerlendirme_tamamlandi':False})])
        self.assertEqual(AIKararMotoru(self.location).contribution_performance()['haber']['ornek'],0)


if __name__=='__main__':unittest.main()
