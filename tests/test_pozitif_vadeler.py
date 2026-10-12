"""Trading-session horizons, immutable forecasts and bounded outcome evidence."""
import copy
import json
from datetime import datetime,date,timedelta
from unittest import TestCase
from unittest.mock import Mock
from tests import test_pozitif_kapanis as fixtures
from ai_karar_motoru import ISTANBUL
from kullanici_kayitlari import atomic_json
from performans_motoru import outcome,sessions_after,business_day,PerformansMotoru,POSITIVE_HORIZONS
from pozitif_kapanis import publish_performance,continuation_report,best_horizons

class PositiveHorizonTests(TestCase):
 setUp=fixtures.PositiveClosingTests.setUp
 row=fixtures.PositiveClosingTests.row
 final=fixtures.PositiveClosingTests.final
 signals=fixtures.PositiveClosingTests.signals
 def record(self):return {'model':'POSITIVE_CANDIDATE','sembol':'S0','zaman':'2026-10-23T19:00:00+03:00','fiyat':100,'hedef':110,'stop':95,'karar':'AL','model_version':'FROZEN_V1'}
 def bars(self):
  return [{'timestamp':d.isoformat(),'open':100+i,'close':101+i,'high':103+i,'low':99-i*.2} for i,d in enumerate(sessions_after(date(2026,10,23),10))]
 def result(self,h,bars=None):return outcome(self.record(),bars or self.bars(),h,datetime(2026,11,10,19,tzinfo=ISTANBUL))
 def verify_horizon(self,h):
  r=self.result(h);self.assertEqual(r['vade_islem_gunu'],h);self.assertEqual(r['getiri_yuzde'],h)
  self.assertEqual(r['tarih'],sessions_after(date(2026,10,23),h)[-1].isoformat());self.assertEqual(r['en_yuksek_fiyat'],102+h)
  self.assertEqual(r['maksimum_yukselis'],h+2);self.assertAlmostEqual(r['mae_pct'],-1-(h-1)*.2);self.assertEqual(r['mfe_pct'],h+2)
  self.assertTrue(r['pozitif_sonuc']);self.assertTrue(r['degerlendirme_tamamlandi'])
 def test_1g(self):self.verify_horizon(1)
 def test_2g(self):self.verify_horizon(2)
 def test_3g(self):self.verify_horizon(3)
 def test_5g(self):self.verify_horizon(5)
 def test_10g(self):self.verify_horizon(10)
 def test_real_bist_holiday_weekend_and_half_session(self):
  self.assertEqual(sessions_after(date(2026,10,27),3),[date(2026,10,28),date(2026,10,30),date(2026,11,2)])
  self.assertFalse(business_day(date(2026,10,29)));self.assertTrue(business_day(date(2026,10,28)))
  self.assertFalse(business_day(date(2026,3,20)));self.assertFalse(business_day(date(2026,5,27)))
 def test_injected_special_closure_is_honored(self):
  self.assertEqual(sessions_after(date(2026,10,23),2,lambda d:d==date(2026,10,26)),[date(2026,10,27),date(2026,10,28)])
 def test_target_stop_order_differs_by_horizon(self):
  bars=self.bars();bars[0].update(high=112,close=109);bars[1].update(low=94,close=96,open=100)
  a=self.result(1,bars);b=self.result(2,bars);self.assertTrue(a['hedefe_ulasti']);self.assertFalse(a['stop_oldu'])
  self.assertTrue(b['hedefe_ulasti']);self.assertTrue(b['stop_oldu']);self.assertEqual(b['ilk_temas'],'HEDEF');self.assertTrue(b['hedef_once'])
 def test_same_bar_order_remains_unknown(self):
  bars=self.bars();bars[0].update(high=112,low=94)
  for h in POSITIVE_HORIZONS:
   with self.subTest(h=h):r=self.result(h,bars);self.assertEqual(r['ilk_temas'],'BELIRSIZ');self.assertIsNone(r['hedef_once'])
 def test_every_horizon_excludes_later_price_data(self):
  for h in POSITIVE_HORIZONS:
   with self.subTest(h=h):
    bars=self.bars();expected=self.result(h,bars)
    for bar in bars[h:]:bar.update(open=500,close=500,high=1000,low=1)
    self.assertEqual(self.result(h,bars),expected)
 def test_missing_session_does_not_shift_horizon(self):
  bars=self.bars();bars.pop(1);self.assertEqual(self.result(2,bars)['neden'],'ISLEM_GUNU_EKSIK');self.assertTrue(self.result(1,bars)['degerlendirme_tamamlandi'])
 def test_future_horizon_not_written_early(self):
  current=datetime(2026,10,26,19,tzinfo=ISTANBUL)
  self.assertIsNotNone(outcome(self.record(),self.bars(),1,current))
  for h in (2,3,5,10):self.assertIsNone(outcome(self.record(),self.bars(),h,current))
 def complete_records(self):
  records=self.signals()
  for r in records:
   for h in POSITIVE_HORIZONS:
    result=copy.deepcopy(r['sonuc_1g']);r['sonuc_'+str(h)+'g']=result
  return records
 def test_five_reports_and_top10_30_50_metrics(self):
  result=publish_performance(self.paths,self.complete_records(),self.now);self.assertEqual(set(result['horizons']),{'1','2','3','5','10'})
  for h,report in result['horizons'].items():
   with self.subTest(h=h):
    self.assertEqual(report['stats']['mfe']['median'],5);self.assertEqual(report['stats']['mae']['mean'],-2)
    for n in ('10','30','50'):
     top=report['capture']['top'][n];self.assertIn('target_hit_rate',top);self.assertIn('stop_hit_rate',top);self.assertIn('mfe',top);self.assertIn('mae',top)
 def test_horizon_report_cannot_use_other_outcomes(self):
  records=self.complete_records();expected=continuation_report(records,self.now,1)
  for r in records:
   for h in (2,3,5,10):r['sonuc_'+str(h)+'g']['getiri_yuzde']=999
  self.assertEqual(continuation_report(records,self.now,1),expected)
 def test_old_forecasts_remain_unchanged_without_new_expectations(self):
  records=self.complete_records();before=copy.deepcopy(records);result=publish_performance(self.paths,records,self.now)
  self.assertEqual(records,before);self.assertEqual(result['horizons']['2']['expected_return_calibration'],{})
 def test_best_horizon_requires_matured_matched_samples(self):
  records=self.complete_records()
  for r in records:r['sonuc_10g']=None
  result=best_horizons(records,self.now);self.assertEqual(result['sample_count'],0);self.assertFalse(result['combinations'])
 def test_best_horizon_detects_three_day_pattern_without_auto_learning(self):
  records=self.complete_records()
  for r in records:
   for h in POSITIVE_HORIZONS:r['sonuc_'+str(h)+'g']['getiri_yuzde']=5 if h==3 else -2
  result=best_horizons(records,self.now);sufficient=[v for v in result['combinations'].values() if v['sufficient']]
  self.assertTrue(sufficient);self.assertTrue(all(v['best_horizon']==3 and v['conclusive'] for v in sufficient));self.assertFalse(result['automatic_application'])
 def test_small_sample_has_no_definite_best_horizon(self):
  result=best_horizons(self.complete_records()[:20],self.now)
  self.assertTrue(all(v['best_horizon'] is None and not v['conclusive'] for v in result['criteria'].values()))
 def test_actual_engine_backfills_2g_10g_and_freezes_snapshot(self):
  forecast={'rank':1,'expected_return':1.2,'continuation_probability':70,'confidence':60,'risk':'ORTA','future_opportunity_score':80,'model_version':'FROZEN_V1','selection_rank':1}
  row={**self.record(),'positive_opportunity':forecast};snapshot={'analiz_tarihi':'2026-10-23','tahmin_zamani':row['zaman'],'top10':[row],'pozitif_havuz':{'adaylar':[row]}}
  path=self.paths.archives/'2026-10-23.json';atomic_json(path,snapshot);frozen=path.read_bytes();provider=Mock(return_value=self.bars())
  engine=PerformansMotoru(self.paths,clock=lambda:datetime(2026,11,10,19,tzinfo=ISTANBUL),history_provider=provider)
  engine.one_round();self.assertEqual(provider.call_count,1);self.assertEqual(path.read_bytes(),frozen)
  records=json.loads(engine.history_path.read_text())['kayitlar']
  for r in records:
   self.assertEqual(r['positive_opportunity'],forecast)
   for h in POSITIVE_HORIZONS:self.assertTrue(r['sonuc_'+str(h)+'g']['degerlendirme_tamamlandi'])
  before=copy.deepcopy(records);engine.one_round();after=json.loads(engine.history_path.read_text())['kayitlar']
  for a,b in zip(before,after):
   for h in POSITIVE_HORIZONS:self.assertEqual(a['sonuc_'+str(h)+'g'],b['sonuc_'+str(h)+'g'])
  self.assertEqual(path.read_bytes(),frozen)
 def test_old_history_backfills_only_missing_new_outcomes(self):
  record={**self.record(),'kayit_id':'OLD','positive_opportunity':{'rank':17,'expected_return':1.5,'model_version':'FROZEN_V1'}}
  for h in (1,3,5):record['sonuc_'+str(h)+'g']=self.result(h)
  before=copy.deepcopy(record);atomic_json(self.paths.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':[record]})
  engine=PerformansMotoru(self.paths,clock=lambda:datetime(2026,11,10,19,tzinfo=ISTANBUL),history_provider=Mock(return_value=self.bars()))
  engine.one_round();updated=json.loads(engine.history_path.read_text())['kayitlar'][0]
  for h in (1,3,5):self.assertEqual(updated['sonuc_'+str(h)+'g'],before['sonuc_'+str(h)+'g'])
  for h in (2,10):self.assertTrue(updated['sonuc_'+str(h)+'g']['degerlendirme_tamamlandi'])
  self.assertEqual(updated['positive_opportunity'],before['positive_opportunity'])
