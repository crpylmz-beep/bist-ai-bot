"""Purged chronological evidence derived from verified live TOP10 outcomes."""
from collections import defaultdict
from datetime import datetime
from math import sqrt
from statistics import mean, stdev

from ai_karar_motoru import HORIZONS, ISTANBUL, number, stamp

VERSION = 'TOP10_TEMPORAL_V1'
MIN_TRAIN_DAYS = 10
MIN_VALIDATION_DAYS = 5
MIN_SAMPLES = 30
# Conservative interval across clustered prediction days, not individual stocks.
# Fixed before seeing outcomes; no bucket/weight search on validation labels.
EDGE_Z = 3.5


def build_evidence(records, current, holiday=None):
    from sinyal_performansi import Stats, indicator_conditions, quality, signal, unique_records
    current = current.astimezone(ISTANBUL)
    unique, _, _ = unique_records(records)
    candidates = [(row, indicator_conditions(row)) for row, conflict in unique
                  if not conflict and signal(row) == 'YARIN_TOP10']
    output = []; baselines = {}
    for horizon in HORIZONS:
        verified = [(row, conditions) for row, conditions in candidates
                    if quality(row, horizon, current, holiday) is None
                    and not row[f'sonuc_{horizon}g'].get('unverified')
                    and not isinstance(row[f'sonuc_{horizon}g'].get('getiri_yuzde'), bool)]
        dates = sorted({stamp(row.get('zaman') or row.get('tarih')).date()
                        for row, _ in verified})
        if len(dates) < MIN_TRAIN_DAYS + MIN_VALIDATION_DAYS:
            continue
        validation_days = max(MIN_VALIDATION_DAYS, (len(dates) + 4) // 5)
        cutoff = datetime.combine(dates[-validation_days], datetime.min.time(), ISTANBUL)
        groups = defaultdict(Stats); days = defaultdict(set); daily = defaultdict(lambda: defaultdict(list))
        latest_train_outcome = None
        for row, conditions in verified:
            at = stamp(row.get('zaman') or row.get('tarih'))
            observed = stamp(row[f'sonuc_{horizon}g']['observed_at'])
            split = 'validation' if at >= cutoff else 'train'
            # Purge overlapping labels and delayed observations from training.
            if split == 'train':
                if observed >= cutoff: continue
                latest_train_outcome = max(latest_train_outcome or observed, observed)
            for key in [('BASE', 'ALL'), *conditions.items()]:
                group = (split, *key)
                groups[group].add(row, horizon, None)
                days[group].add(at.date())
                daily[group][at.date()].append(number(row[f'sonuc_{horizon}g']['getiri_yuzde']))

        def export(key):
            return {**groups[key].export(), 'independent_days': len(days[key])}

        baseline = {split: export((split, 'BASE', 'ALL')) for split in ('train', 'validation')}
        baselines[str(horizon)] = baseline
        keys = sorted({(indicator, condition) for _, indicator, condition in groups if indicator != 'BASE'})
        for indicator, condition in keys:
            splits = {}
            for split in ('train', 'validation'):
                key = (split, indicator, condition)
                edges = [mean(values) - mean(daily[(split, 'BASE', 'ALL')][day])
                         for day, values in daily[key].items()]
                center = mean(edges) if edges else None
                margin = EDGE_Z * stdev(edges) / sqrt(len(edges)) if len(edges) > 1 else None
                splits[split] = {**export(key),
                                 'daily_edge_lower': center - margin if margin is not None else None,
                                 'daily_edge_upper': center + margin if margin is not None else None}
            output.append({'indicator': indicator, 'condition': condition,
                           'signal_type': 'YARIN_TOP10', 'horizon': horizon,
                           'cutoff': cutoff.isoformat(),
                           'train_observed_through': latest_train_outcome.isoformat() if latest_train_outcome else None,
                           **splits})
    return {'version': VERSION, 'updated_at': current.isoformat(), 'analysis_only': True,
            'rows': output, 'baselines': baselines}
