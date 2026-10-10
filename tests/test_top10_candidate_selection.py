import copy
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from ai_karar_motoru import ISTANBUL
import bist_bot
import top10_aday_secimi as selection
from veri_yollari import DataPaths


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 19, tzinfo=ISTANBUL)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, {'BIST_DATA_DIR': self.temp.name,
                                                'TOP10_LEARNING_ENABLED': 'false'}))
        self.paths = DataPaths({'BIST_DATA_DIR': self.temp.name})
        self.paths.ensure()

    def row(self, symbol='AAA', score=80, **extra):
        return dict(sembol=symbol, fiyat=100, rsi=55, sma20=95, sma50=90,
                    macd=2, signal=1, hist=1, hacim_orani=180,
                    risk_getiri=2, degisim=1, atr14=2, old_score=score, **extra)

    def technical(self, mode='TOMORROW'):
        observed = self.now.replace(hour=18, minute=10) if mode == 'TOMORROW' else self.now
        return {'mode': mode, 'asof': self.now.isoformat(), 'data_time': observed.isoformat(),
                'stale': False, 'closing': {'close': 100, 'previous_close': 99,
                 'open': 99, 'high': 101, 'low': 98, 'turnover_tl': 20000000}}

    def ranking(self, rows, **extra):
        now = self.now
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        with ExitStack() as stack:
            stack.enter_context(patch.object(bist_bot, 'datetime', Clock))
            stack.enter_context(patch.object(bist_bot, 'yarin_potansiyel_hesapla', side_effect=lambda r:r['old_score']))
            stack.enter_context(patch('performans_motoru.controlled_context', return_value={}))
            stack.enter_context(patch('performans_motoru.controlled_score', return_value={}))
            stack.enter_context(patch('teknik_gostergeler.shadow', return_value={}))
            stack.enter_context(patch('piyasa_baglami.effects', return_value={'piyasa_baglami_etkisi':0}))
            stack.enter_context(patch('ai_karar_motoru.attach_final_decision'))
            for target, value in extra.items():
                stack.enter_context(patch(target, **value))
            return bist_bot.yarin_top10_listesi(rows, kalibrasyon={'learning_enabled':False},
                                               piyasa={}, learning_context={'status':'DISABLED'})

    def test_symbol_aliases_collapse_without_losing_other_stocks(self):
        rows = [self.row('BIST:aaa.IS'), self.row('AAA.E'), self.row('BBB')]
        self.assertEqual([r['sembol'] for r in selection.prepare_candidates(rows,self.now)], ['AAA','BBB'])

    def test_missing_or_invalid_symbols_rejected(self):
        for symbol in (None, '', '!', 123):
            with self.subTest(symbol=symbol):
                self.assertEqual(selection.prepare_candidates([dict(self.row(),sembol=symbol)],self.now), [])

    def test_freshest_valid_duplicate_wins_in_both_input_orders(self):
        old = self.row(score=90,canli_guncelleme=self.now.replace(hour=18,minute=20).isoformat())
        new = self.row(score=70,canli_guncelleme=self.now.isoformat())
        for rows in ([old,new], [new,old]):
            self.assertIs(selection.prepare_candidates(rows,self.now)[0],new)

    def test_invalid_duplicate_does_not_hide_valid_row(self):
        invalid = dict(self.row(), fiyat=float('nan'))
        for rows in ([invalid,self.row()], [self.row(),invalid]):
            self.assertEqual(len(selection.prepare_candidates(rows,self.now)),1)

    def test_duplicate_content_tie_is_input_order_independent(self):
        rows = [self.row(score=80),self.row(score=81)]
        a = selection.prepare_candidates(copy.deepcopy(rows),self.now)
        b = selection.prepare_candidates(copy.deepcopy(rows[::-1]),self.now)
        self.assertEqual(a,b)

    def test_nonfinite_and_missing_supplied_inputs_rejected(self):
        for key in selection.NUMERIC_INPUTS:
            for value in (None,float('nan'),float('inf'),float('-inf'),'broken'):
                with self.subTest(key=key,value=value):
                    self.assertFalse(selection.valid_candidate(dict(self.row(),**{key:value}),self.now))

    def test_zero_price_and_invalid_rsi_or_volume_rejected(self):
        for key,value in [('fiyat',0),('fiyat',-1),('fiyat',True),('rsi',101),('rsi',-1),('hacim_orani',-1),('sma20',0)]:
            self.assertFalse(selection.valid_candidate(dict(self.row(),**{key:value}),self.now))

    def test_legacy_without_provenance_remains_eligible(self):
        self.assertTrue(selection.valid_candidate(self.row(),self.now))

    def test_future_stale_and_malformed_provenance_rejected(self):
        for value in [(self.now+timedelta(seconds=1)).isoformat(),
                      (self.now-timedelta(days=2)).isoformat(),'broken']:
            self.assertFalse(selection.valid_candidate(self.row(canli_guncelleme=value),self.now))

    def test_nested_future_and_malformed_feature_time_rejected(self):
        for value in ['broken',(self.now+timedelta(seconds=1)).isoformat()]:
            self.assertFalse(selection.valid_candidate(self.row(criteria_snapshot={'captured_at':value}),self.now))

    def test_fresh_technical_record_accepted(self):
        self.assertTrue(selection.valid_candidate(self.row(teknik_gostergeler=self.technical()),self.now))

    def test_technical_stale_mode_time_and_close_mismatch_rejected(self):
        for update in [{'stale':True},{'mode':'INTRADAY'},{'data_time':None},
                       {'asof':'broken'},{'data_time':(self.now+timedelta(seconds=1)).isoformat()},
                       {'closing':{'close':101}}]:
            self.assertFalse(selection.valid_candidate(self.row(teknik_gostergeler=dict(self.technical(),**update)),self.now))

    def test_impossible_ohlc_rejected(self):
        doc=self.technical();doc['closing']['low']=101
        self.assertFalse(selection.valid_candidate(self.row(teknik_gostergeler=doc),self.now))

    def test_invalid_closing_volume_and_previous_close_rejected(self):
        for key,value in [('volume',-1),('turnover_tl',float('nan')),('previous_close',0)]:
            doc=self.technical();doc['closing'][key]=value
            self.assertFalse(selection.valid_candidate(self.row(teknik_gostergeler=doc),self.now))

    def test_actual_intraday_indicator_schema_without_daily_closing_is_accepted(self):
        import pandas as pd
        from teknik_gostergeler import calculate
        now=self.now.replace(hour=12,minute=5)
        frame=pd.DataFrame({'Open':[100]*25,'High':[101]*25,'Low':[99]*25,
                            'Close':[100]*25,'Volume':[10000]*25},
                           index=pd.date_range(now-timedelta(minutes=125),periods=25,freq='5min'))
        doc=calculate(frame,now,'INTRADAY')
        self.assertEqual(doc['closing'],{})
        self.assertTrue(selection.valid_candidate(self.row(teknik_gostergeler=doc),now,'INTRADAY'))

    def test_fully_equal_scores_are_deterministic_under_shuffle(self):
        rows=[self.row(s) for s in ('CCC','AAA','BBB')]
        for seed in range(5):
            shuffled=copy.deepcopy(rows);random.Random(seed).shuffle(shuffled)
            self.assertEqual([r['sembol'] for _,r in self.ranking(shuffled)],['AAA','BBB','CCC'])

    def test_existing_volume_then_risk_tiebreaks_preserved(self):
        rows=[dict(self.row('AAA'),hacim_orani=100,risk_getiri=5),
              dict(self.row('BBB'),hacim_orani=180,risk_getiri=1),
              dict(self.row('CCC'),hacim_orani=180,risk_getiri=2)]
        self.assertEqual([r['sembol'] for _,r in self.ranking(rows)],['CCC','BBB','AAA'])

    def test_pipeline_eligibility_gate_and_base_scores_unchanged(self):
        rows=[self.row('AAA',54),self.row('BBB',80),self.row('CCC',70)]
        result=self.ranking(rows)
        self.assertEqual([(score,r['sembol']) for score,r in result],[(80,'BBB'),(70,'CCC')])
        self.assertEqual([r['base_score'] for _,r in result],[80,70])

    def test_pipeline_deduplicates_before_scoring(self):
        result=self.ranking([self.row('AAA'),self.row('AAA.IS'),self.row('BBB')])
        self.assertEqual([r['sembol'] for _,r in result],['AAA','BBB'])

    def test_nonfinite_raw_score_does_not_enter_pipeline(self):
        self.assertEqual(self.ranking([self.row('AAA',float('inf')),self.row('BBB',80)])[0][1]['sembol'],'BBB')

    def test_bool_raw_score_is_rejected_after_remote_merge(self):
        self.assertEqual(self.ranking([self.row('AAA',True)]),[])

    def test_nonfinite_calibrated_score_cannot_be_clamped_into_top10(self):
        result=self.ranking([self.row()], **{'yarin_kalibrasyon.score':{
            'return_value':{'final_puan':float('nan'),'shadow_puan':80}}})
        self.assertEqual(result,[])

    def test_sixty_candidate_limit_precedes_learning(self):
        rows=[self.row('S'+str(i).zfill(3),90-i*.1) for i in range(75)]
        seen=[]
        def learned(order,model,current):
            seen.extend(order)
            return order
        result=self.ranking(rows,**{'yarin_kalibrasyon.rank_with_learning':{'side_effect':learned}})
        self.assertEqual(len(seen),60);self.assertEqual(len(result),10)
        self.assertEqual(seen[-1][1]['sembol'],'S059')

    def test_learning_can_promote_candidate_sixty_but_not_sixty_one(self):
        rows=[self.row('S'+str(i).zfill(3),90-i*.01) for i in range(61)]
        def adjustment(row,model,current):
            return {'learning_adjustment':3 if row['sembol'] in ('S059','S060') else 0}
        result=self.ranking(rows,**{'yarin_kalibrasyon.top10_learning_adjustment':{'side_effect':adjustment}})
        self.assertEqual(result[0][1]['sembol'],'S059')
        self.assertEqual(result[0][1]['base_rank'],60)
        self.assertNotIn('S060',[r['sembol'] for _,r in result])

    def test_repeated_scan_clears_rank_of_candidate_leaving_the_sixty(self):
        rows=[self.row('S'+str(i).zfill(3),90-i*.1) for i in range(61)]
        self.ranking(rows);self.assertIn('base_rank',rows[0])
        rows[0]['old_score']=55
        self.ranking(rows);self.assertNotIn('base_rank',rows[0])

    def test_select_candidates_deduplicates_and_rejects_nonfinite_scores(self):
        result=selection.select_candidates([(80,self.row()),(90,self.row('AAA.IS')),
                                           (float('inf'),self.row('BBB')),(70,self.row('CCC'))])
        self.assertEqual([(s,r['sembol']) for s,r in result],[(90,'AAA'),(70,'CCC')])

    def test_under_sixty_not_padded(self):
        self.assertEqual(len(selection.select_candidates([(80,self.row())])),1)
        self.assertEqual(selection.select_candidates([]),[])

    def test_intraday_limit_threshold_freshness_and_existing_tiebreaks(self):
        now=self.now.replace(hour=12)
        rows=[self.row('S'+str(i).zfill(3),gun_ici_puan=60,gun_ici_final_puan=80,
                       hacim3_orani=100,momentum15=1) for i in range(65)]
        rows += [self.row('LOW',gun_ici_puan=44,gun_ici_final_puan=95),
                 self.row('OLD',gun_ici_puan=80,canli_guncelleme=(now-timedelta(minutes=21)).isoformat())]
        rows[1]['hacim3_orani']=200;rows[2]['hacim3_orani']=200;rows[2]['momentum15']=2
        result=selection.intraday_candidates(rows,now)
        self.assertEqual(len(result),60)
        self.assertEqual([r['sembol'] for _,r in result[:3]],['S002','S001','S000'])

    def test_intraday_scan_publishes_sixty_candidates_and_keeps_full_search_rows(self):
        now=self.now.replace(hour=12)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now
        rows=[self.row('S'+str(i).zfill(3),gun_ici_puan=60,gun_ici_final_puan=80,
                       hacim3_orani=100,momentum15=1) for i in range(65)]
        by_symbol={r['sembol']:r for r in rows}
        with ExitStack() as stack:
            stack.enter_context(patch.object(bist_bot,'datetime',Clock))
            stack.enter_context(patch.object(bist_bot,'bist_hisseleri_getir',return_value=list(by_symbol)))
            stack.enter_context(patch.object(bist_bot,'gun_ici_gecersiz_oku',return_value=set()))
            stack.enter_context(patch.object(bist_bot,'gun_ici_stream_verileri_getir',return_value=(by_symbol,[])))
            stack.enter_context(patch.object(bist_bot,'gun_ici_analiz_hesapla',side_effect=lambda s,frame:by_symbol[s]))
            stack.enter_context(patch.object(bist_bot,'gun_ici_sinyal_durumlarini_guncelle',side_effect=lambda rows:rows))
            for name in ('ai_sinyal_sonuc_guncelle','ai_ogrenme_kaydet','ai_ogrenme_ozeti_yaz','ai_ogrenilmis_agirliklari_hesapla'):
                stack.enter_context(patch.object(bist_bot,name))
            stack.enter_context(patch.object(bist_bot,'yarin_top10_snapshot_oku',return_value=None))
            stack.enter_context(patch('gun_ici_performans.GunIciPerformans'))
            stack.enter_context(patch('piyasa_baglami.intraday_quotes',return_value=[]))
            stack.enter_context(patch('piyasa_baglami.PiyasaBaglami.refresh',return_value={}))
            top10,all_rows,total=bist_bot.gun_ici_top10_tara()
        self.assertEqual((len(top10),len(all_rows),total),(10,65,65))
        report=json.loads(self.paths.public_file('gun_ici_top10.json').read_text())
        self.assertEqual(report['aday_secimi']['count'],60)
        self.assertEqual(report['aday_secimi']['symbols'][-1],'S059')
        self.assertEqual([r['sembol'] for r in top10],['S'+str(i).zfill(3) for i in range(10)])

    def test_positive_pool_canonicalizes_duplicates_before_counting(self):
        from pozitif_kapanis import build_pool
        rows=[self.row('AAA',teknik_gostergeler=self.technical()),
              self.row('AAA.IS',teknik_gostergeler=self.technical())]
        forecast={'future_opportunity_score':80,'eligible':True,'criteria_snapshot':{}}
        with patch('pozitif_kapanis.attach_final_decision'),patch('pozitif_kapanis.opportunity',return_value=forecast):
            pool=build_pool(rows,self.now,2,lambda row:80)
        self.assertEqual(pool['total_checked'],1)
        self.assertEqual(pool['eligible_symbols'],['AAA'])

    def test_positive_pool_keeps_invalid_positive_count_and_rejection_diagnostics(self):
        from pozitif_kapanis import build_pool
        rows=[dict(self.row(teknik_gostergeler=self.technical()),rsi=float('nan'))]
        pool=build_pool(rows,self.now,1,lambda row:80)
        self.assertEqual(pool['positive_count'],1)
        self.assertEqual(pool['analyzed_count'],0)
        self.assertEqual(pool['rejected'][0]['filters'],['INVALID_TOP10_DATA'])

    def test_positive_pool_retained_invalid_duplicates_cannot_hide_valid_source(self):
        rows=[self.row(),dict(self.row('AAA.IS'),fiyat=float('nan'))]
        clean=selection.prepare_candidates(rows[::-1],self.now,keep_invalid=True)
        self.assertEqual(clean,[rows[0]])

    def test_positive_pool_malformed_technical_data_is_reported_without_crash(self):
        from pozitif_kapanis import build_pool
        pool=build_pool([self.row(teknik_gostergeler=['bad'])],self.now,1,lambda row:80)
        self.assertEqual(pool['positive_count'],1)
        self.assertEqual(pool['analyzed_count'],0)
        self.assertEqual(len(pool['rejected']),1)

    def test_snapshot_baselines_and_positive_pool_share_sixty_selection(self):
        now=self.now
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now
        rows=[self.row('S'+str(i).zfill(3),90-i*.1) for i in range(65)]
        for row in rows:
            row.update(ham_puan=row['old_score'],final_puan=row['old_score'],shadow_puan=row['old_score'],
                       positive_opportunity={'future_opportunity_score':row['old_score']})
        pool={'positive_count':65,'analyzed_count':65,'adaylar':copy.deepcopy(rows),
              'eligible_symbols':[r['sembol'] for r in rows]}
        from yarin_kalibrasyon import rank_with_learning
        def base_rank(items,**kwargs):
            ranked=rank_with_learning(selection.select_candidates([(r['old_score'],r) for r in items]),
                                      {'status':'DISABLED'},now)
            return ranked[:10]
        with patch.object(bist_bot,'datetime',Clock),patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.paths.public_file('yarin_top10.json'))),patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.paths.archives)),patch.object(bist_bot,'yarin_top10_listesi',side_effect=base_rank),patch('yarin_kalibrasyon.top10_learning_context',return_value={'status':'DISABLED'}),patch('pozitif_kapanis.build_pool',return_value=pool),patch('pozitif_kapanis.enrich_closing_sources'):
            snapshot=bist_bot.yarin_top10_kilitli_kaydet(rows,65,pozitif_kapanis=True)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot['aday_secimi']['count'],60)
        self.assertEqual(snapshot['aday_secimi']['symbols'][-1],'S059')
        self.assertEqual(len(snapshot['pozitif_havuz']['adaylar']),65)
        for field in ('top10','base_top10','ham_top10','shadow_top10','controlled_shadow_top10'):
            self.assertEqual(len(snapshot[field]),10)
            self.assertEqual(len({r['sembol'] for r in snapshot[field]}),10)
        archived=json.loads((self.paths.archives/'2026-10-08.json').read_text())
        self.assertEqual(archived['aday_secimi'],snapshot['aday_secimi'])


if __name__ == '__main__':
    unittest.main()
