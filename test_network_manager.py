"""Deterministic policy tests. No network changes, credentials or real HTTP calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest
import network_manager as n

AP=n.AccessPoint('AA:BB:CC:DD:EE:01','stratux',75,'','wlan0')
OTHER=n.AccessPoint('AA:BB:CC:DD:EE:02','stratux',80,'','wlan0')
CAP=dict(stratux_ip='192.168.10.1',internet=True,updates=True)

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.profiles=n.Profiles(Path(self.temp.name)/'networks.json')

    def test_escaped_bssid_and_ssid(self):
        self.assertEqual(n.fields(r'AA\:BB\:CC:Bob\:Home:a\\b'),['AA:BB:CC','Bob:Home','a\\b'])

    def test_friendly_name_validation(self):
        self.assertEqual(n.friendly_name("  Bob's   Stratux "),"Bob's Stratux")
        for value in ('',' '*4,'x'*41):
            with self.assertRaises(ValueError):n.friendly_name(value)

    def test_replacement_requires_explicit_choice_preserves_preference(self):
        self.profiles.save(AP,'uuid1',"Bob's Stratux",CAP,True)
        before=self.profiles.path.read_text()
        with self.assertRaises(ValueError):self.profiles.save(OTHER,'uuid2'," bob's   STRATUX ",CAP)
        self.assertEqual(before,self.profiles.path.read_text())
        self.profiles.save(OTHER,'uuid2',"Bob's Stratux",CAP,replace=True)
        self.assertEqual(self.profiles.data['preferred'],OTHER.bssid)
        self.assertEqual(len(self.profiles.data['networks']),1)
        self.assertNotIn('password',self.profiles.path.read_text())

    def test_choose_another_name_keeps_both(self):
        self.profiles.save(AP,'a','Plane one',CAP,True)
        self.profiles.save(OTHER,'b','Plane two',CAP)
        self.assertEqual(len(self.profiles.data['networks']),2)
        self.assertEqual(self.profiles.data['preferred'],AP.bssid)

    def test_selection_and_ambiguous_ssids(self):
        self.assertEqual(n.selection(self.profiles,[AP,OTHER]),('choose',None))
        self.profiles.save(AP,'a','Bob',CAP,True)
        self.assertEqual(n.selection(self.profiles,[AP,OTHER]),('preferred',AP))
        self.assertEqual(n.selection(self.profiles,[OTHER]),('choose',None))
        self.profiles.save(OTHER,'b','Other',CAP)
        self.assertEqual(n.selection(self.profiles,[OTHER]),('alternative',OTHER))
        self.profiles.data['preferred']=None
        self.assertEqual(n.selection(self.profiles,[AP,OTHER]),('choose',None))

    def test_capabilities_not_mutually_exclusive(self):
        self.profiles.save(AP,'a','Both',CAP,True)
        self.assertTrue(self.profiles.match(AP.bssid)['internet'])
        self.assertEqual(self.profiles.match(AP.bssid)['stratux_ip'],'192.168.10.1')

    def test_scan_preserves_duplicate_names_different_bssids(self):
        output=r'AA\:BB\:CC\:DD\:EE\:01:stratux:75:WPA2:wlan0:*'+'\n'+r'AA\:BB\:CC\:DD\:EE\:02:stratux:80:--:wlan0:'
        m=n.Manager(self.profiles,lambda *a,**kw:SimpleNamespace(returncode=0,stdout=output))
        self.assertEqual(len(m.scan()),2)

    def test_connect_secret_not_in_arguments_and_bssid_pinned(self):
        calls=[]
        def run(arguments,**kw):
            calls.append((arguments,kw))
            if 'GENERAL.CON-UUID' in arguments:return SimpleNamespace(returncode=0,stdout='12345678-1234-1234-1234-123456789012')
            if 'BSSID,IN-USE' in arguments:return SimpleNamespace(returncode=0,stdout=r'AA\:BB\:CC\:DD\:EE\:01:*')
            return SimpleNamespace(returncode=0,stdout='')
        m=n.Manager(self.profiles,run)
        with patch.object(m,'probe',return_value=CAP),patch('network_manager.authorize'):
            connection,result=m.connect(AP,'secret-value')
        self.assertFalse(any('secret-value' in arg for args,_ in calls for arg in args))
        self.assertTrue(any(kw['input']=='secret-value\n' for _,kw in calls))
        self.assertTrue(any('802-11-wireless.bssid' in args and AP.bssid in args for args,_ in calls))

    def test_bssid_mismatch_fails(self):
        self.profiles.save(AP,'id','Saved',CAP)
        m=n.Manager(self.profiles,lambda *a,**k:SimpleNamespace(returncode=0,stdout=r'AA\:BB\:CC\:DD\:EE\:02:*'))
        with self.assertRaisesRegex(RuntimeError,'BSSID'):m.connect(AP)

    def test_probe_checks_real_gateway_and_rejects_unrelated_json(self):
        m=n.Manager(self.profiles)
        m.nm=lambda *a:'10.44.0.254'
        class Response:
            status=200
            def __init__(self,data,url=''):self.data=data;self.url=url
            def read(self,limit):return self.data[:limit]
            def geturl(self):return self.url
            def __enter__(self):return self
            def __exit__(self,*a):pass
        urls=[]
        def local(url,timeout):
            urls.append(url)
            return Response(json.dumps({'GPSLatitude':0,'GPSLongitude':0,'GPSFixQuality':0} if '10.44.0.254' in url else {'hello':'world'}).encode())
        with patch('network_manager.urllib.request.build_opener',return_value=SimpleNamespace(open=local)),patch('network_manager.urllib.request.urlopen',side_effect=OSError):
            result=m.probe('wlan0')
        self.assertEqual(result,dict(stratux_ip='10.44.0.254',internet=False,updates=False))
        self.assertTrue(any('10.44.0.254' in url for url in urls))

    def test_collector_guard_rejects_wrong_boot_and_bssid(self):
        path=Path(self.temp.name)/'session.json'
        with patch('network_manager.PROFILE_PATH',self.profiles.path),patch('network_manager.SESSION_PATH',path),patch('network_manager.boot_id',return_value='this-boot'):
            self.assertTrue(n.receiver_allowed('192.168.10.1')) # legacy, no profiles file
            self.profiles.save(AP,'a','Saved',CAP,True)
            n._guard_cache=(0,None,False)
            self.assertFalse(n.receiver_allowed('192.168.10.1'))
            path.write_text(json.dumps(dict(boot='old-boot',address='192.168.10.1',bssid=AP.bssid,device='wlan0')))
            n._guard_cache=(0,None,False)
            self.assertFalse(n.receiver_allowed('192.168.10.1'))
            path.write_text(json.dumps(dict(boot='this-boot',address='192.168.10.1',bssid=AP.bssid,device='wlan0')))
            n._guard_cache=(0,None,False)
            with patch('network_manager.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=r'AA\:BB\:CC\:DD\:EE\:02:*')):
                self.assertFalse(n.receiver_allowed('192.168.10.1'))

    def test_collector_guard_accepts_only_current_selection(self):
        path=Path(self.temp.name)/'session.json'
        self.profiles.save(AP,'a','Saved',CAP,True)
        with patch('network_manager.PROFILE_PATH',self.profiles.path),patch('network_manager.SESSION_PATH',path),patch('network_manager.boot_id',return_value='this-boot'):
            path.write_text(json.dumps(dict(boot='this-boot',address='192.168.10.1',bssid=AP.bssid,device='wlan0')))
            n._guard_cache=(0,None,False)
            with patch('network_manager.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=r'AA\:BB\:CC\:DD\:EE\:01:*')):
                self.assertTrue(n.receiver_allowed('192.168.10.1'))
            n._guard_cache=(0,None,False)
            self.assertFalse(n.receiver_allowed('10.0.0.1'))

    def test_captive_portal_is_not_internet_or_updates(self):
        class Response:
            status=200
            def geturl(self):return 'https://portal.example/'
            def read(self,limit):return b'<html>Login required</html>'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        m=n.Manager(self.profiles);m.nm=lambda *a:''
        with patch('network_manager.urllib.request.build_opener',return_value=SimpleNamespace(open=lambda *a,**kw:Response())),patch('network_manager.urllib.request.urlopen',return_value=Response()):
            result=m.probe('wlan0')
        self.assertEqual(result,dict(stratux_ip=None,internet=False,updates=False))

    def test_quoted_update_csv_header_is_reachable(self):
        class Response:
            status=204
            def __init__(self,update=False):self.update=update;self.status=200 if update else 204
            def geturl(self):return n.INTERNET_URL
            def read(self,limit):return b'"id","ident","type","name"\n'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        m=n.Manager(self.profiles);m.nm=lambda *a:''
        with patch('network_manager.urllib.request.build_opener',return_value=SimpleNamespace(open=lambda *a,**kw:(_ for _ in ()).throw(OSError()))),patch('network_manager.urllib.request.urlopen',side_effect=[Response(),Response(True)]):
            result=m.probe('wlan0')
        self.assertTrue(result['internet']);self.assertTrue(result['updates'])

if __name__=='__main__':unittest.main()
