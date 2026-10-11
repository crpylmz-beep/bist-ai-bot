"""Read-only logical source/PG comparison. No imports, receipts or source writes."""
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import stat
import time

import ijson
from ijson.common import ObjectBuilder
from .config import StorageError
from .readonly_json_census import ELIGIBLE
from .readonly_inventory import category
from .records import assemble, digest, row_key, shape_for


class Budget:
    def __init__(self, seconds, max_bytes):
        self.deadline = time.monotonic() + seconds
        self.remaining = max_bytes
    def check(self):
        if time.monotonic() >= self.deadline:
            raise StorageError('VERIFY_TIME_LIMIT')
    def read(self, stream, size):
        self.check()
        block = stream.read(min(size if size >= 0 else 65536, 65536))
        self.remaining -= len(block)
        if self.remaining < 0: raise StorageError('VERIFY_BYTE_LIMIT')
        return block


def discover(root, budget, max_files):
    """Metadata manifest rechecked after comparison; no file paths in report."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir(): raise StorageError('VERIFY_ROOT_INVALID')
    manifest = {}; files_seen = 0
    def walk(folder, parts=(), depth=0):
        nonlocal files_seen
        budget.check()
        if depth > 64: raise StorageError('VERIFY_DEPTH_LIMIT')
        with os.scandir(folder) as entries:
            for entry in entries:
                budget.check(); files_seen += 1
                if files_seen > max_files: raise StorageError('VERIFY_FILE_LIMIT')
                relative = Path(*parts, entry.name)
                st = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
                    try: walk(child, (*parts, entry.name), depth + 1)
                    finally: os.close(child)
                else:
                    group = category(entry.name, relative.parts[:-1])
                    if group in ELIGIBLE:
                        manifest[relative.as_posix()] = (group, st.st_dev, st.st_ino,
                            st.st_size, st.st_mtime_ns, st.st_mode)
                    elif stat.S_ISLNK(st.st_mode):
                        # Cannot establish what categories a linked directory hides.
                        raise StorageError('VERIFY_SOURCE_SYMLINK')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: walk(fd)
    finally: os.close(fd)
    return manifest


def logical_rows(path, shape, budget, max_records, root):
    """Parse only explicitly supported business collections, not structural nodes."""
    relative = Path(path).relative_to(root)
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in relative.parts[:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent); parent = child
        fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    finally: os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        class Reader:
            pending = 0
            def read(self, size=-1):
                block = budget.read(stream, size)
                self.pending += len(block)
                if self.pending > 8 * 1024 * 1024:
                    raise StorageError('SOURCE_TOKEN_TOO_LARGE')
                return block
        reader = Reader()
        builder = None; builder_depth = 0; size = 0; selected = None
        collection_key = None; pending = {}; maps = []; present = set(); first = True
        records = 0
        for prefix, event, value in ijson.parse(reader, use_float=True):
            reader.pending = 0
            budget.check()
            if first:
                first = False
                if event != 'start_map': raise StorageError('SOURCE_ROOT_UNSUPPORTED')
            if event == 'start_map': maps.append(set())
            elif event == 'map_key':
                if value in maps[-1]: raise StorageError('SOURCE_DUPLICATE_FIELD')
                maps[-1].add(value)
                if len(maps[-1]) > max_records + 1024: raise StorageError('VERIFY_KEY_LIMIT')
            elif event == 'end_map': maps.pop()
            if len(maps) > 64: raise StorageError('VERIFY_DEPTH_LIMIT')
            for field, mode in shape.fields.items():
                if prefix == field and event in ('start_map', 'start_array'):
                    expected = 'start_map' if mode == 'mapping' else 'start_array'
                    if event != expected: raise StorageError('SOURCE_COLLECTION_INVALID')
                    present.add(field)
                if prefix == field and mode == 'mapping' and event == 'map_key':
                    pending[field] = value
            if builder is None:
                selected = next((field for field, mode in shape.fields.items()
                    if (mode == 'list' and prefix == field + '.item') or
                       (mode == 'mapping' and field in pending and prefix == field + '.' + pending[field])), None)
                if selected is None: continue
                if event != 'start_map': raise StorageError('SOURCE_RECORD_INVALID')
                records += 1
                if records > max_records: raise StorageError('VERIFY_RECORD_LIMIT')
                builder = ObjectBuilder(); builder_depth = 0; size = 0
                collection_key = pending.get(selected) if shape.fields[selected] == 'mapping' else None
            size += len(str(value).encode()) if value is not None else 1
            if size > 8 * 1024 * 1024: raise StorageError('SOURCE_RECORD_TOO_LARGE')
            builder.event(event, value)
            if event in ('start_map', 'start_array'): builder_depth += 1
            elif event in ('end_map', 'end_array'): builder_depth -= 1
            if builder_depth == 0:
                yield selected, collection_key, builder.value
                builder = None
        if first or not present: raise StorageError('SOURCE_COLLECTION_MISSING')


def verify(root, store, *, source_snapshot=False, max_seconds=300,
           max_files=10000, max_records=100000, max_bytes=1024**3, batch_size=100):
    """Exact comparison within explicit V6 dataset/collection/ID namespaces.

    Live-file stability checks are observational; VERIFIED requires separately
    established consistent snapshot, not merely identical start/end metadata.
    """
    from veri_yollari import DataPaths
    if not math.isfinite(max_seconds) or not 0 < max_seconds <= 3600 or not 1 <= max_files <= 100000 or not 1 <= max_records <= 1000000 or not 1 <= batch_size <= 1000 or not 1 <= max_bytes <= 16 * 1024**3:
        raise StorageError('VERIFY_BUDGET_INVALID')
    root = Path(root).absolute(); location = DataPaths({'BIST_DATA_DIR': str(root)})
    budget = Budget(max_seconds, max_bytes)
    counts = {group: {'source_files': 0, 'source_records': 0, 'duplicate_records': 0,
              'conflicting_duplicates': 0, 'unreadable_files': 0, 'unreadable_records': None,
              'unmapped_records': 0, 'unsupported_files': 0, 'pg_total_records': None,
              'pg_unique_records': None, 'pg_duplicate_records': None, 'verified_records': None, 'missing_records': None,
              'mismatched_records': None, 'progress_percent': None, 'source_digest': None}
              for group in sorted(ELIGIBLE)}
    result = {'status': 'INCONCLUSIVE', 'source_snapshot_declared': source_snapshot,
              'source_changed': False, 'read_only': True, 'categories': counts, 'errors': {},
              'scope': 'CLASSIFIED_LEARNING_PREDICTION_SIGNAL_V6_RECORDS',
              'identity_scope': 'V6_DATASET_COLLECTION_RECORD_ID', 'completion_proven': False}
    identities = {}; uncertain = False; manifest = None; db_failed = False
    database_started = False; database_complete = False; source_complete = False
    def error(code):
        result['errors'][code] = result['errors'].get(code, 0) + 1
    try:
        manifest = discover(root, budget, max_files)
        for relative, info in manifest.items():
            budget.check(); group = info[0]; row = counts[group]; row['source_files'] += 1
            path = root / relative
            if not stat.S_ISREG(info[-1]):
                row['unsupported_files'] += 1; uncertain = True; error('SOURCE_NOT_REGULAR'); continue
            shape = shape_for(path, location)
            if shape is None:
                row['unsupported_files'] += 1; uncertain = True; error('SOURCE_SCHEMA_UNSUPPORTED'); continue
            try:
                for field, mapping_key, record in logical_rows(path, shape, budget, max_records, root):
                    budget.check()
                    try: identity = row_key(shape, field, record, mapping_key)
                    except (ValueError, TypeError):
                        row['unmapped_records'] += 1; uncertain = True; error('SOURCE_ID_UNMAPPABLE'); continue
                    key = (shape.dataset + '#' + field, identity)
                    hashed = digest(record)
                    if key in identities:
                        row['duplicate_records'] += 1
                        if identities[key][1] != hashed:
                            row['conflicting_duplicates'] += 1; uncertain = True; error('SOURCE_ID_CONFLICT')
                        continue
                    if len(identities) >= max_records: raise StorageError('VERIFY_RECORD_LIMIT')
                    identities[key] = (group, hashed); row['source_records'] += 1
            except StorageError as exc:
                if exc.storage_code.startswith('VERIFY_'): raise
                row['unreadable_files'] += 1; uncertain = True; error(exc.storage_code)
            except (ijson.JSONError, ValueError, UnicodeError, OSError):
                row['unreadable_files'] += 1; uncertain = True; error('SOURCE_UNREADABLE_OR_INVALID')
        for group, row in counts.items():
            hashed = hashlib.sha256()
            for key in sorted(key for key, value in identities.items() if value[0] == group):
                hashed.update(digest([key, identities[key][1]]).encode())
            row['source_digest'] = hashed.hexdigest()
        source_complete = not uncertain
        database_started = True
        with store.transaction() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            def timeout():
                budget.check()
                millis = max(1, int((budget.deadline - time.monotonic()) * 1000))
                db.execute("SELECT set_config('statement_timeout',%s,true)", (str(millis),))
            timeout()
            # Required storage relations only; do not call migrate/import/startup.
            required = ('records', 'record_extensions', 'row_states', 'outcomes')
            timeout()
            if not db.execute("SELECT to_regnamespace('bist_v6') AS namespace").fetchone()['namespace']:
                raise StorageError('VERIFY_SCHEMA_MISSING')
            for name in required:
                timeout()
                if not db.execute('SELECT to_regclass(%s) AS relation', ('bist_v6.' + name,)).fetchone()['relation']:
                    raise StorageError('VERIFY_TABLE_MISSING')
            for row in counts.values():
                for key in ('pg_total_records', 'pg_unique_records', 'pg_duplicate_records', 'verified_records', 'missing_records', 'mismatched_records'): row[key] = 0
            timeout()
            # Bounded number of dataset aggregates, independent of table row count.
            datasets = db.execute('SELECT dataset,count(*) AS total,count(DISTINCT record_id) AS unique_count FROM bist_v6.records GROUP BY dataset LIMIT %s', (max_files + 1,)).fetchall()
            if len(datasets) > max_files: raise StorageError('VERIFY_DATASET_LIMIT')
            result['pg_unclassified_records'] = 0
            for entry in datasets:
                dataset = entry['dataset']; file_name, separator, field = dataset.partition('#')
                candidate = Path(file_name)
                shape = shape_for(root / candidate, location) if separator and not candidate.is_absolute() and '..' not in candidate.parts else None
                if shape is None or field not in shape.fields:
                    result['pg_unclassified_records'] += entry['total']; continue
                group = category(candidate.name, candidate.parts[:-1])
                if group in counts:
                    counts[group]['pg_total_records'] += entry['total']
                    counts[group]['pg_unique_records'] += entry['unique_count']
                    duplicates = entry['total'] - entry['unique_count']
                    counts[group]['pg_duplicate_records'] += duplicates
                    if duplicates:
                        uncertain = True; error('TARGET_DUPLICATE_ID')
            by_dataset = {}
            for dataset, identity in identities:
                by_dataset.setdefault(dataset, []).append(identity)
            for dataset, ids in by_dataset.items():
                for offset in range(0, len(ids), batch_size):
                    timeout(); batch = ids[offset:offset + batch_size]
                    payload_bytes = 0; payload_rows = 0
                    for table, column in (('records', 'frozen'), ('record_extensions', 'payload'),
                                          ('row_states', 'payload'), ('outcomes', 'payload')):
                        timeout()
                        size = db.execute('SELECT COALESCE(sum(octet_length(' + column + '::text)),0) AS bytes,count(*) AS rows FROM bist_v6.' + table + ' WHERE dataset=%s AND record_id=ANY(%s)', (dataset, batch)).fetchone()
                        payload_bytes += size['bytes']; payload_rows += size['rows']
                        if payload_bytes > 16 * 1024 * 1024 or payload_rows > 10000:
                            raise StorageError('VERIFY_PAYLOAD_LIMIT')
                    class ReadDeadline:
                        def execute(self, query, params=None):
                            timeout()
                            if not query.startswith('SELECT '):
                                raise StorageError('VERIFY_WRITE_FORBIDDEN')
                            return db.execute(query, params)
                    found = store._rows(ReadDeadline(), dataset, batch)
                    budget.check()
                    for identity in batch:
                        group, expected = identities[(dataset, identity)]; row = counts[group]
                        actual = found.get(identity)
                        if actual is None: row['missing_records'] += 1; continue
                        record, extensions, state, outcomes = actual
                        reconstructed = assemble(record['frozen'], extensions, state, outcomes)
                        actual_hash = digest(reconstructed)
                        if actual_hash == expected and digest(record['frozen']) == record['frozen_hash'] and actual_hash == record['current_hash']:
                            row['verified_records'] += 1
                        else: row['mismatched_records'] += 1
        database_complete = True
    except StorageError as exc:
        uncertain = True; error(exc.storage_code)
        db_failed = database_started and exc.storage_code not in ('VERIFY_TIME_LIMIT', 'VERIFY_FILE_LIMIT', 'VERIFY_BYTE_LIMIT', 'VERIFY_RECORD_LIMIT', 'VERIFY_DEPTH_LIMIT', 'VERIFY_SOURCE_SYMLINK', 'VERIFY_PAYLOAD_LIMIT')
    except Exception:
        uncertain = True; db_failed = database_started; error('VERIFY_UNAVAILABLE')
    finally:
        if manifest is not None:
            try:
                if discover(root, budget, max_files) != manifest:
                    result['source_changed'] = True; uncertain = True; error('SOURCE_CHANGED')
                    source_complete = False
            except Exception:
                uncertain = True; error('SOURCE_FINAL_CHECK_UNAVAILABLE')
                source_complete = False
    source = sum(row['source_records'] for row in counts.values())
    verified = sum(row['verified_records'] or 0 for row in counts.values())
    missing = sum(row['missing_records'] or 0 for row in counts.values())
    mismatched = sum(row['mismatched_records'] or 0 for row in counts.values())
    if not database_complete:
        # Partial database observations must not masquerade as a completed count.
        for row in counts.values():
            for key in ('pg_total_records', 'pg_unique_records', 'pg_duplicate_records', 'verified_records', 'missing_records', 'mismatched_records'): row[key] = None
    if db_failed: result['status'] = 'FAILED'
    elif uncertain or not source or not source_snapshot or not database_complete:
        result['status'] = 'INCONCLUSIVE'
    elif verified == source and missing == 0 and mismatched == 0:
        result['status'] = 'VERIFIED'; result['completion_proven'] = True
    elif verified == 0 and missing == source:
        result['status'] = 'NOT_STARTED'
    else:
        result['status'] = 'PARTIAL'
    for row in counts.values():
        row['unreadable_records'] = None if row['unreadable_files'] else 0
        if not uncertain and source_snapshot and row['source_records']:
            row['progress_percent'] = round(row['verified_records'] / row['source_records'] * 100, 2)
    result['source_records'] = source
    result['database_counts_complete'] = database_complete
    result['source_counts_complete'] = source_complete
    result['verified_records'] = verified if database_complete else None
    result['missing_records'] = missing if database_complete else None
    result['progress_percent'] = round(verified / source * 100, 2) if source and not uncertain and source_snapshot else None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only V6 migration evidence; never imports or switches backend')
    parser.add_argument('--root', required=True)
    parser.add_argument('--consistent-source-snapshot', action='store_true', help='Operator declaration of separately verified consistent snapshot')
    parser.add_argument('--max-seconds', type=float, default=300)
    parser.add_argument('--max-records', type=int, default=100000)
    parser.add_argument('--max-files', type=int, default=10000)
    args = parser.parse_args(argv); store = None; pool_filter = None
    try:
        from .schema_diagnostics import PoolDiagnosticsFilter
        pool_filter = PoolDiagnosticsFilter(); logging.getLogger('psycopg.pool').addFilter(pool_filter)
        from .postgres import PostgresStore
        store = PostgresStore()
        value = verify(args.root, store, source_snapshot=args.consistent_source_snapshot,
                       max_seconds=args.max_seconds, max_records=args.max_records, max_files=args.max_files)
    except Exception as exc:
        value = {'status': 'FAILED', 'error_code': getattr(exc, 'storage_code', 'VERIFY_CONNECTION_UNAVAILABLE'), 'progress_percent': None, 'read_only': True}
    finally:
        try:
            if store: store.close()
        except Exception: pass
        if pool_filter: logging.getLogger('psycopg.pool').removeFilter(pool_filter)
    print('[V6_MIGRATION_VERIFY] ' + json.dumps(value, sort_keys=True), flush=True)
    return 0 if value['status'] == 'VERIFIED' else 2


if __name__ == '__main__': raise SystemExit(main())
