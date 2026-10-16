import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import demo_ground as g
import traffic_display as d
from build_demo_ground import simplify,build,join_rings
from test_airports import gui

class GroundTests(unittest.TestCase):
    def test_simplification_and_complete_boundaries_only(self):
        self.assertEqual(simplify([[0,0],[.00001,.5],[0,1]]),[[0,0],[0,1]])
        self.assertIsNone(join_rings([[{'lat':0,'lon':0},{'lat':0,'lon':1}]]))
        ring=join_rings([[{'lat':0,'lon':0},{'lat':0,'lon':1},{'lat':1,'lon':1}],[{'lat':0,'lon':0},{'lat':1,'lon':1}]])
        self.assertEqual(len(ring),1);self.assertEqual(ring[0][0],ring[0][-1])
    def test_pack_validation(self):
        bounds,paths,polygons=g.load_pack()
        self.assertTrue(paths);self.assertTrue(polygons)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json';path.write_text(json.dumps({'schema':2,'bounds':bounds,'paths':[{'kind':'road','points':[[float('nan'),0],[38,-120]]}]}))
            with self.assertRaises(ValueError):g.load_pack(path)
    def test_water_fill_holes_mask_and_road_rotation(self):
        origin=(0,0)
        # Large water square containing a centered island.
        square=[[-.1,-.1],[-.1,.1],[.1,.1],[.1,-.1],[-.1,-.1]]
        island=[[-.02,-.02],[-.02,.02],[.02,.02],[.02,-.02],[-.02,-.02]]
        state=(origin,0,10,1,100)
        ppm=g.rasterize([],[(square,island)],state)
        pixels=ppm.split(b'\n',3)[3]
        def rgb(x,y):return tuple(pixels[(y*100+x)*3:(y*100+x+1)*3])
        self.assertEqual(rgb(50,50),g.BG)
        self.assertEqual(rgb(65,50),(10,32,42))
        self.assertEqual(rgb(0,0),g.BG)
        horizontal=[(0,-.5),(0,.5)]
        image=g.rasterize([('road',horizontal)],[],(origin,90,10,1,100)).split(b'\n',3)[3]
        self.assertIn((104,77,33),[tuple(image[(10*100+x)*3:(10*100+x+1)*3]) for x in (49,50)])
    def test_gui_uses_one_cached_image_and_rejects_old_zoom(self):
        obj=gui();origin=(38.03,-120.41);state=(origin,0,10,1,398)
        obj.ground_level=1;obj.ground_image=None;obj.ground_seen=None;obj.ground_request_key=None
        obj.ground=SimpleNamespace(result=(state,b'fake ppm'),poll=lambda:None,request=lambda value:None,error='',bounds=[37,-122,39,-119],covers=lambda *a:True)
        image=SimpleNamespace(zoom=lambda *args:'cached-image')
        obj.canvas.commands=[]
        with patch.object(d.tk,'PhotoImage',return_value=image) as photo:
            obj.draw_ground(origin);obj.draw_ground(origin)
            self.assertEqual(photo.call_count,1)
        self.assertEqual([c[0] for c in obj.canvas.commands],['create_image','create_image'])
        obj.radius_nm=5;obj.canvas.commands=[];obj.draw_ground(origin)
        self.assertEqual(obj.canvas.commands,[])
        obj.snapshot=d.Snapshot({},[]);obj.draw()
        self.assertFalse(any(c[0]=='create_image' for c in obj.canvas.commands))
        obj.stop.set()
    def test_process_failure_does_not_block_display(self):
        layer=g.GroundLayer('/nonexistent/fishfinder-map.json')
        try:
            deadline=time.monotonic()+5
            while not layer.error and time.monotonic()<deadline:layer.poll();time.sleep(.01)
            self.assertTrue(layer.error)
        finally:layer.close()
        self.assertFalse(layer.process.is_alive())
    def test_trails_batch_without_losing_estimated_style(self):
        obj=gui();obj.canvas.commands=[];obj.radius_nm=10;obj.cx=obj.cy=400;obj.map_heading=0;obj.pixels=39.8
        obj.trail_lines([(0,0),(1,0),(2,0),(3,0),(4,0)],d.GREEN,[False,False,True,True])
        lines=obj.canvas.commands
        self.assertEqual(len(lines),2)
        self.assertEqual(lines[0][2]['fill'],d.GREEN)
        self.assertEqual(lines[1][2]['fill'],d.ESTIMATED)
        self.assertIn('dash',lines[1][2])
        # Leaving then re-entering cannot create a chord connecting separated runs.
        obj.canvas.commands=[]
        obj.trail_lines([(0,0),(20,0),(20,20),(0,1)],d.GREEN)
        self.assertEqual(len(obj.canvas.commands),2)
        for _,coords,_ in obj.canvas.commands:
            for i in range(0,len(coords),2):self.assertLessEqual(math.hypot(coords[i]-400,coords[i+1]-400),398.00001)
        obj.stop.set()

if __name__=='__main__':unittest.main()
