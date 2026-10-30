"""Versioned, non-root FishFinder installations and signed/owner release staging.

READING ORDER: atomic JSON -> signature/manifest checks -> bounded ZIP extraction
-> activation/rollback. Downloading and signing are separate from installation.
The normal user owns this directory: signatures authenticate published releases,
not protect against an attacker who already controls that user's files/processes.
"""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import tempfile
import zipfile

MAX_ARCHIVE=64*1024*1024
MAX_UNPACKED=128*1024*1024
API=1


def atomic(path,value):
    """Replace a complete JSON file, never expose a half-written state file."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
            temporary=Path(stream.name);json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and temporary.exists():temporary.unlink()


def read(path,default):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return default


def sha256(path):
    # Hash in small pieces: a large map/package never needs to fit in RAM.
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


class Store:
    def __init__(self,home):
        self.home=Path(home).expanduser().resolve()
        for folder in ('releases','shared','runtime','trusted-keys','inbox'): (self.home/folder).mkdir(parents=True,exist_ok=True)
        self.state_path=self.home/'state.json';self.pending_path=self.home/'pending.json'

    @contextmanager
    def locked(self):
        # CLI staging and the running supervisor can meet concurrently. A kernel
        # file lock serializes state changes and releases automatically on crash.
        with (self.home/'update.lock').open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            yield

    def state(self):
        return read(self.state_path,dict(current=None,previous=None,high_watermark=0,trial=None))

    def release(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',identifier):
            raise ValueError('Invalid release identifier')
        path=self.home/'releases'/identifier
        if path.is_symlink():raise ValueError('Release folders cannot be symbolic links')
        return path

    def validate(self,archive,manifest,signature=None,owner=False):
        archive=Path(archive);manifest=Path(manifest)
        if manifest.stat().st_size>32768:raise ValueError('Manifest too large')
        raw=manifest.read_bytes();data=json.loads(raw)
        if data.get('product')!='FishFinder' or data.get('schema')!=1:raise ValueError('Wrong manifest product/schema')
        self.release(data['release_id'])
        if data.get('bootstrap_api')!=API:raise ValueError('This release needs a different bootstrap API')
        minimum=data.get('python_min',[3,10])
        if not isinstance(minimum,list) or len(minimum)!=2 or not all(type(x) is int for x in minimum):raise ValueError('Invalid Python compatibility field')
        import sys
        if tuple(sys.version_info[:2])<tuple(minimum):raise ValueError('Python is too old for this release')
        if data.get('platform') not in ('linux','any'):raise ValueError('Unsupported release platform')
        if data.get('platform')=='linux' and platform.system()!='Linux':raise ValueError('This package requires Linux')
        if type(data.get('sequence')) is not int or data['sequence']<1:raise ValueError('Invalid release sequence')
        if type(data.get('size')) is not int or not 0<data['size']<=MAX_ARCHIVE:raise ValueError('Invalid package size')
        if archive.stat().st_size!=data['size'] or sha256(archive)!=data.get('sha256'):raise ValueError('Package checksum/size does not match manifest')
        if not owner:
            # Public keys are installed once by the owner, independently of the
            # downloaded package. Never accept a key supplied by that package.
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature
            if not signature:raise ValueError('Official releases require a signature')
            encoded=Path(signature).read_bytes()
            if len(encoded)>4096:raise ValueError('Signature file too large')
            try:sig=base64.b64decode(encoded,validate=True)
            except ValueError as exc:raise ValueError('Invalid signature encoding') from exc
            valid=False
            for key in (self.home/'trusted-keys').glob('*.pem'):
                try:
                    public=serialization.load_pem_public_key(key.read_bytes())
                    if isinstance(public,Ed25519PublicKey):public.verify(sig,raw);valid=True;break
                except (ValueError,InvalidSignature):pass
            if not valid:raise ValueError('No trusted FishFinder signing key verified this release')
            if data['sequence']<=self.state()['high_watermark']:raise ValueError('Official release is not newer; use explicit local rollback for a retained version')
        return data

    def stage(self,archive,manifest,signature=None,owner=False):
        with self.locked():
            data=self.validate(archive,manifest,signature,owner)
            destination=self.release(data['release_id'])
            if destination.exists():raise ValueError('This release ID is already installed; use a new ID for each build')
            if self.state().get('trial'):raise ValueError('Wait for the current startup trial before staging another release')
            with zipfile.ZipFile(archive) as z:
                members=z.infolist()
                if len(members)>2000:raise ValueError('Too many archive entries')
                total=sum(info.file_size for info in members)
                if total>MAX_UNPACKED:raise ValueError('Unpacked package exceeds limit')
                if shutil.disk_usage(self.home).free<total*2+32*1024*1024:raise ValueError('Insufficient disk space for staging and rollback')
                names=set();files=[]
                for info in members:
                    name=PurePosixPath(info.filename)
                    if name.is_absolute() or '..' in name.parts or '\\' in info.filename or not name.parts:raise ValueError('Unsafe archive path')
                    # Packages contain one named top-level folder, as existing
                    # FishFinder ZIPs do. Nothing may write beside that folder.
                    if name.parts[0]!=data['folder']:raise ValueError('Unexpected archive root')
                    relative=PurePosixPath(*name.parts[1:])
                    mode=info.external_attr>>16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)):
                        raise ValueError('Links and special files are not allowed')
                    if str(relative) in names:raise ValueError('Duplicate archive path')
                    names.add(str(relative))
                    if not info.is_dir():files.append((info,relative))
                with tempfile.TemporaryDirectory(prefix='.staging-',dir=self.home/'releases') as tmp:
                    candidate=Path(tmp)/'app';candidate.mkdir()
                    for info,relative in files:
                        target=candidate/str(relative);target.parent.mkdir(parents=True,exist_ok=True)
                        with z.open(info) as source,target.open('wb') as out:
                            remaining=info.file_size
                            while remaining:
                                chunk=source.read(min(1024*1024,remaining))
                                if not chunk:raise ValueError('Truncated archive member')
                                out.write(chunk);remaining-=len(chunk)
                        target.chmod(0o755 if target.suffix=='.bash' else 0o644)
                    for required in ('FishFinder.py','traffic_display.py','settings.py','airports.json'):
                        if not (candidate/required).is_file():raise ValueError('Missing required application file: '+required)
                    # Per-file hashes in VERSION.json are checked too. They are
                    # useful for diagnostics; the external signature authenticates
                    # the entire ZIP, including this internal manifest.
                    version=read(candidate/'VERSION.json',{})
                    for name,digest in version.get('files',{}).items():
                        path=PurePosixPath(name)
                        if path.is_absolute() or '..' in path.parts or '\\' in name:raise ValueError('Unsafe internal manifest path')
                        if sha256(candidate/name)!=digest:raise ValueError('Internal file checksum mismatch: '+name)
                    atomic(candidate/'.release.json',dict(manifest=data,owner_build=owner))
                    os.replace(candidate,destination)
            pending=dict(release=data['release_id'],owner_build=owner,sequence=data['sequence'],policy='ask')
            atomic(self.pending_path,pending)
            return pending

    def defer(self,policy):
        if policy not in ('ask','next-start','later'):raise ValueError('Invalid pending-update policy')
        with self.locked():
            pending=read(self.pending_path,None)
            if not pending:raise ValueError('No pending update')
            pending['policy']=policy;atomic(self.pending_path,pending)

    def activate(self):
        with self.locked():
            pending=read(self.pending_path,None)
            if not pending:raise ValueError('No pending update')
            if not self.release(pending['release']).is_dir():raise ValueError('Staged release is missing')
            state=self.state();old=state['current']
            state.update(current=pending['release'],previous=old,trial=pending)
            # This single pointer replacement commits activation. If power fails
            # before success is recorded, startup sees trial and restores old.
            atomic(self.state_path,state);self.pending_path.unlink(missing_ok=True)
            return state

    def accept(self):
        with self.locked():
            state=self.state();trial=state.get('trial')
            if trial and not trial['owner_build']:state['high_watermark']=max(state['high_watermark'],trial['sequence'])
            state['trial']=None;atomic(self.state_path,state)

    def rollback(self):
        with self.locked():
            state=self.state()
            if not state.get('previous'):raise ValueError('No previous release to restore')
            state['current'],state['previous']=state['previous'],state['current']
            state['trial']=None;atomic(self.state_path,state)
            return state
