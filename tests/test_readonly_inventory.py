import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from v6_storage.readonly_inventory import report
from v6_storage.__main__ import main


class ReadOnlyInventoryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        for name,data in {'runtime/tahmin_gecmisi.json':b'prediction','runtime/ai_ogrenme_gecmisi.json':b'learning',
            'runtime/.user-unique.tmp':b'UNIQUE TEMP','runtime/.storage-recovery-v5-x.wal':b'UNIQUE RECOVERY',
            'archives/yarin_top10_arsiv/2026-10-09.json':b'ARCHIVE','public/yarin_top10_sonuclar.json':b'OUTCOME',
            'private/user-data/secret-person/push_subscriptions.json':b'PRIVATE',
            'private/user-data/secret-person/.user-private.tmp':b'PRIVATE TEMP',
            'runtime/cache_prices.json':b'CACHE'}.items():
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)

    def snapshot(self):return {str(p.relative_to(self.root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_categories_capacity_no_changes_or_content_reads(self):
        before=self.snapshot()
        with patch('pathlib.Path.open',side_effect=AssertionError('content read forbidden')):
            value=report(self.root)
        self.assertEqual(before,self.snapshot())
        groups=value['categories']
        self.assertEqual(groups['prediction_history']['files'],2)
        self.assertEqual(groups['learning_data']['files'],1)
        self.assertEqual(groups['temporary_files']['files'],2)
        self.assertEqual(groups['recovery_records']['files'],1)
        self.assertEqual(groups['signal_outcomes']['files'],1)
        self.assertFalse(value['source_content_read']);self.assertFalse(value['source_deleted'])
        self.assertEqual(value['r2_capacity_scenario']['raw_preservation_bytes'],len(b'predictionlearningARCHIVEOUTCOMEUNIQUE TEMPUNIQUE RECOVERY'))
        self.assertNotIn('secret-person',json.dumps(value));self.assertNotIn('PRIVATE TEMP',json.dumps(value))
        self.assertTrue(value['complete'])

    def test_symlinks_not_followed(self):
        external=tempfile.TemporaryDirectory();self.addCleanup(external.cleanup)
        outside=Path(external.name)
        (self.root/'outside').symlink_to(outside,target_is_directory=True)
        (self.root/'alias').symlink_to(self.root/'runtime/tahmin_gecmisi.json')
        value=report(self.root);self.assertEqual(value['symlinks_skipped'],2)
        with self.assertRaises(OSError):report(self.root/'outside')

    def test_hardlink_physical_not_double_counted(self):
        first=report(self.root)
        os.link(self.root/'runtime/tahmin_gecmisi.json',self.root/'runtime/prediction_alias.json')
        second=report(self.root)
        self.assertEqual(first['tree_allocated_unique_bytes'],second['tree_allocated_unique_bytes'])
        self.assertEqual(second['hardlink_alias_paths'],1)

    def test_invalid_factors_rejected(self):
        for kwargs in ({'pg_factor_low':float('nan')},{'r2_ratio_high':2},{'pg_factor_low':5,'pg_factor_high':1},{'limit':101}):
            with self.assertRaises(ValueError):report(self.root,**kwargs)

    def test_cli_no_db_r2_or_env_data_root_access(self):
        before=self.snapshot();output=io.StringIO()
        with patch.dict(os.environ,{'BIST_DATA_DIR':'/do-not-access-production','STORAGE_BACKEND':'postgres','BIST_POSTGRES_DSN':'invalid'}),contextlib.redirect_stdout(output),patch('veri_yollari.paths',side_effect=AssertionError('implicit root forbidden')):
            self.assertEqual(main(['inventory','--root',str(self.root)]),0)
        self.assertEqual(before,self.snapshot())
        self.assertFalse(json.loads(output.getvalue())['external_connections'])

    def test_missing_root_no_creation(self):
        missing=self.root/'missing'
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main(['inventory','--root',str(missing)]),2)
        self.assertFalse(missing.exists())

    def test_unreadable_directory_report_incomplete(self):
        original=os.scandir
        def scan(fd):
            if os.fstat(fd).st_ino==(self.root/'runtime').stat().st_ino:raise PermissionError()
            return original(fd)
        with patch('os.scandir',side_effect=scan):value=report(self.root)
        self.assertFalse(value['complete']);self.assertGreater(value['errors'],0)

    def test_dated_signal_and_compressed_archives_separate_capacity(self):
        path=self.root/'runtime/intraday_signal_results/2026-10-09.json';path.parent.mkdir(parents=True);path.write_bytes(b'outcomes')
        compressed=self.root/'archives/yarin_top10_arsiv/2026-10-08.json.gz';compressed.write_bytes(b'already compressed')
        value=report(self.root)
        self.assertEqual(value['categories']['signal_outcomes']['files'],2)
        self.assertEqual(value['postgresql_capacity_scenario']['raw_classified_bytes'],len(b'predictionlearningARCHIVEOUTCOMEoutcomes'))
        self.assertEqual(value['r2_capacity_scenario']['already_compressed_filename_bytes'],compressed.stat().st_size)
        self.assertGreaterEqual(value['r2_capacity_scenario']['estimated_compressed_bytes_low'],compressed.stat().st_size)

    def test_known_price_cache_not_misclassified_as_performance_memory(self):
        path=self.root/'runtime/performans_fiyat_cache.json';path.write_bytes(b'cached prices')
        value=report(self.root)
        self.assertEqual(value['categories']['reproducible_cache_review']['files'],2)
        self.assertEqual(value['categories']['signal_outcomes']['files'],1)
        self.assertIsNone(value['postgresql_capacity_scenario']['estimated_total_cutover_bytes'])
