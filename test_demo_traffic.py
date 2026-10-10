from contextlib import closing
import itertools
import math
import sqlite3
import tempfile
import time
from pathlib import Path
import unittest
from demo_traffic import Scenario,MPH_TO_KNOTS
from test_settings_display import collector
from traffic_display import read_snapshot,draw_splash
from test_airports import Canvas,gui


class DemoTests(unittest.TestCase):
    def test_airport_patterns_and_two_circuits(self):
        scene=Scenario()
        for points,elevation in zip(scene.patterns,[2100,2933,1325,234]):
            self.assertEqual(points[0][2],elevation)
            self.assertEqual(points[-1][2],elevation)
            self.assertEqual(max(p[2] for p in points),elevation+1000)
            self.assertAlmostEqual(points[0][3],75*MPH_TO_KNOTS)
            for a,b,c in zip(points,points[1:],points[2:]):
                v=(b[0]-a[0],b[1]-a[1]);w=(c[0]-b[0],c[1]-b[1])
                # Downwind acceleration midpoint is straight; the other turns are right angles.
                cross=v[0]*w[1]-v[1]*w[0]
                if abs(cross)>1e-6:
                    self.assertLess(cross,0)
                    self.assertAlmostEqual(v[0]*w[0]+v[1]*w[1],0,places=6)
        scene.advance(0);self.assertGreater(scene.flights[0].end,330)

    def test_hour_of_traffic_is_separated_and_repeatable(self):
        scene=Scenario();kinds=set();both=False
        for t in range(3601):
            scene.advance(t);active=[(f,f.sample(t)) for f in scene.flights if f.sample(t) is not None]
            kinds.update(f.kind for f,p in active)
            both|=sum(f.kind=='C172' and 'O22' in f.tail for f,p in active)==2
            samples=[p for f,p in active]+[scene.ownship(t)]
            for a,b in itertools.combinations(samples,2):
                self.assertTrue(abs(a[2]-b[2])>=400 or math.hypot(a[0]-b[0],a[1]-b[1])>=.35)
            own=scene.ownship(t);self.assertAlmostEqual(math.hypot(*own[:2]),5);self.assertEqual(own[2],5000)
        self.assertEqual(kinds,{'C172','airliner','GA','helicopter'});self.assertTrue(both)
        self.assertEqual(Scenario(seed=22).messages(600),Scenario(seed=22).messages(600))

    def test_demo_messages_use_real_database_pipeline(self):
        scene=Scenario();traffic,own=scene.messages(600);now=time.time()
        own['BaroLastMeasurementTime']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(now))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.db';collector.initialize(path)
            with closing(sqlite3.connect(path)) as conn:
                for message in traffic:self.assertTrue(collector.record_traffic(conn,message,now))
                self.assertTrue(collector.record_ownship(conn,own,now))
            snap=read_snapshot(path)
            self.assertEqual(len(snap.reports),len(traffic));self.assertEqual(snap.ownship[0].comparison_alt,5000)

    def test_moving_demo_reaches_display_with_airports(self):
        scene=Scenario();now=time.time();display=gui();display.args.demo=False
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.db';collector.initialize(path)
            with closing(sqlite3.connect(path)) as conn:
                previous=None
                for second in range(10):
                    traffic,own=scene.messages(600+second)
                    stamp=now-9+second
                    for message in traffic:collector.record_traffic(conn,message,stamp)
                    collector.record_ownship(conn,own,stamp)
                    with conn:conn.execute('INSERT OR REPLACE INTO receiver_status VALUES (1,?,?,?)',(stamp,1,'DEMO: simulated traffic'))
                    snap=read_snapshot(path)
                    if previous:
                        common=set(previous.reports)&set(snap.reports)
                        self.assertTrue(any((previous.reports[k][-1].lat,previous.reports[k][-1].lon)!=(snap.reports[k][-1].lat,snap.reports[k][-1].lon) for k in common))
                    previous=snap
            display.snapshot=snap;display.args.range=None;display.airports_visible=False
            display.tick()
            self.assertTrue(display.airports_visible);self.assertEqual(display.radius_nm,20)
            self.assertTrue(any(ident=='KO22' for x,y,ident in display.airport_hits))

    def test_splash_has_readable_title_on_round_canvas(self):
        c=Canvas();draw_splash(c,800,800)
        text=[options['text'] for kind,coords,options in c.commands if kind=='create_text']
        self.assertIn('FISHFINDER',text);self.assertIn('Touch to begin',text)


if __name__=='__main__':unittest.main()
