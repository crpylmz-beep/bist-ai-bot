"""Read-only, bounded exact-file duplicate audit. No paths or hashes in logs."""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from .readonly_inventory import category

GROUPS = ('prediction_history', 'learning_data', 'signal_outcomes')

def audit(root, max_seconds=600, max_files=200000):
    root = Path(root).absolute()
    deadline = time.monotonic() + max_seconds
    fingerprints = defaultdict(list)
    errors = 0
    changed = 0
    seen = 0
    budget_exceeded = False
    def walk_error(_):
        nonlocal errors
        errors += 1
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(folder) / d).is_symlink())
        for name in sorted(files):
            if seen >= max_files or time.monotonic() >= deadline:
                budget_exceeded = True
                break
            seen += 1
            path = Path(folder) / name
            kind = category(name, path.relative_to(root).parts[:-1])
            if kind not in GROUPS or not name.lower().endswith(('.json', '.jsonl')):
                continue
            try:
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode):
                    errors += 1
                    continue
                digest = hashlib.sha256()
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
                    current = os.fstat(stream.fileno())
                    if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                        changed += 1
                        continue
                    while True:
                        if time.monotonic() >= deadline:
                            budget_exceeded = True
                            break
                        block = stream.read(1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                if budget_exceeded:
                    break
                after = path.lstat()
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                    changed += 1
                    continue
                fingerprints[(before.st_size, digest.digest())].append(kind)
            except OSError:
                errors += 1
        if budget_exceeded:
            break
    duplicates = [k for k, groups in fingerprints.items() if len(groups) > 1]
    return {
        'status': 'INCOMPLETE' if errors or changed or budget_exceeded else 'VERIFIED',
        'scope': 'CORE_JSON_EXACT_FILE_DUPLICATES_ONLY',
        'files_seen': seen, 'files_hashed': sum(map(len, fingerprints.values())),
        'duplicate_groups': len(duplicates),
        'duplicate_extra_copies': sum(len(fingerprints[k]) - 1 for k in duplicates),
        'duplicate_extra_bytes': sum(k[0] * (len(fingerprints[k]) - 1) for k in duplicates),
        'errors': errors, 'changed': changed, 'budget_exceeded': budget_exceeded,
        'source_deleted': False, 'source_moved': False,
        'note': 'Exact byte-identical file duplicates only; does not establish duplicate business records or deletion eligibility.'
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    result = audit(args.root)
    print('[V6_DUPLICATE_FILE_AUDIT] ' + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] == 'VERIFIED' else 2

if __name__ == '__main__':
    raise SystemExit(main())
