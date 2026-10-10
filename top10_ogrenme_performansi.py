"""Descriptive paired outcomes only; never a ranking or weight input."""
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean, median
import json
import math

from ai_karar_motoru import HORIZONS, number, stamp, locked
from kullanici_kayitlari import atomic_json, RecordError
from sinyal_performansi import quality, unique_records, excursions
from veri_yollari import paths

VERSION = 'TOP10_PAIRED_PERFORMANCE_V1'
MODELS = {'BASE': 'YARIN_LEARNING_BASELINE', 'LEARNED': 'YARIN_TOP10'}
PERIODS = {'7d': 7, '30d': 30, '90d': 90, 'all_time': None}
MAX_RECENT = 100
MAX_RANK_CHANGES = 2000
MIN_PAIRED_DAYS = 10
MIN_PAIRED_SAMPLES = 100


def verified(row, horizon, current, holiday=None):
    if row.get('comparison_integrity_error'):return row['comparison_integrity_error']
    # BASE is an immutable prospective control, not a live training sample.
    # Reuse all price/session/provenance gates without weakening global quality.
    if row.get('kaynak') != 'IMMUTABLE_YARIN_SNAPSHOT': return 'UNVERIFIED_SNAPSHOT'
    if row.get('model') == MODELS['BASE'] and row.get('performance_source') not in (None, 'LIVE', 'UNKNOWN'):
        return 'NON_PROSPECTIVE_CONTROL'
    if row.get('model') == MODELS['LEARNED'] and (row.get('analysis_only') or row.get('performance_source') not in (None, 'LIVE')):
        return 'NON_LIVE'
    candidate = dict(row, model='YARIN_TOP10', performance_source='LIVE', analysis_only=False)
    result = row.get(f'sonuc_{horizon}g')
    if isinstance(result, dict):
        if result.get('unverified'):return 'UNVERIFIED_RESULT'
        if isinstance(result.get('getiri_yuzde'),bool):return 'INVALID_RESULT_RETURN'
        candidate[f'sonuc_{horizon}g'] = dict(result, performance_source='LIVE')
        if result.get('performance_source') not in (None, 'LIVE', 'UNKNOWN'):
            return 'NON_PROSPECTIVE_RESULT'
    return quality(candidate, horizon, current, holiday)


def metrics(rows, horizon):
    ordered = sorted(rows, key=lambda r: r['tahmin_sirasi'])
    values = [number(r[f'sonuc_{horizon}g']['getiri_yuzde']) for r in ordered]
    positive = sum(v > 0 for v in values)
    moves = [excursions(dict(r, model='YARIN_TOP10'), horizon) for r in ordered]
    mfe = [a for a, _ in moves if a is not None]
    mae = [b for _, b in moves if b is not None]
    average = mean(values)
    average_mae = mean(mae) if mae else None
    return {'count': len(values), 'mean_return': average, 'median_return': median(values),
            'positive_count': positive, 'success_rate': positive / len(values),
            'return_samples':values,'mfe_values':mfe,'mae_values':mae,
            'best_return': max(values), 'worst_return': min(values),
            'mean_mfe': mean(mfe) if mfe else None, 'max_mfe': max(mfe) if mfe else None,
            'mean_mae': average_mae, 'worst_mae': min(mae) if mae else None,
            'mfe_samples': len(mfe), 'mae_samples': len(mae),
            'top3_return': mean(values[:3]), 'top5_return': mean(values[:5]),
            'top10_return': average,
            'return_to_adverse_excursion': average / abs(average_mae)
                if average_mae and len(mae) == len(values) else None}


