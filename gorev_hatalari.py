"""Fixed public error vocabulary; never expose exception messages, URLs or secrets."""
import errno
from contextvars import ContextVar
from contextlib import contextmanager
import requests
import socket

ERRORS={
 'DISK_FULL':('STORAGE','Kalıcı diskte boş alan yetersiz.',True),
 'STORAGE_PERMISSION':('STORAGE','Kalıcı veri yazma/okuma izni yok.',False),
 'STORAGE_IO':('STORAGE','Kalıcı veri dosyası okunamadı veya yazılamadı.',True),
 'NETWORK_TIMEOUT':('REMOTE','Dış veri kaynağı zaman aşımına uğradı.',True),
 'NETWORK_CONNECTION':('REMOTE','Dış veri kaynağına bağlanılamadı.',True),
 'HTTP_RATE_LIMIT':('REMOTE','Dış veri kaynağı istek sınırı uyguluyor.',True),
 'HTTP_BLOCKED':('REMOTE','Dış veri kaynağı erişimi reddediyor.',True),
 'HTTP_AUTH':('CONFIG','Dış veri kaynağı yetkilendirmesi başarısız.',False),
 'HTTP_UNAVAILABLE':('REMOTE','Dış veri kaynağı geçici olarak kullanılamıyor.',True),
 'HTTP_REQUEST':('CONFIG','Dış kaynak isteği veya endpoint doğrulanmalı.',False),
 'PROVIDER_DATA':('SOURCE_DATA','Sağlayıcının verisi eksik veya geçersiz.',True),
 'ANALYSIS_NO_RESULT':('UNKNOWN','Analiz sonuç üretmedi; kaynak veya analiz kontrol edilmeli.',True),
 'EMPTY_UNIVERSE':('SOURCE_DATA','Hisse evreni alınamadı.',True),
 'CODE_ERROR':('CODE','Görev kodunda veya veri modelinde hata oluştu.',False),
 'TASK_ERROR':('UNKNOWN','Görev tamamlanamadı; hata ayrıntısı loglarda.',True),
}
CAPTURE=ContextVar('worker_error_capture',default=None)


def public_issue(value):
    code=value.get('code') if isinstance(value,dict) else 'TASK_ERROR'
    if not isinstance(code,str) or code not in ERRORS:code='TASK_ERROR'
    category,message,retryable=ERRORS[code]
    result={'code':code,'category':category,'message':message,'retryable':retryable}
    status=value.get('http_status') if isinstance(value,dict) else None
    if isinstance(status,int) and 400<=status<=599:result['http_status']=status
    return result


def strongest(issues):
    order={'STORAGE':0,'CODE':1,'CONFIG':2,'UNKNOWN':3,'SOURCE_DATA':4,'REMOTE':5}
    return min((public_issue(i) for i in issues),key=lambda i:order[i['category']])


def describe(error,stage=None):
    if isinstance(error,TaskIssue):return public_issue(error.issue)
    status=getattr(error,'status',None) or getattr(getattr(error,'response',None),'status_code',None)
    code='TASK_ERROR'
    if isinstance(error,OSError) and error.errno in (errno.ENOSPC,errno.EDQUOT):code='DISK_FULL'
    elif isinstance(error,OSError) and error.errno in (errno.EACCES,errno.EPERM):code='STORAGE_PERMISSION'
    elif isinstance(error,(requests.Timeout,TimeoutError)):code='NETWORK_TIMEOUT'
    elif isinstance(error,(requests.ConnectionError,ConnectionError,socket.gaierror)):code='NETWORK_CONNECTION'
    elif status==429:code='HTTP_RATE_LIMIT'
    elif status==403:code='HTTP_BLOCKED'
    elif status==401:code='HTTP_AUTH'
    elif isinstance(status,int) and status>=500:code='HTTP_UNAVAILABLE'
    elif isinstance(status,int) and status>=400:code='HTTP_REQUEST'
    elif isinstance(error,(ValueError,KeyError,TypeError,AttributeError,NameError,ImportError)):
        code='PROVIDER_DATA' if stage=='PROVIDER' else 'CODE_ERROR'
    elif isinstance(error,OSError):code='STORAGE_IO'
    return public_issue({'code':code,'http_status':status})


class TaskIssue(RuntimeError):
    def __init__(self,issue,completed=0):
        self.issue=public_issue(issue);self.completed=completed
        super().__init__(self.issue['code'])


@contextmanager
def capture():
    issues=[];token=CAPTURE.set(issues)
    try:yield issues
    finally:CAPTURE.reset(token)


def remember(error,stage=None):
    issues=CAPTURE.get()
    if issues is not None and not issues:issues.append(describe(error,stage))
