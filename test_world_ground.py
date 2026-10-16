import json
import sqlite3
import tempfile
import time
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import demo_ground as ground
from world_ground import APPLICATION_ID,WorldMap,decode

class WorldTests(unittest.TestCase):
    def fixture(self,path):
        conn=sqlite3.connect(path)
        conn.executescript(f'PRAGMA application_id={APPLICATION_ID}; CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); INSERT INTO metadata VALUES("schema","1"); CREATE TABLE features(id INTEGER PRIMARY KEY,kind TEXT,geometry BLOB); CREATE VIRTUAL TABLE bounds USING rtree(id,west,east,south,north);')
        for ident,(west,east) in enumerate([(179.8,180),(-180,-179.8),(0,.1)],1):
            points=[[0,west],[0,east]]
            conn.execute('INSERT INTO features VALUES(?,?,?)',(ident,'road',zlib.compress(json.dumps(points).encode())))
            conn.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(ident,west,east,0,0))
        conn.commit();conn.close()
    def test_index_query_local_dateline_pole_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'map.sqlite';self.fixture(path)
            world=WorldMap(path)
            try:
                self.assertEqual(len(world.query((0,179.95),20)[0]),2)
                self.assertEqual(len(world.query((0,-179.95),20)[0]),2)
                self.assertEqual(len(world.query((0,0),20)[0]),1)
                self.assertEqual(world.query((89.99,179),20),([],[]))
                with self.assertRaises(sqlite3.OperationalError):world.conn.execute('DELETE FROM features')
                with self.assertRaises(ValueError):world.query((float('nan'),0),10)
            finally:world.close()
    def test_reject_wrong_schema_and_decompression_bomb(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.sqlite';sqlite3.connect(path).close()
            with self.assertRaises(ValueError):WorldMap(path)
        with self.assertRaises(ValueError):decode(zlib.compress(b'0'*8_000_001))
        with self.assertRaises(ValueError):decode(b'broken')
    def test_world_default_local_override_and_saved_off_preference(self):
        import traffic_display as display
        import settings
        from test_airports import Canvas,Root
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'world.sqlite';self.fixture(path)
            args=SimpleNamespace(fullscreen=False,geometry='800x800',demo=True,no_ownship=False,range=10,airports='airports.json',demo_map=False,map_data=None)
            for local,saved,expected_global,expected_level in [(False,False,True,0),(True,False,False,1),(False,True,True,0)]:
                args.demo_map=local;args.map_data=path if saved else None
                config=dict(settings.DEFAULTS);config['ground_map']=False
                with patch.object(display.tk,'Canvas',Canvas),patch('world_ground.DEFAULT_PATH',path),patch.object(settings,'load',return_value=config),patch.object(settings,'explicit',return_value=saved):
                    obj=display.Display(Root(),args)
                self.assertEqual(obj.ground_global,expected_global)
                self.assertEqual(obj.ground_level,expected_level)
                obj.stop.set()

    def test_world_worker_renders_without_gui_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'map.sqlite';self.fixture(path)
            layer=ground.GroundLayer(path)
            try:
                layer.request(((0,179.95),90,20,1,100))
                deadline=time.monotonic()+5
                while not layer.result and not layer.error and time.monotonic()<deadline:
                    layer.poll();time.sleep(.01)
                self.assertFalse(layer.error)
                self.assertIsNotNone(layer.result)
                self.assertTrue(layer.result[1].startswith(b'P6'))
                self.assertTrue(layer.covers((0,179.95),20))
            finally:layer.close()

    def test_three_feature_styles_are_distinct_and_rail_is_dashed(self):
        state=((0,0),0,10,1,100)
        colors=[]
        for kind in ['road','rail','river']:
            pixels=ground.rasterize([(kind,[(0,-.1),(0,.1)])],[],state).split(b'\n',3)[3]
            values=[tuple(pixels[i:i+3]) for i in range(0,len(pixels),3)]
            colored=[p for p in values if p!=ground.BG]
            self.assertTrue(colored);colors.append(set(colored))
            if kind=='rail':rail_count=len(colored)
            if kind=='road':road_count=len(colored)
        self.assertEqual(len(set(tuple(sorted(c)) for c in colors)),3)
        self.assertLess(rail_count,road_count)

if __name__=='__main__':unittest.main()
