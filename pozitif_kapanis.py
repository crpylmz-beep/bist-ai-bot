"""Closing candidate analysis; consumes existing indicators, never activates learning."""
import copy
import math
import os
import hashlib
import json
from datetime import datetime,time,timedelta
from statistics import median
from ai_karar_motoru import ISTANBUL,number,stamp,load,locked,attach_final_decision
from kullanici_kayitlari import atomic_json
from performans_motoru import (evidence_features,evidence_limits,evidence_report,diagnostic_stats,combination_catalog,
                               combination_report,combination_limits,signal_day,distribution,robust,POSITIVE_HORIZONS)
MODEL='POSITIVE_OPPORTUNITY_V1'


def enrich_closing_sources(rows,location,cutoff):
    from piyasa_baglami import usable_context,annotate
    market=usable_context(load(location.public/'piyasa_durumu.json',{}),cutoff,'YARIN')
    if market:annotate(rows,market)
    summaries=load(location.public/'ai_hisse_ozetleri.json',{}).get('hisseler',{})
    intraday=load(location.public/'gun_ici_tum.json',{})
    intraday={r.get('sembol'):r for r in intraday.get('hisseler',[]) if isinstance(r,dict)}
    macro=load(location.public/'makro_canli_etki.json',{});macro_at=stamp(macro.get('updated_at') or macro.get('guncelleme'))
    for row in rows:
        doc=(intraday.get(row.get('sembol')) or {}).get('teknik_gostergeler') or {}
        at=stamp(doc.get('asof'));data_at=stamp(doc.get('data_time'));vw=doc.get('vwap') or {}
        if at and data_at and data_at<=at<=cutoff and data_at.date()==cutoff.date() and cutoff-data_at<=timedelta(minutes=20) and not doc.get('stale') and vw.get('status')=='OK' and number(vw.get('session_value'),0)>0:
            daily=row.get('teknik_gostergeler') or {};reference=(daily.get('vwap') or {}).get('reference_20')
            daily['vwap']=copy.deepcopy(vw);daily['vwap'].update(source_mode='INTRADAY',source_asof=at.isoformat(),source_data_time=data_at.isoformat(),reference_20=reference,
                observation_scope='LAST_KNOWN_SESSION_VWAP_AT_OR_BEFORE_CLOSE')
            row['teknik_gostergeler']=daily
        previous=summaries.get(row.get('sembol')) or {};at=stamp(previous.get('updated_at'))
        if at and at<=cutoff and cutoff-at<=timedelta(hours=24):
            row['haber_katkilari']=[dict(n,observed_at=at.isoformat()) for n in previous.get('haber_katkilari') or []]
            if row['haber_katkilari']:
                row['haber_puani']=max(-10,min(10,sum(number(n.get('etki'),0) for n in row['haber_katkilari'])))
                row['haber_guven']=previous.get('confidence');row['haber_asof']=at.isoformat();row['gecmis_model_performansi']=previous.get('gecmis_basari')
        if macro_at and macro_at<=cutoff and cutoff-macro_at<=timedelta(hours=24):
            values=macro.get('hisseler',{}).get(row.get('sembol')) or {}
            for key in ('makro_puani','sektor_puani'):row[key]=values.get(key)
            row['makro_asof']=macro_at.isoformat()
    return rows


