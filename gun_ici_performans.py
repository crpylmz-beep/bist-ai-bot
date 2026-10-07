"""Independent intraday signals, closed 5m outcomes and bounded shadow learning.
No tomorrow storage or calibration dependency. Pure statistics reuse is intentional.
"""
from datetime import datetime, timedelta, time
import copy
import hashlib
import json
import os
from statistics import mean

from ai_karar_motoru import ISTANBUL, number, stamp, load, locked, clamp
from performans_motoru import robust, criterion_report, session_closed
from kullanici_kayitlari import atomic_json
from veri_yollari import paths

HORIZONS=(5,15,30,60,'SEANS')
CRITERIA=('VWAP','HACIM','EMA','RSI','MACD','OBV','BOLLINGER','MOMENTUM','KIRILIM','HABER','MAKRO','SEKTOR','REJIM')
BASE={k:1/len(CRITERIA) for k in CRITERIA}


def features(record):
    r=record.get('analiz',record)
    def val(key,test):
        n=number(r.get(key));return test(n) if n is not None else None
    def compare(a,b):
        x,y=number(r.get(a)),number(r.get(b));return x>y if x is not None and y is not None else None
    return {'VWAP':compare('fiyat','seans_vwap'),'HACIM':val('hacim3_orani',lambda v:v>=150),
        'EMA':compare('ema9_5','ema21_5'),'RSI':val('rsi5',lambda v:45<=v<=65),
        'MACD':compare('macd5','signal5'),'OBV':val('obv_degisim_15dk',lambda v:v>0),
        'BOLLINGER':compare('fiyat','boll_orta'),'MOMENTUM':val('momentum15',lambda v:v>0),
        'KIRILIM':bool(r['kirilim']) if isinstance(r.get('kirilim'),bool) else None,
        'HABER':val('haber_puani',lambda v:v>0),'MAKRO':val('makro_puani',lambda v:v>0),
        'SEKTOR':val('sektor_puani',lambda v:v>0),
        'REJIM':r['piyasa_rejimi'] in ('POZITIF','YUKSELIS','GUCLU_YUKSELIS') if r.get('piyasa_rejimi') in ('POZITIF','YUKSELIS','GUCLU_YUKSELIS','NOTR','YATAY','NEGATIF','DUSUS','GUCLU_DUSUS') else None}


def normalize_bars(data,current):
    if hasattr(data,'iterrows'):
        data=[dict(timestamp=str(at),**{k.lower():v for k,v in row.items()}) for at,row in data.iterrows()]
    bars={};bad=set()
    for row in data or []:
        at=stamp(row.get('timestamp') or row.get('time'))
        if not at or at.weekday()>=5 or at+timedelta(minutes=5)>current or row.get('complete') is False:continue
        if at.minute%5 or at.second or not time(10)<=at.time().replace(tzinfo=None)<time(18,10):continue
        values={k:number(row.get(k)) for k in ('open','high','low','close')}
        if any(v is None or v<=0 for v in values.values()) or not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:
            bad.add(at);continue
        bar=dict(timestamp=at.isoformat(),**values)
        if at in bars and bars[at]!=bar:bad.add(at)
        bars[at]=bar
    return [bars[k] for k in sorted(bars) if k not in bad]


def due_at(record,horizon):
    start=stamp(record['sinyal_zamani'])
    first=start.replace(second=0,microsecond=0)
    first+=timedelta(minutes=(-first.minute)%5)
    if first<start:first+=timedelta(minutes=5)
    # Arbitrary-second signals use the next full 5m candle, never a pre-signal bar.
    return datetime.combine(start.date(),time(18,10),ISTANBUL) if horizon=='SEANS' else min(first+timedelta(minutes=horizon),datetime.combine(start.date(),time(18,10),ISTANBUL))


