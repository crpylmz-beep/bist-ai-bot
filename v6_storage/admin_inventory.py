"""Explicit, bearer-authenticated metadata scan; no persistent state or cleanup."""
import os
import secrets
import threading
import time
from .readonly_inventory import report

_lock = threading.Lock()
_last_scan = float('-inf')


def handle(headers, url, location):
    global _last_scan
    token = os.environ.get('BIST_STORAGE_ADMIN_TOKEN', '')
    if len(token) < 32 or not token.isascii():
        return {'error': 'Yönetici envanteri etkin değil.'}, 503
    supplied = headers.get('Authorization', '')
    if not supplied.isascii() or not secrets.compare_digest(supplied, 'Bearer ' + token):
        return {'error': 'Yönetici yetkisi gerekiyor.'}, 401
    # No user-selected directory, query, request body or cross-origin browser call.
    if url.query or headers.get('Origin') or headers.get('Content-Length', '0') != '0' or headers.get('Transfer-Encoding'):
        return {'error': 'Parametresiz yönetici isteği gerekiyor.'}, 400
    if location.root is None:
        return {'error': 'Ortak veri kökü tanımlı değil.'}, 503
    if not _lock.acquire(blocking=False):
        return {'error': 'Envanter zaten çalışıyor.'}, 429
    try:
        if time.monotonic() - _last_scan < 60:
            return {'error': 'Yeni envanter için bir dakika bekleyin.'}, 429
        _last_scan = time.monotonic()
        try:
            value = report(location.root, limit=0, max_entries=200000, max_seconds=20)
        except (OSError, ValueError, RecursionError):
            return {'error': 'Envanter okunamadı; hiçbir veri değiştirilmedi.'}, 503
        # Deliberate response allowlist: no names, identifiers, paths or contents.
        result = {key: value[key] for key in (
            'mode', 'generated_at', 'complete', 'budget_exhausted', 'entries_scanned',
            'errors', 'symlinks_skipped', 'filesystem', 'tree_allocated_unique_bytes',
            'live_scan_atomic_snapshot', 'postgresql_capacity_scenario',
            'r2_capacity_scenario', 'notes', 'source_deleted', 'source_moved',
            'source_content_read', 'external_connections')}
        result['categories'] = {key: {field: row[field] for field in ('files', 'logical_bytes', 'allocated_bytes')}
                                for key, row in value['categories'].items()}
        return result, 200 if value['complete'] else 206
    finally:
        _lock.release()
