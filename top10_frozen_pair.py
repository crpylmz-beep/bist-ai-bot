"""Versioned paired predictions inside the existing immutable daily archive."""
import copy
import hashlib
import json

from ai_karar_motoru import number, stamp
from sinyal_performansi import indicator_inputs, frozen_feature_issue

SCHEMA = 'TOP10_FROZEN_PAIR_V1'


def digest(value):
    # JSON turns integer horizon keys into strings; hash the persisted form.
    value=json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def freeze_pair(snapshot):
    """Copy already ranked predictions, never invoke a scorer or price provider."""
    at = stamp(snapshot.get('tahmin_zamani'))
    problems = []; inputs = {}; models = {}
    context = copy.deepcopy(snapshot.get('comparison_context') or {})
    learned_asof=stamp(context.get('learning_asof'))
    if context.get('learning_asof') and (not learned_asof or not at or learned_asof>at):
        problems.append('FUTURE_OR_INVALID_LEARNING_CONTEXT')
    for name, field in (('BASE', 'base_top10'), ('LEARNED', 'top10')):
        rows = snapshot.get(field) or []; predictions = []; seen = set()
        if len(rows) != 10: problems.append(name + '_INCOMPLETE_TOP10')
        for rank, row in enumerate(rows, 1):
            frozen = copy.deepcopy(row.get('tahmin') or {})
            symbol = row.get('sembol')
            if not isinstance(symbol, str) or not symbol.strip() or symbol in seen:
                problems.append(name + '_INVALID_SYMBOL')
                continue
            seen.add(symbol)
            values = copy.deepcopy(indicator_inputs(row))
            if (not at or stamp(frozen.get('tahmin_zamani')) != at or
                    frozen_feature_issue(row, at) or isinstance(frozen.get('fiyat'), bool) or
                    number(frozen.get('fiyat'), 0) <= 0):
                problems.append(name + '_INVALID_FROZEN_INPUT')
            observation = {'price': frozen.get('fiyat'), 'inputs': values,
                           'technical': copy.deepcopy(frozen.get('teknik_gostergeler'))}
            if symbol in inputs and inputs[symbol] != observation:
                problems.append('INCONSISTENT_DATA_SLICE')
            inputs[symbol] = observation
            predictions.append({'rank': rank, 'symbol': symbol, 'prediction': frozen,
                                'observation': observation})
        if name == 'BASE':
            config = {'code_version': 'TOP10_BASE_V1',
                      'calibration': copy.deepcopy(snapshot.get('kalibrasyon_modeli')),
                      'market': copy.deepcopy(snapshot.get('piyasa_modeli')),
                      'basis': (snapshot.get('aday_secimi') or {}).get('basis', 'BASE_FINAL_SCORE')}
        else:
            versions = {p['prediction'].get('learning_version') for p in predictions
                        if isinstance(p['prediction'].get('learning_version'), str)}
            version = next(iter(versions)) if len(versions) == 1 and all(
                p['prediction'].get('learning_version') == next(iter(versions)) for p in predictions) else None
            if not version: problems.append('MISSING_OR_MIXED_LEARNING_VERSION')
            config = {'code_version': version, 'context': context}
        models[name] = {'version': config['code_version'], 'configuration': config,
                        'configuration_digest': digest(config), 'top10': predictions}
    payload = {'schema': SCHEMA, 'snapshot_time': snapshot.get('tahmin_zamani'),
               'data_slice_id': digest(inputs), 'models': models,
               'status': 'INSUFFICIENT' if problems else 'READY',
               'display_status': 'YETERSİZ VERİ' if problems else 'KAYDEDİLDİ',
               'issues': sorted(set(problems))}
    return dict(payload, comparison_digest=digest(payload))


def verify_pair(snapshot):
    stored = snapshot.get('frozen_comparison')
    if not isinstance(stored, dict) or stored.get('schema') != SCHEMA:
        return 'UNVERIFIED_PAIR_SCHEMA'
    try:
        if freeze_pair(snapshot) != stored: return 'PAIR_INTEGRITY_MISMATCH'
        if stored.get('status') != 'READY': return 'INCOMPLETE_OR_INCONSISTENT_PAIR'
    except (TypeError, ValueError, KeyError):
        return 'INVALID_PAIR_PAYLOAD'
    return None
