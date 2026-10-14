import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import demo_ground
import traffic_display as d
from build_demo_ground import simplify,build
from test_airports import gui

class GroundTests(unittest.TestCase):
    def test_simplification_and_relation_boundaries(self):
        self.assertEqual(simplify([[0,0],[.00001,.5],[0,1]]),[[0,0],[0,1]])
        data=build({'elements':[{'type':'way','tags':{'highway':'primary'},'geometry':[{'lat':38,'lon':-120},{'lat':38.1,'lon':-120}]},{'type':'relation','members':[{'type':'way','role':'inner','geometry':[{'lat':38,'lon':-120},{'lat':38,'lon':-120.1}]}]}]})
        self.assertEqual([p['kind'] for p in data['paths']],['road','water'])
    def test_pack_validation_and_missing_file(self):
        bounds,paths=demo_ground.load_pack()
        self.assertTrue(paths)
        self.assertLess(sum(len(p) for _,p in paths),30000)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json';path.write_text(json.dumps({'schema':1,'bounds':bounds,'paths':[{'kind':'road','points':[[float('nan'),0],[38,-120]]}]}))
            with self.assertRaises(ValueError):demo_ground.load_pack(path)
    def test_clipping_rotation_and_live_gating(self):
        obj=gui();obj.ground_level=1
        origin=(38.03,-120.41)
        obj.ground=SimpleNamespace(result=(origin,(('road',((-30,0),(30,0))),)),request=lambda value:None,error='',bounds=[37,-122,39,-119],covers=lambda *a:True)
        obj.ground_request_time=0;obj.map_heading=90;obj.cx=obj.cy=400;obj.unit=1;obj.radius_nm=10;obj.pixels=39.8
        obj.canvas.commands=[];obj.draw_ground(origin)
        lines=[c for c in obj.canvas.commands if c[0]=='create_line']
        self.assertEqual(len(lines),1)
        coords=lines[0][1]
        self.assertAlmostEqual(coords[0],400);self.assertAlmostEqual(coords[2],400)
        self.assertTrue(all(math.hypot(coords[i]-400,coords[i+1]-400)<=398.0001 for i in (0,2)))
        obj.snapshot=d.Snapshot({},[]);obj.draw()
        self.assertFalse(any(c[2].get('fill')=='#273332' for c in obj.canvas.commands))
        obj.stop.set()
