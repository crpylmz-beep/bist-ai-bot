"""Final policy: provider-free, frozen inputs, safety above directional scores."""
import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime,timedelta
from unittest.mock import patch
from pathlib import Path
from ai_karar_motoru import (evaluate,attach_final_decision,AIKararMotoru,decision_view,
                            final_decision_report,DEFAULT_WEIGHTS,ISTANBUL,FINAL_MODEL)
from kullanici_kayitlari import atomic_json,UserRecords
from veri_yollari import DataPaths
from gun_ici_performans import GunIciPerformans
from performans_motoru import PerformansMotoru
import bist_bot as bot

class FinalDecisionTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,6,12,tzinfo=ISTANBUL)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.paths=DataPaths({'BIST_DATA_DIR':self.temp.name});self.paths.ensure()
        self.enterContext(patch.dict('os.environ',{'BIST_DATA_DIR':self.temp.name,'LEARNING_ENABLED':'false','GUN_ICI_LEARNING_ENABLED':'false'}))
    def row(self,technical=85,direction=1,mode='DAILY'):
        return {'sembol':'THYAO','teknik_puan':technical,'fiyat':100,'destek':90 if direction>=0 else 101,'direnc':110,
                'karar_stop':85,'karar_rr':2,'canli_guncelleme':self.now.isoformat(),'rsi':55,
                'macd':direction,'signal':0,'hist':direction,'hist_onceki':0,'hacim_orani':160,
                'sma20':98 if direction>=0 else 102,'sma50':96 if direction>=0 else 104,
                'piyasa_rejimi':direction,'degisim':direction,'obv_durum':'YUKSELEN' if direction>=0 else 'DUSEN',
                'karar_zaman_dilimi':mode}
    def final(self,row=None,**kwargs):return evaluate(row or self.row(),current=self.now,**kwargs)['nihai_karar']
    def doc(self,mode='INTRADAY',direction=1):
        return {'mode':mode,'asof':self.now.isoformat(),'data_time':self.now.isoformat(),'stale':False,'confidence':100,
                'vwap':{'status':'OK','confidence':100,'position':'VWAP_USTU' if direction>0 else 'VWAP_ALTI'},
                'obv':{'status':'OK','confidence':100,'trend':'OBV_YUKSELEN' if direction>0 else 'OBV_DUSEN'},
                'bollinger':{'status':'OK','confidence':100,'squeeze_volume_momentum_break':direction>0,'lower_break':direction<0},
                'momentum':{'status':'OK','confidence':100,'short_pct':direction,'state':'GUCLENIYOR' if direction>0 else 'ZAYIFLIYOR','last_candle':'POZITIF'}}
    def test_strong_buy(self):self.assertEqual(self.final(self.row(100))['karar'],'GUCLU_AL')
    def test_normal_buy(self):self.assertEqual(self.final()['karar'],'AL')
    def test_wait(self):self.assertEqual(self.final(self.row(50))['karar'],'BEKLE')
    def test_sell(self):self.assertEqual(self.final(self.row(20,-1))['karar'],'SAT')
    def test_strong_sell(self):self.assertEqual(self.final(self.row(0,-1))['karar'],'GUCLU_SAT')
    def test_score_and_confidence_are_independent(self):
        row=self.row(100);row['canli_guncelleme']=(self.now-timedelta(hours=1)).isoformat()
        result=self.final(row);self.assertGreater(result['karar_puani'],80);self.assertLess(result['confidence'],50);self.assertEqual(result['karar'],'BEKLE')
    def test_missing_time_and_missing_technical_are_wait(self):
        row=self.row();row.pop('canli_guncelleme');self.assertEqual(self.final(row)['karar'],'BEKLE')
        row=self.row();row.pop('teknik_puan');self.assertEqual(self.final(row)['karar'],'BEKLE')
    def test_mixed_signals(self):
        row=self.row(100);row['macd']=-1;row['obv_durum']='DUSEN'
        result=self.final(row);self.assertEqual(result['karar'],'BEKLE');self.assertLess(result['confidence'],50);self.assertIn('KARISIK',result['safety_flags'])
    def test_critical_news_blocks_buy_and_reduces_confidence(self):
        news={'id':'bad','sembol':'THYAO','ilk_gorulme':self.now.isoformat(),'analiz':{'etki_puani':-9,'guven':100}}
        result=self.final(self.row(100),news=[news]);self.assertNotIn(result['karar'],('AL','GUCLU_AL'));self.assertIn('KRITIK_HABER',result['safety_flags']);self.assertLess(result['confidence'],50)
    def test_positive_news_cannot_create_strong_buy_from_weak_technical(self):
        news={'id':'good','sembol':'THYAO','ilk_gorulme':self.now.isoformat(),'reference_price':90,'analiz':{'etki_puani':10,'guven':100}}
        self.assertNotIn(self.final(self.row(50),news=[news])['karar'],('AL','GUCLU_AL'))
    def test_hard_buy_guards(self):
        for field,value,flag in [('degisim',-7,'SERT_DUSUS'),('degisim',9,'ASIRI_YUKSELIS'),('karar_stop',101,'STOP'),('karar_rr',.5,'RISK_GETIRI'),('rsi',90,'ASIRI_ALIM'),('haber_puani',-8,'KRITIK_HABER')]:
            with self.subTest(field=field):
                row=self.row(100);row[field]=value;result=self.final(row)
                self.assertNotIn(result['karar'],('AL','GUCLU_AL'));self.assertIn(flag,result['safety_flags'])
    def test_nine_percent_fall_and_negative_news_never_strong_buy(self):
        row=self.row(100);row.update(degisim=-9,haber_puani=-9)
        self.assertEqual(self.final(row)['karar'],'BEKLE')
    def test_rsi_alone_cannot_sell(self):
        row=self.row(50);row['rsi']=90;self.assertEqual(self.final(row)['karar'],'BEKLE')
    def test_oversold_without_rebound_is_not_buy(self):
        row=self.row(100);row['rsi']=20;self.assertEqual(self.final(row)['karar'],'BEKLE')
    def test_oversold_confirmed_rebound_keeps_other_buy_gates(self):
        row=self.row(85)
        row.update(rsi=25,rsi_onceki=20,dipten_toparlanma=2,hist=1,hist_onceki=.5,teknik_gostergeler=self.doc('TOMORROW'))
        result=self.final(row);self.assertEqual(result['karar'],'AL');self.assertIn('Aşırı satım sonrası tepki teyitli',result['pozitif_gerekceler'])
    def test_market_and_sector_cannot_create_direction_by_themselves(self):
        row=self.row(78);neutral=self.final(row)
        for value in (10,-10):
            macro={'updated_at':self.now.isoformat(),'sektor_puani':value,'sektor_event_id':'sector'}
            self.assertEqual(self.final(row,macro=macro)['karar'],neutral['karar'])
    def test_strong_down_market_requires_more_strong_buy_confirmations(self):
        row=self.row(100);row['piyasa_baglami']={'piyasa_rejimi':'GUCLU_DUSUS','breadth_score':-60,'rejim_score':-70,'sektor_rs_score':80,'stale':False,'updated_at':self.now.isoformat()}
        result=self.final(row);self.assertEqual(result['minimum_guclu_al_teyidi'],6);self.assertNotEqual(result['karar'],'GUCLU_AL')
    def test_standard_indicators_explain_but_do_not_double_score(self):
        row=self.row();baseline=evaluate(row,current=self.now);row['teknik_gostergeler']=self.doc('TOMORROW')
        result=evaluate(row,current=self.now);self.assertEqual(result['ai_score'],baseline['ai_score']);self.assertEqual(result['teknik_ana_skor_etkisi'],0)
    def test_intraday_preserves_short_frame_and_raw_rank_values(self):
        row=self.row();row.update(gun_ici_al_puani=90,gun_ici_sat_puani=0,gun_ici_rr=2,gun_ici_stop=90,gun_ici_puan=80,
          rsi5=55,macd5=1,signal5=0,ema9_5=99,ema21_5=98,hacim3_orani=160,teknik_gostergeler=self.doc())
        baseline=copy.deepcopy(row);result=attach_final_decision(row,self.now,'INTRADAY')
        self.assertEqual(result['zaman_dilimi'],'INTRADAY');self.assertEqual(result['minimum_al_teyidi'],4)
        self.assertEqual({k:v for k,v in row.items() if k!='nihai_karar'},baseline)
    def test_tomorrow_comment_does_not_overwrite_calibration_fields(self):
        row=self.row();row.update(ham_puan=80,final_puan=81,shadow_puan=82,kalibrasyon_duzeltmesi=1)
        attach_final_decision(row,self.now,'DAILY');self.assertEqual((row['ham_puan'],row['final_puan'],row['shadow_puan'],row['kalibrasyon_duzeltmesi']),(80,81,82,1))
    def test_future_news_and_late_analysis_do_not_change_decision(self):
        row=self.row();before=evaluate(row,current=self.now)
        for event in ({'id':'future','sembol':'THYAO','ilk_gorulme':(self.now+timedelta(days=1)).isoformat(),'analiz':{'etki_puani':-10,'guven':100}},
                      {'id':'revised','sembol':'THYAO','published_at':(self.now-timedelta(days=1)).isoformat(),'ilk_gorulme':(self.now+timedelta(days=1)).isoformat(),'analiz':{'etki_puani':-10,'guven':100}},
                      {'id':'futureanalysis','sembol':'THYAO','ilk_gorulme':self.now.isoformat(),'analiz':{'etki_puani':-10,'guven':100,'updated_at':(self.now+timedelta(days=1)).isoformat()}}):
            self.assertEqual(evaluate(row,news=[event],current=self.now),before)
    def test_future_macro_does_not_change_decision(self):
        before=evaluate(self.row(),current=self.now)
        self.assertEqual(evaluate(self.row(),macro={'updated_at':(self.now+timedelta(days=1)).isoformat(),'makro_puani':-10},current=self.now),before)
    def test_future_model_uses_baseline_not_learned_weights_or_thresholds(self):
        row=self.row();before=evaluate(row,current=self.now);row['model_asof']=(self.now+timedelta(days=1)).isoformat()
        weights=dict(DEFAULT_WEIGHTS,teknik=.8,haber=.05)
        later=evaluate(row,weights=weights,thresholds={'GUCLU_AL':90,'AL':80,'SAT':25,'GUCLU_SAT':15},current=self.now)
        self.assertEqual(later,before)
    def test_future_quote_is_not_a_buy_and_future_indicator_is_not_usable(self):
        row=self.row(100);row['canli_guncelleme']=(self.now+timedelta(days=1)).isoformat();self.assertEqual(self.final(row)['karar'],'BEKLE')
        row=self.row(100);row['teknik_gostergeler']=self.doc();row['teknik_gostergeler']['asof']=(self.now+timedelta(minutes=5)).isoformat()
        self.assertEqual(self.final(row)['karar'],'BEKLE')
    def test_future_history_outcomes_do_not_change_score(self):
        row=self.row();record={'zaman':self.now.isoformat(),'sembol':'THYAO','model':'ORTAK_AI','karar':'AL','piyasa_rejimi':'POZITIF','egitim_durumu':'EGITIM',
              'sonuc_5g':{'observed_at':(self.now+timedelta(days=5)).isoformat(),'degerlendirme_tamamlandi':True,'durum':'BASARILI','getiri_yuzde':20}}
        self.assertEqual(evaluate(row,history=[record]*40,current=self.now),evaluate(row,current=self.now))
    def test_legacy_api_alias_and_five_value_contract(self):
        result=evaluate(self.row(50),current=self.now);self.assertEqual(result['karar'],'IZLE');self.assertEqual(result['nihai_karar']['karar'],'BEKLE')
        for key in ('karar_puani','confidence','teknik_gucluluk','risk_puani','pozitif_gerekceler','negatif_gerekceler','ana_risk','ana_secim_nedeni','kullanilan_kriterler','model_version'):self.assertIn(key,result['nihai_karar'])
    def test_shared_worker_freezes_final_and_future_batch_weights_are_ignored(self):
        engine=AIKararMotoru(self.paths,clock=lambda:self.now);row=self.row(100)
        first=engine.batch(['THYAO'],[row]);self.assertFalse(first['hatalar'])
        frozen=json.loads(engine.history_path.read_text())['kayitlar'][0]['nihai_karar']
        self.assertEqual(frozen['model_version'],FINAL_MODEL)
        row.update(fiyat=90,teknik_puan=10);engine.batch(['THYAO'],[row])
        self.assertEqual(json.loads(engine.history_path.read_text())['kayitlar'][0]['nihai_karar'],frozen)
        config=json.loads(engine.weight_path.read_text());config['updated_at']=(self.now+timedelta(days=1)).isoformat();config['esikler']={'GUCLU_AL':95,'AL':90,'SAT':25,'GUCLU_SAT':15};atomic_json(engine.weight_path,config)
        result=engine.batch(['THYAO'],[self.row(100)])['hisseler']['THYAO'];self.assertEqual(result['nihai_karar']['karar'],'GUCLU_AL')
    def test_read_time_stale_does_not_change_frozen_record(self):
        final=self.final();frozen=copy.deepcopy(final);view=decision_view(final,self.now+timedelta(days=2))
        self.assertEqual(view['karar'],'BEKLE');self.assertLess(view['confidence'],50);self.assertEqual(final,frozen)
    def test_final_performance_uses_frozen_buckets_and_no_future_outcome(self):
        final=self.final();record={'model':'ORTAK_AI','zaman':self.now.isoformat(),'nihai_karar':final,'egitim_durumu':'EGITIM',
          'sonuc_1g':{'observed_at':(self.now+timedelta(days=1)).isoformat(),'degerlendirme_tamamlandi':True,'durum':'BASARILI','getiri_yuzde':3}}
        before=copy.deepcopy(record);self.assertFalse(final_decision_report([record],self.now)['vadeler']['1'])
        later=final_decision_report([record],self.now+timedelta(days=2));self.assertEqual(later['vadeler']['1']['karar:AL']['sample_count'],1)
        self.assertTrue(any(k.startswith('confidence:') for k in later['vadeler']['1']));self.assertFalse(later['thresholds_adapted']);self.assertEqual(record,before)
    def test_detail_http_contract_legacy_fields_and_freshness(self):
        from web_server import create_server
        row=self.row();attach_final_decision(row,self.now,'DAILY');atomic_json(self.paths.public/'bist_data.json',{'hisseler':[row]})
        records=UserRecords(self.paths.users,self.paths.web,public_dir=self.paths.public)
        server=create_server('127.0.0.1',0,records,data_paths=self.paths);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with patch('kullanici_kayitlari.now',return_value=self.now.isoformat()):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/stocks/THYAO') as response:body=json.load(response)
        self.assertEqual(body['nihai_karar']['karar'],'AL');self.assertIn('hedef',body['otomatik']);self.assertIn('alarmlar',body)
        self.assertEqual(body['otomatik']['nihai_karar'],body['nihai_karar'])
        shared=copy.deepcopy(row['nihai_karar']);shared.update(karar='BEKLE',updated_at=(self.now+timedelta(minutes=1)).isoformat(),ana_risk='Kritik negatif haber')
        atomic_json(self.paths.public/'ai_hisse_ozetleri.json',{'hisseler':{'THYAO':{'nihai_karar':shared}}})
        with patch('kullanici_kayitlari.now',return_value=self.now.isoformat()):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/stocks/THYAO') as response:newer=json.load(response)
        self.assertEqual(newer['nihai_karar']['karar'],'BEKLE');self.assertEqual(newer['otomatik']['nihai_karar']['karar'],'AL')
        shared['updated_at']=(datetime.now(ISTANBUL)+timedelta(days=1)).isoformat()
        atomic_json(self.paths.public/'ai_hisse_ozetleri.json',{'hisseler':{'THYAO':{'nihai_karar':shared}}})
        with patch('kullanici_kayitlari.now',return_value=self.now.isoformat()):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/stocks/THYAO') as response:future=json.load(response)
        self.assertEqual(future['nihai_karar']['karar'],'AL')

    def test_sector_evidence_is_controlled_and_direction_stays_wait(self):
        for strength,expected in ((80,1),(-80,-1)):
            row=self.row(78);row['piyasa_rejimi']=0
            row['piyasa_baglami']={'rejim_score':0,'sektor_rs_score':strength,'stale':False,'updated_at':self.now.isoformat()}
            result=self.final(row);self.assertEqual(result['kullanilan_kriterler']['market'],expected)
            self.assertEqual(result['karar'],'BEKLE')

    def test_intraday_signal_freezes_final_even_when_future_quote_changes(self):
        row=self.row();row.update(gun_ici_puan=80,gun_ici_al_puani=90,gun_ici_sat_puani=0,gun_ici_karar='AL',gun_ici_rr=2,
            gun_ici_stop=90,gun_ici_kar_al=110,veri_tarihi=(self.now-timedelta(minutes=5)).isoformat(),
            teknik_gostergeler=self.doc(),rsi5=55,macd5=1,signal5=0,ema9_5=99,ema21_5=98,hacim3_orani=160)
        engine=GunIciPerformans(self.paths,clock=lambda:self.now);top=engine.rank([row]);self.assertEqual(top[0]['gun_ici_final_puan'],80)
        self.assertTrue(engine.record(top));frozen=copy.deepcopy(engine.state()['kayitlar'][0]['nihai_karar'])
        row['nihai_karar']['karar']='GUCLU_SAT';engine.record([row])
        self.assertEqual(engine.state()['kayitlar'][0]['nihai_karar'],frozen)

    def test_tomorrow_archive_freezes_final_and_import_preserves_it(self):
        current=self.now.replace(hour=19);row=self.row(100);row['canli_guncelleme']=current.isoformat()
        attach_final_decision(row,current,'DAILY')
        with patch.object(bot,'YARIN_TOP10_FILE',str(self.paths.public/'yarin_top10.json')),patch.object(bot,'YARIN_TOP10_ARSIV_DIR',str(self.paths.archives)),patch.object(bot,'yarin_top10_listesi',side_effect=lambda rows,**kwargs:[(80,r) for r in rows]),patch.object(bot,'datetime',wraps=datetime) as clock:
            clock.now.return_value=current;first=bot.yarin_top10_kilitli_kaydet([row],1)
            path=self.paths.archives/'2026-10-06.json';original=path.read_bytes();frozen=first['top10'][0]['tahmin']['nihai_karar']
            row['nihai_karar']['karar']='GUCLU_SAT';self.assertEqual(bot.yarin_top10_kilitli_kaydet([row],1),first)
            self.assertEqual(path.read_bytes(),original)
            records=PerformansMotoru(self.paths).snapshot_records({'arsivler':{}})
            self.assertEqual(records[0]['nihai_karar'],frozen);self.assertEqual(path.read_bytes(),original)

    def test_intraday_batch_does_not_mix_daily_indicators(self):
        atomic_json(self.paths.public/'bist_data.json',{'hisseler':[self.row(100)]})
        row=self.row(0,-1);row.update(gun_ici_al_puani=0,gun_ici_sat_puani=100,rsi5=40,macd5=-1,signal5=0,
            hacim3_orani=160,gun_ici_rr=2,gun_ici_stop=110,ema9_5=102,ema21_5=104,teknik_gostergeler=self.doc(direction=-1))
        result=AIKararMotoru(self.paths,clock=lambda:self.now).batch(['THYAO'],[row])['hisseler']['THYAO']
        self.assertEqual(result['girdiler']['rsi'],40);self.assertEqual(result['girdiler']['macd'],-1)
        self.assertEqual(result['nihai_karar']['zaman_dilimi'],'INTRADAY');self.assertEqual(result['nihai_karar']['karar'],'GUCLU_SAT')

    def test_confirmation_and_confidence_performance_modes_do_not_mix(self):
        daily=self.final();intra=copy.deepcopy(daily);intra['zaman_dilimi']='INTRADAY'
        outcome={'observed_at':(self.now+timedelta(days=1)).isoformat(),'durum':'BASARILI','getiri_yuzde':2,'degerlendirme_tamamlandi':True,'tamamlandi':True,'egitime_uygun':True}
        rows=[{'zaman':self.now.isoformat(),'sinyal_zamani':self.now.isoformat(),'nihai_karar':doc,'sonuc_1g':outcome,'sonuclar':{'5':outcome}} for doc in (daily,intra)]
        end=self.now+timedelta(days=2)
        self.assertEqual(final_decision_report(rows,end)['vadeler']['1']['karar:AL']['sample_count'],1)
        self.assertEqual(final_decision_report(rows,end,'INTRADAY')['vadeler']['5']['karar:AL']['sample_count'],1)
