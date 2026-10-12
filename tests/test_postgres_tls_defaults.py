import os
import unittest
from unittest.mock import Mock,patch
from v6_storage.config import Settings,StorageError
from v6_storage.postgres import PostgresStore
from v6_storage.connection_health import postgres_probe

class PostgresTLSDefaults(unittest.TestCase):
 def test_missing_sslmode_defaults_to_require_without_mutation(self):
  for key in ('DATABASE_URL','BIST_POSTGRES_DSN'):
   env={key:'postgresql://user:SECRET@postgres.railway.internal/db'};before=dict(env)
   s=Settings.from_env(env)
   self.assertEqual(s.connection_dsn(),env[key]+'?sslmode=require')
   self.assertEqual(s.mode,'legacy');self.assertEqual(env,before);self.assertEqual(s.dsn,env[key])
 def test_query_credentials_and_encoding_preserved(self):
  for dsn in ('postgres://u:p%40ss%2Fword@remote/db?application_name=a%20b','postgresql://remote/db?'):
   self.assertEqual(Settings(dsn=dsn).connection_dsn(),dsn+'&sslmode=require')
 def test_stronger_modes_preserved_and_idempotent(self):
  for mode in ('require','verify-ca','verify-full'):
   dsn='postgresql://remote/db?sslmode='+mode+'&sslrootcert=%2Fca.pem'
   self.assertEqual(Settings(dsn=dsn).connection_dsn(),dsn)
   self.assertEqual(Settings(dsn=Settings(dsn=dsn).connection_dsn()).connection_dsn(),dsn)
 def test_unsafe_and_duplicate_options_rejected(self):
  for query in ('sslmode=disable','sslmode=allow','sslmode=prefer','sslmode=','sslmode=require&sslmode=require','sslmode=verify-full&sslmode=disable'):
   with self.subTest(query=query),self.assertRaises(StorageError) as error:
    Settings(dsn='postgresql://u:SECRET@remote/db?'+query).connection_dsn()
   self.assertEqual(error.exception.storage_code,'POSTGRES_TLS_REQUIRED');self.assertNotIn('SECRET',str(error.exception))
 def test_loopback_existing_behavior_only_when_unspecified(self):
  for host in ('localhost','127.0.0.1','[::1]'):
   dsn='postgresql://'+host+'/db';self.assertEqual(Settings(dsn=dsn).connection_dsn(),dsn)
  with self.assertRaises(StorageError):Settings(dsn='postgresql://localhost/db?sslmode=disable').connection_dsn()
 def test_invalid_url_and_fragment_redacted(self):
  for dsn in ('not-a-url-SECRET','postgresql://[bad/db','postgresql://remote/db#SECRET'):
   with self.assertRaises(StorageError) as error:Settings(dsn=dsn).connection_dsn()
   self.assertEqual(error.exception.storage_code,'POSTGRES_CONFIGURATION_INVALID');self.assertNotIn('SECRET',str(error.exception))
 def test_pool_receives_required_tls_despite_insecure_libpq_env(self):
  with patch.dict(os.environ,{'PGSSLMODE':'disable'}),patch('psycopg_pool.ConnectionPool') as pool:
   store=PostgresStore(Settings(dsn='postgresql://remote/db'))
   self.assertEqual(pool.call_args.args[0],'postgresql://remote/db?sslmode=require')
   pool.return_value.open.assert_called_once();store.close()
 def test_probe_tls_failure_does_not_retry_plaintext(self):
  with patch('psycopg.connect',side_effect=ConnectionError('TLS unavailable SECRET')) as connect:
   with self.assertRaises(ConnectionError):postgres_probe(Settings(dsn='postgresql://remote/db'))
  connect.assert_called_once();self.assertEqual(connect.call_args.args[0],'postgresql://remote/db?sslmode=require')
 def test_override_precedence_and_no_config(self):
  s=Settings.from_env({'DATABASE_URL':'postgresql://fallback/db?sslmode=verify-full','BIST_POSTGRES_DSN':'postgresql://override/db'})
  self.assertEqual(s.connection_dsn(),'postgresql://override/db?sslmode=require')
  with self.assertRaises(StorageError) as error:Settings.from_env({}).connection_dsn()
  self.assertEqual(error.exception.storage_code,'POSTGRES_NOT_CONFIGURED')
