"""Controlled evidence, bounded family transfers and prospective validation."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch,Mock
from performans_motoru import (evidence_rows,evidence_stats,evidence_report,evidence_features,family_proposal,
 controlled_publish,controlled_context,controlled_score,EVIDENCE_BASE,CRITERION_FAMILIES,FAMILY_BUDGETS,evidence_limits,PerformansMotoru,business_day)
from ai_karar_motoru import ISTANBUL
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json

class ControlledLearningTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.paths=DataPaths({'BIST_DATA_DIR':self.temp.name});self.paths.ensure()
  self.now=datetime(2026,10,20,19,tzinfo=ISTANBUL)
  self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'MIN_LEARNING_SAMPLES':'40','MIN_LEARNING_DAYS':'5','LEARNING_ENABLED':'false'}))
  self.days=[];at=datetime(2026,9,1,19,tzinfo=ISTANBUL)
  while len(self.days)<8:
   if business_day(at.date()):self.days.append(at)
   at+=timedelta(days=1)
 def row(self,i=0,win=True,mode='DAILY',at=None):
  at=at or self.days[i%8];identity='R'+str(i)
  doc={'mode':'INTRADAY' if mode=='INTRADAY' else 'TOMORROW','asof':at.isoformat(),'data_time':at.isoformat(),'stale':False,
       'momentum':{'status':'OK','confidence':100,'short_pct':-1 if win else 1},'obv':{},'vwap':{},'bollinger':{}}
  raw={'fiyat':100,'rsi':55 if win else 80,'rsi5':55 if win else 80,'karar_rr':2,'risk_getiri':2,'gun_ici_rr':2,'atr14':2,
       'canli_guncelleme':at.isoformat(),'teknik_gostergeler':doc}
  outcome={'durum':'BASARILI' if win else 'STOP','getiri_yuzde':4 if win else -2,'yon_getirisi':4 if win else -2,
      'observed_at':(at+timedelta(days=1)).isoformat(),'degerlendirme_tamamlandi':True,'tamamlandi':True,'egitime_uygun':True,
      'hedefe_ulasti':win,'stop_oldu':not win,'hedef_temasi':win,'stop_temasi':not win,'ilk_temas':'HEDEF' if win else 'STOP',
      'maksimum_dusus':-1 if win else -3,'kalite_uyarilari':[]}
  final={'karar':'AL','confidence':55+i%4*10,'teyit_sayisi':3+i%4,'zaman_dilimi':mode,'updated_at':at.isoformat()}
  return {'kayit_id':identity,'id':identity,'sembol':'S'+str(i),'model':'YARIN_TOP10' if mode=='DAILY' else 'GUN_ICI','karar':'AL',
     'zaman':at.isoformat(),'sinyal_zamani':at.isoformat(),'kriterler':raw,'analiz':raw,'teknik_gostergeler':doc,'nihai_karar':final,
     'sektor':'TEKNOLOJI' if win else 'BANKA','piyasa_rejimi':'YUKSELIS' if win else 'DUSUS','egitim_durumu':'EGITIM',
     **{'sonuc_'+str(h)+'g':copy.deepcopy(outcome) for h in (1,3,5,10,20,60)},'sonuclar':{str(h):copy.deepcopy(outcome) for h in (5,15,30,60,'SEANS')}}
 def rows(self,mode='DAILY'):return [self.row(i,i<40,mode) for i in range(80)]
 def pairs(self,rows=None,mode='DAILY'):return evidence_rows(rows or self.rows(mode),self.now,mode,1 if mode=='DAILY' else 60)
 def test_catalog_and_families(self):self.assertEqual(len(CRITERION_FAMILIES),36);self.assertEqual(set(CRITERION_FAMILIES.values()),set(FAMILY_BUDGETS))
 def test_sample_success_failure_counts(self):
  stats=evidence_stats(self.pairs());self.assertEqual((stats['sample_count'],stats['success_count'],stats['failure_count'],stats['different_days']),(80,40,40,8))
 def test_robust_stats_and_hit_rates(self):
  stats=evidence_stats(self.pairs());self.assertEqual(stats['median_return'],1);self.assertEqual(stats['trimmed_mean_return'],1)
  self.assertEqual((stats['average_return'],stats['worst_return'],stats['best_return'],stats['target_hit_rate'],stats['stop_hit_rate']),(1,-2,4,.5,.5))
 def test_confidence_requires_minimum(self):self.assertEqual(evidence_stats(self.pairs()[:39])['confidence'],'DUSUK')
 def test_minimum_days_gate(self):
  rows=[self.row(i,i<40,at=self.days[0]) for i in range(80)];self.assertEqual(evidence_report(self.pairs(rows))['RSI']['direction'],'SABIT')
 def test_minimum_each_group_gate(self):
  pairs=self.pairs()[:39];report=evidence_report(pairs);weights,reasons,_=family_proposal(report,EVIDENCE_BASE,EVIDENCE_BASE,pairs)
  self.assertEqual(weights,EVIDENCE_BASE);self.assertFalse(reasons)
 def test_configurable_safe_minimums(self):
  with patch.dict(os.environ,{'MIN_LEARNING_SAMPLES':'60','MIN_LEARNING_DAYS':'8'}):self.assertEqual(evidence_limits(),(60,8))
  with patch.dict(os.environ,{'MIN_LEARNING_DAYS':'1'}),self.assertRaises(ValueError):evidence_limits()
 def test_unknown_is_not_negative_sample(self):
  row=self.row();row['kriterler'].pop('rsi');row['analiz'].pop('rsi',None)
  report=evidence_report(self.pairs([row]));self.assertEqual(report['RSI']['unknown'],1);self.assertEqual(report['RSI']['yokken']['sample_count'],0)
 def test_same_bar_ambiguity_excluded(self):
  row=self.row();row['sonuc_1g']['ilk_temas']='BELIRSIZ';self.assertFalse(self.pairs([row]))
 def test_bad_quality_excluded(self):
  row=self.row();row['sonuc_1g']['kalite_uyarilari']=['OHLC_EKSIK'];self.assertFalse(self.pairs([row]))
 def test_partial_success_not_full_success(self):
  row=self.row();row['sonuc_1g']['durum']='KISMEN_BASARILI';stats=evidence_stats(self.pairs([row]));self.assertEqual(stats['success_count'],0);self.assertEqual(stats['partial_count'],1)
 def test_first_stock_day_sampling_before_outcome(self):
  first=self.row();first['sonuc_1g']['degerlendirme_tamamlandi']=False;later=self.row();later['zaman']=(self.days[0]+timedelta(minutes=1)).isoformat();later['sinyal_zamani']=later['zaman']
  self.assertFalse(self.pairs([later,first]))
 def test_mode_isolation(self):
  rows=self.rows()+self.rows('INTRADAY');self.assertEqual(len(self.pairs(rows)),80);self.assertEqual(len(self.pairs(rows,'INTRADAY')),80)
 def test_minmax_daily_limits_and_sum(self):
  pairs=self.pairs();report=evidence_report(pairs);weights,reasons,_=family_proposal(report,EVIDENCE_BASE,EVIDENCE_BASE,pairs)
  self.assertTrue(reasons);self.assertAlmostEqual(sum(weights.values()),1)
  for key,value in weights.items():self.assertTrue(EVIDENCE_BASE[key]*.5-1e-12<=value<=EVIDENCE_BASE[key]*1.5+1e-12);self.assertLessEqual(abs(value-EVIDENCE_BASE[key]),.005+1e-12)
 def test_repeated_same_day_cannot_exceed_limit(self):
  pairs=self.pairs();report=evidence_report(pairs);weights=dict(EVIDENCE_BASE)
  for _ in range(20):weights,_,_=family_proposal(report,weights,EVIDENCE_BASE,pairs)
  self.assertLessEqual(max(abs(weights[k]-EVIDENCE_BASE[k]) for k in weights),.005+1e-12)
 def test_family_budget_preserved(self):
  weights,_,_=family_proposal(evidence_report(self.pairs()),EVIDENCE_BASE,EVIDENCE_BASE,self.pairs())
  for family,budget in FAMILY_BUDGETS.items():self.assertAlmostEqual(sum(weights[k] for k,v in CRITERION_FAMILIES.items() if v==family),budget)
 def test_correlated_criteria_not_independent_votes(self):
  rows=self.rows()
  for i,row in enumerate(rows):row['kriterler'].update(sma20=110 if i<40 else 90,sma50=100,ema9_5=110 if i<40 else 90,ema21_5=100)
  pairs=self.pairs(rows);_,_,overlap=family_proposal(evidence_report(pairs),EVIDENCE_BASE,EVIDENCE_BASE,pairs)
  self.assertTrue(any(item['criterion']=='EMA_TREND' and item['representative']=='SMA_TREND' for item in overlap))
 def test_publish_versions_and_private_training_ids(self):
  result=controlled_publish(self.paths,self.rows(),self.now,'DAILY');model=controlled_context(self.paths,self.now,'DAILY')
  self.assertEqual(model['model_version'],result['shadow_version']);self.assertIn('parent_version',model);self.assertEqual(len(model['training_ids']),80)
  public=json.loads((self.paths.public/'kriter_performansi.json').read_text());self.assertNotIn('training_ids',json.dumps(public));self.assertFalse(result['learning_enabled'])
 def test_incremental_no_recompute_without_new_closed_results(self):
  rows=self.rows();first=controlled_publish(self.paths,rows,self.now,'DAILY');path=self.paths.public/'kriter_performansi.json';before=path.read_bytes()
  with patch('performans_motoru.evidence_report',side_effect=AssertionError('No repeated statistics')):second=controlled_publish(self.paths,rows,self.now+timedelta(minutes=1),'DAILY')
  self.assertEqual(first,second);self.assertEqual(before,path.read_bytes())
 def test_regime_and_sector_reports(self):
  report=controlled_publish(self.paths,self.rows(),self.now,'DAILY');self.assertIn('YUKSELIS',report['scopes']['piyasa_rejimi']);self.assertIn('BANKA',report['scopes']['sektor'])
  self.assertFalse(report['scopes']['sektor']['BANKA']['weights_applied'])
 def test_decision_confidence_and_confirmation_buckets(self):
  result=controlled_publish(self.paths,self.rows(),self.now,'DAILY');buckets=result['decision_buckets']
  for band in ('50-60','60-70','70-80','80+'):self.assertIn('karar_confidence:AL:'+band,buckets)
  for count in ('3','4','5','6+'):self.assertIn('teyit:'+count,buckets)
 def test_shadow_never_changes_main_row(self):
  controlled_publish(self.paths,self.rows(),self.now,'DAILY');model=controlled_context(self.paths,self.now,'DAILY');row=self.row(100,True,at=self.now+timedelta(days=1));row['teknik_puan']=80
  before=copy.deepcopy(row);result=controlled_score(row,80,self.now+timedelta(days=1),'DAILY',model)
  self.assertEqual(row,before);self.assertFalse(result['main_score_changed']);self.assertLessEqual(abs(result['correction']),2)
 def test_future_model_cannot_change_past_shadow(self):
  controlled_publish(self.paths,self.rows(),self.now,'DAILY');model=controlled_context(self.paths,self.now,'DAILY');row=self.row();self.assertEqual(controlled_score(row,80,self.days[0],'DAILY',model)['model_version'],'BASE')
 def test_training_and_evaluation_not_same_cohort(self):
  report=controlled_publish(self.paths,self.rows(),self.now,'DAILY');self.assertFalse(report['comparisons'])
  again=controlled_publish(self.paths,self.rows(),self.now+timedelta(minutes=1),'DAILY');self.assertEqual(again,report)
 def test_future_outcomes_do_not_count(self):
  row=self.row();row['sonuc_1g']['observed_at']=(self.now+timedelta(days=1)).isoformat();self.assertFalse(self.pairs([row]))
 def test_future_indicator_is_unknown(self):
  row=self.row();row['teknik_gostergeler']['asof']=(self.now+timedelta(days=1)).isoformat();self.assertTrue(all(v is None for v in evidence_features(row,'DAILY').values()))
 def test_late_news_not_credited(self):
  row=self.row();row['haber_metadata']={'canonical_id':'one','kaynak':'KAP','observed_at':(self.now+timedelta(days=1)).isoformat()};self.assertIsNone(evidence_features(row,'DAILY')['KAP'])
 def test_future_market_not_credited(self):
  row=self.row();row['piyasa_baglami']={'updated_at':(self.now+timedelta(days=1)).isoformat(),'rejim_score':100,'rejim_confidence':100};self.assertIsNone(evidence_features(row,'DAILY')['PIYASA_POZITIF'])
 def test_stale_data_and_negative_news_stop_bonus(self):
  pairs=self.pairs();weights,proposals,_=family_proposal(evidence_report(pairs),EVIDENCE_BASE,EVIDENCE_BASE,pairs)
  model={'created_at':self.now.isoformat(),'training_end':self.now.isoformat(),'model_version':'TEST','mode':'DAILY','weights':weights,'proposals':proposals}
  for change in ({'haber_puani':-8},{'degisim':-9},{'karar_stop':101},{'risk_getiri':.1}):
   row=self.row(100,at=self.now+timedelta(days=1));row['kriterler'].update(change);row.update(change);result=controlled_score(row,80,self.now+timedelta(days=1),'DAILY',model);self.assertLessEqual(result['correction'],0)
  row=self.row();self.assertEqual(controlled_score(row,80,self.now+timedelta(days=1),'DAILY',model)['correction'],0)
 def test_public_reports_preserve_both_modes_and_legacy_weights(self):
  atomic_json(self.paths.public/'onerilen_agirliklar.json',{'mevcut':{'teknik':.7}})
  controlled_publish(self.paths,self.rows(),self.now,'DAILY');controlled_publish(self.paths,self.rows('INTRADAY'),self.now,'INTRADAY')
  doc=json.loads((self.paths.public/'kriter_performansi.json').read_text());self.assertEqual(set(doc['modes']),{'DAILY','INTRADAY'})
  weights=json.loads((self.paths.public/'onerilen_agirliklar.json').read_text());self.assertEqual(weights['mevcut'],{'teknik':.7})
 def test_active_weights_and_snapshots_are_not_modified(self):
  path=self.paths.runtime/'ai_agirliklari.json';atomic_json(path,{'secret':'private','agirliklar':{'teknik':.7}});before=path.read_bytes();rows=self.rows();frozen=copy.deepcopy(rows)
  controlled_publish(self.paths,rows,self.now,'DAILY');self.assertEqual(path.read_bytes(),before);self.assertEqual(rows,frozen)
 def test_no_provider_calls_for_evidence_and_shadow(self):
  with patch('performans_motoru.provider_history',side_effect=AssertionError('No new provider')):controlled_publish(self.paths,self.rows(),self.now,'DAILY')
 def test_news_category_low_confidence_is_other(self):
  row=self.row();row['model']='HABER';row['haber_metadata']={'category':'BILANCO','confidence':30,'observed_at':row['zaman']}
  result=controlled_publish(self.paths,[row],self.now,'DAILY');self.assertIn('OTHER',result['news_types']['1']);self.assertNotIn('BILANCO',result['news_types']['1'])
 def test_news_category_trusted_and_ambiguous_outcome_excluded(self):
  row=self.row();row['model']='HABER';row['haber_metadata']={'category':'SOZLESME','confidence':90,'observed_at':row['zaman']}
  result=controlled_publish(self.paths,[row],self.now,'DAILY');self.assertEqual(result['news_types']['1']['SOZLESME']['sample_count'],1)
 def test_shadow_is_held_prospectively_for_several_days(self):
  controlled_publish(self.paths,self.rows(),self.now,'DAILY');first=controlled_context(self.paths,self.now,'DAILY')
  rows=self.rows();rows[0]['sonuc_3g']['getiri_yuzde']=10
  controlled_publish(self.paths,rows,self.now+timedelta(days=1),'DAILY');later=controlled_context(self.paths,self.now+timedelta(days=1),'DAILY')
  self.assertEqual(first['model_version'],later['model_version'])

 def prospective(self,risk=-1):
  training=self.rows();controlled_publish(self.paths,training,self.now,'DAILY');model=controlled_context(self.paths,self.now,'DAILY')
  days=[];at=datetime(2026,11,2,19,tzinfo=ISTANBUL)
  while len(days)<8:
   if business_day(at.date()):days.append(at)
   at+=timedelta(days=1)
  validation=[]
  for cohort,win in (('YARIN_TOP10',False),('YARIN_CONTROLLED_SHADOW',True)):
   for i in range(80):
    row=self.row(1000+i,win,at=days[i%8]);row.update(model=cohort,kayit_id=cohort+str(i),id=cohort+str(i))
    row['controlled_shadow']={'model_version':model['model_version'],'created_at':row['zaman'],'mode':'DAILY'}
    if win:row['sonuc_1g']['maksimum_dusus']=risk
    validation.append(row)
  return training,validation,model

 def test_promotion_requires_genuine_later_cohort_and_never_applies(self):
  training,validation,model=self.prospective();result=controlled_publish(self.paths,training+validation,datetime(2026,11,30,19,tzinfo=ISTANBUL),'DAILY')
  comparison=result['comparisons'][model['model_version']]
  self.assertTrue(comparison['promotion_candidate']);self.assertFalse(comparison['automatic_promotion'])
  self.assertEqual(comparison['main']['sample_count'],80);self.assertEqual(comparison['shadow']['different_days'],8)

 def test_risk_deterioration_blocks_promotion(self):
  training,validation,model=self.prospective(risk=-5);result=controlled_publish(self.paths,training+validation,datetime(2026,11,30,19,tzinfo=ISTANBUL),'DAILY')
  self.assertFalse(result['comparisons'][model['model_version']]['promotion_candidate'])

 def test_future_validation_and_training_ids_do_not_count(self):
  training,validation,model=self.prospective()
  for row in validation:row['sonuc_1g']['observed_at']='2027-01-01T19:00:00+03:00'
  result=controlled_publish(self.paths,training+validation,datetime(2026,11,30,19,tzinfo=ISTANBUL),'DAILY')
  self.assertEqual(result['comparisons'][model['model_version']]['shadow']['sample_count'],0)
  self.assertFalse(result['comparisons'][model['model_version']]['promotion_candidate'])

 def test_snapshot_freeze_under_later_price_news_market_model_results(self):
  from gun_ici_performans import GunIciPerformans
  at=datetime(2026,10,20,12,tzinfo=ISTANBUL);row={'sembol':'THYAO','fiyat':100,'gun_ici_puan':80,'gun_ici_karar':'AL','gun_ici_rr':2,
   'gun_ici_stop':90,'gun_ici_kar_al':120,'veri_tarihi':(at-timedelta(minutes=5)).isoformat(),'controlled_shadow':{'score':80,'model_version':'BASE'}}
  engine=GunIciPerformans(self.paths,clock=lambda:at);self.assertTrue(engine.record([row]));frozen=copy.deepcopy(engine.state()['kayitlar'][0])
  row.update(fiyat=1000,haber_puani=-10,piyasa_rejimi='GUCLU_DUSUS',controlled_shadow={'score':0,'model_version':'FUTURE'})
  engine.record([row]);later=engine.state()['kayitlar'][0]
  for key in ('analiz','controlled_shadow','giris_fiyati','skor'):self.assertEqual(later[key],frozen[key])

 def test_worker_batch_still_uses_existing_bounded_provider(self):
  records=self.rows()[:10]
  for row in records:
   row.update(model='ORTAK_AI',fiyat=100,hedef=110,stop=95)
   for h in (1,3,5,10,20,60):row['sonuc_'+str(h)+'g']=None
  atomic_json(self.paths.runtime/'ai_ogrenme_gecmisi.json',{'kayitlar':records})
  provider=Mock(return_value=[]);engine=PerformansMotoru(self.paths,clock=lambda:self.now,history_provider=provider,batch_size=2)
  result=engine.one_round();self.assertEqual(provider.call_count,2);self.assertEqual(result['sembol_sayisi'],2)

 def test_static_http_reports_and_private_state_isolation(self):
  import threading,urllib.request,urllib.error
  from web_server import create_server
  controlled_publish(self.paths,self.rows(),self.now,'DAILY');server=create_server('127.0.0.1',0,data_paths=self.paths)
  threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/data/kriter_performansi.json') as response:report=json.load(response)
  self.assertIn('DAILY',report['modes'])
  with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/data/yarin_kalibrasyon.json')

 def test_changed_evidence_is_batched_instead_of_full_recompute_each_tick(self):
  rows=self.rows();first=controlled_publish(self.paths,rows,self.now,'DAILY');rows[0]['sonuc_1g']['getiri_yuzde']=10
  with patch('performans_motoru.evidence_report',side_effect=AssertionError('No per-tick aggregate rebuild')):
   second=controlled_publish(self.paths,rows,self.now+timedelta(minutes=1),'DAILY')
  self.assertEqual(first,second)
  later=controlled_publish(self.paths,rows,self.now+timedelta(hours=2),'DAILY');self.assertNotEqual(later['model_version'],first['model_version'])

 def test_invalid_weight_budget_fails_closed_without_altering_main(self):
  controlled_publish(self.paths,self.rows(),self.now,'DAILY');model=copy.deepcopy(controlled_context(self.paths,self.now,'DAILY'));model['weights']['RSI']=100
  row=self.row(100,at=self.now+timedelta(days=1));value=controlled_score(row,80,self.now+timedelta(days=1),'DAILY',model)
  self.assertEqual(value['score'],80);self.assertEqual(value['model_version'],'BASE')

 def test_reports_release_history_lock_before_taking_model_lock(self):
  import fcntl
  engine=PerformansMotoru(self.paths,clock=lambda:self.now,history_provider=Mock(return_value=[]))
  original=engine.reports
  def report(records,current):
   with Path(str(engine.history_path)+'.lock').open('a') as handle:
    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fcntl.flock(handle,fcntl.LOCK_UN)
   original(records,current)
  with patch.object(engine,'reports',side_effect=report) as callback:engine.one_round()
  self.assertEqual(callback.call_count,1)
