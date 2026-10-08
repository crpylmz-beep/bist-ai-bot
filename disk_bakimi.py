"""Bounded, low-priority scratch proof rounds under the existing worker lock.

Only proven scratch is removed. Bounded progress survives restarts; each round
revalidates descriptors, leases and fingerprints before any removal.
"""
from contextvars import copy_context
import logging
import os
import threading
from atomik_temp_temizligi import inspection_stop
from storage_izleme import GrowthMonitor
from disk_forensik import inspect_atomic_temps,worker_scope_matches


class DiskMaintenance:
    def __init__(self,location,stop,*,interval=300,budget_seconds=60,inspector=inspect_atomic_temps):
        self.location=location;self.stop=stop;self.interval=interval;self.budget=budget_seconds
        self.inspector=inspector;self.visited=set();self.thread=None;self.growth=GrowthMonitor()

    def round(self):
        if not worker_scope_matches(self.location):raise RuntimeError('WORKER_LOCK_REQUIRED')
        from v6_storage.config import Settings
        legacy=Settings.from_env().mode=='legacy'
        token=inspection_stop.set(self.stop)
        try:result=self.inspector(self.location,cleanup=legacy,budget_seconds=self.budget,skip_identifiers=self.visited,release_locks_during_proof=True,resumable=True)
        finally:inspection_stop.reset(token)
        # Timed-out and locked files are retried, but after the other candidates.
        # Each subsequent proof still reacquires every lease/lock and inode check.
        processed=[f for f in result.get('findings',[]) if f['reason']!='BUDGET_EXHAUSTED']
        exhausted=[f for f in result.get('findings',[]) if f['reason']=='BUDGET_EXHAUSTED']
        if not processed and exhausted:processed=exhausted[:1]
        # Resumable inspector overrides a cursor skip for unfinished checkpoints.
        self.visited.update(f['masked_file'] for f in processed)
        if result['scanned']==0:self.visited.clear()
        from history_journal import HistoryJournal
        target=self.location.runtime/'ai_ogrenme_gecmisi.json'
        if legacy and target.exists():
            try:
                merged=HistoryJournal(target).flush()
                if merged:logging.info('[STORAGE_WAL] merged_transactions=%d',merged)
            except (OSError,ValueError) as error:
                logging.warning('[STORAGE_WAL] pending_retained=true type=%s errno=%s',type(error).__name__,getattr(error,'errno',None))
        if self.location.root:self.growth.sample(self.location)
        return result

    def _run(self):
        # Linux per-thread niceness; never lower priority of the market worker.
        try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
        except (AttributeError,OSError):logging.info('[DISK_MAINTENANCE] thread_priority_unavailable')
        import time
        next_round=time.monotonic()+self.interval
        while not self.stop.wait(max(0,next_round-time.monotonic())):
            next_round=time.monotonic()+self.interval
            try:self.round()
            except Exception as error:
                logging.warning('[DISK_MAINTENANCE] round_failed type=%s errno=%s',type(error).__name__,getattr(error,'errno',None))

    def start(self):
        if not worker_scope_matches(self.location):raise RuntimeError('WORKER_LOCK_REQUIRED')
        if self.thread is not None:raise RuntimeError('Maintenance already started')
        context=copy_context()
        self.thread=threading.Thread(target=lambda:context.run(self._run),name='disk-maintenance',daemon=True)
        if self.location.root:self.growth.sample(self.location)
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread is not None:self.thread.join()  # worker flock retained until proof has finished
