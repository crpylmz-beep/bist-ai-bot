"""Read-only integrity report for a stable file tree; no source paths in output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import time

def scan(root, max_files=200000, max_seconds=900):
    root = Path(root).absolute()
    started = time.monotonic()
    rows = []
    errors = []
    visited = 0
    try:
        with os.scandir(root):
            pass
    except OSError:
        return {'status':'INCOMPLETE','reason':'ROOT_UNAVAILABLE','files_checked':0,'errors':1}
    def walk_error(_error):
        errors.append('DIRECTORY_UNREADABLE')
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink())
        for filename in sorted(files):
            visited += 1
            if visited > max_files or time.monotonic()-started > max_seconds:
                return {'status':'INCOMPLETE','files_checked':len(rows),'errors':len(errors),'reason':'BUDGET_EXCEEDED'}
            path = Path(directory)/filename
            try:
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode):
                    continue
                digest = hashlib.sha256()
                with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
                    actual = os.fstat(stream.fileno())
                    if (actual.st_dev,actual.st_ino)!=(before.st_dev,before.st_ino):
                        errors.append('SOURCE_CHANGED')
                        continue
                    while block := stream.read(1024*1024):
                        if time.monotonic()-started > max_seconds:
                            return {'status':'INCOMPLETE','files_checked':len(rows),'errors':len(errors),'reason':'BUDGET_EXCEEDED'}
                        digest.update(block)
                after = path.lstat()
                if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                    errors.append('SOURCE_CHANGED')
                    continue
                rows.append((before.st_size,digest.digest()))
            except OSError:
                errors.append('UNREADABLE_OR_CHANGED')
    summary = hashlib.sha256()
    for size, checksum in sorted(rows):
        summary.update(size.to_bytes(8,'big')+checksum)
    return {'status':'VERIFIED' if not errors else 'INCOMPLETE',
            'files_checked':len(rows),'bytes_checked':sum(r[0] for r in rows),
            'errors':len(errors),'error_codes':sorted(set(errors)),
            'aggregate_fingerprint':summary.hexdigest(),
            'source_changed':bool(errors)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    args=parser.parse_args()
    result=scan(args.root)
    print('[V6_FILE_INTEGRITY] '+json.dumps(result,sort_keys=True))
    return 0 if result['status']=='VERIFIED' else 2

if __name__=='__main__':
    raise SystemExit(main())