def outcome(record,bars,horizon,current):
    start=stamp(record['sinyal_zamani']);due=due_at(record,horizon)
    empty={'durum':'VERI_YETERSIZ','tamamlandi':False,'observed_at':current.isoformat(),'vade':horizon}
    if current<due:return dict(empty,neden='VADE_GELMEDI')
    # Only bars beginning AFTER the signal: a pre-signal high/low is never credited.
    expected=[];at=start.replace(second=0,microsecond=0)
    at+=timedelta(minutes=(-at.minute)%5)
    if at<start:at+=timedelta(minutes=5)
    while at+timedelta(minutes=5)<=due:
        expected.append(at);at+=timedelta(minutes=5)
    mapping={stamp(b['timestamp']):b for b in normalize_bars(bars,current)}
    if not expected or any(at not in mapping for at in expected):return dict(empty,neden='EKSIK_5DK_MUM')
    used=[mapping[at] for at in expected];base=record['giris_fiyati'];target=number(record.get('hedef'));stop=number(record.get('stop'))
    levels=bool(target and stop and stop<base<target)
    first=None;target_hit=stop_hit=False
    for bar in used:
        th=levels and bar['high']>=target;sh=levels and bar['low']<=stop
        target_hit|=bool(th);stop_hit|=bool(sh)
        if first is None and (th or sh):first='BELIRSIZ' if th and sh else 'HEDEF' if th else 'STOP'
    gain=(used[-1]['close']/base-1)*100
    risk=(base-stop)/base*100 if levels else None
    rr=(target-base)/(base-stop) if levels else None
    # Not a short simulator: sell/reduced signals have descriptive results only.
    usable=record.get('karar')=='AL' and levels and rr>=1
    state='BELIRSIZ' if first=='BELIRSIZ' else 'STOP' if first=='STOP' else 'BASARILI' if usable and first=='HEDEF' else 'KISMEN_BASARILI' if usable and gain>=risk*.5 else 'BASARISIZ' if usable else 'REFERANS'
    from performans_motoru import excursion_metrics
    return dict(durum=state,tamamlandi=True,vade=horizon,observed_at=current.isoformat(),sonuc_zamani=due.isoformat(),
        **excursion_metrics(used,base,target,stop),
        model_version=record.get('model_version','LEGACY_UNKNOWN'),performance_source=record.get('performance_source','LIVE'),
        getiri_yuzde=gain,maksimum_yukselis=(max(b['high'] for b in used)/base-1)*100,
        maksimum_dusus=(min(b['low'] for b in used)/base-1)*100,hedef_temasi=target_hit,stop_temasi=stop_hit,
        ilk_temas=first,risk_getiri=rr,kullanim_suresi_dk=(due-start).total_seconds()/60,
        cozumleme='5m',egitime_uygun=usable and first!='BELIRSIZ')


def bounded(values,baseline):
    lower={k:max(BASE[k]*.5,baseline[k]-.005) for k in BASE};upper={k:min(BASE[k]*1.5,baseline[k]+.005) for k in BASE}
    lo,hi=-1.,1.
    for _ in range(80):
        shift=(lo+hi)/2;result={k:max(lower[k],min(upper[k],values[k]+shift)) for k in BASE}
        if sum(result.values())<1:lo=shift
        else:hi=shift
    return {k:round(v,12) for k,v in result.items()}


def apply_score(row,model,current):
    raw=number(row.get('gun_ici_puan'),0);flags=features(row)
    at=stamp(model.get('asof'));valid=not at or at<=current
    delta=sum((model.get('weights',BASE)[k]-BASE[k])*100 for k,v in flags.items() if v is True and k in model.get('approved',{})) if valid else 0
    delta=max(-3,min(3,delta))
    if raw<45 or row.get('_durum'):delta=0
    if any(number(row.get(k),0)<0 for k in ('haber_puani','makro_puani','sektor_puani')) or number(row.get('rsi5'),50)>=70:delta=min(0,delta)
    shadow=max(0,min(100,raw+delta))
    enabled=os.environ.get('GUN_ICI_LEARNING_ENABLED','false').lower()=='true'
    return {'gun_ici_ham_puan':raw,'gun_ici_shadow_puan':shadow,'gun_ici_final_puan':shadow if enabled else raw,
        'gun_ici_kalibrasyon_duzeltmesi':shadow-raw if enabled else 0,'gun_ici_model_version':model.get('version','BASE') if valid else 'BASE',
        'gun_ici_learning_enabled':enabled}