def closing_inputs(row,cutoff):
    """Reused closed-bar values may be calculated later; contextual knowledge must predate close."""
    raw=copy.deepcopy(row);doc=raw.get('teknik_gostergeler') or {};data=stamp(doc.get('data_time'))
    quality=[]
    if not data or data.date()!=cutoff.date() or data>cutoff or doc.get('stale') or doc.get('mode')!='TOMORROW':quality.append('STALE_OR_MISSING_CLOSE')
    if number(raw.get('fiyat'),0)<=0:quality.append('PRICE_MISSING')
    if any(number(raw.get(k)) is None for k in ('rsi','macd','signal','sma20','sma50','atr14','hacim_orani')):quality.append('TECHNICAL_DATA_MISSING')
    closing=doc.get('closing') or {};turnover=number(closing.get('turnover_tl'))
    close=number(closing.get('close'));previous=number(closing.get('previous_close'))
    if close is None or previous is None or previous<=0:quality.append('CLOSE_REFERENCE_MISSING')
    elif abs(number(raw.get('fiyat'),0)-close)>max(.01,close*.0001):quality.append('CLOSE_PRICE_MISMATCH')
    else:raw['degisim']=(close/previous-1)*100
    minimum=float(os.environ.get('POSITIVE_MIN_TURNOVER_TL','1000000'))
    if not math.isfinite(minimum) or minimum<0:raise ValueError('POSITIVE_MIN_TURNOVER_TL >=0')
    if turnover is None or turnover<minimum:quality.append('LOW_OR_UNKNOWN_LIQUIDITY')
    raw['calculated_at']=doc.get('asof');raw['canli_guncelleme']=cutoff.isoformat()
    if not quality:doc['asof']=cutoff.isoformat();raw['teknik_gostergeler']=doc
    ctx=raw.get('piyasa_baglami') or {};at=stamp(ctx.get('updated_at'))
    if not at or at>cutoff:raw['piyasa_baglami']={};raw['piyasa_rejimi']='BILINMIYOR';raw['sektor_rs_score']=None
    news=[n for n in raw.get('haber_katkilari') or [] if stamp(n.get('observed_at') or n.get('updated_at')) and stamp(n.get('observed_at') or n.get('updated_at'))<=cutoff]
    metadata=raw.get('haber_metadata') or {};at=stamp(metadata.get('observed_at') or metadata.get('updated_at'))
    if at and at<=cutoff:news.append(metadata)
    raw['haber_katkilari']=news;raw['haber_metadata']={}
    # Never carry a live aggregate containing later news alongside filtered old events.
    known_scores=[number(n.get('etki'),number(n.get('etki_puani'))) for n in news]
    known_scores=[v for v in known_scores if v is not None]
    raw['haber_puani']=max(-10,min(10,sum(known_scores))) if known_scores else None
    news_at=stamp(raw.get('haber_asof'))
    if not news_at or news_at>cutoff:raw['haber_guven']=None;raw['haber_fiyat_teyidi']=None
    raw['haber_etkisi']=raw['haber_puani']
    raw['provenance_risks']=[]
    if not news and number(row.get('haber_puani'),0)<=-5:raw['provenance_risks'].append('UNVERIFIED_CRITICAL_NEWS')
    macro_at=stamp(raw.get('makro_updated_at') or raw.get('makro_asof'))
    if not macro_at or macro_at>cutoff:raw['makro_puani']=None;raw['sektor_puani']=None
    if (not macro_at or macro_at>cutoff) and number(row.get('makro_puani'),0)<=-5:raw['provenance_risks'].append('UNVERIFIED_NEGATIVE_MACRO')
    raw['nihai_karar']={};raw['controlled_shadow']=None
    return raw,quality


def continuation_pairs(records,current,horizon=1):
    chosen={}
    for r in sorted(records,key=lambda r:str(r.get('zaman',''))):
        at=stamp(r.get('zaman'))
        if r.get('model')!='POSITIVE_CANDIDATE' or r.get('performance_source','LIVE')!='LIVE' or not at or at>=current:continue
        chosen.setdefault((r.get('sembol'),at.date()),r)
    pairs=[]
    for r in chosen.values():
        o=r.get('sonuc_'+str(horizon)+'g') or {};at=stamp(o.get('observed_at'));value=number(o.get('getiri_yuzde'))
        if not at or at>current or at<stamp(r['zaman']) or not o.get('degerlendirme_tamamlandi') or value is None:continue
        if any(number(o.get(k)) is None for k in ('ertesi_gun_acilis','ertesi_gun_kapanis','ertesi_gun_yuksek','ertesi_gun_dusuk')):continue
        if any(k in (o.get('kalite_uyarilari') or []) for k in ('OHLC_EKSIK','ISLEM_GUNU_EKSIK')):continue
        label='CONTINUED' if value>.1 else 'FAILED_CONTINUATION' if value<-.1 else 'NEUTRAL'
        proxy={**o,'trade_outcome':o.get('durum'),'continuation_class':label,
               'positive_close':value>0,'prediction_correct':value>.1,'durum':'BASARILI' if label=='CONTINUED' else 'BASARISIZ' if label=='FAILED_CONTINUATION' else 'KISMEN_BASARILI'}
        pairs.append((r,proxy,evidence_features(r,'DAILY')))
    return pairs


