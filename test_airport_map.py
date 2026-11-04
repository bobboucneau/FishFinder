"""Airport map is a temporary viewing origin, never a substitute ownship position."""
import copy
import math
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_airports import gui
import airport_map
import traffic_display as td


class Tests(unittest.TestCase):
    def make(self):
        d=gui();self.addCleanup(d.stop.set)
        d.ground_level=0
        a=d.catalog.airports['KO22'];now=time.time()
        own=[td.Point(1,now-2,a['lat']+.029,a['lon'],100,5000),
             td.Point(2,now,a['lat']+.03,a['lon'],100,5000)]
        traffic=[td.Point(3,now-2,a['lat']+.039,a['lon']+.02,120,5200),
                 td.Point(4,now,a['lat']+.04,a['lon']+.02,120,5200)]
        d.snapshot=td.Snapshot({'test':traffic},own,demo=True)
        d.draw()
        return d

    def test_view_center_and_back_restore_without_mutating_ownship_or_preferences(self):
        d=self.make();before=copy.deepcopy(d.snapshot)
        config=copy.deepcopy(d.config)
        oldrange=d.radius_nm;anchor=d.anchor;last=d.last_own
        d.airport_selected='KO22';d.airport_runways=False;d.airport_page=0
        d.show_airport_map()
        a=d.catalog.airports['KO22']
        self.assertEqual(d.airport_origin,(a['lat'],a['lon']))
        self.assertEqual(d.map_heading,0)
        self.assertEqual(d.snapshot,before);self.assertEqual(d.config,config)
        self.assertEqual(d.anchor,anchor);self.assertEqual(d.last_own,last)
        self.assertEqual(d.airport_map,'KO22')
        d.set_range(2)
        self.assertFalse(d.idle)
        d.close_airport_map()
        self.assertIsNone(d.airport_map)
        self.assertEqual(d.airport_selected,'KO22')
        self.assertEqual(d.radius_nm,oldrange)

    def test_ownship_is_offset_from_airport_and_link_is_present(self):
        d=self.make();d.airport_selected='KO22';d.show_airport_map()
        x,y,key=next(hit for hit in d.hits if hit[2]=='__ownship__')
        self.assertNotEqual((x,y),(d.cx,d.cy))
        self.assertTrue(any(kw.get('tags')=='airport-ownship-link' for _,_,kw in d.canvas.commands))
        self.assertEqual(len(d.buttons),5)  # four ranges and Back
        self.assertIn('Back to airport',[kw.get('text') for _,_,kw in d.canvas.commands])

    def test_no_or_stale_position_omits_line(self):
        for stale in (False,True):
            d=self.make()
            if stale:
                d.snapshot.ownship=[td.Point(1,time.time()-60,0,0,100,5000)]
            else:d.snapshot.ownship=[]
            d.airport_selected='KO22';d.show_airport_map()
            self.assertFalse(any(kw.get('tags')=='airport-ownship-link' for _,_,kw in d.canvas.commands))
            self.assertIn('Ownship position unavailable',[kw.get('text') for _,_,kw in d.canvas.commands])

    def test_threat_assessment_remains_relative_to_real_ownship(self):
        d=self.make()
        with patch('traffic_display.assess',wraps=td.assess) as assess:
            d.draw();normal=assess.call_args.args[0]
        d.airport_selected='KO22'
        with patch('traffic_display.assess',wraps=td.assess) as assess:
            d.show_airport_map();centered=assess.call_args.args[0]
        self.assertEqual(centered,normal)

    def test_far_link_reaches_edge_in_true_bearing_direction(self):
        for point,expected in ((SimpleNamespace(lat=1,lon=0),(0,10)),
                               (SimpleNamespace(lat=0,lon=1),(10,0))):
            result=airport_map.link_vector((0,0),point,10)
            self.assertAlmostEqual(math.hypot(*result),10)
            self.assertAlmostEqual(result[0],expected[0])
            self.assertAlmostEqual(result[1],expected[1])
