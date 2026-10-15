import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from configure_pi import files_for,find_python,verify_unit,SERVICE

ROOT=Path(__file__).resolve().parent

class ServiceTests(unittest.TestCase):
    def environment(self,root,sleep=False):
        python=root/'python';log=root/'calls'
        python.write_text('#!/bin/bash\necho "$*" >> "$TEST_LOG"\n'+('exec /bin/sleep 20\n' if sleep else 'exit 0\n'));python.chmod(0o755)
        flock=root/'flock'
        flock.write_text(f'#!{sys.executable}\nimport fcntl,sys\ntry:fcntl.flock(int(sys.argv[-1]),fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:sys.exit(1)\n');flock.chmod(0o755)
        env=dict(os.environ,PATH=f'{root}:/usr/bin:/bin',TEST_LOG=str(log),FISHFINDER_PYTHON=str(python),FISHFINDER_LOCK_FILE=str(root/'collector.lock'))
        return env,log
    def test_mode_database_and_argument_forwarding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env,log=self.environment(root)
            for script,demo in [('Finder.bash',False),('DemoFinder.bash',True)]:
                result=subprocess.run(['bash',str(ROOT/script),'--log-level','DEBUG'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                args=log.read_text().splitlines()[-1]
                self.assertIn('-u ',args);self.assertIn('--log-level DEBUG',args)
                self.assertEqual('--demo ' in args,demo)
                self.assertIn('/var/local/FishFinder/'+('demo_objects.db' if demo else 'flying_objects.db'),args)
                for forbidden in ['--demo','--db=/tmp/unsafe.db']:
                    result=subprocess.run(['bash',str(ROOT/script),forbidden],env=env,capture_output=True,text=True)
                    self.assertEqual(result.returncode,2)
    def test_shared_lock_blocks_second_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env,log=self.environment(root,True)
            first=subprocess.Popen(['bash',str(ROOT/'Finder.bash')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                deadline=time.monotonic()+3
                while not log.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(log.exists())
                second=subprocess.run(['bash',str(ROOT/'DemoFinder.bash')],env=env,capture_output=True,text=True,timeout=3)
                self.assertEqual(second.returncode,75,second.stderr)
                self.assertIn('already holds',second.stderr)
            finally:
                os.killpg(first.pid,signal.SIGTERM);first.communicate(timeout=3)
            # Exiting releases the lock without deleting its file.
            env,log=self.environment(root)
            result=subprocess.run(['bash',str(ROOT/'DemoFinder.bash')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_single_service_mode_switch_and_venv_detection(self):
        app=Path('/usr/local/FishFinder/FishFinder-v0.4.11');python=app.parent/'.venv/bin/python3';home=Path('/home/pilot')
        for demo in [True,False]:
            db=Path('/var/local/FishFinder')/('demo_objects.db' if demo else 'flying_objects.db')
            files=files_for('pilot',home,app,db,demo,False,python)
            self.assertEqual(list(files),[Path('/etc/systemd/system')/SERVICE])
            unit=next(iter(files.values()))
            self.assertIn('DemoFinder.bash' if demo else '/Finder.bash',unit)
            self.assertIn(f'FISHFINDER_PYTHON={python}',unit)
            self.assertIn('User=pilot',unit);self.assertIn('RestartPreventExitStatus=75',unit)
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)/'version';app.mkdir();venv=app.parent/'.venv/bin/python3';venv.parent.mkdir(parents=True);venv.write_text('');venv.chmod(0o755)
            self.assertEqual(find_python(app),venv)
    def test_working_directory_is_literal_and_verifier_is_required(self):
        app=Path('/usr/local/FishFinder/version with space')
        unit=next(iter(files_for('pilot',Path('/home/pilot'),app,Path('/var/local/FishFinder/demo_objects.db'),True).values()))
        directory=next(line.split('=',1)[1] for line in unit.splitlines() if line.startswith('WorkingDirectory='))
        self.assertEqual(directory,str(app));self.assertTrue(directory.startswith('/'))
        with self.assertRaises(ValueError):files_for('pilot',Path('/home/pilot'),Path('/bad\npath'),Path('/var/local/FishFinder/demo_objects.db'))
        def inspect(command,**kwargs):
            self.assertEqual(command[:2],['/usr/bin/systemd-analyze','verify'])
            self.assertEqual(Path(command[2]).name,SERVICE)
            self.assertEqual(Path(command[2]).read_text(),unit)
            return subprocess.CompletedProcess(command,0,'','')
        with patch('configure_pi.subprocess.run',side_effect=inspect):verify_unit(unit,'/usr/bin/systemd-analyze')
        with patch('configure_pi.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','bad unit')):
            with self.assertRaisesRegex(ValueError,'bad unit'):verify_unit(unit,'/usr/bin/systemd-analyze')

    def test_live_display_uses_live_database(self):
        text=(ROOT/'Display.bash').read_text()
        self.assertIn('xinput map-to-output',text);self.assertIn('/flying_objects.db',text)
        self.assertNotIn('--demo',text)

if __name__=='__main__':unittest.main()
