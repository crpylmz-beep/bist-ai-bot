"""Environment-only configuration; default legacy never opens external clients."""
from dataclasses import dataclass
import errno
import os
from urllib.parse import urlparse,parse_qs


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
        self.connection_dsn()

    def connection_dsn(self):
        """Return a TLS-enforcing DSN without changing environment or stored secrets."""
        if not self.dsn:raise StorageError('POSTGRES_NOT_CONFIGURED')
        try:
            parsed=urlparse(self.dsn)
            hostname=parsed.hostname
        except ValueError:raise StorageError('POSTGRES_CONFIGURATION_INVALID') from None
        if parsed.scheme not in ('postgres','postgresql') or not hostname or parsed.fragment:
            raise StorageError('POSTGRES_CONFIGURATION_INVALID')
        modes=parse_qs(parsed.query,keep_blank_values=True).get('sslmode')
        if modes is not None:
            if modes not in (['require'],['verify-ca'],['verify-full']):
                raise StorageError('POSTGRES_TLS_REQUIRED')
            return self.dsn
        # Retain existing loopback-only disposable-test behavior. Remote connections
        # explicitly require TLS even when libpq environment defaults prefer plaintext.
        if hostname in ('127.0.0.1','localhost','::1'):return self.dsn
        separator='&' if '?' in self.dsn else '?'
        return self.dsn+separator+'sslmode=require'


@dataclass(frozen=True, repr=False)
class R2Settings:
    bucket: str = ''
    endpoint: str = ''
    access_key: str = ''
    secret_key: str = ''
    private_confirmed: bool = False
    connect_timeout: int = 10
    read_timeout: int = 30

    def __repr__(self):
        return f'R2Settings(configured={bool(self.bucket and self.endpoint and self.access_key and self.secret_key)})'

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        def timeout(name, default):
            try: value = int(env.get(name, str(default)))
            except (ValueError, TypeError): raise StorageError('R2_CONFIGURATION_INVALID') from None
            if not 1 <= value <= 60: raise StorageError('R2_CONFIGURATION_INVALID')
            return value
        return cls(env.get('R2_BUCKET', ''), env.get('R2_ENDPOINT_URL', ''),
                   env.get('R2_ACCESS_KEY_ID', ''), env.get('R2_SECRET_ACCESS_KEY', ''),
                   env.get('R2_PRIVATE_BUCKET_CONFIRMED', 'false').lower() == 'true',
                   timeout('R2_CONNECT_TIMEOUT_SECONDS', 10), timeout('R2_READ_TIMEOUT_SECONDS', 30))

    def require(self):
        if not self.bucket or not self.access_key or not self.secret_key:
            raise StorageError('R2_NOT_CONFIGURED')
        try: parsed = urlparse(self.endpoint)
        except ValueError: raise StorageError('R2_ENDPOINT_INVALID') from None
        if (parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.r2.cloudflarestorage.com')
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')):
            raise StorageError('R2_ENDPOINT_INVALID')
        if not self.private_confirmed:
            raise StorageError('R2_PRIVATE_BUCKET_CONFIRMATION_REQUIRED')
