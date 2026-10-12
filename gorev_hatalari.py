"""Fixed public error vocabulary; never expose exception messages, URLs or secrets."""
import errno
from contextvars import ContextVar
from contextlib import contextmanager
import requests
import socket
import logging
import os
import re
import traceback
from pathlib import Path
import httpx
from borsapy.exceptions import (APIError, AuthenticationError, RateLimitError,
    DataNotAvailableError, TickerNotFoundError, InvalidPeriodError, InvalidIntervalError)

ERRORS={
 'SOURCE_ACCESS_RESTRICTED':('SOURCE_DATA','Haber kaynağı erişim koşulları nedeniyle işlenmedi.',True),
 'SOURCE_ROBOTS_DENIED':('SOURCE_DATA','Haber kaynağı robots.txt politikasına göre işlenmedi.',True),
 'SOURCE_INVALID_FEED':('SOURCE_DATA','Haber kaynağı geçerli RSS sağlamadı.',True),
 'SOURCE_CRAWL_DELAY':('SOURCE_DATA','Haber kaynağının erişim aralığı bu taramaya uygun değil.',True),
 'POSTGRES_UNAVAILABLE':('STORAGE','PostgreSQL bağlantısı/işlemi tamamlanamadı; kalıcı kaynak korunuyor.',True),
 'STORAGE_MIGRATION_REQUIRED':('CONFIG','Depolama migration veya doğrulanmış geçiş onayı gerekiyor.',False),
 'STORAGE_IMMUTABLE_CONFLICT':('STORAGE','Değiştirilemez kayıt çakışması; kaynaklar korunuyor.',False),
 'STORAGE_SHADOW_MISMATCH':('STORAGE','Legacy/PostgreSQL karşılaştırması farklı; geçiş yapılmamalı.',False),
 'STORAGE_PENDING':('STORAGE','Değişiklikler güvenli WAL kaydında; JSON commit bekliyor.',True),
 'STORAGE_SHUTDOWN':('STORAGE','Kapanış sırasında büyük yazım güvenle iptal edildi.',True),
 'WAL_CONFLICT':('STORAGE','Kalıcı journal ile mevcut kayıt çakışıyor; iki kayıt korunuyor.',False),
 'WAL_CORRUPT':('STORAGE','Kalıcı journal doğrulanamadı; mevcut veriler korunuyor.',False),
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
 'OUTSIDE_EQUITY_UNIVERSE':('SOURCE_DATA','Sembol resmî XUTUM pay tarama evreninde değil.',True),
 'PROVIDER_UNSUPPORTED':('SOURCE_DATA','TradingView bu sembolü desteklemiyor (invalid symbol).',True),
 'SOURCE_URL_INVALID':('SOURCE_DATA','Şirket kaynağı URL/yönlendirme güvenlik kuralını karşılamıyor.',True),
 'SOURCE_RESPONSE_TOO_LARGE':('SOURCE_DATA','Dış kaynak yanıtı güvenli boyut sınırını aştı; indirme durduruldu.',True),
 'PROVIDER_API_ERROR':('REMOTE','Fiyat sağlayıcısı isteği başarısız; kaynak hata konumu loglarda.',True),
 'NETWORK_TLS':('CONFIG','Dış kaynak TLS bağlantısı doğrulanamadı.',False),
 'NETWORK_DNS':('REMOTE','Dış kaynağın adresi çözümlenemedi.',True),
 'PROVIDER_CONFIG':('CONFIG','Fiyat sağlayıcısı dönem/aralık ayarı geçersiz.',False),
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


def diagnostics(value):
    if not isinstance(value,dict):return {}
    result={k:max(0,min(v,100000)) for k,v in value.items()
            if k in ('processed','successful','skipped','unsupported','failed','tls_errors','http_errors','response_too_large','systemic_errors')
            and isinstance(v,int) and not isinstance(v,bool)}
    rows=value.get('reasons',[])
    if not isinstance(rows,list):rows=[]
    result['reasons']=[{'symbol':row['symbol'],'reason':public_issue(row.get('reason') if isinstance(row.get('reason'),dict) else row)}
        for row in rows[:25] if isinstance(row,dict)
        and isinstance(row.get('symbol'),str) and re.fullmatch(r'[A-Z0-9]{2,12}',row['symbol'])]
    return result


def strongest(issues):
    order={'STORAGE':0,'CODE':1,'CONFIG':2,'UNKNOWN':3,'SOURCE_DATA':4,'REMOTE':5}
    return min((public_issue(i) for i in issues),key=lambda i:order[i['category']])


def describe(error,stage=None):
    if isinstance(error,TaskIssue):return public_issue(error.issue)
    status=getattr(error,'status',None) or getattr(error,'status_code',None) or getattr(getattr(error,'response',None),'status_code',None)
    code='TASK_ERROR'
    storage_code=getattr(error,'storage_code',None)
    if storage_code in ('POSTGRES_OPERATION_FAILED','POSTGRES_UNAVAILABLE_NO_VERIFIED_BASELINE'):code='POSTGRES_UNAVAILABLE'
    elif storage_code=='SHADOW_MISMATCH':code='STORAGE_SHADOW_MISMATCH'
    elif storage_code in ('IMMUTABLE_RECORD_CONFLICT','IMMUTABLE_SNAPSHOT_METADATA_CONFLICT','IMMUTABLE_SNAPSHOT_MEMBERSHIP_CONFLICT','OUTBOX_IMMUTABLE_CONFLICT','OUTBOX_CHECKSUM_CONFLICT'):code='STORAGE_IMMUTABLE_CONFLICT'
    elif storage_code in ('POSTGRES_CUTOVER_NOT_APPROVED','POSTGRES_SOURCE_NOT_VERIFIED','POSTGRES_DATASET_NOT_MIGRATED','POSTGRES_PROJECTION_NOT_VERIFIED','POSTGRES_PROJECTION_RECORD_MISSING','SCHEMA_MIGRATION_REQUIRED','SCHEMA_MIGRATION_CHECKSUM_MISMATCH','LEGACY_ROLLBACK_REQUIRES_VERIFIED_EXPORT','POSTGRES_NOT_CONFIGURED','POSTGRES_TLS_REQUIRED'):code='STORAGE_MIGRATION_REQUIRED'
    elif getattr(error,'storage_code',None) in ('STORAGE_PENDING','WAL_CONFLICT','WAL_CORRUPT'):code=error.storage_code
    elif isinstance(error,OSError) and error.errno==errno.ECANCELED:code='STORAGE_SHUTDOWN'
    elif stage=='COMPANY_SITE' and isinstance(error,(requests.exceptions.InvalidURL,requests.exceptions.TooManyRedirects)):code='SOURCE_URL_INVALID'
    elif isinstance(error,SiteUrlError):code='SOURCE_URL_INVALID'
    elif isinstance(error,ResponseLimitError):code='SOURCE_RESPONSE_TOO_LARGE'
    elif isinstance(error,OSError) and error.errno in (errno.ENOSPC,errno.EDQUOT):code='DISK_FULL'
    elif isinstance(error,OSError) and error.errno in (errno.EACCES,errno.EPERM):code='STORAGE_PERMISSION'
    elif isinstance(error,requests.exceptions.SSLError):code='NETWORK_TLS'
    elif isinstance(error,socket.gaierror):code='NETWORK_DNS'
    elif isinstance(error,(requests.Timeout,TimeoutError,httpx.TimeoutException)):code='NETWORK_TIMEOUT'
    elif isinstance(error,(requests.ConnectionError,ConnectionError,httpx.NetworkError)):code='NETWORK_CONNECTION'
    elif status==429:code='HTTP_RATE_LIMIT'
    elif status==403:code='HTTP_BLOCKED'
    elif status==401:code='HTTP_AUTH'
    elif isinstance(status,int) and status>=500:code='HTTP_UNAVAILABLE'
    elif isinstance(status,int) and status>=400:code='HTTP_REQUEST'
    elif isinstance(error,RateLimitError):code='HTTP_RATE_LIMIT'
    elif isinstance(error,AuthenticationError):code='HTTP_AUTH'
    elif isinstance(error,(DataNotAvailableError,TickerNotFoundError)):code='PROVIDER_DATA'
    elif isinstance(error,(InvalidPeriodError,InvalidIntervalError)):code='PROVIDER_CONFIG'
    elif isinstance(error,APIError):
        # Exact TradingView protocol reason, not generic network/no-data text.
        if re.search(r"['\"]invalid symbol['\"]\s*\]\s*$",str(error),re.I):
            return public_issue({'code':'PROVIDER_UNSUPPORTED'})
        cause=error.__cause__
        cause_issue=describe(cause,stage) if cause is not None and cause is not error and not isinstance(cause,APIError) else None
        if cause_issue and cause_issue['code']!='TASK_ERROR':return cause_issue
        code='PROVIDER_API_ERROR'
    elif isinstance(error,(ValueError,KeyError,TypeError,AttributeError,NameError,ImportError)):
        code='PROVIDER_DATA' if stage=='PROVIDER' else 'CODE_ERROR'
    elif isinstance(error,OSError):code='STORAGE_IO'
    return public_issue({'code':code,'http_status':status})


class SiteUrlError(ValueError):
    pass


class ResponseLimitError(Exception):
    pass


class TaskIssue(RuntimeError):
    def __init__(self,issue,completed=0,details=None,isolated=False,systemic=False):
        self.issue=public_issue(issue);self.completed=completed;self.details=diagnostics(details)
        self.isolated=isolated;self.systemic=systemic
        super().__init__(self.issue['code'])


@contextmanager
def capture():
    issues=[];token=CAPTURE.set(issues)
    try:yield issues
    finally:CAPTURE.reset(token)


def safe_message(error):
    """Bounded operational message for private logs, never for health/state."""
    try:text=str(error)
    except Exception:return '[message unavailable]'
    # Mask injected secrets before processing or truncating a message.
    for name,value in os.environ.items():
        if value and re.search(r'TOKEN|SECRET|PASSWORD|PRIVATE|AUTH|KEY|COOKIE',name,re.I):
            text=text.replace(value,'[redacted]')
    text=re.sub(r'-----BEGIN [^-]+-----.*?(?:-----END [^-]+-----|$)','[redacted]',text,flags=re.S)
    text=re.sub(r'(?i)\b(?:https?|wss?|ftp)://[^\s\"\'<>]+','[url]',text)
    text=re.sub(r'(?i)\b(?:bearer|basic)\s+[^\s,;]+','[redacted]',text)
    text=re.sub(r"(?i)\b(?:authorization|cookie|password|passwd|token|secret|api[_-]?key|auth|p256dh|endpoint|user[_-]?id)\b[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",'[redacted]',text)
    # Payloads/headers are not needed to identify a failure.
    text=re.sub(r'[\{<].*','[payload omitted]',text,flags=re.S)
    text=re.sub(r'(?i)\b(?:TOKEN|SECRET)\b','[redacted]',text)
    text=re.sub(r'(?<!\w)[A-Za-z0-9_+/=-]{24,}(?!\w)','[redacted]',text)
    text=re.sub(r'(?:[A-Za-z]:\\|/)(?:[^\s\"\']+)','[path]',text)
    text=re.sub(r'[^\s@]+@[^\s@]+','[redacted]',text)
    text=' '.join(text.split())
    return text[:240] or '[empty message]'


def log_source(error,stage=None):
    # Never log exception args, locals or traceback source lines directly.
    safe_stage=stage if stage in ('PROVIDER','ANALYSIS','COMPANY_SITE','TASK') else 'ADAPTER'
    seen=set();current=error
    for depth in range(3):
        if current is None or id(current) in seen:break
        seen.add(id(current))
        frames=traceback.extract_tb(current.__traceback__)[-5:]
        logging.warning('[SOURCE_TRACE] stage=%s depth=%s error=%s code=%s message=%s frames=%s',
            safe_stage,depth,type(current).__name__,describe(current,safe_stage)['code'],safe_message(current),
            [(Path(f.filename).name,f.lineno,f.name) for f in frames])
        current=current.__cause__ or (None if current.__suppress_context__ else current.__context__)


def remember(error,stage=None,stock=None):
    issues=CAPTURE.get()
    if issues is not None and not issues:
        issue=describe(error,stage);issues.append(issue)
        log_source(error,stage)
        if isinstance(stock,str) and re.fullmatch(r'[A-Z0-9]{2,12}',stock):
            logging.warning('[PROVIDER_SYMBOL] symbol=%s tradingview=BIST:%s code=%s',stock,stock,issue['code'])
