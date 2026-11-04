"""Reconnect uses saved BSSID identity; it must never bypass new-device naming."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import unittest
import network_manager as nm
from network_screen import NetworkScreen

AP=nm.AccessPoint('AA:BB:CC:DD:EE:01','stratux',75,'','wlan0')
OTHER=nm.AccessPoint('AA:BB:CC:DD:EE:02','stratux',80,'','wlan0')
CAP=dict(stratux_ip='192.168.10.1',internet=False,updates=False)

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.profiles=nm.Profiles(Path(self.temp.name)/'networks.json')
        self.profiles.save(AP,'saved-uuid','First Stratux',CAP,True)
        self.ui=NetworkScreen.__new__(NetworkScreen)
        self.ui.manager=SimpleNamespace(profiles=self.profiles)
        self.ui.selected=AP;self.ui.startup=True
        self.ui.display=MagicMock()
        self.ui.close=MagicMock();self.ui.name_page=MagicMock()

    def test_verified_saved_startup_skips_naming_without_rewriting_profile(self):
        before=self.profiles.path.read_bytes()
        with patch('network_screen.settings.load',return_value={'stratux_ip':'192.168.10.1'}):
            self.ui.connected(('saved-uuid',CAP))
        self.ui.close.assert_called_once()
        self.ui.name_page.assert_not_called()
        self.ui.display.apply_settings.assert_not_called()
        self.assertTrue(self.ui.display.network_status.startswith('First Stratux'))
        self.assertEqual(before,self.profiles.path.read_bytes())

    def test_changed_receiver_address_is_applied_before_closing(self):
        with patch('network_screen.settings.load',return_value={'stratux_ip':'192.168.10.1','own_tail':'N123A'}):
            self.ui.connected(('saved-uuid',dict(CAP,stratux_ip='192.168.20.1')))
        self.ui.display.apply_settings.assert_called_once_with({'stratux_ip':'192.168.20.1','own_tail':'N123A'})
        self.ui.close.assert_called_once()

    def test_unverified_receiver_does_not_auto_continue(self):
        self.ui.connected(('saved-uuid',dict(CAP,stratux_ip=None)))
        self.ui.close.assert_not_called();self.ui.name_page.assert_called_once()

    def test_new_bssid_with_same_ssid_still_requires_enrollment(self):
        self.ui.selected=OTHER
        self.ui.connected(('new-uuid',CAP))
        self.ui.close.assert_not_called();self.ui.name_page.assert_called_once()
        self.assertIsNotNone(self.profiles.duplicate('First Stratux',OTHER.bssid))

    def test_saved_home_network_continues_without_receiver_or_internet(self):
        home=dict(CAP,stratux_ip=None,internet=False,updates=False)
        self.profiles.save(OTHER,'home-uuid','Home',home)
        self.ui.selected=OTHER
        before=self.profiles.path.read_bytes()
        self.ui.connected(('home-uuid',home))
        self.ui.close.assert_called_once()
        self.ui.name_page.assert_not_called()
        self.assertEqual(before,self.profiles.path.read_bytes())

    def test_choose_saved_network_connects_immediately(self):
        self.ui.busy=False
        self.ui.list=SimpleNamespace(curselection=lambda:(0,))
        self.ui.aps=[OTHER]
        self.profiles.save(OTHER,'home-uuid','Home',dict(CAP,stratux_ip=None))
        self.ui.connect=MagicMock();self.ui.clear=MagicMock()
        self.ui.choose()
        self.ui.connect.assert_called_once()
        self.ui.clear.assert_not_called()
        self.assertEqual(self.ui.selected,OTHER)

    def test_setup_can_still_edit_existing_name(self):
        self.ui.startup=False
        self.ui.connected(('saved-uuid',CAP))
        self.ui.close.assert_not_called();self.ui.name_page.assert_called_once()

    def test_saving_same_name_for_same_bssid_is_allowed(self):
        self.ui.capabilities=CAP;self.ui.connection_id='saved-uuid'
        self.ui.busy=False;self.ui.name=SimpleNamespace(get=lambda:'First Stratux')
        self.ui.preferred=SimpleNamespace(get=lambda:True)
        self.ui.message=MagicMock()
        with patch('network_screen.settings.load',return_value={'stratux_ip':'192.168.10.1'}):
            self.ui.save()
        self.ui.close.assert_called_once()
        self.assertEqual(len(self.profiles.data['networks']),1)
        self.assertEqual(self.profiles.data['preferred'],AP.bssid)
        self.ui.message.set.assert_not_called()
