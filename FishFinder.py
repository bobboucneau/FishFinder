#!/usr/local/Fishfinder/.venv/bin/python3
"""Collect Stratux traffic and ownship; periodically prune the shared database.

Requires websocket-client. Existing table/column names are preserved.
Do not run the old collector/OwnShip.py alongside this replacement.
"""

# READING THIS FILE: the collector (the part that listens and records).
#
# Start at main() near the bottom to see startup and shutdown. It chooses either
# real Stratux data or simulated data, checks the database, and starts workers.
# A worker is a background thread: it has its own job but shares a stop signal.
# Traffic reception, database writing, ownship polling, and cleanup are separate
# so a slow operation does not stop all the others.
#
# Data travels from Stratux -> decoded Python dictionaries -> validated numbers
# -> SQLite rows. The display reads those rows in a separate running program.
# Here, 'tail' is the database identity key; registration/callsign are display
# names and may change without creating another aircraft. Estimated positions
# are saved with an explicit marker, not silently treated as fresh observations.
#
# Python landmarks: def starts a function; indentation groups its steps; return
# hands a result back to its caller. 'with conn' commits database changes on
# success and rolls them back on an exception. 'with closing(...)' also closes
# the connection. A log records diagnostics; it does not itself save a report.


import queue
import argparse
import socket
import json
import logging
import math
import sqlite3
import threading
import time
import urllib.request
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone
import settings
from fs_checks import database_problem

import websocket

# Shared storage policy. Paths are kept outside the versioned program folder so a software
# upgrade need not erase live data. Constants in capitals are named choices used later;
# changing one can affect memory, history, or network behavior.
DATABASE_PATH = Path('/var/local/FishFinder/flying_objects.db')
TRAFFIC_URL = 'ws://192.168.10.1/traffic'
SITUATION_URL = 'http://192.168.10.1/getSituation'
OWNSHIP_INTERVAL = 3
CLEANUP_INTERVAL = 3
OWNSHIP_HISTORY = 110  # About 5.5 minutes at a three-second poll interval.
AIRCRAFT_AGE = 60
HISTORY_SECONDS = 300
REPORT_HISTORY = 600  # Safety cap per tail; normal sampling yields about 300.
REPORT_INTERVAL = 1.0
HTTP_TIMEOUT = 5
RECONNECT_DELAY = 5
TRAFFIC_IDLE_SECONDS = 0
TRAFFIC_QUEUE_SIZE = 1024


# Open one connection to the chosen SQLite file. Each worker needs its own connection;
# connections are not passed between threads.
def connect_database(db_path=DATABASE_PATH):
    # Each calling thread owns its connection. Wait briefly for other writers.
    return sqlite3.connect(str(db_path), timeout=10)


# Create missing tables, add columns introduced by newer versions, and prepare indexes
# without deleting existing records.
def initialize(db_path=DATABASE_PATH):
    if sqlite3.sqlite_version_info < (3, 25, 0):
        raise RuntimeError('SQLite 3.25 or newer is required for history cleanup')
    # Require the directory to exist: do not silently create a wrong location.
    if not Path(db_path).parent.is_dir():
        raise RuntimeError(f'Database directory does not exist: {Path(db_path).parent}')
    with closing(connect_database(db_path)) as conn:
        # WAL is SQLite's write-ahead log mode. It lets the display read while the collector
        # writes, with a small sidecar file beside the database. It does not allow two
        # threads to share one Python connection.
        conn.execute('PRAGMA journal_mode=WAL')
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS aircraft (tail TEXT PRIMARY KEY, time REAL)')
            conn.execute('''CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tail TEXT, time REAL,
                speed REAL, asl REAL, longitude REAL, latitude REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ownship (
                id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL,
                speed REAL, asl REAL, longitude REAL, latitude REAL)''')
            # Read the existing schema before adding columns. This is an upgrade, not a
            # reset: older databases keep their collected rows. The braces build a set of
            # column names so membership can be checked quickly.
            columns = {row[1] for row in conn.execute('PRAGMA table_info(aircraft)')}
            for name in ('registration', 'callsign'):
                if name not in columns:
                    conn.execute(f'ALTER TABLE aircraft ADD COLUMN {name} TEXT')
            for table in ('reports', 'ownship'):
                columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
                for name, kind in [('comparison_alt','REAL'),('alt_ref','TEXT')]:
                    if name not in columns: conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(reports)')}
            for name, kind in [('estimated', 'INTEGER DEFAULT 0'), ('position_age', 'REAL')]:
                if name not in columns: conn.execute(f'ALTER TABLE reports ADD COLUMN {name} {kind}')
            # The CHECK(id=1) rule allows only one status slot. INSERT OR REPLACE later
            # refreshes that slot; it is a current-state message, not an ever-growing status
            # history.
            conn.execute('CREATE TABLE IF NOT EXISTS receiver_status (id INTEGER PRIMARY KEY CHECK(id=1), time REAL, available INTEGER, message TEXT)')
            conn.execute('CREATE INDEX IF NOT EXISTS aircraft_time_idx ON aircraft(time)')
            conn.execute('CREATE INDEX IF NOT EXISTS reports_time_idx ON reports(time)')
            conn.execute('CREATE INDEX IF NOT EXISTS reports_tail_time_idx ON reports(tail, time DESC, id DESC)')


