"""Opt-in real OHLC validation, never evidence of historical model superiority.

Quote files are fetched read-only using the existing provider into a scratch
directory. The prediction lists here are explicitly validation fixtures.
Missing external quotes skip these checks rather than substituting fake prices.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from ai_karar_motoru import HORIZONS,ISTANBUL,stamp
from kullanici_kayitlari import atomic_json
from performans_motoru import PerformansMotoru,bist_calendar,outcome
from veri_yollari import DataPaths
import bist_bot
import top10_ogrenme_performansi as comparison

SYMBOLS=('THYAO','ASELS','AKBNK','GARAN','EREGL','TUPRS','BIMAS','SISE','KCHOL','SAHOL')


class RealPriceValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory=os.environ.get('BIST_REAL_VALIDATION_DIR')
        if not directory:raise unittest.SkipTest('Real provider OHLC not supplied; no simulated substitute')
        cls.prices={};cls.quote_paths=[]
        for symbol in SYMBOLS:
            path=Path(directory)/('bist-real-validation-'+symbol.lower()+'.json')
            if not path.exists():raise unittest.SkipTest('Missing real provider quotes: '+symbol)
            cls.prices[symbol]=json.loads(path.read_bytes());cls.quote_paths.append(path)
        cls.at=datetime(2026,5,25,19,tzinfo=ISTANBUL)
        cls.now=datetime(2026,10,10,19,tzinfo=ISTANBUL)
        cls.expected_days=[day.date() for day in bist_calendar(2026).sessions_in_range('2026-05-26','2026-10-09')[:60]]
        assert len(cls.expected_days)==60

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.by_day={s:{stamp(r['timestamp']).date():r for r in bars} for s,bars in self.prices.items()}
        rows=[]
        for i,symbol in enumerate(SYMBOLS,1):
            base=self.by_day[symbol][self.at.date()]['close']
            rows.append({'sembol':symbol,'fiyat':base,'yarin_ai_karar':'AL',
                         'ai_yarin_hedef':base*1.1,'ai_yarin_stop':base*.95,'yarin_top10_puani':80,
                         'learning_version':'VALIDATION_FIXTURE_NOT_A_HISTORICAL_MODEL',
                         'learning_adjustment':0,'base_rank':i,'learned_rank':i,'base_score':80})
        self.snapshot=bist_bot.yarin_snapshot_modeli({'analiz_tarihi':self.at.date().isoformat(),
            'top10':copy.deepcopy(rows),'base_top10':copy.deepcopy(rows),
            'comparison_context':{'purpose':'REAL_PRICE_PROCESSING_ONLY_NOT_MODEL_PERFORMANCE'}},self.at.isoformat())
        self.archive=self.location.archives/(self.at.date().isoformat()+'.json')
        atomic_json(self.archive,self.snapshot)

    def engine(self):
        def real_quote_cache(symbol):return copy.deepcopy(self.prices[symbol])
        return PerformansMotoru(self.location,clock=lambda:self.now,history_provider=real_quote_cache,batch_size=25)

    def test_actual_ohlc_all_symbols_six_calendar_horizons_close_return_and_risk(self):
        records=self.engine().snapshot_records({})
        for row in records:
            symbol=row['sembol'];base=row['fiyat']
            for h in HORIZONS:
                with self.subTest(symbol=symbol,horizon=h):
                    result=outcome(row,self.prices[symbol],h,self.now,price_source='BORSAPY_DAILY_OHLCV_READ_ONLY')
                    self.assertTrue(result['degerlendirme_tamamlandi'])
                    day=self.expected_days[h-1];window=[self.by_day[symbol][d] for d in self.expected_days[:h]]
                    self.assertEqual(result['tarih'],day.isoformat())
                    self.assertEqual(result['fiyat'],self.by_day[symbol][day]['close'])
                    self.assertAlmostEqual(result['getiri_yuzde'],(result['fiyat']/base-1)*100,places=3)
                    self.assertAlmostEqual(result['mfe_pct'],max(0,(max(r['high'] for r in window)/base-1)*100),places=3)
                    self.assertAlmostEqual(result['mae_pct'],min(0,(min(r['low'] for r in window)/base-1)*100),places=3)
        self.assertEqual(self.expected_days[0].isoformat(),'2026-05-26') # Real half session.
        self.assertEqual(self.expected_days[1].isoformat(),'2026-06-01') # Eid closure skipped.

    def test_real_prices_through_archive_worker_report_and_idempotent_rerun(self):
        engine=self.engine();archive_before=self.archive.read_bytes()
        engine.one_round()
        history=json.loads(engine.history_path.read_bytes());records=history['kayitlar']
        self.assertEqual(len(records),20)
        self.assertTrue(all(r[f'sonuc_{h}g']['degerlendirme_tamamlandi'] for r in records for h in HORIZONS))
        for h in HORIZONS:
            stats=comparison.api_report({'horizon':[str(h)]},self.location)['summary']
            self.assertEqual(stats['models']['BASE']['sample_count'],10)
            self.assertEqual(stats['differences_vs_base']['mean_return'],0) # Identical fixture lists.
            self.assertTrue(stats['models']['BASE']['risk']['complete'])
            self.assertEqual(stats['display_status'],'YETERSİZ VERİ')
        with patch.object(engine,'provider',side_effect=AssertionError('sealed outcomes refetched')):
            engine.one_round()
        self.assertEqual(json.loads(engine.history_path.read_bytes())['kayitlar'],records)
        self.assertEqual(self.archive.read_bytes(),archive_before)

    def test_source_quote_files_and_immutable_prediction_payloads_are_not_modified(self):
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.quote_paths}
        original=copy.deepcopy(self.snapshot);self.engine().one_round()
        self.assertEqual(self.snapshot,original)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.quote_paths})

    def test_future_prices_do_not_change_short_horizon_and_missing_real_close_is_not_imputed(self):
        row=self.engine().snapshot_records({})[0];symbol=row['sembol']
        first=outcome(row,self.prices[symbol],1,self.now)
        changed=copy.deepcopy(self.prices[symbol])
        for bar in changed:
            if stamp(bar['timestamp']).date()>self.expected_days[0]:bar.update(close=1,high=1,low=1,open=1)
        self.assertEqual(outcome(row,changed,1,self.now),first)
        missing=[r for r in self.prices[symbol] if stamp(r['timestamp']).date()!=self.expected_days[0]]
        self.assertFalse(outcome(row,missing,1,self.now)['degerlendirme_tamamlandi'])

    def test_validation_fixtures_never_claim_historical_learning_superiority(self):
        self.engine().one_round()
        report=comparison.api_report({},self.location)
        evaluation=report['summary']['chronological_evaluation']
        self.assertEqual(evaluation['assessment'],'INSUFFICIENT_DATA')
        self.assertEqual(evaluation['paired_days'],1)
        self.assertEqual(set(evaluation['by_learning_version']),{'VALIDATION_FIXTURE_NOT_A_HISTORICAL_MODEL'})
        self.assertFalse(evaluation['reconstructed_scores'])
