import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch,Mock
import pandas as pd
from ai_karar_motoru import ISTANBUL
from veri_yollari import DataPaths
from kullanici_kayitlari import atomic_json
from pozitif_kapanis import (closing_inputs,build_pool,opportunity,continuation_pairs,historical_expectation,
                            capture_metrics,continuation_report,publish_performance,enrich_closing_sources,MODEL)
from performans_motoru import PerformansMotoru,evidence_features,outcome
from teknik_gostergeler import calculate

class PositiveClosingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.paths=DataPaths({'BIST_DATA_DIR':self.temp.name});self.paths.ensure()
  self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'POSITIVE_MIN_TURNOVER_TL':'1000000','MIN_LEARNING_SAMPLES':'40','MIN_LEARNING_DAYS':'5','POSITIVE_WINNER_RETURN_PCT':'2','LEARNING_ENABLED':'false'}))
  self.now=datetime(2026,10,6,19,tzinfo=ISTANBUL);self.cutoff=self.now.replace(hour=18,minute=10)
 def row(self,i=0,change=1.2,when=None):
  when=when or self.now;cutoff=when.replace(hour=18,minute=10)
  doc={'mode':'TOMORROW','asof':when.isoformat(),'data_time':cutoff.isoformat(),'stale':False,'confidence':100,
   'obv':{'status':'OK','confidence':100,'trend':'OBV_YUKSELEN','breakout':'OBV_KIRILIM_POZITIF','divergence':'YOK'},
   'momentum':{'status':'OK','confidence':100,'short_pct':2,'acceleration':1,'positive_turn':True,'state':'GUCLENIYOR','direction':'POZITIF'},
   'bollinger':{'status':'OK','confidence':100,'squeeze':True,'upper_break':True,'squeeze_volume_momentum_break':True},'vwap':{'status':'UNKNOWN','reference_20':99},
   'closing':{'close':100,'previous_close':100/(1+change/100),'turnover_tl':20000000,'volume_acceleration':.5,'return_3d':2,'ema9':97,'ema21':94,'macd_hist_improving':True}}
  return {'sembol':'S'+str(i),'fiyat':100,'degisim':change,'rsi':55,'macd':2,'signal':1,'hist':1,'sma20':95,'sma50':90,'ema9_daily':97,'ema21_daily':94,
   'atr14':2,'hacim_orani':180,'risk_getiri':2,'karar_rr':2,'karar_stop':95,'karar_hedef':110,'yarin_stop':95,'yarin_kar_al':110,
   'destek':93,'direnc':120,'teknik_puan':95,'teknik_puan_yarin':95,'al_puani':95,'sat_puani':5,'guven_skoru':90,'karar':'AL',
   'teknik_gostergeler':doc,'canli_guncelleme':when.isoformat(),'makro_sektor':'TEKNOLOJI'}
 def final(self,row,current,mode):row['nihai_karar']={'karar':'AL','confidence':90,'safety_flags':[],'updated_at':current.isoformat(),'zaman_dilimi':'DAILY','model_version':'FINAL_V1'}
 def pool(self,rows=None,score=None):
  with patch('pozitif_kapanis.attach_final_decision',side_effect=self.final):return build_pool(rows or [self.row()],self.now,len(rows or [1]),score or (lambda r:85))
 def signals(self,n=160):
  days=[];day=datetime(2026,9,1,19,tzinfo=ISTANBUL)
  while len(days)<8:
   if day.weekday()<5:days.append(day)
   day+=timedelta(days=1)
  records=[]
  for i in range(n):
   row=self.row(i,when=days[i%8]);self.final(row,days[i%8],'DAILY')
   raw,errors=closing_inputs(row,days[i%8].replace(hour=18,minute=10));self.final(raw,days[i%8],'DAILY')
   forecast=opportunity(raw,days[i%8].replace(hour=18,minute=10),[],85)
   rank=i//8+1;forecast.update(selection_rank=rank,baseline_rank=rank,shadow_rank=n//8-rank+1,rank=rank)
   value=3 if i<n//2 else -2
   result={'degerlendirme_tamamlandi':True,'observed_at':(days[i%8]+timedelta(days=3)).isoformat(),'durum':'BASARILI' if value>0 else 'STOP',
    'getiri_yuzde':value,'yon_getirisi':value,'ertesi_gun_acilis':100,'ertesi_gun_kapanis':100+value,'ertesi_gun_yuksek':105,'ertesi_gun_dusuk':98,
    'hedefe_ulasti':value>0,'stop_oldu':value<0,'maksimum_yukselis':5,'maksimum_dusus':-2,'mfe_pct':5,'mae_pct':-2,'kalite_uyarilari':[]}
   records.append({'kayit_id':'P'+str(i),'model':'POSITIVE_CANDIDATE','performance_source':'LIVE','sembol':row['sembol'],'zaman':days[i%8].isoformat(),'karar':'AL',
    'fiyat':100,'hedef':110,'stop':95,'confidence':60,'sektor':'TEKNOLOJI','piyasa_rejimi':'YUKSELIS','kriterler':raw,'teknik_gostergeler':raw['teknik_gostergeler'],
    'criteria_snapshot':forecast['criteria_snapshot'],'positive_opportunity':forecast,'model_version':MODEL,**{'sonuc_'+str(h)+'g':copy.deepcopy(result) for h in (1,3,5)}})
  return records
 def test_all_positive_no_cap(self):
  rows=[self.row(i,.1) for i in range(280)];pool=self.pool(rows)
  self.assertEqual((pool['positive_count'],pool['analyzed_count']),(280,280));self.assertEqual(len(pool['adaylar']),280)
 def test_small_positive_movements_not_filtered(self):
  pool=self.pool([self.row(i,n) for i,n in enumerate((.001,.1,.5,1,2))]);self.assertEqual(pool['analyzed_count'],5)
 def test_zero_negative_excluded(self):
  pool=self.pool([self.row(i,n) for i,n in enumerate((0,-1,-7,1))]);self.assertEqual(pool['positive_count'],1)
 def test_rounded_zero_but_true_positive_kept(self):
  row=self.row(change=.001);row['degisim']=0;self.assertEqual(self.pool([row])['analyzed_count'],1)
 def test_today_return_does_not_rank(self):
  fast=self.row(1,6.8);fast.update(rsi=69,hacim_orani=70,direnc=100.5);fast['teknik_gostergeler']['momentum'].update(acceleration=-1,positive_turn=False)
  modest=self.row(2,1.2);pool=self.pool([fast,modest]);self.assertEqual(pool['adaylar'][0]['sembol'],'S2')
 def test_expected_returns_three_horizons_and_method(self):
  f=self.pool()['adaylar'][0]['positive_opportunity']
  for k in ('expected_return_next_session','expected_return_3d','expected_return_5d'):self.assertIsInstance(f[k],float)
  self.assertEqual(f['expected_return_method']['1'],'TECHNICAL_SCENARIO_UNCALIBRATED');self.assertFalse(f['probability_calibrated'])
 def test_historical_estimate_requires_sample_days(self):
  records=self.signals();row=self.row();flags=evidence_features(records[0],'DAILY')
  self.assertIsNotNone(historical_expectation(row,flags,records,self.cutoff,1));self.assertIsNone(historical_expectation(row,flags,records[:20],self.cutoff,1))
 def test_future_outcomes_do_not_affect_forecast(self):
  records=self.signals();row=self.row();flags=evidence_features(records[0],'DAILY');before=historical_expectation(row,flags,records,self.cutoff,1)
  future=copy.deepcopy(records)
  for r in future:
   r['kayit_id']='F'+r['kayit_id'];r['sembol']='F'+r['sembol'];r['sonuc_1g'].update(observed_at=(self.now+timedelta(days=1)).isoformat(),getiri_yuzde=999)
  self.assertEqual(historical_expectation(row,flags,records+future,self.cutoff,1),before)
 def test_probability_score_range(self):
  f=self.pool()['adaylar'][0]['positive_opportunity'];self.assertTrue(0<=f['continuation_probability']<=100)
 def test_early_move_score(self):
  row=self.row();f=self.pool([row])['adaylar'][0]['positive_opportunity'];row['teknik_gostergeler']['closing']['volume_acceleration']=-1
  row['teknik_gostergeler']['momentum']['positive_turn']=False;lower=self.pool([row])['adaylar'][0]['positive_opportunity'];self.assertLess(lower['early_move_score'],f['early_move_score'])
 def test_sustainability_score(self):
  a=self.pool()['adaylar'][0]['positive_opportunity'];row=self.row();row.update(hacim_orani=50,rsi=69)
  b=self.pool([row])['adaylar'][0]['positive_opportunity'];self.assertLess(b['move_sustainability_score'],a['move_sustainability_score'])
 def test_extended_move_penalty(self):
  high=self.pool([self.row(change=6.8)])['adaylar'][0]['positive_opportunity'];small=self.pool()['adaylar'][0]['positive_opportunity'];self.assertGreater(high['extended_move_penalty'],small['extended_move_penalty'])
 def test_opportunity_components_weights(self):
  f=self.pool()['adaylar'][0]['positive_opportunity'];self.assertAlmostEqual(sum(f['weights'].values()),1);self.assertTrue(0<=f['future_opportunity_score']<=100);self.assertIn('news',f['components'])
 def test_top10_top30_top50_all_trace(self):
  pool=self.pool([self.row(i) for i in range(80)]);self.assertEqual(len(pool['eligible_symbols'][:10]),10);self.assertEqual(len(pool['eligible_symbols'][10:30]),20)
  self.assertEqual(len(pool['eligible_symbols'][:50]),50);self.assertEqual(len(pool['adaylar']),80)
 def test_reason_and_risk_fields(self):
  f=self.pool()['adaylar'][0]['positive_opportunity']
  for key in ('rank','symbol','current_return','future_opportunity_score','expected_return','continuation_probability','early_move_score','sustainability_score','confidence','risk','technical_strength','reasons','risks','model_version','neden_bu_sirada','neden_daha_asagida'):self.assertIn(key,f)
 def test_hard_overextension_cannot_pass(self):self.assertFalse(self.pool([self.row(change=7.5)])['adaylar'][0]['positive_opportunity']['eligible'])
 def test_rr_safety(self):
  row=self.row();row.update(karar_rr=.5,risk_getiri=.5);self.assertIn('LOW_RISK_REWARD',self.pool([row])['adaylar'][0]['positive_opportunity']['selection_blocks'])
 def test_stop_safety(self):
  row=self.row();row['karar_stop']=101;self.assertFalse(self.pool([row])['adaylar'][0]['positive_opportunity']['eligible'])
 def test_critical_news_provenance_cannot_be_ignored(self):
  row=self.row();row['haber_puani']=-8;f=self.pool([row])['adaylar'][0]['positive_opportunity'];self.assertIn('UNVERIFIED_CRITICAL_NEWS',f['selection_blocks'])
 def test_final_ai_block_wins(self):
  def blocked(row,current,mode):self.final(row,current,mode);row['nihai_karar']['safety_flags']=['KRITIK_HABER']
  with patch('pozitif_kapanis.attach_final_decision',side_effect=blocked):pool=build_pool([self.row()],self.now,1,lambda r:95)
  self.assertFalse(pool['eligible_symbols'])
 def test_stale_price_rejected(self):
  row=self.row();row['teknik_gostergeler']['data_time']=(self.cutoff-timedelta(days=1)).isoformat();self.assertEqual(self.pool([row])['analyzed_count'],0)
 def test_liquidity_rejected(self):
  row=self.row();row['teknik_gostergeler']['closing']['turnover_tl']=100;self.assertEqual(self.pool([row])['analyzed_count'],0)
 def test_future_price_mismatch_rejected(self):
  row=self.row();row['fiyat']=120;self.assertIn('CLOSE_PRICE_MISMATCH',self.pool([row])['rejected'][0]['filters'])
 def test_missing_data_rejected(self):
  row=self.row();row.pop('atr14');self.assertEqual(self.pool([row])['analyzed_count'],0)
 def test_only_after_close_and_not_weekend(self):
  with self.assertRaises(ValueError):build_pool([self.row()],self.now.replace(hour=12),1,lambda r:85)
  with self.assertRaises(ValueError):build_pool([self.row()],datetime(2026,10,10,19,tzinfo=ISTANBUL),1,lambda r:85)
 def test_input_not_mutated(self):
  row=self.row();before=copy.deepcopy(row);self.pool([row]);self.assertEqual(row,before)
 def test_future_news_market_macro_excluded(self):
  row=self.row();row.update(haber_puani=10,makro_puani=10,makro_asof=(self.now+timedelta(days=1)).isoformat(),haber_katkilari=[{'observed_at':self.now.isoformat()}],piyasa_baglami={'updated_at':self.now.isoformat()})
  raw,errors=closing_inputs(row,self.cutoff);self.assertIsNone(raw['haber_puani']);self.assertIsNone(raw['makro_puani']);self.assertEqual(raw['piyasa_baglami'],{})
 def test_future_news_cannot_contaminate_old_event_aggregate(self):
  row=self.row();row.update(haber_puani=10,haber_guven=100,haber_fiyat_teyidi=100,haber_asof=self.now.isoformat(),haber_katkilari=[
   {'observed_at':self.cutoff.isoformat(),'etki':2},{'observed_at':self.now.isoformat(),'etki':8}])
  raw,errors=closing_inputs(row,self.cutoff);self.assertEqual(raw['haber_puani'],2);self.assertEqual(len(raw['haber_katkilari']),1)
  self.assertIsNone(raw['haber_guven']);self.assertIsNone(raw['haber_fiyat_teyidi'])
 def test_standard_closing_summary_uses_only_closed_bars(self):
  index=pd.date_range('2026-07-01',periods=71,freq='B',tz=ISTANBUL);close=pd.Series(range(100,171),index=index,dtype=float)
  frame=pd.DataFrame({'Close':close,'Open':close-1,'High':close+2,'Low':close-2,'Volume':20000},index=index)
  at=index[-2].replace(hour=18,minute=15);doc=calculate(frame,at,'TOMORROW');baseline=calculate(frame.iloc[:-1],at,'TOMORROW')
  self.assertEqual(doc,baseline);self.assertEqual(doc['closing']['close'],169);self.assertIsNotNone(doc['closing']['ema9'])
 def test_all_three_outcome_horizons(self):
  records=self.signals()
  for h in (1,3,5):self.assertEqual(len(continuation_pairs(records,self.now,h)),160)
 def test_continued_failed_neutral(self):
  records=self.signals(3)
  for r,value in zip(records,(3,-2,0)):r['sonuc_1g']['getiri_yuzde']=value
  self.assertEqual({o['continuation_class'] for r,o,f in continuation_pairs(records,self.now,1)},{'CONTINUED','FAILED_CONTINUATION','NEUTRAL'})
 def test_ambiguous_trade_does_not_hide_known_close(self):
  records=self.signals(1);records[0]['sonuc_1g'].update(ilk_temas='BELIRSIZ',kalite_uyarilari=['TEMAS_SIRASI_BELIRSIZ'],durum='VERI_YETERSIZ')
  self.assertEqual(len(continuation_pairs(records,self.now,1)),1)
 def test_missing_ohlc_not_in_outcome(self):
  records=self.signals(1);records[0]['sonuc_1g'].pop('ertesi_gun_yuksek');self.assertFalse(continuation_pairs(records,self.now,1))
 def test_capture_recall_precision_fpr(self):
  pairs=continuation_pairs(self.signals(),self.now);result=capture_metrics(pairs)['top'];self.assertEqual(result['10']['winner_recall'],1);self.assertEqual(result['10']['precision'],1)
  self.assertEqual(result['30']['precision'],.5);self.assertEqual(result['30']['false_positive_rate'],1);self.assertEqual(result['10']['false_positive_rate'],0);self.assertEqual(result['50']['capture_rate'],1)
 def test_incomplete_cohort_cannot_claim_capture(self):
  records=self.signals();records[0]['sonuc_1g']=None;report=continuation_report(records,self.now,1)
  self.assertFalse(report['daily'][records[0]['zaman'][:10]]['complete']);self.assertIsNone(report['daily'][records[0]['zaman'][:10]]['capture']['top']['10']['capture_rate'])
 def test_rank_buckets(self):
  report=continuation_report(self.signals(400),self.now,1);self.assertEqual(set(report['rank_buckets']),{'1-5','6-10','11-20','21-30','31-50'})
  self.assertEqual(report['rank_buckets']['31-50']['sample_count'],160)
 def test_expected_return_calibration(self):
  records=self.signals()
  for r in records:r['positive_opportunity']['expected_return_next_session']=2.5
  b=continuation_report(records,self.now,1)['expected_return_calibration']['2-3'];self.assertEqual(b['sample_count'],160);self.assertIsNotNone(b['prediction_error'])
 def test_probability_calibration(self):
  records=self.signals()
  for r in records:r['positive_opportunity']['continuation_probability']=75
  b=continuation_report(records,self.now,1)['probability_calibration']['70-80'];self.assertEqual(b['actual_continuation_rate'],.5);self.assertEqual(b['calibration_error'],-.25)
 def test_risk_calibration(self):
  records=self.signals()
  for r in records:r['positive_opportunity']['risk']='ORTA'
  b=continuation_report(records,self.now,1)['risk_calibration']['ORTA'];self.assertEqual(b['median_mae'],-2);self.assertEqual(b['median_range_pct'],7)
 def test_regime_sector_profiles(self):
  r=continuation_report(self.signals(),self.now,1);self.assertIn('YUKSELIS',r['regime_sector_profiles']['piyasa_rejimi']);self.assertIn('TEKNOLOJI',r['regime_sector_profiles']['sektor'])
 def test_small_sector_sample_no_rule(self):
  r=continuation_report(self.signals(10),self.now,1);self.assertIsNone(r['regime_sector_profiles']['sektor']['TEKNOLOJI']['success_rate'])
 def test_pattern_windows_existing_combinations(self):
  report=continuation_report(self.signals(),self.now,1);self.assertEqual(set(report['patterns']),{'5','20','60'});self.assertIn('combinations',report['patterns']['60'])
 def test_shadow_comparison_separate_rankings(self):
  report=continuation_report(self.signals(),self.now,1);self.assertEqual(report['ranking_comparison']['selection_rank']['success_rate'],1);self.assertEqual(report['ranking_comparison']['shadow_rank']['success_rate'],0)
 def test_missed_winner_private_error_log(self):
  records=self.signals()
  for r in records:r['positive_opportunity']['selection_rank']=20;r['positive_opportunity']['selection_blocks']=['QUALITY_THRESHOLD']
  report=publish_performance(self.paths,records,self.now);self.assertEqual(report['missed_winner_count'],80)
  private=json.loads((self.paths.runtime/'karar_hata_gunlugu.json').read_text());self.assertIn('POSITIVE_DAILY',private['modes']);self.assertEqual(next(iter(private['modes']['POSITIVE_DAILY'].values()))['failure_type'],'MISSED_WINNER')
 def test_learning_still_disabled(self):self.assertFalse(self.pool()['learning_enabled']);self.assertFalse(publish_performance(self.paths,self.signals(),self.now)['learning_enabled'])
 def test_public_report_http(self):
  from web_server import create_server
  publish_performance(self.paths,self.signals(),self.now);server=create_server('127.0.0.1',0,data_paths=self.paths)
  threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/data/pozitif_hisseler_performansi.json') as response:self.assertIn('1',json.load(response)['horizons'])
 def test_real_final_policy_not_mocked(self):
  pool=build_pool([self.row()],self.now,1,lambda r:85);self.assertEqual(pool['adaylar'][0]['nihai_karar']['karar'],'AL');self.assertTrue(pool['eligible_symbols'])
 def test_pool_control_signals_do_not_feed_main_ai(self):
  from ai_karar_motoru import history_context
  records=self.signals();past,info=history_context(records,self.row(),'YUKSELIS',self.now)
  self.assertEqual(info['ornek'],0)
 def test_cached_reports_skip_repeated_statistics(self):
  records=self.signals();publish_performance(self.paths,records,self.now)
  with patch('pozitif_kapanis.continuation_report',side_effect=AssertionError('No repeat aggregation')):publish_performance(self.paths,records,self.now+timedelta(minutes=1))
 def test_future_signals_not_published_as_current_day(self):
  records=self.signals()
  for r in records:r['zaman']=(self.now+timedelta(days=1)).isoformat()
  self.assertIsNone(publish_performance(self.paths,records,self.now))
 def test_cached_market_news_macro_sources_are_time_bounded(self):
  row=self.row();previous={'updated_at':(self.cutoff-timedelta(minutes=1)).isoformat(),'confidence':80,'haber_katkilari':[{'canonical_id':'K','etki':2,'teyit_edildi':True}]}
  atomic_json(self.paths.public/'ai_hisse_ozetleri.json',{'hisseler':{'S0':previous}})
  atomic_json(self.paths.public/'makro_canli_etki.json',{'updated_at':self.now.isoformat(),'hisseler':{'S0':{'makro_puani':10}}})
  enrich_closing_sources([row],self.paths,self.cutoff);raw,quality=closing_inputs(row,self.cutoff)
  self.assertEqual(raw['haber_puani'],2);self.assertIsNone(raw.get('makro_puani'));self.assertTrue(raw['haber_katkilari'])
 def test_snapshot_pool_freeze_and_no_same_day_overwrite(self):
  import bist_bot
  class Frozen(datetime):
   @classmethod
   def now(cls,tz=None):return self.now
  with patch.object(bist_bot,'datetime',Frozen),patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.paths.public/'yarin_top10.json')),patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.paths.archives)):
   snapshot=bist_bot.yarin_top10_kilitli_kaydet([self.row(i) for i in range(60)],60,pozitif_kapanis=True)
   self.assertIsNotNone(snapshot);self.assertEqual(len(snapshot['pozitif_havuz']['adaylar']),60);self.assertEqual(len(snapshot['top10']),10)
   path=self.paths.archives/'2026-10-06.json';before=path.read_bytes()
   later=bist_bot.yarin_top10_kilitli_kaydet([self.row(change=7.5)],1,pozitif_kapanis=True)
   self.assertEqual(path.read_bytes(),before);self.assertEqual(snapshot,later)
   engine=PerformansMotoru(self.paths,clock=lambda:self.now,history_provider=Mock(return_value=[]));records=engine.snapshot_records({})
   positive=[r for r in records if r['model']=='POSITIVE_CANDIDATE'];self.assertEqual(len(positive),60);self.assertTrue(all(r['analysis_only'] for r in positive))
   frozen=copy.deepcopy(snapshot)
   for row in records:row['sonuc_1g']={'getiri_yuzde':99}
   self.assertEqual(snapshot,frozen);self.assertEqual(path.read_bytes(),before)
 def test_pending_positive_five_horizons_and_bounded_provider(self):
  rows=self.signals(12)
  for r in rows:
   for h in (1,3,5):r['sonuc_'+str(h)+'g']=None
  atomic_json(self.paths.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':rows});provider=Mock(return_value=[])
  result=PerformansMotoru(self.paths,clock=lambda:self.now,history_provider=provider,batch_size=2).one_round();self.assertEqual(provider.call_count,2)
  history=json.loads(self.paths.runtime_file('ai_ogrenme_gecmisi.json').read_text())['kayitlar'];self.assertTrue(any('sonuc_2g' in r and 'sonuc_10g' in r for r in history));self.assertTrue(all('sonuc_20g' not in r for r in history))
 def test_worker_closing_cache_resume_and_skip_existing_archive(self):
  from ana_motor_gorevleri import WorkerTasks
  with patch('ana_motor_gorevleri.istanbul_now',return_value=self.now):
   worker=WorkerTasks();self.addCleanup(worker.close);worker.batch_size=2
   symbols=['S0','S1','S2','S3'];cached={s:self.row(i) for i,s in enumerate(symbols[:2])}
   atomic_json(self.paths.runtime/'pozitif_kapanis_tarama.json',{'date':self.now.date().isoformat(),'symbols':symbols,'rows':cached})
   with patch.object(worker.bot,'bist_hisseleri_getir',return_value=symbols),patch.object(worker.live,'tek_hisse_guncelle',side_effect=lambda s:(s,self.row(int(s[1:])))) as provider,patch.object(worker.bot,'yarin_top10_kilitli_kaydet',return_value={'top10':[]}) as freeze,patch.object(worker,'ai_context',return_value={}):
    self.assertEqual(worker.tomorrow(),4);self.assertEqual(provider.call_count,2);self.assertTrue(freeze.call_args.kwargs['pozitif_kapanis'])
    atomic_json(self.paths.archives/'2026-10-06.json',{'immutable':True});self.assertEqual(worker.tomorrow(),0);self.assertEqual(provider.call_count,2)
 def test_session_vwap_reuses_only_preclose_intraday_cache(self):
  row=self.row();doc={'mode':'INTRADAY','asof':self.cutoff.isoformat(),'data_time':(self.cutoff-timedelta(minutes=5)).isoformat(),'stale':False,
   'vwap':{'status':'OK','confidence':100,'session_value':99,'position':'VWAP_USTU','transition':'VWAP_RECLAIM'}}
  atomic_json(self.paths.public/'gun_ici_tum.json',{'hisseler':[{'sembol':'S0','teknik_gostergeler':doc}]})
  enrich_closing_sources([row],self.paths,self.cutoff);self.assertEqual(row['teknik_gostergeler']['vwap']['session_value'],99)
  self.assertEqual(row['teknik_gostergeler']['vwap']['source_mode'],'INTRADAY')
  other=self.row();doc['asof']=self.now.isoformat();atomic_json(self.paths.public/'gun_ici_tum.json',{'hisseler':[{'sembol':'S0','teknik_gostergeler':doc}]})
  enrich_closing_sources([other],self.paths,self.cutoff);self.assertEqual(other['teknik_gostergeler']['vwap']['status'],'UNKNOWN')
