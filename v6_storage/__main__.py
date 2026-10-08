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
    sub.add_parser('schema')
    migration=sub.add_parser('migrate');migration.add_argument('source');migration.add_argument('--apply',action='store_true');migration.add_argument('--budget-records',type=int)
    archive=sub.add_parser('archive');archive.add_argument('source');archive.add_argument('--apply',action='store_true')
    restore=sub.add_parser('restore');restore.add_argument('manifest');restore.add_argument('target');restore.add_argument('--apply',action='store_true')
    export=sub.add_parser('export');export.add_argument('source');export.add_argument('target')
    sub.add_parser('usage')
    args=parser.parse_args(argv)
    from veri_yollari import paths
    location=paths();database=None
    try:
        if args.command=='schema':
            from .postgres import PostgresStore
            database=PostgresStore(Settings.from_env());print(json.dumps({'applied':database.migrate()}));return 0
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
        print(json.dumps({'error':error.storage_code,'success':False}));return 2
    finally:
        if database:database.close()


if __name__=='__main__':raise SystemExit(main())