def historical_expectation(row,flags,history,cutoff,horizon):
    pairs=history.get(str(horizon),[]) if isinstance(history,dict) else continuation_pairs(history,cutoff,horizon);matches=[]
    for p in pairs:
        r,o,f=p;known=[k for k,v in flags.items() if isinstance(v,bool) and isinstance(f.get(k),bool) and k not in ('AL','SAT','BEKLE','GUCLU_AL','GUCLU_SAT')]
        if number(o.get('mae_pct')) is None:continue
        if len(known)>=5 and sum(flags[k]==f[k] for k in known)/len(known)>=.7:
            if row.get('piyasa_rejimi') not in (None,'BILINMIYOR') and r.get('piyasa_rejimi')!=row['piyasa_rejimi']:continue
            matches.append(p)
    stats=diagnostic_stats(matches,50,7)
    if not stats['sufficient']:return None
    mae=[abs(number(o.get('mae_pct'),0)) for r,o,f in matches]
    # Conservative expectation penalizes actual adverse excursion, no positive outlier average.
    estimate=stats['median_return']-.15*median(mae)
    return {'expected_return':round(estimate,4),'probability':round((stats['success_count']+1)/(stats['sample_count']+2)*100,2),
            'sample_count':stats['sample_count'],'different_days':stats['different_days'],'method':'HISTORICAL_SIMILAR_FROZEN_SIGNALS'}


