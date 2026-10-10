import contextlib
import io
import json
import os
import unittest
from unittest.mock import Mock,patch
from v6_storage.__main__ import main
from v6_storage.config import StorageError,Settings
from v6_storage.postgres import PostgresStore
from v6_storage.schema_diagnostics import postgres_details

class SchemaDiagnosticsTests(unittest.TestCase):
 def run_schema(self,argv,env=None):
  output=io.StringIO()
  with patch.dict(os.environ,env or {},clear=True),contextlib.redirect_stdout(output):result=main(argv)
  return result,json.loads(output.getvalue())
 def test_no_dsn_is_explicit_and_offline(self):
  with patch('v6_storage.postgres.PostgresStore') as store:
   code,data=self.run_schema(['schema'])
  self.assertEqual(code,2);self.assertEqual(data['error'],'POSTGRES_NOT_CONFIGURED');self.assertEqual(data['stage'],'CONFIGURATION');store.assert_not_called()
 def test_no_tls_not_silently_disabled(self):
  code,data=self.run_schema(['schema'],{'DATABASE_URL':'postgresql://user:SECRET@remote/db?sslmode=disable'})
  self.assertEqual(code,2);self.assertEqual(data['error'],'POSTGRES_TLS_REQUIRED');self.assertNotIn('SECRET',str(data))
 def test_readonly_check_does_not_migrate(self):
  with patch('v6_storage.postgres.PostgresStore') as store:
   code,data=self.run_schema(['schema','--check'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,0);store.return_value.migrate.assert_not_called();store.return_value.ready.assert_called_once();store.return_value.close.assert_called_once();self.assertTrue(data['read_only'])
 def test_apply_must_verify(self):
  with patch('v6_storage.postgres.PostgresStore') as store:
   store.return_value.migrate.return_value=['001_core.sql']
   code,data=self.run_schema(['schema'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,0);self.assertTrue(data['verified']);store.return_value.ready.assert_called_once()
 def test_not_verified_never_success(self):
  with patch('v6_storage.postgres.PostgresStore') as store:
   store.return_value.ready.side_effect=StorageError('SCHEMA_MIGRATION_REQUIRED')
   code,data=self.run_schema(['schema','--check'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,2);self.assertEqual(data['stage'],'SCHEMA_VERIFY');self.assertFalse(data['success'])
 def test_override_precedence_remains(self):
  code,data=self.run_schema(['schema'],{'DATABASE_URL':'postgresql://localhost/test','BIST_POSTGRES_DSN':'postgresql://user:SECRET@remote/db?sslmode=disable'})
  self.assertEqual(data['error'],'POSTGRES_TLS_REQUIRED');self.assertEqual(code,2)
 def test_sqlstate_classification_and_safe_logs(self):
  for state,reason in [('28P01','POSTGRES_AUTH_FAILED'),('42501','POSTGRES_PERMISSION_DENIED'),('08006','POSTGRES_CONNECTION_FAILED'),('42601','POSTGRES_SQL_SYNTAX'),('53100','POSTGRES_DISK_FULL')]:
   with self.subTest(state=state):
    error=RuntimeError('SECRET postgresql://user:password@host');error.sqlstate=state
    pool=Mock();pool.connection.side_effect=error
    store=PostgresStore(Settings(dsn='postgresql://localhost/test'),pool=pool)
    with self.assertLogs(level='ERROR') as logs,self.assertRaises(StorageError) as caught:
     with store.transaction():pass
    self.assertEqual(caught.exception.safe_details['reason'],reason)
    self.assertNotIn('SECRET',str(logs.output));self.assertNotIn('password',str(caught.exception))
 def test_untrusted_state_not_logged(self):
  error=RuntimeError('SECRET');error.sqlstate='SECRET URL'
  self.assertEqual(postgres_details(error),{'reason':'POSTGRES_OPERATION_FAILED'})
 def test_dependency_missing_is_safe(self):
  import builtins
  original=builtins.__import__
  def importing(name,*args,**kwargs):
   if name=='psycopg_pool':raise ImportError('secret filesystem path')
   return original(name,*args,**kwargs)
  with patch('builtins.__import__',side_effect=importing):
   code,data=self.run_schema(['schema'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,2);self.assertEqual(data['error'],'POSTGRES_DEPENDENCY_MISSING');self.assertEqual(data['stage'],'DEPENDENCIES')
 def test_connect_failure_is_safe(self):
  with patch('v6_storage.postgres.PostgresStore',side_effect=ConnectionError('SECRET')):
   code,data=self.run_schema(['schema'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,2);self.assertEqual(data['stage'],'CONNECT');self.assertEqual(data['reason'],'POSTGRES_CONNECTION_FAILED');self.assertNotIn('SECRET',str(data))

 def test_schema_failure_survives_launcher_error_code_only(self):
  error=StorageError('POSTGRES_OPERATION_FAILED');error.safe_details={'reason':'POSTGRES_AUTH_FAILED','sqlstate':'28P01'}
  with patch('v6_storage.postgres.PostgresStore') as store:
   store.return_value.migrate.side_effect=error
   code,data=self.run_schema(['schema'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,2);self.assertEqual(data['error'],'POSTGRES_AUTH_FAILED');self.assertEqual(data['storage_error'],'POSTGRES_OPERATION_FAILED');self.assertEqual(data['stage'],'SCHEMA_APPLY')

 def test_actual_ready_sql_is_server_readonly_and_no_ddl(self):
  import hashlib
  from pathlib import Path
  from contextlib import contextmanager
  import v6_storage.postgres as postgres
  manifest=[{'version':p.name,'checksum':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (Path(postgres.__file__).parent/'migrations').glob('*.sql')]
  class Cursor:
   def __init__(self,rows):self.rows=rows
   def fetchone(self):return self.rows[0]
   def __iter__(self):return iter(self.rows)
  class Connection:
   def __init__(self):self.sql=[];self.readonly=False
   @contextmanager
   def transaction(self):yield self
   def execute(self,sql):
    self.sql.append(sql)
    if sql=='SET TRANSACTION READ ONLY':self.readonly=True;return Cursor([])
    if not self.readonly or not sql.startswith('SELECT '):raise AssertionError('Write attempted')
    if 'to_regclass' in sql:return Cursor([{'name':'bist_v6.schema_migrations'}])
    if 'SELECT version,checksum' in sql:return Cursor(manifest)
    raise AssertionError('Unexpected SQL')
  connection=Connection()
  class Pool:
   @contextmanager
   def connection(self,**kwargs):yield connection
   def close(self):pass
  store=PostgresStore(Settings(dsn='postgresql://localhost/test'),pool=Pool())
  with patch('v6_storage.postgres.PostgresStore',return_value=store):
   code,data=self.run_schema(['schema','--check'],{'DATABASE_URL':'postgresql://localhost/test'})
  self.assertEqual(code,0);self.assertTrue(data['read_only']);self.assertEqual(len(connection.sql),3)
  self.assertEqual(connection.sql[0],'SET TRANSACTION READ ONLY')
  self.assertTrue(all(sql.startswith('SELECT ') for sql in connection.sql[1:]))

 def test_full_cli_failure_output_redacts_credentials(self):
  error=RuntimeError('postgresql://private_user:SECRET_PASSWORD@private_host/db?token=SECRET_TOKEN')
  error.sqlstate='28P01'
  pool=Mock();pool.connection.side_effect=error
  store=PostgresStore(Settings(dsn='postgresql://localhost/test'),pool=pool)
  stdout=io.StringIO();stderr=io.StringIO()
  with patch.dict(os.environ,{'DATABASE_URL':'postgresql://localhost/test'},clear=True),patch('v6_storage.postgres.PostgresStore',return_value=store),contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr),self.assertLogs(level='ERROR') as logs:
   code=main(['schema','--check'])
  self.assertEqual(code,2);self.assertEqual(json.loads(stdout.getvalue())['error'],'POSTGRES_AUTH_FAILED')
  output=stdout.getvalue()+stderr.getvalue()+str(logs.output)
  for secret in ('private_user','SECRET_PASSWORD','private_host','SECRET_TOKEN'):self.assertNotIn(secret,output)

 def test_unknown_five_letter_state_is_not_logged(self):
  error=RuntimeError('secret');error.sqlstate='TOKEN'
  self.assertEqual(postgres_details(error),{'reason':'POSTGRES_OPERATION_FAILED'})

 def test_raw_pool_warning_redacted_and_specific_failure_preserved(self):
  import logging
  original=list(logging.getLogger('psycopg.pool').filters)
  auth=RuntimeError('SECRET_PASSWORD');auth.sqlstate='28P01'
  timeout=StorageError('POSTGRES_OPERATION_FAILED');timeout.safe_details={'reason':'POSTGRES_CONNECTION_TIMEOUT'}
  def failing():
   logging.getLogger('psycopg.pool').warning('raw SECRET_TOKEN %s',auth)
   raise timeout
  stdout=io.StringIO();stderr=io.StringIO()
  with patch.dict(os.environ,{'DATABASE_URL':'postgresql://localhost/test'},clear=True),patch('v6_storage.postgres.PostgresStore') as store,contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
   store.return_value.ready.side_effect=failing
   code=main(['schema','--check'])
  self.assertEqual(code,2);self.assertEqual(json.loads(stdout.getvalue())['error'],'POSTGRES_AUTH_FAILED')
  self.assertNotIn('SECRET',stdout.getvalue()+stderr.getvalue())
  self.assertEqual(logging.getLogger('psycopg.pool').filters,original)

 def test_missing_table_and_schema_have_specific_safe_cli_codes(self):
  for state,expected in [('42P01','POSTGRES_TABLE_MISSING'),('3F000','POSTGRES_SCHEMA_MISSING')]:
   with self.subTest(state=state):
    failure=RuntimeError('SECRET postgres://private_user:password@private_host');failure.sqlstate=state
    pool=Mock();pool.connection.side_effect=failure
    store=PostgresStore(Settings(dsn='postgresql://localhost/test'),pool=pool)
    with patch('v6_storage.postgres.PostgresStore',return_value=store),self.assertLogs(level='ERROR') as logs:
     code,result=self.run_schema(['schema','--check'],{'DATABASE_URL':'postgresql://localhost/test'})
    self.assertEqual(code,2);self.assertEqual(result['error'],expected);self.assertEqual(result['sqlstate'],state)
    self.assertEqual(result['stage'],'SCHEMA_VERIFY')
    output=str(result)+str(logs.output)
    for secret in ('SECRET','private_user','password','private_host'):self.assertNotIn(secret,output)
