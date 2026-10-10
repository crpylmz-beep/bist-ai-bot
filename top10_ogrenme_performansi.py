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


def verified(row, horizon, current, holiday=None):
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
    excluded = Counter()
    data_quality={name:{'records':len(items),'verified':0,'pending':0,'missing_due_outcomes':0,'excluded':0}
                  for name,items in lists.items()}
    for name, items in lists.items():
        ranks = [r.get('tahmin_sirasi') for r in items]
        symbols = [r.get('sembol') for r in items]
        if len(items) != 10 or sorted(ranks, key=str) != sorted(range(1, 11), key=str) or len(set(symbols)) != 10:
            excluded[name + '_INCOMPLETE_TOP10'] += 1
    for row, conflict in rows:
        reason = 'CONFLICTING_DUPLICATE' if conflict else verified(row, horizon, current, holiday)
        if reason: excluded[reason] += 1
        name=next(name for name,model in MODELS.items() if row.get('model')==model)
        if reason is None:data_quality[name]['verified']+=1
        elif reason in ('PENDING','FUTURE_OUTCOME'):
            from performans_motoru import sessions_after,session_closed
            signal_time=stamp(row.get('zaman'))
            due=signal_time and signal_time<=current and session_closed(sessions_after(signal_time.date(),horizon,holiday)[-1],current)
            data_quality[name]['missing_due_outcomes' if due else 'pending']+=1
        else:data_quality[name]['excluded']+=1
    result['data_quality']=data_quality
    # Paired predictions must share one frozen observation time and symbol price.
    times = {r.get('zaman') for r, _ in rows}
    if len(times) != 1: excluded['INCONSISTENT_SNAPSHOT_TIME'] += 1
    prices = defaultdict(set)
    for row, _ in rows: prices[row.get('sembol')].add(number(row.get('fiyat')))
    if any(len(v) > 1 for v in prices.values()): excluded['INCONSISTENT_BASE_PRICE'] += 1
    closes = defaultdict(set)
    for row, _ in rows:
        value = row.get(f'sonuc_{horizon}g')
        if isinstance(value, dict): closes[row.get('sembol')].add(number(value.get('fiyat')))
    if any(len(v) > 1 for v in closes.values()): excluded['INCONSISTENT_RESULT_PRICE'] += 1
    result['excluded'] = dict(excluded)
    if excluded: return result
    result['base'] = metrics(lists['BASE'], horizon)
    result['learned'] = metrics(lists['LEARNED'], horizon)
    keys = ('mean_return', 'median_return', 'success_rate', 'top3_return', 'top5_return', 'top10_return')
    result['differences'] = {k: result['learned'][k] - result['base'][k] for k in keys}
    edge = result['differences']['mean_return']
    result['status'] = 'TIE' if math.isclose(edge, 0, abs_tol=1e-9) else 'LEARNED_BETTER' if edge > 0 else 'BASE_BETTER'
    return result


def summary(comparisons):
    valid = [r for r in comparisons if r['status'] != 'INSUFFICIENT']
    counts = Counter(r['status'] for r in valid)
    edges = [r['differences']['mean_return'] for r in valid]
    models={}
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
    delta={'mean_return':models['LEARNED']['mean_return']-models['BASE']['mean_return'] if all(models[n]['sample_count'] for n in MODELS) else None,
           'success_rate_percentage_points':100*(models['LEARNED']['success_rate']-models['BASE']['success_rate']) if all(models[n]['sample_count'] for n in MODELS) else None}
    exclusions=Counter()
    for row in comparisons:exclusions.update(row.get('excluded',{}))
    return {'completed_days': len(valid), 'insufficient_days': len(comparisons) - len(valid),
            'learned_wins': counts['LEARNED_BETTER'], 'base_wins': counts['BASE_BETTER'],
            'ties': counts['TIE'], 'learned_win_rate': counts['LEARNED_BETTER'] / len(valid) if valid else None,
            'mean_learned_edge': mean(edges) if edges else None,
            'median_learned_edge': median(edges) if edges else None,
            'models':models,'differences_vs_base':delta,'excluded_reasons':dict(exclusions),
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
    comparisons = [comparison(key, rows, h, current, holiday)
                   for key, rows in sorted(groups.items()) for h in HORIZONS]
    periods = {}
    for period, days in PERIODS.items():
        cohort = [r for r in comparisons if stamp(r['snapshot_time']) and
                  (days is None or stamp(r['snapshot_time']) >= current - timedelta(days=days))]
        periods[period] = {str(h): summary([r for r in cohort if r['horizon'] == h]) for h in HORIZONS}
    changes = []
    for key, items in sorted(groups.items(), reverse=True):
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
