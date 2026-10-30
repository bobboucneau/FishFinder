"""Airport entry/navigation tests use offline data and mocked preference writes."""
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch
import airport_selection as a
import airport_data
import settings
from test_airports import gui

class Tests(unittest.TestCase):
    def test_lookup_local_code_and_full_identifier(self):
        catalog=SimpleNamespace(airports={'KO22':{'ident':'KO22','code':'O22'},'KGOO':{'ident':'KGOO','code':'KGOO'}})
        self.assertEqual(a.lookup(catalog,' o22 ')['ident'],'KO22')
        self.assertEqual(a.lookup(catalog,'KGOO')['ident'],'KGOO')
        for value in ('','NOFOUND','O22/','ABCDEFGH','Ｏ２２'):
            with self.assertRaises(ValueError):a.lookup(catalog,value)

    def test_ambiguous_alias_is_not_guessed(self):
        catalog=SimpleNamespace(airports={'A':{'code':'XYZ'},'B':{'code':'XYZ'}})
        with self.assertRaisesRegex(ValueError,'More than one'):a.lookup(catalog,'XYZ')

    def test_distance_and_cardinal_true_bearings(self):
        for destination,bearing in (((1,0),0),((0,1),90),((-1,0),180),((0,-1),270)):
            distance,actual=a.distance_bearing((0,0),destination)
            self.assertAlmostEqual(distance,60.04,places=1);self.assertAlmostEqual(actual,bearing)
        distance,bearing=a.distance_bearing((0,179.5),(0,-179.5))
        self.assertAlmostEqual(distance,60.04,places=1);self.assertEqual(bearing,90)

    def test_missing_stale_and_coincident_position(self):
        airport={'lat':0,'lon':0};fix=SimpleNamespace(time=100,lat=0,lon=0)
        self.assertIn('unavailable',a.navigation_text(None,airport,100))
        self.assertIn('unavailable',a.navigation_text(fix,airport,116))
        self.assertIn('unavailable',a.navigation_text(fix,airport,99))
        self.assertEqual(a.navigation_text(fix,airport,101),'At airport · 0.0 NM')
        self.assertEqual(a.navigation_text(fix,{'lat':0,'lon':1},101),'090° TRUE · 60.0 NM')

    def test_manual_selection_preserves_ownship_and_map(self):
        display=gui();self.addCleanup(display.stop.set)
        snapshot=display.snapshot;center=display.last_own;radius=display.radius_nm
        with patch.object(settings,'save',side_effect=lambda values:dict(values)):
            display.choose_airport('KO22')
        self.assertEqual(display.config['manual_airport'],'KO22')
        self.assertEqual(display.airport_selected,'KO22')
        self.assertIs(display.snapshot,snapshot);self.assertEqual(display.last_own,center)
        self.assertEqual(display.radius_nm,radius)
        display.airport_action('close')
        self.assertIsNone(display.airport_selected);self.assertEqual(display.config['manual_airport'],'KO22')
        with patch.object(settings,'save',side_effect=lambda values:dict(values)):
            display.choose_airport('KCPU',remember=False)
        self.assertEqual(display.config['manual_airport'],'')
        self.assertEqual(display.airport_selected,'KCPU')

    def test_restored_selection_and_shared_navigation_line(self):
        with patch.object(settings,'load',return_value=dict(settings.DEFAULTS,manual_airport='KO22')):
            display=gui()
        self.addCleanup(display.stop.set)
        self.assertEqual(display.airport_selected,'KO22')
        labels=[kw.get('text','') for _,_,kw in display.canvas.commands]
        self.assertTrue(any('TRUE' in label and 'NM' in label for label in labels))
        self.assertIn('Select airport',labels)
        display.airport_fix=None;display.canvas.commands=[];display.airport_details()
        self.assertIn('Ownship position unavailable',[kw.get('text') for _,_,kw in display.canvas.commands])

    def test_invalid_saved_selection_is_rejected(self):
        for code in ('ABC/DEF','é','x'*33):
            with self.assertRaises(ValueError):settings.validate({'manual_airport':code})
        self.assertEqual(settings.validate({'manual_airport':' ko22 '})['manual_airport'],'KO22')

if __name__=='__main__':unittest.main()