def opportunity(row,cutoff,history,legacy_score):
    doc=row.get('teknik_gostergeler') or {};closing=doc.get('closing') or {};mom=doc.get('momentum') or {};bb=doc.get('bollinger') or {};obv=doc.get('obv') or {};vw=doc.get('vwap') or {}
    flags=evidence_features(dict(row,zaman=cutoff.isoformat()),'DAILY')
    true=lambda key:flags.get(key) is True
    price=number(row.get('fiyat'),0);atr=number(row.get('atr14'),0);rr=number(row.get('karar_rr'),number(row.get('risk_getiri')))
    rsi=number(row.get('rsi'),50);change=number(row.get('degisim'),0);volume=number(row.get('hacim_orani'),0)
    resistance=number(row.get('direnc'));distance=(resistance/price-1)*100 if resistance and price else None
    acceleration=number(mom.get('acceleration'),0);vol_accel=number(closing.get('volume_acceleration'),0)
    early=min(100,20+15*(vol_accel>0)+15*true('OBV_KIRILIM')+15*bool(mom.get('positive_turn'))+10*(acceleration>0)+10*bool(closing.get('macd_hist_improving'))+10*(vw.get('transition')=='VWAP_RECLAIM')+10*bool(bb.get('squeeze_volume_momentum_break'))+5*true('SEKTOR_GUCLU'))
    sustain=max(0,min(100,25+15*(volume>=100)+10*(acceleration>0)+10*true('OBV_TREND')+10*true('SMA_TREND')+10*(distance is not None and distance>=3)+10*true('SEKTOR_GUCLU')+10*true('PIYASA_POZITIF')-15*(rsi>=68)-15*true('PIYASA_NEGATIF')-10*true('HABER_NEGATIF')))
    penalty=8*(change>=5)+12*(change>=6)+25*(change>=7)+15*(rsi>=68)+10*(distance is not None and distance<2)+10*(number(closing.get('return_3d'),0)>10)+10*(vol_accel<-.2)
    reference=number(vw.get('session_value'),number(vw.get('reference_20')))
    if reference and price/reference>1.1:penalty+=10
    penalty=min(80,penalty)
    heuristic_prob=max(10,min(90,25+.3*sustain+.25*early-penalty*.5))
    estimates={str(h):historical_expectation(row,flags,history,cutoff,h) for h in (1,3,5)}
    # Cold-start is explicitly a technical scenario, never a calibrated statistical forecast.
    scenario=max(-5,min(5,(atr/price*100 if price else 0)*(heuristic_prob/100-.35)*min(2,rr or 0)-penalty*.03))
    expected={str(h):(estimates[str(h)]['expected_return'] if estimates[str(h)] else round(scenario*math.sqrt(h),4)) for h in (1,3,5)}
    probability=estimates['1']['probability'] if estimates['1'] else round(heuristic_prob,2)
    coverage=sum(v is not None for k,v in flags.items() if k not in ('AL','SAT','BEKLE','GUCLU_AL','GUCLU_SAT'))/31
    base_conf=number((row.get('nihai_karar') or {}).get('confidence'),number(row.get('guven_skoru'),50))
    confidence=min(85 if estimates['1'] else 60,base_conf,35+65*coverage)
    technical=max(0,min(100,legacy_score));risk='YUKSEK' if penalty>=25 or (atr/price*100 if price else 100)>5 else 'DUSUK' if rr and rr>=2 and sustain>=65 else 'ORTA'
    sector=70 if true('SEKTOR_GUCLU') else 30 if true('SEKTOR_ZAYIF') else 50;market=70 if true('PIYASA_POZITIF') else 30 if true('PIYASA_NEGATIF') else 50
    news=60 if true('HABER_POZITIF') and true('HABER_FIYAT_TEYIDI') else 20 if true('HABER_NEGATIF') else 50
    components={'expected_return':max(0,min(100,50+expected['1']*10)),'continuation':probability,'early':early,'sustainability':sustain,'technical':technical,
                'volume':max(0,min(100,volume/2)),'sector':sector,'market':market,'news':news,
                'macro':70 if true('MAKRO_POZITIF') else 30 if true('MAKRO_NEGATIF') else 50,
                'breadth':70 if true('BREADTH_POZITIF') else 30 if true('BREADTH_NEGATIF') else 50,
                'risk_reward':min(100,(rr or 0)*30),'confidence':confidence}
    weights={'expected_return':.15,'continuation':.15,'early':.1,'sustainability':.1,'technical':.14,'volume':.08,'sector':.03,'market':.03,'news':.03,'macro':.02,'breadth':.02,'risk_reward':.08,'confidence':.07}
    score=max(0,min(100,sum(components[k]*w for k,w in weights.items())-penalty*.4-(10 if risk=='YUKSEK' else 0)))
    reasons=[text for yes,text in ((vol_accel>0,'Hacim ivmesi pozitif'),(true('OBV_KIRILIM'),'OBV kırılımı'),(acceleration>0,'Momentum güçleniyor'),(true('SEKTOR_GUCLU'),'Sektör güçlü'),(early>=55,'Erken hareket işaretleri'),(distance is not None and distance>=3,'Direnç mesafesi uygun')) if yes]
    risks=[text for yes,text in ((penalty>0,'Uzamış hareket/direnç riski'),(true('PIYASA_NEGATIF'),'Negatif piyasa rejimi'),(true('HABER_NEGATIF'),'Negatif haber'),(not estimates['1'],'İstatistiksel örnek yetersiz; teknik senaryo'),(coverage<.6,'Bazı kriterler bilinmiyor')) if yes]
    blocks=list(row.get('provenance_risks') or []);final=row.get('nihai_karar') or {}
    if legacy_score<55:blocks.append('EXISTING_ELIGIBILITY')
    if change>=7:blocks.append('EXTENDED_MOVE_HARD_GATE')
    if change<=-7:blocks.append('HARD_FALL')
    if rr is None or rr<1.5:blocks.append('LOW_RISK_REWARD')
    stop=number(row.get('karar_stop'),number(row.get('yarin_stop')));target=number(row.get('karar_hedef'),number(row.get('yarin_kar_al')))
    if stop is None or target is None or not stop<price<target:blocks.append('INVALID_STOP_TARGET')
    if true('HABER_NEGATIF') and number(row.get('haber_puani'),0)<=-5:blocks.append('NEGATIVE_CRITICAL_NEWS')
    if final.get('safety_flags'):blocks.extend(final['safety_flags'])
    if final.get('karar') not in ('AL','GUCLU_AL'):blocks.append('FINAL_AI_NOT_BUY')
    if confidence<40 or score<50:blocks.append('QUALITY_THRESHOLD')
    return {'model_version':MODEL,'captured_at':cutoff.isoformat(),'current_return':change,'future_opportunity_score':round(score,4),
        'expected_return_next_session':expected['1'],'expected_return_3d':expected['3'],'expected_return_5d':expected['5'],
        'expected_return':expected['1'],'expected_return_method':{str(h):estimates[str(h)]['method'] if estimates[str(h)] else 'TECHNICAL_SCENARIO_UNCALIBRATED' for h in (1,3,5)},
        'continuation_probability':probability,'probability_calibrated':bool(estimates['1']),'early_move_score':early,
        'move_sustainability_score':sustain,'sustainability_score':sustain,'extended_move_penalty':penalty,'confidence':round(confidence,2),'risk':risk,
        'legacy_score':legacy_score,'technical_strength':technical,'components':components,'weights':weights,'reasons':reasons,'risks':risks,'selection_blocks':sorted(set(blocks)),
        'eligible':not blocks,'neden_bu_sirada':'; '.join(reasons) or 'Teknik güç, risk/getiri ve devam işaretleri birlikte değerlendirildi.',
        'neden_daha_asagida':'; '.join(risks+blocks),'criteria_snapshot':{'flags':flags,'captured_at':cutoff.isoformat(),'mode':'DAILY','model_version':MODEL},'learning_enabled':False}