def comparison(snapshot_id, rows, horizon, current, holiday=None):
    lists = {name: [r for r, _ in rows if r.get('model') == model] for name, model in MODELS.items()}
    at = min((stamp(r.get('zaman')) for r, _ in rows if stamp(r.get('zaman'))), default=None)
    result = {'snapshot_id': snapshot_id, 'snapshot_time': at.isoformat() if at else None,
              'horizon': horizon, 'status': 'INSUFFICIENT', 'base': None, 'learned': None,
              'differences': None, 'excluded': {}}
    versions = {r.get('learning_version') for r in lists['LEARNED']
                if isinstance(r.get('learning_version'),str) and r['learning_version'].strip()}
    result['learning_version'] = next(iter(versions)) if len(versions)==1 and all(
        isinstance(r.get('learning_version'),str) and r['learning_version'] in versions
        for r in lists['LEARNED']) else None
    result['learning_applied'] = any(number(r.get('learning_adjustment'),0)!=0 for r in lists['LEARNED'])
    result['model_versions']={name:{'version':items[0].get('model_version') if items else None,
        'configuration_digest':items[0].get('model_configuration_digest') if items else None}
        for name,items in lists.items()}
    result['outcomes_available_at'] = None
    excluded = Counter()
    if any(r.get('comparison_schema') for r,_ in rows):
        for field in ('comparison_schema','data_slice_id','comparison_digest'):
            values=[r.get(field) for r,_ in rows]
            if any(not isinstance(v,str) or not v for v in values) or len(set(values))!=1:
                excluded['INCONSISTENT_'+field.upper()]+=1
        for name,items in lists.items():
            for field in ('model_version','model_configuration_digest'):
                values=[r.get(field) for r in items]
                if not values or any(not isinstance(v,str) or not v for v in values) or len(set(values))!=1:
                    excluded[name+'_INCONSISTENT_'+field.upper()]+=1
    observed = {name: [] for name in MODELS}
    coherent = not excluded
    data_quality={name:{'records':len(items),'verified':0,'pending':0,'missing_due_outcomes':0,'excluded':0}
                  for name,items in lists.items()}
    for name, items in lists.items():
        ranks = [r.get('tahmin_sirasi') for r in items]
        symbols = [r.get('sembol') for r in items]
        if (len(items)>10 or len(set(symbols))!=len(symbols) or
            any(type(rank) is not int or not 1<=rank<=10 for rank in ranks) or len(set(ranks))!=len(ranks)):
            coherent = False
        if len(items) != 10 or sorted(ranks, key=str) != sorted(range(1, 11), key=str) or len(set(symbols)) != 10:
            excluded[name + '_INCOMPLETE_TOP10'] += 1
    for row, conflict in rows:
        reason = 'CONFLICTING_DUPLICATE' if conflict else verified(row, horizon, current, holiday)
        if reason: excluded[reason] += 1
        name=next(name for name,model in MODELS.items() if row.get('model')==model)
        if reason is None:
            data_quality[name]['verified']+=1
            observed[name].append(row)
        elif reason in ('PENDING','FUTURE_OUTCOME'):
            from performans_motoru import sessions_after,session_closed
            signal_time=stamp(row.get('zaman'))
            due=signal_time and signal_time<=current and session_closed(sessions_after(signal_time.date(),horizon,holiday)[-1],current)
            data_quality[name]['missing_due_outcomes' if due else 'pending']+=1
        else:data_quality[name]['excluded']+=1
    result['data_quality']=data_quality
    # Paired predictions must share one frozen observation time and symbol price.
    times = {r.get('zaman') for r, _ in rows}
    if len(times) != 1:
        excluded['INCONSISTENT_SNAPSHOT_TIME'] += 1
        coherent = False
    prices = defaultdict(set)
    for row, _ in rows: prices[row.get('sembol')].add(number(row.get('fiyat')))
    if any(len(v) > 1 for v in prices.values()):
        excluded['INCONSISTENT_BASE_PRICE'] += 1
        coherent = False
    closes = defaultdict(set)
    for row, _ in rows:
        value = row.get(f'sonuc_{horizon}g')
        if isinstance(value, dict): closes[row.get('sembol')].add(number(value.get('fiyat')))
    if any(len(v) > 1 for v in closes.values()):
        excluded['INCONSISTENT_RESULT_PRICE'] += 1
    observed_closes = defaultdict(set)
    for items in observed.values():
        for row in items:
            observed_closes[row['sembol']].add(number(row[f'sonuc_{horizon}g']['fiyat']))
    if any(len(values)>1 for values in observed_closes.values()):coherent=False
    result['observed_models'] = {}
    for name, items in observed.items():
        values = [number(row[f'sonuc_{horizon}g']['getiri_yuzde']) for row in items] if coherent else []
        result['observed_models'][name] = {
            'sample_count': len(values), 'positive_count': sum(value>0 for value in values),
            'mean_return': mean(values) if values else None,
            'success_rate': sum(value>0 for value in values)/len(values) if values else None}
    result['excluded'] = dict(excluded)
    result['display_status']='YETERSİZ VERİ' if excluded else 'TAMAMLANDI'
    if excluded: return result
    result['base'] = metrics(lists['BASE'], horizon)
    result['learned'] = metrics(lists['LEARNED'], horizon)
    result['outcomes_available_at'] = max(stamp(r[f'sonuc_{horizon}g']['observed_at'])
                                        for r,_ in rows).isoformat()
    keys = ('mean_return', 'median_return', 'success_rate', 'top3_return', 'top5_return', 'top10_return')
    result['differences'] = {k: result['learned'][k] - result['base'][k] for k in keys}
    edge = result['differences']['mean_return']
    result['status'] = 'TIE' if math.isclose(edge, 0, abs_tol=1e-9) else 'LEARNED_BETTER' if edge > 0 else 'BASE_BETTER'
    return result


