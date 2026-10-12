import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from veri_yollari import DataPaths
from ai_karar_motoru import HORIZONS,ISTANBUL
from kullanici_kayitlari import atomic_json
from performans_motoru import PerformansMotoru,outcome,sessions_after

class MemoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
  self.path=self.location.runtime_file('tahmin_gecmisi.json')
  self.start=datetime(2026,10,2,18,30,tzinfo=ISTANBUL)
  self.days=sessions_after(self.start.date(),60,lambda d:False)
  self.bars=[{'date':d.isoformat(),'open':100,'high':110,'low':90,'close':105,'complete':True} for d in self.days]
  self.row={'id':'legacy1','sembol':'THYAO','tarih':self.start.isoformat(),'sinyal':'AGRESIF_ALIS','fiyat':100,'hedef1':120,'stop':80,'custom':{'keep':[1,2]}}
 def save(self,row=None):atomic_json(self.path,{'tahminler':[copy.deepcopy(row or self.row)],'ogrenme_gecmisi':[{'keep':True}]})
 def read(self):return json.loads(self.path.read_text())
 def motor(self,day,bars=None):
  return PerformansMotoru(self.location,clock=lambda:datetime.combine(day,datetime.min.time(),ISTANBUL).replace(hour=19),
      history_provider=lambda s:self.bars if bars is None else bars,holiday=lambda d:False)
 def test_all_six_horizons_and_frozen_base(self):
  self.save();before=copy.deepcopy(self.row);self.motor(self.days[-1]).one_round();row=self.read()['tahminler'][0]
  for h in HORIZONS:
   result=row['sonuc_'+str(h)+'g'];self.assertTrue(result['degerlendirme_tamamlandi'])
   self.assertEqual(result['getiri_yuzde'],5);self.assertEqual(result['tarih'],self.days[h-1].isoformat());self.assertEqual(row['takip'][str(h)]['status'],'COMPLETED')
  for key,value in before.items():self.assertEqual(row[key],value)
  self.assertEqual(self.read()['ogrenme_gecmisi'],[{'keep':True}])
 def test_pending_and_restart_resume_independent_horizons(self):
  self.save();self.motor(self.days[0]).one_round();first=self.read()['tahminler'][0]
  self.assertEqual(first['takip']['1']['status'],'COMPLETED')
  for h in HORIZONS[1:]:self.assertEqual(first['takip'][str(h)]['status'],'PENDING')
  completed=copy.deepcopy(first['sonuc_1g']);self.motor(self.days[4]).one_round();later=self.read()['tahminler'][0]
  self.assertEqual(later['sonuc_1g'],completed);self.assertEqual(later['takip']['5']['status'],'COMPLETED');self.assertEqual(later['takip']['60']['status'],'PENDING')
 def test_missing_day_does_not_slide_horizon(self):
  self.save();self.motor(self.days[3],self.bars[1:]).one_round();row=self.read()['tahminler'][0]
  self.assertFalse(row['sonuc_1g']['degerlendirme_tamamlandi']);self.assertEqual(row['takip']['1']['status'],'PENDING')
  self.motor(self.days[4]).one_round();self.assertEqual(self.read()['tahminler'][0]['takip']['1']['status'],'COMPLETED')
 def test_weekend_and_holiday_skip(self):
  self.assertEqual(self.days[0].isoformat(),'2026-10-05')
  dates=sessions_after(self.start.date(),1,lambda d:d.isoformat()=='2026-10-05');self.assertEqual(dates[0].isoformat(),'2026-10-06')
 def test_mfe_mae_and_lookahead(self):
  result=outcome(dict(self.row,zaman=self.row['tarih']),self.bars,1,self.start+timedelta(days=100),holiday=lambda d:False)
  later=copy.deepcopy(self.bars);later[-1].update(high=99999,low=1)
  self.assertEqual(result,outcome(dict(self.row,zaman=self.row['tarih']),later,1,self.start+timedelta(days=100),holiday=lambda d:False))
  self.assertEqual(result['mfe_pct'],10);self.assertEqual(result['mae_pct'],-10)
 def test_old_completed_outcome_preserved_and_labelled_unverified(self):
  row=dict(self.row,sonuc_1g={'fiyat':99,'tarih':'2026-10-05','getiri_yuzde':123,'unique':'KEEP'})
  self.save(row);self.motor(self.days[4]).one_round();saved=self.read()['tahminler'][0]
  self.assertEqual(saved['sonuc_1g'],row['sonuc_1g']);self.assertTrue(saved['takip']['1']['legacy_unverified'])
 def test_neutral_old_history_preserved_without_new_tracking(self):
  row=dict(self.row,sinyal='NOTR');self.save(row);before=self.path.read_bytes();self.motor(self.days[4]).one_round();self.assertEqual(self.path.read_bytes(),before)
 def test_missing_reference_price_not_zero_or_completed(self):
  row=dict(self.row,fiyat=None);self.save(row);self.motor(self.days[4]).one_round();saved=self.read()['tahminler'][0]
  self.assertIsNone(saved['fiyat']);self.assertEqual(saved['takip']['1']['status'],'PENDING');self.assertFalse(saved['sonuc_1g']['degerlendirme_tamamlandi'])
 def test_repeat_round_preserves_complete_result(self):
  self.save();motor=self.motor(self.days[-1]);motor.one_round();before=self.path.read_bytes();self.motor(self.days[-1]).one_round();self.assertEqual(self.path.read_bytes(),before)

 def test_missing_ohlc_remains_pending_without_excursions(self):
  self.save();bars=copy.deepcopy(self.bars);bars[0]['high']=None
  self.motor(self.days[0],bars).one_round();row=self.read()['tahminler'][0]
  self.assertEqual(row['takip']['1']['status'],'PENDING');self.assertEqual(row['sonuc_1g']['neden'],'OHLC_EKSIK')
  self.assertIsNone(row['sonuc_1g'].get('mfe_pct'));self.assertIsNone(row['sonuc_1g'].get('mae_pct'))
 def test_source_and_signal_summaries_do_not_copy_history(self):
  self.save();self.motor(self.days[-1]).one_round()
  report=json.loads(self.location.public_file('performans_ozeti.json').read_text())['tahmin_hafizasi']
  self.assertEqual(set(report['vadeler']),{'1','3','5','10','20','60'})
  self.assertIn('AGRESIF_ALIS',report['sinyaller']);self.assertIn('GUNLUK_TARAMA',report['kaynaklar'])
  history=json.loads(self.location.runtime_file('ai_ogrenme_gecmisi.json').read_text())
  self.assertFalse(any(r.get('model')=='TAHMIN_HAFIZASI' for r in history['kayitlar']))

class CaptureTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'history.json'
 def capture(self,signal,source='GUNLUK_TARAMA'):
  import bist_bot
  with patch.object(bist_bot,'sinyal_sinifi',return_value=signal),patch.object(bist_bot,'guclu_tepki_mi',return_value=False):
   return bist_bot.tahminleri_kaydet([{'sembol':'THYAO','fiyat':100,'puan':80}],1,kaynak=source,liste_kaydet=False,dosya_yolu=self.path)
 def test_neutral_not_saved_and_daily_duplicate_blocked(self):
  self.assertTrue(self.capture('NOTR'));self.assertEqual(json.loads(self.path.read_text())['tahminler'],[])
  self.assertTrue(self.capture('AGRESIF_ALIS'));self.assertTrue(self.capture('AGRESIF_ALIS'))
  self.assertEqual(len(json.loads(self.path.read_text())['tahminler']),1)
 def test_different_signal_and_source_are_not_duplicates(self):
  self.capture('AGRESIF_ALIS');self.capture('AGRESIF_SATIS');self.capture('AGRESIF_ALIS','DIFFERENT_SOURCE')
  rows=json.loads(self.path.read_text())['tahminler'];self.assertEqual(len(rows),3);self.assertEqual(len({r['id'] for r in rows}),3)
  self.assertEqual(set(rows[0]['takip']),{'1','3','5','10','20','60'})
 def test_corrupt_source_is_not_replaced_by_empty_history(self):
  self.path.write_bytes(b'{broken');self.assertFalse(self.capture('AGRESIF_ALIS'));self.assertEqual(self.path.read_bytes(),b'{broken')

 def test_existing_daily_decision_is_captured_without_reranking(self):
  import bist_bot
  with patch.object(bist_bot,'sinyal_sinifi',return_value='NOTR'),patch.object(bist_bot,'guclu_tepki_mi',return_value=False),patch.object(bist_bot,'yarin_top10_listesi') as rank:
   bist_bot.tahminleri_kaydet([{'sembol':'THYAO','fiyat':100,'karar':'AL','guven_skoru':74}],1,liste_kaydet=False,dosya_yolu=self.path)
   rank.assert_not_called()
  row=json.loads(self.path.read_text())['tahminler'][0]
  self.assertEqual(row['sinyal'],'AL');self.assertEqual(row['guven'],74)
 def test_concurrent_duplicate_writers_keep_one_frozen_record(self):
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.capture('AGRESIF_ALIS'),range(8)))
  self.assertTrue(all(results));rows=json.loads(self.path.read_text())['tahminler'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['fiyat'],100)
 def test_storage_failure_propagates_for_worker_classification(self):
  import bist_bot
  with patch.object(bist_bot,'sinyal_sinifi',return_value='AGRESIF_ALIS'),patch.object(bist_bot,'guclu_tepki_mi',return_value=False),patch('kullanici_kayitlari.atomic_json',side_effect=OSError(28,'No space left on device')):
   with self.assertRaises(OSError) as error:bist_bot.tahminleri_kaydet([{'sembol':'THYAO','fiyat':100}],1,liste_kaydet=False,dosya_yolu=self.path,strict=True)
  self.assertEqual(error.exception.errno,28);self.assertFalse(self.path.exists())

 def test_neutral_common_ai_is_visible_without_history_growth(self):
  from ai_karar_motoru import AIKararMotoru
  location=DataPaths({'BIST_DATA_DIR':self.temp.name});location.ensure()
  now=datetime(2026,10,6,12,tzinfo=ISTANBUL)
  engine=AIKararMotoru(location,clock=lambda:now)
  result=engine.batch(['THYAO'],[{'sembol':'THYAO','fiyat':100,'teknik_puan':50,'canli_guncelleme':now.isoformat()}])
  self.assertEqual(result['hisseler']['THYAO']['karar'],'IZLE')
  self.assertEqual(json.loads(engine.history_path.read_text())['kayitlar'],[])
