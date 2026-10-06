"""Shared POSIX persistence paths; unset BIST_DATA_DIR preserves local layout."""
from pathlib import Path
import argparse
import fcntl
import os
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
PRIVATE_NAMES = {'kullanici_seviyeleri.json', 'fiyat_alarmlari.json',
                 'push_subscriptions.json', 'pending_notifications.json'}
RUNTIME_LEGACY = {'kap_son_gorulen.json': 'kap_son_gorulen.json',
                  **{name:'webapp/data/'+name for name in (
                      'makro_gorulen.json','canli_motor_durum.json','tahmin_gecmisi.json',
                      'gun_ici_gecersiz_semboller.json','ai_ogrenme_gecmisi.json',
                      'haber_zeka_gecmisi.json','makro_ai_gecmisi.json')}}


class DataPaths:
    def __init__(self, environ=None, repo_root=None):
        env = os.environ if environ is None else environ
        self.repo = Path(repo_root or ROOT).resolve()
        self.web = self.repo/'webapp'
        value = env.get('BIST_DATA_DIR', '').strip()
        if value and not Path(value).expanduser().is_absolute():
            raise ValueError('BIST_DATA_DIR mutlak bir mount yolu olmalı')
        self.root = Path(value).expanduser().resolve() if value else None
        if self.root and (self.root == self.web or self.root.is_relative_to(self.web)):
            raise ValueError('BIST_DATA_DIR public web root altında olamaz')
        self.public = self.root/'public' if self.root else self.web/'data'
        self.users = self.root/'private'/'user-data' if self.root else Path(env.get('BIST_USER_DATA_DIR') or self.repo/'.local/user-data').resolve()
        self.runtime = self.root/'runtime' if self.root else Path(env.get('BIST_RUNTIME_DIR') or self.repo/'.local/runtime').resolve()
        self.archives = self.root/'archives'/'yarin_top10_arsiv' if self.root else self.public/'yarin_top10_arsiv'
        self.public,self.users,self.runtime,self.archives = (p.resolve() for p in (self.public,self.users,self.runtime,self.archives))
        if self.root and any(not p.is_relative_to(self.root) for p in (self.public,self.users,self.runtime,self.archives)):
            raise ValueError('Veri dizinleri ortak kökün dışına çıkamaz')
        for name,expected in (('BIST_USER_DATA_DIR',self.users),('BIST_RUNTIME_DIR',self.runtime)):
            if self.root and env.get(name) and Path(env[name]).resolve()!=expected:
                raise ValueError(name+' ortak BIST_DATA_DIR ile çelişiyor')
        for private in (self.users,self.runtime):
            if private.is_relative_to(self.web) or private.is_relative_to(self.public):
                raise ValueError('Private/runtime dizini public altında olamaz')
        if self.users==self.runtime or self.users.is_relative_to(self.runtime) or self.runtime.is_relative_to(self.users):
            raise ValueError('User/runtime dizinleri ayrı olmalı')
        if self.root and any(self.archives.is_relative_to(p) or p.is_relative_to(self.archives) for p in (self.public,self.users,self.runtime)):
            raise ValueError('Archive dizini public/private/runtime ile ayrı olmalı')

    def public_file(self, name):
        if name in PRIVATE_NAMES or name in RUNTIME_LEGACY:
            raise ValueError('Bu dosya public veri değil')
        if Path(name).name!=name or not name.endswith('.json'):
            raise ValueError('Geçersiz public JSON adı')
        return self.public/name

    def runtime_file(self, name):
        if Path(name).name!=name:raise ValueError('Geçersiz runtime adı')
        if not self.root and name in RUNTIME_LEGACY:return self.repo/RUNTIME_LEGACY[name]
        return self.runtime/name

    def ensure(self):
        for path in (self.public,self.users,self.runtime,self.archives):
            path.mkdir(parents=True,exist_ok=True,mode=0o700)


def paths(repo_root=None):
    return DataPaths(repo_root=repo_root)


def public_file(name, repo_root=None):
    return paths(repo_root).public_file(name)


def public_dir(repo_root=None):
    return paths(repo_root).public


def runtime_file(name, repo_root=None):
    return paths(repo_root).runtime_file(name)


def data_file(name, repo_root=None):
    location=paths(repo_root)
    return location.runtime_file(name) if name in RUNTIME_LEGACY else location.public_file(name)


def archive_dir(repo_root=None):
    return paths(repo_root).archives


def copy_new(source, target):
    """Byte-preserving atomic create, never overwrite a live file or archive."""
    if source.is_symlink() or not source.is_file():return False
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temporary=tempfile.mkstemp(prefix='.migration-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as stream,source.open('rb') as original:
            shutil.copyfileobj(original,stream);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,target)
        except FileExistsError:return False
        directory=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return True
    finally:os.unlink(temporary)


def migrate(destination):
    """Offline opt-in copy; run with both processes stopped. Sources remain intact."""
    if not destination.root:raise ValueError('Migration için BIST_DATA_DIR gerekiyor')
    destination.ensure()
    legacy=DataPaths(environ={},repo_root=destination.repo)
    copied=0
    with (destination.root/'.migration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for source in legacy.public.glob('*.json'):
            if source.name in PRIVATE_NAMES:continue
            target=destination.runtime_file(source.name) if source.name in RUNTIME_LEGACY else destination.public_file(source.name)
            copied+=copy_new(source,target)
        for source in legacy.archives.glob('*.json'):
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',source.name):copied+=copy_new(source,destination.archives/source.name)
        for source in legacy.users.glob('*.json'):copied+=copy_new(source,destination.users/source.name)
        for source in legacy.runtime.glob('*.json'):copied+=copy_new(source,destination.runtime/source.name)
        for name,old in RUNTIME_LEGACY.items():copied+=copy_new(destination.repo/old,destination.runtime_file(name))
    return copied


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--migrate',action='store_true',help='Processes stopped: copy legacy JSONs without overwriting')
    args=parser.parse_args();location=paths()
    if args.migrate:print('Copied:',migrate(location))
    else:
        for name in ('public','users','runtime','archives'):print(name,getattr(location,name))
