"""Adapters reuse existing scoring; events enqueue rather than blocking collectors."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib
import json
import os
import threading

from ana_motor import ROOT, istanbul_now, market_open, after_close, runtime_dir
from kullanici_kayitlari import atomic_json, symbol


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
        failed=False
        for stock,version in batch:
            result=self.original_priority(stock,gun_ici_yenile=False)
            if not result:
                failed=True
                with self.lock:
                    self.events.move_to_end(stock)
                    self.save_queue()
                continue
            self.ai_context([result])
            with self.lock:
                if self.events.get(stock)==version:self.events.pop(stock,None)
                self.save_queue()
            completed+=1
        if failed:raise RuntimeError('Bazı öncelikli fiyatlar alınamadı')
        return completed

    def full_scan(self):
        if not self.symbols or self.cursor>=len(self.symbols):
            self.symbols=self.bot.bist_hisseleri_getir();self.cursor=0
            if not self.symbols:raise RuntimeError('Sembol listesi boş')
        batch=self.symbols[self.cursor:self.cursor+self.batch_size]
        results=list(self.technical_pool.map(self.live.tek_hisse_guncelle,batch))
        successful=[row for _,row in results if row]
        if not successful:raise RuntimeError('Tarama batch fiyatları alınamadı')
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
        self.market_context()
        self.ai_context(successful)
        self.cursor+=len(batch)
        if len(successful)!=len(batch):
            for stock,row in results:
                if row is None:self.enqueue(stock)
        return {'updated':len(successful), 'cycle_complete':self.cursor>=len(self.symbols)}

    def bootstrap(self):
        # One bounded daily-analysis pass even outside the trading session.
        # Existing providers/analysis/write functions; no intraday/snapshot fabrication.
        result=self.full_scan()
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
        from sirket_site_motoru import SirketSiteMotoru
        self.company=SirketSiteMotoru(self.directory,enqueue=self.enqueue,stop=lambda:self.stop.is_set())
        return {'bootstrap':self.bootstrap, 'kap':kap_canli.kap_kontrol, 'macro':makro_kaynak.yeni_haberleri_isle,
                'alarm':self.alarm, 'push':self.push,
                'priority':self.priority, 'full_scan':self.full_scan,
                'intraday_top10':self.intraday, 'yarin_top10':self.tomorrow,
                'company_site':self.company.tek_tur,'performance':self.performance,
                'intraday_performance':self.intraday_performance,'market_context':self.market_context}

    def market_context(self):
        from piyasa_baglami import PiyasaBaglami
        try:return PiyasaBaglami().refresh()
        except Exception as error:return {'hata':type(error).__name__}

    def intraday_performance(self):
        from gun_ici_performans import bekleyen_gun_ici_sonuclari_guncelle
        return bekleyen_gun_ici_sonuclari_guncelle()

    def performance(self):
        from performans_motoru import bekleyen_sonuclari_guncelle
        result=bekleyen_sonuclari_guncelle()
        from yarin_kalibrasyon import YarinKalibrasyon
        try:
            YarinKalibrasyon().refresh()
        except Exception as error:
            result['kalibrasyon_hatasi']=type(error).__name__
        if result.get('hatalar') and not result.get('tamamlanan_vade'):
            raise RuntimeError('Performans fiyat kaynakları alınamadı')
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