# Convert a received value to a finite decimal number. Return None for missing, boolean,
# invalid, or infinite values.
def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


# Accept numeric coordinates inside Earth latitude/longitude limits. Zero is a valid
# coordinate, not a missing-data marker.
def valid_position(lat, lng):
    return (lat is not None and lng is not None
            and -90 <= lat <= 90 and -180 <= lng <= 180)


# Choose the stable aircraft database key first, then keep registration and callsign as
# separate human-readable labels.
def identity(data):
    # Normalize one incoming name: strip surrounding spaces, use uppercase, and ignore the
    # literal missing-name placeholder.
    def label(value):
        return value.strip().upper() if isinstance(value, str) and value.strip().upper() != 'NO TAIL' else ''
    # Stratux can replace an N-number with an airline callsign. Those are names, not reliable
    # database identity. Prefer the 24-bit ICAO address and retain both readable names.
    registration, callsign = label(data.get('Reg')), label(data.get('Tail'))
    # get() reads a dictionary field without crashing if it is absent. An absent field
    # becomes None. The address may arrive as a number or text, so normalize it before
    # checking its range.
    address = data.get('Icao_addr')
    if isinstance(address, str):
        try:
            text = address.strip()
            address = int(text, 16 if text.lower().startswith('0x') or any(c in text.upper() for c in 'ABCDEF') else 10)
        except ValueError:
            address = None
    if isinstance(address, int) and not isinstance(address, bool) and 0 < address <= 0xFFFFFF:
        return f'icao:{address:06X}', registration, callsign
    if registration:
        return 'reg:' + registration, registration, callsign
    if callsign:
        return 'label:' + callsign, registration, callsign
    return None, registration, callsign


