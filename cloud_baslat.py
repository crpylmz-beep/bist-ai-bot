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
    location = paths()
    location.ensure()
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
