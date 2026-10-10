"""Explicit, bounded V6 transfer coordinator. Never switches backend or deletes.

Source/backup/restore identities are private; console output contains counts only.
Preparation and import require separate explicit invocations and operator approval.
"""
import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import stat

from .config import Settings, StorageError
from .migration import Migrator, checksum, fingerprint
from .migration_safety import compare_source, create_backup, restore_rehearsal, inspect_backup
from .records import digest, shape_for
from .readonly_inventory import category

CHUNK = 1024 * 1024
MAX_FILES = 10000
MAX_MANIFEST = 16 * CHUNK


def fail(code):
    raise StorageError(code)


def external(path, root):
    """Reject symlink components and nested/source storage, including /data."""
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            fail('TRANSFER_SYMLINK_FORBIDDEN')
    source = Path(root).resolve()
    if path == source or path.is_relative_to(source) or source.is_relative_to(path):
        fail('TRANSFER_EXTERNAL_STORAGE_REQUIRED')
    if path == Path('/data') or path.is_relative_to('/data'):
        fail('TRANSFER_EXTERNAL_STORAGE_REQUIRED')
    return path


def census(root, max_files=MAX_FILES):
    """Hash all regular files without guessing temp/recovery semantics."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        fail('SOURCE_ROOT_INVALID')
    if not 1 <= max_files <= MAX_FILES:
        fail('TRANSFER_BUDGET_INVALID')
    rows = []; directories = []; exceptional = 0
    def walk(folder, depth=0):
        nonlocal exceptional
        if depth > 64:
            fail('TRANSFER_DEPTH_LIMIT')
        with os.scandir(folder) as entries:
            for entry in entries:
                relative = Path(entry.path).relative_to(root).as_posix()
                st = entry.stat(follow_symlinks=False)
                if len(rows) + len(directories) + exceptional >= max_files:
                    fail('TRANSFER_FILE_LIMIT')
                if stat.S_ISDIR(st.st_mode):
                    directories.append(relative); walk(Path(entry.path), depth + 1)
                elif stat.S_ISREG(st.st_mode):
                    before = fingerprint(entry.path)
                    hashed = checksum(entry.path)
                    if fingerprint(entry.path) != before:
                        fail('SOURCE_CHANGED')
                    rows.append({'path': relative, 'size': st.st_size, 'sha256': hashed,
                                 'category': category(entry.name, Path(relative).parts)})
                else:
                    # Links/devices cannot be treated as complete backups.
                    exceptional += 1
    walk(root)
    rows.sort(key=lambda row: row['path']); directories.sort()
    value = {'files': rows, 'directories': directories, 'exceptional': exceptional}
    value['tree_hash'] = digest(value)
    return value


def read_manifest(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_MANIFEST:
        fail('TRANSFER_MANIFEST_INVALID')
    with path.open() as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        fail('TRANSFER_MANIFEST_INVALID')
    return value


def save_manifest(path, value):
    """One bounded private checkpoint; no large source-sized temporary copies."""
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if len(raw) > MAX_MANIFEST:
        fail('TRANSFER_MANIFEST_LIMIT')
    path = Path(path); temporary = path.with_suffix('.next')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except BaseException:
        # Keep interrupted checkpoint for inspection; never remove source/recovery files.
        raise


def copy_checked(source, target, expected):
    """Resume only an exact prefix. Conflicting backup bytes are never overwritten."""
    source = Path(source); target = Path(target)
    if target.is_symlink():
        fail('TRANSFER_SYMLINK_FORBIDDEN')
    before = fingerprint(source)
    if before['size'] != expected['size'] or checksum(source) != expected['sha256']:
        fail('SOURCE_CHANGED')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    offset = target.stat().st_size if target.exists() else 0
    if offset > expected['size']:
        fail('BACKUP_PREFIX_MISMATCH')
    with source.open('rb') as incoming:
        if offset:
            with target.open('rb') as saved:
                left = offset
                while left:
                    block = min(CHUNK, left)
                    if incoming.read(block) != saved.read(block):
                        fail('BACKUP_PREFIX_MISMATCH')
                    left -= block
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab') as saved:
            while block := incoming.read(CHUNK): saved.write(block)
            saved.flush(); os.fsync(saved.fileno())
    if fingerprint(source) != before or checksum(target) != expected['sha256']:
        fail('BACKUP_CHECKSUM_MISMATCH')


def database_signature(store):
    """Bounded, read-only full user-table signature; no row values leave memory."""
    from psycopg import sql
    schema = []
    with store.transaction() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor = db.execute("SELECT table_schema,table_name,column_name,ordinal_position,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_schema,table_name,ordinal_position")
        while batch := cursor.fetchmany(100):
            schema.extend(batch)
            if len(schema) > 10000: fail('DATABASE_SCHEMA_BUDGET')
        # Exclude views: pg_dump restores definitions, not view-query results.
        relations = db.execute("SELECT n.nspname AS namespace,c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','m') AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' LIMIT 10001").fetchall()
        if len(relations) > 10000: fail('DATABASE_SCHEMA_BUDGET')
        summaries = []
        for number, row in enumerate(relations):
            count = 0; total = 0; xor = 0
            with db.cursor(name='v6_backup_' + str(number)) as stream:
                stream.execute(sql.SQL('SELECT row_to_json(t) AS value FROM {}.{} AS t').format(sql.Identifier(row['namespace']), sql.Identifier(row['name'])))
                while batch := stream.fetchmany(100):
                    for item in batch:
                        value = int(digest(item['value']), 16); count += 1; total = (total + value) % (1 << 256); xor ^= value
            summaries.append((row['namespace'], row['name'], count, total, xor))
    # Comparison aid, not an automatic cutover approval or proof of every SQL object.
    return digest({'columns': schema, 'tables': sorted(summaries)})


def isolated_empty(store):
    with store.transaction() as db:
        db.execute('SET TRANSACTION READ ONLY')
        row = db.execute("SELECT count(*) AS count FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'").fetchone()
        return row['count'] == 0


def summary(tree):
    categories = {}
    for row in tree['files']:
        group = categories.setdefault(row['category'], {'files': 0, 'bytes': 0})
        group['files'] += 1; group['bytes'] += row['size']
    return {'files': len(tree['files']), 'bytes': sum(row['size'] for row in tree['files']),
            'exceptional': tree['exceptional'], 'categories': categories}


def coordinate(root, workspace=None, phase='prepare', apply=False, quiescent=False,
               external_confirmed=False, store=None, isolated_store=None, max_files=MAX_FILES,
               max_records=100000, budget_records=None, progress=None):
    """One entrypoint, explicit backup rehearsal gate, no automatic cutover.

    Quiescence/storage confirmation is an operator prerequisite, not a claim that
    this tool has stopped live writers or provisioned durable storage.
    """
    from veri_yollari import DataPaths
    root = Path(root).absolute()
    if not 1 <= max_records <= 1000000 or budget_records is not None and budget_records < 1:
        fail('TRANSFER_BUDGET_INVALID')
    tree = census(root, max_files)
    result = dict(summary(tree), mode='APPLY' if apply else 'DRY_RUN', status='DRY_RUN',
                  source_changed=False, backend_changed=False, unresolved=0, imported=0,
                  reasons={})
    if not apply:
        location = DataPaths({'BIST_DATA_DIR': str(root)})
        result['supported_files'] = sum(shape_for(root / row['path'], location) is not None for row in tree['files'])
        result['unresolved'] = len(tree['files']) - result['supported_files'] + tree['exceptional']
        return result
    if phase not in ('prepare', 'import'): fail('TRANSFER_PHASE_INVALID')
    if not quiescent: fail('SOURCE_QUIESCENCE_REQUIRED')
    if not external_confirmed: fail('DURABLE_EXTERNAL_STORAGE_REQUIRED')
    if not workspace: fail('TRANSFER_WORKSPACE_REQUIRED')
    work = external(workspace, root)
    if tree['exceptional']: fail('SOURCE_NONREGULAR_UNRESOLVED')
    if not work.is_dir(): fail('PRIVATE_WORKSPACE_PRECREATE_REQUIRED')
    if work.stat().st_mode & 0o077: fail('PRIVATE_WORKSPACE_PERMISSIONS_REQUIRED')
    lock = os.open(work / 'operator.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: fail('TRANSFER_OPERATOR_BUSY')
        return _locked(root, work, tree, result, phase, store, isolated_store,
                       max_files, max_records, budget_records, progress)
    finally:
        os.close(lock)


def _locked(root, work, tree, result, phase, store, isolated_store, max_files,
            max_records, budget_records, progress):
    from veri_yollari import DataPaths
    manifest = work / 'transfer.json'
    state = read_manifest(manifest) if manifest.exists() else {'version': 1, 'tree': tree, 'verified': {}}
    if state.get('version') != 1 or state.get('tree') != tree:
        fail('SOURCE_CHANGED_OR_DIFFERENT_TRANSFER')
    if phase == 'prepare':
        # Separate durable volume required; capacity includes two independent tree copies.
        needed = 0
        for row in tree['files']:
            for name in ('backup', 'rehearsal'):
                target = external(work / name / row['path'], root)
                existing = target.stat().st_size if target.exists() else 0
                needed += max(0, row['size'] - existing)
        if shutil.disk_usage(work).free < needed + 64 * CHUNK:
            fail('EXTERNAL_BACKUP_SPACE_INSUFFICIENT')
        save_manifest(manifest, state)
        for name in ('backup', 'rehearsal'):
            external(work / name, root).mkdir(mode=0o700, exist_ok=True)
        for directory in tree['directories']:
            for name in ('backup', 'rehearsal'):
                (work / name / directory).mkdir(parents=True, mode=0o700, exist_ok=True)
        for index, row in enumerate(tree['files']):
            source = root / row['path']
            backup = work / 'backup' / row['path']; restored = work / 'rehearsal' / row['path']
            # Reject symlink parents on every resume, not just the workspace root.
            external(backup, root); external(restored, root)
            copy_checked(source, backup, row); copy_checked(backup, restored, row)
            if progress: progress({'stage': 'DATA_BACKUP_REHEARSAL', 'completed': index + 1, 'files': len(tree['files'])})
        if census(work / 'backup', max_files) != tree or census(work / 'rehearsal', max_files) != tree or census(root, max_files) != tree:
            fail('DATA_RESTORE_EQUALITY_FAILED')
        if store is None or isolated_store is None: fail('DATABASE_BACKUP_CLIENTS_REQUIRED')
        store.ready()
        # Empty isolated restore must be supplied by operator; restore function checks it.
        backup = work / 'postgres.dump'
        if backup.exists() and not state.get('pg_sha256'):
            fail('DATABASE_PARTIAL_BACKUP_PRESERVED')
        if not state.get('pg_sha256'):
            with store.transaction() as db:
                db.execute('SET TRANSACTION READ ONLY')
                size = db.execute('SELECT pg_database_size(current_database()) AS bytes').fetchone()['bytes']
            if shutil.disk_usage(work).free < size * 2 + 64 * CHUNK:
                fail('EXTERNAL_DATABASE_BACKUP_SPACE_INSUFFICIENT')
            state['pg_sha256'] = create_backup(backup, apply=True)['sha256']; save_manifest(manifest, state)
        inspect_backup(backup, state['pg_sha256'])
        if not state.get('db_restore_started') or isolated_empty(isolated_store):
            state['db_restore_started'] = True; save_manifest(manifest, state)
            restore_rehearsal(backup, state['pg_sha256'], apply=True)
        isolated_store.ready()
        before = database_signature(store); restored = database_signature(isolated_store)
        if before != restored: fail('DATABASE_RESTORE_EQUALITY_FAILED')
        state['db_signature'] = before; state['db_rehearsal'] = True
        state['prepared'] = True; save_manifest(manifest, state)
        result['status'] = 'PREPARED_REQUIRES_SEPARATE_IMPORT_APPROVAL'
        return result
    if not state.get('prepared') or not state.get('db_rehearsal'):
        fail('VERIFIED_BACKUP_REHEARSAL_REQUIRED')
    inspect_backup(work / 'postgres.dump', state['pg_sha256'])
    if census(work / 'backup', max_files) != tree or census(work / 'rehearsal', max_files) != tree:
        fail('DATA_RESTORE_EQUALITY_FAILED')
    if store is None: fail('POSTGRES_NOT_CONFIGURED')
    store.ready()
    # Validate all prospective files before writing any import batches.
    location = DataPaths({'BIST_DATA_DIR': str(root)})
    plans = []
    def unresolved(row, code):
        result['unresolved'] += 1
        result['reasons'][code] = result['reasons'].get(code, 0) + 1
        state.setdefault('unresolved', {})[row['path']] = code
    for row in tree['files']:
        shape = shape_for(root / row['path'], location)
        if shape is None:
            unresolved(row, 'ARCHIVED_UNSUPPORTED_' + row['category'].upper())
            continue
        check = Migrator(batch_size=100).run(root / row['path'], shape,
                                               max_records=max_records)
        if check['status'] != 'VERIFIED':
            unresolved(row, check.get('error', 'SOURCE_RECORD_BUDGET_EXHAUSTED'))
            continue
        plans.append((row, shape))
    if census(root, max_files) != tree: fail('SOURCE_CHANGED')
    for index, (row, shape) in enumerate(plans):
        # Import immutable, independently restored bytes rather than live writer paths.
        source = work / 'rehearsal' / row['path']
        report = Migrator(store, batch_size=100).run(source, shape, True, budget_records,
                                                    max_records=max_records)
        if report['status'] == 'VERIFIED':
            equality = compare_source(source, shape, store, max_records=max_records)
            if equality['status'] == 'VERIFIED':
                state['verified'][row['path']] = row['sha256']; result['imported'] += 1
                state.setdefault('unresolved', {}).pop(row['path'], None)
            else: unresolved(row, 'DESTINATION_EQUALITY_FAILED')
        else:
            unresolved(row, report.get('error', 'IMPORT_' + report['status']))
            if report['status'] == 'BUDGET_EXHAUSTED':
                save_manifest(manifest, state); result['status'] = 'BUDGET_EXHAUSTED'; return result
        save_manifest(manifest, state)
        if progress: progress({'stage': 'IMPORT_VERIFY', 'completed': index + 1, 'files': len(plans), 'unresolved': result['unresolved']})
    if census(root, max_files) != tree: fail('SOURCE_CHANGED')
    result['status'] = 'UNRESOLVED' if result['unresolved'] else 'VERIFIED_NO_CUTOVER'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='V6 tree transfer; DRY_RUN by default, no backend cutover')
    parser.add_argument('--root', required=True); parser.add_argument('--workspace')
    parser.add_argument('--phase', choices=('prepare', 'import'), default='prepare')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-quiescent', action='store_true')
    parser.add_argument('--durable-external-storage', action='store_true')
    parser.add_argument('--max-records', type=int, default=100000)
    parser.add_argument('--budget-records', type=int)
    args = parser.parse_args(argv); stores = []; pool_filter = None
    try:
        store = isolated = None
        # No client or connection attempt in dry-run. Early gates precede DB access.
        if args.apply:
            if not args.writers_quiescent: fail('SOURCE_QUIESCENCE_REQUIRED')
            if not args.durable_external_storage: fail('DURABLE_EXTERNAL_STORAGE_REQUIRED')
            if not args.workspace: fail('TRANSFER_WORKSPACE_REQUIRED')
            external(args.workspace, args.root)
            from .schema_diagnostics import PoolDiagnosticsFilter
            pool_filter = PoolDiagnosticsFilter()
            logging.getLogger('psycopg.pool').addFilter(pool_filter)
            from .postgres import PostgresStore
            store = PostgresStore(Settings.from_env()); stores.append(store)
            if args.phase == 'prepare':
                settings = Settings(dsn=os.environ.get('V6_RESTORE_DSN', ''))
                settings.require_database()
                isolated = PostgresStore(settings); stores.append(isolated)
        result = coordinate(args.root, args.workspace, args.phase, args.apply,
                            args.writers_quiescent, args.durable_external_storage,
                            store, isolated, max_records=args.max_records,
                            budget_records=args.budget_records,
                            progress=lambda row: print('[V6_TRANSFER] ' + json.dumps(row), flush=True))
        print('[V6_TRANSFER] ' + json.dumps(result, sort_keys=True))
        return 0 if result['status'] in ('DRY_RUN', 'PREPARED_REQUIRES_SEPARATE_IMPORT_APPROVAL', 'VERIFIED_NO_CUTOVER') else 2
    except Exception as error:
        code = error.storage_code if isinstance(error, StorageError) else 'TRANSFER_UNAVAILABLE'
        print('[V6_TRANSFER] ' + json.dumps({'status': 'UNRESOLVED', 'error_code': code}))
        return 2
    finally:
        try:
            for store in stores: store.close()
        finally:
            if pool_filter:
                logging.getLogger('psycopg.pool').removeFilter(pool_filter)


if __name__ == '__main__':
    raise SystemExit(main())
