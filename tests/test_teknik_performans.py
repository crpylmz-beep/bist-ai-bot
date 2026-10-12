"""Frozen technical evidence and independent, point-in-time outcome reports."""
import copy
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import bist_bot as bot
import teknik_gostergeler as tech
from performans_motoru import PerformansMotoru
from veri_yollari import DataPaths

class TechnicalPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,10,6,13,20,tzinfo=tech.ISTANBUL)
        self.end=self.at+timedelta(days=100)
        index=pd.date_range('2026-10-06 10:00',periods=40,freq='5min',tz='Europe/Istanbul')
        self.frame=pd.DataFrame({'Open':[100]*39+[102],'High':[100.2]*39+[102.2],'Low':[99.8]*39+[101.8],
                                 'Close':[100]*39+[102],'Volume':[100]*39+[300]},index=index)
        self.doc=tech.calculate(self.frame,self.at)
    def record(self,mode='INTRADAY',day=0,symbol='THYAO',gain=2):
        at=self.at+timedelta(days=day);doc=copy.deepcopy(self.doc)
        doc.update(asof=at.isoformat(),data_time=at.isoformat(),mode=mode)
        outcome={'durum':'BASARILI','getiri_yuzde':gain,'observed_at':(at+timedelta(days=1)).isoformat(),
                 'tamamlandi':True,'egitime_uygun':True,'degerlendirme_tamamlandi':True,'kalite_uyarilari':[]}
        return {'sembol':symbol,'sinyal_zamani':at.isoformat(),'zaman':at.isoformat(),'karar':'AL',
                'model':'YARIN_TOP10' if mode=='TOMORROW' else 'GUN_ICI','teknik_gostergeler':doc,
                'sonuclar':{str(h):copy.deepcopy(outcome) for h in (5,15,30,60,'SEANS')},
                **{'sonuc_'+str(h)+'g':copy.deepcopy(outcome) for h in (1,3,5,10,20,60)}}
    def report(self,records,mode='INTRADAY',current=None):return tech.performance_report(records,current or self.end,mode)
    def test_metrics_and_separate_horizons(self):
        intra=self.record();daily=self.record('TOMORROW',symbol='ASELS')
        a=self.report([intra,daily]);b=self.report([intra,daily],'TOMORROW')
        self.assertEqual(set(a['vadeler']),{'5','15','30','60','SEANS'})
        self.assertEqual(set(b['vadeler']),{'1','3','5','10','20','60'})
        value=a['vadeler']['5']['OBV_POZITIF_TREND']['varken']
        self.assertEqual((value['sample_count'],value['success_rate'],value['median_return'],value['trimmed_mean']),(1,1,2,2))
        self.assertEqual(b['vadeler']['1']['OBV_POZITIF_TREND']['varken']['sample_count'],1)
        self.assertEqual(value['confidence'],'DUSUK');self.assertFalse(a['learning_enabled']);self.assertFalse(b['score_applied'])
    def test_future_outcomes_do_not_change_earlier_report_or_frozen_criteria(self):
        record=self.record();before=copy.deepcopy(record)
        report=self.report([record],current=self.at+timedelta(minutes=30))
        self.assertEqual(report['vadeler']['5']['VWAP_USTU']['varken']['sample_count'],0)
        later=self.report([record]);self.assertEqual(later['vadeler']['5']['VWAP_USTU']['varken']['sample_count'],1)
        self.assertEqual(record,before);self.assertEqual(tech.features(record),tech.features(before))
    def test_duplicate_stock_day_uses_first_signal_before_outcome_filter(self):
        first=self.record();second=self.record();second['sinyal_zamani']=(self.at+timedelta(minutes=5)).isoformat()
        first['sonuclar']['5']['egitime_uygun']=False
        value=self.report([second,first])['vadeler']['5']['OBV_POZITIF_TREND']
        self.assertEqual(value['varken']['sample_count'],0)
    def test_unknown_legacy_and_mismatched_mode_are_not_negative_evidence(self):
        record=self.record();record.pop('teknik_gostergeler');other=self.record(symbol='ASELS');other['teknik_gostergeler']['mode']='TOMORROW'
        result=self.report([record,other])['vadeler']['5']['VWAP_USTU']
        self.assertEqual(result['bilinmeyen'],2);self.assertEqual(result['yokken']['sample_count'],0)
    def test_pre_signal_observation_and_unfinished_outcomes_are_rejected(self):
        record=self.record();record['sonuclar']['5']['observed_at']=(self.at-timedelta(minutes=1)).isoformat()
        record['sonuclar']['15']['tamamlandi']=False
        report=self.report([record])
        for h in ('5','15'):self.assertEqual(report['vadeler'][h]['OBV_POZITIF_TREND']['varken']['sample_count'],0)
    def test_future_indicator_snapshot_is_unknown_not_backfilled(self):
        record=self.record();record['teknik_gostergeler']['asof']=(self.at+timedelta(minutes=5)).isoformat()
        self.assertEqual(self.report([record])['vadeler']['5']['VWAP_USTU']['bilinmeyen'],1)
    def test_confidence_needs_both_groups_and_independent_days(self):
        rows=[]
        for i in range(80):
            row=self.record(day=i%8,symbol='S'+str(i),gain=i%3)
            if i>=40:row['teknik_gostergeler']['obv']['trend']='OBV_DUSEN'
            rows.append(row)
        value=self.report(rows)['vadeler']['5']['OBV_POZITIF_TREND']
        self.assertEqual(value['confidence'],'YETERLI');self.assertEqual(value['varken']['sample_count'],40)
        self.assertEqual(value['yokken']['independent_days'],8)
        for row in rows:row['sinyal_zamani']=self.at.isoformat();row['zaman']=self.at.isoformat();row['teknik_gostergeler'].update(asof=self.at.isoformat(),data_time=self.at.isoformat())
        self.assertEqual(self.report(rows)['vadeler']['5']['OBV_POZITIF_TREND']['confidence'],'DUSUK')
    def test_tomorrow_archive_freezes_and_performance_import_uses_frozen_document(self):
        with tempfile.TemporaryDirectory() as root:
            paths=DataPaths({'BIST_DATA_DIR':root});paths.ensure();current=self.at.replace(hour=19,minute=0)
            daily=self.frame.copy();daily.index=pd.bdate_range(end='2026-10-06',periods=40,tz='Europe/Istanbul')
            doc=tech.calculate(daily,current,'TOMORROW')
            row={'sembol':'THYAO','fiyat':102,'yarin_ai_karar':'AL','ai_yarin_hedef':110,'ai_yarin_stop':95,'teknik_gostergeler':doc}
            with patch.object(bot,'YARIN_TOP10_FILE',str(paths.public/'yarin_top10.json')),patch.object(bot,'YARIN_TOP10_ARSIV_DIR',str(paths.archives)),patch.object(bot,'yarin_top10_listesi',side_effect=lambda rows,**kwargs:[(80,r) for r in rows]),patch.object(bot,'datetime',wraps=datetime) as clock:
                clock.now.return_value=current
                first=bot.yarin_top10_kilitli_kaydet([row],1);path=paths.archives/'2026-10-06.json';original=path.read_bytes()
                self.assertEqual(first['top10'][0]['tahmin']['teknik_gostergeler'],doc)
                row['teknik_gostergeler']['obv']['value']=999999;row['fiyat']=999
                second=bot.yarin_top10_kilitli_kaydet([row],1)
                self.assertEqual(first,second);self.assertEqual(path.read_bytes(),original)
                imported=PerformansMotoru(location=paths).snapshot_records({'arsivler':{}})
                self.assertNotEqual(imported[0]['teknik_gostergeler']['obv']['value'],999999)
                self.assertEqual(path.read_bytes(),original)
    def test_actual_daily_pipeline_future_price_cannot_change_score_or_indicators(self):
        daily=self.frame.copy();daily.index=pd.bdate_range(end='2026-10-06',periods=40,tz='Europe/Istanbul')
        future=daily.tail(1).copy();future.index=pd.DatetimeIndex(['2026-10-07'],tz='Europe/Istanbul');future.loc[:,'Close']=100000
        with patch.object(bot.bp,'Ticker') as provider,patch.object(bot,'datetime',wraps=datetime) as clock,patch.object(bot,'yarin_top10_canli_guncelle'),patch.object(bot,'canli_makro_puani_getir',return_value={}):
            clock.now.return_value=self.at.replace(hour=19,minute=0)
            provider.return_value.history.return_value=daily;before=bot.hisse_analiz_hesapla('THYAO')
            provider.return_value.history.return_value=pd.concat([daily,future]);after=bot.hisse_analiz_hesapla('THYAO')
            self.assertIsNotNone(before);self.assertEqual(before,after)
