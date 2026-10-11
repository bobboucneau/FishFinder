"""Small non-destructive checks under the actual application user's permissions."""
import os
from pathlib import Path
import tempfile


def write_problem(path, atomic=False):
    path=Path(path)
    try:
        if path.exists() and not os.access(path,os.R_OK):return f'Cannot read {path}'
        # Atomic replacement requires a writable directory even for a writable file.
        with tempfile.TemporaryFile(dir=path.parent):pass
        if path.exists() and not atomic:
            with path.open('r+b'):pass
    except OSError as exc:return f'Cannot write {path}: {exc}. Check owner and directory permissions for the current user.'
    return ''


def database_problem(path):
    for candidate in (Path(path),Path(str(path)+'-wal'),Path(str(path)+'-shm')):
        if candidate==Path(path) or candidate.exists():
            problem=write_problem(candidate)
            if problem:return problem
    return ''