def build_pool(rows,current,total,score_fn,history=None):
    from top10_aday_secimi import prepare_candidates, valid_candidate
    rows=prepare_candidates(rows,current,keep_invalid=True)
    cutoff=datetime.combine(current.date(),time(18,10),ISTANBUL)
    if current.weekday()>=5 or current.time().replace(tzinfo=None)<time(18,15):raise ValueError('Kapanış analizi yalnız kapanmış işlem seansında')
    from performans_motoru import controlled_context,controlled_score
    from veri_yollari import paths
    from yarin_kalibrasyon import YarinKalibrasyon,score as baseline_score
    from piyasa_baglami import effects
    model=controlled_context(paths(),cutoff,'DAILY')
    calibration=YarinKalibrasyon(paths(),clock=lambda:cutoff).context()
    history=history or [];history={str(h):continuation_pairs(history,cutoff,h) for h in (1,3,5)}
    candidates=[];rejected=[];positive=0;seen=set()
    for row in rows:
        symbol=row.get('sembol')
        if symbol in seen:continue
        seen.add(symbol)
        doc=row.get('teknik_gostergeler')
        closing=doc.get('closing') if isinstance(doc,dict) else None
        if not isinstance(closing,dict):closing={}
        price=number(closing.get('close'));previous=number(closing.get('previous_close'))
        change=(price/previous-1)*100 if price and previous and previous>0 else number(row.get('degisim'),0)
        if change<=0:continue
        positive+=1
        if not valid_candidate(row,current):
            rejected.append({'sembol':symbol,'filters':['INVALID_TOP10_DATA']})
            continue
        raw,quality=closing_inputs(row,cutoff)
        if quality:rejected.append({'sembol':symbol,'filters':quality});continue
        attach_final_decision(raw,cutoff,'DAILY')
        legacy=score_fn(raw);raw.update(baseline_score(raw,legacy,calibration));raw.update(effects(raw,legacy,cutoff,'YARIN'))
        raw['final_puan']=max(0,min(95,raw['final_puan']+raw.get('piyasa_baglami_etkisi',0))) if legacy>=55 else raw['final_puan']
        raw['controlled_shadow']=controlled_score(raw,legacy,cutoff,'DAILY',model)
        forecast=opportunity(raw,cutoff,history,legacy)
        forecast['feature_cutoff']=cutoff.isoformat();forecast['captured_at']=current.isoformat()
        forecast['main_model_score']=raw['final_puan'];forecast['main_model_version']=raw.get('calibration_version')
        forecast['criteria_snapshot']['captured_at']=current.isoformat()
        candidate={**raw,'positive_opportunity':forecast,'criteria_snapshot':forecast['criteria_snapshot'],'model_version':MODEL,'sektor':raw.get('makro_sektor',raw.get('sektor','BILINMIYOR'))}
        candidates.append(candidate)
    candidates.sort(key=lambda r:(-r['positive_opportunity']['future_opportunity_score'],r.get('sembol','')))
    for rank,row in enumerate(candidates,1):row['positive_opportunity'].update(rank=rank,symbol=row['sembol'])
    eligible=[r for r in candidates if r['positive_opportunity']['eligible']]
    for rank,row in enumerate(eligible,1):row['positive_opportunity']['selection_rank']=rank
    baseline=sorted(eligible,key=lambda r:(-r['positive_opportunity']['main_model_score'],r['sembol']))
    for rank,row in enumerate(baseline,1):row['positive_opportunity']['baseline_rank']=rank
    shadow=sorted(eligible,key=lambda r:(-min(100,r['positive_opportunity']['future_opportunity_score']+number((r.get('controlled_shadow') or {}).get('correction'),0)),r['sembol']))
    for rank,row in enumerate(shadow,1):row['positive_opportunity']['shadow_rank']=rank
    return {'model_version':MODEL,'cutoff':cutoff.isoformat(),'positive_count':positive,'analyzed_count':len(candidates),'total_checked':len(seen),'total_universe':total,
            'adaylar':candidates,'eligible_symbols':[r['sembol'] for r in eligible],'shadow_symbols':[r['sembol'] for r in shadow],
            'rejected':rejected,'learning_enabled':False,'ranking_basis':'FUTURE_OPPORTUNITY_NOT_TODAY_RETURN'}


