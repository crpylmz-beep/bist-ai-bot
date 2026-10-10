import contextlib,copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from v6_storage.migration_safety import inspect_backup,compare_source,create_backup,restore_rehearsal,main
from v6_storage.migration import Migrator
from v6_storage.records import Shape,digest
from v6_storage.config import StorageError

class SafetyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'source.json';self.rows=[{'kayit_id':str(i),'fiyat':10+i} for i in range(7)]
  self.path.write_text(json.dumps({'rows':self.rows}));self.shape=Shape('test',{'rows':'list'})
 def store(self,missing=False,extra=False,corrupt=False):
  owner=self;calls=[]
  class Cursor:
   def __init__(self,row):self.row=row
   def fetchone(self):return self.row
  class DB:
   def execute(self,sql,params=None):
    calls.append(sql)
    if sql.startswith('SET TRANSACTION'):return Cursor(None)
    if not sql.startswith('SELECT '):raise AssertionError('Write attempted')
    if 'FROM bist_v6.documents' in sql:return Cursor({'metadata':{},'collections':{'rows':'list'}})
    return Cursor({'count':len(owner.rows)+(1 if extra else 0)-(1 if missing else 0)})
  class Store:
   @contextlib.contextmanager
   def transaction(self):yield DB()
   def _rows(self,db,dataset,ids):
    assert len(ids)<=2
    result={}
    for row in owner.rows:
     key=row['kayit_id']
     if key not in ids or missing and key=='0':continue
     result[key]=({'frozen':copy.deepcopy(row),'frozen_hash':digest(row),'current_hash':'bad' if corrupt else digest(row)},{},{},{})
    return result
  return Store(),calls
 def test_equal_batched_source_unchanged(self):
  before=self.path.read_bytes();store,calls=self.store();r=compare_source(self.path,self.shape,store,batch_size=2)
  self.assertEqual(r['status'],'VERIFIED');self.assertEqual(r['records'],7);self.assertEqual(self.path.read_bytes(),before)
  self.assertIn('READ ONLY',calls[0]);self.assertEqual(len(list(self.path.parent.iterdir())),1)
 def test_missing_records(self):
  r=compare_source(self.path,self.shape,self.store(missing=True)[0],2);self.assertEqual(r['missing'],1);self.assertEqual(r['status'],'MISMATCH')
 def test_extra_records(self):self.assertEqual(compare_source(self.path,self.shape,self.store(extra=True)[0],2)['extra'],1)
 def test_integrity_corruption(self):self.assertEqual(compare_source(self.path,self.shape,self.store(corrupt=True)[0],2)['integrity_errors'],7)
 def test_budget_not_verified(self):self.assertEqual(compare_source(self.path,self.shape,self.store()[0],2,3)['status'],'BUDGET_EXHAUSTED')
 def test_duplicate_rejected(self):
  self.path.write_text(json.dumps({'rows':[self.rows[0],self.rows[0]]}))
  with self.assertRaises(StorageError) as e:compare_source(self.path,self.shape,self.store()[0],2)
  self.assertEqual(e.exception.storage_code,'SOURCE_DUPLICATE_ID')
 def test_broken_json_safely_reported(self):
  self.path.write_text('{broken')
  with patch('v6_storage.records.shape_for',return_value=self.shape),patch('v6_storage.postgres.PostgresStore',return_value=Mock()):
   self.assertEqual(main(['compare',str(self.path)]),2)
 def test_backup_inspection_not_restore_proof(self):
  runner=Mock(return_value=SimpleNamespace(returncode=0));r=inspect_backup(self.path,hashlib.sha256(self.path.read_bytes()).hexdigest(),runner)
  self.assertFalse(r['restore_verified']);self.assertEqual(runner.call_args.args[0][1],'--list')
 def test_backup_wrong_checksum_before_command(self):
  runner=Mock()
  with self.assertRaises(StorageError):inspect_backup(self.path,'0'*64,runner)
  runner.assert_not_called()
 def test_backup_dry_run_no_files(self):
  runner=Mock();r=create_backup(self.path.parent/'backup.dump',runner=runner)
  self.assertEqual(r['mode'],'DRY_RUN');runner.assert_not_called();self.assertEqual(len(list(self.path.parent.iterdir())),1)
 def test_data_backup_prohibited(self):
  with self.assertRaises(StorageError):create_backup('/data/backup.dump')
 def test_restore_refuses_production(self):
  env={'DATABASE_URL':'postgresql://u:SECRET@server/db?sslmode=require','V6_RESTORE_DSN':'postgresql://other:SECRET2@server/db','V6_RESTORE_ISOLATED':'1'}
  with patch.dict(os.environ,env,clear=True),patch('v6_storage.migration_safety.inspect_backup',return_value={}),self.assertRaises(StorageError) as e:
   restore_rehearsal(self.path,'0'*64,True)
  self.assertEqual(e.exception.storage_code,'PRODUCTION_RESTORE_FORBIDDEN');self.assertNotIn('SECRET',str(e.exception))
 def test_restore_default_no_db(self):
  with patch('v6_storage.migration_safety.inspect_backup',return_value={'restore_verified':False}):
   connect=Mock();r=restore_rehearsal(self.path,'0'*64,connect=connect);connect.assert_not_called();self.assertFalse(r['restored'])
 def test_resumable_import_and_repeat_only_fake_destination(self):
  class Store:
   def __init__(self):self.cursor=0;self.rows={};self.finished=False
   def import_cursor(self,*args):return self.cursor
   def put_rows(self,dataset,batch,kind,receipt,**kwargs):
    self.rows.update(dict(batch));self.cursor=receipt['position'];return SimpleNamespace(conflicts=0)
   def import_conflicts(self,*args):return False
   def publish_document(self,*args,**kwargs):pass
   def finish_import(self,*args):self.finished=True
  store=Store();before=self.path.read_bytes();tool=Migrator(store,batch_size=2)
  self.assertEqual(tool.run(self.path,self.shape,True,2)['status'],'BUDGET_EXHAUSTED')
  self.assertEqual(tool.run(self.path,self.shape,True)['status'],'VERIFIED')
  self.assertEqual(tool.run(self.path,self.shape,True)['status'],'VERIFIED');self.assertEqual(len(store.rows),7);self.assertEqual(self.path.read_bytes(),before)
 def test_restore_nonempty_target_refused(self):
  env={'DATABASE_URL':'postgresql://production/db','V6_RESTORE_DSN':'postgresql://isolated/test','V6_RESTORE_ISOLATED':'1'}
  db=Mock();db.transaction.return_value=contextlib.nullcontext();db.execute.return_value.fetchone.return_value=(1,)
  connection=Mock();connection.__enter__=Mock(return_value=db);connection.__exit__=Mock(return_value=False)
  with patch.dict(os.environ,env,clear=True),patch('v6_storage.migration_safety.inspect_backup',return_value={}),self.assertRaises(StorageError) as error:
   restore_rehearsal(self.path,'0'*64,True,connect=Mock(return_value=connection))
  self.assertEqual(error.exception.storage_code,'RESTORE_TARGET_NOT_EMPTY')
 def test_restore_mock_success_never_claims_verified(self):
  env={'DATABASE_URL':'postgresql://u:SECRET@production/db','V6_RESTORE_DSN':'postgresql://u:SECRET2@isolated/test','V6_RESTORE_ISOLATED':'1'}
  db=Mock();db.transaction.return_value=contextlib.nullcontext();db.execute.return_value.fetchone.return_value=(0,)
  connection=Mock();connection.__enter__=Mock(return_value=db);connection.__exit__=Mock(return_value=False)
  runner=Mock(return_value=SimpleNamespace(returncode=0));raw=hashlib.sha256(self.path.read_bytes()).hexdigest()
  with patch.dict(os.environ,env,clear=True),patch('v6_storage.migration_safety.inspect_backup',return_value={}):
   result=restore_rehearsal(self.path,raw,True,runner,Mock(return_value=connection))
  self.assertTrue(result['restored']);self.assertFalse(result['restore_verified'])
  self.assertNotIn('SECRET',str(runner.call_args.args));self.assertIn('PGDATABASE',runner.call_args.kwargs['env'])
 def test_backup_failure_keeps_only_new_owned_file(self):
  target=self.path.parent/'partial.dump';runner=Mock(return_value=SimpleNamespace(returncode=1))
  with patch.dict(os.environ,{'DATABASE_URL':'postgresql://u:SECRET@server/db'},clear=True),self.assertRaises(StorageError) as error:
   create_backup(target,True,runner)
  self.assertTrue(target.exists());self.assertEqual(error.exception.storage_code,'BACKUP_FAILED_PARTIAL_PRESERVED')
  self.assertNotIn('SECRET',str(runner.call_args.args));self.assertTrue(self.path.exists())
 def test_inventory_cli_is_readonly(self):
  before=self.path.read_bytes()
  with contextlib.redirect_stdout(__import__('io').StringIO()) as output:
   self.assertEqual(main(['inventory','--root',self.temp.name]),0)
  self.assertEqual(self.path.read_bytes(),before);self.assertEqual(len(list(self.path.parent.iterdir())),1)
  self.assertNotIn(str(self.path),output.getvalue())

 def test_interrupted_import_replays_committed_cursor(self):
  class Store:
   def __init__(self):self.cursor=0;self.rows={};self.fail=True
   def import_cursor(self,*args):return self.cursor
   def put_rows(self,dataset,batch,kind,receipt,**kwargs):
    self.rows.update(dict(batch));self.cursor=receipt['position']
    if self.fail:self.fail=False;raise StorageError('POSTGRES_OPERATION_FAILED')
    return SimpleNamespace(conflicts=0)
   def import_conflicts(self,*args):return False
   def publish_document(self,*args,**kwargs):pass
   def finish_import(self,*args):pass
  store=Store();tool=Migrator(store,2);before=self.path.read_bytes()
  self.assertEqual(tool.run(self.path,self.shape,True)['status'],'UNRESOLVED')
  self.assertEqual(tool.run(self.path,self.shape,True)['status'],'VERIFIED')
  self.assertEqual(len(store.rows),7);self.assertEqual(self.path.read_bytes(),before)
