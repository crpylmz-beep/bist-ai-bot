import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime,timedelta
from unittest.mock import Mock,patch

from ai_karar_motoru import ISTANBUL,evaluate,AIKararMotoru
from kullanici_kayitlari import atomic_json
from veri_yollari import DataPaths
from piyasa_baglami import build_context,PiyasaBaglami,stock_context,annotate,effects,usable_context,intraday_quotes


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'LEARNING_ENABLED':'false','GUN_ICI_LEARNING_ENABLED':'false'}))
        self.current=datetime(2026,10,6,12,tzinfo=ISTANBUL)
        self.map={'S'+str(i).zfill(3):'A' if i<20 else 'B' if i<40 else 'C' for i in range(60)}
        atomic_json(self.location.public/'sektor_haritasi.json',{'hisseler':{s:{'sektor':v} for s,v in self.map.items()}})
        self.engine=PiyasaBaglami(self.location,clock=lambda:self.current)

    def rows(self,change=3):
        return [dict(sembol=s,fiyat=100,degisim=change,acilisa_gore_degisim=change,
            canli_guncelleme=self.current.isoformat(),veri_tarihi=(self.current-timedelta(minutes=5)).isoformat(),
            sma20=90 if change>0 else 110 if change<0 else 100,sma50=80 if change>0 else 120 if change<0 else 100,
            ema9_5=90 if change>0 else 110 if change<0 else 100,ema21_5=80 if change>0 else 120 if change<0 else 100,
            momentum15=change,hacim_orani=180,hacim3_orani=180,rsi=55,rsi5=55,
            teknik_puan=80,gun_ici_puan=80,gun_ici_karar='AL',gun_ici_guven=80,
            gun_ici_alim_alt=99,gun_ici_alim_ust=100,gun_ici_kar_al=105,gun_ici_stop=98,
            yarin_alim_alt=99,yarin_alim_ust=100,yarin_kar_al=105,yarin_stop=98,
            al_puani=90,sat_puani=10,destek=98,direnc=105,haber_puani=0,makro_puani=0,sektor_puani=0)
            for s in self.map]

    def index(self,change=3):
        return {'degisim':change,'updated_at':self.current.isoformat(),'fiyat':100,'acilis':100/(1+change/100),'yuksek':102,'dusuk':99}

    def context(self,change=3,rows=None,index=None,source='DAILY'):
        return build_context(self.rows(change) if rows is None else rows,self.map,self.index(change) if index is None else index,self.map,self.current,source)

    def strong_relative(self):
        rows=self.rows();
        for r in rows:r['degisim']=4 if self.map[r['sembol']]=='A' else -2 if self.map[r['sembol']]=='B' else 1
        return self.context(rows=rows,index=self.index(1))

    def test_strong_up_multiple_components(self):
        doc=self.context();self.assertEqual(doc['piyasa_rejimi'],'GUCLU_YUKSELIS')
        self.assertGreaterEqual(doc['kullanilan_veri_sayisi'],3);self.assertGreater(doc['rejim_confidence'],50)

    def test_strong_down(self):self.assertEqual(self.context(-3)['piyasa_rejimi'],'GUCLU_DUSUS')

    def test_flat(self):self.assertEqual(self.context(0)['piyasa_rejimi'],'YATAY')

    def test_up_and_down_supported(self):
        for change,expected in ((1,'YUKSELIS'),(-1,'DUSUS')):
            rows=self.rows(change)
            for r in rows:r.update(sma20=100,sma50=100,momentum15=0,hacim_orani=100)
            self.assertEqual(self.context(change,rows=rows)['piyasa_rejimi'],expected)

    def test_insufficient_and_single_index_unknown(self):
        doc=self.context(rows=self.rows()[:5]);self.assertEqual(doc['piyasa_rejimi'],'BELIRSIZ');self.assertLess(doc['rejim_confidence'],50)
        rows=self.rows()
        for r in rows:
            for k in ('sma20','sma50','momentum15','hacim_orani'):r.pop(k)
        for r in rows:self.map[r['sembol']]='A'
        doc=self.context(rows=rows);self.assertEqual(doc['piyasa_rejimi'],'BELIRSIZ')

    def test_positive_negative_breadth_counts(self):
        positive=self.context()['breadth'];negative=self.context(-3)['breadth']
        self.assertEqual(positive['yukselen'],60);self.assertEqual(positive['guclu_yukselen'],60)
        self.assertEqual(positive['hacim_destekli_yukselen'],60);self.assertEqual(negative['dusen'],60)
        self.assertEqual(positive['score'],100);self.assertEqual(negative['score'],-100)
        self.assertIsNone(positive['yukselen_dusen_orani'])

    def test_coverage_and_minimum_count(self):
        doc=self.context(rows=self.rows()[:30]);self.assertFalse(doc['breadth']['yeterli_veri'])
        self.assertEqual(doc['breadth']['coverage'],.5);self.assertIsNone(doc['breadth']['score'])
        small=self.rows()[:5];doc=build_context(small,[r['sembol'] for r in small],self.index(),self.map,self.current)
        self.assertFalse(doc['breadth']['yeterli_veri'])

    def test_missing_quotes_not_treated_flat(self):
        rows=self.rows()
        for r in rows[:30]:r.pop('degisim')
        doc=self.context(rows=rows);self.assertEqual(doc['breadth']['degismeyen'],0)
        self.assertEqual(doc['breadth']['gecerli'],30)

    def test_strong_weak_sectors_relative_formula(self):
        doc=self.strong_relative();a,b=doc['sektorler']['A'],doc['sektorler']['B']
        self.assertEqual(a['relatif_getiri'],3);self.assertEqual(a['rs_score'],75)
        self.assertEqual(a['sinif'],'COK_GUCLU');self.assertEqual(b['sinif'],'COK_ZAYIF')
        self.assertEqual(a['hisse_sayisi'],20);self.assertEqual(a['hacim_destegi'],1)

    def test_unknown_sector_no_effect(self):
        self.map['S000']='BILINMIYOR';doc=self.context()
        ctx=stock_context(doc,self.rows()[0]);self.assertEqual(ctx['sektor_confidence'],0)
        row=dict(self.rows()[0],piyasa_baglami=ctx);self.assertEqual(effects(row,80,self.current)['sektor_duzeltmesi'],0)

    def test_small_sector_fallback(self):
        self.map['S000']='SMALL';doc=self.context();self.assertFalse(doc['sektorler']['SMALL']['yeterli_veri'])
        self.assertIsNone(doc['sektorler']['SMALL']['rs_score'])

    def test_stale_prices_excluded(self):
        rows=self.rows()
        for r in rows:r['canli_guncelleme']=(self.current-timedelta(minutes=21)).isoformat()
        doc=self.context(rows=rows);self.assertTrue(doc['stale']);self.assertEqual(doc['breadth']['stale_hisse'],60)
        self.assertEqual(doc['piyasa_rejimi'],'BELIRSIZ')

    def test_partial_stale_reduces_coverage(self):
        rows=self.rows()
        for r in rows[:10]:r['canli_guncelleme']=(self.current-timedelta(minutes=30)).isoformat()
        doc=self.context(rows=rows);self.assertEqual(doc['breadth']['gecerli'],50)
        self.assertLess(doc['breadth']['confidence'],100)

    def test_future_quotes_excluded(self):
        rows=self.rows()
        for r in rows:r['canli_guncelleme']=(self.current+timedelta(seconds=1)).isoformat()
        doc=self.context(rows=rows);self.assertEqual(doc['breadth']['gelecek_hisse'],60);self.assertEqual(doc['piyasa_rejimi'],'BELIRSIZ')

    def test_closed_label_and_intraday_disabled(self):
        doc=self.context();now=self.current.replace(hour=18,minute=15)
        doc['updated_at']=now.isoformat()
        closed=usable_context(doc,now,'YARIN');self.assertFalse(closed['piyasa_acik']);self.assertEqual(closed['veri_etiketi'],'SON_BILINEN_SEANS')
        self.assertTrue(usable_context(doc,now,'INTRADAY')['stale'])

    def test_old_context_no_effect(self):
        doc=self.context();row=self.rows()[0];annotate([row],doc)
        self.assertEqual(effects(row,80,self.current+timedelta(minutes=21),'YARIN')['piyasa_baglami_etkisi'],0)

    def test_future_context_no_effect(self):
        doc=self.context();doc['updated_at']=(self.current+timedelta(seconds=1)).isoformat()
        row=self.rows()[0];annotate([row],doc);self.assertEqual(effects(row,80,self.current)['piyasa_baglami_etkisi'],0)

    def test_input_age_expires_even_when_report_timestamp_is_recent(self):
        rows=self.rows()
        for r in rows:r['canli_guncelleme']=(self.current-timedelta(minutes=19)).isoformat()
        doc=self.context(rows=rows);row=rows[0];annotate([row],doc)
        later=self.current+timedelta(minutes=2)
        self.assertTrue(usable_context(doc,later)['stale'])
        self.assertEqual(effects(row,80,later)['piyasa_baglami_etkisi'],0)

    def test_cached_confidence_decays_without_new_price_fetch(self):
        doc=self.context()
        aged=usable_context(doc,self.current+timedelta(minutes=11))
        self.assertLess(aged['rejim_confidence'],doc['rejim_confidence'])
        self.assertEqual(doc['breadth']['confidence'],100)

    def test_market_api_labels_closed_and_stale_without_worker(self):
        from web_server import create_server
        self.current=self.current.replace(hour=17,minute=55)
        self.engine.refresh(rows=self.rows(),universe=self.map,index=self.index())
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        from piyasa_baglami import build_measurement
        atomic_json(self.location.public/'market_context.json',build_measurement([],[],{},self.current,lambda _:False))
        self.current=self.current.replace(hour=18,minute=16)
        with patch('piyasa_baglami.PiyasaBaglami',return_value=self.engine):
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/market-context') as response:
                result=json.load(response)
        self.assertFalse(result['piyasa_acik']);self.assertEqual(result['veri_etiketi'],'SON_BILINEN_SEANS')
        self.assertTrue(result['stale']);self.assertEqual(result['rejim_confidence'],0)
        self.assertTrue(all(v['confidence']==0 for v in result['sektor_siralamasi']))

    def test_future_market_cannot_select_learned_regime_scope(self):
        import bist_bot
        from yarin_kalibrasyon import BASE
        doc=self.context();doc['updated_at']=(self.current+timedelta(seconds=1)).isoformat()
        row=dict(self.rows()[0],piyasa_rejimi='YATAY')
        active={'general':BASE,'approved':{},'regimes':{'GUCLU_YUKSELIS':dict(BASE,HACIM=BASE['HACIM']+.01,RSI=BASE['RSI']-.01)},
            'scope_approved':{'regimes':{'GUCLU_YUKSELIS':{'HACIM':{}}}}}
        class Fixed(datetime):
            @classmethod
            def now(cls,tz=None):return self.current
        with patch.object(bist_bot,'datetime',Fixed),patch.object(bist_bot,'yarin_potansiyel_hesapla',return_value=80):
            bist_bot.yarin_top10_listesi([row],kalibrasyon={'learning_enabled':True,'active':active,'shadow':{'general':BASE}},piyasa=doc)
        self.assertEqual(row['kalibrasyon_duzeltmesi'],0)
        self.assertEqual(row['final_puan'],80)

    def test_intraday_effect_limit_and_raw_preserved(self):
        from gun_ici_performans import GunIciPerformans
        doc=self.strong_relative();atomic_json(self.engine.file,doc)
        row=self.rows()[0];raw=row['gun_ici_puan']
        engine=GunIciPerformans(self.location,clock=lambda:self.current);engine.rank([row])
        self.assertEqual(row['gun_ici_puan'],raw);self.assertEqual(row['gun_ici_ham_puan'],raw)
        self.assertLessEqual(abs(row['gun_ici_final_puan']-raw),2.5)
        self.assertEqual(row['gun_ici_kalibrasyon_duzeltmesi'],0)

    def test_tomorrow_chain_preserves_calibration_and_raw(self):
        import bist_bot
        doc=self.strong_relative();row=self.rows()[0]
        class Fixed(datetime):
            @classmethod
            def now(cls,tz=None):return self.current
        with patch.object(bist_bot,'datetime',Fixed),patch.object(bist_bot,'yarin_potansiyel_hesapla',return_value=80):
            top=bist_bot.yarin_top10_listesi([row],kalibrasyon={'learning_enabled':False},piyasa=doc)
        self.assertEqual(row['ham_puan'],80);self.assertEqual(row['kalibrasyon_duzeltmesi'],0)
        self.assertAlmostEqual(row['final_puan'],80+row['piyasa_baglami_etkisi']);self.assertLessEqual(abs(top[0][0]-80),2.5)

    def test_learning_effect_and_market_effect_separate(self):
        from gun_ici_performans import BASE
        from gun_ici_performans import GunIciPerformans
        atomic_json(self.engine.file,self.strong_relative())
        engine=GunIciPerformans(self.location,clock=lambda:self.current)
        atomic_json(engine.weights_file,{'weights':dict(BASE,HACIM=BASE['HACIM']+.005),'approved':{'HACIM':{}},'version':'TEST','asof':self.current.isoformat()})
        row=self.rows()[0]
        with patch.dict(os.environ,{'GUN_ICI_LEARNING_ENABLED':'true'}):engine.rank([row])
        self.assertAlmostEqual(row['gun_ici_kalibrasyon_duzeltmesi'],.5)
        self.assertAlmostEqual(row['gun_ici_final_puan'],80+.5+row['piyasa_baglami_etkisi'])

    def test_shared_ai_explained_separate_contributions(self):
        doc=self.strong_relative();result=evaluate(self.rows()[0],market=doc,current=self.current)
        self.assertIn('breadth',result['katkilar']);self.assertIn('sektor_relatif_guc',result['katkilar'])
        self.assertTrue(any('sektörü piyasadan güçlü' in r for r in result['reasons_positive']))
        self.assertEqual(result['piyasa_rejimi_kaynagi'],'ORTAK_PIYASA_BAGLAMI')

    def test_shared_ai_negative_reasons_and_confidence(self):
        row=self.rows()[0];down=self.context(-3)
        result=evaluate(row,market=down,current=self.current)
        self.assertTrue(any('genişliği zayıf' in r for r in result['reasons_negative']))
        self.assertEqual(result['piyasa_baglami_katkilari']['piyasa_confidence_duzeltmesi'],-10)

    def test_context_alone_never_creates_buy_or_sell(self):
        row=self.rows()[0]
        for technical,context in ((78,self.context()),(30,self.context(-3))):
            row['teknik_puan']=technical
            result=evaluate(row,market=context,current=self.current)
            self.assertEqual(result['karar'],'IZLE')

    def test_hard_safety_and_levels(self):
        doc=self.strong_relative();row=self.rows()[0];annotate([row],doc);before=copy.deepcopy(row)
        for changes,raw in (({'haber_puani':-8},80),({'makro_puani':-8},80),({'rsi':80},80),({'degisim':6},80),({},-999),({},40)):
            r=dict(row,**changes);result=effects(r,raw,self.current,'YARIN')
            self.assertLessEqual(result['piyasa_baglami_etkisi'],0)
            self.assertEqual(r['yarin_stop'],before['yarin_stop']);self.assertEqual(r['yarin_kar_al'],before['yarin_kar_al'])

    def test_weak_technical_not_promoted(self):
        row=self.rows()[0];annotate([row],self.strong_relative())
        self.assertLessEqual(effects(row,60,self.current,'YARIN')['piyasa_baglami_etkisi'],0)

    def test_all_effects_configured_and_total_capped(self):
        with patch.dict(os.environ,{'MARKET_REGIME_MAX_EFFECT':'2','BREADTH_MAX_EFFECT':'2','SECTOR_RS_MAX_EFFECT':'2'}):
            doc=self.context();doc['sektorler']['A'].update(rs_score=100,confidence=100)
            row=self.rows()[0];annotate([row],doc);result=effects(row,80,self.current)
            self.assertLessEqual(abs(result['piyasa_baglami_etkisi']),3.000001)

    def test_config_limits_frozen_with_version(self):
        doc=self.context();row=self.rows()[0];annotate([row],doc);before=effects(row,80,self.current)
        with patch.dict(os.environ,{'MARKET_REGIME_MAX_EFFECT':'0'}):self.assertEqual(effects(row,80,self.current),before)

    def test_context_does_not_overwrite_macro_sector(self):
        row=dict(self.rows()[0],makro_sektor='LEGACY_MACRO')
        annotate([row],self.strong_relative())
        self.assertEqual(row['makro_sektor'],'LEGACY_MACRO')
        self.assertEqual(row['piyasa_sektoru'],'A')

    def test_unknown_regime_score_cannot_boost_ai_confidence(self):
        doc=self.context();doc.update(piyasa_rejimi='BELIRSIZ',rejim_confidence=25)
        result=evaluate(self.rows()[0],market=doc,current=self.current)
        doc['rejim_score']=None
        unknown=evaluate(self.rows()[0],market=doc,current=self.current)
        self.assertEqual(result['confidence'],unknown['confidence'])

    def test_future_market_doc_not_used_by_common_ai(self):
        doc=self.strong_relative();doc['updated_at']=(self.current+timedelta(seconds=1)).isoformat()
        result=evaluate(self.rows()[0],market=doc,current=self.current)
        self.assertEqual(result['piyasa_rejimi'],'BELIRSIZ')
        self.assertEqual(result['katkilar']['breadth'],0)
        self.assertEqual(result['katkilar']['sektor_relatif_guc'],0)

    def test_no_provider_request_and_refresh_throttle(self):
        atomic_json(self.location.public/'bist_data.json',{'hisseler':self.rows(),'bist100':self.index(),'updated_at':self.current.isoformat()})
        with patch('sektor_haritasi.bp.Ticker',side_effect=AssertionError('provider')),patch('bist_bot.bp.Index',side_effect=AssertionError('provider')):
            first=self.engine.refresh();self.assertEqual(first,self.engine.refresh())
        self.assertTrue(self.engine.file.exists())

    def test_missing_sector_map_does_not_crawl(self):
        (self.location.public/'sektor_haritasi.json').unlink()
        with patch('sektor_haritasi.bp.Ticker',side_effect=AssertionError('provider')):
            doc=self.engine.refresh(rows=self.rows(),universe=self.map,index=self.index())
        self.assertEqual(set(doc['sektorler']),{'BILINMIYOR'})

    def test_filtered_stream_stocks_used_for_breadth_without_reanalysis(self):
        import pandas as pd
        frame=pd.DataFrame({'Open':[100,100],'Close':[101,200]},index=pd.DatetimeIndex([self.current-timedelta(minutes=5),self.current]))
        quotes=intraday_quotes({'FILTERED':frame},[],self.current)
        self.assertEqual(quotes[0]['fiyat'],101);self.assertAlmostEqual(quotes[0]['acilisa_gore_degisim'],1)

    def test_index_fetch_reused_five_minutes(self):
        import bist_bot
        self.enterContext(patch.object(bist_bot,'DATA_FILE',str(self.location.public/'bist_data.json')))
        info={'last':100,'change_percent':1,'open':99,'high':101,'low':98,'volume':1000}
        with patch.object(bist_bot.bp,'Index',return_value=Mock(info=info)) as provider:
            bist_bot.web_verisi_kaydet([],list(self.map));bist_bot.web_verisi_kaydet([],list(self.map))
            provider.assert_called_once_with('XU100')
        self.assertIn('updated_at',json.loads((self.location.public/'bist_data.json').read_text())['bist100'])

    def test_intraday_snapshot_context_immutable(self):
        from gun_ici_performans import GunIciPerformans
        atomic_json(self.engine.file,self.strong_relative());row=self.rows()[0]
        intraday=GunIciPerformans(self.location,clock=lambda:self.current);intraday.rank([row]);intraday.record([row])
        frozen=copy.deepcopy(intraday.state()['kayitlar'][0]['piyasa_baglami'])
        atomic_json(self.engine.file,self.context(-3));self.current+=timedelta(minutes=5)
        updated=dict(row,veri_tarihi=(self.current-timedelta(minutes=5)).isoformat());intraday.rank([updated]);intraday.record([updated])
        self.assertEqual(intraday.state()['kayitlar'][0]['piyasa_baglami'],frozen)

    def test_common_ai_history_freezes_context(self):
        atomic_json(self.engine.file,self.strong_relative());engine=AIKararMotoru(self.location,clock=lambda:self.current)
        row=dict(self.rows()[0],teknik_puan=90,rsi=55,macd=1,signal=.5,hacim_orani=160,karar_rr=2,canli_guncelleme=self.current.isoformat())
        result=engine.batch(['S000'],[row])
        self.assertNotEqual(result['hisseler']['S000']['karar'],'IZLE')
        first=json.loads(engine.history_path.read_text())['kayitlar'][0]
        atomic_json(self.engine.file,self.context(-3));self.current+=timedelta(minutes=5);engine.batch(['S000'],[self.rows()[0]])
        self.assertEqual(json.loads(engine.history_path.read_text())['kayitlar'][0],first)
        self.assertIn('sektor_rs_score',first['piyasa_baglami'])

    def test_tomorrow_snapshot_carries_context_and_is_immutable(self):
        import bist_bot
        self.current=self.current.replace(hour=18,minute=15)
        rows=self.rows();atomic_json(self.location.public/'bist_data.json',{'hisseler':rows,'bist100':self.index(),'updated_at':self.current.isoformat()})
        self.enterContext(patch.object(bist_bot,'YARIN_TOP10_FILE',str(self.location.public/'yarin_top10.json')))
        self.enterContext(patch.object(bist_bot,'YARIN_TOP10_ARSIV_DIR',str(self.location.archives)))
        class Fixed(datetime):
            @classmethod
            def now(cls,tz=None):return self.current
        with patch.object(bist_bot,'datetime',Fixed),patch.object(bist_bot,'yarin_potansiyel_hesapla',return_value=80):
            saved=bist_bot.yarin_top10_kilitli_kaydet(rows,len(rows))
            self.assertIsNotNone(saved);ctx=saved['top10'][0]['tahmin']['piyasa_baglami']
            self.assertEqual(ctx['piyasa_rejimi'],'GUCLU_YUKSELIS')
            before=(self.location.archives/'2026-10-06.json').read_bytes()
            self.engine.refresh(rows=self.rows(-3),universe=self.map,index=self.index(-3),force=True)
            bist_bot.yarin_top10_kilitli_kaydet(self.rows(-3),60)
            self.assertEqual((self.location.archives/'2026-10-06.json').read_bytes(),before)

    def test_worker_market_task_no_price_fetch(self):
        from ana_motor_gorevleri import WorkerTasks
        with patch.object(PiyasaBaglami,'refresh',return_value={'ok':True}) as refresh:
            self.assertEqual(WorkerTasks.market_context(None),{'ok':True});refresh.assert_called_once_with()

    def test_scheduler_market_open_gate(self):
        from ana_motor import AnaMotor
        callback=Mock();self.current=self.current.replace(hour=20)
        worker=AnaMotor({'market_context':callback},directory=self.location.runtime,clock=lambda:self.current)
        try:worker.tick();callback.assert_not_called()
        finally:worker.shutdown()

    def test_public_http_report(self):
        from web_server import create_server
        self.engine.refresh(rows=self.rows(),universe=self.map,index=self.index())
        server=create_server('127.0.0.1',0,data_paths=self.location)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/data/piyasa_durumu.json') as response:
            self.assertEqual(json.load(response)['piyasa_rejimi'],'GUCLU_YUKSELIS')


if __name__=='__main__':unittest.main()