def capture_metrics(pairs,complete=True):
    threshold=float(os.environ.get('POSITIVE_WINNER_RETURN_PCT','2'))
    if not math.isfinite(threshold) or threshold<=0:raise ValueError('POSITIVE_WINNER_RETURN_PCT >0')
    winners=[p for p in pairs if p[1]['getiri_yuzde']>=threshold];result={}
    for size in (10,30,50):
        chosen=[p for p in pairs if 0<number((p[0].get('positive_opportunity') or {}).get('selection_rank'),100000)<=size]
        hits=[p for p in chosen if p[1]['getiri_yuzde']>=threshold];stats=horizon_stats(chosen)
        reliable=complete and stats['sufficient'];wins_reliable=complete and diagnostic_stats(winners)['sufficient']
        result[str(size)]={'selected_count':len(chosen),'winner_count':len(hits),'all_winner_count':len(winners),
            'winner_recall':len(hits)/len(winners) if wins_reliable and winners else None,
            'capture_rate':len(hits)/len(winners) if wins_reliable and winners else None,
            'precision':len(hits)/len(chosen) if reliable and chosen else None,
            'false_positive_rate':(len(chosen)-len(hits))/(len(pairs)-len(winners)) if reliable and diagnostic_stats(pairs)['sufficient'] and len(pairs)>len(winners) else None,
            'average_return':stats['average_return'] if complete else None,'median_return':stats['median_return'] if complete else None,
            'continuation_success_rate':stats['success_rate'] if complete else None,
            'target_hit_rate':stats['target_hit_rate'] if complete else None,'stop_hit_rate':stats['stop_hit_rate'] if complete else None,
            'mfe':stats['mfe'] if complete else None,'mae':stats['mae'] if complete else None,
            'confidence':'YETERLI' if reliable and wins_reliable else 'DUSUK','cohort_complete':complete}
    return {'denominator_scope':'FROZEN_QUALITY_POSITIVE_POOL','winner_threshold_pct':threshold,'top':result}


def horizon_stats(pairs):
    stats=diagnostic_stats(pairs)
    for key,field in (('mfe','mfe_pct'),('mae','mae_pct')):
        selected=[p for p in pairs if number(p[1].get(field)) is not None]
        values=[number(p[1][field]) for p in selected];enough=diagnostic_stats(selected)['sufficient']
        stats[key]={'sample_count':len(values),'mean':sum(values)/len(values) if enough else None,'median':median(values) if enough else None}
    return stats


def continuation_report(records,current,horizon):
    all_pairs=continuation_pairs(records,current,horizon);expected={}
    for r in records:
        at=stamp(r.get('zaman'))
        if r.get('model')=='POSITIVE_CANDIDATE' and at and at<current:expected.setdefault(at.date().isoformat(),set()).add(r['sembol'])
    by_day={d:[p for p in all_pairs if signal_day(p[0])==d] for d in expected}
    complete_days={d for d,p in by_day.items() if len(p)==len(expected[d])}
    pairs=[p for p in all_pairs if signal_day(p[0]) in complete_days]
    rank_buckets={}
    for lo,hi in ((1,5),(6,10),(11,20),(21,30),(31,50)):
        selected=[p for p in pairs if lo<=number((p[0].get('positive_opportunity') or {}).get('selection_rank'),100000)<=hi]
        rank_buckets[f'{lo}-{hi}']=diagnostic_stats(selected)
    return_buckets={};probability_buckets={};risk_buckets={}
    def bucket(values):
        stats=diagnostic_stats([p for p,v in values]);errors=[p[1]['getiri_yuzde']-v for p,v in values]
        return {**stats,'prediction_error':median(errors) if stats['sufficient'] else None,'mean_absolute_error':sum(abs(v) for v in errors)/len(errors) if stats['sufficient'] else None}
    for p in pairs:
        forecast=p[0].get('positive_opportunity') or {};value=number(forecast.get('expected_return_next_session' if horizon==1 else 'expected_return_'+str(horizon)+'d'))
        if value is not None:
            key='NEGATIVE' if value<0 else '0-1' if value<1 else '1-2' if value<2 else '2-3' if value<3 else '3-5' if value<5 else '5+'
            return_buckets.setdefault(key,[]).append((p,value))
        value=number(forecast.get('continuation_probability'))
        if value is not None:
            key='<50' if value<50 else '50-60' if value<60 else '60-70' if value<70 else '70-80' if value<80 else '80-90' if value<90 else '90+'
            probability_buckets.setdefault(key,[]).append((p,value))
        risk_buckets.setdefault(forecast.get('risk','BILINMIYOR'),[]).append(p)
    probabilities={}
    for k,values in probability_buckets.items():
        stats=diagnostic_stats([p for p,v in values]);probabilities[k]={**stats,'predicted_probability_mean':sum(v for p,v in values)/len(values),'actual_continuation_rate':stats['success_rate'],
            'calibration_error':stats['success_rate']-sum(v for p,v in values)/len(values)/100 if stats['sufficient'] else None}
    risks={}
    for key,values in risk_buckets.items():
        stats=diagnostic_stats(values);mae=[number(p[1].get('mae_pct')) for p in values];mae=[v for v in mae if v is not None]
        volatility=[number(p[1].get('mfe_pct'),0)-number(p[1].get('mae_pct'),0) for p in values if number(p[1].get('mae_pct')) is not None and number(p[1].get('mfe_pct')) is not None]
        risks[key]={**stats,'median_mae':median(mae) if stats['sufficient'] and mae else None,'median_range_pct':median(volatility) if stats['sufficient'] and volatility else None,
                    'drawdown_scope':'SIGNAL_MAE_NOT_PORTFOLIO'}
    scopes={field:{key:diagnostic_stats([p for p in pairs if str(p[0].get(field) or 'BILINMIYOR')==key]) for key in distribution(pairs,field)} for field in ('piyasa_rejimi','sektor')}
    last=[];day=current.date()
    while len(last)<60:
        if day.weekday()<5:last.append(day.isoformat())
        day-=timedelta(days=1)
    patterns={}
    for size in (5,20,60):
        selected=[p for p in pairs if signal_day(p[0]) in last[:size]]
        patterns[str(size)]={'stats':diagnostic_stats(selected),'criteria':evidence_report(selected),'combinations':combination_report(selected,combination_catalog(selected),'LIVE')}
    comparisons={}
    for key in ('baseline_rank','selection_rank','shadow_rank'):
        selected=[p for p in pairs if 0<number((p[0].get('positive_opportunity') or {}).get(key),100000)<=10]
        comparisons[key]=diagnostic_stats(selected)
    return {'horizon':horizon,'horizon_unit':'TRADING_SESSIONS','stats':horizon_stats(pairs),'capture':capture_metrics(pairs),
        'daily':{d:{'expected_count':len(expected[d]),'observed_count':len(value),'complete':d in complete_days,
                    'capture':capture_metrics(value,d in complete_days)} for d,value in by_day.items()},
        'continued':diagnostic_stats([p for p in pairs if p[1]['continuation_class']=='CONTINUED']),
        'failed_continuation':diagnostic_stats([p for p in pairs if p[1]['continuation_class']=='FAILED_CONTINUATION']),
        'neutral':diagnostic_stats([p for p in pairs if p[1]['continuation_class']=='NEUTRAL']),
        'rank_buckets':rank_buckets,'expected_return_calibration':{k:bucket(v) for k,v in return_buckets.items()},
        'probability_calibration':probabilities,'risk_calibration':risks,'regime_sector_profiles':scopes,'patterns':patterns,
        'ranking_comparison':comparisons,'automatic_changes':False}


