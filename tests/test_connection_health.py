import contextlib
import io
import json
import os
import unittest
from unittest.mock import Mock, patch
from v6_storage.config import Settings, R2Settings, StorageError
from v6_storage.connection_health import check, postgres_probe, r2_probe
from v6_storage.__main__ import main

ENV={'BIST_POSTGRES_DSN':'postgresql://fixture-user:fixture-secret@db.example/test?sslmode=require',
     'R2_BUCKET':'fixture-private','R2_ENDPOINT_URL':'https://fixture.r2.cloudflarestorage.com',
     'R2_ACCESS_KEY_ID':'fixture-access','R2_SECRET_ACCESS_KEY':'fixture-secret',
     'R2_PRIVATE_BUCKET_CONFIRMED':'true'}


class ConnectionHealthTests(unittest.TestCase):
    def test_missing_connections_never_open_clients_even_probe(self):
        for probe in (False,True):
            with patch('v6_storage.connection_health.postgres_probe',side_effect=AssertionError('no network')),patch('v6_storage.connection_health.r2_probe',side_effect=AssertionError('no network')):
                result=check(env={},probe=probe)
            self.assertTrue(all(row['status']=='NOT_CONFIGURED' for row in result['services'].values()))
        self.assertEqual(Settings.from_env({}).mode,'legacy')

    def test_passive_configured_no_connections_or_secrets(self):
        with patch('v6_storage.connection_health.postgres_probe',side_effect=AssertionError('no network')),patch('v6_storage.connection_health.r2_probe',side_effect=AssertionError('no network')):
            value=check(env=ENV)
        self.assertTrue(all(row['status']=='CONFIGURED_UNCHECKED' for row in value['services'].values()))
        output=json.dumps(value)+repr(Settings.from_env(ENV))+repr(R2Settings.from_env(ENV))
        for secret in ('fixture-secret','fixture-access','db.example','fixture-private'):
            self.assertNotIn(secret,output)

    def test_explicit_probes_once_no_mode_changes(self):
        pg=Mock();r2=Mock();result=check(env=ENV,probe=True,pg_checker=pg,r2_checker=r2)
        pg.assert_called_once();r2.assert_called_once()
        self.assertTrue(all(row['status']=='OK' for row in result['services'].values()))
        for key in ('schema_changed','storage_backend_changed','data_moved'):self.assertFalse(result[key])
        self.assertEqual(ENV.get('STORAGE_BACKEND','legacy'),'legacy')

    def test_failure_redacted_and_other_backend_continues(self):
        r2=Mock();value=check(env=ENV,probe=True,pg_checker=Mock(side_effect=RuntimeError('fixture-secret')),r2_checker=r2)
        self.assertEqual(value['services']['postgresql']['code'],'POSTGRES_PROBE_FAILED')
        self.assertEqual(value['services']['r2']['status'],'OK');r2.assert_called_once()
        self.assertNotIn('fixture-secret',json.dumps(value))

    def test_partial_and_invalid_configuration_no_probe(self):
        for env,service,code in (({'R2_BUCKET':'x'},'r2','R2_NOT_CONFIGURED'),
            ({**ENV,'R2_ENDPOINT_URL':'http://unsafe.test'},'r2','R2_ENDPOINT_INVALID'),
            ({**ENV,'R2_PRIVATE_BUCKET_CONFIRMED':'false'},'r2','R2_PRIVATE_BUCKET_CONFIRMATION_REQUIRED'),
            ({**ENV,'BIST_POSTGRES_DSN':'postgres://user:secret@db.example/db?sslmode=disable'},'postgresql','POSTGRES_TLS_REQUIRED')):
            pg=Mock();r2=Mock();value=check(env=env,probe=False,pg_checker=pg,r2_checker=r2)
            self.assertEqual(value['services'][service]['code'],code);pg.assert_not_called();r2.assert_not_called()

    def test_timeout_bounds_and_credentials_repr(self):
        settings=R2Settings.from_env({**ENV,'R2_CONNECT_TIMEOUT_SECONDS':'4','R2_READ_TIMEOUT_SECONDS':'8'})
        self.assertEqual((settings.connect_timeout,settings.read_timeout),(4,8))
        for value in ('0','61','bad'):
            with self.assertRaises(StorageError):R2Settings.from_env({**ENV,'R2_READ_TIMEOUT_SECONDS':value})

    def test_postgres_probe_read_only_queries_closes_connection(self):
        db=Mock();db.transaction.return_value.__enter__=Mock();db.transaction.return_value.__exit__=Mock()
        db.execute.return_value.fetchone.return_value=(1,)
        connection=Mock();connection.__enter__=Mock(return_value=db);connection.__exit__=Mock()
        with patch('psycopg.connect',return_value=connection) as connect:
            postgres_probe(Settings.from_env(ENV))
        self.assertEqual(db.execute.call_args_list[0].args[0],'SET TRANSACTION READ ONLY')
        self.assertEqual(db.execute.call_args_list[-1].args[0],'SELECT 1 AS connected')
        self.assertEqual(db.execute.call_count,3);connection.__exit__.assert_called_once()
        self.assertTrue(connect.call_args.kwargs['autocommit'])

    def test_r2_probe_head_only_closes_even_on_failure(self):
        client=Mock();archive=Mock(client=client)
        for failure in (None,RuntimeError('fixture-secret')):
            client.head_bucket.side_effect=failure;client.reset_mock()
            with patch('v6_storage.r2.R2Archive',return_value=archive):
                if failure:
                    with self.assertRaises(RuntimeError):r2_probe(R2Settings.from_env(ENV),ENV)
                else:r2_probe(R2Settings.from_env(ENV),ENV)
            client.head_bucket.assert_called_once_with(Bucket='fixture-private');client.close.assert_called_once()
            self.assertEqual(len(client.mock_calls),2)

    def test_cli_passive_and_failure_exit_codes(self):
        output=io.StringIO()
        with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(output):self.assertEqual(main(['connections-health']),0)
        self.assertIn('NOT_CONFIGURED',output.getvalue())
        with patch.dict(os.environ,{'R2_BUCKET':'x'},clear=True),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main(['connections-health','--probe']),2)

    def test_conflicting_tls_options_rejected_before_connect(self):
        env={**ENV,'BIST_POSTGRES_DSN':ENV['BIST_POSTGRES_DSN']+'&sslmode=disable'}
        pg=Mock();result=check(env=env,probe=True,pg_checker=pg,r2_checker=Mock())
        self.assertEqual(result['services']['postgresql']['code'],'POSTGRES_TLS_REQUIRED')
        pg.assert_not_called()
