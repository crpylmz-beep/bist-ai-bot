import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from ai_karar_motoru import HORIZONS,ISTANBUL
from kullanici_kayitlari import atomic_json
from veri_yollari import DataPaths
from performans_motoru import (PerformansMotoru,outcome,sessions_after,session_closed,
    session_end,propose_outcome_correction,OUTCOME_VERSION)
import top10_ogrenme_performansi as comparison


class AutoOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.at=datetime(2026,10,27,19,tzinfo=ISTANBUL)
        self.now=datetime(2027,3,1,19,tzinfo=ISTANBUL)
        self.days=sessions_after(self.at.date(),60)
        self.bars=[{'date':d.isoformat(),'open':100,'high':110,'low':98,'close':105,'complete':True} for d in self.days]
        self.rows=[]
        for name,model in comparison.MODELS.items():
            for rank in range(1,11):
                self.rows.append({'kayit_id':f'{name}-{rank}','snapshot_id':'frozen-day','snapshot_tarihi':'2026-10-27',
                    'sembol':f'S{rank}','zaman':self.at.isoformat(),'model':model,'fiyat':100,'hedef':120,'stop':95,
                    'karar':'AL','kaynak':'IMMUTABLE_YARIN_SNAPSHOT','tahmin_sirasi':rank,'egitim_durumu':'EGITIM',
                    'learning_version':'TOP10_INDICATOR_V2','learning_adjustment':1 if name=='LEARNED' else 0,
                    **{f'sonuc_{h}g':None for h in HORIZONS}})

    def seed(self,rows=None):atomic_json(self.location.runtime_file('ai_ogrenme_gecmisi.json'),{'kayitlar':rows or self.rows})
    def read(self):return json.loads(self.location.runtime_file('ai_ogrenme_gecmisi.json').read_bytes())['kayitlar']
    def engine(self,provider=None,batch_size=25):
        engine=PerformansMotoru(self.location,clock=lambda:self.now,history_provider=provider or Mock(return_value=self.bars),batch_size=batch_size)
        engine.reports=Mock();return engine

    def test_actual_bist_holidays_weekends_and_half_day_count_as_sessions(self):
        self.assertEqual([d.isoformat() for d in sessions_after(self.at.date(),3)],['2026-10-28','2026-10-30','2026-11-02'])
        self.assertEqual(sessions_after(datetime(2026,4,22).date(),1)[0].isoformat(),'2026-04-24')
        self.assertFalse(session_closed(datetime(2026,10,29).date(),self.now))
        self.assertFalse(session_closed(datetime(2026,10,31).date(),self.now))

    def test_half_day_closes_with_buffer_and_regular_day_boundary_is_preserved(self):
        half=datetime(2026,10,28,12,45,tzinfo=ISTANBUL)
        self.assertEqual(session_end(half.date()),half)
        self.assertFalse(session_closed(half.date(),half-timedelta(seconds=1)))
        self.assertTrue(session_closed(half.date(),half))
        regular=datetime(2026,10,30,18,15,tzinfo=ISTANBUL)
        self.assertFalse(session_closed(regular.date(),regular-timedelta(seconds=1)))
        self.assertTrue(session_closed(regular.date(),regular))
        self.assertIsNone(outcome(self.rows[0],self.bars,1,half-timedelta(seconds=1)))
        self.assertTrue(outcome(self.rows[0],self.bars,1,half)['degerlendirme_tamamlandi'])

    def test_worker_completes_all_six_horizons_and_pairs_share_price_evidence(self):
        self.seed();provider=Mock(return_value=self.bars);engine=self.engine(provider)
        engine.one_round();rows=self.read()
        self.assertEqual(len(rows),20);self.assertEqual(provider.call_count,10)
        for h in HORIZONS:
            for row in rows:
                value=row[f'sonuc_{h}g']
                self.assertTrue(value['degerlendirme_tamamlandi'])
                self.assertEqual(value['evaluation_version'],OUTCOME_VERSION)
                self.assertEqual(value['tarih'],self.days[h-1].isoformat())
                self.assertEqual(value['getiri_yuzde'],5)
                self.assertEqual(value['mfe_pct'],10)
                self.assertEqual(value['mae_pct'],-2)
            for stock in range(10):
                a=rows[stock][f'sonuc_{h}g'];b=rows[stock+10][f'sonuc_{h}g']
                self.assertEqual(a['price_data_digest'],b['price_data_digest'])
                self.assertEqual(a['price_source'],b['price_source'])
        stats=comparison.aggregate(rows,self.now)['horizons']
        for h in HORIZONS:
            self.assertEqual(stats[str(h)]['models']['BASE']['sample_count'],10)
            self.assertEqual(stats[str(h)]['differences_vs_base']['mean_return'],0)

    def test_missing_prices_retry_same_day_with_fresh_cache(self):
        self.now=datetime(2026,10,28,13,tzinfo=ISTANBUL)
        self.seed(self.rows[:1]);provider=Mock(side_effect=[[],self.bars]);engine=self.engine(provider)
        engine.one_round()
        self.assertFalse(self.read()[0]['sonuc_1g']['degerlendirme_tamamlandi'])
        self.now+=timedelta(hours=1);engine.one_round();self.assertEqual(provider.call_count,1)
        self.now+=timedelta(hours=5);engine.one_round()
        self.assertEqual(provider.call_count,2)
        self.assertTrue(self.read()[0]['sonuc_1g']['degerlendirme_tamamlandi'])

    def test_sealed_results_do_not_change_or_duplicate_on_reruns(self):
        self.seed();provider=Mock(return_value=self.bars);engine=self.engine(provider);engine.one_round()
        before=copy.deepcopy(self.read())
        self.now+=timedelta(days=1);provider.side_effect=AssertionError('completed results refetched')
        result=engine.one_round()
        self.assertEqual(result['tamamlanan_vade'],0)
        self.assertEqual(self.read(),before)

    def test_late_counterpart_reuses_original_evidence_without_new_quote(self):
        self.seed(self.rows[:10]);provider=Mock(return_value=self.bars);engine=self.engine(provider);engine.one_round()
        first=self.read();self.now+=timedelta(days=1)
        atomic_json(engine.history_path,{'kayitlar':first+copy.deepcopy(self.rows[10:])})
        provider.side_effect=AssertionError('paired evidence already frozen')
        result=engine.one_round()
        self.assertEqual(result['hatalar'],{})
        rows=self.read()
        for h in HORIZONS:
            self.assertEqual(rows[0][f'sonuc_{h}g']['price_data_digest'],rows[10][f'sonuc_{h}g']['price_data_digest'])
            self.assertEqual(rows[0][f'sonuc_{h}g']['observed_at'],rows[10][f'sonuc_{h}g']['observed_at'])

    def test_stale_unverified_incomplete_and_conflicting_prices_do_not_complete(self):
        for kind in ('stale','unverified','incomplete','conflict','missing','boolean'):
            bars=copy.deepcopy(self.bars)
            if kind=='stale':bars[0]['stale']=True
            if kind=='unverified':bars[0]['unverified']=True
            if kind=='incomplete':bars[0]['complete']=False
            if kind=='conflict':bars.append(dict(bars[0],close=106))
            if kind=='missing':bars.pop(0)
            if kind=='boolean':bars[0]['close']=True
            with self.subTest(kind=kind):self.assertFalse(outcome(self.rows[0],bars,1,self.now)['degerlendirme_tamamlandi'])

    def test_data_corrections_are_versioned_proposals_and_original_stays_sealed(self):
        row=copy.deepcopy(self.rows[0]);row['sonuc_1g']=outcome(row,self.bars,1,self.now,price_source='PROVIDER')
        original=copy.deepcopy(row['sonuc_1g']);bars=copy.deepcopy(self.bars);bars[0]['close']=106
        a=propose_outcome_correction(row,1,bars,self.now,'Provider corrected close','PROVIDER')
        b=propose_outcome_correction(row,1,bars,self.now+timedelta(hours=1),'Provider corrected close','PROVIDER')
        self.assertEqual(a,b);self.assertEqual(len(row['outcome_corrections']),1)
        bars[0]['close']=107
        c=propose_outcome_correction(row,1,bars,self.now,'Second correction','PROVIDER')
        self.assertEqual(c['version'],2);self.assertEqual(c['status'],'PROPOSED')
        self.assertEqual(row['sonuc_1g'],original)
        with self.assertRaises(ValueError):propose_outcome_correction(row,1,[],self.now,'Missing data','PROVIDER')

    def test_comparison_rejects_different_provider_rules_or_price_windows(self):
        self.seed();engine=self.engine();engine.one_round();rows=self.read()
        for field in ('price_source','price_data_digest','evaluation_version'):
            changed=copy.deepcopy(rows);changed[0]['sonuc_1g'][field]='different'
            stats=comparison.aggregate(changed,self.now)['horizons']['1']
            with self.subTest(field=field):
                self.assertEqual(stats['models']['BASE']['sample_count'],0)
                self.assertEqual(stats['display_status'],'YETERSİZ VERİ')

    def test_short_horizon_does_not_use_later_unreliable_bars(self):
        bars=copy.deepcopy(self.bars);bars[-1]['stale']=True
        self.assertTrue(outcome(self.rows[0],bars,1,self.now)['degerlendirme_tamamlandi'])
        self.assertFalse(outcome(self.rows[0],bars,60,self.now)['degerlendirme_tamamlandi'])

    def test_available_sealed_horizon_is_reused_when_longer_quote_request_fails(self):
        self.now=datetime(2026,10,28,13,tzinfo=ISTANBUL)
        self.seed(self.rows[:1]);provider=Mock(return_value=self.bars);engine=self.engine(provider);engine.one_round()
        first=self.read();self.now=datetime(2026,11,2,19,tzinfo=ISTANBUL)
        atomic_json(engine.history_path,{'kayitlar':first+[copy.deepcopy(self.rows[10])]})
        provider.side_effect=RuntimeError('provider temporarily unavailable')
        engine.one_round();rows=self.read()
        self.assertTrue(rows[1]['sonuc_1g']['degerlendirme_tamamlandi'])
        self.assertEqual(rows[0]['sonuc_1g']['price_data_digest'],rows[1]['sonuc_1g']['price_data_digest'])
        self.assertIsNone(rows[1]['sonuc_3g'])

    def test_unverified_sealed_counterpart_is_not_reused(self):
        self.seed(self.rows[:1]);engine=self.engine();engine.one_round();rows=self.read()
        for h in HORIZONS:rows[0][f'sonuc_{h}g']['unverified']=True
        rows[0]['sonuc_2g']['unverified']=True
        atomic_json(engine.history_path,{'kayitlar':rows+[copy.deepcopy(self.rows[10])]})
        self.now+=timedelta(days=1)
        provider=Mock(return_value=[]);self.engine(provider).one_round()
        rows=self.read()
        self.assertGreater(provider.call_count,0)
        self.assertFalse(rows[1]['sonuc_1g']['degerlendirme_tamamlandi'])

    def test_explicit_correction_persists_audit_without_altering_sealed_history(self):
        self.seed(self.rows[:1]);engine=self.engine();engine.one_round()
        before=copy.deepcopy(self.read());bars=copy.deepcopy(self.bars);bars[0]['close']=106
        proposal=engine.propose_correction(before[0]['kayit_id'],1,bars,'Verified provider correction')
        after=self.read()
        self.assertEqual(after[0]['outcome_corrections'][0],proposal)
        after[0].pop('outcome_corrections');self.assertEqual(after,before)
        engine.propose_correction(before[0]['kayit_id'],1,bars,'Verified provider correction')
        self.assertEqual(len(self.read()[0]['outcome_corrections']),1)
        with self.assertRaises(ValueError):engine.propose_correction('missing',1,bars,'Correction')

    def test_calendar_close_respects_utc_input_and_ramadan_eve(self):
        from datetime import timezone
        eve=datetime(2026,3,19,12,45,tzinfo=ISTANBUL)
        self.assertEqual(session_end(eve.date()),eve)
        self.assertTrue(session_closed(eve.date(),eve.astimezone(timezone.utc)))
        self.assertFalse(session_closed(eve.date(),(eve-timedelta(seconds=1)).astimezone(timezone.utc)))
        days=sessions_after(datetime(2026,3,18).date(),2)
        self.assertEqual(days[0],eve.date())
        self.assertGreater(days[1],datetime(2026,3,22).date())

    def test_worker_existing_report_api_contains_all_six_realized_metrics(self):
        self.seed()
        engine=PerformansMotoru(self.location,clock=lambda:self.now,history_provider=Mock(return_value=self.bars),batch_size=25)
        engine.one_round()
        for h in HORIZONS:
            result=comparison.api_report({'horizon':[str(h)]},self.location)
            stats=result['summary']
            self.assertEqual(stats['models']['BASE']['sample_count'],10)
            self.assertEqual(stats['models']['LEARNED']['median_return'],5)
            self.assertEqual(stats['differences_vs_base']['success_rate_percentage_points'],0)
            self.assertTrue(stats['models']['BASE']['risk']['complete'])
            self.assertEqual(stats['display_status'],'YETERSİZ VERİ')

    def test_paired_reuse_does_not_skip_quotes_for_existing_shadow_models(self):
        self.seed(self.rows[:1]);provider=Mock(return_value=self.bars);engine=self.engine(provider);engine.one_round()
        original=self.read();self.now+=timedelta(days=1)
        shadow=copy.deepcopy(self.rows[0]);shadow.update(kayit_id='shadow',model='YARIN_SHADOW')
        atomic_json(engine.history_path,{'kayitlar':original+[shadow]})
        bars=copy.deepcopy(self.bars)
        for bar in bars:bar['close']=106
        provider.return_value=bars;engine.one_round()
        rows=self.read()
        self.assertEqual(rows[1]['sonuc_1g']['getiri_yuzde'],6)
        self.assertEqual(rows[0]['sonuc_1g']['getiri_yuzde'],5)
        self.assertEqual(provider.call_count,2)
