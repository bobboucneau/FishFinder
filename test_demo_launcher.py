import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).with_name('DemoDisplay.bash').resolve()

class LauncherTests(unittest.TestCase):
    def run_launcher(self,geometry,mapping_ok=True,script=SCRIPT):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);log=root/'calls'
            files={'xrandr':'#!/bin/bash\nprintf "%s\\n" "$TEST_XRANDR"\n',
                   'xinput':'#!/bin/bash\necho "xinput:$*" >> "$TEST_LOG"\n[[ "$1" == "list" ]] && exit 0\nexit "$TEST_MAPPING_STATUS"\n',
                   'python':'#!/bin/bash\necho "python:$*" >> "$TEST_LOG"\n'}
            for name,text in files.items():
                p=root/name;p.write_text(text);p.chmod(0o755)
            env=dict(os.environ,PATH=f'{root}:/usr/bin:/bin',TEST_XRANDR=geometry,TEST_LOG=str(log),TEST_MAPPING_STATUS='0' if mapping_ok else '1',FISHFINDER_PYTHON=str(root/'python'))
            result=subprocess.run(['bash',str(script),'--touch-debug'],env=env,capture_output=True,text=True)
            return result,log.read_text() if log.exists() else ''
    def test_single_and_dual_monitor_geometry(self):
        for offset in ('+0+0','+1920+0','-800+0'):
            with self.subTest(offset=offset):
                result,log=self.run_launcher(f'HDMI-1 disconnected\nDSI-1 connected primary 800x800{offset} (normal left inverted right)')
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('xinput:map-to-output pointer:10-0014 Goodix Capacitive TouchScreen DSI-1',log)
                self.assertIn(f'--geometry 800x800{offset} --fullscreen --touch-debug',log)
                self.assertLess(log.index('xinput:'),log.index('python:'))
    def test_production_display_mapping_and_database(self):
        result,log=self.run_launcher('DSI-1 connected 800x800+0+0',script=SCRIPT.with_name('Display.bash'))
        self.assertEqual(result.returncode,0,result.stderr)
        command=log.split('python:',1)[1]
        self.assertIn('/var/local/FishFinder/flying_objects.db',command)
        self.assertNotIn('--demo',command)
        self.assertIn('--geometry 800x800+0+0',command)

    def test_failure_stops_before_display(self):
        result,log=self.run_launcher('DSI-1 connected 800x800+0+0',False)
        self.assertNotEqual(result.returncode,0);self.assertNotIn('python:',log)
        result,log=self.run_launcher('DSI-1 disconnected')
        self.assertNotEqual(result.returncode,0);self.assertNotIn('python:',log)

if __name__=='__main__':unittest.main()
