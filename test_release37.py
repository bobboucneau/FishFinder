"""Focused behavior checks for the Nov 4 usability changes.

No test sends a shutdown request or changes an installed database/settings file.
The Canvas records shapes and labels so navigation can be tested without a flight.
"""
import copy
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import airport_reference
import settings
import traffic_display
from test_airports import gui, Canvas, Root


class Tests(unittest.TestCase):
    def make(self):
        display=gui()
        self.addCleanup(display.stop.set)
        return display

    def labels(self, display):
        return [kw.get('text','') for _,_,kw in display.canvas.commands]

    def test_notice_requires_deliberate_acknowledgement_each_start(self):
        # main() always supplies this flag; constructing Display alone does not
        # start a real GUI/network session in tests.
        args=SimpleNamespace(fullscreen=False,geometry='800x800',demo=True,
                             no_ownship=False,range=10,airports='airports.json',
                             startup_notice=True)
        for _ in range(2):
            with patch.object(traffic_display.tk,'Canvas',Canvas):
                d=traffic_display.Display(Root(),args)
            self.addCleanup(d.stop.set)
            self.assertTrue(d.notice_pending)
            self.assertIn('FLIGHT SAFETY NOTICE',self.labels(d))
            self.assertEqual(d.hits,[])
            d.single_tap(SimpleNamespace(x=400,y=340))
            self.assertTrue(d.notice_pending)
            with patch.object(settings,'save') as save:
                d.tap(SimpleNamespace(x=400,y=626))
                self.assertFalse(d.notice_pending)
                save.assert_not_called()
            self.assertIn('Airport',self.labels(d))

    def test_notice_power_cancel_preserves_notice(self):
        d=self.make();d.notice_pending=True
        d.request_poweroff()
        self.assertTrue(d.exit_pending)
        self.assertIn('Shut down FishFinder?',self.labels(d))
        d.single_tap(SimpleNamespace(x=318,y=460))
        self.assertFalse(d.exit_pending)
        self.assertTrue(d.notice_pending)

    def test_radios_returns_directly_to_same_airport(self):
        d=self.make();d.choose_airport('KCPU',remember=False)
        d.airport_action('view')
        self.assertTrue(d.airport_runways)
        self.assertIn('Back to airport',self.labels(d))
        action=next(action for *_,action in d.airport_buttons if action=='view')
        d.airport_action(action)
        self.assertEqual(d.airport_selected,'KCPU')
        self.assertFalse(d.airport_runways)
        self.assertIn('Radios / data',self.labels(d))

    def test_custom_fallback_is_msl_and_never_overrides_published(self):
        from datetime import datetime, timezone, timedelta
        d=self.make();a=copy.deepcopy(d.catalog.airports['KCPU'])
        today=datetime.now(timezone.utc).date()
        a['reference'].update(effective=today.isoformat(),
                              expires=(today+timedelta(days=28)).isoformat(),
                              pattern_msl_ft=None,pattern_remarks=[])
        runway=a['runways'][0]
        self.assertEqual(airport_reference.pattern_altitude(a,runway,1500)[0],2828)
        a['reference']['pattern_msl_ft']=2400
        self.assertEqual(airport_reference.pattern_altitude(a,runway,1500)[0],2400)
        self.assertEqual(settings.validate({})['pattern_height_agl'],1000)
        self.assertEqual(settings.validate({'pattern_height_agl':'1500'})['pattern_height_agl'],1500)
        for value in (True,499,3001,1000.5):
            with self.assertRaises(ValueError):settings.validate({'pattern_height_agl':value})

    def test_main_power_centered_and_map_button_removed(self):
        d=self.make();d.last_touch=time.monotonic();d.draw()
        self.assertFalse(any(label.startswith('Map ') for label in self.labels(d)))
        bounds=next(box[:4] for box in d.buttons if box[4].__name__=='request_poweroff')
        self.assertEqual((bounds[0]+bounds[2])/2,400)
        self.assertGreater(bounds[1],211)