# Validate one traffic message, update its aircraft identity/last-seen row, and save a
# position only when quality and sampling rules allow it. Return whether a report row was
# saved.
def record_traffic(conn, data, received_at=None):
    if not isinstance(data, dict):
        raise ValueError('Traffic message must be a JSON object')
    tail, registration, callsign = identity(data)
    if tail is None:
        return False
    # Use reception time supplied by the stream when available. This keeps database/logging
    # delays from making an old queued observation look newly received.
    timestamp = time.time() if received_at is None else received_at
    lat, lng = number(data.get('Lat')), number(data.get('Lng'))
    altitude, speed = number(data.get('Alt')), number(data.get('Speed'))
    # Explicit validity flags take precedence; older feeds may omit them.
    position_age=number(data.get('Age'))
    estimated = data.get('ExtrapolatedPosition') is True
    # A receiver-projected position can help motion look smooth, but it gets an estimated
    # marker and a bounded age allowance. Later altitude-conflict filtering must not treat it
    # as a fresh observed measurement.
    age_limit = 60 if estimated else 10
    position_ok = data.get('Position_valid', True) is True and valid_position(lat, lng) and (position_age is None or 0 <= position_age <= age_limit)
    speed_ok = data.get('Speed_valid', True) is True and speed is not None and speed >= 0
    # Build an explanation even when the report is rejected. saved=False in the log can mean
    # invalid data OR simply that the one-second sample interval has not elapsed.
    reasons=[]
    if data.get('Position_valid',True) is not True: reasons.append('position_flag_invalid')
    if not valid_position(lat,lng): reasons.append('coordinates_invalid')
    if position_age is not None and not 0<=position_age<=age_limit: reasons.append(f'position_age_outside_0_to_{age_limit}s')
    if data.get('Speed_valid',True) is not True: reasons.append('speed_flag_invalid')
    if speed is None or speed<0: reasons.append('speed_missing_or_invalid')
    if altitude is None: reasons.append('altitude_missing_or_invalid')
    report_ok = position_ok and speed_ok and altitude is not None
    with conn:
        # Maintain the aircraft's last-seen identity even if this particular message cannot
        # become a plotted report. The reports table holds position history; the aircraft
        # table holds the current name/last-seen information.
        conn.execute('INSERT OR IGNORE INTO aircraft (tail) VALUES (?)', (tail,))
        # SQL updates the existing identity row. COALESCE/NULLIF keep an older known
        # registration when a new message omits it; the CASE expression avoids needlessly
        # replacing a known callsign with the registration.
        conn.execute('''UPDATE aircraft SET time = ?,
            registration = COALESCE(NULLIF(?, ''), registration),
            callsign = CASE WHEN ? = '' THEN callsign
                WHEN ? = COALESCE(NULLIF(?, ''), registration) AND callsign IS NOT NULL
                    THEN callsign ELSE ? END
            WHERE tail = ?''',
            (timestamp, registration, callsign, callsign, registration, callsign, tail))
        if report_ok:
            # Find the most recently saved report for THIS aircraft, not the most recent
            # report in the whole database. Question marks in SQL are value placeholders; the
            # separate tuple supplies values safely.
            previous = conn.execute(
                'SELECT time FROM reports WHERE tail = ? ORDER BY time DESC, id DESC LIMIT 1',
                (tail,),
            ).fetchone()
            # Keep one position per second per aircraft, rather than every frame.
            # Resume immediately if the system clock has moved backwards.
            previous_time = number(previous[0]) if previous else None
            report_ok = (previous_time is None or timestamp < previous_time
                         or timestamp - previous_time >= REPORT_INTERVAL)
            if not report_ok: reasons.append(f'sample_interval({timestamp-previous_time:.3f}s)')
        # Only the accepted sample reaches this INSERT. The SQL column order and the value
        # tuple must match. comparison_alt is deliberately stricter than the ordinary display
        # altitude: it requires fresh observed pressure altitude.
        if report_ok:
            conn.execute('''INSERT INTO reports
                (tail, time, speed, asl, longitude, latitude, comparison_alt, alt_ref, estimated, position_age) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (tail, timestamp, speed, altitude, lng, lat,
                 altitude if not estimated and data.get('AltIsGNSS') is False and number(data.get('AgeLastAlt')) is not None and 0 <= number(data.get('AgeLastAlt')) <= 10 else None,
                 'pressure' if data.get('AltIsGNSS') is False else None, int(estimated), position_age))
    logging.info('Traffic %s | altitude=%s speed=%s position=(%s, %s) saved=%s | reason=%s | Position_valid=%r Speed_valid=%r Age=%r ExtrapolatedPosition=%r',
        tail, altitude, speed, lat, lng, report_ok, ','.join(reasons) or ('accepted_estimated' if estimated else 'accepted'),
        data.get('Position_valid','missing'),data.get('Speed_valid','missing'),
        data.get('Age','missing'),data.get('ExtrapolatedPosition','missing'))
    return report_ok


# Validate receiver GPS data and save one ownship row. A missing GPS altitude can remain
# unknown; invalid position or speed cannot.
def record_ownship(conn, data, received_at=None):
    if not isinstance(data, dict):
        raise ValueError('Situation response must be a JSON object')
    timestamp = time.time() if received_at is None else received_at
    # A response can be reachable yet contain an old GPS fix. A new HTTP response time does
    # not automatically mean the GPS position inside it is fresh.
    if 'GPSLastFixLocalTime' in data and not timestamp_fresh(data['GPSLastFixLocalTime'],timestamp):
        return False
    # Skip an explicitly reported lack of GPS fix.
    if 'GPSFixQuality' in data:
        quality = number(data['GPSFixQuality'])
        if quality is None or quality <= 0:
            return False
    lat = number(data.get('GPSLatitude'))
    lng = number(data.get('GPSLongitude'))
    # Prefer an explicitly MSL GPS altitude when present. This displayed altitude is separate
    # from the pressure altitude stored for like-for-like vertical comparisons.
    altitude = number(data.get('GPSAltitudeMSL'))
    if altitude is None: altitude = number(data.get('GPSAltitude'))
    speed = number(data.get('GPSGroundSpeed'))
    if not valid_position(lat, lng) or speed is None or speed < 0:
        logging.debug('Skipping ownship: missing or invalid GPS fields')
        return False
    timestamp = time.time() if received_at is None else received_at
    with conn:
        conn.execute('''INSERT INTO ownship (time, speed, asl, longitude, latitude, comparison_alt, alt_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?)''', (timestamp, speed, altitude, lng, lat,
            number(data.get('BaroPressureAltitude')) if timestamp_fresh(data.get('BaroLastMeasurementTime'), timestamp) else None, 'pressure'))
    logging.info('Ownship | altitude=%s speed=%s position=(%s, %s)', altitude, speed, lat, lng)
    return True


# Apply both age limits and per-aircraft row caps in one transaction. Keeping a bounded
# recent history prevents indefinite database growth.
def cleanup_once(conn, now=None):
    timestamp = time.time() if now is None else now
    # Compute cutoff times once so all deletion rules refer to the same instant. An aircraft
    # can disappear from the active list before its older trail rows reach the longer history
    # cutoff.
    cutoff = timestamp - AIRCRAFT_AGE
    history_cutoff = timestamp - HISTORY_SECONDS
    with conn:
        conn.execute('DELETE FROM ownship WHERE time < ? OR time IS NULL', (history_cutoff,))
        conn.execute('''DELETE FROM ownship WHERE id NOT IN
            (SELECT id FROM ownship ORDER BY id DESC LIMIT ?)''', (OWNSHIP_HISTORY,))
        conn.execute('DELETE FROM aircraft WHERE time < ? OR time IS NULL', (cutoff,))
        conn.execute('DELETE FROM reports WHERE time < ? OR time IS NULL', (history_cutoff,))
        # Window functions avoid repeatedly counting the expanded history.
        # Supported by SQLite 3.25+ (standard on modern Debian).
        # ROW_NUMBER ranks rows separately for each aircraft, newest first. Retain only the
        # allowed ranks. This extra row cap protects against unusually dense input even when
        # its timestamps are all recent.
        conn.execute('''DELETE FROM reports WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY tail ORDER BY time DESC, id DESC
                ) AS position_rank FROM reports
            ) WHERE position_rank <= ?
        )''', (REPORT_HISTORY,))


# Run cleanup repeatedly until the shared stop flag is set. A cleanup error is logged and
# retried without intentionally stopping reception.
def cleanup_loop(stop, db_path=DATABASE_PATH):
    with closing(connect_database(db_path)) as conn:
        while not stop.is_set():
            try:
                cleanup_once(conn)
            except Exception:
                logging.exception('Cleanup failed; will retry')
            # Pause after each run, independently of report-history settings.
            stop.wait(CLEANUP_INTERVAL)


# Read the receiver time string and require it to be between now and ten seconds ago. Bad or
# future timestamps are not fresh.
def timestamp_fresh(value, now):
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
        return 0 <= now-stamp <= 10
    except (ValueError, TypeError, OverflowError):
        return False


# Build an HTTP address from the currently saved Stratux IP, so a later connection attempt
# can use a changed setting.
def receiver_url(path):
    import network_manager
    address=settings.load()['stratux_ip']
    if not network_manager.receiver_allowed(address):raise OSError('Selected Stratux association unavailable')
    return 'http://' + address + path


# Fetch the ownship/status JSON with a timeout and check that expected Stratux fields exist.
# A reachable unrelated web server is not enough.
def fetch_situation():
    with urllib.request.urlopen(receiver_url('/getSituation'), timeout=HTTP_TIMEOUT) as response:
        data=json.load(response)
    if not isinstance(data,dict) or not {'GPSLatitude','GPSLongitude','GPSFixQuality'} <= data.keys():
        raise ValueError('Device did not return a Stratux situation response')
    return data


# Poll GPS independently of traffic. Also publish receiver availability so the display can
# show a quiet waiting message.
def ownship_loop(stop, db_path=DATABASE_PATH):
    previous=None
    with closing(connect_database(db_path)) as conn:
        while not stop.is_set():
            # Use monotonic time for elapsed intervals: it cannot jump when the wall clock is
            # corrected. Use wall-clock time for database timestamps that need to be compared
            # across programs.
            started = time.monotonic()
            try:
                data=fetch_situation()
                record_ownship(conn, data)
                available=True; message='Stratux connected'
            except (OSError, ValueError, TimeoutError) as exc:
                available=False; message='Stratux not available. Waiting...'
                logging.debug('Receiver poll: %s', exc)
            except Exception:
                available=False; message='Collector error: check log'
                logging.exception('Ownship processing failed')
            # Publish reachability independently of whether GPS has a fix. An indoor receiver
            # can be connected and functioning while its ownship location is unavailable.
            with conn:
                conn.execute('INSERT OR REPLACE INTO receiver_status VALUES (1,?,?,?)', (time.time(),int(available),message))
            if previous != (available,message):
                logging.info(message); previous=(available,message)
            stop.wait(max(0.1, RECONNECT_DELAY if not available else OWNSHIP_INTERVAL - (time.monotonic()-started)))


def traffic_socket_options():
    """OS keepalive detects a broken link without application ping deadlines."""
    options=[(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)]
    for name,value in [('TCP_KEEPIDLE',10),('TCP_KEEPINTVL',3),('TCP_KEEPCNT',3)]:
        if hasattr(socket,name): options.append((socket.IPPROTO_TCP,getattr(socket,name),value))
    return options


# Back off briefly after failures, up to the configured maximum; avoid both a busy retry loop
# and a long fixed first delay.
def traffic_retry_delay(failures):
    return min(RECONNECT_DELAY, 2 ** min(max(0,failures-1),3))


# Report a quiet-stream timeout only when explicitly enabled. No local aircraft can
# legitimately mean no traffic messages.
def traffic_stream_idle(last_message, now, timeout=TRAFFIC_IDLE_SECONDS):
    return timeout>0 and last_message is not None and now-last_message>=timeout


# Consume queued messages and write them to SQLite away from the WebSocket callback. Log slow
# processing/backlogs so a pause can be diagnosed.
def traffic_writer(stop, inbox, db_path):
    last_backlog_log=0.0
    with closing(connect_database(db_path)) as conn:
        while not stop.is_set():
            # get() waits briefly for work. The short timeout lets this worker recheck the
            # stop flag, rather than hanging forever on an empty queue.
            try: received_at,data=inbox.get(timeout=.2)
            except queue.Empty: continue
            try:
                started=time.monotonic()
                lag=time.time()-received_at
                if lag>=2 and started-last_backlog_log>=10:
                    logging.warning('Traffic processing is %.1f seconds behind; %s frames queued',lag,inbox.qsize())
                    last_backlog_log=started
                record_traffic(conn,data,received_at)
                elapsed=time.monotonic()-started
                if elapsed>=1: logging.warning('Traffic database/log processing took %.1f seconds',elapsed)
            except Exception: logging.exception('Traffic message could not be saved')


# Probe Stratux, open its traffic stream, enqueue messages, and reconnect when needed. A
# helper watcher closes the connection for shutdown or an IP change.
def traffic_session_loop(stop, inbox, writer=None):
    failures=0
    while not stop.is_set():
        if writer is not None and not writer.is_alive(): raise RuntimeError('Traffic database writer stopped')
        try:
            fetch_situation()
            address=settings.load()['stratux_ip']
        except (OSError, ValueError, TimeoutError):
            failures+=1
            stop.wait(traffic_retry_delay(failures)); continue
        # Callbacks share this small connection-state dictionary. It belongs to the current
        # connection attempt and is rebuilt before the next attempt.
        state=dict(error='',opened=None,local_reason='',code=None,message='',last_message=None,dropped=0)
        # This callback runs when the socket connects. Remember the connection start and log
        # the receiver address.
        def on_open(ws):
            state['opened']=time.monotonic()
            logging.info('Connected to Stratux traffic at %s',address)
        # This callback handles an arriving frame: decode JSON, attach receipt time, and
        # enqueue it without waiting for a database write.
        def on_message(ws,message):
            if stop.is_set(): return
            state['last_message']=time.monotonic()
            try: data=json.loads(message)
            except (ValueError,TypeError):
                state['error']='Invalid traffic JSON'; return
            # A tuple groups the receipt timestamp and decoded message together. put_nowait()
            # does not pause the network callback while another worker writes to disk.
            item=(time.time(),data)
            try: inbox.put_nowait(item)
            # There is a hard queue size. If the writer falls far behind, discard the oldest
            # waiting frame and favor current observations instead of using unlimited memory.
            except queue.Full:
                # Bound memory and favor recent observations over an old backlog.
                try: inbox.get_nowait()
                except queue.Empty: pass
                try: inbox.put_nowait(item)
                except queue.Full: pass
                state['dropped']+=1
        # Remember the socket error so the eventual disconnect log can explain what happened.
        def on_error(ws,error):
            state['error']=f'{type(error).__name__}: {error}'
        # Remember the server close code/message if supplied. A missing code is not itself
        # proof of a successful or intentional close.
        def on_close(ws,code,message):
            state['code']=code;state['message']=message or ''
        ws=websocket.WebSocketApp('ws://'+address+'/traffic',on_message=on_message,
                                 on_open=on_open,on_error=on_error,on_close=on_close)
        # An Event is a thread-safe signal. This one stops the connection watcher after
        # run_forever ends, so an old watcher cannot interfere with the next connection.
        connection_finished=threading.Event()
        # Watch for shutdown, a dead database writer, a changed IP, or an optional idle
        # timeout; ask the socket to close when one applies.
        def close_on_stop():
            while not connection_finished.wait(0.2):
                if writer is not None and not writer.is_alive():
                    state['local_reason']='traffic database writer stopped'; stop.set()
                elif stop.is_set(): state['local_reason']='shutdown'
                elif settings.load()['stratux_ip'] != address or not __import__('network_manager').receiver_allowed(address): state['local_reason']='receiver IP changed'
                elif traffic_stream_idle(state['last_message'],time.monotonic(),TRAFFIC_IDLE_SECONDS):
                    state['local_reason']='traffic stream quiet; requesting a fresh connection'
                else: continue
                ws.close(); return
        watcher=threading.Thread(target=close_on_stop,name='traffic-stop',daemon=True)
        watcher.start()
        try:
            # Avoid a client ping timeout closing an otherwise usable stream.
            ws.run_forever(ping_interval=0,sockopt=traffic_socket_options(),http_no_proxy=[address])
        except Exception as exc:
            state['error']=f'{type(exc).__name__}: {exc}'
        finally:
            # finally runs whether the stream ended normally or by error. Set the signal,
            # wait for the watcher to finish, then close the socket to release resources.
            connection_finished.set(); watcher.join(); ws.close()
        if state['dropped']:
            logging.warning('Traffic queue overflow: dropped %s older observations',state['dropped'])
        if stop.is_set():
            logging.info('Traffic connection closed for shutdown'); break
        if state['local_reason']:
            logging.info('Traffic connection closed: %s',state['local_reason'])
            failures=0; continue
        uptime=None if state['opened'] is None else time.monotonic()-state['opened']
        failures=1 if uptime is not None and uptime>=10 else failures+1
        delay=traffic_retry_delay(failures)
        reason=state['error'] or (f"server close {state['code']}: {state['message']}" if state['code'] is not None else 'connection ended without a close frame')
        logging.warning('Traffic disconnected (%s); retry in %s seconds',reason,delay)
        stop.wait(delay)


# Start one writer thread plus a bounded input queue, run the stream loop, then stop and join
# the writer during shutdown.
def traffic_loop(stop, db_path=DATABASE_PATH):
    inbox=queue.Queue(maxsize=TRAFFIC_QUEUE_SIZE)
    writer_stop=threading.Event()
    writer=threading.Thread(target=traffic_writer,args=(writer_stop,inbox,db_path),name='traffic-writer')
    writer.start()
    try: traffic_session_loop(stop,inbox,writer)
    finally:
        writer_stop.set();writer.join()


# Parse launch options, validate setup, start the appropriate real/demo workers, monitor
# their health, and stop them together on exit.
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-level',choices=('DEBUG','INFO','WARNING','ERROR'),default='INFO')
    parser.add_argument('--traffic-idle-seconds',type=float,default=0,help='Optional: refresh a formerly active but quiet traffic stream; 0 disables')
    parser.add_argument('--demo',action='store_true',help='Offline airport-pattern simulation; uses a separate demo database')
    parser.add_argument('--demo-seed',type=int,default=22,help='Repeatable random seed for demo traffic')
    parser.add_argument('--db',type=Path,default=None,help='Database override (must have an existing parent directory)')
    # Parse command-line switches only at launch. --demo selects synthetic input and, unless
    # overridden, a separate database; it does not turn real recorded traffic into simulated
    # data.
    args=parser.parse_args()
    if not math.isfinite(args.traffic_idle_seconds) or args.traffic_idle_seconds<0: parser.error('Traffic idle timeout must be a finite nonnegative number')
    global TRAFFIC_IDLE_SECONDS, DATABASE_PATH
    TRAFFIC_IDLE_SECONDS=args.traffic_idle_seconds
    DATABASE_PATH=args.db or (DATABASE_PATH.with_name("demo_objects.db") if args.demo else DATABASE_PATH)
    logging.basicConfig(level=getattr(logging,args.log_level), format='%(asctime)s %(threadName)s %(levelname)s %(message)s')
    settings.load()  # Fail clearly on invalid configuration before starting workers.
    logging.getLogger('websocket').setLevel(logging.CRITICAL)
    websocket.setdefaulttimeout(HTTP_TIMEOUT)
    problem=database_problem(DATABASE_PATH)
    if problem:raise RuntimeError(problem)
    initialize(DATABASE_PATH)
    logging.info('Using database %s', DATABASE_PATH)
    # All workers receive this same stop signal. Setting it requests a cooperative shutdown;
    # each worker finishes its current bounded operation and exits its loop.
    stop = threading.Event()
    if args.demo:
        from demo_traffic import run as demo_loop
        workers=[threading.Thread(target=demo_loop,args=(stop,DATABASE_PATH,args.demo_seed),name="demo"),
                 threading.Thread(target=cleanup_loop,args=(stop,DATABASE_PATH),name="cleanup")]
    else:
        workers = [
            threading.Thread(target=ownship_loop, args=(stop,DATABASE_PATH), name='ownship'),
            threading.Thread(target=cleanup_loop, args=(stop,DATABASE_PATH), name='cleanup'),
            threading.Thread(target=traffic_loop, args=(stop,DATABASE_PATH), name='traffic'),
        ]
    try:
        for worker in workers:
            worker.start()
        # The main thread checks worker health once per second. A failed worker should end
        # the process so systemd can restart a complete collector, rather than leaving a
        # silently half-working service.
        while not stop.wait(1):
            if any(not worker.is_alive() for worker in workers):
                logging.error('A worker stopped unexpectedly; shutting down')
                break
    except KeyboardInterrupt:
        logging.info('Shutdown requested')
    finally:
        stop.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join()
        logging.info('All workers stopped; database connections closed')


# Python sets __name__ to '__main__' only when this file is launched directly. Importing
# these functions from tests or the demo does not automatically start the collector.
if __name__ == '__main__':
    main()
