"""Small, read-only hardware checks; no extra packages and no network requests.

The display's background worker samples these values every five seconds. The Tk
thread only reads the latest immutable result, so a slow firmware command cannot
hold up touch handling. Missing Linux/Pi facilities mean unknown, never healthy.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import shutil
import subprocess
import threading
import time


@dataclass(frozen=True)
class Health:
    sampled: float = 0.0
    temperature: float | None = None
    available_kib: int | None = None
    total_kib: int | None = None
    throttled: int | None = None


def memory_values(text):
    # MemAvailable includes memory Linux can reclaim from caches. MemFree alone
    # would produce false alarms on a healthy machine caching the map archive.
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in ('MemTotal:', 'MemAvailable:'):
            try: values[fields[0][:-1]] = int(fields[1])
            except ValueError: pass
    total, available = values.get('MemTotal'), values.get('MemAvailable')
    if total is None or available is None or total <= 0 or not 0 <= available <= total:
        return None, None
    return available, total


def sample():
    temperature = available = total = throttled = None
    command = shutil.which('vcgencmd')
    if command:
        # Only fixed, locally installed commands run here. Both have bounded
        # timeouts; no shell interpolation or elevated permissions are needed.
        for argument in ('measure_temp', 'get_throttled'):
            try:
                value = subprocess.run([command, argument], capture_output=True,
                    text=True, timeout=1, check=True).stdout.strip().split('=', 1)[1]
                if argument == 'measure_temp':
                    parsed = float(value.split("'")[0])
                    if math.isfinite(parsed) and -40 <= parsed <= 150: temperature = parsed
                else: throttled = int(value, 0)
            except (OSError, subprocess.SubprocessError, ValueError, IndexError): pass
    if temperature is None:
        try:
            # Thermal-zone readings are a fallback when firmware tools are absent.
            value = float(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
            if math.isfinite(value) and -40 <= value <= 150: temperature = value
        except (OSError, ValueError): pass
    try: available, total = memory_values(Path('/proc/meminfo').read_text())
    except OSError: pass
    return Health(time.monotonic(), temperature, available, total, throttled)


class Monitor:
    def __init__(self, stop):
        self.latest = Health()
        self.thread = threading.Thread(target=self.run, args=(stop,), daemon=True,
                                       name='system-health')
        self.thread.start()

    def run(self, stop):
        while not stop.is_set():
            self.latest = sample()
            stop.wait(5)


def indicators(receiver, gps_time, now, demo=False, database_error=False):
    # Availability comes from the collector's situation probe, not the existence
    # of nearby aircraft. Quiet skies are not a connectivity failure.
    if demo:
        return [('Stratux DEMO', 'unknown'), ('GPS DEMO', 'unknown')]
    if database_error:
        return [('Stratux ?', 'unknown'), ('GPS ?', 'unknown')]
    age = now - receiver[0] if receiver else None
    if age is None: state = 'unknown'
    elif not 0 <= age <= 15: state = 'red'
    else: state = 'green' if receiver[1] else 'red'
    # An ADS-B ownship position can still be valid without a receiver GPS fix.
    # GPS means the fresh usable ownship position actually used by the display.
    gps_age = now - gps_time if gps_time is not None else None
    gps = 'red' if gps_age is None or not 0 <= gps_age <= 15 else 'green' if gps_age <= 10 else 'amber'
    return [('Stratux' + (' ?' if state == 'unknown' else ''), state), ('GPS', gps)]


def hardware_status(health, now):
    # No warning claims to predict or prevent every OOM kill: a sudden allocation
    # can exhaust memory between samples. These are early-warning heuristics.
    if health.sampled <= 0 or not 0 <= now - health.sampled <= 15:
        return ('Temp ?', 'unknown'), []
    temp = health.temperature
    label = 'Temp ?' if temp is None else f'Temp {temp:.0f}°C'
    color = 'unknown' if temp is None else 'red' if temp >= 80 else 'amber' if temp >= 75 else 'green'
    warnings = []
    available, total = health.available_kib, health.total_kib
    if available is not None and total:
        # Warn at either low absolute headroom or a low proportion of RAM.
        # 1 MiB = 1,024 KiB. Swap is not treated as equivalent to usable RAM.
        if available < max(48 * 1024, total * .05):
            warnings.append((f'Memory CRITICAL · {available / 1024:.0f} MB available', 'red'))
        elif available < max(96 * 1024, total * .10):
            warnings.append((f'Memory LOW · {available / 1024:.0f} MB available', 'amber'))
    flags = health.throttled
    if flags is not None:
        # Low bits describe present trouble; high bits only record history since
        # boot and must not be presented as a fault still happening now.
        if flags & 1: warnings.append(('Power · undervoltage', 'red'))
        if flags & 0xE: warnings.append(('System · throttling / speed limited', 'amber'))
    return (label, color), warnings
