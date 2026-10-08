"""Bounded independent scheduling for BIST workers; no deployment side effects."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, time as day_time
from pathlib import Path
from zoneinfo import ZoneInfo
from contextlib import contextmanager
import argparse
import fcntl
import json
import logging
import os
import signal
import threading
import time
import errno

from kullanici_kayitlari import atomic_json
from veri_yollari import paths
from gorev_hatalari import describe,public_issue,TaskIssue,log_source,diagnostics

ROOT = Path(__file__).resolve().parent
ISTANBUL = ZoneInfo('Europe/Istanbul')
DEFAULTS = {'bootstrap':30, 'kap':60, 'macro':120, 'alarm':30, 'push':20,
            'intraday_top10':300, 'company_site':900, 'full_scan':30,
            'priority':2, 'yarin_top10':60, 'performance':900, 'intraday_performance':300, 'market_context':300}
ENV_NAMES = {'bootstrap':'BOOTSTRAP', 'kap':'KAP', 'macro':'MACRO', 'alarm':'ALARM', 'push':'PUSH',
             'intraday_top10':'INTRADAY_TOP10', 'company_site':'COMPANY_SITE',
             'full_scan':'FULL_SCAN', 'priority':'PRIORITY', 'yarin_top10':'YARIN_TOP10', 'performance':'PERFORMANCE', 'intraday_performance':'INTRADAY_PERFORMANCE', 'market_context':'MARKET_CONTEXT'}
DEFAULTS['economy_news']=900
ENV_NAMES['economy_news']='ECONOMY_NEWS'
TECHNICAL = {'bootstrap', 'full_scan', 'priority', 'intraday_top10', 'yarin_top10'}
from gunluk_al_sat import INTERVAL_SECONDS as INTRADAY_SIGNAL_INTERVAL
DEFAULTS['indicator_performance']=900
ENV_NAMES['indicator_performance']='INDICATOR_PERFORMANCE'
DEFAULTS['sector_strength']=300
ENV_NAMES['sector_strength']='SECTOR_STRENGTH'
DEFAULTS['market_regime']=300
ENV_NAMES['market_regime']='MARKET_REGIME'
DEFAULTS['intraday_signals']=INTRADAY_SIGNAL_INTERVAL
ENV_NAMES['intraday_signals']='INTRADAY_SIGNALS'
TECHNICAL.add('intraday_signals')


def istanbul_now():
    return datetime.now(ISTANBUL)


def local_time(value):
    if value.tzinfo is None:
        raise ValueError('Aware datetime gerekiyor')
    return value.astimezone(ISTANBUL)


def market_open(value, holiday=None):
    value = local_time(value)
    return (value.weekday() < 5 and not (holiday and holiday(value.date()))
            and day_time(10) <= value.time() < day_time(18, 10))


def after_close(value, holiday=None):
    value = local_time(value)
    return value.weekday() < 5 and not (holiday and holiday(value.date())) and value.time() >= day_time(18, 15)


def runtime_dir():
    return paths().runtime


def health_snapshot(directory=None):
    """Public allowlist: never return arbitrary persisted runtime fields."""
    try:
        data = json.loads(((Path(directory) if directory else runtime_dir())/'ana_motor_durum.json').read_text())
        stamp = datetime.fromisoformat(data['updated_at'])
        if stamp.tzinfo is None:
            raise ValueError('Naive heartbeat')
        age = (istanbul_now() - stamp).total_seconds()
        running = data.get('motor_durumu') == 'RUNNING'
        healthy = running and 0 <= age <= 30
        status = 'AKTIF' if healthy else 'GECIKMIS' if running and 30 < age <= 120 else 'DURMUS_OLABILIR'
        tasks = {}
        for name, task in data.get('tasks', {}).items():
            if name in DEFAULTS and isinstance(task, dict):
                tasks[name] = {key: task[key] for key in ('status', 'last_success', 'started_at', 'failures', 'retry_in_seconds') if key in task}
                if task.get('last_error'):tasks[name]['last_error']=public_issue(task['last_error'])
                if task.get('diagnostics'):tasks[name]['diagnostics']=diagnostics(task['diagnostics'])
        result = {'motor_durumu': data.get('motor_durumu', 'UNKNOWN'), 'healthy': healthy,
                  'worker_status': status, 'heartbeat_age_seconds': round(age, 1),
                  'updated_at': data['updated_at'], 'tasks': tasks}
        result.update({k:v for k,v in data.items() if k.startswith('last_') and isinstance(v,str) and k in {
            'last_'+name+suffix for name in DEFAULTS for suffix in ('','_check','_batch')}})
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'motor_durumu':'NOT_RUNNING', 'healthy':False, 'worker_status':'DURMUS_OLABILIR', 'tasks':{}}


@contextmanager
def worker_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory/'ana_motor.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Ana motor zaten çalışıyor') from None
        from disk_forensik import worker_cleanup_scope
        with worker_cleanup_scope(directory):
            yield


@dataclass
class Task:
    callback: object
    interval: float
    next_due: float = 0
    failures: int = 0
    future: object = None
    scheduled_day: str = None


class AnaMotor:
    def __init__(self, callbacks, directory=None, clock=istanbul_now, monotonic=time.monotonic,
                 intervals=None, holiday=None, snapshot_exists=None, max_workers=6):
        self.directory = Path(directory) if directory else runtime_dir()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock, self.monotonic, self.holiday = clock, monotonic, holiday
        self.snapshot_exists = snapshot_exists or (lambda day:(paths().archives/f'{day}.json').exists())
        self.stop = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='bist-task')
        self.tasks = {}
        self._intraday_closed_log_due=0
        for name, callback in callbacks.items():
            interval = (intervals or {}).get(name, float(os.environ.get(ENV_NAMES[name]+'_INTERVAL_SECONDS', DEFAULTS[name])))
            if not 1 <= interval <= 86400:
                raise ValueError('Geçersiz görev periyodu: '+name)
            if name=='intraday_signals' and interval<INTRADAY_SIGNAL_INTERVAL:
                raise ValueError('Günlük AL/SAT periyodu en az 300 saniye olmalı')
            self.tasks[name] = Task(callback, interval)
        self.state = {'motor_durumu':'RUNNING', 'tasks':{}, 'son_hata':None, 'yarin_completed_day':None}
        path = self.directory/'ana_motor_durum.json'
        if path.exists():
            old = json.loads(path.read_text())  # Do not silently destroy damaged state.
            self.state['yarin_completed_day'] = old.get('yarin_completed_day')
            self.state.update({k:v for k,v in old.items() if k.startswith('last_')})
        self.persist()

    def persist(self):
        self.state['updated_at'] = local_time(self.clock()).isoformat(timespec='seconds')
        try:atomic_json(self.directory/'ana_motor_durum.json', self.state)
        except OSError as error:
            if error.errno not in (errno.ENOSPC,errno.EDQUOT):raise
            logging.error('[DISK] Worker heartbeat kaydedilemedi: alan yetersiz; önceki state korundu. Volume kapasitesi artırılmalı.')

    def tick(self):
        current, mono = local_time(self.clock()), self.monotonic()
        for name, task in self.tasks.items():
            if task.future and task.future.done():
                try:
                    result = task.future.result()
                    task.failures = 0
                    if name != 'full_scan' or not isinstance(result,dict) or result.get('cycle_complete'):
                        self.state['last_'+name+('_check' if name in ('kap','macro','alarm','push','company_site') else '')] = current.isoformat(timespec='seconds')
                    if name == 'full_scan' and isinstance(result,dict):
                        self.state['last_full_scan_batch']=current.isoformat(timespec='seconds')
                    report=diagnostics(result.get('diagnostics')) if isinstance(result,dict) else {}
                    task_status=('OK_WITH_SKIPS' if report.get('successful') else 'SKIPPED') if report.get('skipped') else 'OK'
                    self.state['tasks'][name] = {'status':task_status, 'last_success':current.isoformat(timespec='seconds'),**({'diagnostics':report} if report else {})}
                    if name == 'yarin_top10':
                        self.state['yarin_completed_day'] = task.scheduled_day
                    summary=' '+str(result) if isinstance(result,(int,float)) else ''
                    if isinstance(result,dict) and name=='alarm':
                        summary=' piyasa kapalı - atlandı' if result.get('skipped') else f" {result.get('kontrol_edilen_alarm',0)} kontrol / {result.get('tetiklenen_alarm',0)} tetik"
                    elif isinstance(result,dict) and name=='push':
                        summary=f" {result.get('sent',0)} gönderildi / {result.get('failed',0)} hata"
                    if report:
                        summary+=' '+ ' '.join(f'{key}={report.get(key,0)}' for key in ('processed','successful','skipped','unsupported','failed','tls_errors','http_errors','response_too_large','systemic_errors'))
                    if name != 'priority' or (result.get('diagnostics',{}).get('processed',0) if isinstance(result,dict) else result):
                        logging.info('[%s] %s %s%s', current.strftime('%H:%M:%S'), name.upper(),task_status, summary)
                    task.next_due = mono + task.interval
                except Exception as error:
                    issue=describe(error)
                    site_isolated=(name=='company_site' and isinstance(error,TaskIssue) and error.isolated
                        and (issue['code'] in ('NETWORK_TLS','NETWORK_DNS','NETWORK_CONNECTION','NETWORK_TIMEOUT',
                             'HTTP_UNAVAILABLE','HTTP_RATE_LIMIT','HTTP_BLOCKED','SOURCE_RESPONSE_TOO_LARGE','SOURCE_URL_INVALID')
                             or (issue['code']=='HTTP_REQUEST' and issue.get('http_status') in (404,410))))
                    systemic=(name=='company_site' and isinstance(error,TaskIssue) and error.systemic
                        and issue['code'] in ('NETWORK_TLS','NETWORK_DNS','NETWORK_CONNECTION','NETWORK_TIMEOUT','HTTP_UNAVAILABLE','HTTP_RATE_LIMIT'))
                    progressed=(not systemic and isinstance(error,TaskIssue) and error.completed>0
                                and (issue['category'] in ('REMOTE','SOURCE_DATA')
                                     or (name=='company_site' and issue['code']=='NETWORK_TLS')))
                    # Keep partial progress moving, but retain the failure counter
                    # and DEGRADED issue; never treat the failed stocks as successful.
                    task.failures += 1
                    exponent=0 if progressed or site_isolated else min(task.failures-1,6)
                    delay = min(900, max(5,task.interval) * 2 ** exponent)
                    if (progressed or site_isolated) and name=='company_site':delay=min(delay,30)
                    task.next_due = mono + delay
                    detail = {'task':name, 'error':type(error).__name__, 'at':current.isoformat(timespec='seconds'),'last_error':issue}
                    self.state['son_hata'] = detail
                    status='DEGRADED' if progressed or site_isolated or (systemic and error.completed>0) else 'RETRYING' if issue['category'] in ('REMOTE','SOURCE_DATA') or issue['code'] in ('STORAGE_PENDING','STORAGE_SHUTDOWN') else 'ERROR'
                    self.state['tasks'][name] = {'status':status, 'failures':task.failures, 'retry_in_seconds':delay, 'completed':error.completed if isinstance(error,TaskIssue) else 0, **detail,**({'diagnostics':error.details} if isinstance(error,TaskIssue) and error.details else {})}
                    logging.warning('[%s] %s %s code=%s category=%s retry=%ss',current.strftime('%H:%M:%S'),name.upper(),status,issue['code'],issue['category'],delay)
                    if not isinstance(error,TaskIssue):log_source(error,'TASK')
                    # Stack locations only: never format exception args or source lines containing secrets.
                    import traceback
                    frames=traceback.extract_tb(error.__traceback__)[-4:]
                    logging.warning('[TASK_TRACE] %s %s',name,[(Path(f.filename).name,f.lineno,f.name) for f in frames])
                task.future = None
        if not self.stop.is_set():
            # Priority queue gets the technical lane before another bulk batch.
            order = sorted(self.tasks, key=lambda name: (name != 'priority',name))
            for name in order:
                task = self.tasks[name]
                if task.future or mono < task.next_due:
                    continue
                if name == 'full_scan' and 'bootstrap' in self.tasks and not (self.directory/'public_bootstrap_complete.json').exists():
                    continue
                if name == 'bootstrap' and (self.directory/'public_bootstrap_complete.json').exists():
                    continue
                if name=='indicator_performance':
                    from sinyal_performansi import indicator_enabled
                    if not indicator_enabled():continue
                if name=='sector_strength':
                    from piyasa_baglami import sector_enabled
                    if not sector_enabled():continue
                if name=='market_regime':
                    from piyasa_baglami import regime_enabled
                    if not regime_enabled():continue
                if name=='intraday_signals':
                    from gunluk_al_sat import enabled
                    if not enabled():continue
                if name in ('intraday_top10','full_scan','market_context','intraday_signals') and not market_open(current,self.holiday):
                    if name=='intraday_signals' and mono>=self._intraday_closed_log_due:
                        logging.info('[INTRADAY_SIGNAL] market_closed skip')
                        self._intraday_closed_log_due=mono+max(INTRADAY_SIGNAL_INTERVAL,task.interval)
                    continue
                if name == 'yarin_top10':
                    day=current.date().isoformat()
                    if not after_close(current,self.holiday) or self.state['yarin_completed_day'] == day or self.snapshot_exists(day):
                        continue
                    task.scheduled_day=day
                if name in TECHNICAL and any(t.future for n,t in self.tasks.items() if n in TECHNICAL):
                    continue
                previous=self.state['tasks'].get(name,{})
                self.state['tasks'][name]={'status':'RUNNING','started_at':current.isoformat(timespec='seconds'),**({k:previous[k] for k in ('last_error','diagnostics') if previous.get(k)})}
                task.future=self.executor.submit(task.callback)
        for name,task in self.tasks.items():
            state=self.state['tasks'].get(name,{})
            if not task.future and state.get('status') in ('ERROR','RETRYING','DEGRADED'):
                state['retry_in_seconds']=max(0,round(task.next_due-mono,1))
        self.persist()

    def request_stop(self, *_):
        from storage_izleme import shutdown_writes
        shutdown_writes(self.stop)
        self.stop.set()

    def shutdown(self):
        from storage_izleme import shutdown_writes
        shutdown_writes(self.stop)
        self.stop.set()
        self.state['motor_durumu']='STOPPING';self.persist()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.tick()  # Collect completed jobs, without scheduling more work.
        self.state['motor_durumu']='STOPPED';self.persist()

    def run(self):
        try:
            while not self.stop.is_set():
                self.tick()
                self.stop.wait(1)
        finally:
            self.shutdown()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true',help='Offline configuration/import check; no providers or sends')
    args=parser.parse_args()
    os.chdir(ROOT)
    paths().ensure()
    # Legacy collectors use time.strftime/datetime.now; align those too.
    os.environ['TZ']='Europe/Istanbul'
    if hasattr(time,'tzset'):
        time.tzset()
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    if args.check:
        from ana_motor_gorevleri import check_configuration
        print(json.dumps(check_configuration(),ensure_ascii=False));return
    with worker_lock(runtime_dir()):
        from disk_koruma import reclaim_once
        from atomik_temp_temizligi import cleanup_atomic_temps
        from v6_storage.config import Settings
        if Settings.from_env().mode=='legacy':
            cleanup_atomic_temps(paths(),resumable=True)
            reclaim_once(paths())
        else:logging.info('[STORAGE_V6] migration_mode=true automatic_cleanup=false legacy_wal_rewrite=false')
        from ana_motor_gorevleri import WorkerTasks
        from cloud_bootstrap import bootstrap_public
        bootstrap_public()
        adapter=WorkerTasks()
        motor=AnaMotor(adapter.callbacks())
        adapter.stop=motor.stop
        from storage_izleme import bind_shutdown
        bind_shutdown(motor.stop)
        logging.info('[WORKER] başladı')
        signal.signal(signal.SIGTERM,motor.request_stop)
        signal.signal(signal.SIGINT,motor.request_stop)
        from disk_bakimi import DiskMaintenance
        maintenance=DiskMaintenance(paths(),motor.stop).start()
        try:
            motor.run()
        finally:
            maintenance.close()
            adapter.close()


if __name__=='__main__':
    main()
