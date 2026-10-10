import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from v6_storage.config import StorageError
from v6_storage.migration import checksum
from v6_storage.records import digest
from v6_storage import tree_transfer as transfer


class MemoryStore:
    def __init__(self):
        self.rows = {}; self.cursors = {}; self.documents = {}; self.conflict = False
        self.sql = []; self.batches = []; self.disconnected = False
    def ready(self): pass
    def import_cursor(self, source, field): return self.cursors.get((source, field), 0)
    def put_rows(self, dataset, batch, kind, receipt, **kwargs):
        self.batches.append(len(batch))
        if self.disconnected: raise StorageError('POSTGRES_OPERATION_FAILED')
        if not self.conflict:
            self.rows.setdefault(dataset, {}).update(copy.deepcopy(dict(batch)))
        self.cursors[(receipt['source_id'], receipt['field'])] = receipt['position']
        return SimpleNamespace(conflicts=int(self.conflict))
    def import_conflicts(self, source): return self.conflict
    def publish_document(self, shape, meta, *args, **kwargs):
        self.documents[shape.dataset] = {'metadata': meta, 'collections': shape.fields}
    def finish_import(self, *args): pass
    @contextlib.contextmanager
    def transaction(self):
        owner = self
        class DB:
            def execute(self, sql, params=None):
                owner.sql.append(sql)
                if sql.startswith('SET '): row = None
                elif 'pg_database_size' in sql: row = {'bytes': 1}
                elif 'FROM bist_v6.documents' in sql: row = owner.documents.get(params[0])
                elif 'count(*)' in sql: row = {'count': len(owner.rows.get(params[0], {}))}
                else: raise AssertionError('Unexpected query')
                return SimpleNamespace(fetchone=lambda: row)
        yield DB()
    def _rows(self, db, dataset, ids):
        result = {}
        for key in ids:
            if key in self.rows.get(dataset, {}):
                row = self.rows[dataset][key]
                result[key] = ({'frozen': row, 'frozen_hash': digest(row), 'current_hash': digest(row)}, {}, {}, {})
        return result


class TreeTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'source'; self.root.mkdir()
        self.work = base / 'external'; self.work.mkdir(mode=0o700)
        runtime = self.root / 'runtime'; runtime.mkdir()
        self.source = runtime / 'ai_ogrenme_gecmisi.json'
        self.source.write_text(json.dumps({'kayitlar': [{'kayit_id': str(i), 'fiyat': 10} for i in range(7)]}))
        self.before = transfer.census(self.root)
        self.store = MemoryStore()

    def call(self, phase='prepare', **kwargs):
        return transfer.coordinate(self.root, self.work, phase, True, True, True,
                                   self.store, self.store, **kwargs)

    @contextlib.contextmanager
    def remote_fakes(self):
        def backup(path, **kwargs):
            Path(path).write_bytes(b'FAKE OFFLINE ARCHIVE')
            return {'sha256': checksum(path)}
        with patch.object(transfer, 'create_backup', side_effect=backup), \
             patch.object(transfer, 'inspect_backup', return_value={}), \
             patch.object(transfer, 'restore_rehearsal', return_value={'restored': True}), \
             patch.object(transfer, 'database_signature', return_value='offline-equal'):
            yield

    def prepare(self):
        with self.remote_fakes(): return self.call()

    def test_dry_run_no_clients_no_files(self):
        before = set(self.work.iterdir())
        with patch('v6_storage.postgres.PostgresStore', side_effect=AssertionError('Client')):
            result = transfer.coordinate(self.root)
        self.assertEqual(result['supported_files'], 1)
        self.assertEqual(set(self.work.iterdir()), before)
        self.assertEqual(transfer.census(self.root), self.before)

    def test_prepare_copies_all_bytes_and_rehearses_outside_source(self):
        result = self.prepare()
        self.assertEqual(result['status'], 'PREPARED_REQUIRES_SEPARATE_IMPORT_APPROVAL')
        self.assertEqual(transfer.census(self.work / 'backup'), self.before)
        self.assertEqual(transfer.census(self.work / 'rehearsal'), self.before)
        self.assertEqual(transfer.census(self.root), self.before)
        self.assertFalse(self.store.rows)

    def test_import_real_streaming_migrator_and_equality(self):
        self.prepare()
        with self.remote_fakes(): result = self.call('import')
        self.assertEqual(result['status'], 'VERIFIED_NO_CUTOVER')
        self.assertEqual(result['imported'], 1)
        self.assertEqual(len(self.store.rows['runtime/ai_ogrenme_gecmisi.json#kayitlar']), 7)
        self.assertEqual(transfer.census(self.root), self.before)
        self.assertTrue(all(query.startswith(('SELECT ', 'SET ')) for query in self.store.sql))

    def test_idempotent_rerun(self):
        self.prepare()
        with self.remote_fakes():
            self.call('import'); self.call('import')
        self.assertEqual(len(next(iter(self.store.rows.values()))), 7)

    def test_temp_recovery_unknown_kept_unresolved(self):
        for name in ('.user-unique.tmp', 'recovery.wal', 'unknown.bin'):
            (self.root / name).write_bytes(b'UNIQUE PRIVATE BYTES')
        before = transfer.census(self.root); self.prepare()
        with self.remote_fakes(): result = self.call('import')
        self.assertEqual(result['status'], 'UNRESOLVED'); self.assertEqual(result['unresolved'], 3)
        self.assertEqual(result['imported'], 1)
        self.assertEqual(transfer.census(self.root), before)
        self.assertEqual(transfer.census(self.work / 'backup'), before)
        self.assertEqual(len(result['reasons']), 3)

    def test_conflict_preserved_never_success(self):
        self.prepare(); self.store.conflict = True
        with self.remote_fakes(): result = self.call('import')
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertFalse(self.store.rows)
        self.assertEqual(transfer.census(self.root), self.before)

    def test_disconnect_then_resume(self):
        self.prepare(); self.store.disconnected = True
        with self.remote_fakes(): result = self.call('import')
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.store.disconnected = False
        with self.remote_fakes(): result = self.call('import')
        self.assertEqual(result['status'], 'VERIFIED_NO_CUTOVER')

    def test_budget_resume_bounded_batches(self):
        self.source.write_text(json.dumps({'kayitlar': [{'kayit_id': str(i)} for i in range(207)]}))
        self.prepare()
        with self.remote_fakes():
            self.assertEqual(self.call('import', budget_records=100)['status'], 'BUDGET_EXHAUSTED')
            self.assertEqual(self.call('import', budget_records=100)['status'], 'BUDGET_EXHAUSTED')
            self.assertEqual(self.call('import', budget_records=100)['status'], 'VERIFIED_NO_CUTOVER')
        self.assertEqual(len(next(iter(self.store.rows.values()))), 207)
        self.assertLessEqual(max(self.store.batches), 100)

    def test_source_change_fail_closed_before_import(self):
        self.prepare(); self.source.write_text('{}')
        with self.assertRaises(StorageError): self.call('import')
        self.assertFalse(self.store.rows)

    def test_rehearsal_checksum_corruption(self):
        self.prepare(); (self.work / 'rehearsal/runtime/ai_ogrenme_gecmisi.json').write_text('{}')
        with self.remote_fakes(), self.assertRaises(StorageError): self.call('import')
        self.assertFalse(self.store.rows)

    def test_missing_gate(self):
        with self.assertRaises(StorageError):
            transfer.coordinate(self.root, self.work, apply=True)
        self.assertFalse(list(self.work.iterdir()))

    def test_missing_external_confirmation(self):
        with self.assertRaises(StorageError):
            transfer.coordinate(self.root, self.work, apply=True, quiescent=True)

    def test_unprepared_import(self):
        with self.assertRaises(StorageError): self.call('import')
        self.assertFalse(self.store.rows)

    def test_source_workspace_rejected(self):
        with self.assertRaises(StorageError): transfer.external(self.root / 'backup', self.root)

    def test_symlink_source_not_followed(self):
        (self.root / 'secret-link').symlink_to(self.source)
        with self.assertRaises(StorageError): self.call()
        self.assertEqual(transfer.census(self.root)['exceptional'], 1)

    def test_symlink_backup_component_rejected(self):
        (self.work / 'backup').symlink_to(self.root)
        with self.assertRaises(StorageError): self.call()
        self.assertEqual(transfer.census(self.root), self.before)

    def test_partial_backup_resumes_prefix(self):
        target = self.work / 'partial'; target.write_bytes(self.source.read_bytes()[:10])
        row = self.before['files'][0]
        transfer.copy_checked(self.source, target, row)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())

    def test_partial_mismatch_not_overwritten(self):
        target = self.work / 'partial'; target.write_bytes(b'BAD')
        with self.assertRaises(StorageError): transfer.copy_checked(self.source, target, self.before['files'][0])
        self.assertEqual(target.read_bytes(), b'BAD')

    def test_low_disk_before_big_copy(self):
        with patch.object(transfer.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)), self.assertRaises(StorageError): self.call()
        self.assertFalse((self.work / 'backup').exists())

    def test_invalid_json_reported_without_guessing(self):
        self.source.write_text('{broken'); self.prepare()
        with self.remote_fakes(): result = self.call('import')
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIn('SOURCE_JSON_INVALID', result['reasons'])

    def test_duplicate_identity_rejected(self):
        self.source.write_text(json.dumps({'kayitlar': [{'kayit_id': 'same'}, {'kayit_id': 'same'}]})); self.prepare()
        with self.remote_fakes(): result = self.call('import')
        self.assertIn('SOURCE_DUPLICATE_ID', result['reasons']); self.assertFalse(self.store.rows)

    def test_record_cap_fail_closed(self):
        self.prepare()
        with self.remote_fakes(): result = self.call('import', max_records=2)
        self.assertEqual(result['status'], 'UNRESOLVED'); self.assertFalse(self.store.rows)

    def test_file_budget(self):
        with self.assertRaises(StorageError): transfer.census(self.root, 1)

    def test_console_no_private_paths_or_contents(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(transfer.main(['--root', str(self.root)]), 0)
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertNotIn('kayit_id', output.getvalue())
        self.assertNotIn(self.source.name, output.getvalue())

    def test_exception_message_not_logged(self):
        with patch.object(transfer, 'census', side_effect=ValueError('postgres://SECRET')), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(transfer.main(['--root', str(self.root)]), 2)
        self.assertNotIn('SECRET', output.getvalue())

    def test_single_operator_lock(self):
        import fcntl
        with (self.work / 'operator.lock').open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(StorageError) as error: self.call()
        self.assertEqual(error.exception.storage_code, 'TRANSFER_OPERATOR_BUSY')

    def test_db_backup_mismatch_not_prepared(self):
        with self.remote_fakes(), patch.object(transfer, 'database_signature', side_effect=('original', 'different')), self.assertRaises(StorageError): self.call()
        self.assertFalse(transfer.read_manifest(self.work / 'transfer.json').get('prepared'))

    def test_backend_untouched(self):
        with patch.dict(os.environ, {'STORAGE_BACKEND': 'legacy'}):
            self.prepare()
            with self.remote_fakes(): self.call('import')
            self.assertEqual(os.environ['STORAGE_BACKEND'], 'legacy')

    def test_partial_database_backup_not_overwritten(self):
        (self.work / 'postgres.dump').write_bytes(b'PARTIAL UNIQUE')
        with self.remote_fakes(), self.assertRaises(StorageError) as error: self.call()
        self.assertEqual(error.exception.storage_code, 'DATABASE_PARTIAL_BACKUP_PRESERVED')
        self.assertEqual((self.work / 'postgres.dump').read_bytes(), b'PARTIAL UNIQUE')

    def test_changed_during_backup_not_prepared(self):
        real = transfer.copy_checked
        def racing(source, target, row):
            real(source, target, row)
            if Path(source) == self.source: self.source.write_text('{}')
        with self.remote_fakes(), patch.object(transfer, 'copy_checked', side_effect=racing), self.assertRaises(StorageError): self.call()
        self.assertFalse(transfer.read_manifest(self.work / 'transfer.json').get('prepared'))

    def test_failed_restore_resumes_only_empty_isolated_target(self):
        with self.remote_fakes(), patch.object(transfer, 'restore_rehearsal', side_effect=StorageError('RESTORE_REHEARSAL_FAILED')), self.assertRaises(StorageError): self.call()
        with self.remote_fakes(), patch.object(transfer, 'isolated_empty', return_value=True), patch.object(transfer, 'restore_rehearsal', return_value={}) as restore:
            self.call(); restore.assert_called_once()

    def test_destination_mismatch_not_success(self):
        self.prepare()
        with self.remote_fakes(), patch.object(transfer, 'compare_source', return_value={'status': 'MISMATCH'}): result = self.call('import')
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIn('DESTINATION_EQUALITY_FAILED', result['reasons'])

    def test_checkpoint_private_and_no_big_temporary_copy(self):
        self.prepare()
        self.assertEqual((self.work / 'transfer.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.work / 'transfer.next').exists())
        self.assertFalse(any(path.suffix == '.next' for path in self.root.rglob('*')))

    def test_empty_source_tree_preserved(self):
        self.source.unlink(); self.source.parent.rmdir()
        result = self.prepare()
        self.assertEqual(result['files'], 0)
        self.assertTrue((self.work / 'backup').is_dir())

    def test_database_signature_read_only_streamed_and_order_independent(self):
        queries = []
        class Rows:
            def __init__(self, rows): self.rows = rows
            def fetchmany(self, limit):
                rows = self.rows[:limit]; self.rows = self.rows[limit:]; return rows
            def fetchall(self): return self.rows
        class DB:
            def __init__(self, rows): self.rows = rows
            def execute(self, query):
                queries.append(query)
                if query.startswith('SET '): return Rows([])
                if 'information_schema.columns' in query:
                    return Rows([{'table_schema': 'bist_v6', 'table_name': 'records', 'column_name': 'id'}])
                return Rows([{'namespace': 'bist_v6', 'name': 'records'}])
            @contextlib.contextmanager
            def cursor(self, name):
                rows = Rows([{'value': row} for row in self.rows])
                rows.execute = lambda query: queries.append(str(query))
                yield rows
        class Store:
            def __init__(self, rows): self.db = DB(rows)
            def transaction(self): return contextlib.nullcontext(self.db)
        first = transfer.database_signature(Store([{'id': 1}, {'id': 2}]))
        second = transfer.database_signature(Store([{'id': 2}, {'id': 1}]))
        third = transfer.database_signature(Store([{'id': 1}, {'id': 3}]))
        self.assertEqual(first, second); self.assertNotEqual(first, third)
        self.assertEqual(len(first), 64)
        self.assertTrue(any('READ ONLY' in query for query in queries))
        self.assertFalse(any(query.startswith(('INSERT ', 'UPDATE ', 'CREATE ', 'DELETE ')) for query in queries))


if __name__ == '__main__': unittest.main()
