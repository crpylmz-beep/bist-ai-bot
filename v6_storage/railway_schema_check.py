"""Opt-in, one read-only schema check per launcher process; no file markers."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

FLAG='BIST_RUN_POSTGRES_SCHEMA_CHECK_ONCE'
_lock=threading.Lock()
_attempted=False
SAFE_ERRORS=frozenset(('POSTGRES_NOT_CONFIGURED','POSTGRES_CONFIGURATION_INVALID',
 'POSTGRES_TLS_REQUIRED','STORAGE_MODE_INVALID','STORAGE_CONFIGURATION_INVALID',
 'POSTGRES_DEPENDENCY_MISSING','POSTGRES_OPERATION_FAILED','POSTGRES_AUTH_FAILED',
 'POSTGRES_PERMISSION_DENIED','POSTGRES_DATABASE_NOT_FOUND','POSTGRES_TABLE_MISSING',
 'POSTGRES_SCHEMA_MISSING','POSTGRES_SQL_SYNTAX','POSTGRES_OBJECT_CONFLICT',
 'POSTGRES_DISK_FULL','POSTGRES_CONNECTION_LIMIT','POSTGRES_NOT_READY',
 'POSTGRES_CONNECTION_FAILED','POSTGRES_CONNECTION_TIMEOUT','SCHEMA_MIGRATION_REQUIRED',
 'SCHEMA_MIGRATION_CHECKSUM_MISMATCH'))
SAFE_STAGES=frozenset(('CONFIGURATION','DEPENDENCIES','CONNECT','SCHEMA_VERIFY'))
SAFE_STATES=frozenset(('28P01','28000','42501','3D000','42P01','3F000','42601','42P07',
 '53100','53300','57P03','08000','08001','08003','08004','08006','08007','08P01'))


def _log(status,code=None,stage=None,state=None):
    value={'status':status,'read_only':True}
    if code:value['error_code']=code
    if stage in SAFE_STAGES:value['stage']=stage
    if state in SAFE_STATES:value['sqlstate']=state
    logging.info('[V6_SCHEMA_CHECK] %s',json.dumps(value,sort_keys=True))


def run_check(root,runner=None):
    """Only --check; never default schema, migrate, ensure(), or credential output."""
    if os.environ.get('BIST_RUN_POSTGRES_SCHEMA_ONCE')=='1':
        _log('BLOCKED','WRITE_CAPABLE_SCHEMA_FLAG_ENABLED');return False
    runner=runner or subprocess.run
    try:
        result=runner([sys.executable,'-B','-m','v6_storage','schema','--check'],
            cwd=Path(root),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,timeout=45)
        if not isinstance(result.stdout,str) or len(result.stdout)>8192:
            _log('FAILED','UNVERIFIED_OUTPUT');return False
        value=json.loads(result.stdout)
        if not isinstance(value,dict):raise ValueError()
        if result.returncode==0:
            if value.get('verified') is True and value.get('read_only') is True and value.get('applied')==[]:
                _log('SUCCESS');return True
            _log('FAILED','UNVERIFIED_OUTPUT');return False
        code=value.get('error')
        _log('FAILED',code if isinstance(code,str) and code in SAFE_ERRORS else 'UNKNOWN_SAFE_ERROR',
             value.get('stage') if isinstance(value.get('stage'),str) else None,
             value.get('sqlstate') if isinstance(value.get('sqlstate'),str) else None)
        return False
    except subprocess.TimeoutExpired:
        _log('FAILED','CHECK_TIMEOUT');return False
    except OSError:
        _log('FAILED','CHECK_LAUNCH_FAILED');return False
    except Exception:
        _log('FAILED','UNVERIFIED_OUTPUT');return False


def start_once(root):
    """Flag off by default. No retry; other worker/web processes continue."""
    global _attempted
    if os.environ.get(FLAG)!='1':return False
    with _lock:
        if _attempted:return False
        _attempted=True
    try:
        threading.Thread(target=run_check,args=(root,),name='v6-readonly-schema-check',daemon=True).start()
        return True
    except Exception:
        _log('FAILED','CHECK_LAUNCH_FAILED');return False
