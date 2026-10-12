"""Explicit operator tools. No production mutation from imports or startup."""
import argparse
import json
import logging
from pathlib import Path
from .config import Settings,StorageError
from .records import shape_for,canonical
from .migration import Migrator


def main(argv=None):
    parser=argparse.ArgumentParser(description='V6 storage: defaults to read-only dry run')
    sub=parser.add_subparsers(dest='command',required=True)
    schema=sub.add_parser('schema')
    schema.add_argument('--check',action='store_true',help='Read-only verification; no schema DDL')
    migration=sub.add_parser('migrate');migration.add_argument('source');migration.add_argument('--apply',action='store_true');migration.add_argument('--budget-records',type=int)
    archive=sub.add_parser('archive');archive.add_argument('source');archive.add_argument('--apply',action='store_true')
    restore=sub.add_parser('restore');restore.add_argument('manifest');restore.add_argument('target');restore.add_argument('--apply',action='store_true')
    export=sub.add_parser('export');export.add_argument('source');export.add_argument('target')
    sub.add_parser('usage')
    health=sub.add_parser('connections-health')
    health.add_argument('--probe',action='store_true')
    log_inventory=sub.add_parser('inventory-log')
    log_inventory.add_argument('--railway-logs',action='store_true')
    inventory=sub.add_parser('inventory');inventory.add_argument('--root',required=True)
    inventory.add_argument('--pg-factor-low',type=float,default=1.5);inventory.add_argument('--pg-factor-high',type=float,default=3.0)
    inventory.add_argument('--r2-ratio-low',type=float,default=.25);inventory.add_argument('--r2-ratio-high',type=float,default=.75)
    args=parser.parse_args(argv)
    if args.command=='connections-health':
        from .connection_health import check
        value=check(probe=args.probe)
        print(json.dumps(value,ensure_ascii=True))
        return 2 if any(row['status'] in ('ERROR','PARTIALLY_CONFIGURED') for row in value['services'].values()) else 0
    if args.command=='inventory-log':
        from .inventory_log import run_once
        return run_once(railway_logs=args.railway_logs)
    if args.command=='inventory':
        from .readonly_inventory import report
        try:
            value=report(args.root,pg_factor_low=args.pg_factor_low,pg_factor_high=args.pg_factor_high,r2_ratio_low=args.r2_ratio_low,r2_ratio_high=args.r2_ratio_high)
        except (OSError,ValueError):
            print(json.dumps({'mode':'READ_ONLY_METADATA','error':'INVENTORY_UNAVAILABLE_OR_INVALID_ARGUMENT','success':False}));return 2
        print(json.dumps(value,ensure_ascii=False));return 0 if value['complete'] else 2
    from veri_yollari import paths
    location=paths();database=None;stage=None;pool_filter=None
    try:
        if args.command=='schema':
            stage='CONFIGURATION'
            settings=Settings.from_env();settings.require_database()
            stage='DEPENDENCIES'
            try:
                import psycopg
                import psycopg_pool
            except ImportError:
                raise StorageError('POSTGRES_DEPENDENCY_MISSING') from None
            from .schema_diagnostics import PoolDiagnosticsFilter
            pool_filter=PoolDiagnosticsFilter()
            logging.getLogger('psycopg.pool').addFilter(pool_filter)
            stage='CONNECT'
            from .postgres import PostgresStore
            try:database=PostgresStore(settings)
            except StorageError:raise
            except Exception as error:
                from .schema_diagnostics import postgres_details
                safe=StorageError('POSTGRES_OPERATION_FAILED');safe.safe_details=postgres_details(error)
                raise safe from None
            stage='SCHEMA_VERIFY' if args.check else 'SCHEMA_APPLY'
            applied=[] if args.check else database.migrate()
            stage='SCHEMA_VERIFY'
            database.ready()
            print(json.dumps({'applied':applied,'verified':True,'read_only':args.check}));return 0
        if args.command=='migrate':
            selected=shape_for(args.source,location)
            if selected is None:raise StorageError('SOURCE_SCHEMA_UNSUPPORTED_ARCHIVE_REQUIRED')
            if args.apply:
                from .postgres import PostgresStore
                database=PostgresStore(Settings.from_env());database.ready()
            report=Migrator(database).run(args.source,selected,args.apply,args.budget_records)
            print(json.dumps(report));return 0 if report['status']=='VERIFIED' else 2
        if args.command=='archive':
            if not args.apply:
                from .migration import checksum,fingerprint
                print(json.dumps({'mode':'DRY_RUN','size':fingerprint(args.source)['size'],'sha256':checksum(args.source),'source_deleted':False}));return 0
            from .r2 import R2Archive
            print(json.dumps(R2Archive().archive(args.source)));return 0
        if args.command=='restore':
            if not args.apply:print(json.dumps({'mode':'DRY_RUN','source_changed':False}));return 0
            from .r2 import R2Archive
            manifest=json.loads(Path(args.manifest).read_text())
            R2Archive().restore(manifest,args.target);print(json.dumps({'restored':True,'overwrite':False}));return 0
        if args.command=='export':
            from .postgres import PostgresStore
            from atomik_depolama import atomic_write_json
            selected=shape_for(args.source,location)
            if selected is None:raise StorageError('SOURCE_SCHEMA_UNSUPPORTED')
            database=PostgresStore(Settings.from_env());value=database.document(selected)
            target=Path(args.target)
            if target.exists() or target.is_symlink() or target.absolute()==Path(args.source).absolute():raise StorageError('EXPORT_NEW_TARGET_REQUIRED')
            atomic_write_json(target,value,overwrite=False)
            from .migration import checksum
            print(json.dumps({'exported':True,'sha256':checksum(target),'source_changed':False}));return 0
        if args.command=='usage':
            from .usage import disk_report
            print(json.dumps(disk_report(location.root or location.runtime)));return 0
    except StorageError as error:
        payload={'error':error.storage_code,'success':False}
        if args.command=='schema':
            payload['stage']=stage
            details=getattr(error,'safe_details',{})
            if details.get('reason')=='POSTGRES_CONNECTION_TIMEOUT' and pool_filter and pool_filter.best():
                details=pool_filter.best()
            payload.update(details)
            if details.get('reason'):
                payload['error']=details['reason']
                payload['storage_error']=error.storage_code
        print(json.dumps(payload));return 2
    finally:
        try:
            if database:database.close()
        finally:
            if pool_filter:logging.getLogger('psycopg.pool').removeFilter(pool_filter)


if __name__=='__main__':raise SystemExit(main())