def best_horizons(records,current):
    """Compare the same matured signals, never young 1G vs older 10G cohorts."""
    pairs={str(h):continuation_pairs(records,current,h) for h in POSITIVE_HORIZONS}
    identity=lambda p:(p[0].get('sembol'),p[0].get('zaman'))
    common=set.intersection(*(set(map(identity,value)) for value in pairs.values()))
    expected={}
    for r in records:
        at=stamp(r.get('zaman'))
        if r.get('model')=='POSITIVE_CANDIDATE' and at and at<current:expected.setdefault(signal_day(r),set()).add((r.get('sembol'),r.get('zaman')))
    complete={day for day,ids in expected.items() if ids<=common}
    pairs={h:[p for p in values if identity(p) in common and signal_day(p[0]) in complete] for h,values in pairs.items()}
    minimum,days,_=combination_limits()
    def compare(predicate):
        stats={h:diagnostic_stats([p for p in values if predicate(p[2])],minimum,days) for h,values in pairs.items()}
        enough=all(s['sufficient'] for s in stats.values())
        if not enough:return {'best_horizon':None,'sufficient':False,'conclusive':False,'horizons':stats}
        best=max(stats,key=lambda h:(stats[h]['success_rate'],stats[h]['median_return'],-int(h)))
        conclusive=all(stats[best]['success_interval'][0]>s['success_interval'][1] for h,s in stats.items() if h!=best)
        return {'best_horizon':int(best),'sufficient':True,'conclusive':conclusive,'horizons':stats,
                'interpretation':'CONFIRMED_DIFFERENCE' if conclusive else 'OBSERVED_BEST_DIFFERENCE_UNCONFIRMED'}
    base=pairs['1'];criteria={key:compare(lambda flags,k=key:flags.get(k) is True) for key in (base[0][2] if base else [])}
    combos={'+'.join(keys):compare(lambda flags,ks=keys:all(flags.get(k.lstrip('!')) is (not k.startswith('!')) for k in ks)) for keys in combination_catalog(base)}
    return {'population':'SAME_FULLY_MATURED_DAILY_COHORTS','horizon_unit':'TRADING_SESSIONS','sample_count':len(base),
            'minimum_samples':minimum,'minimum_days':days,'criteria':criteria,'combinations':combos,'automatic_application':False}


