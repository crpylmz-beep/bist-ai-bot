import contextlib
import copy
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from v6_storage.config import StorageError
from v6_storage.records import digest
from v6_storage import migration_verify as module


class Store:
    def __init__(self, rows, *, missing_schema=False, missing_table=False, fail=False, corrupt=False, duplicate=False, huge_payload=False):
        self.rows = rows; self.missing_schema = missing_schema; self.fail = fail
        self.corrupt = corrupt; self.queries = []; self.after_read = None
        self.missing_table = missing_table
        self.duplicate = duplicate
        self.huge_payload = huge_payload
    @contextlib.contextmanager
    def transaction(self):
        if self.fail: raise StorageError('POSTGRES_OPERATION_FAILED')
        owner = self
        class DB:
            def execute(self, query, params=None):
                owner.queries.append(query)
                assert query.startswith(('SELECT ', 'SET TRANSACTION ')), query
                if 'to_regnamespace' in query: rows = [{'namespace': None if owner.missing_schema else 'present'}]
                elif 'to_regclass' in query: rows = [{'relation': None if owner.missing_table else 'present'}]
                elif 'GROUP BY dataset' in query:
                    rows = [{'dataset': dataset, 'total': len(records) + int(owner.duplicate), 'unique_count': len(records)} for dataset, records in owner.rows.items()]
                elif 'octet_length' in query: rows = [{'bytes': 17 * 1024**2 if owner.huge_payload else 1, 'rows': 1}]
                else: rows = []
                return SimpleNamespace(fetchone=lambda: rows[0], fetchall=lambda: rows)
        yield DB()
    def _rows(self, db, dataset, ids):
        assert len(ids) <= 100
        found = {}
        for identity in ids:
            if identity not in self.rows.get(dataset, {}): continue
            row = copy.deepcopy(self.rows[dataset][identity])
            found[identity] = ({'frozen': row, 'frozen_hash': digest(row), 'current_hash': 'invalid' if self.corrupt else digest(row)}, {}, {}, {})
        if self.after_read: self.after_read()
        return found


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / 'runtime').mkdir()
        self.source = self.root / 'runtime/ai_ogrenme_gecmisi.json'
        self.records = [{'kayit_id': 'a', 'fiyat': 10}, {'kayit_id': 'b', 'fiyat': 11}]
        self.write(self.records)
        self.dataset = 'runtime/ai_ogrenme_gecmisi.json#kayitlar'
    def write(self, rows): self.source.write_text(json.dumps({'surum': 1, 'kayitlar': rows}))
    def store(self, rows=None, **kwargs):
        return Store({self.dataset: {row['kayit_id']: row for row in (self.records if rows is None else rows)}}, **kwargs)
    def check(self, store=None, **kwargs):
        return module.verify(self.root, self.store() if store is None else store,
                             source_snapshot=True, **kwargs)
    def group(self, result): return result['categories']['learning_data']

    def test_complete(self):
        store = self.store(); before = self.source.read_bytes(); result = self.check(store)
        self.assertEqual(result['status'], 'VERIFIED'); self.assertTrue(result['completion_proven'])
        self.assertEqual(result['progress_percent'], 100)
        self.assertEqual(self.group(result)['source_records'], 2)
        self.assertEqual(self.group(result)['pg_total_records'], 2)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertIn('READ ONLY', store.queries[0])
        self.assertEqual(len(list(self.root.rglob('*'))), 2)

    def test_partial(self):
        result = self.check(self.store(self.records[:1]))
        self.assertEqual(result['status'], 'PARTIAL'); self.assertEqual(result['progress_percent'], 50)
        self.assertEqual(result['verified_records'], 1); self.assertEqual(result['missing_records'], 1)

    def test_not_started(self):
        result = self.check(self.store([]))
        self.assertEqual(result['status'], 'NOT_STARTED'); self.assertEqual(result['progress_percent'], 0)

    def test_identical_duplicates_deduplicated(self):
        self.write([*self.records, self.records[0]])
        result = self.check(); row = self.group(result)
        self.assertEqual(result['status'], 'VERIFIED'); self.assertEqual(row['source_records'], 2)
        self.assertEqual(row['duplicate_records'], 1)

    def test_conflicting_duplicates_inconclusive(self):
        self.write([*self.records, {'kayit_id': 'a', 'fiyat': 999}])
        result = self.check()
        self.assertEqual(result['status'], 'INCONCLUSIVE'); self.assertIsNone(result['progress_percent'])
        self.assertEqual(self.group(result)['conflicting_duplicates'], 1)

    def test_broken_json_unreadable_count_unknown(self):
        self.source.write_text('{"kayitlar": [')
        result = self.check(); self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertEqual(self.group(result)['unreadable_files'], 1)
        self.assertIsNone(self.group(result)['unreadable_records'])

    def test_changed_source(self):
        store = self.store(); store.after_read = lambda: self.write(self.records[:1])
        result = self.check(store)
        self.assertEqual(result['status'], 'INCONCLUSIVE'); self.assertTrue(result['source_changed'])

    def test_added_source_during_scan(self):
        store = self.store()
        store.after_read = lambda: (self.root / 'runtime/tahmin_gecmisi.json').write_text('{"tahminler":[]}')
        result = self.check(store); self.assertTrue(result['source_changed'])
        self.assertFalse(result['completion_proven'])

    def test_connection_error(self):
        result = self.check(self.store(fail=True))
        self.assertEqual(result['status'], 'FAILED'); self.assertIsNone(result['verified_records'])
        self.assertIn('POSTGRES_OPERATION_FAILED', result['errors'])

    def test_missing_schema_or_table(self):
        result = self.check(self.store(missing_schema=True))
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('VERIFY_SCHEMA_MISSING', result['errors'])

    def test_missing_table(self):
        result = self.check(self.store(missing_table=True))
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('VERIFY_TABLE_MISSING', result['errors'])

    def test_unmappable_identity(self):
        self.write([{'fiyat': 10}]); result = self.check()
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertEqual(self.group(result)['unmapped_records'], 1)

    def test_content_mismatch(self):
        rows = copy.deepcopy(self.records); rows[0]['fiyat'] = 999
        result = self.check(self.store(rows))
        self.assertEqual(result['status'], 'PARTIAL'); self.assertEqual(result['progress_percent'], 50)
        self.assertEqual(self.group(result)['mismatched_records'], 1)

    def test_database_hash_integrity_error(self):
        result = self.check(self.store(corrupt=True))
        self.assertEqual(result['status'], 'PARTIAL'); self.assertEqual(result['progress_percent'], 0)
        self.assertEqual(self.group(result)['mismatched_records'], 2)

    def test_live_source_cannot_be_verified(self):
        result = module.verify(self.root, self.store())
        self.assertEqual(result['status'], 'INCONCLUSIVE'); self.assertIsNone(result['progress_percent'])
        self.assertEqual(result['verified_records'], 2)

    def test_unsupported_source_no_structural_guess(self):
        (self.root / 'runtime/learning_unknown.json').write_text('{"a":{"b":1}}')
        result = self.check(); self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertEqual(self.group(result)['unsupported_files'], 1)
        self.assertEqual(self.group(result)['source_records'], 2)

    def test_record_limit(self):
        result = self.check(max_records=1)
        self.assertEqual(result['status'], 'INCONCLUSIVE'); self.assertIsNone(result['verified_records'])

    def test_byte_limit(self):
        result = self.check(max_bytes=1)
        self.assertEqual(result['status'], 'INCONCLUSIVE'); self.assertIsNone(result['progress_percent'])

    def test_time_limit(self):
        with patch.object(module.time, 'monotonic', side_effect=[0, 1, 2, 3, 4]):
            result = self.check(max_seconds=0.1)
        self.assertNotEqual(result['status'], 'VERIFIED')

    def test_empty_sources_not_vacuously_verified(self):
        self.write([]); self.assertEqual(self.check()['status'], 'INCONCLUSIVE')

    def test_target_extras_separately_counted(self):
        result = self.check(self.store([*self.records, {'kayit_id': 'extra'}]))
        self.assertEqual(self.group(result)['pg_unique_records'], 3)
        self.assertEqual(result['verified_records'], 2)

    def test_no_personal_content_or_path_in_report(self):
        report = json.dumps(self.check())
        self.assertNotIn(str(self.root), report); self.assertNotIn('fiyat', report)
        self.assertNotIn(self.source.name, report)

    def test_cli_secret_exception_redacted(self):
        with patch('v6_storage.postgres.PostgresStore', side_effect=RuntimeError('postgres://PASSWORD')), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(module.main(['--root', str(self.root)]), 2)
        self.assertNotIn('PASSWORD', output.getvalue())

    def test_mapping_collection(self):
        self.source.unlink()
        source = self.root / 'runtime/yarin_top10_sonuclar.json'
        source.write_text(json.dumps({'sonuclar': {'one': {'fiyat': 10}}}))
        dataset = 'runtime/yarin_top10_sonuclar.json#sonuclar'
        result = self.check(Store({dataset: {'one': {'fiyat': 10}}}))
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertEqual(result['categories']['signal_outcomes']['source_records'], 1)

    def test_nested_structure_is_not_a_record(self):
        self.write([{'kayit_id': 'one', 'criteria': [{'x': 1}, {'x': 2}], 'metadata': {'a': 1}}])
        result = self.check(self.store([{'kayit_id': 'one', 'criteria': [{'x': 1}, {'x': 2}], 'metadata': {'a': 1}}]))
        self.assertEqual(result['source_records'], 1); self.assertEqual(result['status'], 'VERIFIED')

    def test_symlink_directory_not_followed(self):
        (self.root / 'linked').symlink_to(self.root / 'runtime', target_is_directory=True)
        result = self.check()
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertIn('VERIFY_SOURCE_SYMLINK', result['errors'])

    def test_oversized_token_bounded_before_building_record(self):
        self.write([{'kayit_id': 'large', 'content': 'x' * (9 * 1024 * 1024)}])
        result = self.check()
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertIn('SOURCE_TOKEN_TOO_LARGE', result['errors'])

    def test_results_state_and_extensions_reconstructed(self):
        self.write([{'kayit_id': 'a', 'fiyat': 10, 'note': 'known', 'pending': True,
                     'sonuc_1g': {'completed': True, 'return': 3}}])
        store = self.store()
        frozen = {'kayit_id': 'a', 'fiyat': 10}
        complete = {'kayit_id': 'a', 'fiyat': 10, 'note': 'known', 'pending': True,
                     'sonuc_1g': {'completed': True, 'return': 3}}
        def rows(db, dataset, ids):
            return {'a': ({'frozen': frozen, 'frozen_hash': digest(frozen), 'current_hash': digest(complete)},
                          {'note': 'known'}, {'pending': True}, {'sonuc_1g': {'completed': True, 'return': 3}})}
        store._rows = rows
        result = self.check(store)
        self.assertEqual(result['status'], 'VERIFIED'); self.assertEqual(result['verified_records'], 1)

    def test_prediction_history_category(self):
        self.source.unlink(); source = self.root / 'runtime/tahmin_gecmisi.json'
        source.write_text(json.dumps({'tahminler': self.records}))
        result = self.check(Store({'runtime/tahmin_gecmisi.json#tahminler': {row['kayit_id']: row for row in self.records}}))
        self.assertEqual(result['categories']['prediction_history']['source_records'], 2)
        self.assertEqual(result['status'], 'VERIFIED')

    def test_batch_sizes_and_multiple_select_timeout_guards(self):
        rows = [{'kayit_id': str(i)} for i in range(205)]
        self.write(rows); store = self.store(rows)
        original = store._rows
        def retrieve(db, dataset, ids):
            db.execute('SELECT 1')
            return original(db, dataset, ids)
        store._rows = retrieve
        result = self.check(store)
        self.assertEqual(result['verified_records'], 205)
        self.assertGreater(sum('statement_timeout' in query for query in store.queries), 3)

    def test_database_duplicate_identity_never_verified(self):
        result = self.check(self.store(duplicate=True))
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertEqual(self.group(result)['pg_duplicate_records'], 1)
        self.assertIsNone(result['progress_percent'])

    def test_write_query_from_adapter_rejected(self):
        store = self.store()
        store._rows = lambda db, dataset, ids: db.execute('DELETE FROM bist_v6.records')
        result = self.check(store)
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('VERIFY_WRITE_FORBIDDEN', result['errors'])
        self.assertFalse(any(query.startswith('DELETE ') for query in store.queries))

    def test_oversized_pg_batch_not_loaded(self):
        store = self.store(huge_payload=True)
        store._rows = lambda *args: self.fail('Oversized batch should not be fetched')
        result = self.check(store)
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertIn('VERIFY_PAYLOAD_LIMIT', result['errors'])
        self.assertIsNone(result['verified_records'])


if __name__ == '__main__': unittest.main()
