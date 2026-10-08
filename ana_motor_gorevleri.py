"""Adapters reuse existing scoring; events enqueue rather than blocking collectors."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib
import json
import os
import threading
import logging

from ana_motor import ROOT, istanbul_now, market_open, after_close, runtime_dir
from kullanici_kayitlari import atomic_json, symbol
from gorev_hatalari import capture,public_issue,TaskIssue,strongest


def check_configuration():
    from push_bildirim_motoru import public_config
    # Imports must not contact providers or need BOT_TOKEN.
    for name in ('canli_motor','kap_canli','makro_kaynak','makro_ai','sirket_site_motoru',
                 'fiyat_alarm_motoru','push_bildirim_motoru','ai_karar_motoru','performans_motoru'):
        importlib.import_module(name)
    return {'imports':'OK', 'push_configured':public_config()['configured'],
            'timezone':'Europe/Istanbul', 'runtime_dir':str(runtime_dir()), 'deployment':False}


class WorkerTasks:
    def __init__(self):
        import bist_bot
        import canli_motor
        self.bot, self.live = bist_bot, canli_motor
        self.directory=runtime_dir();self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.Lock();self.events=OrderedDict()
        self.queue_event_ids=set()
        self.queue_path=self.directory/'oncelik_kuyrugu.json'
        if self.queue_path.exists():
            saved=json.loads(self.queue_path.read_text())
            self.queue_event_ids=set(saved.pop("_news_event_ids",[]))
            self.events=OrderedDict(saved)
        self.stop=threading.Event()
        self.technical_pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='bist-price')
        self.batch_size=int(os.environ.get('FULL_SCAN_BATCH_SIZE','10'))
        if not 1 <= self.batch_size <= 25:raise ValueError('FULL_SCAN_BATCH_SIZE: 1–25')
        self.symbols=[];self.cursor=0
        self.original_priority=canli_motor.oncelikli_hisse_guncelle
        self.original_intraday=canli_motor.gun_ici_top10_guncelle
        canli_motor.oncelikli_hisse_guncelle=self.enqueue
        canli_motor.gun_ici_top10_guncelle=self.intraday_event

    def enqueue(self, stock, gun_ici_yenile=True, event_id=None):
        stock=symbol(stock)
        with self.lock:
            if event_id and event_id in self.queue_event_ids:
                return {"sembol":stock,"queued":False}
            # Universe-sized bounded queue; repeated events coalesce.
            if len(self.events)>=2000 and stock not in self.events:
                raise RuntimeError('Öncelik kuyruğu dolu')
            self.events[stock]=self.events.get(stock,0)+1
            if event_id:self.queue_event_ids.add(event_id)
            self.save_queue()
        return {'sembol':stock,'queued':True}

    def save_queue(self):
        value=dict(self.events)
        if self.queue_event_ids:value['_news_event_ids']=sorted(self.queue_event_ids)
        atomic_json(self.queue_path,value)

    def intraday_event(self):
        # Event scoring is refreshed by the regular market-gated intraday task.
        return {'queued':True,'market_open':market_open(istanbul_now())}

    def ai_context(self, rows):
        from ai_karar_motoru import ai_batch_guncelle
        try:
            return ai_batch_guncelle([row['sembol'] for row in rows],rows=rows)
        except Exception as error:
            # AI context is supplementary; provider and alarm jobs keep running.
            return {'hatalar':{'batch':type(error).__name__}}

    def priority(self):
        with self.lock:
            batch=list(self.events.items())[:3]
        completed=0
        failed=[];skips=[]
        for stock,version in batch:
            with capture() as issues:
                try:
                    if self.symbols and stock not in self.symbols:
                        issues.append(public_issue({'code':'OUTSIDE_EQUITY_UNIVERSE'}));result=None
                    else:result=self.original_priority(stock,gun_ici_yenile=False)
                except Exception as error:
                    from gorev_hatalari import remember
                    remember(error);result=None
            if not result:
                issue=issues[0] if issues else public_issue({'code':'ANALYSIS_NO_RESULT'})
                if issue['code'] in ('PROVIDER_UNSUPPORTED','OUTSIDE_EQUITY_UNIVERSE'):
                    skips.append({'symbol':stock,**issue})
                    self.record_unsupported(stock,issue['code'])
                    with self.lock:
                        if self.events.get(stock)==version:self.events.pop(stock,None)
                        self.save_queue()
                    continue
                failed.append(issue)
                with self.lock:
                    self.events.move_to_end(stock)
                    self.save_queue()
                continue
            self.ai_context([result])
            with self.lock:
                if self.events.get(stock)==version:self.events.pop(stock,None)
                self.save_queue()
            completed+=1
        details={'processed':len(batch),'successful':completed,'skipped':len(skips),'unsupported':sum(item['code']=='PROVIDER_UNSUPPORTED' for item in skips),'failed':len(failed),'reasons':skips}
        if failed:raise TaskIssue(strongest(failed),completed,details)
        return {'updated':completed,'diagnostics':details}

    def record_unsupported(self,stock,code='PROVIDER_UNSUPPORTED'):
        with self.lock:
            path=self.directory/'provider_unsupported.json'
            saved=json.loads(path.read_text()) if path.exists() else {}
            saved[stock]={'code':code,'updated_at':istanbul_now().isoformat()}
            # Diagnostic index only; no signals, users, snapshots or outcomes.
            if len(saved)>2000:
                oldest=min(saved,key=lambda s:saved[s]['updated_at']);saved.pop(oldest)
            atomic_json(path,saved)
        logging.warning('[PROVIDER_SKIP] symbol=%s reason=%s',stock,code)

    def scan_one(self,stock):
        with capture() as issues:
            try:_,row=self.live.tek_hisse_guncelle(stock)
            except Exception as error:
                from gorev_hatalari import remember
                remember(error);row=None
        return stock,row,(issues[0] if issues else public_issue({'code':'ANALYSIS_NO_RESULT'})) if not row else None

    def full_scan(self):
        if not self.symbols or self.cursor>=len(self.symbols):
            self.symbols=self.bot.bist_hisseleri_getir();self.cursor=0;self.cycle_successful=0
            if not self.symbols:raise TaskIssue({'code':'EMPTY_UNIVERSE'})
        batch=self.symbols[self.cursor:self.cursor+self.batch_size]
        results=list(self.technical_pool.map(self.scan_one,batch))
        successful=[row for _,row,_ in results if row]
        skipped=[{'symbol':stock,**issue} for stock,row,issue in results if issue and issue['code']=='PROVIDER_UNSUPPORTED']
        failures=[(stock,issue) for stock,row,issue in results if issue and issue['code']!='PROVIDER_UNSUPPORTED']
        details={'processed':len(results),'successful':len(successful),'skipped':len(skipped),'unsupported':len(skipped),'failed':len(failures),'reasons':skipped}
        for item in skipped:self.record_unsupported(item['symbol'])
        if not successful:
            # One permanently invalid batch cannot starve the rest of the universe.
            for stock,_ in failures:self.enqueue(stock)
            self.cursor+=len(batch)
            if failures:raise TaskIssue(strongest(issue for _,issue in failures),details=details)
            return {'updated':0,'cycle_complete':self.cursor>=len(self.symbols),'diagnostics':details}
        # Merge updated rows without replacing remaining live stocks with placeholders.
        path=Path(self.bot.DATA_FILE)
        current=json.loads(path.read_text()) if path.exists() else {'hisseler':[]}
        merged={row['sembol']:row for row in current.get('hisseler',[]) if isinstance(row,dict) and row.get('sembol')}
        for row in merged.values():
            if not row.get('canli_guncelleme'):
                row['canli_guncelleme']=current.get('updated_at') or current.get('guncelleme')
        for row in successful:
            row['canli_guncelleme']=self.live.simdi()
            merged[row['sembol']]=row
        self.bot.web_verisi_kaydet(list(merged.values()),self.symbols)
        from veri_yollari import paths
        if not self.bot.tahminleri_kaydet(successful,len(self.symbols),kaynak='GUNLUK_TARAMA',
                liste_kaydet=False,dosya_yolu=paths().runtime_file('tahmin_gecmisi.json'),strict=True):
            raise RuntimeError('Anlamlı tahmin kaydı yazılamadı; mevcut veri korundu')
        self.cycle_successful=getattr(self,'cycle_successful',0)+len(successful)
        self.market_context()
        self.ai_context(successful)
        self.cursor+=len(batch)
        if failures:
            for stock,_ in failures:self.enqueue(stock)
            raise TaskIssue(strongest(issue for _,issue in failures),len(successful),details)
        return {'updated':len(successful), 'cycle_complete':self.cursor>=len(self.symbols),'diagnostics':details}

    def bootstrap(self):
        # One bounded daily-analysis pass even outside the trading session.
        # Existing providers/analysis/write functions; no intraday/snapshot fabrication.
        try:result=self.full_scan()
        except TaskIssue:
            # A degraded final batch must not restart the entire bootstrap forever.
            if self.symbols and self.cursor>=len(self.symbols) and getattr(self,'cycle_successful',0)>0:
                atomic_json(self.directory/'public_bootstrap_complete.json',
                            {'completed_at':istanbul_now().isoformat(),'status':'DEGRADED'})
            raise
        if result.get('cycle_complete'):
            atomic_json(self.directory/'public_bootstrap_complete.json',
                        {'completed_at':istanbul_now().isoformat()})
        return result

    def intraday(self):
        if not market_open(istanbul_now()):
            return 0
        top10, rows, total=self.bot.gun_ici_top10_tara()
        if not total:raise RuntimeError('Gün içi veri alınamadı')
        self.ai_context(rows or [])
        return len(top10 or [])

    def tomorrow(self):
        # Separate closing scan uses the same technical functions and selection.
        # This job owns the technical lane; unrelated collectors/alarms continue.
        day=istanbul_now().date()
        if not after_close(istanbul_now()):raise RuntimeError('Kapanış seansı tamamlanmadı')
        # Idempotent direct callback too: an immutable daily snapshot ends this scan.
        from veri_yollari import paths
        if (paths().archives/(day.isoformat()+'.json')).exists():return 0
        symbols=self.bot.bist_hisseleri_getir()
        if not symbols:raise RuntimeError('Kapanış sembol listesi boş')
        checkpoint=self.directory/'pozitif_kapanis_tarama.json'
        saved=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        cached=saved.get('rows',{}) if saved.get('date')==day.isoformat() and saved.get('symbols')==symbols else {}
        pending=[stock for stock in symbols if stock not in cached]
        for start in range(0,len(pending),self.batch_size):
            if self.stop.is_set():raise InterruptedError('Kapanış taraması durduruldu')
            for stock,row in self.technical_pool.map(self.live.tek_hisse_guncelle,pending[start:start+self.batch_size]):
                if row:
                    from ai_karar_motoru import stamp
                    observed=stamp((row.get('teknik_gostergeler') or {}).get('data_time'))
                    if not observed or observed.date()!=day or observed>istanbul_now():continue
                    row['canli_guncelleme']=self.live.simdi()
                    cached[stock]=row
            atomic_json(checkpoint,{'date':day.isoformat(),'symbols':symbols,'rows':cached})
        rows=list(cached.values())
        if self.stop.is_set() or istanbul_now().date()!=day:
            raise InterruptedError('Snapshot tarihi değişti veya motor durduruldu')
        # Avoid freezing an empty or severely incomplete provider outage result.
        if len(rows)<max(1,int(len(symbols)*0.8)):
            raise RuntimeError('Kapanış taraması eksik; snapshot üretilmedi')
        if not self.bot.yarin_top10_kilitli_kaydet(rows,len(symbols),pozitif_kapanis=True):
            raise RuntimeError('Snapshot kaydedilemedi')
        self.ai_context(rows)
        return len(rows)

    def callbacks(self):
        import kap_canli
        import makro_kaynak
        from ekonomi_haberleri import EconomyNews
        self.economy_news=EconomyNews(self.bot.bist_hisseleri_getir,self.enqueue)
        logging.info('[NEWS] company_site=disabled priority=KAP,EKONOMIM,BLOOMBERG_HT,ENSONHABER_EKONOMI')
        from haber_kaynak_politikasi import SourceRestrictions
        news_policy=SourceRestrictions()
        result={'bootstrap':self.bootstrap, 'kap':lambda:news_policy.call('KAP',kap_canli.kap_kontrol), 'macro':makro_kaynak.yeni_haberleri_isle,
                'alarm':self.alarm, 'push':self.push,
                'priority':self.priority, 'full_scan':self.full_scan,
                'intraday_top10':self.intraday, 'yarin_top10':self.tomorrow,
                'economy_news':self.economy_news.one_round,'performance':self.performance,
                'intraday_performance':self.intraday_performance,'market_context':self.market_context}
        from sinyal_performansi import indicator_enabled
        if indicator_enabled():result['indicator_performance']=self.indicator_performance
        from piyasa_baglami import regime_enabled,sector_enabled
        if regime_enabled():result["market_regime"]=self.market_regime
        if sector_enabled():result["sector_strength"]=self.sector_strength
        from gunluk_al_sat import enabled,GunlukAlSat
        intraday_enabled=enabled()
        if not getattr(self,'_intraday_flag_logged',False):
            logging.info('[INTRADAY_SIGNAL] enabled=true timeframe=5m market_gate=enabled' if intraday_enabled else '[INTRADAY_SIGNAL] enabled=false')
            self._intraday_flag_logged=True
        if intraday_enabled:
            from veri_yollari import paths
            self.daily_intraday=GunlukAlSat(location=paths(),universe=self.bot.bist_hisseleri_getir)
            result['intraday_signals']=self.daily_intraday.one_round
        return result

    def market_context(self):
        from piyasa_baglami import PiyasaBaglami
        try:return PiyasaBaglami().refresh()
        except Exception as error:return {'hata':type(error).__name__}

    def indicator_performance(self):
        from sinyal_performansi import refresh_indicator_performance
        return refresh_indicator_performance()

    def sector_strength(self):
        from piyasa_baglami import PiyasaBaglami
        return PiyasaBaglami().refresh_sectors(enqueue=self.enqueue)

    def market_regime(self):
        from piyasa_baglami import PiyasaBaglami
        # Exceptions remain visible to scheduler/backoff; other tasks are isolated.
        return PiyasaBaglami().refresh_measurement()

    def company_site(self):
        # Explicit/manual compatibility only; never registered in the scheduler.
        if not hasattr(self,'company'):
            from sirket_site_motoru import SirketSiteMotoru
            self.company=SirketSiteMotoru(self.directory,enqueue=self.enqueue,stop=lambda:self.stop.is_set())
        completed=self.company.tek_tur()
        details=getattr(self.company,'last_round_details',None)
        if getattr(self.company,'last_round_issue',None):
            progress=details['successful'] if isinstance(details,dict) else completed
            raise TaskIssue(self.company.last_round_issue,progress,details,
                isolated=getattr(self.company,'last_round_isolated',False) is True,
                systemic=getattr(self.company,'last_round_systemic',False) is True)
        return {'updated':completed,'diagnostics':details} if isinstance(details,dict) else completed

    def intraday_performance(self):
        from gun_ici_performans import bekleyen_gun_ici_sonuclari_guncelle,GunIciPerformans
        result=bekleyen_gun_ici_sonuclari_guncelle()
        GunIciPerformans().signal_round()
        return result

    def performance(self):
        from performans_motoru import bekleyen_sonuclari_guncelle
        result=bekleyen_sonuclari_guncelle()
        from yarin_kalibrasyon import YarinKalibrasyon
        try:
            YarinKalibrasyon().refresh()
        except Exception as error:
            from gorev_hatalari import describe
            raise TaskIssue(describe(error),result.get('tamamlanan_vade',0)) from None
        if result.get('hatalar'):
            details=result.get('error_details') or {}
            raise TaskIssue(strongest(details.values()) if details else {'code':'ANALYSIS_NO_RESULT'},result.get('tamamlanan_vade',0))
        return result

    def alarm(self):
        if not market_open(istanbul_now()):
            return {'kontrol_edilen_alarm':0, 'tetiklenen_alarm':0, 'skipped':'MARKET_CLOSED'}
        from fiyat_alarm_motoru import alarmlari_kontrol_et
        result=alarmlari_kontrol_et()
        if result.get('fiyat_hatalari') and not result.get('kontrol_edilen_alarm'):
            raise RuntimeError('Alarm fiyat kaynakları alınamadı')
        return result

    def push(self):
        from push_bildirim_motoru import bildirimleri_gonder
        result=bildirimleri_gonder()
        if result.get('failed'):
            raise RuntimeError('Bazı push teslimleri başarısız')
        return result

    def close(self):
        self.technical_pool.shutdown(wait=True,cancel_futures=True)
        self.live.oncelikli_hisse_guncelle=self.original_priority
        self.live.gun_ici_top10_guncelle=self.original_intraday
