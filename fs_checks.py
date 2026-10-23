"""Small non-destructive checks under the actual application user's permissions."""

# READING THIS FILE: check access before starting a write operation.
#
# These checks run with the application's actual user permissions. A file can
# be writable while its parent folder is not; that matters for replacement files.
# SQLite may also need adjacent -wal and -shm files. Return a useful explanation
# instead of changing permissions or escalating to root automatically.
# Temporary probes are created/closed without altering existing file contents.

import os
from pathlib import Path
import tempfile


# Probe read/write access and parent-folder access without changing existing contents. Return
# an empty string when no problem is found.
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


# Check the main database and any existing SQLite sidecar files, returning the first
# actionable permissions problem.
def database_problem(path):
    for candidate in (Path(path),Path(str(path)+'-wal'),Path(str(path)+'-shm')):
        if candidate==Path(path) or candidate.exists():
            problem=write_problem(candidate)
            if problem:return problem
    return ''
