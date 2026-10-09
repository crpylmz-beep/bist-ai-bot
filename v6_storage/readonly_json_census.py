"""Bounded read-only structural JSON record census. Never logs names or content."""
import argparse
import json
import os
from pathlib import Path
import stat
import time
import ijson
from .readonly_inventory import category

ELIGIBLE = frozenset(('prediction_history', 'learning_data', 'signal_outcomes'))

def census(root, max_seconds=600, max_files=200000):
    root = Path(root).absolute()
    deadline = time.monotonic() + max_seconds
    counts = {k: {'files': 0, 'array_items': 0, 'object_members': 0, 'jsonl_lines': 0,
                  'nested_array_items': 0, 'nested_object_members': 0, 'max_depth': 0,
                  'unsupported_roots': 0, 'parse_errors': 0, 'changed': 0} for k in sorted(ELIGIBLE)}
    scanned = 0
    errors = 0
    stopped = False
    def walk_error(_):
        nonlocal errors
        errors += 1
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            if time.monotonic() >= deadline or scanned >= max_files:
                stopped = True
                break
            scanned += 1
            path = Path(directory) / name
            group = category(name, path.relative_to(root).parts[:-1])
            if group not in ELIGIBLE or not name.casefold().endswith(('.json', '.jsonl')):
                continue
            row = counts[group]
            row['files'] += 1
            try:
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode):
                    row['unsupported_roots'] += 1
                    continue
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
                    current = os.fstat(stream.fileno())
                    if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                        row['changed'] += 1
                        continue
                    if name.casefold().endswith('.jsonl'):
                        for line in stream:
                            if time.monotonic() >= deadline:
                                stopped = True
                                break
                            if line.strip():
                                json.loads(line)
                                row['jsonl_lines'] += 1
                    else:
                        parser = ijson.parse(stream)
                        root_event = next(parser, None)
                        if root_event is None:
                            row['parse_errors'] += 1
                        elif root_event[1] == 'start_array':
                            for prefix, event, _value in parser:
                                if time.monotonic() >= deadline:
                                    stopped = True
                                    break
                                depth = prefix.count('.') + (1 if prefix else 0)
                                row['max_depth'] = max(row['max_depth'], depth)
                                if prefix == 'item' and event in ('start_map', 'start_array', 'string', 'number', 'boolean', 'null'):
                                    row['array_items'] += 1
                                elif prefix.endswith('.item') and event in ('start_map', 'start_array', 'string', 'number', 'boolean', 'null'):
                                    row['nested_array_items'] += 1
                                if event == 'map_key' and prefix:
                                    row['nested_object_members'] += 1
                        elif root_event[1] == 'start_map':
                            for prefix, event, _value in parser:
                                if time.monotonic() >= deadline:
                                    stopped = True
                                    break
                                depth = prefix.count('.') + (1 if prefix else 0)
                                row['max_depth'] = max(row['max_depth'], depth)
                                if prefix == '' and event == 'map_key':
                                    row['object_members'] += 1
                                elif event == 'map_key':
                                    row['nested_object_members'] += 1
                                if prefix.endswith('.item') and event in ('start_map', 'start_array', 'string', 'number', 'boolean', 'null'):
                                    row['nested_array_items'] += 1
                        else:
                            row['unsupported_roots'] += 1
                after = path.lstat()
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                    row['changed'] += 1
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError, ijson.JSONError):
                row['parse_errors'] += 1
        if stopped:
            break
    incomplete = stopped or errors or any(r['parse_errors'] or r['changed'] or r['unsupported_roots'] for r in counts.values())
    return {'status': 'INCOMPLETE' if incomplete else 'STRUCTURAL_COUNTS_OK',
            'scope': 'CLASSIFIED_CORE_JSON_ONLY', 'root_snapshot_atomic': False,
            'files_seen': scanned, 'directory_errors': errors, 'budget_exceeded': stopped,
            'counts': counts, 'note': 'Structural elements are not deduplicated business records; live data may change.'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    result = census(args.root)
    print('[V6_JSON_CENSUS] ' + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] == 'STRUCTURAL_COUNTS_OK' else 2

if __name__ == '__main__':
    raise SystemExit(main())
