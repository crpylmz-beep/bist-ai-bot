"""One borsapy quote stream; bounded current-state file, no analysis/history writes."""
from datetime import datetime, time
import json
import os
from pathlib import Path

from fiyat_guncelligi import IST, daily_change, price_metadata, preserve_newer_price
from kullanici_kayitlari import atomic_json
from veri_yollari import paths


class BorsaFiyatMotoru:
    def __init__(self, symbols, directory=None, stream_factory=None, clock=None):
        self.symbols=symbols; self.directory=Path(directory or paths().public)
        self.path=self.directory/'borsa_fiyatlari.json'
        self.factory=stream_factory;self.clock=clock or (lambda:datetime.now(IST))
        self.stream=None;self.subscribed=set();self.rows={};self.universe=[];self.universe_day=None;self.disconnected_since=None
        if self.path.exists():
            try:saved=json.loads(self.path.read_text())
            except (OSError,ValueError):saved={}
            self.rows={row['sembol']:row for row in saved.get('hisseler',[]) if isinstance(row,dict) and row.get('sembol')}

    def close(self):
        if self.stream:
            self.stream.disconnect();self.stream=None;self.subscribed.clear();self.disconnected_since=None

    def round(self):
        from ana_motor import market_open,after_close
        from performans_motoru import business_day
        now=self.clock().astimezone(IST)
        if not business_day(now.date()) or (not market_open(now) and not (after_close(now) and now.time()<time(21))):
            self.close()
            return {'market_closed':True,'fresh':0,'coverage':len(self.rows)}
        if self.universe_day!=now.date():
            if self.universe_day is not None:self.close()
            universe=sorted(set(self.symbols()))
            if not universe:
                from gorev_hatalari import TaskIssue
                raise TaskIssue({'code':'EMPTY_UNIVERSE'})
            self.universe=universe;self.universe_day=now.date()
        if self.stream is None:
            if self.factory is None:
                import borsapy as bp
                self.stream=bp.TradingViewStream(auth_token=os.environ.get('BIST_TRADINGVIEW_AUTH_TOKEN'))
            else:self.stream=self.factory()
            self.stream.connect(timeout=10)
        if not self.stream.is_connected:
            self.disconnected_since=self.disconnected_since or now
            if (now-self.disconnected_since).total_seconds()>=600:self.close()
            from requests.exceptions import ConnectionError
            raise ConnectionError('QUOTE_STREAM_UNAVAILABLE')
        self.disconnected_since=None
        # Only subscribe once. Rate limit bootstrap; never one socket/request per stock.
        added=0
        for stock in [stock for stock in self.universe if stock not in self.subscribed][:100]:
            self.stream.subscribe(stock);self.subscribed.add(stock)
            added+=1
        quotes=self.stream.get_all_quotes();valid=0;invalid=0;delayed=0
        for stock in self.universe:
            quote=quotes.get(stock)
            if not quote:continue
            change=daily_change(quote.get('last'),quote.get('prev_close'))
            try:
                at=datetime.fromtimestamp(float(quote['timestamp']),IST)
            except (TypeError,ValueError,KeyError,OverflowError):
                invalid+=1;continue
            if change is None or at>now or at.date()!=now.date():
                invalid+=1;continue
            metadata=price_metadata(at,now=now)
            row={'sembol':stock,'fiyat':float(quote['last']),'onceki_kapanis':float(quote['prev_close']),
                 **metadata,'degisim':change,'gunluk_degisim':change,
                 'gunluk_degisim_kaynagi':'PREVIOUS_SESSION_CLOSE','fiyat_kaynagi':'borsapy.TradingViewStream',
                 'onceki_kapanis_tarihi':metadata['onceki_kapanis_beklenen_tarih'],
                 'fiyat_okuma_zamani':now.isoformat(),'son_islem_yasi_saniye':max(0,int((now-at).total_seconds())),
                 'gecikme_garantisi':False}
            if now.time()>=time(18,30):row['fiyat_turu']='SESSION_CLOSE'
            previous=self.rows.get(stock)
            if previous and previous.get('fiyat_zamani')==row['fiyat_zamani'] and (previous.get('fiyat')!=row['fiyat'] or previous.get('onceki_kapanis')!=row['onceki_kapanis']):
                invalid+=1;continue
            self.rows[stock]=preserve_newer_price(previous or {},row)
            valid+=1;delayed+=row['son_islem_yasi_saniye']>60
        # Official daily-history close takes precedence over an older intraday quote.
        daily=self.directory/'bist_data.json'
        if daily.exists():
            document=json.loads(daily.read_text())
            for row in document.get('hisseler',[]):
                if row.get('sembol') not in self.universe or row.get('fiyat_turu')!='SESSION_CLOSE' or now.time()<time(18,30):continue
                if daily_change(row.get('fiyat'),row.get('onceki_kapanis')) is None:continue
                previous=self.rows.get(row['sembol'])
                if previous and str(previous.get('fiyat_zamani',''))[:10]==str(row.get('fiyat_zamani',''))[:10] and previous.get('onceki_kapanis_tarihi')==row.get('onceki_kapanis_beklenen_tarih'):
                    row=dict(row,onceki_kapanis=previous['onceki_kapanis'])
                self.rows[row['sembol']]=preserve_newer_price(row,previous or row)
        saved=[self.rows[stock] for stock in self.universe if stock in self.rows]
        result={'updated_at':now.isoformat(),'hisseler':saved,'universe_count':len(self.universe),
                'coverage':len(saved),'provider_valid':valid,'missing':len(self.universe)-len(saved),
                'invalid':invalid,'delayed':delayed,'not_observed':len(self.universe)-valid,'realtime_guaranteed':False,
                'provider_notice':'Gerçek zaman garantisi yok; anonim TradingView akışı yaklaşık 15 dakika gecikebilir.'}
        self.directory.mkdir(parents=True,exist_ok=True)
        atomic_json(self.path,result)
        return {'fresh':valid-delayed,'coverage':len(saved),'missing':result['missing'],'invalid':invalid,'delayed':delayed,'provider_valid':valid,'not_observed':result['not_observed'],'subscriptions_added':added}
