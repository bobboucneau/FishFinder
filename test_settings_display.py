# READING THE TESTS: this file checks behavior without requiring a flight.
# An assert... call states what must be true; a failed assertion means the
# observed result differs from the expected one. Mock/patch objects temporarily
# replace a dependency, so tests can exercise errors without changing hardware.
# These checks on a Mac do not replace touchscreen/GPS validation on the Pi.

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
    # Check: label settings zoom and runway extensions.
    def test_label_settings_zoom_and_runway_extensions(self):
        self.assertEqual(settings.validate({})['label_size'],'normal')
        self.assertTrue(settings.validate({})['runway_extensions'])
        with self.assertRaises(ValueError):settings.validate({'label_size':'huge'})
        with self.assertRaises(ValueError):settings.validate({'runway_extensions':'yes'})
        factors=[settings.label_scale(settings.DEFAULTS,r) for r in (20,10,5,2)]
        self.assertEqual(factors,sorted(set(factors)))
        self.assertGreater(settings.label_scale(dict(settings.DEFAULTS,label_size='large'),20),factors[0])
        obj=gui();origin=obj.airport_origin
        airport=dict(obj.catalog.airports['KRHV'],ident='TEST',code='TEST',lat=origin[0],lon=origin[1],runways=[dict(le_latitude_deg=origin[0]-.005,le_longitude_deg=origin[1],he_latitude_deg=origin[0]+.005,he_longitude_deg=origin[1])])
        obj.catalog.airports['TEST']=airport
        with patch.object(obj.catalog,'nearby',return_value=[(0,airport,0)]):
            def redraw(radius):
                obj.radius_nm=radius;obj.airport_query=None;obj.draw()
                return [coords for name,coords,kw in obj.canvas.commands if kw.get('tags')=='runway-extension']
            self.assertEqual(len(redraw(5)),2)
            for coords in redraw(5):self.assertAlmostEqual(math.dist(coords[:2],coords[2:])/obj.pixels,3,places=4)
            for radius in (2,5,10,20):self.assertEqual(len(redraw(radius)),2)
            obj.config['runway_extensions']=False
            for radius in (2,5,10,20):self.assertFalse(redraw(radius))
            obj.config['runway_extensions']=True;airport['runways']=[dict(length_ft=3000,le_heading_degT=90)]
            self.assertFalse(redraw(5))  # A schematic is not a located centerline.
        obj.stop.set()

    # Check: wake then range and exit touch actions.
    def test_wake_then_range_and_exit_touch_actions(self):
        obj=gui();obj.touch_debug=True
        from io import StringIO
        log=StringIO()
        obj.last_touch=time.monotonic()-20;obj.draw()
        with patch('sys.stdout',log):
            obj.tap(SimpleNamespace(x=269,y=721))
            self.assertTrue(obj.idle);self.assertEqual(obj.radius_nm,10)
            obj.tap(SimpleNamespace(x=269,y=721))
            self.assertFalse(obj.idle);self.assertEqual(obj.radius_nm,10)
            obj.tap(SimpleNamespace(x=269,y=721))
            self.assertEqual(obj.radius_nm,2)
            self.assertFalse(any(kw.get('text')=='Exit' for _,_,kw in obj.canvas.commands))
            obj.request_exit();self.assertTrue(obj.exit_pending)
            obj.tap(SimpleNamespace(x=318,y=460));self.assertFalse(obj.exit_pending)
            obj.request_exit()
            with patch.object(obj,'close') as close:
                obj.tap(SimpleNamespace(x=482,y=460));close.assert_called_once()
        self.assertIn('canvas=800x800',log.getvalue())
        self.assertIn('TOUCH ACTION',log.getvalue())
        self.assertEqual(obj.touch_mark[:2],(482,460))
        obj.stop.set()

    # Check: hidden object tap preserves hidden controls.
    def test_hidden_object_tap_preserves_hidden_controls(self):
        obj=gui();obj.last_touch=time.monotonic()-20;obj.draw()
        x,y,tail=obj.hits[0]
        obj.hits=[(x,y,tail)];obj.airport_hits=[]
        obj.tap(SimpleNamespace(x=x,y=y))
        self.assertIsNone(obj.selected)
        obj.root.fire(obj.pending_tap[0])
        self.assertEqual(obj.selected,tail);self.assertTrue(obj.idle)
        self.assertEqual(obj.buttons,[])
        obj.stop.set()

    # Check: double tap cancels object popup.
    def test_double_tap_cancels_object_popup(self):
        obj=gui();obj.last_touch=time.monotonic()-20;obj.draw()
        x,y,tail=obj.hits[0]
        obj.hits=[(x,y,tail)];obj.airport_hits=[]
        obj.tap(SimpleNamespace(x=x,y=y))
        token=obj.pending_tap[0]
        obj.tap(SimpleNamespace(x=x+5,y=y+5))
        self.assertIsNone(obj.pending_tap);self.assertIsNone(obj.selected)
        self.assertNotIn(token,obj.root.callbacks);self.assertFalse(obj.idle)
        obj.selected=tail;obj.last_touch=time.monotonic()-20;obj.draw()
        obj.tap(SimpleNamespace(x=300,y=300));obj.tap(SimpleNamespace(x=300,y=300))
        self.assertIsNone(obj.selected);self.assertFalse(obj.idle)
        obj.stop.set()

    # Check: hide vertical setting and display.
    def test_hide_vertical_setting_and_display(self):
        self.assertFalse(settings.validate({})['hide_vertical'])
        with self.assertRaises(ValueError):settings.validate({'hide_vertical':'yes'})
        obj=gui();obj.config['hide_vertical']=True
        with patch.object(d,'vertical_clear',return_value=True):obj.draw()
        self.assertFalse([hit for hit in obj.hits if hit[2]!='__ownship__'])
        with patch.object(d,'vertical_clear',return_value=False):obj.draw()
        self.assertTrue([hit for hit in obj.hits if hit[2]!='__ownship__'])
        obj.stop.set()

    # Check: ground map preference saved and applied.
    def test_ground_map_preference_saved_and_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            self.assertFalse(settings.explicit('ground_map',path))
            settings.save(dict(ground_map=True),path)
            self.assertTrue(settings.load(path)['ground_map'])
            self.assertTrue(settings.explicit('ground_map',path))
            settings.save(dict(ground_map=False),path)
            self.assertFalse(settings.load(path)['ground_map'])
            with self.assertRaises(ValueError):settings.validate(dict(ground_map='off'))
        obj=gui();obj.config['ground_map']=True;obj.ground_level=1
        renderer=SimpleNamespace(close=lambda:None,poll=lambda:None,request=lambda state:None,result=None,error="",bounds=None)
        obj.ground=renderer
        with patch.object(settings,'save',side_effect=lambda values:settings.validate(values)):
            obj.apply_settings(dict(obj.config,ground_map=False))
            self.assertIsNone(obj.ground);self.assertEqual(obj.ground_level,0)
            # Enable from Setup without a --demo-map launch flag; start lazily in demo draw.
            with patch.object(d.demo_ground,'GroundLayer',return_value=renderer) as start:
                obj.apply_settings(dict(obj.config,ground_map=True))
                start.assert_called_once();self.assertEqual(obj.ground_level,1)
        obj.stop.set()

    # Check: settings validation and atomic persistence.
    def test_settings_validation_and_atomic_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            cfg=settings.save(dict(stratux_ip='192.168.20.1',own_tail='n123ab'),path)
            self.assertEqual(settings.load(path)['own_tail'],'N123AB')
            baseline=path.read_text()
            with self.assertRaises(ValueError):settings.save(dict(stratux_ip='bad'),path)
            self.assertEqual(path.read_text(),baseline)
            self.assertEqual(cfg['vertical_threshold_ft'],5000)

    # Check: vertical styles and closure.
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

    # Check: scope idle and wake touch.
    def test_scope_idle_and_wake_touch(self):
        display=gui()
        self.assertAlmostEqual(display.pixels*display.radius_nm,398)
        self.assertTrue(any(k.get('text')=='Setup' for _,_,k in display.canvas.commands))
        display.last_touch=time.monotonic()-11;display.draw()
        self.assertTrue(display.idle);self.assertEqual(display.buttons,[])
        labels=[k.get('text','') for _,_,k in display.canvas.commands]
        self.assertIn('N123AB',labels)
        self.assertIn('10 NM',labels)
        ranges=[coords[0] for _,coords,kw in display.canvas.commands if str(kw.get('text','')).endswith(' NM')]
        self.assertEqual(len(ranges),4);self.assertEqual(len(set(ranges)),1)
        self.assertNotIn('Setup',labels);self.assertNotIn('Exit',labels)
        airport_labels=[kw['text'] for _,_,kw in display.canvas.commands if kw.get('tags')=='map-label' and kw.get('fill') in ('#f075d5','#48baff','#9aafaa')]
        self.assertTrue(airport_labels)
        self.assertTrue(all(' · ' not in label for label in airport_labels))
        self.assertTrue(display.hits)
        display.tap(SimpleNamespace(x=400,y=770))
        self.assertTrue(display.idle);self.assertFalse(display.exit_pending)
        display.tap(SimpleNamespace(x=400,y=770));self.assertFalse(display.idle)
        display.tap(SimpleNamespace(x=400,y=770));self.assertFalse(display.exit_pending)
        display.request_exit();self.assertTrue(display.exit_pending)

    # Check: parallel runways without changing cache.
    def test_parallel_runways_without_changing_cache(self):
        display=gui();airport=display.catalog.airports['KRHV']
        baseline=json.dumps(airport)
        segments=runway_segments(airport,d.xy)
        vectors=[(b[0]-a[0],b[1]-a[1]) for r,a,b,_ in segments]
        self.assertAlmostEqual(vectors[0][0]*vectors[1][1]-vectors[0][1]*vectors[1][0],0)
        self.assertTrue(all(r.get('_aligned') for r,_,_,_ in segments))
        self.assertEqual(json.dumps(airport),baseline)

    # Check: collector migration and nullable own altitude.
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

    # Check: wrong device and connection failure are quiet.
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

    # Check: traffic reconnect options and diagnostics.
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

    # Check: saved reports return to info level.
    def test_saved_reports_return_to_info_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path)
            with closing(sqlite3.connect(path)) as conn,patch.object(collector.logging,'info') as info:
                collector.record_traffic(conn,dict(Icao_addr=124,Reg='N124AB',Lat=37,Lng=-122,Alt=10000,Speed=100),time.time())
                self.assertTrue(info.called)
                info.reset_mock()
                collector.record_traffic(conn,dict(Icao_addr=124,Reg='N124AB',Lat=37,Lng=-122,Alt=10000,Speed=100),time.time())
                self.assertTrue(info.called);self.assertFalse(info.call_args.args[6]);self.assertIn('sample_interval',info.call_args.args[7])

    # Check: quiet stream is normal by default.
    def test_quiet_stream_is_normal_by_default(self):
        self.assertEqual(collector.TRAFFIC_IDLE_SECONDS,0)
        self.assertFalse(collector.traffic_stream_idle(None,1000,20))
        self.assertFalse(collector.traffic_stream_idle(1,1000,0))
        self.assertTrue(collector.traffic_stream_idle(1,22,20))

    # Check: database processing runs off websocket callback.
    def test_database_processing_runs_off_websocket_callback(self):
        import threading
        arrived=threading.Event();release=threading.Event();second_received=threading.Event()
        stopped=threading.Event()
        class WS:
            def __init__(self,url,**callbacks):self.callbacks=callbacks
            def run_forever(self,**kwargs):
                self.callbacks['on_open'](self)
                self.callbacks['on_message'](self,'{"Icao_addr":123}')
                self.asserted=arrived.wait(1)
                self.callbacks['on_message'](self,'{"Icao_addr":124}')
                second_received.set();release.set();stopped.set()
            def close(self):pass
        def slow_record(*args):arrived.set();release.wait(2)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path)
            with patch.object(collector,'fetch_situation',return_value={}),patch.object(collector.websocket,'WebSocketApp',WS,create=True),patch.object(collector,'record_traffic',side_effect=slow_record):
                collector.traffic_loop(stopped,path)
        self.assertTrue(arrived.is_set());self.assertTrue(second_received.is_set())

    # Check: extrapolated reports preserve uncertainty.
    def test_extrapolated_reports_preserve_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path);collector.initialize(path)
            base=dict(Icao_addr=125,Lat=37,Lng=-122,Alt=10000,Speed=100,
                      Position_valid=True,Speed_valid=True,Age=30,ExtrapolatedPosition=True,
                      AltIsGNSS=False,AgeLastAlt=0)
            with closing(sqlite3.connect(path)) as conn:
                self.assertTrue(collector.record_traffic(conn,base))
                self.assertFalse(collector.record_traffic(conn,dict(base,Age=61)))
                self.assertFalse(collector.record_traffic(conn,dict(base,Position_valid=False)))
                self.assertFalse(collector.record_traffic(conn,dict(base,ExtrapolatedPosition=False)))
            snap=d.read_snapshot(path)
            p=snap.reports['icao:00007D'][-1]
            self.assertTrue(p.estimated);self.assertEqual(p.position_age,30)
            self.assertIsNone(p.comparison_alt)

    # Check: report rejection reasons are visible.
    def test_report_rejection_reasons_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.db';collector.initialize(path)
            base=dict(Icao_addr=125,Reg='N125AB',Lat=37,Lng=-122,Alt=10000,Speed=100)
            with closing(sqlite3.connect(path)) as conn:
                for changes,reason in [(dict(Age=12),'position_age_outside_0_to_10s'),(dict(Position_valid=False),'position_flag_invalid'),(dict(Speed_valid=False),'speed_flag_invalid'),(dict(Alt=None),'altitude_missing_or_invalid')]:
                    with patch.object(collector.logging,'info') as info:
                        self.assertFalse(collector.record_traffic(conn,dict(base,**changes),time.time()))
                        self.assertIn(reason,info.call_args.args[7])

    # Check: truncated update retains cache.
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
