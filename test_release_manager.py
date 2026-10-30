"""Updater tests use tiny temporary releases and temporary signing keys only."""
import base64
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import release_manager as r
import release_tools as tools
import configure_bootstrap as installer

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.store=r.Store(self.base/'device')
        self.key=Ed25519PrivateKey.generate()
        public=self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        (self.store.home/'trusted-keys/publisher.pem').write_bytes(public)

    def package(self,identifier='one',sequence=1,extra=None):
        archive=self.base/(identifier+'.zip');manifest=self.base/(identifier+'.manifest.json');signature=self.base/(identifier+'.sig')
        files={'FishFinder.py':b'print("collector")','traffic_display.py':b'print("display")','settings.py':b'# settings','airports.json':b'{}'}
        version={'version':identifier,'files':{name:hashlib.sha256(value).hexdigest() for name,value in files.items()}}
        with zipfile.ZipFile(archive,'w') as z:
            for name,value in files.items():z.writestr('package/'+name,value)
            z.writestr('package/VERSION.json',json.dumps(version))
            if extra:extra(z)
        tools.make_manifest(archive,identifier,sequence,manifest,platform='any')
        signature.write_bytes(base64.b64encode(self.key.sign(manifest.read_bytes())))
        return archive,manifest,signature

    def test_signed_stage_does_not_activate(self):
        pending=self.store.stage(*self.package())
        self.assertFalse(pending['owner_build']);self.assertIsNone(self.store.state()['current'])
        self.assertEqual(r.read(self.store.pending_path,{})['policy'],'ask')

    def test_unsigned_requires_explicit_owner_mode(self):
        archive,manifest,signature=self.package()
        with self.assertRaises(ValueError):self.store.stage(archive,manifest)
        pending=self.store.stage(archive,manifest,owner=True)
        self.assertTrue(pending['owner_build'])

    def test_tampered_archive_rejected(self):
        archive,manifest,signature=self.package();archive.write_bytes(archive.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'checksum/size'):self.store.stage(archive,manifest,signature)
        self.assertEqual(list((self.store.home/'releases').iterdir()),[])

    def test_tampered_manifest_and_wrong_key_rejected(self):
        archive,manifest,signature=self.package();data=json.loads(manifest.read_text());data['sequence']=2;r.atomic(manifest,data)
        with self.assertRaisesRegex(ValueError,'signing key'):self.store.stage(archive,manifest,signature)
        signature.write_bytes(base64.b64encode(Ed25519PrivateKey.generate().sign(manifest.read_bytes())))
        with self.assertRaisesRegex(ValueError,'signing key'):self.store.stage(archive,manifest,signature)

    def test_activation_accept_and_replay(self):
        self.store.stage(*self.package());self.store.activate();self.assertIsNotNone(self.store.state()['trial'])
        self.store.accept();self.assertEqual(self.store.state()['high_watermark'],1)
        with self.assertRaisesRegex(ValueError,'not newer'):self.store.stage(*self.package('replayed',1))

    def test_trial_rollback_preserves_old_release(self):
        self.store.stage(*self.package());self.store.activate();self.store.accept()
        self.store.stage(*self.package('two',2));self.store.activate()
        self.assertEqual(self.store.state()['previous'],'one')
        self.store.rollback();self.assertEqual(self.store.state()['current'],'one')
        self.assertTrue(self.store.release('two').is_dir())
        self.assertEqual(self.store.state()['high_watermark'],1)

    def test_pending_policy_and_shared_data_survive(self):
        shared=self.store.home/'shared/settings.json';shared.write_text('{"keep": true}')
        self.store.stage(*self.package());self.store.defer('next-start')
        self.assertEqual(r.read(self.store.pending_path,{})['policy'],'next-start')
        self.store.activate();self.store.accept()
        self.assertEqual(shared.read_text(),'{"keep": true}')

    def test_archive_traversal_rejected_even_for_owner(self):
        archive,manifest,sig=self.package(extra=lambda z:z.writestr('package/../../outside',b'bad'))
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.store.stage(archive,manifest,owner=True)
        self.assertFalse((self.base/'outside').exists())

    def test_symlinks_rejected(self):
        def symlink(z):
            entry=zipfile.ZipInfo('package/link');entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(entry,'/etc/passwd')
        with self.assertRaisesRegex(ValueError,'Links'):self.store.stage(*self.package(extra=symlink))

    def test_size_and_space_limits(self):
        package=self.package()
        with patch('release_manager.MAX_UNPACKED',1):
            with self.assertRaisesRegex(ValueError,'Unpacked'):self.store.stage(*package)
        with patch('release_manager.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
            with self.assertRaisesRegex(ValueError,'disk space'):self.store.stage(*package)

    def test_api_and_release_id_validation(self):
        archive,manifest,sig=self.package();data=json.loads(manifest.read_text());data['bootstrap_api']=2;r.atomic(manifest,data)
        with self.assertRaisesRegex(ValueError,'bootstrap API'):self.store.stage(archive,manifest,owner=True)
        for identifier in ('../outside','a/b','/root',''):
            with self.assertRaises(ValueError):self.store.release(identifier)

    def test_internal_hash_validation(self):
        def change(z):z.writestr('package/extra.txt',b'allowed extra file')
        package=self.package(extra=change)
        # Corrupt an internal hash, then make a new matching external manifest.
        archive,manifest,sig=package
        with zipfile.ZipFile(archive) as z:members={n:z.read(n) for n in z.namelist()}
        version=json.loads(members['package/VERSION.json']);version['files']['FishFinder.py']='0'*64
        members['package/VERSION.json']=json.dumps(version).encode()
        with zipfile.ZipFile(archive,'w') as z:
            for n,b in members.items():z.writestr(n,b)
        tools.make_manifest(archive,'one',1,manifest,platform='any')
        with self.assertRaisesRegex(ValueError,'Internal file'):self.store.stage(archive,manifest,owner=True)

    def test_one_time_service_uses_stable_nonroot_path(self):
        unit,script=installer.files_for('fish',Path('/home/fish'),Path('/home/fish/runtime/bin/python3'),Path('/var/local/FishFinder/demo_objects.db'),True)
        self.assertIn('User=fish',unit)
        self.assertIn('bootstrap/xsession.bash',unit)
        self.assertNotIn('FishFinder-v0.',unit)
        self.assertIn('--demo',script)
        self.assertIn('--home',script)
        self.assertIn('exec ',script)

    def test_boot_recovers_interrupted_trial(self):
        import bootstrap
        self.store.stage(*self.package());self.store.activate();self.store.accept()
        self.store.stage(*self.package('two',2));self.store.activate()
        launcher=bootstrap.Launcher.__new__(bootstrap.Launcher);launcher.store=self.store
        calls=[];launcher.launch=lambda:calls.append('launched');launcher.problem=lambda text:self.fail(text)
        launcher.startup()
        self.assertEqual(self.store.state()['current'],'one');self.assertEqual(calls,['launched'])

    def test_preapproved_next_start_activates(self):
        import bootstrap
        self.store.stage(*self.package());self.store.activate();self.store.accept()
        self.store.stage(*self.package('two',2));self.store.defer('next-start')
        launcher=bootstrap.Launcher.__new__(bootstrap.Launcher);launcher.store=self.store
        launcher.launch=lambda:None;launcher.problem=lambda text:self.fail(text)
        launcher.startup()
        self.assertEqual(self.store.state()['current'],'two')
        self.assertIsNotNone(self.store.state()['trial'])

    def test_healthy_heartbeat_accepts_trial(self):
        import bootstrap
        from types import SimpleNamespace
        self.store.stage(*self.package());self.store.activate()
        r.atomic(self.store.home/'runtime/display-heartbeat.json',dict(release='one',monotonic=100))
        launcher=bootstrap.Launcher.__new__(bootstrap.Launcher)
        launcher.store=self.store;launcher.quitting=False;launcher.prompted=None;launcher.prompt=None
        launcher.display=SimpleNamespace(poll=lambda:None);launcher.collector=SimpleNamespace(poll=lambda:None)
        launcher.started=50;launcher.ready_since=80
        launcher.root=SimpleNamespace(withdraw=lambda:None,after=lambda *a:None)
        launcher.problem=lambda text:self.fail(text)
        with patch('bootstrap.time.monotonic',return_value=100):launcher.poll()
        self.assertIsNone(self.store.state()['trial']);self.assertEqual(self.store.state()['high_watermark'],1)

    def test_owner_builder_does_not_sweep_private_files(self):
        import build_release
        archive,_,_=self.package()
        with zipfile.ZipFile(archive) as z:z.extractall(self.base/'source')
        source=self.base/'source/package';(source/'settings.json').write_text('{"private":true}')
        built,manifest=build_release.build(source,'owner-copy',1,self.base/'out')
        with zipfile.ZipFile(built) as z:self.assertFalse(any(name.endswith('/settings.json') for name in z.namelist()))
        with self.assertRaisesRegex(ValueError,'private'):build_release.build(source,'bad',1,self.base/'out',['settings.json'])

    def test_venv_symlink_path_is_preserved(self):
        import os
        link=self.base/'venv/bin/python3';link.parent.mkdir(parents=True)
        link.symlink_to('/usr/bin/python3')
        _,script=installer.files_for('fish',Path('/home/fish'),Path(os.path.abspath(link)),Path('/var/local/FishFinder/demo_objects.db'),True)
        self.assertIn(str(link),script)
        self.assertNotIn('exec /usr/bin/python3 ',script)
        # Check the installer entry point uses the same non-resolving conversion.
        self.assertNotIn('args.python.resolve()',Path(installer.__file__).read_text())

if __name__=='__main__':unittest.main()
