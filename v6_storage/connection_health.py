"""Passive by default; explicit probes are read-only and never change storage mode."""
import os
from .config import Settings, R2Settings, StorageError

SAFE_CODES = frozenset(('POSTGRES_NOT_CONFIGURED', 'POSTGRES_CONFIGURATION_INVALID',
    'POSTGRES_TLS_REQUIRED', 'STORAGE_MODE_INVALID', 'STORAGE_CONFIGURATION_INVALID',
    'R2_NOT_CONFIGURED', 'R2_CONFIGURATION_INVALID', 'R2_ENDPOINT_INVALID',
    'R2_PRIVATE_BUCKET_CONFIRMATION_REQUIRED'))


def postgres_probe(settings):
    # One short-lived diagnostic connection, no background pool retry logs.
    # The application row store continues to use its existing connection pool.
    import psycopg
    with psycopg.connect(settings.dsn, connect_timeout=settings.timeout,
                         options='-c timezone=Europe/Istanbul', autocommit=True) as db:
        with db.transaction():
            db.execute('SET TRANSACTION READ ONLY')
            db.execute("SELECT set_config('statement_timeout', %s, true)", (str(settings.timeout * 1000),))
            row = db.execute('SELECT 1 AS connected').fetchone()
            if not row or row[0] != 1:
                raise StorageError('POSTGRES_PROBE_FAILED')


def r2_probe(settings, env):
    from .r2 import R2Archive
    archive = R2Archive(env=env)
    try:
        # HEAD only: no object listings, downloads, uploads, bucket creation or deletion.
        archive.client.head_bucket(Bucket=settings.bucket)
    finally:
        archive.client.close()


def check(*, env=None, probe=False, pg_checker=None, r2_checker=None):
    env = os.environ if env is None else env
    result = {'mode': 'READ_ONLY_CONNECTION_HEALTH', 'active_probe_requested': bool(probe),
              'storage_backend_changed': False, 'data_moved': False, 'schema_changed': False,
              'readiness_scope': 'CONNECTIVITY_ONLY_NOT_CUTOVER_APPROVAL', 'services': {}}
    for name in ('postgresql', 'r2'):
        row = {'status': 'NOT_CONFIGURED', 'code': 'POSTGRES_NOT_CONFIGURED' if name == 'postgresql' else 'R2_NOT_CONFIGURED'}
        result['services'][name] = row
        configured = bool(env.get('BIST_POSTGRES_DSN') or env.get('DATABASE_URL')) if name == 'postgresql' else any(env.get(key) for key in ('R2_BUCKET','R2_ENDPOINT_URL','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY'))
        if not configured:
            continue
        try:
            if name == 'postgresql':
                settings = Settings.from_env(env); settings.require_database()
            else:
                settings = R2Settings.from_env(env); settings.require()
            row.update(status='CONFIGURED_UNCHECKED', code='PROBE_NOT_REQUESTED')
            if probe:
                if name == 'postgresql': (pg_checker or postgres_probe)(settings)
                else: (r2_checker or r2_probe)(settings, env)
                row.update(status='OK', code='READ_ONLY_PROBE_OK')
        except Exception as error:
            code = error.storage_code if isinstance(error, StorageError) and error.storage_code in SAFE_CODES else ('POSTGRES_PROBE_FAILED' if name == 'postgresql' else 'R2_PROBE_FAILED')
            row.update(status='PARTIALLY_CONFIGURED' if code == 'R2_NOT_CONFIGURED' else 'ERROR', code=code)
    return result
