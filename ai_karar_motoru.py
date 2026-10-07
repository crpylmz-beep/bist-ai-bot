"""Shared explainable context; never replaces TOP10 selection or frozen predictions."""
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import hashlib
import json
import math
import os
import copy

from haber_etki_motoru import haber_etki_sonumleme, fiyat_teyidi_hesapla
from kullanici_kayitlari import atomic_json, symbol, RecordError
from veri_yollari import paths, data_file

ISTANBUL = ZoneInfo('Europe/Istanbul')
HORIZONS = (1, 3, 5, 10, 20, 60)
DEFAULT_WEIGHTS = {'teknik': .70, 'haber': .12, 'makro': .06, 'sektor': .04,
                   'fiyat_teyidi': .03, 'gecmis_basari': .03, 'piyasa_rejimi': .02}
LIMITS = {'teknik': (.55, .80), 'haber': (.05, .18), 'makro': (0, .10),
          'sektor': (0, .08), 'fiyat_teyidi': (0, .06),
          'gecmis_basari': (0, .05), 'piyasa_rejimi': (0, .05)}
THRESHOLDS = {'GUCLU_AL': 82, 'AL': 70, 'SAT': 35, 'GUCLU_SAT': 20}


def number(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def stamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (value.replace(tzinfo=ISTANBUL) if value.tzinfo is None else value).astimezone(ISTANBUL)
    except (ValueError, TypeError):
        return None


def minutes(value, current):
    parsed = stamp(value)
    return max(0, (current-parsed).total_seconds()/60) if parsed and parsed <= current else None


def load(path, default):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Path(str(path)+'.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def learning_history_lock(function):
    """Also used by existing GUN_ICI writers: one lock for the shared history."""
    @wraps(function)
    def call(*args, **kwargs):
        target=data_file('ai_ogrenme_gecmisi.json')
        with locked(target):
            if Path(target).exists():
                existing=load(target,{})
                if not isinstance(existing,dict) or not isinstance(existing.get('kayitlar'),list):
                    raise ValueError('Öğrenme geçmişi geçersiz; dosya korunuyor')
            return function(*args, **kwargs)
    return call


def normalize_weights(values, bounds=None):
    """Project centrally configured weights onto a bounded unit simplex."""
    bounds = bounds or LIMITS
    if set(values) != set(DEFAULT_WEIGHTS):
        raise ValueError('Ağırlık grupları eksik veya bilinmiyor')
    raw = {key: number(value) for key, value in values.items()}
    if any(value is None or value < 0 for value in raw.values()) or not sum(raw.values()):
        raise ValueError('Ağırlıklar pozitif ve sonlu olmalı')
    total = sum(raw.values()); raw = {k: v/total for k, v in raw.items()}
    if sum(b[0] for b in bounds.values()) > 1+1e-9 or sum(b[1] for b in bounds.values()) < 1-1e-9:
        raise ValueError('Ağırlık sınırları normalize edilemiyor')
    low, high = -1., 1.
    for _ in range(80):
        shift = (low+high)/2
        projected = {k: clamp(raw[k]+shift, *bounds[k]) for k in raw}
        if sum(projected.values()) < 1: low = shift
        else: high = shift
    return {k: round(v, 10) for k, v in projected.items()}


def history_context(history, row, regime, current):
    eligible = []
    for record in history:
        if not isinstance(record,dict):continue
        recorded=stamp(record.get('zaman') or record.get('sinyal_zamani'))
        if recorded and recorded>current:continue
        if record.get('egitim_durumu') == 'REFERANS' or record.get('karar') not in ('AL','SAT','GUCLU_AL','GUCLU_SAT'):
            continue
        if record.get('sembol') != row.get('sembol') and (not row.get('makro_sektor') or record.get('sektor') != row['makro_sektor']):
            continue
        if record.get('model') == 'ORTAK_AI' and record.get('piyasa_rejimi') != regime:
            continue
        result = record.get('sonuc_5g')
        if isinstance(result, dict):
            if result.get('degerlendirme_tamamlandi') is False or result.get('durum')=='VERI_YETERSIZ':continue
            available = stamp(result.get('observed_at') or result.get('tarih'))
            if not available or available > current: continue
            change = number(result.get('getiri_yuzde'))
            if change is None: continue
            if result.get('durum') in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP'):
                eligible.append(result['durum']=='BASARILI')
            else:eligible.append((change > 0) if record['karar'] in ('AL','GUCLU_AL') else (change < 0))
        elif record.get('sonuc') in ('BASARILI','BASARISIZ'):
            available = stamp(record.get('sonuc_zaman'))
            if available and available <= current: eligible.append(record['sonuc']=='BASARILI')
    count = len(eligible)
    # No adaptive influence from a few lucky outcomes or reference rows.
    rate = sum(eligible)/count if count else None
    return ((rate-.5)*100 if count >= 30 else 0), {'ornek': count, 'basari_orani': rate, 'minimum': 30}


def evaluate(row, news=None, macro=None, history=None, market=None, weights=None, current=None, baselines=None, thresholds=None):
    current = current or datetime.now(ISTANBUL)
    current = current.astimezone(ISTANBUL)
    row=copy.deepcopy(row)
    quote_at=stamp(row.get('canli_guncelleme') or row.get('updated_at'))
    if quote_at and quote_at>current:
        row={'sembol':row['sembol'],'updated_at':quote_at.isoformat()}
    weights = normalize_weights(weights or DEFAULT_WEIGHTS)
    thresholds = thresholds or THRESHOLDS
    model_at=stamp(row.get('model_asof'))
    if model_at and model_at>current:weights=normalize_weights(DEFAULT_WEIGHTS);thresholds=THRESHOLDS
    if set(thresholds)!=set(THRESHOLDS) or any(number(v) is None for v in thresholds.values()):
        raise ValueError('Karar eşikleri geçersiz')
    if not 10<=thresholds['GUCLU_SAT']<thresholds['SAT']<50<thresholds['AL']<thresholds['GUCLU_AL']<=95:
        raise ValueError('Karar eşikleri güvenli sırada olmalı')
    news, macro, market = news or [], macro or {}, market or {}
    macro_at=stamp(macro.get('updated_at') or macro.get('guncelleme'))
    if macro_at and macro_at>current:macro={}
    risks, positive, negative = [], [], []
    stock = symbol(row['sembol'])
    technical_time = row.get('canli_guncelleme') or row.get('updated_at')
    technical_age = minutes(technical_time, current)
    technical = number(row.get('teknik_puan'))
    if technical is None and number(row.get('al_puani')) is not None:
        technical = clamp(50+(number(row['al_puani'], 0)-number(row.get('sat_puani'), 0))/2, 0, 100)
    if technical is None and number(row.get('gun_ici_al_puani')) is not None:
        technical = clamp(50+(number(row['gun_ici_al_puani'],0)-number(row.get('gun_ici_sat_puani'),0))/2,0,100)
    indicators = {k: row.get(k) for k in ('trend','rsi','macd','signal','hist','hacim_orani',
        'vwap20_durum','obv_durum','boll_durum','karar_rr','risk_getiri','destek','direnc',
        'gun_ici_sinyal_durumu','sma20','sma50','ema9_5','ema21_5','atr14','atr14_5',
        'yarin_kirilim','gun_ici_hacimli_kirilim','hist_onceki','rsi_onceki','momentum15')}
    if indicators['trend'] is None and number(row.get('sma20')) is not None and number(row.get('sma50')) is not None:
        indicators['trend']='YUKARI' if float(row['sma20'])>float(row['sma50']) else 'ASAGI' if float(row['sma20'])<float(row['sma50']) else 'YATAY'
    if technical is None:
        technical = 50; risks.append('TEKNIK_VERI_EKSIK')
    if technical_age is None: risks.append('TEKNIK_ZAMANI_BILINMIYOR')
    elif technical_age > 20: risks.append('TEKNIK_VERI_ESKI')
    elif technical_age > 10: risks.append('TEKNIK_VERI_GECIKMIS')
    if number(row.get('rsi'),50) > 75: risks.append('RSI_ASIRI_ALIM')
    rr = number(row.get('karar_rr'), number(row.get('risk_getiri')))
    if rr is not None and rr < 1: risks.append('DUSUK_RISK_GETIRI')
    regime_value = number(row.get('piyasa_rejimi'))
    if regime_value is None: regime_value = number(market.get('degisim'))
    regime = 'POZITIF' if regime_value is not None and regime_value > .5 else 'NEGATIF' if regime_value is not None and regime_value < -.5 else 'YATAY' if regime_value is not None else 'BILINMIYOR'
    rich_market=market.get('model')=='BIST_CONTEXT_V1'
    market_context={}
    if rich_market:
        from piyasa_baglami import usable_context,stock_context
        market_context=stock_context(usable_context(market,current),row)
        regime=market_context['piyasa_rejimi'] if not market_context['stale'] and market_context['rejim_confidence']>=50 else 'BELIRSIZ'
        regime_value=number(market_context.get('rejim_score'))/20 if number(market_context.get('rejim_score')) is not None and not market_context['stale'] and regime!='BELIRSIZ' and market_context['rejim_confidence']>=50 else None
        if market_context['stale']:risks.append('PIYASA_BAGLAMI_ESKI_VEYA_YETERSIZ')
    if regime_value is None: risks.append('PIYASA_REJIMI_EKSIK')
    baselines = baselines if baselines is not None else {}
    details, ids, seen = [], [], set()
    for event in news:
        if not isinstance(event,dict):continue
        if event.get('sembol') != stock: continue
        event_id = str(event.get('canonical_id') or event.get('id') or hashlib.sha256(
            (stock+str(event.get('baslik'))+str(event.get('tarih'))).encode()).hexdigest())
        if event_id in seen: continue
        analysis = event.get('analiz', event)
        knowledge=[stamp(event.get(k)) for k in ('ilk_gorulme','observed_at','updated_at')]
        knowledge.extend(stamp(analysis.get(k)) for k in ('updated_at','analyzed_at'))
        if any(at and at>current for at in knowledge):continue
        variants = event.get('variants') or [{}]
        published=event.get('published_at') or variants[0].get('event_time') or event.get('ilk_gorulme') or event.get('tarih')
        if stamp(published) and stamp(published)>current:continue
        age = minutes(published, current)
        if age is None:
            risks.append('HABER_ZAMANI_BILINMIYOR'); continue
        seen.add(event_id)
        price = number(row.get('fiyat'),0)
        reference = number(event.get('reference_price'), number(analysis.get('ilk_fiyat')))
        key = stock+':'+event_id
        baseline = baselines.get(key)
        if reference is None and baseline and stamp(baseline['timestamp']) < current:
            reference = baseline['price']
            reference_type='ILK_AI_GOZLEMI'
        else:reference_type='HABER_FIYATI' if reference else 'BILINMIYOR'
        if key not in baselines and price > 0:
            baselines[key] = {'price': price, 'timestamp': current.isoformat()}
        change = (price/reference-1)*100 if reference and reference > 0 and price > 0 else None
        score = haber_etki_sonumleme(clamp(number(analysis.get('etki_puani'),0),-10,10),age)
        confirmed = change is not None and change > 0 and number(row.get('hacim_orani'),0) >= 100
        confirmation = fiyat_teyidi_hesapla(score,change or 0,number(row.get('hacim_orani'),100),
            True if row.get('vwap20_durum')=='USTUNDE' else False if row.get('vwap20_durum')=='ALTINDA' else None,
            True if row.get('obv_durum') in ('POZITIF','YUKSELEN') else False if row.get('obv_durum') in ('NEGATIF','DUSEN') else None) if change is not None else 0
        if score > 0 and not confirmed:
            confirmation = min(confirmation, clamp((change or 0)/2,-4,0))
        factor = 1 if score <= 0 or confirmed else .35
        if score > 0 and not confirmed: risks.append('POZITIF_HABER_FIYAT_HACIM_TEYIDI_YOK')
        ids.append(event_id)
        details.append({'canonical_id':event_id,'baslik':event.get('ana_baslik') or event.get('baslik') or analysis.get('baslik'),
            'kaynak_etiketi':event.get('kaynak_etiketi') or analysis.get('kaynak'),
            'nedenler':analysis.get('nedenler',[]),'kaynaklar':event.get('kaynaklar',[]),'yas_dakika':round(age,2),
            'ham_etki':number(analysis.get('etki_puani'),0),'sonumlu_etki':score,'teyit_edildi':confirmed,
            'referans_fiyat':reference,'referans_turu':reference_type,'haber_sonrasi_degisim':change,'teyit_katsayisi':factor,
            'etki':score*clamp(number(analysis.get('guven'),0),0,100)/100*factor,'fiyat_teyidi':confirmation})
    details = sorted(details,key=lambda r:r['yas_dakika'])[:5]
    news_value = clamp(sum(d['etki'] for d in details),-10,10)
    if news_value < 0:risks.append('NEGATIF_HABER_ETKISI')
    price_value = clamp(sum(d['fiyat_teyidi'] for d in details),-4,4)
    if not details: risks.append('HABER_VERISI_YOK')
    macro_age = minutes(macro.get('updated_at') or macro.get('guncelleme'),current)
    macro_value = number(macro.get('makro_puani'),0)
    sector_value = number(macro.get('sektor_puani'),0)
    macro_id, sector_id = macro.get('event_id'), macro.get('sektor_event_id')
    # Legacy macro writers mirror the same event into the sector field.
    overlap = (macro_id and macro_id == sector_id) or (not sector_id and macro_value == sector_value)
    if overlap: sector_value = 0
    if macro_id in seen: macro_value = 0; risks.append('HABER_MAKRO_ORTAK_OLAY_TEK_ETKI')
    if sector_id in seen: sector_value = 0
    if not macro: risks.append('MAKRO_VERISI_YOK')
    if macro_age is None and (macro_value or sector_value):
        macro_value = sector_value = 0; risks.append('MAKRO_ZAMANI_BILINMIYOR')
        macro={};macro_id=sector_id=None
    elif macro_age is not None:
        decay = .5**(macro_age/1440)
        macro_value *= decay; sector_value *= decay
        if macro_age > 1440: risks.append('MAKRO_VERISI_ESKI')
    if macro_value < 0:risks.append('NEGATIF_MAKRO_ETKISI')
    if sector_value < 0:risks.append('NEGATIF_SEKTOR_ETKISI')
    past, history_info = history_context(history or [],row,regime,current)
    if history_info['ornek'] < 30: risks.append('BENZER_SINYAL_ORNEGI_YETERSIZ')
    values = {'teknik':technical-50,'haber':news_value*5,'makro':clamp(macro_value,-10,10)*5,
              'sektor':clamp(sector_value,-10,10)*5,'fiyat_teyidi':price_value*12.5,
              'gecmis_basari':past,'piyasa_rejimi':clamp(regime_value or 0,-5,5)*10}
    contributions = {k: round(values[k]*weights[k],4) for k in weights}
    baseline_score=round(clamp(50+sum(v for k,v in contributions.items() if k!='piyasa_rejimi'),0,100),1)
    market_effects={}
    if rich_market:
        from piyasa_baglami import effects
        safety_row=dict(row,piyasa_baglami=market_context,haber_puani=news_value,makro_puani=macro_value,sektor_puani=sector_value)
        market_effects=effects(safety_row,technical,current)
        contributions.update(piyasa_rejimi=market_effects['piyasa_duzeltmesi'],
            breadth=market_effects['breadth_duzeltmesi'],sektor_relatif_guc=market_effects['sektor_duzeltmesi'])
        positive.extend(market_effects['piyasa_reasons_positive'])
        negative.extend(market_effects['piyasa_reasons_negative'])
    score = round(clamp(50+sum(contributions.values()),0,100),1)
    group_labels={'teknik':'Teknik','haber':'Haber/KAP','makro':'Makro','sektor':'Sektör','fiyat_teyidi':'Fiyat teyidi',
                  'gecmis_basari':'Geçmiş başarı','piyasa_rejimi':'Piyasa rejimi','breadth':'Piyasa genişliği','sektor_relatif_guc':'Sektör relatif gücü'}
    for group, amount in sorted(contributions.items(),key=lambda p:abs(p[1]),reverse=True):
        label=group_labels.get(group,group)
        if amount > .01: positive.append(f'{label}: +{amount:.2f} puan')
        elif amount < -.01: negative.append(f'{label}: {amount:.2f} puan')
    # Existing indicators explain the technical group; they are not rescored a second time.
    evidence = list(row.get('karar_nedenleri') or row.get('nedenler') or [])
    coverage = sum(number(row.get(k)) is not None for k in ('rsi','macd','hacim_orani','destek','direnc'))/5
    confidence = 30+coverage*30+(10 if details else 0)+(10 if macro else 0)+(10 if regime_value is not None else 0)+(10 if history_info['ornek']>=30 else 0)
    if 'TEKNIK_VERI_EKSIK' in risks: confidence = min(confidence,20)
    if technical_age is None: confidence *= .5
    elif technical_age > 20: confidence *= .35
    elif technical_age > 10: confidence *= .7
    confidence = round(clamp(confidence,0,100),1)
    confidence=clamp(confidence+market_effects.get('piyasa_confidence_duzeltmesi',0),0,100)
    if confidence < 50: risks.append('DUSUK_GUVEN')
    decision = 'GUCLU_AL' if score >= thresholds['GUCLU_AL'] else 'AL' if score >= thresholds['AL'] else 'GUCLU_SAT' if score <= thresholds['GUCLU_SAT'] else 'SAT' if score <= thresholds['SAT'] else 'IZLE'
    if rich_market and ((decision in ('AL','GUCLU_AL') and baseline_score<thresholds['AL']) or (decision in ('SAT','GUCLU_SAT') and baseline_score>thresholds['SAT'])):
        decision='IZLE'
    if decision in ('AL','GUCLU_AL') and (confidence < 50 or news_value <= -5 or macro_value <= -5): decision = 'IZLE'
    from teknik_gostergeler import reasons,view,features
    technical_positive,technical_negative=reasons(row,current)
    positive.extend(technical_positive);negative.extend(technical_negative)
    standard=view(row,current)
    if standard.get('stale'):
        risks.append('STANDART_TEKNIK_VERI_ESKI')
        confidence=min(confidence,49)
        if decision in ('AL','GUCLU_AL'):decision='IZLE'
    result = {'sembol':stock,'model':'ORTAK_AI','ai_score':score,'karar':decision,'confidence':confidence,
        'kisa_gerekce':'; '.join((positive+negative)[:3]) or 'Yeterli doğrulanmış katkı yok.',
        'reasons_positive':positive,'reasons_negative':negative,'risk_flags':list(dict.fromkeys(risks)),
        'katkilar':contributions,'girdiler':indicators,'teknik_kriterler':evidence,
        'teknik_gostergeler':standard,'standart_teknik_kriterler':features(dict(row,zaman=current.isoformat())),
        'teknik_katkilar':row.get('teknik_katkilar'),'teknik_ana_skor_etkisi':0,
        'indikator_katkilari':{k:{'deger':v,'grup':'teknik','ayri_ek_puan':0} for k,v in indicators.items()},
        'haber_katkilari':details,'canonical_ids':sorted(d['canonical_id'] for d in details),
        'makro_event_id':macro_id,'sektor_event_id':sector_id,'ayni_makro_sektor_olayi':bool(overlap),
        'gecmis_benzer_sinyal':history_info,'piyasa_rejimi':regime,'sektor':market_context.get('sektor') if rich_market else row.get('makro_sektor') or macro.get('sektor',''),
        'piyasa_rejimi_kaynagi':'ORTAK_PIYASA_BAGLAMI' if rich_market else 'HISSE_GIRDISI' if number(row.get('piyasa_rejimi')) is not None else 'BIST100_GUNLUK_DEGISIM_PROXY',
        'piyasa_baglami':market_context,'piyasa_baglami_katkilari':market_effects,
        'baglam_oncesi_ai_score':baseline_score if rich_market else score,
        'timestamp':current.isoformat(timespec='seconds'),'updated_at':current.isoformat(timespec='seconds'),
        'veri_tazeligi':{'teknik_timestamp':technical_time,'teknik_yas_dakika':technical_age,'makro_yas_dakika':macro_age,
            'haber_yaslari_dakika':[d['yas_dakika'] for d in details]},
        'agirliklar':weights,'seviye_politikasi':'MEVCUT_SEVIYELER_KORUNUR'}
    result['karar_esikleri']=dict(thresholds)
    result['nihai_karar']=final_decision(row,result,current)
    # IZLE remains the legacy API alias; the new contract has exactly five decisions.
    result['karar']='IZLE' if result['nihai_karar']['karar']=='BEKLE' else result['nihai_karar']['karar']
    result['confidence']=result['nihai_karar']['confidence']
    return result


FINAL_MODEL='FINAL_DECISION_V1'
FINAL_LABELS={'trend':'Trend','momentum':'Momentum','volume':'Hacim','price':'Fiyat konumu',
              'obv':'OBV','bollinger':'Bollinger','risk':'Risk/getiri','market':'Piyasa/sektör','news':'Haber/KAP'}


def final_decision(row,result,current):
    """One decision policy on the existing score; evidence is never added as extra points."""
    doc=result.get('teknik_gostergeler') or {};intraday=doc.get('mode')=='INTRADAY' or row.get('karar_zaman_dilimi')=='INTRADAY'
    def n(*names):return next((number(row[k]) for k in names if number(row.get(k)) is not None),None)
    def side(value,tolerance=0):return None if value is None else 1 if value>tolerance else -1 if value<-tolerance else 0
    def difference(a,b):return side(a-b) if a is not None and b is not None else None
    price=n('fiyat');stop=n('gun_ici_stop','stop') if intraday else n('karar_stop','yarin_stop','stop')
    support=n('destek','gun_dusuk');rr=n('gun_ici_rr','risk_getiri') if intraday else n('karar_rr','risk_getiri')
    rsi=n('rsi5','rsi') if intraday else n('rsi')
    change=n('degisim','acilisa_gore_degisim')
    trend=difference(n('ema9_5','sma20') if intraday else n('sma20'),n('ema21_5','sma50') if intraday else n('sma50'))
    if trend is None and row.get('trend') in ('YUKARI','ASAGI'):trend=1 if row['trend']=='YUKARI' else -1
    line=n('macd5','macd') if intraday else n('macd');signal=n('signal5','signal') if intraday else n('signal')
    macd_side=difference(line,signal)
    mom=doc.get('momentum',{});obv=doc.get('obv',{});bb=doc.get('bollinger',{});vw=doc.get('vwap',{})
    valid=lambda g:g.get('status')=='OK' and not doc.get('stale') and number(g.get('confidence'),0)>=50
    momentum=side(number(mom.get('short_pct')),.05) if valid(mom) else side(n('momentum15'),.05) if intraday and not doc else macd_side if not doc else None
    if macd_side is not None and momentum is not None and macd_side*momentum<0:momentum=0
    position=1 if vw.get('position')=='VWAP_USTU' else -1 if vw.get('position')=='VWAP_ALTI' else 0 if valid(vw) else None
    if not valid(vw):position=difference(price,n('sma20','destek')) if not intraday else None
    if support is not None and price is not None and price<support:position=-1
    obv_side={'OBV_YUKSELEN':1,'OBV_DUSEN':-1,'OBV_YATAY':0}.get(obv.get('trend')) if valid(obv) else {'YUKSELEN':1,'DUSEN':-1,'YATAY':0}.get(row.get('obv_durum')) if not doc else None
    if valid(obv) and obv.get('divergence')=='NEGATIF_UYUMSUZLUK':obv_side=-1
    boll=1 if valid(bb) and bb.get('squeeze_volume_momentum_break') else -1 if valid(bb) and bb.get('lower_break') else 0 if valid(bb) else None
    volume=n('hacim3_orani','hacim_orani') if intraday else n('hacim_orani')
    volume_side=momentum if volume is not None and volume>=100 and momentum in (-1,1) else 0 if volume is not None else None
    ctx=result.get('piyasa_baglami') or row.get('piyasa_baglami') or {}
    context_at=stamp(ctx.get('updated_at'))
    if context_at and context_at>current:ctx={}
    market_side=side(number(ctx.get('rejim_score'))) if ctx and not ctx.get('stale') else {'POZITIF':1,'NEGATIF':-1,'YATAY':0}.get(result.get('piyasa_rejimi'))
    breadth=number(ctx.get('breadth_score'));sector=number(ctx.get('sektor_rs_score'))
    if sector is not None and market_side in (None,0):market_side=side(sector)
    news_value=sum(number(e.get('etki'),0) for e in result.get('haber_katkilari',[]))
    news_raw=n('haber_puani');news_direction=side(news_value) if result.get('haber_katkilari') else side(news_raw)
    flags={'trend':trend,'momentum':momentum,'volume':volume_side,'price':position,'obv':obv_side,'bollinger':boll,
           'risk':1 if rr is not None and rr>=(1.4 if intraday else 1.5) else -1 if rr is not None else None,
           'market':market_side,'news':news_direction}
    positive=[FINAL_LABELS[k]+' teyidi olumlu' for k,v in flags.items() if v==1]
    negative=[FINAL_LABELS[k]+' teyidi olumsuz' for k,v in flags.items() if v==-1]
    technical=number(result.get('girdiler',{}).get('teknik_puan'),n('teknik_puan'))
    if technical is None:
        al=n('gun_ici_al_puani') if intraday else n('al_puani');sat=n('gun_ici_sat_puani') if intraday else n('sat_puani')
        technical=clamp(50+((al or 0)-(sat or 0))/2,0,100) if al is not None else None
    confidence=number(result.get('confidence'),0);blocked=[]
    labels={'SERT_DUSUS':'Günlük düşüş %7 veya daha fazla','ASIRI_YUKSELIS':'Aşırı yükseliş sonrası takip riski',
            'KRITIK_HABER':'Kritik negatif haber','STOP':'Fiyat stop seviyesinde veya altında',
            'RISK_GETIRI':'Risk/getiri yetersiz veya doğrulanamadı','ESKI_VERI':'Teknik veri eski veya zamanı doğrulanamadı',
            'VERI_EKSIK':'Teknik veri yetersiz','MAKRO_NEGATIF':'Makro koşullar belirgin negatif','KARISIK':'Teknik teyitler çelişiyor',
            'DUSUK_GUVEN':'Veri güveni karar için yetersiz','TEYIT_YETERSIZ':'Yön için yeterli bağımsız teyit yok','ASIRI_ALIM':'Aşırı alımda yeni alış teyidi yetersiz'}
    if change is not None and change<=-7:blocked.append('SERT_DUSUS')
    if change is not None and change>(5 if intraday else 4):blocked.append('ASIRI_YUKSELIS')
    critical=any(number(e.get('ham_etki'),0)<=-5 for e in result.get('haber_katkilari',[])) or (news_raw is not None and news_raw<=-5)
    if critical:blocked.append('KRITIK_HABER');confidence=min(confidence,49)
    if price is not None and stop is not None and price<=stop:blocked.append('STOP')
    atr=n('atr14_5','atr14') if intraday else n('atr14')
    if atr is not None and atr<0:blocked.append('VERI_EKSIK');confidence=min(confidence,20)
    if flags['risk']!=1:blocked.append('RISK_GETIRI')
    freshness=result.get('veri_tazeligi',{}).get('teknik_yas_dakika')
    if freshness is None or freshness>20 or doc.get('stale'):blocked.append('ESKI_VERI');confidence=min(confidence,35)
    if technical is None or price is None or price<=0 or row.get('_durum'):blocked.append('VERI_EKSIK');confidence=min(confidence,20)
    if number(result.get('katkilar',{}).get('makro'),0)<=-1.5:blocked.append('MAKRO_NEGATIF')
    if rsi is not None and rsi>=75:blocked.append('ASIRI_ALIM')
    tech_keys=('trend','momentum','volume','price','obv','bollinger')
    ups=sum(flags[k]==1 for k in tech_keys);downs=sum(flags[k]==-1 for k in tech_keys)
    conflict=(ups>=2 and downs>=2) or (macd_side==-1 and position==1 and obv_side==-1)
    if conflict:blocked.append('KARISIK');confidence=min(confidence,49)
    if confidence<50:blocked.append('DUSUK_GUVEN')
    technical_floor=technical if technical is not None else 0
    score=number(result.get('ai_score'),50);thresholds=result.get('karar_esikleri') or THRESHOLDS
    weak_market=ctx.get('piyasa_rejimi')=='GUCLU_DUSUS' and breadth is not None and breadth<-20
    buy_min=4 if intraday else 3;strong_min=6 if weak_market else 5
    buy_ok=not blocked and ups>=buy_min and (trend==1 or momentum==1) and technical_floor>=65
    sell_ok=confidence>=50 and not conflict and 'ESKI_VERI' not in blocked and 'VERI_EKSIK' not in blocked and downs>=2 and (trend==-1 or momentum==-1)
    decision='BEKLE'
    context_points=sum(number(result.get('katkilar',{}).get(k),0) for k in ('makro','sektor','piyasa_rejimi','breadth','sektor_relatif_guc'))
    core_score=score-context_points
    if buy_ok and score>=thresholds['AL'] and core_score>=thresholds['AL']:
        decision='GUCLU_AL' if score>=thresholds['GUCLU_AL'] and core_score>=thresholds['GUCLU_AL'] and ups>=strong_min and trend==momentum==volume_side==1 and technical_floor>=85 else 'AL'
    elif sell_ok and ((score<=thresholds['SAT'] and core_score<=thresholds['SAT']) or 'STOP' in blocked or (critical and downs>=3)):
        decision='GUCLU_SAT' if score<=thresholds['GUCLU_SAT'] and downs>=4 and technical_floor<=25 else 'SAT'
    if decision=='BEKLE' and not blocked:blocked.append('TEYIT_YETERSIZ')
    if rsi is not None and rsi<30:
        rebound=(n('dipten_toparlanma') or 0)>0 and mom.get('last_candle')=='POZITIF' and volume_side==1 and n('hist_onceki') is not None and n('hist','hist5') is not None and n('hist','hist5')>n('hist_onceki') and n('rsi_onceki') is not None and rsi>n('rsi_onceki')
        positive.append('Aşırı satım sonrası tepki teyitli' if rebound else 'Aşırı satım tek başına alış teyidi değildir')
        if not rebound and decision in ('AL','GUCLU_AL'):decision='BEKLE';blocked.append('TEYIT_YETERSIZ')
    negative.extend(labels[k] for k in blocked)
    if weak_market:negative.append('Piyasa güçlü düşüşte ve breadth negatif; güçlü alış teyidi artırıldı')
    negative.extend(result.get('reasons_negative') or [])
    quality_labels={'HABER_VERISI_YOK':'Haber/KAP verisi yok; güven katkısı sınırlı',
                    'MAKRO_VERISI_YOK':'Makro verisi yok; güven katkısı sınırlı',
                    'PIYASA_REJIMI_EKSIK':'Piyasa rejimi doğrulanamadı',
                    'BENZER_SINYAL_ORNEGI_YETERSIZ':'Benzer geçmiş sinyal sayısı yetersiz',
                    'TEKNIK_VERI_GECIKMIS':'Teknik veri gecikmiş; güven düşürüldü'}
    quality=[quality_labels[k] for k in result.get('risk_flags',[]) if k in quality_labels]
    negative.extend(quality)
    positive.extend(result.get('reasons_positive') or [])
    matched=ups if decision in ('AL','GUCLU_AL') else downs if decision in ('SAT','GUCLU_SAT') else max(ups,downs)
    reasons=list(dict.fromkeys(positive));risks=list(dict.fromkeys(negative))
    if flags['risk']==1 and atr is not None and atr>0:reasons.append('ATR ile risk aralığı izleniyor')
    breakout=n('gun_ici_hacimli_kirilim') if intraday else n('yarin_kirilim')
    if breakout is not None and price is not None and price>=breakout and volume_side==1:reasons.append('Hacimli kırılım seviyesi teyit edildi')
    return {'karar':decision,'karar_puani':score,'confidence':round(confidence,1),'teknik_gucluluk':technical,
            'risk_puani':min(100,len(blocked)*15+downs*8+len(quality)*3),'pozitif_gerekceler':reasons,'negatif_gerekceler':risks,
            'ana_risk':labels[blocked[0]] if blocked else risks[0] if risks else 'Belirgin risk saptanmadı',
            'ana_secim_nedeni':'; '.join(reasons[:3]) if decision in ('AL','GUCLU_AL') else '; '.join(risks[:3]) or 'Yeterli yön teyidi yok',
            'teyit_sayisi':matched,'teyit_toplam':len(tech_keys),'minimum_al_teyidi':buy_min,'minimum_guclu_al_teyidi':strong_min,
            'kullanilan_kriterler':flags,'safety_flags':blocked,'model_version':FINAL_MODEL,
            'girdi_snapshot':{'fiyat':price,'stop':stop,'risk_getiri':rr,'rsi':rsi,'macd':line,'signal':signal,
                             'hacim_orani':volume,'atr':atr,'breadth':breadth,'sektor_relatif_guc':sector,
                             'teknik_puan':technical,'katkilar':copy.deepcopy(result.get('katkilar',{}))},
            'zaman_dilimi':'INTRADAY' if intraday else 'DAILY','updated_at':current.isoformat(timespec='seconds'),
            'veri_zamani':doc.get('data_time') or result.get('veri_tazeligi',{}).get('teknik_timestamp'),'learning_enabled':False}


def attach_final_decision(row,current,mode):
    """Reuse the existing analysis in memory; preserve every ranking/level field."""
    source=copy.deepcopy(row);source['karar_zaman_dilimi']=mode
    if mode=='INTRADAY':
        source['teknik_puan']=clamp(50+(number(row.get('gun_ici_al_puani'),0)-number(row.get('gun_ici_sat_puani'),0))/2,0,100)
        for old,new in (('rsi5','rsi'),('macd5','macd'),('signal5','signal'),('hist5','hist'),('hacim3_orani','hacim_orani'),('gun_ici_rr','karar_rr')):
            if row.get(old) is not None:source[new]=row[old]
        source.setdefault('destek',row.get('gun_dusuk'));source.setdefault('direnc',row.get('gun_yuksek'))
    doc=source.get('teknik_gostergeler') or {}
    source.setdefault('updated_at',doc.get('asof'))
    market=source.get('piyasa_baglami') or {}
    captured_at=source.get('canli_guncelleme') or source.get('updated_at')
    news=[]
    if number(source.get('haber_puani')) is not None and number(source.get('haber_puani'))!=0:
        news=[{'sembol':source.get('sembol'),'canonical_id':'ANALIZ_OZETI','ilk_gorulme':captured_at,
               'analiz':{'etki_puani':source['haber_puani'],'guven':number(source.get('haber_guven'),50)}}]
    macro={k:source[k] for k in ('makro_puani','sektor_puani') if number(source.get(k)) is not None}
    if macro:macro['updated_at']=captured_at
    try:result=evaluate(source,news=news,macro=macro,current=current)
    except RecordError:
        result={'ai_score':50,'confidence':0,'veri_tazeligi':{},'girdiler':{},'katkilar':{},'piyasa_rejimi':'BILINMIYOR'}
        result['nihai_karar']=final_decision(source,result,current)
    # Context already attached by the existing market layer is used as evidence, not rescored.
    if market:result['piyasa_baglami']=copy.deepcopy(market);result['nihai_karar']=final_decision(source,result,current)
    row['nihai_karar']=copy.deepcopy(result['nihai_karar'])
    return row['nihai_karar']


def decision_view(document,current):
    """Read-time stale protection without changing the frozen signal or alarm identity."""
    result=copy.deepcopy(document or {})
    if not result:return result
    at=stamp(result.get('updated_at'));data=stamp(result.get('veri_zamani'))
    stale=not at or at>current or not data or data>current or (current-data).total_seconds()>1200
    if result.get('zaman_dilimi')=='DAILY' and data and at and at<=current:
        from teknik_gostergeler import stale_at
        stale=stale_at(data,current,'TOMORROW')
    if stale:
        result.update(karar='BEKLE',confidence=min(35,number(result.get('confidence'),0)),ana_risk='Teknik veri eski veya zamanı doğrulanamadı')
        result['stale']=True
    return result


def final_decision_report(records,current,mode='DAILY'):
    """Measure frozen decision/confidence/confirmation buckets; never adapt thresholds."""
    from performans_motoru import robust
    horizons=(5,15,30,60,'SEANS') if mode=='INTRADAY' else HORIZONS
    report={}
    for horizon in horizons:
        groups={}
        for record in records:
            final=record.get('nihai_karar') or {}
            if not final or final.get('zaman_dilimi')!=mode:continue
            signal=stamp(record.get('sinyal_zamani') or record.get('zaman'))
            frozen=stamp(final.get('updated_at'))
            if not signal or signal>current or not frozen or frozen>signal:continue
            outcome=(record.get('sonuclar') or {}).get(str(horizon),{}) if mode=='INTRADAY' else record.get('sonuc_'+str(horizon)+'g') or {}
            observed=stamp(outcome.get('observed_at'))
            complete=outcome.get('tamamlandi') if mode=='INTRADAY' else outcome.get('degerlendirme_tamamlandi')
            if not complete or not observed or observed>current or observed<signal or number(outcome.get('getiri_yuzde')) is None:continue
            if mode=='INTRADAY' and not outcome.get('egitime_uygun'):continue
            if mode=='DAILY' and (record.get('egitim_durumu')=='REFERANS' or outcome.get('kalite_uyarilari')):continue
            if outcome.get('durum') not in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP'):continue
            confidence=number(final.get('confidence'),0)
            bucket='0-49' if confidence<50 else '50-69' if confidence<70 else '70-100'
            for key in ('karar:'+str(final.get('karar')),'confidence:'+bucket,'teyit:'+str(final.get('teyit_sayisi'))):
                groups.setdefault(key,[]).append(outcome)
        report[str(horizon)]={key:{**robust([number(r['getiri_yuzde']) for r in rows]),'sample_count':len(rows),
            'success_rate':sum(r['durum']=='BASARILI' for r in rows)/len(rows)} for key,rows in groups.items()}
    return {'mode':mode,'vadeler':report,'learning_enabled':False,'thresholds_adapted':False,'updated_at':current.isoformat()}


class AIKararMotoru:
    def __init__(self, location=None, clock=None):
        self.location = location or paths()
        self.clock = clock or (lambda: datetime.now(ISTANBUL))
        self.weight_path = self.location.runtime/'ai_agirliklari.json'
        self.public_path = self.location.public/'ai_hisse_ozetleri.json'
        self.history_path = self.location.runtime_file('ai_ogrenme_gecmisi.json')
        self.baseline_path = self.location.runtime/'ai_fiyat_teyit.json'
        self.lock_path = self.location.runtime/'ai_karar_motoru'

    def weights(self):
        if not self.weight_path.exists():
            atomic_json(self.weight_path,{'surum':1,'agirliklar':DEFAULT_WEIGHTS,'sinirlar':
                {k:{'min':v[0],'max':v[1],'gunluk_maksimum_degisim':.005} for k,v in LIMITS.items()},
                'esikler':THRESHOLDS,'learning_enabled':False,'updated_at':self.clock().isoformat()})
        document = load(self.weight_path,{})
        return normalize_weights(document['agirliklar'])

    def update_weights(self, proposed):
        """Explicit bounded parameter update; no automatic optimization or source editing."""
        with locked(self.lock_path):
            current = self.weights()
            if os.environ.get('LEARNING_ENABLED','false').lower() != 'true':
                return {'changed':False,'reason':'LEARNING_DISABLED','agirliklar':current}
            from performans_motoru import minimum_samples
            with locked(self.history_path):
                records=load(self.history_path,{'kayitlar':[]})['kayitlar']
            eligible=[r for r in records if r.get('egitim_durumu')!='REFERANS' and isinstance(r.get('sonuc_1g') or r.get('sonuc_5g'),dict)
                      and (r.get('sonuc_1g') or r.get('sonuc_5g')).get('degerlendirme_tamamlandi',False)
                      and (r.get('sonuc_1g') or r.get('sonuc_5g')).get('durum') in ('BASARILI','KISMEN_BASARILI','BASARISIZ','STOP')]
            if len(eligible)<minimum_samples():
                return {'changed':False,'reason':'MINIMUM_SAMPLES','agirliklar':current}
            doc = load(self.weight_path,{})
            day = self.clock().astimezone(ISTANBUL).date().isoformat()
            baseline = doc.get('gun_baslangic',current) if doc.get('degisim_gunu')==day else current
            bounds = {k:(max(LIMITS[k][0],baseline[k]-.005),min(LIMITS[k][1],baseline[k]+.005)) for k in current}
            updated = normalize_weights(proposed,bounds)
            doc.update(agirliklar=updated,gun_baslangic=baseline,degisim_gunu=day,learning_enabled=True,updated_at=self.clock().isoformat())
            atomic_json(self.weight_path,doc)
            return {'changed':updated!=current,'agirliklar':updated}

    def batch(self, stocks, rows=None):
        results, errors = {}, {}
        # One batch uses one coherent shared input snapshot and no provider requests.
        with locked(self.lock_path):
            data = load(self.location.public/'bist_data.json',{'hisseler':[]})
            row_map = {r['sembol']:r for r in data.get('hisseler',[]) if isinstance(r,dict) and r.get('sembol')}
            for row in rows or []:
                if not isinstance(row,dict) or not row.get('sembol'):continue
                if 'gun_ici_al_puani' in row and row['sembol'] in row_map:
                    merged=dict(row)
                    merged['karar_zaman_dilimi']='INTRADAY'
                    merged['teknik_puan']=clamp(50+(number(row.get('gun_ici_al_puani'),0)-number(row.get('gun_ici_sat_puani'),0))/2,0,100)
                    for old,new in (('rsi5','rsi'),('macd5','macd'),('signal5','signal'),('hacim3_orani','hacim_orani'),('gun_ici_rr','karar_rr')):
                        if row.get(old) is not None:merged[new]=row[old]
                    merged.setdefault('updated_at',(row.get('teknik_gostergeler') or {}).get('asof'))
                    row_map[row['sembol']]=merged
                else:row_map[row['sembol']]=row
            def optional(path, default):
                try:
                    value=load(path,default)
                    return value if isinstance(value,type(default)) else default
                except (ValueError,OSError):return default
            ledger = optional(self.location.runtime/'haber_dedup.json',{'haberler':[]})
            news = ledger.get('haberler',[])
            if not news: news = optional(self.location.runtime_file('haber_zeka_gecmisi.json'),{'haberler':[]}).get('haberler',[])
            macro = optional(self.location.public/'makro_canli_etki.json',{})
            intraday = optional(self.location.public/'gun_ici_tum.json',{'hisseler':[]})
            intraday_map = {r['sembol']:r for r in intraday.get('hisseler',[]) if isinstance(r,dict) and r.get('sembol')}
            market = optional(self.location.public/'piyasa_durumu.json',{'model':'BIST_CONTEXT_V1'})
            try: weights = self.weights(); weight_error = False
            except (ValueError,KeyError,TypeError): weights = DEFAULT_WEIGHTS; weight_error = True
            current = self.clock().astimezone(ISTANBUL)
            baselines = load(self.baseline_path,{})
            public = load(self.public_path,{'surum':1,'hisseler':{}})
            with locked(self.history_path):
                history = load(self.history_path,{'kayitlar':[]})
                records = history.setdefault('kayitlar',[])
                ids = {r.get('kayit_id') for r in records}
                for raw_stock in dict.fromkeys(stocks):
                    try:
                        stock = symbol(raw_stock)
                        row = dict(row_map.get(stock,{'sembol':stock}))
                        daily_status=intraday_map.get(stock,{})
                        row.setdefault('gun_ici_sinyal_durumu',daily_status.get('gun_ici_sinyal_durumu'))
                        # A file timestamp is weaker than a per-stock quote timestamp.
                        inherited = not (row.get('canli_guncelleme') or row.get('updated_at'))
                        if inherited: row['updated_at'] = data.get('updated_at') or data.get('guncelleme')
                        context = dict(macro.get('hisseler',{}).get(stock,{}))
                        if context:
                            for key in ('guncelleme','updated_at','event_id'):context.setdefault(key,macro.get(key))
                        config=load(self.weight_path,{}) if not weight_error else {}
                        model_at=stamp(config.get('updated_at'))
                        if model_at and model_at>current:weights=DEFAULT_WEIGHTS;config={}
                        result = evaluate(row,news,context,records,market,weights,current,baselines,config.get('esikler'))
                        if inherited:
                            result['risk_flags'].append('HISSE_BAZLI_ZAMAN_EKSIK');result['confidence']=round(result['confidence']*.8,1)
                        if weight_error:result['risk_flags'].append('AGIRLIK_DOSYASI_GECERSIZ')
                        if result['confidence'] < 50 and 'DUSUK_GUVEN' not in result['risk_flags']:result['risk_flags'].append('DUSUK_GUVEN')
                        if result['confidence'] < 50 and result['karar'] in ('AL','GUCLU_AL','SAT','GUCLU_SAT'):result['karar']='IZLE'
                        if result['confidence']<50:
                            result['nihai_karar']['confidence']=result['confidence']
                            if result['nihai_karar']['karar'] in ('AL','GUCLU_AL','SAT','GUCLU_SAT'):
                                result['nihai_karar'].update(karar='BEKLE',ana_risk='Hisse bazlı veri güveni yetersiz')
                        signal_time=stamp(result['veri_tazeligi']['teknik_timestamp'])
                        signal_bucket=signal_time.replace(minute=(signal_time.minute//5)*5,second=0,microsecond=0).isoformat() if signal_time else None
                        identity = [FINAL_MODEL,stock,signal_bucket,result['karar'],result['canonical_ids'],
                                    result['makro_event_id'],result['sektor_event_id'],result['piyasa_rejimi']]
                        signal_id = 'ORTAK_AI_'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:24]
                        result['sinyal_id'] = signal_id
                        public['hisseler'][stock] = result;results[stock] = result
                        if signal_id not in ids:
                            trainable = current.weekday()<5 and 600<=current.hour*60+current.minute<=1090 and result['confidence']>=50 and number(row.get('fiyat'),0)>0
                            record = {'kayit_id':signal_id,'model':'ORTAK_AI','sembol':stock,'zaman':result['updated_at'],
                                'karar':result['karar'],'ai_score':result['ai_score'],'confidence':result['confidence'],
                                'nihai_karar':copy.deepcopy(result['nihai_karar']),
                                'katkilar':result['katkilar'],'piyasa_rejimi':result['piyasa_rejimi'],'sektor':result['sektor'],
                                'teknik_gostergeler':result['teknik_gostergeler'],
                                'standart_teknik_kriterler':result['standart_teknik_kriterler'],
                                'piyasa_baglami':result['piyasa_baglami'],
                                'fiyat':number(row.get('fiyat')),'reasons_positive':result['reasons_positive'],
                                'reasons_negative':result['reasons_negative'],'risk_flags':result['risk_flags'],
                                'sonuc':'BEKLIYOR' if trainable else 'REFERANS','egitim_durumu':'EGITIM' if trainable else 'REFERANS',
                                'sinyal_id':signal_id,'sinyal_turu':'ORTAK_AI','referans_fiyat':number(row.get('fiyat')),
                                'kriterler':{**result['girdiler'],**{k:row.get(k) for k in ('momentum15','karar_rr','risk_getiri')}},
                                'haber_etkisi':result['katkilar']['haber'],'makro_etkisi':result['katkilar']['makro'],
                                'haber_katkilari':result['haber_katkilari'],'teknik_skor':number(row.get('teknik_puan'),number(row.get('al_puani'))),
                                'kaynak':'ORTAK_AI','snapshot_id':None,'hedef':number(row.get('karar_hedef'),number(row.get('hedef1'))),
                                'stop':number(row.get('karar_stop'),number(row.get('stop'))),
                                **{'sonuc_'+str(day)+'g':None for day in HORIZONS}}
                            records.append(record);ids.add(signal_id)
                    except Exception as error:
                        errors[str(raw_stock)] = type(error).__name__
                history.update(guncelleme=current.isoformat(),toplam_kayit=len(records))
                atomic_json(self.history_path,history)
            atomic_json(self.baseline_path,baselines)
            public['updated_at'] = current.isoformat(timespec='seconds')
            self.public_path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(self.public_path,public)
        return {'hisseler':results,'hatalar':errors}

    def measure(self, stock, closes):
        """Record frozen 1/3/5/10/20/60 trading-session outcomes from supplied closes.

        Supply only complete, dated exchange sessions; never count today's intraday quote.
        No new market provider: callers can reuse their already downloaded history.
        """
        from performans_motoru import outcome
        stock = symbol(stock);current = self.clock().astimezone(ISTANBUL)
        changed = 0
        with locked(self.history_path):
            doc = load(self.history_path,{'kayitlar':[]})
            for record in doc['kayitlar']:
                if record.get('model')!='ORTAK_AI' or record.get('sembol')!=stock:continue
                for day in HORIZONS:
                    key = 'sonuc_'+str(day)+'g'
                    existing=record.get(key)
                    if isinstance(existing,dict) and existing.get('degerlendirme_tamamlandi',True):continue
                    result=outcome(record,closes,day,current,require_ohlc=False)
                    if result is None:continue
                    record[key]=result
                    changed+=int(result['degerlendirme_tamamlandi'])
            atomic_json(self.history_path,doc)
        return changed

    def contribution_performance(self):
        """Descriptive associations, never automatic causality/weight optimization."""
        with locked(self.history_path):records=load(self.history_path,{'kayitlar':[]})['kayitlar']
        result = {}
        for group in DEFAULT_WEIGHTS:
            values = [(r['katkilar'].get(group,0),r['sonuc_5g']['getiri_yuzde']) for r in records
                if r.get('model')=='ORTAK_AI' and r.get('egitim_durumu')!='REFERANS' and isinstance(r.get('sonuc_5g'),dict)
                and r['sonuc_5g'].get('degerlendirme_tamamlandi',True) and number(r['sonuc_5g'].get('getiri_yuzde')) is not None
                and r['sonuc_5g'].get('durum')!='VERI_YETERSIZ']
            informative = [(c,p) for c,p in values if abs(c)>.01]
            result[group] = {'ornek':len(informative),'yon_uyumu':sum((c>0)==(p>0) for c,p in informative)/len(informative) if informative else None}
        return result


def ai_batch_guncelle(semboller, rows=None):
    return AIKararMotoru().batch(semboller,rows)


def ai_hisse_guncelle(sembol, row=None):
    return ai_batch_guncelle([sembol], [row] if row is not None else None)


def ai_sonuclari_guncelle(sembol, kapanislar):
    return AIKararMotoru().measure(sembol,kapanislar)


def ai_ozet_oku(sembol, location=None):
    """All screens read the same result; reading never evaluates or changes history."""
    try:
        return load((location or paths()).public/'ai_hisse_ozetleri.json',{}).get('hisseler',{}).get(symbol(sembol))
    except (ValueError, OSError, AttributeError):
        return None
