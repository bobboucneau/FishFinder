#!/usr/local/Fishfinder/.venv/bin/python3
"""Collect Stratux traffic and ownship; periodically prune the shared database.

Requires websocket-client. Existing table/column names are preserved.
Do not run the old collector/OwnShip.py alongside this replacement.
"""

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

import websocket

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


def connect_database(db_path=DATABASE_PATH):
    # Each calling thread owns its connection. Wait briefly for other writers.
    return sqlite3.connect(str(db_path), timeout=10)


def initialize(db_path=DATABASE_PATH):
    if sqlite3.sqlite_version_info < (3, 25, 0):
        raise RuntimeError('SQLite 3.25 or newer is required for history cleanup')
    # Require the directory to exist: do not silently create a wrong location.
    if not Path(db_path).parent.is_dir():
        raise RuntimeError(f'Database directory does not exist: {Path(db_path).parent}')
    with closing(connect_database(db_path)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS aircraft (tail TEXT PRIMARY KEY, time REAL)')
            conn.execute('''CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tail TEXT, time REAL,
                speed REAL, asl REAL, longitude REAL, latitude REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ownship (
                id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL,
                speed REAL, asl REAL, longitude REAL, latitude REAL)''')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(aircraft)')}
            for name in ('registration', 'callsign'):
                if name not in columns:
                    conn.execute(f'ALTER TABLE aircraft ADD COLUMN {name} TEXT')
            for table in ('reports', 'ownship'):
                columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
                for name, kind in [('comparison_alt','REAL'),('alt_ref','TEXT')]:
                    if name not in columns: conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
            conn.execute('CREATE TABLE IF NOT EXISTS receiver_status (id INTEGER PRIMARY KEY CHECK(id=1), time REAL, available INTEGER, message TEXT)')
            conn.execute('CREATE INDEX IF NOT EXISTS aircraft_time_idx ON aircraft(time)')
            conn.execute('CREATE INDEX IF NOT EXISTS reports_time_idx ON reports(time)')
            conn.execute('CREATE INDEX IF NOT EXISTS reports_tail_time_idx ON reports(tail, time DESC, id DESC)')


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def valid_position(lat, lng):
    return (lat is not None and lng is not None
            and -90 <= lat <= 90 and -180 <= lng <= 180)


def identity(data):
    def label(value):
        return value.strip().upper() if isinstance(value, str) and value.strip().upper() != 'NO TAIL' else ''
    registration, callsign = label(data.get('Reg')), label(data.get('Tail'))
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


def record_traffic(conn, data, received_at=None):
    if not isinstance(data, dict):
        raise ValueError('Traffic message must be a JSON object')
    tail, registration, callsign = identity(data)
    if tail is None:
        return False
    timestamp = time.time() if received_at is None else received_at
    lat, lng = number(data.get('Lat')), number(data.get('Lng'))
    altitude, speed = number(data.get('Alt')), number(data.get('Speed'))
    # Explicit validity flags take precedence; older feeds may omit them.
    position_age=number(data.get('Age'))
    position_ok = data.get('Position_valid', True) is True and valid_position(lat, lng) and (position_age is None or 0 <= position_age <= 10)
    speed_ok = data.get('Speed_valid', True) is True and speed is not None and speed >= 0
    report_ok = position_ok and speed_ok and altitude is not None
    with conn:
        conn.execute('INSERT OR IGNORE INTO aircraft (tail) VALUES (?)', (tail,))
        conn.execute('''UPDATE aircraft SET time = ?,
            registration = COALESCE(NULLIF(?, ''), registration),
            callsign = CASE WHEN ? = '' THEN callsign
                WHEN ? = COALESCE(NULLIF(?, ''), registration) AND callsign IS NOT NULL
                    THEN callsign ELSE ? END
            WHERE tail = ?''',
            (timestamp, registration, callsign, callsign, registration, callsign, tail))
        if report_ok:
            previous = conn.execute(
                'SELECT time FROM reports WHERE tail = ? ORDER BY time DESC, id DESC LIMIT 1',
                (tail,),
            ).fetchone()
            # Keep one position per second per aircraft, rather than every frame.
            # Resume immediately if the system clock has moved backwards.
            previous_time = number(previous[0]) if previous else None
            report_ok = (previous_time is None or timestamp < previous_time
                         or timestamp - previous_time >= REPORT_INTERVAL)
        if report_ok:
            conn.execute('''INSERT INTO reports
                (tail, time, speed, asl, longitude, latitude, comparison_alt, alt_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (tail, timestamp, speed, altitude, lng, lat,
                 altitude if data.get('AltIsGNSS') is False and number(data.get('AgeLastAlt')) is not None and 0 <= number(data.get('AgeLastAlt')) <= 10 else None,
                 'pressure' if data.get('AltIsGNSS') is False else None))
    logging.info('Traffic %s | altitude=%s speed=%s position=(%s, %s) saved=%s',
        tail, altitude, speed, lat, lng, report_ok)
    return report_ok


def record_ownship(conn, data, received_at=None):
    if not isinstance(data, dict):
        raise ValueError('Situation response must be a JSON object')
    timestamp = time.time() if received_at is None else received_at
    if 'GPSLastFixLocalTime' in data and not timestamp_fresh(data['GPSLastFixLocalTime'],timestamp):
        return False
    # Skip an explicitly reported lack of GPS fix.
    if 'GPSFixQuality' in data:
        quality = number(data['GPSFixQuality'])
        if quality is None or quality <= 0:
            return False
    lat = number(data.get('GPSLatitude'))
    lng = number(data.get('GPSLongitude'))
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


def cleanup_once(conn, now=None):
    timestamp = time.time() if now is None else now
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
        conn.execute('''DELETE FROM reports WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY tail ORDER BY time DESC, id DESC
                ) AS position_rank FROM reports
            ) WHERE position_rank <= ?
        )''', (REPORT_HISTORY,))


def cleanup_loop(stop, db_path=DATABASE_PATH):
    with closing(connect_database(db_path)) as conn:
        while not stop.is_set():
            try:
                cleanup_once(conn)
            except Exception:
                logging.exception('Cleanup failed; will retry')
            # Pause after each run, independently of report-history settings.
            stop.wait(CLEANUP_INTERVAL)


def timestamp_fresh(value, now):
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
        return 0 <= now-stamp <= 10
    except (ValueError, TypeError, OverflowError):
        return False


def receiver_url(path):
    return 'http://' + settings.load()['stratux_ip'] + path


def fetch_situation():
    with urllib.request.urlopen(receiver_url('/getSituation'), timeout=HTTP_TIMEOUT) as response:
        data=json.load(response)
    if not isinstance(data,dict) or not {'GPSLatitude','GPSLongitude','GPSFixQuality'} <= data.keys():
        raise ValueError('Device did not return a Stratux situation response')
    return data


def ownship_loop(stop, db_path=DATABASE_PATH):
    previous=None
    with closing(connect_database(db_path)) as conn:
        while not stop.is_set():
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


def traffic_retry_delay(failures):
    return min(RECONNECT_DELAY, 2 ** min(max(0,failures-1),3))


def traffic_stream_idle(last_message, now, timeout=TRAFFIC_IDLE_SECONDS):
    return timeout>0 and last_message is not None and now-last_message>=timeout


def traffic_writer(stop, inbox, db_path):
    last_backlog_log=0.0
    with closing(connect_database(db_path)) as conn:
        while not stop.is_set():
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
        state=dict(error='',opened=None,local_reason='',code=None,message='',last_message=None,dropped=0)
        def on_open(ws):
            state['opened']=time.monotonic()
            logging.info('Connected to Stratux traffic at %s',address)
        def on_message(ws,message):
            if stop.is_set(): return
            state['last_message']=time.monotonic()
            try: data=json.loads(message)
            except (ValueError,TypeError):
                state['error']='Invalid traffic JSON'; return
            item=(time.time(),data)
            try: inbox.put_nowait(item)
            except queue.Full:
                # Bound memory and favor recent observations over an old backlog.
                try: inbox.get_nowait()
                except queue.Empty: pass
                try: inbox.put_nowait(item)
                except queue.Full: pass
                state['dropped']+=1
        def on_error(ws,error):
            state['error']=f'{type(error).__name__}: {error}'
        def on_close(ws,code,message):
            state['code']=code;state['message']=message or ''
        ws=websocket.WebSocketApp('ws://'+address+'/traffic',on_message=on_message,
                                 on_open=on_open,on_error=on_error,on_close=on_close)
        connection_finished=threading.Event()
        def close_on_stop():
            while not connection_finished.wait(0.2):
                if writer is not None and not writer.is_alive():
                    state['local_reason']='traffic database writer stopped'; stop.set()
                elif stop.is_set(): state['local_reason']='shutdown'
                elif settings.load()['stratux_ip'] != address: state['local_reason']='receiver IP changed'
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


def traffic_loop(stop, db_path=DATABASE_PATH):
    inbox=queue.Queue(maxsize=TRAFFIC_QUEUE_SIZE)
    writer_stop=threading.Event()
    writer=threading.Thread(target=traffic_writer,args=(writer_stop,inbox,db_path),name='traffic-writer')
    writer.start()
    try: traffic_session_loop(stop,inbox,writer)
    finally:
        writer_stop.set();writer.join()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-level',choices=('DEBUG','INFO','WARNING','ERROR'),default='INFO')
    parser.add_argument('--traffic-idle-seconds',type=float,default=0,help='Optional: refresh a formerly active but quiet traffic stream; 0 disables')
    args=parser.parse_args()
    if not math.isfinite(args.traffic_idle_seconds) or args.traffic_idle_seconds<0: parser.error('Traffic idle timeout must be a finite nonnegative number')
    global TRAFFIC_IDLE_SECONDS
    TRAFFIC_IDLE_SECONDS=args.traffic_idle_seconds
    logging.basicConfig(level=getattr(logging,args.log_level), format='%(asctime)s %(threadName)s %(levelname)s %(message)s')
    settings.load()  # Fail clearly on invalid configuration before starting workers.
    logging.getLogger('websocket').setLevel(logging.CRITICAL)
    websocket.setdefaulttimeout(HTTP_TIMEOUT)
    initialize()
    logging.info('Using database %s', DATABASE_PATH)
    stop = threading.Event()
    workers = [
        threading.Thread(target=ownship_loop, args=(stop,), name='ownship'),
        threading.Thread(target=cleanup_loop, args=(stop,), name='cleanup'),
        threading.Thread(target=traffic_loop, args=(stop,), name='traffic'),
    ]
    try:
        for worker in workers:
            worker.start()
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


if __name__ == '__main__':
    main()
