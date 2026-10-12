import copy
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from datetime import timedelta
import test_sinyal_performansi as signal_tests
from sinyal_performansi import (indicator_conditions,aggregate_indicators,capture_indicators,
                                indicator_report,publish,RELIABILITY)
from veri_yollari import DataPaths


class IndicatorTests(unittest.TestCase):
    setUp=signal_tests.AnalysisTests.setUp
    short=signal_tests.AnalysisTests.short
    def condition(self,**values):return indicator_conditions(dict(self.row,**values))
    def rows(self,records=None):return aggregate_indicators(records or [self.row],self.now,self.holiday)['rows']
    def stat(self,records=None,h=1,signal='ALL'):
        return next(r for r in self.rows(records) if r['indicator']=='RSI' and r['horizon']==h and r['period']=='ALL' and r['signal_type']==signal)
    def test_rsi_boundaries(self):
        for value,label in ((0,'0-29'),(29,'0-29'),(30,'30-39'),(39,'30-39'),(40,'40-49'),(49,'40-49'),(50,'50-59'),(59,'50-59'),(60,'60-69'),(69,'60-69'),(70,'70-100'),(100,'70-100')):
            self.assertEqual(self.condition(rsi=value)['RSI'],label)
    def test_macd_sign(self):self.assertEqual(self.condition(macd=-1)['MACD_SIGN'],'NEGATIVE')
    def test_macd_signal(self):self.assertEqual(self.condition(macd=1,signal=2)['MACD_SIGNAL'],'BELOW')
    def test_histogram_sign(self):self.assertEqual(self.condition(hist=.5)['HIST_SIGN'],'POSITIVE')
    def test_histogram_trend_requires_both(self):
        self.assertEqual(self.condition(hist=.5,hist_onceki=.2)['HIST_TREND'],'IMPROVING')
        self.assertNotIn('HIST_TREND',self.condition(hist=.5))
    def test_volume_boundaries(self):
        for value,label in ((79,'<80'),(80,'80-119'),(119,'80-119'),(120,'120-149'),(149,'120-149'),(150,'150-199'),(199,'150-199'),(200,'200+')):
            self.assertEqual(self.condition(hacim_orani=value)['VOLUME'],label)
    def test_price_sma20(self):self.assertEqual(self.condition(sma20=101)['PRICE_SMA20'],'BELOW')
    def test_price_sma50(self):self.assertEqual(self.condition(sma50=99)['PRICE_SMA50'],'ABOVE')
    def test_sma_trend(self):self.assertEqual(self.condition(sma20=90,sma50=110)['SMA_TREND'],'BELOW')
    def test_vwap(self):self.assertEqual(self.condition(vwap20=90)['VWAP'],'ABOVE')
    def test_obv(self):self.assertEqual(self.condition(obv_durum='YUKSELEN')['OBV'],'POSITIVE')
    def test_bollinger(self):self.assertEqual(self.condition(boll_durum='ALT_BANDA_YAKIN')['BOLLINGER'],'NEAR_LOWER')
    def test_atr(self):
        for atr,label in ((1,'<2%'),(2,'2-4%'),(4,'4%+')):self.assertEqual(self.condition(atr14=atr)['ATR'],label)
    def test_actual_confirmation_count(self):
        self.assertEqual(self.condition(nihai_karar={'teyit_sayisi':5,'teyit_toplam':6})['CONFIRMATION_COUNT'],'5/6')
        self.assertNotIn('CONFIRMATIONS',self.condition())
    def test_predefined_combinations(self):
        self.assertEqual(self.condition()['COMBO_RSI_MACD_VOLUME'],'CONFIRMED')
        self.assertEqual(self.condition(hacim_orani=90)['COMBO_MACD_VOLUME'],'NOT_CONFIRMED')
        self.assertLessEqual(sum(k.startswith('COMBO') for k in self.condition()),6)
    def test_all_horizons(self):
        for h in (1,3,5,10,20,60):self.assertEqual(self.stat(h=h)['completed'],1)
    def test_buy_direction(self):self.assertEqual(self.stat()['mean_return'],5)
    def test_sell_direction(self):self.assertEqual(self.stat([self.short()])['mean_return'],5)
    def test_pending_excluded(self):
        row=copy.deepcopy(self.row);row['sonuc_1g']=None
        stat=self.stat([row]);self.assertEqual(stat['pending'],1);self.assertIsNone(stat['success_rate'])
    def test_legacy_excluded(self):
        row=copy.deepcopy(self.row);del row['sonuc_1g']['degerlendirme_tamamlandi']
        self.assertEqual(self.stat([row])['excluded'],{'UNVERIFIED':1})
    def test_no_snapshot_backfill(self):
        row={'id':'empty','tarih':self.row['tarih'],'sembol':'THYAO'};before=copy.deepcopy(row)
        self.assertEqual(indicator_conditions(row),{});self.assertEqual(row,before)
        self.assertEqual(aggregate_indicators([row],self.now)['unavailable']['RSI'],1)
    def test_new_snapshot_is_independent_and_does_not_invent(self):
        source={'rsi':55};snapshot=capture_indicators(source,self.row['tarih']);source['rsi']=90
        self.assertEqual(snapshot['inputs'],{'rsi':55})
    def test_snapshot_overrides_later_raw_features(self):
        row=dict(self.row,indicator_snapshot=capture_indicators(self.row,self.row['tarih']),rsi=90)
        self.assertEqual(indicator_conditions(row)['RSI'],'50-59')
    def test_future_snapshot_excluded(self):
        row=dict(self.row,indicator_snapshot=capture_indicators(self.row,(self.at+timedelta(days=1)).isoformat()))
        self.assertEqual(self.stat([row])['excluded'],{'FUTURE_FEATURES':1})
    def test_duplicates(self):self.assertEqual(self.stat([self.row,self.row])['sample_count'],1)
    def test_conflicting_duplicates(self):
        row=copy.deepcopy(self.row);row['rsi']=60
        self.assertEqual(self.stat([self.row,row])['excluded'],{'DUPLICATE_CONFLICT':1})
    def test_confidence_shared(self):
        stat=self.stat();self.assertEqual(stat['reliability'],'INSUFFICIENT');self.assertEqual(stat['sample_count'],1)
        self.assertEqual(aggregate_indicators([self.row],self.now)['reliability_thresholds'],RELIABILITY)
    def test_time_filter(self):self.assertFalse(any(r['period']=='7' for r in self.rows()))
    def test_signal_indicator_breakdown(self):self.assertEqual(self.stat(signal='AGRESIF_ALIS')['wins'],1)
    def test_structured_indicators(self):
        tech={'asof':self.row['tarih'],'obv':{'status':'OK','trend':'OBV_YUKSELEN'},'bollinger':{'status':'OK','upper':110,'lower':90,'squeeze':True,'upper_break':False}}
        row=dict(self.row,indicator_snapshot=capture_indicators(dict(self.row,teknik_gostergeler=tech),self.row['tarih']))
        found=indicator_conditions(row);self.assertEqual(found['OBV'],'POSITIVE');self.assertEqual(found['BOLL_SQUEEZE'],'YES')
    def test_learning_dataset_uses_frozen_indicator_snapshot(self):
        from sinyal_performansi import clean_dataset
        row=dict(self.row,indicator_snapshot=capture_indicators(self.row,self.row['tarih']),rsi=90)
        example=next(clean_dataset([row],self.now,self.holiday))
        self.assertEqual(example['features']['rsi'],55)
        self.assertEqual(example['features']['indicator_conditions']['RSI'],'50-59')
        self.assertNotIn('mfe_pct',example['features']['indicator_conditions'])
    def test_zero_return_is_unsuccessful_but_not_a_loss(self):
        row=copy.deepcopy(self.row);row['sonuc_1g'].update(fiyat=100,getiri_yuzde=0,yon_getirisi=0)
        stat=self.stat([row]);self.assertEqual(stat['wins'],0);self.assertEqual(stat['failures'],1);self.assertEqual(stat['losses'],0)
    def test_snapshot_without_capture_timestamp_is_unverified(self):
        row=dict(self.row,indicator_snapshot={'inputs':{'rsi':55}})
        self.assertEqual(self.stat([row])['excluded'],{'UNVERIFIED_FEATURES':1})
    def test_future_structured_indicator_timestamp_excluded(self):
        snapshot=capture_indicators(dict(self.row,teknik_gostergeler={'asof':(self.at+timedelta(days=1)).isoformat()}),self.row['tarih'])
        self.assertEqual(self.stat([dict(self.row,indicator_snapshot=snapshot)])['excluded'],{'FUTURE_FEATURES':1})
    def test_cache_rebuild_and_http_filters(self):
        from web_server import create_server
        with tempfile.TemporaryDirectory() as directory:
            location=DataPaths({'BIST_DATA_DIR':directory});location.ensure()
            with patch('sinyal_performansi.aggregate_indicators',side_effect=lambda rows,now:aggregate_indicators(rows,now,self.holiday)):
                publish(location,[self.row],self.now)
                target=location.public_file('sinyal_performansi.json');first=target.read_bytes();target.write_text('{broken')
                publish(location,[self.row],self.now);self.assertEqual(target.read_bytes(),first)
            server=create_server('127.0.0.1',0,data_paths=location);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                root=f'http://127.0.0.1:{server.server_port}/api/indicator-performance'
                with urllib.request.urlopen(root+'?indicator=RSI&condition=50-59&signal_type=AGRESIF_ALIS&horizon=1&period=ALL') as response:
                    result=json.load(response);self.assertEqual(len(result['rows']),1);self.assertEqual(result['rows'][0]['wins'],1)
                target.write_text('{broken')
                with self.assertRaises(urllib.error.HTTPError) as cache_error:urllib.request.urlopen(root)
                self.assertEqual(cache_error.exception.code,503)
                target.write_bytes(first)
                for query in ('indicator=BAD','horizon=2','period=5','condition=BAD','signal_type=BAD','indicator=RSI&condition=ABOVE','horizon=1&horizon=3','secret=anything','indicator='):
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(root+'?'+query)
                    self.assertEqual(error.exception.code,400)
            finally:server.shutdown();server.server_close();thread.join()
