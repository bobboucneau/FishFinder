"""Bounded HTTP reads and per-worker progress reporting."""
from contextvars import ContextVar
import time

report = ContextVar('airport_progress', default=None)


def stage(message):
    callback = report.get()
    if callback:
        callback(message)


def read_download(response, label, limit):
    """Read in chunks; report received bytes even without Content-Length."""
    data = bytearray()
    next_report = 0
    stage(f'Downloading {label}…')
    while len(data) <= limit:
        chunk = response.read(min(65536, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if time.monotonic() >= next_report:
            stage(f'Downloading {label} · {len(data)/1024:,.0f} KB')
            next_report = time.monotonic() + .25
    if len(data) > limit:
        raise ValueError(f'{label}: download exceeds size limit')
    stage(f'Downloaded {label} · {len(data)/1024:,.0f} KB')
    return data
