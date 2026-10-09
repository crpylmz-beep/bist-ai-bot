"""Private, streaming gzip archives with full read-back SHA-256 verification."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlparse
import zlib
from .config import StorageError,R2Settings
from .migration import checksum,fingerprint
from .records import now

CHUNK=1024*1024
PART=5*1024*1024
RESERVE=40*1024*1024


class R2Archive:
    def __init__(self,client=None,bucket=None,env=None,sleep=time.sleep):
        env=os.environ if env is None else env;self.sleep=sleep
        self.bucket=bucket or env.get('R2_BUCKET');self.client=client
        if not self.bucket:raise StorageError('R2_NOT_CONFIGURED')
        if client is None:
            settings=R2Settings.from_env({**env,'R2_BUCKET':self.bucket});settings.require()
            endpoint=settings.endpoint
            import boto3
            import botocore.session
            session=botocore.session.Session()
            config_store=session.get_component('config_store')
            for name,value in (('profile',None),('config_file',os.devnull),('credentials_file',os.devnull)):config_store.set_config_variable(name,value)
            from botocore.config import Config
            self.client=boto3.Session(botocore_session=session).client('s3',endpoint_url=endpoint,aws_access_key_id=settings.access_key,aws_secret_access_key=settings.secret_key,region_name='auto',config=Config(connect_timeout=settings.connect_timeout,read_timeout=settings.read_timeout,retries={'total_max_attempts':3,'mode':'standard'}))

    def call(self,name,**kwargs):
        for attempt in range(3):
            try:return getattr(self.client,name)(Bucket=self.bucket,**kwargs)
            except Exception as error:
                response=getattr(error,'response',{});status=response.get('ResponseMetadata',{}).get('HTTPStatusCode');code=str(response.get('Error',{}).get('Code',''))
                if status==404 or code in ('NoSuchKey','404','NotFound'):raise StorageError('R2_NOT_FOUND') from None
                retry=status in (408,429,500,502,503,504) or type(error).__name__ in ('TimeoutError','ConnectionError','EndpointConnectionError','ReadTimeoutError','ConnectTimeoutError')
                if not retry or attempt==2:raise StorageError('R2_TRANSFER_FAILED') from None
                self.sleep(0.25*2**attempt)

    def _head(self,key):
        try:return self.call('head_object',Key=key)
        except StorageError as error:
            if error.storage_code=='R2_NOT_FOUND':return None
            raise

    def validate_manifest(self,manifest):
        import re
        if not isinstance(manifest,dict):raise StorageError('ARCHIVE_MANIFEST_INVALID')
        for field in ('raw_size','compressed_size'):
            if type(manifest.get(field)) is not int or manifest[field]<0:raise StorageError('ARCHIVE_MANIFEST_INVALID')
        for field in ('raw_sha256','compressed_sha256'):
            if not isinstance(manifest.get(field),str) or not re.fullmatch(r'[0-9a-f]{64}',manifest[field]):raise StorageError('ARCHIVE_MANIFEST_INVALID')
        if not isinstance(manifest.get('object_key'),str) or not manifest['object_key'].startswith('bist/'):raise StorageError('ARCHIVE_MANIFEST_INVALID')

    def verify(self,key,manifest,sink=None):
        self.validate_manifest(manifest)
        body=self.call('get_object',Key=key)['Body'];compressed=hashlib.sha256();raw=hashlib.sha256();size=0;packed=0;decoder=zlib.decompressobj(31)
        try:
            while block:=body.read(CHUNK):
                compressed.update(block);packed+=len(block)
                if packed>manifest['compressed_size']:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
                pending=block
                while pending:
                    data=decoder.decompress(pending,CHUNK);pending=decoder.unconsumed_tail
                    size+=len(data)
                    if size>manifest['raw_size']:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
                    raw.update(data)
                    if sink:sink.write(data)
                    if decoder.unused_data:raise StorageError('ARCHIVE_TRAILING_DATA')
            if not decoder.eof or size!=manifest['raw_size'] or packed!=manifest['compressed_size'] or raw.hexdigest()!=manifest['raw_sha256'] or compressed.hexdigest()!=manifest['compressed_sha256']:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
        except zlib.error:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH') from None
        finally:body.close()
        return True

    def archive(self,path,version='v6',store=None):
        path=Path(path);before=fingerprint(path);raw_sha=checksum(path)
        if not version.replace('-','').replace('_','').isalnum():raise StorageError('ARCHIVE_VERSION_INVALID')
        # Object identity is content-addressed; date is recorded in immutable manifest.
        key=f'bist/{version}/{raw_sha[:2]}/{raw_sha}.json.gz';manifest_key=key+'.manifest.json'
        head=self._head(key)
        if head:
            try:
                body=self.call('get_object',Key=manifest_key)['Body']
                try:
                    data=body.read(65537)
                    if len(data)>65536:raise StorageError('ARCHIVE_MANIFEST_INVALID')
                    manifest=json.loads(data)
                finally:body.close()
            except StorageError as error:
                if error.storage_code!='R2_NOT_FOUND':raise
                # Crash after completion but before manifest: prove existing bytes first.
                manifest=self.recover_manifest(key,raw_sha,before['size'],head['ContentLength'],version)
                self.call('put_object',Key=manifest_key,Body=json.dumps(manifest).encode(),ContentType='application/json')
            if manifest['raw_sha256']!=raw_sha or manifest['raw_size']!=before['size']:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
            self.verify(key,manifest)
            if store:store.record_archive(raw_sha,manifest)
            return dict(manifest,duplicate=True)
        upload=self.call('create_multipart_upload',Key=key,ContentType='application/gzip',Metadata={'raw-sha256':raw_sha,'format':'bist-v6'})['UploadId']
        parts=[];buffer=bytearray();compressed=hashlib.sha256();packed=0;encoder=zlib.compressobj(6,zlib.DEFLATED,31);second_hash=hashlib.sha256()
        def send(data):
            nonlocal packed
            number=len(parts)+1
            if number>10000:raise StorageError('ARCHIVE_MULTIPART_LIMIT')
            packed+=len(data);compressed.update(data)
            answer=self.call('upload_part',Key=key,UploadId=upload,PartNumber=number,Body=data)
            parts.append({'PartNumber':number,'ETag':answer['ETag']})
        try:
            with path.open('rb') as source:
                while block:=source.read(CHUNK):
                    second_hash.update(block);buffer.extend(encoder.compress(block))
                    while len(buffer)>=PART:
                        send(bytes(buffer[:PART]));del buffer[:PART]
            buffer.extend(encoder.flush())
            if buffer:send(bytes(buffer));buffer.clear()
            if fingerprint(path)!=before or second_hash.hexdigest()!=raw_sha:raise StorageError('SOURCE_CHANGED')
            self.call('complete_multipart_upload',Key=key,UploadId=upload,MultipartUpload={'Parts':parts})
            manifest={'version':version,'created_at':now(),'object_key':key,'raw_sha256':raw_sha,'raw_size':before['size'],'compressed_sha256':compressed.hexdigest(),'compressed_size':packed,'status':'VERIFIED'}
            self.verify(key,manifest)
            self.call('put_object',Key=manifest_key,Body=json.dumps(manifest).encode(),ContentType='application/json')
            if store:store.record_archive(raw_sha,manifest)
            return dict(manifest,duplicate=False)
        except BaseException:
            try:self.call('abort_multipart_upload',Key=key,UploadId=upload)
            except StorageError:pass  # Only this owned upload; source and completed object remain.
            raise

    def recover_manifest(self,key,raw_sha,raw_size,compressed_size,version):
        body=self.call('get_object',Key=key)['Body'];decoder=zlib.decompressobj(31);hashed=hashlib.sha256();packed=hashlib.sha256();size=0;count=0
        try:
            while block:=body.read(CHUNK):
                packed.update(block);count+=len(block)
                if count>compressed_size:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
                pending=block
                while pending:
                    data=decoder.decompress(pending,CHUNK);pending=decoder.unconsumed_tail
                    size+=len(data);hashed.update(data)
                    if size>raw_size or decoder.unused_data:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
            if not decoder.eof or size!=raw_size or count!=compressed_size or hashed.hexdigest()!=raw_sha:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH')
        except zlib.error:raise StorageError('ARCHIVE_CHECKSUM_MISMATCH') from None
        finally:body.close()
        return {'version':version,'created_at':now(),'object_key':key,'raw_sha256':raw_sha,'raw_size':raw_size,'compressed_sha256':packed.hexdigest(),'compressed_size':count,'status':'VERIFIED'}

    def restore(self,manifest,target):
        self.validate_manifest(manifest)
        target=Path(target)
        if target.exists() or target.is_symlink():raise StorageError('RESTORE_TARGET_EXISTS')
        if not target.parent.is_dir():raise StorageError('RESTORE_DIRECTORY_REQUIRED')
        if shutil.disk_usage(target.parent).free<manifest['raw_size']+RESERVE:raise StorageError('RESTORE_DISK_SPACE_GUARD')
        fd,tmp=tempfile.mkstemp(prefix='.v6-restore-owned-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as sink:
                self.verify(manifest['object_key'],manifest,sink);sink.flush();os.fsync(sink.fileno())
            os.link(tmp,target)
            directory=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:os.unlink(tmp)  # Only the newly allocated restore scratch.
        return target

    def usage(self,max_pages=20):
        total=0;objects=0;token=None
        for _ in range(max_pages):
            options={'Prefix':'bist/','MaxKeys':1000}
            if token:options['ContinuationToken']=token
            page=self.call('list_objects_v2',**options)
            for item in page.get('Contents',[]):total+=item['Size'];objects+=1
            if not page.get('IsTruncated'):return {'bytes':total,'objects':objects,'complete':True}
            token=page['NextContinuationToken']
        return {'bytes':total,'objects':objects,'complete':False}
