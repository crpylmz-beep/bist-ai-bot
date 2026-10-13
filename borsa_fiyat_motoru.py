"""Bounded shared borsapy quotes, explicit coverage and last-session fallback.

Only the small current public projection is written. No prediction, learning,
user, recovery journal or database migration is changed here.
"""
from datetime import datetime,time
from pathlib import Path
import logging
import os
from fiyat_guncelligi import IST,daily_change,price_metadata,preserve_newer_price,session_close_time,session_confirmation_time
from public_veri_guvenligi import read_public,write_public
from veri_yollari import paths


class BorsaFiyatMotoru:
    def __init__(self,symbols,directory=None,stream_factory=None,clock=None,history_fetcher=None):
        self.symbols=symbols
        self.directory=Path(directory or paths().public)
        self.path=self.directory/'borsa_fiyatlari.json'
        self.factory=stream_factory
        self.history_fetcher=history_fetcher
        self.clock=clock or (lambda:datetime.now(IST))
        self.stream=None;self.subscribed=set();self.rows={}
        self.universe=[];self.universe_day=None;self.disconnected_since=None
        self.history_cursor=0;self.history_day=None;self.history_attempts={}
        # A malformed projection is retained; new verified rows go to a pending view.
        saved,self.damaged=read_public(self.path)
        for row in saved['hisseler']:
            if row.get('sembol') and self._verified(row) and self._stamp(row)<=self.clock().astimezone(IST):self.rows[row['sembol']]=row

    @staticmethod
    def _stamp(row):
        try:
            at=datetime.fromisoformat(row.get('fiyat_zamani') or '')
            return at.replace(tzinfo=IST) if at.tzinfo is None else at.astimezone(IST)
        except (ValueError,TypeError):return None

    @classmethod
    def _verified(cls,row):
        at=cls._stamp(row)
        if not at or daily_change(row.get('fiyat'),row.get('onceki_kapanis')) is None:return False
        from performans_motoru import bist_calendar
        cal=bist_calendar(at.year)
        if not cal.is_session(at.date().isoformat()):return False
        expected=cal.previous_session(at.date().isoformat()).date().isoformat()
        return row.get('onceki_kapanis_tarihi')==expected

    def close(self):
        if self.stream:self.stream.disconnect()
        self.stream=None;self.subscribed.clear();self.disconnected_since=None

    def _history(self,stock):
        if self.history_fetcher:return self.history_fetcher(stock)
        import borsapy as bp
        return bp.Ticker(stock).history(period='5d',interval='1d')

    @staticmethod
    def _closed_day(now):
        from performans_motoru import bist_calendar
        cal=bist_calendar(now.year)
        session=cal.date_to_session(now.date().isoformat(),direction='previous')
        if session.date()==now.date() and now<session_confirmation_time(now.date()):session=cal.previous_session(session)
        return session.date()

    def _historical_quote(self,stock,bars,closed_day,now):
        import pandas as pd
        if not isinstance(bars,pd.DataFrame) or bars.empty or not {'Close'}<=set(bars.columns):return None
        if not isinstance(bars.index,pd.DatetimeIndex):return None
        data=bars.copy();index=data.index
        data.index=index.tz_localize(IST) if index.tz is None else index.tz_convert(IST)
        data=data.loc[data.index.date<=closed_day].sort_index()
        data=data.loc[~data.index.duplicated(keep=False)]
        if len(data)<2:return None
        day=data.index[-1].date()
        # Never slide a missing previous session onto an older candle.
        from performans_motoru import bist_calendar
        expected=bist_calendar(day.year).previous_session(day.isoformat()).date()
        previous=data.loc[data.index.date==expected]
        if previous.empty:return None
        value=float(data.iloc[-1]['Close']);prior=float(previous.iloc[-1]['Close'])
        change=daily_change(value,prior)
        if change is None:return None
        return {'sembol':stock,'fiyat':value,'onceki_kapanis':prior,
                **price_metadata(data.index[-1],daily=True,now=now),
                'onceki_kapanis_tarihi':expected.isoformat(),'degisim':change,'gunluk_degisim':change,
                'gunluk_degisim_kaynagi':'PREVIOUS_SESSION_CLOSE','fiyat_okuma_zamani':now.isoformat(),
                'fiyat_kaynagi':'borsapy.history','gecikme_garantisi':False}

    def _save_row(self,row,now):
        if not self._verified(row):return False
        at=self._stamp(row)
        if at>now:return False
        previous=self.rows.get(row['sembol'])
        old=self._stamp(previous or {})
        if old and at<old:return False
        # A corrected reference at the same trade timestamp is legitimate provider data.
        self.rows[row['sembol']]=preserve_newer_price(previous or {},row)
        return True

    def round(self):
        from ana_motor import market_open
        from performans_motoru import business_day
        from gorev_hatalari import describe,log_source
        now=self.clock().astimezone(IST)
        opened=business_day(now.date()) and market_open(now) and now<session_close_time(now.date())
        closed_day=self._closed_day(now)
        wanted_day=now.date() if opened else closed_day
        if self.universe_day!=now.date():
            if self.universe_day is not None:self.close()
            self.universe=sorted(set(self.symbols()))
            if not self.universe:
                from gorev_hatalari import TaskIssue
                raise TaskIssue({'code':'EMPTY_UNIVERSE'})
            self.universe_day=now.date()
            self.history_attempts={s:at for s,at in self.history_attempts.items() if s in self.universe}
        issues=[];reasons=[];accepted=set();invalid=0;added=0
        def problem(error,stock=None):
            issue=describe(error);issues.append(issue)
            if stock:reasons.append({'symbol':stock,'code':issue['code']})
            log_source(error,'PROVIDER')
        # Existing verified daily projection can bootstrap a closed-session view.
        try:
            daily,broken=read_public(self.directory/'bist_data.json')
            if broken:issues.append({'code':'PUBLIC_JSON_CORRUPT'})
            for row in daily['hisseler']:
                if row.get('sembol') in self.universe and row.get('fiyat_turu')=='SESSION_CLOSE':
                    self._save_row(row,now)
        except (OSError,ValueError,UnicodeError) as error:problem(error)
        use_stream=opened or (self.stream is not None and business_day(now.date()) and time(10)<=now.time()<time(21))
        if use_stream:
            try:
                if self.stream is None:
                    if self.factory:self.stream=self.factory()
                    else:
                        import borsapy as bp
                        self.stream=bp.TradingViewStream(auth_token=os.environ.get('BIST_TRADINGVIEW_AUTH_TOKEN'))
                    self.stream.connect(timeout=10)
                if not self.stream.is_connected:
                    self.disconnected_since=self.disconnected_since or now
                    if (now-self.disconnected_since).total_seconds()>=600:self.close()
                    from requests.exceptions import ConnectionError
                    raise ConnectionError('QUOTE_STREAM_UNAVAILABLE')
                self.disconnected_since=None
                for stock in [s for s in self.universe if s not in self.subscribed][:100]:
                    self.stream.subscribe(stock);self.subscribed.add(stock);added+=1
                for stock,quote in self.stream.get_all_quotes().items():
                    if stock not in self.universe:continue
                    try:
                        at=datetime.fromtimestamp(float(quote['timestamp']),IST)
                        change=daily_change(quote.get('last'),quote.get('prev_close'))
                        if at>now or at.date()!=now.date() or change is None:raise ValueError('Invalid quote observation')
                        metadata=price_metadata(at,now=now)
                        row={'sembol':stock,'fiyat':float(quote['last']),'onceki_kapanis':float(quote['prev_close']),
                             **metadata,'onceki_kapanis_tarihi':metadata['onceki_kapanis_beklenen_tarih'],
                             'degisim':change,'gunluk_degisim':change,'gunluk_degisim_kaynagi':'PREVIOUS_SESSION_CLOSE',
                             'fiyat_kaynagi':'borsapy.TradingViewStream','fiyat_okuma_zamani':now.isoformat(),
                             'gecikme_garantisi':False,'son_islem_yasi_saniye':max(0,int((now-at).total_seconds()))}
                        if now>=session_confirmation_time(now.date()):row['fiyat_turu']='SESSION_CLOSE'
                        if self._save_row(row,now):accepted.add(stock)
                    except (ValueError,TypeError,KeyError,OverflowError):
                        invalid+=1;reasons.append({'symbol':stock,'code':'PROVIDER_DATA'})
            except Exception as error:problem(error)
        else:self.close()
        # Small after-hours bootstrap, never 631 concurrent provider calls.
        # Successful closed-session rows are not fetched again. Failures are retried hourly.
        if not opened:
            needed=[s for s in self.universe if not self.rows.get(s) or self._stamp(self.rows[s]).date()<closed_day or self.rows[s].get('fiyat_turu')!='SESSION_CLOSE']
            attempted=0
            for stock in needed:
                if stock in self.rows and self._stamp(self.rows[stock]).date()>closed_day:continue
                last=self.history_attempts.get(stock)
                if last and (now-last).total_seconds()<3600:continue
                attempted+=1
                self.history_attempts[stock]=now
                try:
                    bars=self._history(stock)
                    try:row=self._historical_quote(stock,bars,closed_day,now)
                    except (ValueError,TypeError,OverflowError):
                        row=None;invalid+=1
                    if row and self._save_row(row,now):accepted.add(stock)
                    else:reasons.append({'symbol':stock,'code':'PROVIDER_DATA'})
                except Exception as error:problem(error,stock)
                if attempted>=10:break
        rows=[{**self.rows[s],'piyasa_kapali':not opened} for s in self.universe if s in self.rows]
        current=sum(self._stamp(r).date()==wanted_day for r in rows)
        stale=sum(self._stamp(r).date()<wanted_day for r in rows)
        delayed=sum(opened and (now-self._stamp(r)).total_seconds()>60 for r in rows)
        unconfirmed=sum(not opened and r.get('fiyat_turu')!='SESSION_CLOSE' for r in rows)
        missing=len(self.universe)-len(rows)
        status=('NO_DATA' if not rows else 'PARTIAL' if missing or stale or invalid or unconfirmed else
                'DELAYED' if delayed else 'CURRENT' if opened else 'LAST_SESSION')
        doc={'updated_at':now.isoformat(),'hisseler':rows,'universe_count':len(self.universe),
             'mode':'OPEN' if opened else 'CLOSED','status':status,'expected_session':wanted_day.isoformat(),
             'coverage':len(rows),'current_session_count':current,'provider_valid':len(accepted),
             'missing':missing,'stale':stale,'invalid':invalid,'delayed':delayed,'unconfirmed_close':unconfirmed,
             'not_observed':len(self.universe)-len(accepted),'realtime_guaranteed':False,
             'reasons':reasons[:25],'provider_errors':[i['code'] for i in issues[:10]],
             'provider_notice':'Gerçek zaman garantisi yok; anonim TradingView akışı yaklaşık 15 dakika gecikebilir.'}
        self.directory.mkdir(parents=True,exist_ok=True)
        publication=write_public(self.path,doc)
        if publication['pending']:issues.append({'code':'PUBLIC_JSON_CORRUPT'})
        report={k:v for k,v in doc.items() if k!='hisseler'}
        report.update(market_closed=not opened,fresh=max(0,current-delayed),subscriptions_added=added,
                      issues=issues,pending=publication['pending'])
        logging.info('[QUOTE_DATA] status=%s mode=%s universe=%d provider_valid=%d current=%d missing=%d delayed=%d stale=%d invalid=%d public_file=%s',
                     status,doc['mode'],len(self.universe),len(accepted),current,missing,delayed,stale,invalid,publication['filename'])
        return report
