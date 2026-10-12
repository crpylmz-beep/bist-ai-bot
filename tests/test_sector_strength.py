import copy,json,os,tempfile,threading,unittest,urllib.request,urllib.error
from datetime import datetime,timedelta
from unittest.mock import Mock,patch
from ai_karar_motoru import ISTANBUL
from veri_yollari import DataPaths
from kullanici_kayitlari import RecordError,atomic_json
from gorev_hatalari import TaskIssue
import piyasa_baglami as m

class SectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.location=DataPaths({'BIST_DATA_DIR':self.temp.name});self.location.ensure()
        self.enterContext(patch.dict(os.environ,{'BIST_DATA_DIR':self.temp.name,'SECTOR_STRENGTH_ENABLED':'true'}))
        self.now=datetime(2026,10,8,19,tzinfo=ISTANBUL);self.holiday=lambda _:False
        self.symbols=['S'+str(i).zfill(3) for i in range(12)]
        self.mapping={s:'BANK' if i<6 else 'TECH' for i,s in enumerate(self.symbols)}
        self.engine=m.PiyasaBaglami(self.location,lambda:self.now)
    def row(self,s='S000',side=1):
        close=100+side
        raw={'close':close,'previous_close':100,'open':100,'high':max(close,100)+1,'low':min(close,100)-1,
            'return_1d':side,'return_5d':side*6,'return_20d':side*12,'sma20':90 if side>0 else 110 if side<0 else 100,
            'sma50':80 if side>0 else 120 if side<0 else 100,'sma20_slope':side,'volume':1000,'return_3d':side,'rsi':60,'macd_histogram':side}
        return {'sembol':s,'teknik_gostergeler':{'mode':'TOMORROW','asof':self.now.isoformat(),'data_time':self.now.replace(hour=18,minute=15).isoformat(),'closing':raw}}
    def rows(self,side=1):return [self.row(s,side) for s in self.symbols]
    def build(self,rows=None,index=None,mapping=None,official=None,market=None):
        return m.build_sectors(self.rows() if rows is None else rows,self.symbols,self.mapping if mapping is None else mapping,self.row('XU100',0) if index is None else index,self.now,official,market,self.holiday)
    def sector(self,doc=None):return (doc or self.build())['sectors'][0]
    def publish(self,rows=None,index=None):
        atomic_json(self.location.public/'bist_data.json',{'hisseler':self.rows() if rows is None else rows})
        atomic_json(self.location.public/'sektor_haritasi.json',{'hisseler':{s:{'sektor':name} for s,name in self.mapping.items()}})
        return self.engine.refresh_sectors(self.symbols,self.row('XU100',0) if index is None else index,official={},holiday=self.holiday,discover=False)
    def test_xutum_filter(self):self.assertEqual(sum(s['valid_member_count'] for s in self.build(self.rows()+[self.row('FUND')])['sectors']),12)
    def test_normalization(self):
        rows=self.rows();rows[0]['sembol']='BIST:S000.IS';self.assertEqual(sum(v['valid_member_count'] for v in self.build(rows)['sectors']),12)
    def test_mapping(self):self.assertEqual(self.build()['stocks']['S000']['sector_name'],'BANK')
    def test_unknown(self):
        d=self.build(mapping={});self.assertEqual(d['sectors'][0]['sector_code'],'UNKNOWN');self.assertIsNone(d['stocks']['S000']['stock_relative_strength_score']);self.assertFalse(d['final'])
    def test_synthetic(self):self.assertEqual(self.sector()['benchmark_source'],'SYNTHETIC_MEMBERS')
    def test_official_verified_members(self):
        official={'BANK':{'verified':True,'members':self.symbols[:6],'observation':self.row('XBANK',-1)}}
        d=self.build(official=official);s=next(s for s in d['sectors'] if s['sector_name']=='BANK');self.assertEqual(s['benchmark_source'],'OFFICIAL_INDEX');self.assertEqual(s['sector_return_5d'],-6)
    def test_unverified_official_fallback(self):
        d=self.build(official={'BANK':{'verified':False,'members':self.symbols[:6],'observation':self.row('XBANK')}});self.assertEqual(next(s for s in d['sectors'] if s['sector_name']=='BANK')['benchmark_source'],'SYNTHETIC_MEMBERS')
    def test_wrong_official_members(self):
        d=self.build(official={'BANK':{'verified':True,'members':self.symbols,'observation':self.row('XBANK')}});self.assertTrue(all(s['benchmark_source']=='SYNTHETIC_MEMBERS' for s in d['sectors']))
    def test_xu100(self):self.assertEqual(self.sector()['benchmark'],'XU100')
    def test_wrong_main_index(self):self.assertIsNone(self.sector(self.build(index=self.row('XBANK')))['relative_strength_score'])
    def test_relative_1d(self):self.assertEqual(self.sector()['relative_strength_1d'],1)
    def test_relative_5d(self):self.assertEqual(self.sector()['relative_strength_5d'],6)
    def test_relative_20d(self):self.assertEqual(self.sector()['relative_strength_20d'],12)
    def test_rs_fixed_weights(self):
        score,parts=m.relative_score({1:2,5:5,20:10});self.assertEqual(score,100);self.assertEqual(parts,{'1':10,'5':17.5,'20':22.5})
    def test_daily_spike_capped(self):self.assertEqual(m.relative_score({1:10000,5:0,20:0})[0],60)
    def test_missing_long_no_daily_takeover(self):self.assertIsNone(m.relative_score({1:10000,5:None,20:None})[0])
    def test_missing_daily_fixed_weight(self):self.assertEqual(m.relative_score({1:None,5:5,20:10})[0],90)
    def test_positive_trend(self):self.assertEqual(self.sector()['trend_state'],'POSITIVE')
    def test_neutral_trend(self):self.assertEqual(self.sector(self.build(self.rows(0)))['trend_state'],'NEUTRAL')
    def test_negative_trend(self):self.assertEqual(self.sector(self.build(self.rows(-1)))['trend_state'],'NEGATIVE')
    def test_improving_momentum(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing'].update(return_5d=-1,return_20d=-2)
        self.assertEqual(self.sector(self.build(rows))['momentum_state'],'IMPROVING')
    def test_weakening_momentum(self):
        rows=self.rows(-1)
        for r in rows:r['teknik_gostergeler']['closing'].update(return_5d=6,return_20d=12)
        self.assertEqual(self.sector(self.build(rows))['momentum_state'],'WEAKENING')
    def test_advancing(self):self.assertEqual(self.sector()['advancing_count'],6)
    def test_declining(self):self.assertEqual(self.sector(self.build(self.rows(-1)))['declining_count'],6)
    def test_unchanged(self):self.assertEqual(self.sector(self.build(self.rows(0)))['unchanged_count'],6)
    def test_sma20(self):self.assertEqual(self.sector()['above_sma20_pct'],100)
    def test_sma50_own_denominator(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['closing']['sma50']=None
        s=next(v for v in self.build(rows)['sectors'] if v['sector_name']=='BANK');self.assertEqual(s['sample_counts']['sma50'],5);self.assertEqual(s['above_sma50_pct'],100)
    def test_volume_coverage(self):
        rows=self.rows()
        for r in rows[:3]:r['teknik_gostergeler']['closing']['volume']=None
        s=next(v for v in self.build(rows)['sectors'] if v['sector_name']=='BANK');self.assertIsNone(s['volume_strength'])
    def test_volume_strong(self):self.assertEqual(self.sector()['volume_strength'],'STRONG')
    def test_volume_weak(self):self.assertEqual(self.sector(self.build(self.rows(-1)))['volume_strength'],'WEAK')
    def test_volume_zero(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing']['volume']=0
        self.assertIsNone(self.sector(self.build(rows))['volume_strength'])
    def test_low_coverage(self):
        d=self.build(self.rows()[:3]);s=next(v for v in d['sectors'] if v['sector_name']=='BANK');self.assertIsNone(s['sector_state']);self.assertLessEqual(s['sector_confidence'],40)
    def test_confidence_separate_direction(self):self.assertEqual(self.sector()['sector_confidence'],self.sector(self.build(self.rows(-1)))['sector_confidence'])
    def test_conflicting_evidence_confidence(self):
        rows=self.rows(-1)
        for r in rows:r['teknik_gostergeler']['closing'].update(return_5d=6,return_20d=12)
        self.assertLess(self.sector(self.build(rows))['sector_confidence'],self.sector()['sector_confidence'])
    def test_leading_state(self):self.assertEqual(self.sector()['sector_state'],'LEADING')
    def test_neutral_state(self):self.assertEqual(self.sector(self.build(self.rows(0)))['sector_state'],'NEUTRAL')
    def test_lagging_state(self):self.assertEqual(self.sector(self.build(self.rows(-1)))['sector_state'],'LAGGING')
    def test_strong_state(self):
        rows=self.rows()
        for r in rows:r['teknik_gostergeler']['closing'].update(return_5d=1,return_20d=2,sma20_slope=0)
        self.assertEqual(self.sector(self.build(rows))['sector_state'],'STRONG')
    def test_weak_state(self):
        rows=self.rows(-1)
        for r in rows:r['teknik_gostergeler']['closing'].update(return_5d=-1,return_20d=-2,sma20_slope=0)
        self.assertEqual(self.sector(self.build(rows))['sector_state'],'WEAK')
    def test_leading_quadrant(self):self.assertEqual(m.rrg_quadrant(70,.3),'LEADING')
    def test_weakening_quadrant(self):self.assertEqual(m.rrg_quadrant(70,-.3),'WEAKENING')
    def test_lagging_quadrant(self):self.assertEqual(m.rrg_quadrant(30,-.3),'LAGGING')
    def test_improving_quadrant(self):self.assertEqual(m.rrg_quadrant(30,.3),'IMPROVING')
    def test_stock_vs_sector(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['closing'].update(return_5d=12,return_20d=24)
        stock=self.build(rows)['stocks']['S000'];self.assertEqual(stock['vs_sector_5d'],5);self.assertGreater(stock['stock_relative_strength_score'],50)
    def test_alignment(self):self.assertEqual(m.alignment(90,'LEADING','STRONG_BULL'),'STRONG_ALIGNMENT');self.assertEqual(m.alignment(70,'STRONG','BULL'),'POSITIVE_ALIGNMENT')
    def test_alignment_negative_mixed(self):self.assertEqual(m.alignment(20,'LAGGING','BEAR'),'NEGATIVE_ALIGNMENT');self.assertEqual(m.alignment(90,'LAGGING','BULL'),'MIXED')
    def test_top_stocks(self):self.assertEqual(len(self.sector()['top_stocks']),5)
    def test_lagging_stocks(self):self.assertEqual(len(self.sector()['lagging_stocks']),5)
    def test_top_rank_not_input_order(self):
        rows=self.rows();rows[5]['teknik_gostergeler']['closing'].update(return_5d=12,return_20d=24)
        s=next(v for v in self.build(rows)['sectors'] if v['sector_name']=='BANK');self.assertEqual(s['top_stocks'][0]['symbol'],'S005');self.assertNotEqual(s['lagging_stocks'][0]['symbol'],'S005')
    def test_stale_view(self):
        p=self.build();view=m.sector_view(p,self.now+timedelta(days=1),self.holiday);self.assertTrue(view['stale']);self.assertEqual(view['sectors'][0]['sector_confidence'],0);self.assertEqual(p['sectors'][0]['sector_confidence'],100)
    def test_open_daily(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['data_time']=self.now.replace(hour=14).isoformat()
        self.assertEqual(sum(v['valid_member_count'] for v in self.build(rows)['sectors']),11)
    def test_future_source(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['asof']=(self.now+timedelta(days=1)).isoformat();self.assertEqual(sum(v['valid_member_count'] for v in self.build(rows)['sectors']),11)
    def test_duplicate_conflict(self):self.assertEqual(sum(v['valid_member_count'] for v in self.build(self.rows()+[self.row('S000',-1)])['sectors']),11)
    def test_one_bad_optional_value(self):
        rows=self.rows();rows[0]['teknik_gostergeler']['closing']['sma20']='bad';d=self.build(rows);self.assertFalse(d['failures']);self.assertEqual(sum(v['valid_member_count'] for v in d['sectors']),12)
    def test_one_sector_failure(self):
        original=m.sector_metrics
        def fail(name,*args,**kwargs):
            if name=='BANK':raise RuntimeError('sector calculation bug')
            return original(name,*args,**kwargs)
        with patch('piyasa_baglami.sector_metrics',side_effect=fail):d=self.build()
        self.assertEqual(d['sectors'][0]['sector_name'],'TECH');self.assertEqual(len(d['failures']),1);self.assertFalse(d['final'])
    def test_immutable(self):
        self.publish();p=self.location.runtime/'sector_context/2026-10-08.json';before=p.read_bytes();self.publish(self.rows(-1));self.assertEqual(p.read_bytes(),before)
    def test_no_closed_rewrite(self):
        self.publish();p=self.location.public/'sector_context.json';before=p.stat().st_mtime_ns;self.now+=timedelta(minutes=5);self.publish();self.assertEqual(p.stat().st_mtime_ns,before)
    def test_paths(self):self.publish();self.assertTrue((self.location.runtime/'sector_context/2026-10-08.json').exists());self.assertTrue((self.location.public/'sector_context.json').exists())
    def test_atomic_preserves_previous(self):
        self.publish();p=self.location.public/'sector_context.json';before=p.read_bytes();self.now+=timedelta(days=1)
        with patch('kullanici_kayitlari.os.replace',side_effect=OSError('fail')):
            with self.assertRaises(OSError):self.publish()
        self.assertEqual(p.read_bytes(),before)
    def test_corrupt_archive_not_overwritten(self):
        self.publish();p=self.location.runtime/'sector_context/2026-10-08.json';p.write_text('{bad')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(p.read_text(),'{bad')
    def test_corrupt_public_503(self):
        (self.location.public/'sector_context.json').write_text('{bad')
        with self.assertRaises(RecordError) as c:self.engine.sectors()
        self.assertEqual(c.exception.status,503)
    def test_missing_public_503(self):
        with self.assertRaises(RecordError) as c:self.engine.sectors()
        self.assertEqual(c.exception.status,503)
    def test_corrupt_shape_503(self):
        d=self.build();d['sectors'][0]['member_count']='bad';atomic_json(self.location.public/'sector_context.json',d)
        with self.assertRaises(RecordError) as c:self.engine.sectors()
        self.assertEqual(c.exception.status,503)
    def test_flag_default_true(self):
        with patch.dict(os.environ,{},clear=True):self.assertTrue(m.sector_enabled())
    def test_flag_false_no_read(self):
        with patch.dict(os.environ,{'SECTOR_STRENGTH_ENABLED':'false'}):self.assertFalse(self.engine.sectors()['enabled']);self.assertFalse(self.engine.refresh_sectors()['enabled']);self.assertIsNone(m.stock_sector_view('S000',self.location,self.now))
    def test_api_all(self):self.publish();self.assertEqual(len(self.engine.sectors()['sectors']),2)
    def test_api_sector(self):self.publish();self.assertEqual(self.engine.sectors({'sector':['BANK']})['sectors'][0]['sector_name'],'BANK')
    def test_api_symbol(self):self.publish();self.assertEqual(self.engine.sectors({'symbol':['S000']})['stock_sector_context']['symbol'],'S000')
    def test_api_invalid_queries(self):
        for query in ({'sector':['']},{'symbol':['bad!']},{'sector':['BANK','TECH']},{'foo':['x']},{'symbol':['S000'],'sector':['BANK']}):
            with self.assertRaises(RecordError) as c:self.engine.sectors(query)
            self.assertEqual(c.exception.status,400)
    def test_api_unknown_filter(self):
        self.publish()
        with self.assertRaises(RecordError) as c:self.engine.sectors({'sector':['missing']})
        self.assertEqual(c.exception.status,400)
    def test_market_frozen_reference(self):
        market={'engine_version':m.MEASUREMENT_VERSION,'as_of':self.now.replace(hour=18,minute=15).isoformat(),'created_at':self.now.isoformat(),'final':True,'regime':'BULL','regime_score':70,'breadth_score':65,'risk_state':'NORMAL'}
        d=self.build(market=market);market['regime']='BEAR';self.assertEqual(d['market_context']['market_regime'],'BULL')
    def test_frozen_helper(self):
        d=self.build();c=m.frozen_sector_context(d,'S000',self.now);d['stocks']['S000']['sector_state']='LAGGING';self.assertEqual(c['sector_state'],'LEADING')
    def test_frozen_future_rejected(self):
        d=self.build();self.assertEqual(m.frozen_sector_context(d,'S000',self.now-timedelta(seconds=1)),{})
    def test_frozen_knowledge_time(self):
        d=self.build();d['created_at']=(self.now+timedelta(seconds=30)).isoformat();self.assertEqual(m.frozen_sector_context(d,'S000',self.now),{})
    def test_frozen_stale_rejected(self):self.assertEqual(m.frozen_sector_context(self.build(),'S000',self.now+timedelta(days=1)),{})
    def test_input_snapshots_unchanged(self):
        rows=self.rows();before=copy.deepcopy(rows);self.build(rows);self.assertEqual(rows,before)
    def test_disk_compact_no_series(self):
        d=self.publish();raw=json.dumps(d);self.assertNotIn('teknik_gostergeler',raw);self.assertNotIn('Close',raw);self.assertLess(len(raw),50000)
    def test_provider_partial_failure(self):
        atomic_json(self.location.public/'bist_data.json',{'hisseler':self.rows()})
        atomic_json(self.location.public/'sektor_haritasi.json',{'hisseler':{s:{'sektor':n} for s,n in self.mapping.items()}})
        with patch('bist_bot.bp.indices',return_value=['XAAA','XBBB']),patch('bist_bot.bp.Index') as provider:
            provider.return_value.components=[{'symbol':'OTHER'}]
            provider.side_effect=[ConnectionError('remote unavailable'),provider.return_value]
            result=self.engine.refresh_sectors(self.symbols,self.row('XU100',0),holiday=self.holiday)
            self.assertEqual(result['diagnostics']['successful'],2);self.assertEqual(result['diagnostics']['skipped'],1)
            self.assertEqual(result['source_issues'][0]['code'],'NETWORK_CONNECTION')
            self.assertEqual(result['source_issues'][0]['symbol'],'XAAA')
        self.assertEqual(len(json.loads((self.location.public/'sector_context.json').read_text())['sectors']),2)
    def test_discovery_official_membership(self):
        with patch('bist_bot.bp.indices',return_value=['XBANK']),patch('bist_bot.bp.Index') as provider,patch('teknik_gostergeler.calculate',return_value=self.row('XBANK')['teknik_gostergeler']):
            provider.return_value.components=[{'symbol':s} for s in self.symbols[:6]]
            official,issues=m.sector_indices(self.location,set(self.symbols),self.mapping,self.now,self.holiday)
            self.assertFalse(issues);self.assertTrue(official['BANK']['verified']);self.assertEqual(provider.return_value.history.call_count,1)
            m.sector_indices(self.location,set(self.symbols),self.mapping,self.now,self.holiday);self.assertEqual(provider.return_value.history.call_count,1)
    def test_discovery_no_guessed_mapping(self):
        with patch('bist_bot.bp.indices',return_value=['XBANK']),patch('bist_bot.bp.Index') as provider:
            provider.return_value.components=[{'symbol':'OTHER'}]
            official,_=m.sector_indices(self.location,set(self.symbols),self.mapping,self.now,self.holiday);self.assertEqual(official,{});provider.return_value.history.assert_not_called()
    def test_no_stock_or_main_benchmark_fetch(self):
        with patch('bist_bot.bp.Ticker') as ticker,patch('bist_bot.bp.Index') as index:self.publish();ticker.assert_not_called();index.assert_not_called()
    def test_worker_registered(self):
        from ana_motor_gorevleri import WorkerTasks
        adapter=WorkerTasks();self.addCleanup(adapter.close);self.assertIn('sector_strength',adapter.callbacks())
    def test_worker_disabled(self):
        from ana_motor_gorevleri import WorkerTasks
        adapter=WorkerTasks();self.addCleanup(adapter.close)
        with patch.dict(os.environ,{'SECTOR_STRENGTH_ENABLED':'false'}):self.assertNotIn('sector_strength',adapter.callbacks())
    def test_worker_fault_isolated(self):
        from ana_motor import AnaMotor
        alarm=Mock(return_value=0);worker=AnaMotor({'sector_strength':Mock(side_effect=RuntimeError('bug')),'alarm':alarm},self.location.runtime,clock=lambda:self.now)
        try:
            worker.tick()
            for t in worker.tasks.values():
                if t.future:
                    try:t.future.result(timeout=5)
                    except RuntimeError:pass
            worker.tick();self.assertTrue(alarm.called);self.assertIn(worker.state['tasks']['sector_strength']['status'],('ERROR','RETRYING'))
        finally:worker.shutdown()
    def test_worker_flag_runtime(self):
        from ana_motor import AnaMotor
        callback=Mock();worker=AnaMotor({'sector_strength':callback},self.location.runtime,clock=lambda:self.now)
        try:
            with patch.dict(os.environ,{'SECTOR_STRENGTH_ENABLED':'false'}):worker.tick()
            callback.assert_not_called()
        finally:worker.shutdown()
    def test_created_after_calculation(self):
        atomic_json(self.location.public/'bist_data.json',{'hisseler':self.rows()})
        atomic_json(self.location.public/'sektor_haritasi.json',{'hisseler':{s:{'sektor':n} for s,n in self.mapping.items()}})
        finish=self.now+timedelta(seconds=30);clock=Mock(side_effect=[self.now,finish,finish])
        doc=m.PiyasaBaglami(self.location,clock).refresh_sectors(self.symbols,self.row('XU100',0),official={},holiday=self.holiday,discover=False)
        self.assertEqual(doc['created_at'],finish.isoformat());self.assertEqual(m.frozen_sector_context(doc,'S000',self.now),{})
    def test_corrupt_stock_cache(self):
        d=self.build();d['stocks']['S000']='bad';atomic_json(self.location.public/'sector_context.json',d)
        with self.assertRaises(RecordError) as c:self.engine.sectors({'symbol':['S000']})
        self.assertEqual(c.exception.status,503)
    def test_sector_code_failure_not_disguised_as_provider(self):
        original=m.sector_metrics
        def fail(name,*args,**kwargs):
            if name=='BANK':raise ValueError('real code error')
            return original(name,*args,**kwargs)
        with patch('piyasa_baglami.sector_metrics',side_effect=fail):
            with self.assertRaises(TaskIssue) as issue:self.publish()
        self.assertEqual(issue.exception.issue['code'],'CODE_ERROR');self.assertEqual(len(json.loads((self.location.public/'sector_context.json').read_text())['sectors']),1)
    def test_http_endpoint(self):
        import web_server
        self.publish();server=web_server.create_server('127.0.0.1',0,data_paths=self.location);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with patch('piyasa_baglami.datetime') as clock:
                clock.now.return_value=self.now;clock.combine=datetime.combine
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/sector-strength?symbol=S000') as r:d=json.load(r)
            self.assertEqual(d['stock_sector_context']['symbol'],'S000')
        finally:server.shutdown();server.server_close();thread.join()
    def frame(self):
        import pandas as pd
        from performans_motoru import business_day
        dates=[d for d in pd.bdate_range(end='2026-10-08',periods=70,tz=ISTANBUL) if business_day(d.date())];prices=list(range(100,100+len(dates)))
        return pd.DataFrame({'Open':prices,'High':[p+1 for p in prices],'Low':[p-1 for p in prices],'Close':prices,'Volume':[1000]*len(prices)},index=dates)
    def test_real_session_horizons(self):
        from teknik_gostergeler import calculate
        frame=self.frame();doc=calculate(frame,self.now,'TOMORROW')['closing']
        for h in (1,5,20):self.assertAlmostEqual(doc[f'return_{h}d'],(frame.Close.iloc[-1]/frame.Close.iloc[-h-1]-1)*100)
    def test_missing_session_not_compressed(self):
        from teknik_gostergeler import calculate
        frame=self.frame().drop(self.frame().index[-3]);closing=calculate(frame,self.now,'TOMORROW')['closing'];self.assertIsNone(closing['return_5d']);self.assertIsNone(closing['return_20d']);self.assertIsNotNone(closing['return_1d'])
    def test_future_bar_no_lookahead(self):
        import pandas as pd
        from teknik_gostergeler import calculate
        frame=self.frame();before=calculate(frame,self.now,'TOMORROW')['closing'];frame.loc[pd.Timestamp('2026-10-09',tz=ISTANBUL)]=[900,1000,800,950,1e9];self.assertEqual(calculate(frame,self.now,'TOMORROW')['closing'],before)
    def test_open_bar_excluded(self):
        from teknik_gostergeler import calculate
        frame=self.frame();doc=calculate(frame,self.now.replace(hour=14),'TOMORROW')['closing'];self.assertEqual(doc['close'],frame.Close.iloc[-2])
    def legacy_rows(self):
        rows=self.rows()
        for row in rows:
            for h in (1,5,20):row['teknik_gostergeler']['closing'].pop(f'return_{h}d')
        return rows
    def seed(self,rows=None):
        atomic_json(self.location.public/'bist_data.json',{'hisseler':self.rows() if rows is None else rows})
        atomic_json(self.location.public/'sektor_haritasi.json',{'hisseler':{s:{'sektor':n} for s,n in self.mapping.items()}})
    def test_legacy_seed_reproduces_provider_data(self):
        self.seed(self.legacy_rows())
        with self.assertLogs(level='INFO') as logs:
            with self.assertRaises(TaskIssue) as issue:self.engine.refresh_sectors(self.symbols,self.row('XU100',0),official={},holiday=self.holiday,discover=False)
        self.assertEqual(issue.exception.issue['code'],'PROVIDER_DATA');self.assertTrue(any('usable_history_count=0' in line and 'valid_sector_count=0' in line for line in logs.output))
    def test_valid_partial_not_final_is_usable(self):
        rows=self.rows()
        for r in rows[:3]:r['teknik_gostergeler']['closing']['return_20d']=None
        result=self.publish(rows);self.assertFalse(result['final']);self.assertEqual(result['diagnostics']['successful'],1);self.assertEqual(result['diagnostics']['skipped'],1)
        bank=next(s for s in result['sectors'] if s['sector_name']=='BANK');self.assertEqual(bank['sample_counts']['return_20d'],3);self.assertIsNone(bank['sector_state']);self.assertFalse((self.location.runtime/'sector_context/2026-10-08.json').exists())
    def test_valid_partial_completes_later_without_overwrite(self):
        rows=self.rows()
        for r in rows[:3]:r['teknik_gostergeler']['closing']['return_20d']=None
        self.publish(rows);self.publish();path=self.location.runtime/'sector_context/2026-10-08.json';before=path.read_bytes();self.publish(self.rows(-1));self.assertEqual(path.read_bytes(),before)
    def test_no_usable_sector_still_degraded(self):
        self.seed([])
        with self.assertRaises(TaskIssue) as issue:self.engine.refresh_sectors(self.symbols,self.row('XU100',0),official={},holiday=self.holiday,discover=False)
        self.assertEqual(issue.exception.issue['code'],'PROVIDER_DATA')
    def test_benchmark_cache_upgrade(self):
        old=self.row('XU100',0)
        for h in (1,5,20):old['teknik_gostergeler']['closing'].pop(f'return_{h}d')
        p=self.location.runtime/'market_context_index.json';atomic_json(p,old)
        with patch('bist_bot.bp.Index') as provider,patch('teknik_gostergeler.calculate',return_value=self.row('XU100',0)['teknik_gostergeler']):
            index,issue=m.sector_benchmark(self.location,self.now,self.holiday);self.assertIsNone(issue);self.assertEqual(index['teknik_gostergeler']['closing']['return_20d'],0)
            m.sector_benchmark(self.location,self.now,self.holiday);self.assertEqual(provider.return_value.history.call_count,1)
    def test_missing_benchmark_bootstraps_real_history(self):
        with patch('bist_bot.bp.Index') as provider:
            provider.return_value.history.return_value=self.frame()
            index,issue=m.sector_benchmark(self.location,self.now,self.holiday)
        self.assertIsNone(issue);self.assertTrue(m.sector_history_usable(m.closed_observation(index,self.now,self.holiday)))
    def test_complete_benchmark_no_provider_call(self):
        atomic_json(self.location.runtime/'market_context_index.json',self.row('XU100',0))
        with patch('bist_bot.bp.Index') as provider:
            index,issue=m.sector_benchmark(self.location,self.now,self.holiday);self.assertIsNone(issue);provider.assert_not_called()
    def test_benchmark_failure_preserves_old_cache(self):
        p=self.location.runtime/'market_context_index.json';atomic_json(p,self.row('XU100',0));before=p.read_bytes()
        self.now+=timedelta(days=1)
        with patch('bist_bot.bp.Index') as provider:
            provider.return_value.history.side_effect=ConnectionError('source failure');index,issue=m.sector_benchmark(self.location,self.now,self.holiday)
        self.assertEqual(index,{});self.assertEqual(issue['code'],'NETWORK_CONNECTION');self.assertEqual(p.read_bytes(),before)
    def test_empty_benchmark_format(self):
        import pandas as pd
        with patch('bist_bot.bp.Index') as provider:
            provider.return_value.history.return_value=pd.DataFrame();index,issue=m.sector_benchmark(self.location,self.now,self.holiday)
        self.assertEqual(index,{});self.assertEqual(issue['code'],'PROVIDER_DATA')
    def test_wrong_history_columns_not_fabricated(self):
        f=self.frame().rename(columns=str.lower)
        with patch('bist_bot.bp.Index') as provider:
            provider.return_value.history.return_value=f;index,issue=m.sector_benchmark(self.location,self.now,self.holiday)
        self.assertFalse(index);self.assertEqual(issue['code'],'PROVIDER_DATA')
    def test_market_final_archive_unchanged_during_cache_upgrade(self):
        symbols=['S'+str(i).zfill(3) for i in range(60)];rows=[self.row(s) for s in symbols]
        old=self.row('XU100',0)
        for h in (1,5,20):old['teknik_gostergeler']['closing'].pop(f'return_{h}d')
        market=m.build_measurement(rows,symbols,old,self.now,self.holiday);self.assertTrue(market['final'])
        p=self.location.runtime/'market_context/2026-10-08.json';p.parent.mkdir();atomic_json(p,market);before=p.read_bytes();atomic_json(self.location.runtime/'market_context_index.json',old)
        with patch('bist_bot.bp.Index') as provider,patch('teknik_gostergeler.calculate',return_value=self.row('XU100',0)['teknik_gostergeler']):
            self.engine.refresh_measurement(symbols,holiday=self.holiday);provider.assert_not_called()
            m.sector_benchmark(self.location,self.now,self.holiday);self.assertEqual(provider.return_value.history.call_count,1)
        self.assertEqual(p.read_bytes(),before)
    def test_bootstrap_queue_bounded(self):
        callback=Mock();count=m.sector_bootstrap(self.location,self.legacy_rows(),set(self.symbols),self.mapping,self.now,callback,self.holiday)
        self.assertEqual(count,10);self.assertEqual(callback.call_count,10);self.assertEqual(callback.call_args_list[0].kwargs,{'gun_ici_yenile':False})
    def test_bootstrap_queue_rotates(self):
        callback=Mock();m.sector_bootstrap(self.location,self.legacy_rows(),set(self.symbols),self.mapping,self.now,callback,self.holiday);callback.reset_mock()
        m.sector_bootstrap(self.location,self.legacy_rows(),set(self.symbols),self.mapping,self.now+timedelta(minutes=5),callback,self.holiday)
        self.assertEqual(callback.call_args_list[0].args[0],'S010');self.assertEqual(callback.call_args_list[1].args[0],'S011')
    def test_bootstrap_no_duplicate_within_round(self):
        callback=Mock();m.sector_bootstrap(self.location,self.legacy_rows(),set(self.symbols),self.mapping,self.now,callback,self.holiday)
        self.assertEqual(m.sector_bootstrap(self.location,self.legacy_rows(),set(self.symbols),self.mapping,self.now,callback,self.holiday),0);self.assertEqual(callback.call_count,10)
    def test_bootstrap_unknown_not_queued(self):
        callback=Mock();self.assertEqual(m.sector_bootstrap(self.location,self.legacy_rows(),set(self.symbols),{},self.now,callback,self.holiday),0);callback.assert_not_called()
    def test_bootstrap_existing_fresh_data_not_queued(self):
        callback=Mock();self.assertEqual(m.sector_bootstrap(self.location,self.rows(),set(self.symbols),self.mapping,self.now,callback,self.holiday),0)
    def test_bootstrap_advances_to_real_worker_result(self):
        self.seed(self.legacy_rows());callback=Mock()
        with self.assertLogs(level='INFO') as logs:
            with self.assertRaises(TaskIssue):self.engine.refresh_sectors(self.symbols,self.row('XU100',0),official={},holiday=self.holiday,discover=False,enqueue=callback)
        self.assertEqual(callback.call_count,10);self.assertTrue(any('stage=MEMBER_HISTORY' in s and 'queued=10' in s for s in logs.output))
        self.seed(self.rows());result=self.engine.refresh_sectors(self.symbols,self.row('XU100',0),official={},holiday=self.holiday,discover=False,enqueue=callback);self.assertEqual(result['diagnostics']['successful'],2)
    def test_unmapped_source_logged_without_benchmark_fetch(self):
        self.seed();atomic_json(self.location.public/'sektor_haritasi.json',{'hisseler':{}})
        with patch('bist_bot.bp.Index') as provider,self.assertLogs(level='INFO') as logs:
            with self.assertRaises(TaskIssue):self.engine.refresh_sectors(self.symbols,official={},holiday=self.holiday,discover=False)
        provider.assert_not_called();self.assertTrue(any('stage=MAPPING' in line and 'mapped_member_count=0' in line for line in logs.output))
    def test_official_incomplete_uses_valid_synthetic(self):
        row=self.row('XBANK');row['teknik_gostergeler']['closing'].pop('return_20d')
        official={'BANK':{'verified':True,'members':self.symbols[:6],'observation':row}}
        self.assertEqual(next(s for s in self.build(official=official)['sectors'] if s['sector_name']=='BANK')['benchmark_source'],'SYNTHETIC_MEMBERS')
    def test_optional_empty_catalogue_entry_fallback(self):
        self.seed()
        with patch('bist_bot.bp.indices',return_value=['XAAA']),patch('bist_bot.bp.Index') as provider:
            provider.return_value.components=[];result=self.engine.refresh_sectors(self.symbols,self.row('XU100',0),holiday=self.holiday)
        self.assertEqual(result['diagnostics']['successful'],2);self.assertEqual(result['source_issues'][0]['stage'],'INDEX_MEMBERSHIP');self.assertEqual(result['source_issues'][0]['code'],'PROVIDER_DATA')
    def test_optional_empty_index_history_fallback(self):
        import pandas as pd
        self.seed()
        with patch('bist_bot.bp.indices',return_value=['XBANK']),patch('bist_bot.bp.Index') as provider:
            provider.return_value.components=[{'symbol':s} for s in self.symbols[:6]];provider.return_value.history.return_value=pd.DataFrame();result=self.engine.refresh_sectors(self.symbols,self.row('XU100',0),holiday=self.holiday)
        self.assertEqual(result['diagnostics']['successful'],2);self.assertEqual(result['source_issues'][0]['stage'],'INDEX_HISTORY');self.assertTrue(all(s['benchmark_source']=='SYNTHETIC_MEMBERS' for s in result['sectors']))
    def test_optional_critical_error_not_swallowed(self):
        self.seed()
        with patch('piyasa_baglami.sector_indices',return_value=({},[{'code':'CODE_ERROR','symbol':'XBANK'}])):
            with self.assertRaises(TaskIssue) as issue:self.engine.refresh_sectors(self.symbols,self.row('XU100',0),holiday=self.holiday)
        self.assertEqual(issue.exception.issue['code'],'CODE_ERROR')
    def test_worker_forwards_existing_enqueue(self):
        from ana_motor_gorevleri import WorkerTasks
        adapter=WorkerTasks();self.addCleanup(adapter.close)
        with patch('piyasa_baglami.PiyasaBaglami') as engine:
            adapter.sector_strength();self.assertEqual(engine.return_value.refresh_sectors.call_args.kwargs['enqueue'],adapter.enqueue)
    def test_scheduler_reports_successful_fallback_with_skips(self):
        from ana_motor import AnaMotor
        rows=self.rows()
        for row in rows[:3]:row['teknik_gostergeler']['closing']['return_20d']=None
        worker=AnaMotor({'sector_strength':lambda:self.publish(rows)},self.location.runtime,clock=lambda:self.now)
        try:
            worker.tick();worker.tasks['sector_strength'].future.result(timeout=10);worker.tick()
            self.assertEqual(worker.state['tasks']['sector_strength']['status'],'OK_WITH_SKIPS')
            self.assertEqual(worker.state['tasks']['sector_strength']['diagnostics']['successful'],1)
        finally:worker.shutdown()
    def test_scheduler_keeps_no_data_degraded(self):
        from ana_motor import AnaMotor
        worker=AnaMotor({'sector_strength':lambda:self.publish(self.legacy_rows())},self.location.runtime,clock=lambda:self.now)
        try:
            worker.tick()
            with self.assertRaises(TaskIssue):worker.tasks['sector_strength'].future.result(timeout=10)
            worker.tick();self.assertEqual(worker.state['tasks']['sector_strength']['status'],'DEGRADED');self.assertEqual(worker.state['tasks']['sector_strength']['last_error']['code'],'PROVIDER_DATA')
        finally:worker.shutdown()
    def test_low_confidence_sector_counted_as_skip(self):
        self.symbols=['S'+str(i).zfill(3) for i in range(14)];self.mapping={s:'BANK' if i<8 else 'TECH' for i,s in enumerate(self.symbols)}
        rows=self.rows()[:5]+self.rows()[8:]
        for r in rows[:5]:r['teknik_gostergeler']['closing'].update(sma20=None,sma50=None,volume=None)
        result=self.publish(rows);self.assertEqual(result['diagnostics']['successful'],1);self.assertEqual(result['diagnostics']['skipped'],1)
        bank=next(s for s in result['sectors'] if s['sector_name']=='BANK');self.assertIsNone(bank['sector_state']);self.assertLess(bank['sector_confidence'],50)
    def test_unusable_states_not_frozen(self):
        self.symbols=self.symbols[:8];self.mapping={s:'BANK' for s in self.symbols};rows=self.rows()[:5]
        for r in rows:r['teknik_gostergeler']['closing'].update(sma20=None,sma50=None,volume=None)
        with self.assertRaises(TaskIssue):self.publish(rows)
        doc=json.loads((self.location.public/'sector_context.json').read_text());self.assertFalse(doc['final']);self.assertFalse((self.location.runtime/'sector_context/2026-10-08.json').exists())
    def test_sector_trace_has_safe_counts_and_codes(self):
        with self.assertLogs(level='INFO') as logs:m.sector_trace('PARTIAL_FALLBACK',self.build(),set(self.symbols),self.mapping,{'code':'PROVIDER_DATA','secret':'NEVER_LOG'})
        line=logs.output[0]
        for field in ('benchmark_source=','valid_sector_count=2','xutum_member_count=12','mapped_member_count=12','usable_history_count=12','code=PROVIDER_DATA'):self.assertIn(field,line)
        self.assertNotIn('NEVER_LOG',line)
    def test_legacy_formula_unchanged(self):
        before=m.build_context([],[],{}, {},self.now);self.publish();self.assertEqual(m.build_context([],[],{}, {},self.now),before)
    def test_old_prediction_history_untouched(self):
        p=self.location.runtime/'tahmin_gecmisi.json';p.write_bytes(b'{"old_prediction":{"price":123,"rank":1,"score":88}}');before=p.read_bytes();self.publish();self.assertEqual(p.read_bytes(),before)
    def test_small_sector_stays_insufficient_without_blocking_final(self):
        mapping=dict(self.mapping);mapping['S000']='SMALL';d=self.build(mapping=mapping);self.assertTrue(d['final']);self.assertIsNone(next(s for s in d['sectors'] if s['sector_name']=='SMALL')['sector_state'])
    def test_partial_sector_preserved_and_not_final(self):
        rows=self.rows()
        for row in rows[:3]:row['teknik_gostergeler']['closing']['return_20d']=None
        d=self.build(rows);self.assertFalse(d['final']);self.assertTrue(any(s['data_status']=='COMPLETE' for s in d['sectors']))
    def test_weekend_skipped(self):
        from teknik_gostergeler import calculate
        f=self.frame();doc=calculate(f,self.now,'TOMORROW')['closing'];self.assertAlmostEqual(doc['return_5d'],(f.Close.iloc[-1]/f.Close.iloc[-6]-1)*100)
        self.assertGreater((f.index[-1]-f.index[-6]).days,5)
    def test_holiday_skipped(self):
        import pandas as pd
        from performans_motoru import business_day
        from teknik_gostergeler import calculate
        dates=[d for d in pd.bdate_range(end='2026-05-05',periods=60,tz=ISTANBUL) if business_day(d.date())]
        self.assertNotIn(pd.Timestamp('2026-05-01',tz=ISTANBUL),dates)
        f=self.frame().iloc[:len(dates)].copy();f.index=dates
        closing=calculate(f,datetime(2026,5,5,19,tzinfo=ISTANBUL),'TOMORROW')['closing'];self.assertIsNotNone(closing['return_5d'])


if __name__=='__main__':unittest.main()