def publish_performance(location,records,current):
    eligible=[r for r in records if r.get('model')=='POSITIVE_CANDIDATE' and stamp(r.get('zaman')) and stamp(r['zaman'])<=current]
    if not eligible:return None
    path=location.public/'pozitif_hisseler_performansi.json'
    known=[]
    for r in eligible:
        outcomes={str(h):r.get('sonuc_'+str(h)+'g') for h in POSITIVE_HORIZONS if stamp((r.get('sonuc_'+str(h)+'g') or {}).get('observed_at')) and stamp(r['sonuc_'+str(h)+'g']['observed_at'])<=current}
        known.append((r.get('kayit_id'),r.get('positive_opportunity'),outcomes))
    fingerprint=hashlib.sha256(json.dumps([MODEL,'PERFORMANCE_V2',known,current.date().isoformat(),evidence_limits(),combination_limits(),os.environ.get('POSITIVE_WINNER_RETURN_PCT','2')],sort_keys=True,default=str).encode()).hexdigest()
    previous=load(path,{})
    if previous.get('fingerprint')==fingerprint:return previous
    report={str(h):continuation_report(eligible,current,h) for h in POSITIVE_HORIZONS}
    latest=max(signal_day(r) for r in eligible);snapshot=load(location.archives/(latest+'.json'),{})
    pool=snapshot.get('pozitif_havuz') or {};missed=[]
    complete_days={d for d,v in report['1']['daily'].items() if v['complete']}
    threshold=float(os.environ.get('POSITIVE_WINNER_RETURN_PCT','2'))
    for r,o,f in continuation_pairs(eligible,current,1):
        forecast=r.get('positive_opportunity') or {};rank=number(forecast.get('selection_rank'),100000)
        if signal_day(r) not in complete_days or o['getiri_yuzde']<threshold or rank<=10:continue
        filters=forecast.get('selection_blocks') or []
        missed.append({'id':r['kayit_id']+'|MISSED_WINNER','symbol':r['sembol'],'signal_time':r['zaman'],'signal_type':'POSITIVE_CANDIDATE',
            'decision':r.get('recorded_decision'),'score':forecast.get('future_opportunity_score'),'confidence':forecast.get('confidence'),
            'target':r.get('hedef'),'stop':r.get('stop'),'actual_result':o,'failure_type':'MISSED_WINNER','failure_types':['MISSED_WINNER'],
            'main_reason':'; '.join(filters) or 'Gelecek fırsat sıralamasında ilk 10 dışında kaldı',
            'missed_risk':forecast.get('risks',[]),'misleading_criteria':[],
            'market_regime':r.get('piyasa_rejimi'),'sector':r.get('sektor'),'news_context':{},'model_version':forecast.get('model_version',MODEL),
            'source':'LIVE','mode':'POSITIVE_DAILY','filters':filters,'extended_move_penalty':forecast.get('extended_move_penalty'),
            'confidence_low':number(forecast.get('confidence'),0)<50,'missing_confirmations':forecast.get('selection_blocks',[]),
            'analysis_policy':'OBSERVED_RANK_OR_FILTER_NOT_CAUSAL'})
    if missed:
        path=location.runtime/'karar_hata_gunlugu.json'
        with locked(path):
            doc=load(path,{'modes':{}});errors=doc.setdefault('modes',{}).setdefault('POSITIVE_DAILY',{})
            errors.update({e['id']:e for e in missed});atomic_json(path,doc)
    result={'model_version':MODEL,'updated_at':current.isoformat(),'analysis_date':latest,'positive_count':pool.get('positive_count'),
        'analyzed_count':pool.get('analyzed_count'), 'quality_rejected_count':len(pool.get('rejected',[])),
        'missed_winner_count':len(missed),'most_common_failure':max((f for e in missed for f in e['filters']),key=lambda key:sum(key in e['filters'] for e in missed),default=None),
        'average_analyzed_positive_count':sum(len({r['sembol'] for r in eligible if signal_day(r)==d}) for d in {signal_day(r) for r in eligible})/len({signal_day(r) for r in eligible}),
        'fingerprint':fingerprint,'horizons':report,'best_horizons':best_horizons(eligible,current),
        'horizon_unit':'TRADING_SESSIONS','learning_enabled':False,'automatic_application':False,'measurement_population':'QUALITY_POSITIVE_CLOSING_POOL'}
    path=location.public/'pozitif_hisseler_performansi.json'
    with locked(path):atomic_json(path,result)
    return result