def chronological_evaluation(comparisons):
    """Evaluate frozen prospective ranks; never rescore the past with today's model.

    Timeline metrics are retrospective outcomes as of the enclosing report time,
    not labels available to a learner on the original prediction date.
    """
    ordered = sorted((r for r in comparisons if stamp(r.get('snapshot_time'))),
                     key=lambda r:(stamp(r['snapshot_time']),str(r['snapshot_id'])))

    def evaluate(rows):
        completed = [r for r in rows if r['status']!='INSUFFICIENT' and r.get('learning_version')]
        days = set(); applied_days = set(); samples = 0; returns = Counter(); positives = Counter()
        timeline = []
        for row in rows:
            paired = row['status']!='INSUFFICIENT' and bool(row.get('learning_version'))
            if paired:
                day = stamp(row['snapshot_time']).date();days.add(day)
                if row['learning_applied']:applied_days.add(day)
                samples += row['base']['count']
                for name in MODELS:
                    stat = row[name.lower()]
                    returns[name] += stat['mean_return']*stat['count']
                    positives[name] += stat['positive_count']
            timeline.append({'snapshot_id':row['snapshot_id'],'snapshot_time':row['snapshot_time'],
                             'outcomes_available_at':row.get('outcomes_available_at'),
                             'learning_version':row.get('learning_version'),
                             'status':row['status'],'included_in_paired_metrics':paired,
                             'exclusion_reason':('UNVERIFIED_LEARNING_VERSION' if not row.get('learning_version') else
                                                 'INCOMPLETE_OR_UNVERIFIED_PAIR' if not paired else None),
                             'paired_sample_count':samples,
                             'paired_days':len(days),
                             'cumulative_return_difference':(returns['LEARNED']-returns['BASE'])/samples if samples else None,
                             'cumulative_success_difference_pp':100*(positives['LEARNED']-positives['BASE'])/samples if samples else None})
        models = {name:{'sample_count':samples,'mean_return':returns[name]/samples if samples else None,
                        'success_rate':positives[name]/samples if samples else None} for name in MODELS}
        return_delta = (returns['LEARNED']-returns['BASE'])/samples if samples else None
        success_delta = 100*(positives['LEARNED']-positives['BASE'])/samples if samples else None
        sufficient = len(days)>=MIN_PAIRED_DAYS and samples>=MIN_PAIRED_SAMPLES
        if not sufficient:assessment='INSUFFICIENT_DATA'
        elif len(applied_days)<MIN_PAIRED_DAYS:assessment='INSUFFICIENT_APPLIED_LEARNING'
        elif math.isclose(return_delta,0,abs_tol=1e-9) and math.isclose(success_delta,0,abs_tol=1e-9):assessment='TIE'
        elif return_delta>0 and success_delta>=0:assessment='DESCRIPTIVE_LEARNED_AHEAD'
        elif return_delta<0 and success_delta<=0:assessment='DESCRIPTIVE_BASE_AHEAD'
        else:assessment='MIXED_RESULTS'
        return {'assessment':assessment,'sufficient':sufficient,'paired_days':len(days),
                'paired_snapshots':len(completed),'paired_samples_per_model':samples,
                'applied_learning_days':len(applied_days),'excluded_snapshots':len(rows)-len(completed),
                'models':models,'differences_vs_base':{'mean_return':return_delta,
                    'success_rate_percentage_points':success_delta},
                'first_snapshot_time':rows[0]['snapshot_time'] if rows else None,
                'last_snapshot_time':rows[-1]['snapshot_time'] if rows else None,
                'timeline':timeline[-MAX_RECENT:],'timeline_truncated':len(timeline)>MAX_RECENT}

    versions = sorted({r['learning_version'] for r in ordered if r.get('learning_version')})
    overall=evaluate(ordered)
    if len(versions)>1:overall['assessment']='MULTIPLE_MODEL_VERSIONS'
    return {**overall,'by_learning_version':{
                version:evaluate([r for r in ordered if r.get('learning_version')==version]) for version in versions},
            'minimum_paired_days':MIN_PAIRED_DAYS,'minimum_samples_per_model':MIN_PAIRED_SAMPLES,
            'comparison_basis':'PROSPECTIVE_IMMUTABLE_SNAPSHOTS',
            'reconstructed_scores':False,'improvement_claim':'DESCRIPTIVE_ONLY_NOT_STATISTICAL_PROOF',
            'metric_timeline_basis':'RETROSPECTIVE_OUTCOMES_BY_PREDICTION_TIME'}


