from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import settings
import traffic_display as d
from test_airports import gui
from airport_data import runway_segments
import update_airports as updater
try:
    import FishFinder as collector
except ModuleNotFoundError as exc:
    if exc.name!='websocket':raise
    # These tests cover database/probe behavior, without opening a WebSocket.
    with patch.dict('sys.modules',websocket=SimpleNamespace()):
        import FishFinder as collector


class Tests(unittest.TestCase):
    def test_settings_validation_and_atomic_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            cfg=settings.save(dict(stratux_ip='192.168.20.1',own_tail='n123ab'),path)
            self.assertEqual(settings.load(path)['own_tail'],'N123AB')
            baseline=path.read_text()
            with self.assertRaises(ValueError):settings.save(dict(stratux_ip='bad'),path)
            self.assertEqual(path.read_text(),baseline)
            self.assertEqual(cfg['vertical_threshold_ft'],5000)

    def test_vertical_styles_and_closure(self):
        now=time.time()
        def track(alt,rate=0,ref='pressure'):
            return [d.Point(i,now-20+i*10,37,-122,100,alt+rate*i*10,alt+rate*i*10,ref) for i in range(3)]
        own=track(3000)
        self.assertTrue(d.vertical_clear(track(14000),own,5000))
        self.assertFalse(d.vertical_clear(track(14000,-30),own,5000))
        self.assertFalse(d.vertical_clear(track(14000),[],5000))
        self.assertFalse(d.vertical_clear(track(14000,ref=None),own,5000))
        self.assertFalse(d.vertical_clear(track(14000)[-1:],own,5000))
        unknown=[d.Point(i,now-20+i*10,37,-122,100,None,3000,'pressure') for i in range(3)]
        self.assertFalse(d.vertical_clear(track(14000),unknown,5000))

    def test_scope_idle_and_wake_touch(self):
        display=gui()
        self.assertAlmostEqual(display.pixels*display.radius_nm,398)
        self.assertTrue(any(k.get('text')=='Setup' for _,_,k in display.canvas.commands))
        display.last_touch=time.monotonic()-11;display.draw()
        self.assertTrue(display.idle);self.assertEqual(display.buttons,[])
        labels=[k.get('text','') for _,_,k in display.canvas.commands]
        self.assertIn('N123AB',labels)
        self.assertIn('10 NM',labels)
        self.assertNotIn('Setup',labels);self.assertNotIn('Exit',labels)
        airport_labels=[kw['text'] for _,_,kw in display.canvas.commands if kw.get('tags')=='map-label' and kw.get('fill')==d.BLUE]
        self.assertTrue(airport_labels)
        self.assertTrue(all(' · ' not in label for label in airport_labels))
        self.assertTrue(display.hits)
        display.tap(SimpleNamespace(x=400,y=770))
        self.assertFalse(display.idle);self.assertFalse(display.exit_pending)
        display.tap(SimpleNamespace(x=400,y=770));self.assertTrue(display.exit_pending)

    def test_parallel_runways_without_changing_cache(self):
        display=gui();airport=display.catalog.airports['KRHV']
        baseline=json.dumps(airport)
        segments=runway_segments(airport,d.xy)
        vectors=[(b[0]-a[0],b[1]-a[1]) for r,a,b,_ in segments]
        self.assertAlmostEqual(vectors[0][0]*vectors[1][1]-vectors[0][1]*vectors[1][0],0)
        self.assertTrue(all(r.get('_aligned') for r,_,_,_ in segments))
        self.assertEqual(json.dumps(airport),baseline)

    def test_collector_migration_and_nullable_own_altitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path);collector.initialize(path)
            conn=sqlite3.connect(path)
            now=time.time()
            try:
                self.assertTrue(collector.record_ownship(conn,dict(GPSLatitude=37,GPSLongitude=-122,GPSFixQuality=1,GPSGroundSpeed=0),now))
                row=conn.execute('SELECT asl,comparison_alt FROM ownship').fetchone();self.assertEqual(row,(None,None))
                self.assertTrue(collector.record_traffic(conn,dict(Icao_addr=123,Reg='N123AB',Lat=37,Lng=-122,Alt=12000,Speed=120,AltIsGNSS=False,AgeLastAlt=2),now))
                self.assertEqual(conn.execute('SELECT comparison_alt,alt_ref FROM reports').fetchone(),(12000,'pressure'))
            finally:conn.close()
            self.assertIsNone(d.read_snapshot(path).ownship[-1].altitude)

    def test_wrong_device_and_connection_failure_are_quiet(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"hello":"world"}'
        with patch.object(collector.urllib.request,'urlopen',return_value=Response()):
            with self.assertRaises(ValueError):collector.fetch_situation()
        class Stop:
            stopped=False
            def is_set(self):return self.stopped
            def wait(self,*args):self.stopped=True;return True
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path)
            with patch.object(collector,'fetch_situation',side_effect=OSError('no route')),patch.object(collector.logging,'exception') as errors:
                collector.ownship_loop(Stop(),path);errors.assert_not_called()
            with sqlite3.connect(path) as conn:
                row=conn.execute('SELECT available,message FROM receiver_status').fetchone()
                self.assertEqual(row,(0,'Stratux not available. Waiting...'))

    def test_traffic_reconnect_options_and_diagnostics(self):
        self.assertEqual([collector.traffic_retry_delay(n) for n in range(1,8)],[1,2,4,5,5,5,5])
        options=collector.traffic_socket_options()
        self.assertIn((collector.socket.SOL_SOCKET,collector.socket.SO_KEEPALIVE,1),options)
        captured={}
        class Stop:
            stopped=False
            def is_set(self):return self.stopped
            def wait(self,delay):captured['delay']=delay;self.stopped=True;return True
        class WS:
            def __init__(self,url,**callbacks):self.callbacks=callbacks
            def run_forever(self,**kwargs):
                captured.update(kwargs)
                self.callbacks['on_open'](self)
                self.callbacks['on_error'](self,TimeoutError('test link failure'))
                self.callbacks['on_close'](self,None,None)
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path)
            with patch.object(collector,'fetch_situation',return_value={}),patch.object(collector.websocket,'WebSocketApp',WS,create=True),patch.object(collector.logging,'warning') as warning:
                collector.traffic_loop(Stop(),path)
                self.assertIn('test link failure',warning.call_args.args[1])
        self.assertEqual(captured['ping_interval'],0)
        self.assertEqual(captured['delay'],1)
        self.assertEqual(captured['http_no_proxy'],['192.168.10.1'])

    def test_saved_reports_return_to_info_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path)
            with closing(sqlite3.connect(path)) as conn,patch.object(collector.logging,'info') as info:
                collector.record_traffic(conn,dict(Icao_addr=124,Reg='N124AB',Lat=37,Lng=-122,Alt=10000,Speed=100),time.time())
                self.assertTrue(info.called)

    def test_truncated_update_retains_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'airports.json'
            path.write_text(json.dumps(dict(countries=[],airports=[{}]*100)))
            original=path.read_bytes()
            row=dict(ident='TEST',type='small_airport',name='Test',latitude_deg='0',longitude_deg='0')
            with patch.object(updater,'fetch',side_effect=[[row],[dict(airport_ident='TEST')],[dict(airport_ident='TEST')]]):
                with self.assertRaises(ValueError):updater.refresh(path)
            self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
