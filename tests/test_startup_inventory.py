import os
import unittest
from unittest.mock import patch, Mock
import cloud_baslat as cloud


class StartupInventoryTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(cloud,'_inventory_attempted',False)
        self.guard.start();self.addCleanup(self.guard.stop)

    def test_default_and_other_values_disabled(self):
        with patch.dict(os.environ,{},clear=True),patch('v6_storage.inventory_log.run_once') as run:
            cloud.run_startup_inventory();run.assert_not_called()
            for value in ('0','false','true','yes',' 1','1 '):
                with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':value}):cloud.run_startup_inventory()
            run.assert_not_called();self.assertFalse(cloud._inventory_attempted)

    def test_enabled_once_per_process_and_no_retry(self):
        with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':'1'}),patch('v6_storage.inventory_log.run_once',return_value=0) as run:
            cloud.run_startup_inventory();cloud.run_startup_inventory()
            run.assert_called_once_with(railway_logs=True)

    def test_partial_scan_logs_only_safe_prefix(self):
        with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':'1'}),patch('v6_storage.inventory_log.run_once',return_value=2) as run,self.assertLogs(level='WARNING') as output:
            cloud.run_startup_inventory();cloud.run_startup_inventory()
        run.assert_called_once();self.assertIn('[V6_INVENTORY]',output.output[0]);self.assertIn('INCOMPLETE_OR_UNAVAILABLE',output.output[0])

    def test_unexpected_error_safe_and_not_retried(self):
        with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':'1'}),patch('v6_storage.inventory_log.run_once',side_effect=RuntimeError('SECRET user data /data/private')) as run,self.assertLogs(level='WARNING') as output:
            cloud.run_startup_inventory();cloud.run_startup_inventory()
        run.assert_called_once();self.assertIn('[V6_INVENTORY]',output.output[0]);self.assertNotIn('SECRET',str(output.output));self.assertNotIn('/data',str(output.output))

    def test_initial_scan_precedes_normal_bootstrap_and_service_continues(self):
        events=[];location=Mock()
        location.ensure.side_effect=lambda:events.append('ensure')
        with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':'1'}),patch('v6_storage.inventory_log.run_once',side_effect=lambda **kw:events.append('inventory') or 0),patch.object(cloud,'paths',return_value=location),patch('disk_koruma.report'),patch('disk_koruma.cleanup_startup'),patch.object(cloud,'seed_reference_data'),patch.object(cloud.signal,'signal'),patch.object(cloud,'supervise',return_value=0) as service:
            self.assertEqual(cloud.main(),0)
        self.assertEqual(events,['inventory','ensure']);service.assert_called_once()

    def test_startup_error_does_not_stop_service(self):
        with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':'1'}),patch('v6_storage.inventory_log.run_once',side_effect=OSError('SECRET')),patch.object(cloud,'paths',return_value=Mock()),patch('disk_koruma.report'),patch('disk_koruma.cleanup_startup'),patch.object(cloud,'seed_reference_data'),patch.object(cloud.signal,'signal'),patch.object(cloud,'supervise',return_value=0) as service,self.assertLogs(level='WARNING'):
            self.assertEqual(cloud.main(),0)
        service.assert_called_once()

    def test_inventory_imports_cannot_write_bytecode_and_flag_restored(self):
        def run(**kwargs):
            self.assertTrue(cloud.sys.dont_write_bytecode)
            return 0
        with patch.dict(os.environ,{'BIST_RUN_INVENTORY_ONCE':'1'}),patch('v6_storage.inventory_log.run_once',side_effect=run),patch.object(cloud.sys,'dont_write_bytecode',False):
            cloud.run_startup_inventory()
            self.assertFalse(cloud.sys.dont_write_bytecode)