def summary(comparisons):
    valid = [r for r in comparisons if r['status'] != 'INSUFFICIENT']
    counts = Counter(r['status'] for r in valid)
    edges = [r['differences']['mean_return'] for r in valid]
    models={}
    observed_models={}
    for name in MODELS:
        rows=[r[name.lower()] for r in valid if isinstance(r.get(name.lower()),dict)]
        samples=sum(r['count'] for r in rows)
        positives=sum(r['positive_count'] for r in rows)
        quality_counts=Counter()
        for comparison in comparisons:quality_counts.update(comparison.get('data_quality',{}).get(name,{}))
        models[name]={'sample_count':samples,'positive_count':positives,
                      'success_rate':positives/samples if samples else None,
                      'mean_return':sum(r['mean_return']*r['count'] for r in rows)/samples if samples else None,
                      'data_quality':dict(quality_counts)}
        returns=[v for r in rows for v in r.get('return_samples',[])]
        mae=[v for r in rows for v in r.get('mae_values',[])]
        mfe=[v for r in rows for v in r.get('mfe_values',[])]
        risk_complete=bool(samples) and len(mae)==samples and len(mfe)==samples
        models[name].update(median_return=median(returns) if samples and len(returns)==samples else None,
            risk={'display_status':'TAMAMLANDI' if risk_complete else 'YETERSİZ VERİ',
                  'complete':risk_complete,'mae_samples':len(mae),'mfe_samples':len(mfe),
                  'mean_mae':mean(mae) if mae else None,'median_mae':median(mae) if mae else None,
                  'worst_mae':min(mae) if mae else None,'mean_mfe':mean(mfe) if mfe else None,
                  'median_mfe':median(mfe) if mfe else None})
        observed=[r['observed_models'][name] for r in comparisons if name in r.get('observed_models',{})]
        observed_samples=sum(r['sample_count'] for r in observed)
        observed_positive=sum(r['positive_count'] for r in observed)
        observed_models[name]={
            'sample_count':observed_samples, 'positive_count':observed_positive,
            'success_rate':observed_positive/observed_samples if observed_samples else None,
            'mean_return':sum(r['mean_return']*r['sample_count'] for r in observed if r['sample_count'])/observed_samples if observed_samples else None}
    delta={'mean_return':models['LEARNED']['mean_return']-models['BASE']['mean_return'] if all(models[n]['sample_count'] for n in MODELS) else None,
           'success_rate_percentage_points':100*(models['LEARNED']['success_rate']-models['BASE']['success_rate']) if all(models[n]['sample_count'] for n in MODELS) else None}
    exclusions=Counter()
    delta['median_return']=(models['LEARNED']['median_return']-models['BASE']['median_return']
                            if all(models[n]['median_return'] is not None for n in MODELS) else None)
    delta['mean_mae']=(models['LEARNED']['risk']['mean_mae']-models['BASE']['risk']['mean_mae']
                      if all(models[n]['risk']['complete'] for n in MODELS) else None)
    for row in comparisons:exclusions.update(row.get('excluded',{}))
    return {'display_status':'TAMAMLANDI' if len({stamp(r.get('snapshot_time')).date() for r in valid
                if stamp(r.get('snapshot_time'))})>=MIN_PAIRED_DAYS else 'YETERSİZ VERİ',
            'completed_days': len(valid), 'insufficient_days': len(comparisons) - len(valid),
            'learned_wins': counts['LEARNED_BETTER'], 'base_wins': counts['BASE_BETTER'],
            'ties': counts['TIE'], 'learned_win_rate': counts['LEARNED_BETTER'] / len(valid) if valid else None,
            'mean_learned_edge': mean(edges) if edges else None,
            'median_learned_edge': median(edges) if edges else None,
            'models':models,'differences_vs_base':delta,'excluded_reasons':dict(exclusions),
            'observed_models':observed_models,
            'observed_metrics_basis':'VERIFIED_OUTCOMES_ONLY_NOT_PAIRED_COMPARISON',
            'metrics_basis':'COMPLETE_VERIFIED_PAIRED_TOP10_ONLY',
            'success_definition':'POSITIVE_CLOSE_RETURN', 'horizon_basis':'BIST_TRADING_SESSIONS'}