class GunIciPerformans:
    def __init__(self,location=None,clock=None,provider=None):
        self.location=location or paths();self.clock=clock or (lambda:datetime.now(ISTANBUL));self.provider=provider
        self.file=self.location.runtime/'gun_ici_sonuclar.json'
        self.weights_file=self.location.runtime/'gun_ici_agirliklari.json'
        self.bars_file=self.location.runtime/'gun_ici_mumlar.json'

    def state(self):return load(self.file,{'kayitlar':[],'listeler':[]})

    def model(self):return load(self.weights_file,{'weights':BASE,'approved':{},'version':'BASE','versions':{}})

    def rank(self,rows):
        from piyasa_baglami import PiyasaBaglami,annotate,effects
        from teknik_gostergeler import shadow
        current=self.clock().astimezone(ISTANBUL);model=self.model()
        from performans_motoru import controlled_context,controlled_score
        controlled=controlled_context(self.location,current,'INTRADAY')
        context=PiyasaBaglami(self.location,clock=self.clock).context('INTRADAY')
        if context:annotate(rows,context)
        for row in rows:
            row.update(apply_score(row,model,current))
            row.update(shadow(row,row['gun_ici_ham_puan'],current,'INTRADAY'))
            row.update(effects(row,row['gun_ici_ham_puan'],current,'INTRADAY'))
            from ai_karar_motoru import attach_final_decision
            attach_final_decision(row,current,'INTRADAY')
            row['controlled_shadow']=controlled_score(row,row['gun_ici_ham_puan'],current,'INTRADAY',controlled)
            row['gun_ici_kalibrasyon_sonrasi_puan']=row['gun_ici_final_puan']
            row['gun_ici_final_puan']=clamp(row['gun_ici_final_puan']+row['piyasa_baglami_etkisi'],0,100)
            row['gun_ici_shadow_puan']=clamp(row['gun_ici_shadow_puan']+row['piyasa_baglami_etkisi'],0,100)
            if row.get('gun_ici_guven') is not None:
                row['gun_ici_baglam_guven']=clamp(number(row['gun_ici_guven'],0)+row['piyasa_confidence_duzeltmesi'],0,100)
        key=lambda r:(r['gun_ici_final_puan'],number(r.get('hacim3_orani'),0),number(r.get('momentum15'),0))
        return sorted([r for r in rows if r['gun_ici_ham_puan']>=45],key=key,reverse=True)[:10]

    def cache_bars(self,by_symbol):
        current=self.clock().astimezone(ISTANBUL)
        with locked(self.bars_file):
            stored=load(self.bars_file,{})
            for symbol,data in by_symbol.items():
                fresh=normalize_bars(data,current)
                merged={b['timestamp']:b for b in stored.get(symbol,[])}
                merged.update({b['timestamp']:b for b in fresh})
                stored[symbol]=[b for _,b in sorted(merged.items()) if stamp(b['timestamp'])>=current-timedelta(days=7)]
            atomic_json(self.bars_file,stored)

    def record(self,top10,rows=None):
        current=self.clock().astimezone(ISTANBUL)
        if current.weekday()>=5 or not time(10)<=current.time().replace(tzinfo=None)<time(18,10):return []
        model=self.model();created=[]
        with locked(self.file):
            state=self.state();all_rows={r.get('sembol'):r for r in rows or top10}
            # Follow decisions on open records without altering the frozen analysis.
            for record in state['kayitlar']:
                if record['durum'] in ('HEDEF','STOP','SONLANDI'):continue
                row=all_rows.get(record['sembol'])
                if row:
                    decision=row.get('gun_ici_karar')
                    record['durum']='SAT_DONDU' if decision=='SAT' else 'ZAYIFLIYOR' if decision!='AL' else 'AL_DEVAM'
                    record['sinyal_yasi_dk']=max(0,(current-stamp(record['sinyal_zamani'])).total_seconds()/60)
            membership=[];shadow_members=[]
            candidates=[r for r in (rows or top10) if number(r.get('gun_ici_puan'),0)>=45]
            shadow=sorted(candidates,key=lambda r:(number(r.get('gun_ici_shadow_puan'),number(r.get('gun_ici_puan'),0)),number(r.get('hacim3_orani'),0),number(r.get('momentum15'),0)),reverse=True)[:10]
            controlled=sorted(candidates,key=lambda r:number((r.get('controlled_shadow') or {}).get('score'),number(r.get('gun_ici_puan'),0)),reverse=True)[:10]
            to_record=list(top10)+[r for r in shadow if r.get('sembol') not in {x.get('sembol') for x in top10}]
            to_record.extend(r for r in controlled if r.get('sembol') not in {x.get('sembol') for x in to_record})
            # A list occurrence can reference an older signal; first occurrence/rank is frozen.
            for rank,row in enumerate(to_record,1):
                symbol=row.get('sembol');price=number(row.get('fiyat'),0);source=stamp(row.get('veri_tarihi'))
                if not symbol or price<=0 or not source or source+timedelta(minutes=5)>current or (current-source).total_seconds()>900:continue
                previous=next((r for r in reversed(state['kayitlar']) if r['sembol']==symbol and r['sinyal_zamani'][:10]==current.date().isoformat()),None)
                meaningful=previous is None or previous['karar']!=row.get('gun_ici_karar','IZLE') or previous['durum'] in ('HEDEF','STOP','SONLANDI')
                if previous:
                    meaningful|=abs(price/previous['giris_fiyati']-1)>=.01 or abs(number(row.get('gun_ici_puan'),0)-previous['skor'])>=5
                    for name,field in (('hedef','gun_ici_kar_al'),('stop','gun_ici_stop')):
                        old=number(previous.get(name));new=number(row.get(field))
                        meaningful|=bool(old and new and abs(new/old-1)>=.01)
                    # Repeated calls on one source candle cannot manufacture another signal.
                    if source<=stamp(previous['kaynak_zamani']):meaningful=False
                if not meaningful:membership.append(previous['id']);continue
                snapshot=json.loads(json.dumps(row,default=str))
                identity=hashlib.sha256((symbol+'|'+source.isoformat()+'|'+json.dumps(snapshot,sort_keys=True)).encode()).hexdigest()[:24]
                if any(r['id']==identity for r in state['kayitlar']):continue
                record={'id':identity,'sembol':symbol,'sinyal_zamani':current.isoformat(),'kaynak_zamani':source.isoformat(),
                    'performance_source':'LIVE',
                    'sinyal_yasi_dk':number(row.get('gun_ici_sinyal_yasi_dk'),0),'giris_fiyati':price,
                    'skor':number(row.get('gun_ici_puan'),0),'karar':row.get('gun_ici_karar','IZLE'),
                    'alim_alt':row.get('gun_ici_alim_alt'),'alim_ust':row.get('gun_ici_alim_ust'),
                    'hedef':row.get('gun_ici_kar_al'),'stop':row.get('gun_ici_stop'),
                    'sektor':row.get('makro_sektor'),'piyasa_rejimi':row.get('piyasa_rejimi'),
                    'ai_score':row.get('gun_ici_nihai_ai_puan'),'confidence':row.get('gun_ici_guven'),
                    'analiz':snapshot,'durum':'YENI_AL' if row.get('gun_ici_karar')=='AL' else 'SAT_DONDU' if row.get('gun_ici_karar')=='SAT' else 'ZAYIFLIYOR',
                    'ilk_sira':rank,'ana_liste_adayi':symbol in {x.get('sembol') for x in top10},
                    'teknik_gostergeler':snapshot.get('teknik_gostergeler'),
                    'nihai_karar':snapshot.get('nihai_karar'),
                    'controlled_shadow':snapshot.get('controlled_shadow'),
                    'controlled_shadow_adayi':symbol in {x.get('sembol') for x in controlled},
                    'teknik_katkilar':snapshot.get('teknik_katkilar'),
                    'teknik_shadow_puan':snapshot.get('teknik_shadow_puan'),
                    'piyasa_baglami':snapshot.get('piyasa_baglami'),
                    'model_version':row.get('gun_ici_model_version',model.get('version','BASE') if not stamp(model.get('asof')) or stamp(model['asof'])<=current else 'BASE'),
                    'sonuclar':{}}
                state['kayitlar'].append(record);membership.append(identity);created.append(identity)
            ids={r['sembol']:r['id'] for r in state['kayitlar'] if r['id'] in membership}
            membership=[ids[r['sembol']] for r in top10 if r.get('sembol') in ids]
            shadow_members=[ids[r['sembol']] for r in shadow if r.get('sembol') in ids]
            if membership:
                signature=hashlib.sha256(json.dumps([membership,shadow_members]).encode()).hexdigest()[:24]
                if not any(x['id']==signature and x['tarih']==current.date().isoformat() for x in state['listeler']):
                    state['listeler'].append({'id':signature,'tarih':current.date().isoformat(),'zaman':current.isoformat(),'uyeler':membership,'shadow':shadow_members})
            atomic_json(self.file,state)
        return created

    def prices(self,symbol):
        if self.provider:return self.provider(symbol)
        # Existing project provider, same interval as gun_ici_analiz_hesapla.
        import bist_bot
        return bist_bot.bp.Ticker(symbol).history(period='5d',interval='5m')

    def signal_round(self,holiday=None,daily_provider=None):
        """Frozen V1 adapter on the existing driver/provider/calendar infrastructure."""
        from intraday_sinyal_performansi import (load_sources,observations,fingerprint,due_at,
            outcome as signal_outcome,HORIZONS as signal_horizons,publish)
        from performans_motoru import provider_history
        from gorev_hatalari import remember,describe,TaskIssue,strongest
        current=self.clock().astimezone(ISTANBUL)
        source,source_errors=load_sources(self.location,current)
        observed,duplicates,malformed=observations(source,current)
        result_root=self.location.runtime_file('intraday_signal_results')
        control_path=self.location.runtime_file('intraday_signal_performance_state.json')
        with locked(control_path):
            control=load(control_path,{'cursor':0});results={};by_day={}
            for index,(row,issue) in enumerate(observed):
                at=stamp(row.get('timestamp'))
                if not at:continue
                day=at.date().isoformat()
                if day not in by_day:
                    try:
                        by_day[day]=load(result_root/(day+'.json'),{'events':{}})
                        if not isinstance(by_day[day],dict) or not isinstance(by_day[day].get('events'),dict):raise ValueError('Derived results')
                    except Exception as error:
                        by_day[day]=None;source_errors['RESULT_'+day]=type(error).__name__
                if by_day[day] is None:
                    observed[index]=(row,issue or 'DERIVED_FILE_INVALID');continue
                saved=by_day[day]['events'].get(row['event_id'])
                if saved and (not isinstance(saved,dict) or not isinstance(saved.get('outcomes'),dict)):
                    observed[index]=(row,issue or 'DERIVED_RECORD_INVALID');continue
                if saved:results[row['event_id']]=saved
            pending=[]
            for row,issue in observed:
                if issue:continue
                saved=results.get(row['event_id'],{})
                if saved and saved.get('source_hash')!=fingerprint(row):continue
                retry=stamp(saved.get('retry_at'))
                if retry and retry>current:continue
                due=[h for h in signal_horizons if due_at(row,h,holiday)<=current and not saved.get('outcomes',{}).get(h,{}).get('completed')]
                if due:pending.append((row,due))
            symbols=list(dict.fromkeys(row['symbol'] for row,_ in pending));batch=[]
            if symbols:
                cursor=control.get('cursor',0)%len(symbols)
                batch=[symbols[(cursor+i)%len(symbols)] for i in range(min(10,len(symbols)))]
                control['cursor']=(cursor+len(batch))%len(symbols)
            cache=load(self.bars_file,{})
            daily_cache=load(self.location.runtime_file('performans_fiyat_cache.json'),{})
            failures=[];failed_symbols=set();updated=0;dirty=set()
            for symbol in batch:
                selected=[(r,hs) for r,hs in pending if r['symbol']==symbol][:50]
                try:
                    bars=cache.get(symbol,[])
                    needs_fresh=any(signal_outcome(r,bars,[],'SEANS' if h in ('D1','D3') else h,current,holiday).get('reason')=='MISSING_5M_BAR'
                        for r,hs in selected for h in hs)
                    if needs_fresh:
                        fresh=normalize_bars(self.prices(symbol),current)
                        bars=normalize_bars(list(bars)+fresh,current)
                    prices=[]
                    if any(h in ('D1','D3') for _,hs in selected for h in hs):
                        cached=daily_cache.get(symbol,{})
                        if cached.get('day')==current.date().isoformat() and cached.get('closed')==session_closed(current.date(),current):prices=cached['bars']
                        else:prices=list((daily_provider or provider_history)(symbol))
                    for row,hs in selected:
                        try:
                            key=row['event_id'];saved=copy.deepcopy(results.get(key,{'source_hash':fingerprint(row),'outcomes':{}}))
                            for horizon in hs:
                                value=signal_outcome(row,bars,prices,horizon,current,holiday)
                                saved['outcomes'][horizon]=value;updated+=int(value['completed'])
                            age=current-stamp(row['timestamp'])
                            saved['retry_at']=(current+(timedelta(hours=6) if age>timedelta(days=5) else timedelta(minutes=5))).isoformat()
                            results[key]=saved;day=stamp(row['timestamp']).date().isoformat();by_day[day]['events'][key]=saved;dirty.add(day)
                        except Exception as error:
                            remember(error,'INTRADAY_SIGNAL_PERFORMANCE',symbol);failures.append(describe(error));failed_symbols.add(symbol)
                except Exception as error:
                    remember(error,'INTRADAY_SIGNAL_PERFORMANCE',symbol);failures.append(describe(error));failed_symbols.add(symbol)
                    for row,_ in selected:
                        key=row['event_id'];saved=copy.deepcopy(results.get(key,{'source_hash':fingerprint(row),'outcomes':{}}))
                        saved['retry_at']=(current+timedelta(minutes=5)).isoformat();results[key]=saved
                        day=stamp(row['timestamp']).date().isoformat();by_day[day]['events'][key]=saved;dirty.add(day)
            for day in dirty:
                target=result_root/(day+'.json')
                with locked(target):atomic_json(target,by_day[day])
            atomic_json(control_path,control)
            diagnostics={'processed':len(batch),'successful':len(batch)-len(failed_symbols),'failed':len(failed_symbols)+len(source_errors),
                         'updated_outcomes':updated,'source_errors':source_errors,'duplicates':duplicates,'malformed':malformed}
            publish(self.location,observed,results,current,holiday,diagnostics)
        if source_errors:
            import logging
            logging.warning('[INTRADAY_SIGNAL_PERFORMANCE] unreadable_source_files=%d',len(source_errors))
            failures.append({'code':'STORAGE_IO'})
        if failures:raise TaskIssue(strongest(failures),len(batch)-len(failed_symbols),diagnostics)
        return {'diagnostics':diagnostics}

    def one_round(self):
        current=self.clock().astimezone(ISTANBUL);limit=max(1,min(25,int(os.environ.get('GUN_ICI_PERFORMANCE_BATCH_SIZE','10'))))
        with locked(self.file):state=self.state()
        pending=[r for r in state['kayitlar'] if any(str(h) not in r['sonuclar'] and due_at(r,h)<=current for h in HORIZONS)
                 and (not stamp(r.get('retry_at')) or stamp(r['retry_at'])<=current)]
        symbols=list(dict.fromkeys(r['sembol'] for r in pending))[:limit];updates={};errors={}
        cache=load(self.bars_file,{})
        for symbol in symbols:
            records=[r for r in pending if r['sembol']==symbol][:10]
            try:
                bars=cache.get(symbol,[])
                if any(not outcome(r,bars,h,current)['tamamlandi'] for r in records for h in HORIZONS if str(h) not in r['sonuclar'] and due_at(r,h)<=current):
                    fresh=normalize_bars(self.prices(symbol),current)
                    mapping={b['timestamp']:b for b in bars};mapping.update({b['timestamp']:b for b in fresh});bars=list(mapping.values())
                for r in records:
                    results={};missing=False
                    for h in HORIZONS:
                        if str(h) in r['sonuclar'] or due_at(r,h)>current:continue
                        result=outcome(r,bars,h,current)
                        if result['tamamlandi']:results[str(h)]=result
                        elif current.date()>stamp(r['sinyal_zamani']).date()+timedelta(days=5):
                            results[str(h)]=dict(result,tamamlandi=True,neden='PROVIDER_KAPSAMI_YETERSIZ')
                        else:missing=True
                    updates[r['id']]=(results,missing)
            except Exception as error:errors[symbol]=type(error).__name__
        with locked(self.file):
            state=self.state()
            for r in state['kayitlar']:
                if r['id'] in updates:
                    results,missing=updates[r['id']]
                    for h,result in results.items():r['sonuclar'].setdefault(h,result)
                    r['retry_at']=(current+timedelta(minutes=5)).isoformat() if missing else None
                    r['sinyal_yasi_dk']=max(0,(current-stamp(r['sinyal_zamani'])).total_seconds()/60)
                    contacts=[r['sonuclar'][str(h)].get('ilk_temas') for h in HORIZONS if str(h) in r['sonuclar']]
                    contact=next((c for c in contacts if c),None)
                    if contact in ('HEDEF','STOP'):r['durum']=contact
                    elif 'SEANS' in r['sonuclar']:r['durum']='SONLANDI'
                elif r['sembol'] in errors:r['retry_at']=(current+timedelta(minutes=5)).isoformat()
            atomic_json(self.file,state)
        self.publish_and_learn(state,current)
        return {'kontrol_edilen_sembol':len(symbols),'guncellenen_sinyal':len(updates),'hatalar':errors}

    def publish_and_learn(self,state,current):
        # One fixed first completed signal per symbol/day; recurring scans cannot inflate evidence.
        selected={};views=[];seen=set()
        for r in sorted(state['kayitlar'],key=lambda r:r['sinyal_zamani']):
            if r.get('karar')!='AL':continue
            key=(r['sembol'],r['sinyal_zamani'][:10])
            if key in seen:continue
            seen.add(key)  # Selection is fixed before observing eligibility or outcome.
            result=r['sonuclar'].get('60',{});at=stamp(result.get('observed_at'))
            if not result.get('egitime_uygun') or not at or at>current or stamp(r['sinyal_zamani'])>current:continue
            selected[key]=r
            views.append(dict(r,zaman=r['sinyal_zamani'],sonuc_1g=dict(result,degerlendirme_tamamlandi=True),egitim_durumu='EGITIM'))
        minimum=max(40,int(os.environ.get('GUN_ICI_MIN_LEARNING_SAMPLES','40')))
        report=criterion_report(views,minimum=minimum,feature_fn=features)
        with locked(self.weights_file):
            model=self.model();day=current.date().isoformat()
            if model.get('refresh_day')!=day:
                baseline=model.get('weights',BASE)
                # Backdated runs cannot reuse coefficients learned in the future.
                if stamp(model.get('asof')) and stamp(model['asof'])>current:baseline=BASE
                proposed=dict(baseline);approved={}
                for key,v in report['kriterler'].items():
                    if v['onerilen_agirlik_yonu'] in ('ARTIR','AZALT'):
                        proposed[key]+=.0025 if v['onerilen_agirlik_yonu']=='ARTIR' else -.0025
                        approved[key]=v
                weights=bounded(proposed,baseline) if approved else dict(baseline)
                version='GUN_ICI_'+day+'_'+hashlib.sha256(json.dumps([weights,approved],sort_keys=True).encode()).hexdigest()[:16]
                variant={'weights':weights,'approved':approved,'asof':current.isoformat()}
                versions=model.get('versions',{});versions[version]=variant
                model=dict(model,**variant,version=version,versions=versions,refresh_day=day)
                atomic_json(self.weights_file,model)
        daily={};by_id={r['id']:r for r in state['kayitlar']}
        reporting={};seen=set()
        for r in sorted(state['kayitlar'],key=lambda r:r['sinyal_zamani']):
            if r.get('ana_liste_adayi') is False:continue
            key=(r['sembol'],r['sinyal_zamani'][:10])
            if key in seen:continue
            seen.add(key)
            result=r['sonuclar'].get('60',{});at=stamp(result.get('observed_at'))
            if result.get('tamamlandi') and at and at<=current and number(result.get('getiri_yuzde')) is not None:
                reporting[key]=r
        for r in reporting.values():daily.setdefault(r['sinyal_zamani'][:10],[]).append(r)
        def summary(rows):
            pairs=[(r,r['sonuclar'].get('60',{})) for r in rows];pairs=[(r,v) for r,v in pairs if v.get('tamamlandi') and number(v.get('getiri_yuzde')) is not None]
            gains=[v['getiri_yuzde'] for _,v in pairs]
            ranked=sorted(pairs,key=lambda p:p[0]['skor'],reverse=True)
            correlation=None
            if len(ranked)>1:
                x=[r['skor'] for r,v in ranked];y=[v['getiri_yuzde'] for r,v in ranked];xm,ym=mean(x),mean(y)
                denom=(sum((v-xm)**2 for v in x)*sum((v-ym)**2 for v in y))**.5
                if denom:correlation=sum((a-xm)*(b-ym) for a,b in zip(x,y))/denom
            return dict(robust(gains),pozitif_aday=sum(v>0 for v in gains),hedef=sum(v.get('ilk_temas')=='HEDEF' for _,v in pairs),
                stop=sum(v.get('ilk_temas')=='STOP' for _,v in pairs),top3=robust([v['getiri_yuzde'] for _,v in ranked[:3]]),
                top5=robust([v['getiri_yuzde'] for _,v in ranked[:5]]),top10=robust([v['getiri_yuzde'] for _,v in ranked[:10]]),
                en_iyi=max(({'sembol':r['sembol'],'getiri':v['getiri_yuzde']} for r,v in pairs),key=lambda v:v['getiri'],default=None),
                en_kotu=min(({'sembol':r['sembol'],'getiri':v['getiri_yuzde']} for r,v in pairs),key=lambda v:v['getiri'],default=None),skor_getiri_korelasyonu=correlation)
        comparisons=[]
        for listing in state['listeler'][-100:]:
            def result(ids):
                rows=[by_id[i] for i in ids if i in by_id]
                if not rows:return None
                for r in rows:
                    value=r['sonuclar'].get('60',{});observed=stamp(value.get('observed_at'));end=stamp(value.get('sonuc_zamani'))
                    if not value.get('tamamlandi') or not observed or observed>current or not end or end<=stamp(listing['zaman']):return None
                gains=[r['sonuclar']['60'].get('getiri_yuzde') for r in rows]
                if any(v is None for v in gains):return None
                return dict(robust(gains),top3=robust(gains[:3]),top5=robust(gains[:5]),top10=robust(gains[:10]))
            comparisons.append({'tarih':listing['tarih'],'zaman':listing['zaman'],'mevcut':result(listing['uyeler']),'shadow':result(listing['shadow'])})
        self.location.public.mkdir(parents=True,exist_ok=True)
        def grouped(field):
            groups={}
            for r in reporting.values():groups.setdefault(r.get(field) or 'BILINMIYOR',[]).append(r)
            return {k:summary(rs) for k,rs in groups.items()}
        from teknik_gostergeler import performance_report
        technical=performance_report(state['kayitlar'],current,'INTRADAY',minimum)
        from ai_karar_motoru import final_decision_report
        final_report=final_decision_report(list(reporting.values()),current,'INTRADAY')
        atomic_json(self.location.public/'gun_ici_performans.json',{'updated_at':current.isoformat(),'ana_vade_dk':60,'gunler':{d:summary(rs) for d,rs in daily.items()},
            'sektorler':grouped('sektor'),'rejimler':grouped('piyasa_rejimi'),
            'kriterler':report,'standart_teknik_kriterler':technical,'nihai_karar_performansi':final_report,'shadow_karsilastirmasi':comparisons,'ornek_birimi':'HISSE_GUN','learning_enabled':os.environ.get('GUN_ICI_LEARNING_ENABLED','false').lower()=='true'})
        atomic_json(self.location.public/'gun_ici_onerilen_agirliklar.json',{'updated_at':current.isoformat(),'version':model['version'],'oneriler':model['approved'],
            'minimum_her_grup':minimum,'minimum_islem_gunu':5,'otomatik_aktivasyon':False})
        from performans_motoru import controlled_publish
        controlled_publish(self.location,state['kayitlar'],current,'INTRADAY')


def bekleyen_gun_ici_sonuclari_guncelle(**kwargs):return GunIciPerformans(**kwargs).one_round()
