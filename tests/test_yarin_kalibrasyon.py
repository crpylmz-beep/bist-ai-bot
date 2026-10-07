import copy
import json
import os
import tempfile
import threading
import urllib.request
import urllib.error
import unittest
from datetime import datetime,timedelta
from unittest.mock import Mock,patch

from ai_karar_motoru import ISTANBUL
from kullanici_kayitlari import atomic_json
from veri_yollari import DataPaths
from performans_motoru import PerformansMotoru,sessions_after
from yarin_kalibrasyon import YarinKalibrasyon,BASE,bounded,score,features,evidence


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'LEARNING_ENABLED':'false','MIN_LEARNING_SAMPLES':'40'}))
        self.current=datetime(2026,10,6,19,tzinfo=ISTANBUL)
        self.engine=YarinKalibrasyon(self.location,clock=lambda:self.current)
        self.row={'sembol':'XYZ','rsi':55,'fiyat':100,'sma20':95,'sma50':90,'macd':2,'signal':1,'hist':1,
            'hacim_orani':180,'degisim':1,'direnc':112,'risk_getiri':2,'haber_puani':0,'makro_puani':0,'sektor_puani':0,
            'makro_sektor':'TEKNOLOJI','piyasa_rejimi':'POZITIF','yarin_alim_alt':99,'yarin_alim_ust':100,'yarin_kar_al':110,'yarin_stop':95}

    def seed(self,count=40,days=None,future=False,sector='TEKNOLOJI'):
        rows=[];dates=sessions_after(datetime(2026,6,1).date(),max(count,1))
        for present in (True,False):
            for i in range(count):
                at=dates[i if days is None else i%days]
                observed=self.current+timedelta(days=1) if future else datetime.combine(at,datetime.min.time(),ISTANBUL)+timedelta(hours=19)
                rows.append({'kayit_id':str(present)+str(i),'model':'YARIN_TOP10','zaman':(observed-timedelta(days=1)).isoformat(),
                    'snapshot_tarihi':str(at),'sembol':'S'+str(i),'sektor':sector,'piyasa_rejimi':'POZITIF','egitim_durumu':'EGITIM',
                    'kriterler':dict(self.row,hacim_orani=180 if present else 80),
                    'sonuc_1g':{'durum':'BASARILI' if present else 'BASARISIZ','degerlendirme_tamamlandi':True,
                        'getiri_yuzde':2 if present else -2,'tarih':at.isoformat(),'observed_at':observed.isoformat()},
                    **{'sonuc_'+str(h)+'g':{'durum':'VERI_YETERSIZ','degerlendirme_tamamlandi':True} for h in (2,3,5,10,20,60)}})
        atomic_json(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':rows});return rows

    def test_learning_disabled_raw_score_and_ranking_unchanged(self):
        import bist_bot
        self.seed();self.engine.refresh()
        rows=[dict(self.row,sembol='A',test_raw=81),dict(self.row,sembol='B',test_raw=80)]
        with patch.object(bist_bot,'yarin_potansiyel_hesapla',side_effect=lambda row:row['test_raw']):
            ranked=bist_bot.yarin_top10_listesi(rows,kalibrasyon=self.engine.context())
        self.assertEqual([row['sembol'] for _,row in ranked],['A','B'])
        self.assertEqual([v for v,_ in ranked],[81,80]);self.assertEqual(rows[0]['kalibrasyon_duzeltmesi'],0)

    def test_shadow_computed_without_activation(self):
        self.seed();model=self.engine.refresh();result=score(self.row,80,model)
        self.assertEqual(result['final_puan'],80);self.assertGreater(result['shadow_puan'],80)
        self.assertFalse(result['learning_enabled']);self.assertEqual(result['calibration_version'],'BASE')

    def test_config_cannot_lower_calibration_below_forty_samples(self):
        self.seed(count=39)
        with patch.dict(os.environ,{'MIN_LEARNING_SAMPLES':'30','LEARNING_ENABLED':'true'}):
            model=self.engine.refresh()
        for key in BASE:self.assertAlmostEqual(model['active']['general'][key],BASE[key],places=11)
        self.assertEqual(model['shadow']['approved'],{})

    def test_enabled_small_explainable_effect(self):
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            model=self.engine.refresh();result=score(self.row,80,model)
        self.assertGreater(result['final_puan'],80);self.assertLessEqual(result['final_puan']-80,3)
        self.assertGreater(result['kalibrasyon_katkilari']['HACIM'],0)

    def test_minimum_40_per_group(self):
        self.seed(39);model=self.engine.refresh()
        self.assertEqual(score(self.row,80,model)['shadow_puan'],80)
        self.assertNotIn('HACIM',model['shadow']['approved'])

    def test_five_distinct_sessions_required(self):
        self.seed(days=4);model=self.engine.refresh()
        self.assertEqual(score(self.row,80,model)['shadow_puan'],80)

    def test_low_confidence_no_approval(self):
        records=self.seed()
        for r in records:r['sonuc_1g']['durum']='BASARILI';r['sonuc_1g']['getiri_yuzde']=1
        atomic_json(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':records})
        model=self.engine.refresh();self.assertFalse(model['shadow']['approved'])

    def test_daily_005_limit_repeated_refresh(self):
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            for _ in range(10):model=self.engine.refresh(force=True)
        for variant in ('active','shadow'):
            for key,v in model[variant]['general'].items():self.assertLessEqual(abs(v-BASE[key]),.005000001)

    def test_weight_min_max_and_normalization(self):
        current=dict(BASE)
        for _ in range(100):current=bounded({k:1 if k=='HACIM' else 0 for k in BASE},current)
        self.assertAlmostEqual(sum(current.values()),1)
        for key,val in current.items():self.assertGreaterEqual(val,BASE[key]*.5-1e-9);self.assertLessEqual(val,BASE[key]*1.5+1e-9)

    def test_score_effect_limit(self):
        weights=dict(BASE);weights['HACIM']+=.04;weights['RSI']+=.04
        active={'general':weights,'approved':{'HACIM':{},'RSI':{}}}
        result=score(self.row,80,{'active':active,'shadow':active,'learning_enabled':True})
        self.assertEqual(result['final_puan'],83)

    def test_sector_and_regime_fallback(self):
        self.seed();model=self.engine.refresh()
        self.assertIn('TEKNOLOJI',model['shadow']['sectors']);self.assertIn('POZITIF',model['shadow']['regimes'])
        unseen=dict(self.row,makro_sektor='BILINMEYEN',piyasa_rejimi='NEGATIF')
        plain=copy.deepcopy(model);plain['shadow']['sectors']={};plain['shadow']['regimes']={}
        self.assertEqual(score(unseen,80,model)['shadow_puan'],score(unseen,80,plain)['shadow_puan'])

    def test_versions_and_rollback_next_day(self):
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            first=self.engine.refresh();old=first['active_version']
            self.current+=timedelta(days=1);second=self.engine.refresh()
            self.assertNotEqual(old,second['active_version']);frozen=self.engine.freeze_day()
            self.engine.rollback(old);self.assertEqual(self.engine.freeze_day(),frozen)
            self.current+=timedelta(days=1);restored=self.engine.refresh()
        self.assertEqual(restored['active']['general'],first['active']['general'])
        self.assertTrue(self.engine.history.exists())
        with self.assertRaises(ValueError):self.engine.rollback('not-a-model')

    def test_same_day_frozen_even_env_change(self):
        self.seed();first=self.engine.freeze_day()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):
            self.engine.refresh(force=True);second=self.engine.freeze_day()
        self.assertEqual(first,second);self.assertFalse(second['learning_enabled'])

    def test_negative_event_safety_never_positive_bonus_or_levels_change(self):
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):model=self.engine.refresh()
        row=dict(self.row,haber_puani=-5,ai_yarin_hedef=110,ai_yarin_stop=95);before=copy.deepcopy(row)
        result=score(row,80,model);self.assertLessEqual(result['final_puan'],80);self.assertEqual(row,before)

    def test_excessive_rise_penalty_cannot_get_positive_bonus(self):
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):model=self.engine.refresh()
        self.assertLessEqual(score(dict(self.row,degisim=5),80,model)['final_puan'],80)

    def test_hard_rejection_cannot_be_revived(self):
        import bist_bot
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):model=self.engine.refresh()
        bad=dict(self.row,degisim=-4)
        self.assertEqual(bist_bot.yarin_potansiyel_hesapla(bad),-999)
        self.assertEqual(score(bad,-999,model)['final_puan'],-999)
        self.assertEqual(bist_bot.yarin_top10_listesi([bad],kalibrasyon=model),[])

    def test_outlier_not_enough_to_approve(self):
        records=self.seed()
        for r in records:r['sonuc_1g']['durum']='BASARILI';r['sonuc_1g']['getiri_yuzde']=1
        records[0]['sonuc_1g']['getiri_yuzde']=1000
        atomic_json(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':records})
        self.assertFalse(self.engine.refresh()['shadow']['approved'])

    def test_future_results_not_used(self):
        self.seed(future=True);model=self.engine.refresh()
        self.assertEqual(model['shadow']['ornek'],0);self.assertEqual(score(self.row,80,model)['shadow_puan'],80)

    def test_future_version_not_read_for_earlier_prediction(self):
        self.seed();self.engine.refresh();self.current-=timedelta(days=1)
        context=self.engine.context();self.assertEqual(context['shadow_version'],'BASE')

    def test_backdated_refresh_does_not_inherit_future_weights(self):
        self.seed()
        for _ in range(4):self.engine.refresh(force=True);self.current+=timedelta(days=1)
        self.current=datetime(2026,10,5,19,tzinfo=ISTANBUL)
        model=self.engine.refresh(force=True)
        self.assertLess(abs(model['shadow']['general']['HACIM']-BASE['HACIM']),.003)

    def test_only_used_criteria_no_phantom_indicators(self):
        self.assertNotIn('OBV',BASE);self.assertNotIn('BOLLINGER',BASE);self.assertNotIn('PIYASA_REJIMI',BASE)
        flags=features({});self.assertTrue(all(v is None for v in flags.values()))

    def test_no_evidence_for_key_no_learned_bonus(self):
        variant={'general':dict(BASE,RSI=BASE['RSI']+.02),'approved':{}}
        self.assertEqual(score(self.row,80,{'shadow':variant,'learning_enabled':False})['shadow_puan'],80)

    def test_prospective_snapshot_shadow_and_immutable_archive(self):
        import bist_bot
        self.seed()
        clock=self.enterContext(patch.object(bist_bot,'datetime',wraps=datetime))
        clock.now.side_effect=lambda tz=None:self.current if tz else self.current.replace(tzinfo=None)
        self.enterContext(patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.location.public/'yarin_top10.json')))
        self.enterContext(patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.location.archives)))
        with patch.object(bist_bot,'yarin_potansiyel_hesapla',return_value=80):
            result=bist_bot.yarin_top10_kilitli_kaydet([dict(self.row)],1)
            self.assertIsNotNone(result);frozen=(self.location.archives/'2026-10-06.json').read_bytes()
            self.assertTrue(result['shadow_top10']);self.assertTrue(result['ham_top10'])
            prediction=result['top10'][0]['tahmin']
            for key in ('ham_puan','kalibrasyon_duzeltmesi','final_puan','calibration_version','shadow_version'):self.assertIn(key,prediction)
            self.assertEqual(prediction['ham_puan'],80)
            self.assertEqual(bist_bot.yarin_top10_kilitli_kaydet([dict(self.row,fiyat=999)],1),result)
        self.assertEqual(frozen,(self.location.archives/'2026-10-06.json').read_bytes())

    def test_shadow_can_select_candidate_outside_baseline_top10(self):
        import bist_bot
        self.seed()
        clock=self.enterContext(patch.object(bist_bot,'datetime',wraps=datetime))
        clock.now.side_effect=lambda tz=None:self.current if tz else self.current.replace(tzinfo=None)
        self.enterContext(patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.location.public/'yarin_top10.json')))
        self.enterContext(patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.location.archives)))
        rows=[dict(self.row,sembol='S'+str(i),test_raw=90) for i in range(9)]
        rows.extend([dict(self.row,sembol='RAW',hacim_orani=80,test_raw=80.1),dict(self.row,sembol='SHADOW',test_raw=80)])
        with patch.object(bist_bot,'yarin_potansiyel_hesapla',side_effect=lambda row:row['test_raw']):
            snapshot=bist_bot.yarin_top10_kilitli_kaydet(rows,11)
        self.assertEqual(snapshot['top10'][-1]['sembol'],'RAW')
        self.assertEqual(snapshot['ham_top10'][-1]['sembol'],'RAW')
        self.assertEqual(snapshot['shadow_top10'][-1]['sembol'],'SHADOW')

    def test_enabled_final_score_orders_candidates(self):
        import bist_bot
        self.seed()
        with patch.dict(os.environ,{'LEARNING_ENABLED':'true'}):model=self.engine.refresh()
        rows=[dict(self.row,sembol='RAW',hacim_orani=80,test_raw=80.1),dict(self.row,sembol='LEARNED',test_raw=80)]
        with patch.object(bist_bot,'yarin_potansiyel_hesapla',side_effect=lambda row:row['test_raw']):
            ranked=bist_bot.yarin_top10_listesi(rows,kalibrasyon=model)
        self.assertEqual(ranked[0][1]['sembol'],'LEARNED')

    def test_current_vs_shadow_performance_measured_separately(self):
        self.seed();model=self.engine.refresh()
        prediction={'fiyat':100,'hedef':110,'stop':95,'tahmin_zamani':self.current.isoformat()}
        atomic_json(self.location.archives/'2026-10-06.json',{'analiz_tarihi':'2026-10-06','top10':[],
            'ham_top10':[{'sembol':'RAW','tahmin':prediction}],
            'shadow_top10':[{'sembol':'SHADOW','tahmin':prediction}]})
        self.current+=timedelta(days=1)
        def prices(stock):
            value=102 if stock=='RAW' else 105
            return [{'timestamp':'2026-10-07','open':100,'high':106,'low':99,'close':value}]
        PerformansMotoru(self.location,clock=lambda:self.current,history_provider=prices).one_round()
        self.engine.refresh()
        report=json.loads((self.location.public/'kalibrasyon_durumu.json').read_text())
        self.assertEqual(report['mevcut_top10']['ortalama'],2);self.assertEqual(report['shadow_top10']['ortalama'],5)
        self.assertFalse(report['otomatik_aktivasyon']);self.assertEqual(os.environ['LEARNING_ENABLED'],'false')

    def test_worker_calibration_error_isolated(self):
        from ana_motor_gorevleri import WorkerTasks
        worker=WorkerTasks()
        try:
            with patch('performans_motoru.bekleyen_sonuclari_guncelle',return_value={'tamamlanan_vade':1}),patch.object(YarinKalibrasyon,'refresh',side_effect=RuntimeError('fake')):
                self.assertEqual(worker.performance()['kalibrasyon_hatasi'],'RuntimeError')
        finally:worker.close()

    def test_public_report_http_and_private_weights_not_exposed(self):
        from web_server import create_server
        self.seed();self.engine.refresh()
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(base+'/data/kalibrasyon_durumu.json') as response:
            report=json.load(response)
        self.assertFalse(report['learning_enabled'])
        self.assertIn('HACIM',report['onerilen_degisiklikler'])
        self.assertNotIn('versions',report)
        for route in ('/runtime/yarin_kalibrasyon.json','/data/yarin_agirlik_gecmisi.json'):
            with self.subTest(route=route),self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base+route)
            self.assertEqual(error.exception.code,404)


if __name__=='__main__':unittest.main()