def aggregate(records, current, holiday=None):
    selected = [r for r in records if isinstance(r, dict) and r.get('model') in MODELS.values()]
    malformed_input = sum(not isinstance(r.get('sembol'), str) or not isinstance(r.get('zaman'), str) for r in selected)
    selected = [r for r in selected if isinstance(r.get('sembol'), str) and isinstance(r.get('zaman'), str)]
    unique, duplicates, malformed = unique_records(selected)
    groups = defaultdict(list)
    for row, conflict in unique:
        if row.get('snapshot_id'): groups[str(row['snapshot_id'])].append((row, conflict))
    groups = dict(sorted(groups.items(),key=lambda item:(
        min((stamp(r.get('zaman')) for r,_ in item[1] if stamp(r.get('zaman'))),default=current),item[0])))
    comparisons = [comparison(key, rows, h, current, holiday)
                   for key, rows in groups.items() for h in HORIZONS]
    periods = {}
    for period, days in PERIODS.items():
        cohort = [r for r in comparisons if stamp(r['snapshot_time']) and
                  stamp(r['snapshot_time'])<=current and
                  (days is None or stamp(r['snapshot_time']) >= current - timedelta(days=days))]
        periods[period] = {str(h):dict(summary([r for r in cohort if r['horizon']==h]),
            chronological_evaluation=chronological_evaluation([r for r in cohort if r['horizon']==h])) for h in HORIZONS}
    changes = []
    for key, items in reversed(list(groups.items())):
        base = {r['sembol'] for r, _ in items if r['model'] == MODELS['BASE']}
        learned = {r['sembol'] for r, _ in items if r['model'] == MODELS['LEARNED']}
        emitted = set()
        for row, conflict in sorted(items, key=lambda item: item[0]['model'] != MODELS['LEARNED']):
            symbol = row['sembol']
            if symbol in emitted: continue
            emitted.add(symbol)
            if not row.get('rank_change') and (symbol in base) == (symbol in learned): continue
            changes.append({'snapshot_id': key, 'snapshot_time': row.get('zaman'), 'symbol': symbol,
                **{k: row.get(k) for k in ('base_rank', 'learned_rank', 'rank_change', 'learning_adjustment')},
                'entered_top10': symbol in learned and symbol not in base,
                'exited_top10': symbol in base and symbol not in learned,
                'returns': {str(h): number(row[f'sonuc_{h}g']['getiri_yuzde'])
                    if not conflict and verified(row, h, current, holiday) is None else None for h in HORIZONS}})
            if len(changes) >= MAX_RANK_CHANGES: break
        if len(changes) >= MAX_RANK_CHANGES: break
    return {'version': VERSION, 'analysis_only': True, 'updated_at': current.isoformat(),
            'summary': periods['all_time']['1'], 'horizons': periods['all_time'], 'periods': periods,
            'recent_comparisons': sorted(comparisons, key=lambda r: (r['snapshot_time'] or '', r['horizon']), reverse=True)[:MAX_RECENT],
            'rank_changes': changes, 'duplicates': duplicates, 'malformed': malformed + malformed_input,
            'classification_basis': 'PAIRED_TOP10_MEAN_RETURN',
            'period_basis': 'SNAPSHOT_TIME', 'minimum_list_size': 10}


