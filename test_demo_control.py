"""Mode requests and non-O22 scenarios, without a real receiver or live database."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from demo_control import airport_spec,request
from demo_traffic import Scenario
from bootstrap import Launcher

AIRPORTS=Path(__file__).with_name('airports.json')
class DemoControlTests(unittest.TestCase):
    def test_airport_alias_and_bad_selection(self):
        a,spec=airport_spec(AIRPORTS,'O22')
        self.assertEqual(a['code'],'O22')
        with self.assertRaises(ValueError):airport_spec(AIRPORTS,'ZZZZZZZ')
    def test_custom_airport_moves_and_uses_elevation(self):
        scenario=Scenario(AIRPORTS,airport='KCPU')
        self.assertEqual(len(scenario.specs),1)
        self.assertNotEqual(scenario.ownship(0),scenario.ownship(20))
        self.assertEqual(scenario.ownship(0)[2],float(scenario.home['elevation_ft'])+2900)
        messages,own=scenario.messages(600)
        self.assertTrue(messages)
        self.assertLess(abs(own['GPSLatitude']-scenario.home['lat']),.1)
    def test_atomic_request(self):
        with tempfile.TemporaryDirectory() as folder:
            request(folder,'demo','KCPU')
            self.assertEqual(json.loads((Path(folder)/'runtime/mode-request.json').read_text()),{'mode':'demo','airport':'KCPU'})
    def test_switch_preserves_live_database(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);(home/'shared').mkdir()
            (home/'shared/airports.json').symlink_to(AIRPORTS.resolve())
            live=home/'flying_objects.db';live.write_bytes(b'live untouched')
            demo=home/'demo_objects.db';demo.write_bytes(b'old synthetic history')
            launcher=Launcher.__new__(Launcher)
            launcher.store=Mock(home=home);launcher.database_dir=home
            launcher.args=Mock();launcher.progress=Mock();launcher.root=Mock()
            launcher.stop_children=Mock();launcher.launch=Mock()
            launcher.switch_mode({'mode':'demo','airport':'KCPU'})
            self.assertEqual(live.read_bytes(),b'live untouched')
            self.assertFalse(demo.exists())
            self.assertTrue(launcher.args.demo)
            launcher.switch_mode({'mode':'live','airport':'KCPU'})
            self.assertEqual(launcher.args.database,str(live))
            self.assertFalse(launcher.args.demo)
    def test_invalid_request_does_not_stop_children(self):
        launcher=Launcher.__new__(Launcher);launcher.stop_children=Mock()
        with self.assertRaises(ValueError):launcher.switch_mode({'mode':'unexpected'})
        launcher.stop_children.assert_not_called()
if __name__=='__main__':unittest.main()
