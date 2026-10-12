import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from v6_storage.config import Settings,StorageError
from v6_storage.postgres import PostgresStore
from v6_storage.__main__ import main
from v6_storage.railway_schema_check import run_check

class SchemaVerificationReasons(unittest.TestCase):
 def store(self,schema='bist_v6',metadata='bist_v6.schema_migrations',rows=None):
  expected=[{'version':p.name,'checksum':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(Path('v6_storage/migrations').glob('*.sql'))]
  sql=[]
  class Cursor:
   def __init__(self,values):self.values=values
   def fetchone(self):return self.values[0]
   def __iter__(self):return iter(self.values)
  class Connection:
   @contextlib.contextmanager
   def transaction(self):yield self
   def execute(self,query):
    sql.append(query)
    if query=='SET TRANSACTION READ ONLY':return Cursor([])
    if not sql or sql[0]!='SET TRANSACTION READ ONLY' or not query.startswith('SELECT '):raise AssertionError('Write attempted')
    if 'to_regnamespace' in query:return Cursor([{'schema_name':schema,'name':metadata}])
    if query=='SELECT version,checksum FROM bist_v6.schema_migrations':return Cursor(expected if rows is None else rows)
    raise AssertionError('Unexpected SQL')
  connection=Connection()
  class Pool:
   @contextlib.contextmanager
   def connection(self,**kwargs):yield connection
   def close(self):pass
  return PostgresStore(Settings(dsn='postgresql://localhost/test'),pool=Pool()),sql,expected
 def failure(self,expected_code,**kwargs):
  store,sql,_=self.store(**kwargs)
  with self.assertRaises(StorageError) as caught:store.ready()
  self.assertEqual(caught.exception.storage_code,expected_code)
  self.assertEqual(sql[0],'SET TRANSACTION READ ONLY')
  self.assertTrue(all(q.startswith('SELECT ') for q in sql[1:]))
 def test_namespace_missing(self):self.failure('SCHEMA_NAMESPACE_MISSING',schema=None,metadata=None)
 def test_metadata_missing(self):self.failure('SCHEMA_METADATA_MISSING',metadata=None)
 def test_empty_metadata(self):self.failure('SCHEMA_MIGRATION_VERSION_MISSING',rows=[])
 def test_partial_metadata(self):self.failure('SCHEMA_MIGRATION_VERSION_MISSING',rows=self.store()[2][:-1])
 def test_checksum_mismatch(self):
  rows=self.store()[2];rows[0]['checksum']='SECRET'
  self.failure('SCHEMA_MIGRATION_CHECKSUM_MISMATCH',rows=rows)
 def test_mismatch_precedes_missing(self):self.failure('SCHEMA_MIGRATION_CHECKSUM_MISMATCH',rows=[{'version':'001_core.sql','checksum':'SECRET'}])
 def test_all_versions_verified_select_only(self):
  store,sql,_=self.store();self.assertTrue(store.ready());self.assertEqual(len(sql),3)
 def test_unknown_metadata_not_logged_or_executed(self):
  rows=self.store()[2]+[{'version':'SECRET','checksum':'SECRET'}]
  store,sql,_=self.store(rows=rows);self.assertTrue(store.ready());self.assertNotIn('SECRET',str(sql))
 def test_cli_and_startup_fixed_codes_no_secrets(self):
  for code in ('SCHEMA_NAMESPACE_MISSING','SCHEMA_METADATA_MISSING','SCHEMA_MIGRATION_VERSION_MISSING','SCHEMA_MIGRATION_CHECKSUM_MISMATCH'):
   with patch.dict(os.environ,{'DATABASE_URL':'postgresql://u:SECRET@localhost/db'},clear=True),patch('v6_storage.postgres.PostgresStore') as store,contextlib.redirect_stdout(io.StringIO()) as out:
    store.return_value.ready.side_effect=StorageError(code)
    self.assertEqual(main(['schema','--check']),2)
    store.return_value.migrate.assert_not_called()
   payload=json.loads(out.getvalue());self.assertEqual(payload['error'],code);self.assertEqual(payload['stage'],'SCHEMA_VERIFY');self.assertNotIn('SECRET',out.getvalue())
   runner=Mock(return_value=Mock(returncode=2,stdout=out.getvalue()))
   with patch.dict(os.environ,{},clear=True),self.assertLogs(level='INFO') as logs:self.assertFalse(run_check('/tmp',runner))
   self.assertIn(code,str(logs.output));self.assertNotIn('SECRET',str(logs.output))