def publish(location, records, current, holiday=None):
    report = aggregate(records, current, holiday)
    target = location.public_file('top10_ogrenme_performansi.json')
    with locked(target): atomic_json(target, report)
    return report


def safe_publish(location, records, current, holiday=None):
    try: return publish(location, records, current, holiday)
    except Exception as error:
        print('[TOP10_COMPARISON] yardımcı rapor üretilemedi:', type(error).__name__)
        return None


def api_report(query, location=None):
    if set(query) - {'horizon', 'period'} or any(len(v) != 1 for v in query.values()):
        raise RecordError('Geçersiz karşılaştırma filtresi.', 400)
    horizon = query.get('horizon', ['1'])[0]
    period = query.get('period', ['all_time'])[0]
    if horizon not in {str(h) for h in HORIZONS} or period not in PERIODS:
        raise RecordError('Geçersiz vade veya dönem.', 400)
    try:
        report = json.loads((location or paths()).public_file('top10_ogrenme_performansi.json').read_bytes())
        if report['version'] != VERSION or report['analysis_only'] is not True: raise ValueError('Version')
        if not stamp(report['updated_at']): raise ValueError('Timestamp')
        result = dict(report, summary=report['periods'][period][horizon], selected_horizon=int(horizon), selected_period=period)
        cutoff = stamp(report['updated_at']) - timedelta(days=PERIODS[period]) if PERIODS[period] else None
        result['recent_comparisons'] = [r for r in report['recent_comparisons'] if r['horizon'] == int(horizon)
            and (cutoff is None or stamp(r['snapshot_time']) and stamp(r['snapshot_time']) >= cutoff)]
        result['rank_changes'] = [dict(r, returns={horizon: r['returns'][horizon]}) for r in report['rank_changes']
            if cutoff is None or stamp(r['snapshot_time']) and stamp(r['snapshot_time']) >= cutoff]
        return result
    except Exception:
        raise RecordError('TOP10 karşılaştırma verisi henüz kullanılamıyor.', 503) from None
