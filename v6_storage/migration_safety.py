"""Read-only backup inspection and bounded JSON/PostgreSQL equality checks.

No restore, migration, schema creation, source deletion or storage-mode switching.
"""
import re
from pathlib import Path
import subprocess
from .config import StorageError
from .migration import checksum,fingerprint,metadata,pairs
from .records import digest,row_key,assemble


def inspect_backup(path,expected_sha256,runner=None):
    if not isinstance(expected_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha256):
        raise StorageError('BACKUP_CHECKSUM_REQUIRED')
    path=Path(path).absolute()
    before=fingerprint(path)
    if checksum(path)!=expected_sha256:raise StorageError('BACKUP_CHECKSUM_MISMATCH')
    try:
        result=(runner or subprocess.run)(['pg_restore','--list',str(path)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=False)
    except (OSError,subprocess.TimeoutExpired):raise StorageError('BACKUP_INSPECTION_UNAVAILABLE') from None
    if fingerprint(path)!=before:raise StorageError('SOURCE_CHANGED')
    if result.returncode:raise StorageError('BACKUP_FORMAT_INVALID')
    return {'checksum_verified':True,'archive_readable':True,'restore_verified':False,
            'production_readiness':'RESTORE_REHEARSAL_REQUIRED','source_changed':False}


def compare_source(path,shape,store,batch_size=100,max_records=100000):
    """Compare against an isolated restore or destination using one read-only snapshot.

    Unknown/recovery files are not guessed: caller must supply a verified Shape.
    Counts refer to each source collection, not unrelated database datasets.
    """
    if not 1<=batch_size<=1000 or not 1<=max_records<=1000000:
        raise StorageError('VERIFICATION_BUDGET_INVALID')
    before=fingerprint(path);raw=checksum(path);actual,meta=metadata(path,shape)
    report={'status':'VERIFIED','source_changed':False,'records':0,'missing':0,
            'mismatched':0,'integrity_errors':0,'extra':0,'collections':0}
    with store.transaction() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        document=db.execute('SELECT metadata,collections FROM bist_v6.documents WHERE dataset=%s',(shape.dataset,)).fetchone()
        if not document or document['metadata']!=meta or document['collections']!=actual.fields:
            report['integrity_errors']+=1
        for field,mode in actual.fields.items():
            dataset=shape.dataset+'#'+field;seen=set();batch=[];missing_before=report['missing']
            def verify_batch():
                found=store._rows(db,dataset,[identity for identity,row in batch])
                for identity,row in batch:
                    value=found.get(identity)
                    if value is None:report['missing']+=1;continue
                    record,extensions,state,outcomes=value
                    reconstructed=assemble(record['frozen'],extensions,state,outcomes)
                    if digest(reconstructed)!=digest(row):report['mismatched']+=1
                    if digest(record['frozen'])!=record['frozen_hash'] or digest(reconstructed)!=record['current_hash']:
                        report['integrity_errors']+=1
                batch.clear()
            for key,row in pairs(path,field,mode):
                if report['records']>=max_records:
                    report['status']='BUDGET_EXHAUSTED';return report
                identity=row_key(shape,field,row,key)
                if identity in seen:raise StorageError('SOURCE_DUPLICATE_ID')
                seen.add(identity);report['records']+=1;batch.append((identity,row))
                if len(batch)>=batch_size:verify_batch()
            if batch:verify_batch()
            count=db.execute('SELECT count(*) AS count FROM bist_v6.records WHERE dataset=%s',(dataset,)).fetchone()['count']
            report['extra']+=max(0,count-(len(seen)-(report['missing']-missing_before)))
            report['collections']+=1
    if fingerprint(path)!=before or checksum(path)!=raw:raise StorageError('SOURCE_CHANGED')
    if any(report[k] for k in ('missing','mismatched','integrity_errors','extra')):report['status']='MISMATCH'
    return report


def _private_path(path):
    from pathlib import Path
    import os
    value=Path(path).absolute()
    root=Path(os.environ.get('BIST_DATA_DIR','/data')).resolve()
    resolved=value.resolve()
    if resolved==root or root in resolved.parents or Path('/data')==resolved or Path('/data') in resolved.parents:
        raise StorageError('BACKUP_OUTSIDE_DATA_REQUIRED')
    if value.is_symlink():raise StorageError('SOURCE_NOT_REGULAR')
    return value


def create_backup(target,apply=False,runner=None):
    """Explicit pg_dump custom archive; never run implicitly or write /data."""
    import os
    from .config import Settings
    path=_private_path(target)
    if path.exists():raise StorageError('BACKUP_NEW_TARGET_REQUIRED')
    if not apply:return {'mode':'DRY_RUN','backup_created':False,'requires':'EXPLICIT_APPLY_AND_PRIVATE_EXTERNAL_CAPACITY'}
    dsn=Settings.from_env().connection_dsn()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        # URL passed through environment, not argv or logs. One consistent pg_dump snapshot.
        result=(runner or subprocess.run)(['pg_dump','--format=custom','--no-password'],
            env={**os.environ,'PGDATABASE':dsn},stdout=fd,stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,timeout=1800,check=False)
        os.fsync(fd)
    except (OSError,subprocess.TimeoutExpired):raise StorageError('BACKUP_FAILED_PARTIAL_PRESERVED') from None
    finally:os.close(fd)
    if result.returncode:raise StorageError('BACKUP_FAILED_PARTIAL_PRESERVED')
    return {'backup_created':True,'sha256':checksum(path),'restore_verified':False}


def restore_rehearsal(path,expected_sha256,apply=False,runner=None,connect=None):
    """Restores only to a separately declared, empty isolated DB; never production."""
    import os
    from urllib.parse import urlparse
    from .config import Settings
    source=_private_path(path)
    inspected=inspect_backup(source,expected_sha256,runner)
    if not apply:return dict(inspected,mode='DRY_RUN',restored=False)
    if os.environ.get('V6_RESTORE_ISOLATED')!='1':raise StorageError('ISOLATED_RESTORE_CONFIRMATION_REQUIRED')
    production=Settings.from_env().connection_dsn()
    isolated=Settings(dsn=os.environ.get('V6_RESTORE_DSN','')).connection_dsn()
    def identity(dsn):
        value=urlparse(dsn);return value.hostname,value.port or 5432,value.path
    if identity(production)==identity(isolated):raise StorageError('PRODUCTION_RESTORE_FORBIDDEN')
    if connect is None:
        import psycopg
        connect=psycopg.connect
    with connect(isolated,autocommit=True,connect_timeout=10) as db:
        with db.transaction():
            db.execute('SET TRANSACTION READ ONLY')
            count=db.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'").fetchone()[0]
            if count:raise StorageError('RESTORE_TARGET_NOT_EMPTY')
    try:
        result=(runner or subprocess.run)(['pg_restore','--no-password','--single-transaction','--exit-on-error','--no-owner','--no-privileges','--dbname=',str(source)],
            env={**os.environ,'PGDATABASE':isolated},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1800,check=False)
    except (OSError,subprocess.TimeoutExpired):raise StorageError('RESTORE_REHEARSAL_FAILED') from None
    if result.returncode:raise StorageError('RESTORE_REHEARSAL_FAILED')
    if checksum(source)!=expected_sha256:raise StorageError('SOURCE_CHANGED')
    return {'restored':True,'restore_verified':False,'requires':'RECORD_AND_SCHEMA_EQUALITY_CHECK','source_changed':False}


def main(argv=None):
    import argparse,json
    from .records import shape_for
    parser=argparse.ArgumentParser(description='V6 safety tools; mutating backup/isolated restore require --apply')
    commands=parser.add_subparsers(dest='command',required=True)
    inventory=commands.add_parser('inventory');inventory.add_argument('--root',required=True)
    backup=commands.add_parser('backup');backup.add_argument('target');backup.add_argument('--apply',action='store_true')
    inspect=commands.add_parser('inspect-backup');inspect.add_argument('source');inspect.add_argument('--sha256',required=True)
    restore=commands.add_parser('restore-rehearsal');restore.add_argument('source');restore.add_argument('--sha256',required=True);restore.add_argument('--apply',action='store_true')
    compare=commands.add_parser('compare');compare.add_argument('source');compare.add_argument('--batch-size',type=int,default=100);compare.add_argument('--max-records',type=int,default=100000)
    args=parser.parse_args(argv);store=None
    try:
        if args.command=='inventory':
            from .readonly_inventory import report
            from .readonly_integrity import scan
            value=report(args.root,limit=0)
            integrity=scan(args.root,max_files=200000,max_seconds=60)
            result={'inventory':value,'integrity':integrity,'status':'VERIFIED' if value['complete'] and integrity['status']=='VERIFIED' else 'INCOMPLETE'}
        elif args.command=='backup':result=create_backup(args.target,args.apply)
        elif args.command=='inspect-backup':result=inspect_backup(args.source,args.sha256)
        elif args.command=='restore-rehearsal':result=restore_rehearsal(args.source,args.sha256,args.apply)
        else:
            from veri_yollari import paths
            from .postgres import PostgresStore
            shape=shape_for(args.source,paths())
            if shape is None:raise StorageError('SOURCE_SCHEMA_UNSUPPORTED_RECOVERY_PRESERVED')
            store=PostgresStore();result=compare_source(args.source,shape,store,args.batch_size,args.max_records)
        print(json.dumps(result,sort_keys=True));return 0 if result.get('status','VERIFIED')=='VERIFIED' else 2
    except Exception as error:
        import ijson
        code=error.storage_code if isinstance(error,StorageError) else ('SOURCE_JSON_INVALID' if isinstance(error,ijson.JSONError) else 'SOURCE_NOT_FOUND' if isinstance(error,FileNotFoundError) else 'SOURCE_RECORD_INVALID' if isinstance(error,ValueError) else 'VERIFICATION_UNAVAILABLE')
        print(json.dumps({'status':'UNRESOLVED','error':code}));return 2
    finally:
        if store:store.close()

if __name__=='__main__':raise SystemExit(main())
