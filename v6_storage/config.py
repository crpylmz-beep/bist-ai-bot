"""Environment-only configuration; default legacy never opens external clients."""
from dataclasses import dataclass
import errno
import os
from urllib.parse import urlparse


class StorageError(OSError):
    def __init__(self,code):
        self.storage_code=code
        super().__init__(errno.EIO,code)


@dataclass(frozen=True)
class Settings:
    mode:str='legacy'
    dsn:str=''
    cutover_ack:bool=False
    batch_size:int=100
    pool_size:int=4
    timeout:int=10

    @classmethod
    def from_env(cls,env=None):
        env=os.environ if env is None else env
        mode=env.get('STORAGE_BACKEND','legacy').strip().lower()
        if mode not in ('legacy','shadow','postgres'):raise StorageError('STORAGE_MODE_INVALID')
        def bounded(name,default,minimum,maximum):
            try:value=int(env.get(name,str(default)))
            except ValueError:raise StorageError('STORAGE_CONFIGURATION_INVALID') from None
            if not minimum<=value<=maximum:raise StorageError('STORAGE_CONFIGURATION_INVALID')
            return value
        return cls(mode,env.get('BIST_POSTGRES_DSN') or env.get('DATABASE_URL',''),env.get('STORAGE_POSTGRES_CUTOVER_ACK','false').lower()=='true',bounded('STORAGE_BATCH_SIZE',100,1,1000),bounded('STORAGE_POOL_SIZE',4,1,8),bounded('STORAGE_TIMEOUT_SECONDS',10,1,30))

    def __repr__(self):return f'Settings(mode={self.mode!r},configured={bool(self.dsn)},cutover_ack={self.cutover_ack})'

    def require_database(self):
        if not self.dsn:raise StorageError('POSTGRES_NOT_CONFIGURED')
        parsed=urlparse(self.dsn)
        if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname:raise StorageError('POSTGRES_CONFIGURATION_INVALID')
        # Remote plaintext connections are prohibited; local disposable tests may use trust.
        if parsed.hostname not in ('127.0.0.1','localhost','::1') and not any(x in parsed.query.split('&') for x in ('sslmode=require','sslmode=verify-ca','sslmode=verify-full')):
            raise StorageError('POSTGRES_TLS_REQUIRED')
