"""Read-only identity census for explicitly supported runtime JSON schemas.

Reports aggregate identity collisions, never records, keys, paths or digests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import time

import ijson
from storage_schemas import SCHEMAS

DATASETS = {
    'ai_ogrenme_gecmisi.json',
    'tahmin_gecmisi.json',
    'gun_ici_sonuclar.json',
    'yarin_top10_sonuclar.json',
}
KEY_FIELDS = ('kayit_id', 'event_id', 'prediction_id', 'signal_id',
              'result_id', 'id', 'canonical_id')

def _fingerprint(row):
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256()
    for token in encoder.iterencode(row):
        digest.update(token.encode('utf-8'))
    return digest.digest()

def _identity(row, mapping_key=None):
    if not isinstance(row, dict):
        return None
    key = next((row[k] for k in KEY_FIELDS
                if isinstance(row.get(k), str) and row[k]), mapping_key)
    if not isinstance(key, str) or not key or len(key) > 512:
        return None
    if mapping_key is not None and key != mapping_key:
        return None
    return key

def audit(root, max_seconds=600, max_records=2000000):
    root = Path(root).absolute()
    deadline = time.monotonic() + max_seconds
    summary = {}
    incomplete = False
    for filename in sorted(DATASETS):
        if time.monotonic() >= deadline:
            incomplete = True
            break
        field, mapping = SCHEMAS[filename]
        row = {'records': 0, 'unique_ids': 0, 'identical_repeats': 0,
               'conflicting_repeats': 0, 'missing_or_invalid_id': 0,
               'errors': 0, 'changed': 0, 'truncated': False}
        summary[filename] = row
        path = root / 'runtime' / filename
        identities = {}
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                row['errors'] += 1
                incomplete = True
                continue
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    row['changed'] += 1
                    incomplete = True
                    continue
                iterator = ijson.kvitems(stream, field) if mapping else ijson.items(stream, field + '.item')
                for item in iterator:
                    if time.monotonic() >= deadline or row['records'] >= max_records:
                        row['truncated'] = True
                        incomplete = True
                        break
                    mapping_key, record = item if mapping else (None, item)
                    row['records'] += 1
                    key = _identity(record, mapping_key)
                    if key is None:
                        row['missing_or_invalid_id'] += 1
                        continue
                    digest = _fingerprint(record)
                    old = identities.get(key)
                    if old is None:
                        identities[key] = digest
                    elif old == digest:
                        row['identical_repeats'] += 1
                    else:
                        row['conflicting_repeats'] += 1
            after = path.lstat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                row['changed'] += 1
                incomplete = True
        except (OSError, ValueError, UnicodeError, ijson.JSONError):
            row['errors'] += 1
            incomplete = True
        row['unique_ids'] = len(identities)
        if row['errors'] or row['changed']:
            incomplete = True
    return {
        'status': 'INCOMPLETE' if incomplete else 'STRUCTURAL_ID_AUDIT_OK',
        'scope': 'FOUR_EXPLICIT_RUNTIME_DATASETS_ONLY',
        'counts': summary,
        'note': 'Identity collisions within each dataset only. No record is deleted, merged or migrated. Incomplete on changed source or scan budget.'
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    result = audit(args.root)
    print('[V6_RECORD_ID_AUDIT] ' + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] == 'STRUCTURAL_ID_AUDIT_OK' else 2

if __name__ == '__main__':
    raise SystemExit(main())
