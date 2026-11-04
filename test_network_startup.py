"""No chooser flash on preferred startup; unavailable/error states retain recovery."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import queue
import unittest
import network_manager as nm
from network_screen import NetworkScreen

AP=nm.AccessPoint('AA:BB:CC:DD:EE:01','stratux',75,'','wlan0')

class Tests(unittest.TestCase):
    def make(self,aps,preferred=AP.bssid):
        ui=NetworkScreen.__new__(NetworkScreen)
        ui.busy=False;ui.startup=True;ui.startup_progress=False
        ui.message=MagicMock();ui.progress_page=MagicMock();ui.list_page=MagicMock()
        ui.list=MagicMock();ui.connect=MagicMock()
        profiles=SimpleNamespace(data={'preferred':preferred},match=lambda b:{'name':'Receiver'} if b==preferred else None)
        ui.manager=SimpleNamespace(profiles=profiles,scan=lambda:aps)
        ui.job=lambda callback,done:done(callback())
        return ui

    def test_preferred_startup_never_builds_chooser(self):
        ui=self.make([AP]);ui.scan(automatic=True)
        ui.progress_page.assert_called_once()
        ui.connect.assert_called_once()
        ui.list_page.assert_not_called()
        ui.list.insert.assert_not_called()
        self.assertEqual(ui.selected,AP)

    def test_missing_preferred_shows_chooser_after_scan(self):
        ui=self.make([]);ui.scan(automatic=True)
        ui.progress_page.assert_called_once();ui.list_page.assert_called_once()
        ui.connect.assert_not_called()
        self.assertIn('Preferred Stratux unavailable',ui.message.set.call_args.args[0])

    def test_first_setup_lists_available_networks(self):
        ui=self.make([AP],None);ui.scan(automatic=True)
        ui.list_page.assert_called_once()
        ui.list.insert.assert_called_once()
        ui.connect.assert_not_called()

    def test_explicit_other_networks_does_not_autoconnect(self):
        ui=self.make([AP]);ui.scan(automatic=False)
        ui.progress_page.assert_not_called()
        ui.list_page.assert_called_once();ui.connect.assert_not_called()

    def test_failed_scan_or_connect_exposes_recovery_choices(self):
        ui=self.make([])
        ui.closed=False;ui.startup_progress=True;ui.jobs=queue.Queue()
        ui.jobs.put((MagicMock(),None,'Connection timed out'))
        ui.poll()
        self.assertFalse(ui.busy)
        ui.list_page.assert_called_once()
        self.assertIn('Wait / Retry',ui.message.set.call_args.args[0])
