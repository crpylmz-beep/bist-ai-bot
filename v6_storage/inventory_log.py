"""One metadata scan: explicit CLI or opt-in launcher hook; no persistent state."""
import json
import os
import stat
import sys
from pathlib import Path
from .readonly_inventory import report


def summary(value):
    # Only fixed category names and aggregate numbers are allowed into logs.
    return {
        'mode': 'READ_ONLY_METADATA', 'complete': value['complete'],
        'budget_exhausted': value['budget_exhausted'], 'errors': value['errors'],
        'categories': {key: {'files': row['files'], 'logical_bytes': row['logical_bytes'],
                             'allocated_bytes': row['allocated_bytes']}
                       for key, row in value['categories'].items()},
        'postgresql_capacity_scenario': value['postgresql_capacity_scenario'],
        'r2_capacity_scenario': value['r2_capacity_scenario'],
        'estimates_not_measurements': True, 'classification_advisory': True,
        'live_scan_atomic_snapshot': False, 'source_content_read': False,
        'source_changed': False,
    }


def run_once(*, railway_logs=False):
    # No DataPaths.ensure, marker, recovery journal, cache or file logger.
    fd = None
    try:
        if railway_logs:
            # Write to the existing container log pipe, NEVER a disk-backed log.
            fd = os.open('/proc/1/fd/1', os.O_WRONLY | os.O_NONBLOCK)
            if not stat.S_ISFIFO(os.fstat(fd).st_mode):
                return 2
        root = os.environ.get('BIST_DATA_DIR', '').strip()
        if not root or not Path(root).is_absolute():
            value = {'mode': 'READ_ONLY_METADATA', 'error': 'DATA_ROOT_REQUIRED'}
            status = 2
        else:
            try:
                value = summary(report(root, limit=0, max_entries=200000, max_seconds=20))
                status = 0 if value['complete'] else 2
            except (OSError, ValueError, RecursionError):
                value = {'mode': 'READ_ONLY_METADATA', 'error': 'INVENTORY_UNAVAILABLE', 'source_changed': False}
                status = 2
        payload = '[V6_INVENTORY] ' + json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n'
        if fd is None:
            sys.stdout.write(payload)
        else:
            data = payload.encode('ascii')
            # Bounded single pipe write avoids partial/interleaved reports.
            if len(data) > os.fpathconf(fd, 'PC_PIPE_BUF'):
                return 2
            if os.write(fd, data) != len(data):
                return 2
        return status
    except OSError:
        # Do not expose exception text/paths, or fall back to disk files.
        return 2
    finally:
        if fd is not None:
            os.close(fd)
