"""Local recovery and explicitly approved diagnostic exports."""
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile

from fs_checks import check_database, database_notice


def corruption_error(error):
    code = getattr(error, 'sqlite_errorcode', 0) or 0
    return (code & 255) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB) or not code


def recovery_offered(path):
    try:
        return database_notice(path).read_text().startswith('Corrupt database:')
    except OSError:
        return False


def damaged(path):
    """Distinguish corruption from temporary locks, permissions and I/O errors."""
    if not Path(path).is_file() or not database_notice(path).is_file():
        return False
    try:
        check_database(path)
    except sqlite3.DatabaseError as error:
        return corruption_error(error)
    return False


def fresh_start(path, support):
    """Save the latest failed database and sidecars before removing active files."""
    path, support = Path(path), Path(support)
    if not damaged(path):
        raise ValueError('Fresh Start requires confirmed database corruption.')
    support.mkdir(mode=0o700, parents=True, exist_ok=True)
    files = [Path(str(path) + suffix) for suffix in ('-wal', '-shm', '-journal', '')]
    files = [item for item in files if item.is_file()]
    # Publish the entire damaged set together. If packing fails, the old
    # archive and the original database files are still available.
    with tempfile.TemporaryDirectory(dir=support) as temporary:
        archive = Path(temporary) / 'damaged.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for item in files:
                bundle.write(item, item.name)
        with archive.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(archive, support / 'latest-damaged.zip')
        directory = os.open(support, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    (support / 'support.zip').unlink(missing_ok=True)
    for item in files:
        item.unlink()
    database_notice(path).unlink(missing_ok=True)


def bundle(home, include_database=False):
    """Replace the previous export with a bounded, explicitly described bundle."""
    home = Path(home)
    support = home / 'support'
    support.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=support) as temporary:
        target = Path(temporary) / 'support.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('collector.log', 'display.log'):
                path = home / 'runtime' / name
                if path.is_file():
                    with path.open('rb') as stream:
                        stream.seek(max(0, os.fstat(stream.fileno()).st_size - 128 * 1024))
                        archive.writestr(name, stream.read(128 * 1024))
            if (home / 'state.json').is_file():
                archive.write(home / 'state.json', 'release-state.json')
            failed = support / 'latest-damaged.zip'
            if include_database and failed.is_file():
                archive.write(failed, failed.name)
        os.replace(target, support / 'support.zip')
    return support / 'support.zip'


def destination(value):
    """Accept a destination, never passwords or arbitrary SFTP commands."""
    value = value.strip()
    pattern = r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*:/[A-Za-z0-9_./-]*'
    if not re.fullmatch(pattern, value) or '..' in value.split('/'):
        raise ValueError('Use an SFTP destination such as support@example.com:/incoming.')
    return value


def upload(path, value):
    host, directory = destination(value).split(':', 1)
    remote = directory.rstrip('/') + '/fishfinder-' + uuid.uuid4().hex + '.zip'
    with Path(path).open('rb') as source, tempfile.TemporaryDirectory() as temporary:
        # Use a fixed local filename in a private working directory so batch
        # commands never interpolate a local path or any user-entered quotes.
        with (Path(temporary) / 'support.zip').open('wb') as copy:
            shutil.copyfileobj(source, copy)
        result = subprocess.run(
            ['sftp', '-b', '-', '-oBatchMode=yes', '-oStrictHostKeyChecking=yes',
             '-oConnectTimeout=10', host],
            input=f'put support.zip {remote}.part\nrename {remote}.part {remote}\n',
            cwd=temporary, text=True, capture_output=True, timeout=120,
        )
    if result.returncode:
        raise RuntimeError('Upload failed. Check Internet, the configured SFTP key, host key and destination.')
