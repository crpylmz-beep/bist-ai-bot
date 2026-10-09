"""One volume, two independent processes; Railway cannot share volumes across services."""
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from veri_yollari import paths, copy_new

ROOT = Path(__file__).resolve().parent
_inventory_attempted = False
_inventory_lock = threading.Lock()


def run_startup_inventory():
    """Opt-in, at most once per launcher process; no persistent marker or retry."""
    global _inventory_attempted
    if os.environ.get('BIST_RUN_INVENTORY_ONCE') != '1':
        return
    with _inventory_lock:
        if _inventory_attempted:
            return
        _inventory_attempted = True
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from v6_storage.inventory_log import run_once
        status = run_once(railway_logs=True)
        if status != 0:
            logging.warning('[V6_INVENTORY] {"complete":false,"error":"STARTUP_INVENTORY_INCOMPLETE_OR_UNAVAILABLE"}')
    except Exception:
        # Diagnostic failure must not stop web/worker; never log exception payload.
        logging.warning('[V6_INVENTORY] {"complete":false,"error":"STARTUP_INVENTORY_FAILED"}')
    finally:
        sys.dont_write_bytecode = previous_bytecode



def seed_reference_data(location):
    from cloud_bootstrap import bootstrap_public
    result=bootstrap_public(location)
    logging.info('[CLOUD] public bootstrap: %s kayıt hazırlandı', result['created'])


def stop_children(children, timeout=25):
    for child in children.values():
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + timeout
    for child in children.values():
        try:
            child.wait(timeout=max(0, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def supervise(launcher=None, stop=None):
    launcher = launcher or (lambda name: subprocess.Popen([sys.executable, '-u', str(ROOT/name)], cwd=ROOT, env={**os.environ, 'PYTHONUNBUFFERED':'1'}))
    stop = stop or threading.Event()
    children = {}
    restart_at = 0
    try:
        logging.info('[CLOUD] worker başlatılıyor')
        children['worker'] = launcher('ana_motor.py')
        logging.info('[CLOUD] worker pid=%s', children['worker'].pid)
        logging.info('[CLOUD] web başlatılıyor')
        children['web'] = launcher('web_server.py')
        logging.info('[CLOUD] web pid=%s', children['web'].pid)
        if os.environ.get('BIST_RUN_POSTGRES_SCHEMA_ONCE') == '1':
            def _verify_schema_once():
                # Never print the DSN or subprocess stderr: both may contain secrets.
                try:
                    result = subprocess.run(
                        [sys.executable, '-u', '-B', '-m', 'v6_storage', 'schema'],
                        cwd=ROOT, env={**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0:
                        import json
                        try:
                            applied = json.loads(result.stdout).get('applied', [])
                            if not isinstance(applied, list) or not all(isinstance(x, str) for x in applied):
                                raise ValueError('invalid result')
                            logging.info('[V6_SCHEMA_ONCE_RESULT] status=SUCCESS applied_count=%d', len(applied))
                        except (ValueError, TypeError):
                            logging.warning('[V6_SCHEMA_ONCE_RESULT] status=UNVERIFIED_OUTPUT')
                    else:
                        try:
                            payload = json.loads(result.stdout)
                            code = payload.get('error', 'UNKNOWN')
                            if not isinstance(code, str) or not code.isupper() or len(code) > 80 or not all(ch.isupper() or ch.isdigit() or ch == '_' for ch in code):
                                code = 'UNSAFE_OR_UNKNOWN'
                        except (ValueError, TypeError, AttributeError):
                            code = 'UNKNOWN'
                        logging.warning('[V6_SCHEMA_ONCE_RESULT] status=FAILED exit_code=%d error_code=%s', result.returncode, code)
                except subprocess.TimeoutExpired:
                    logging.warning('[V6_SCHEMA_ONCE_RESULT] status=TIMEOUT')
                except OSError:
                    logging.warning('[V6_SCHEMA_ONCE_RESULT] status=LAUNCH_FAILED')
            threading.Thread(target=_verify_schema_once, name='v6-schema-once', daemon=True).start()
            logging.info('[V6_SCHEMA_ONCE_LAUNCH] started')
        if os.environ.get('BIST_RUN_INTEGRITY_ONCE') == '1':
            try:
                subprocess.Popen(
                    [sys.executable, '-u', '-B', '-m', 'v6_storage.readonly_integrity', '--root', '/data'],
                    cwd=ROOT, env={**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                    stdout=None, stderr=None, start_new_session=True,
                )
                logging.info('[V6_INTEGRITY_LAUNCH] started')
            except OSError:
                logging.warning('[V6_INTEGRITY_LAUNCH] failed')
        if os.environ.get('BIST_RUN_JSON_CENSUS_ONCE') == '1':
            try:
                subprocess.Popen(
                    [sys.executable, '-u', '-B', '-m', 'v6_storage.readonly_json_census', '--root', '/data'],
                    cwd=ROOT, env={**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                    stdout=None, stderr=None, start_new_session=True,
                )
                logging.info('[V6_JSON_CENSUS_LAUNCH] started')
            except OSError:
                logging.warning('[V6_JSON_CENSUS_LAUNCH] failed')
        if os.environ.get('BIST_RUN_DUPLICATE_AUDIT_ONCE') == '1':
            try:
                subprocess.Popen(
                    [sys.executable, '-u', '-B', '-m', 'v6_storage.readonly_duplicate_files', '--root', '/data'],
                    cwd=ROOT, env={**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                    stdout=None, stderr=None, start_new_session=True,
                )
                logging.info('[V6_DUPLICATE_FILE_AUDIT_LAUNCH] started')
            except OSError:
                logging.warning('[V6_DUPLICATE_FILE_AUDIT_LAUNCH] failed')
        while not stop.wait(.5):
            if children['worker'].poll() is not None:
                logging.error('[CLOUD] worker beklenmedik çıkış code=%s; servis yeniden başlatılmalı', children['worker'].returncode)
                return 1
            if children['web'].poll() is not None:
                if time.monotonic() >= restart_at:
                    logging.warning('[CLOUD] web beklenmedik çıkış code=%s; yeniden başlatılıyor', children['web'].returncode)
                    children['web'] = launcher('web_server.py')
                    logging.info('[CLOUD] web pid=%s', children['web'].pid)
                    restart_at = time.monotonic()+5
        return 0
    except OSError as error:
        logging.error('[CLOUD] süreç başlatma hatası: %s', type(error).__name__)
        return 1
    finally:
        logging.info('[CLOUD] child processler kapatılıyor')
        stop_children(children)


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    run_startup_inventory()
    location = paths()
    location.ensure()
    from disk_koruma import report,cleanup_startup
    report(location)
    cleanup_startup(location)
    report(location)
    seed_reference_data(location)
    stop = threading.Event()
    def request_stop(signum, _):
        logging.info('[CLOUD] kapanış sinyali=%s', signum)
        stop.set()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    return supervise(stop=stop)


if __name__ == '__main__':
    sys.exit(main())
