"""Read-only network checks: no host or radio changes in these tests."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import threading
import subprocess
import unittest
import network_diagnostics as d

class Tests(unittest.TestCase):
    def test_targets_reject_commands_urls_and_options(self):
        for value in ('192.168.10.1','2001:db8::1','fishfinder.local','gateway'):
            self.assertEqual(d.target(value),value)
        for value in ('','-c5','$(id)','a;b','http://example.com','host:22','x y','a\nb'):
            with self.assertRaises(ValueError):d.target(value)

    def test_ping_is_bounded_without_shell_and_reports_latency(self):
        run=MagicMock(return_value=SimpleNamespace(returncode=0,stdout='64 bytes time=2.34 ms'))
        self.assertIn('responded · 2.34 ms',d.ping('192.168.10.1',run))
        args,kwargs=run.call_args
        self.assertEqual(args[0][-2:],['--','192.168.10.1'])
        self.assertNotIn('shell',kwargs)
        self.assertEqual(kwargs['timeout'],7)

    def test_no_reply_does_not_assert_offline(self):
        run=MagicMock(return_value=SimpleNamespace(returncode=1,stdout=''))
        self.assertIn('does not prove it is offline',d.ping('example.com',run))
        run.side_effect=subprocess.TimeoutExpired('ping',7)
        self.assertIn('ICMP may be blocked',d.ping('example.com',run))
        run.side_effect=FileNotFoundError()
        self.assertIn('unavailable',d.ping('example.com',run))

    def test_connection_reads_actual_active_ap_and_ipv6(self):
        replies=['wlan0:wifi:connected\neth0:ethernet:disconnected',
                 r'GENERAL.CONNECTION:Home\: WiFi'+'\n'+r'IP4.ADDRESS[1]:10.0.0.6/24'+'\n'+
                 r'IP4.GATEWAY:10.0.0.1'+'\n'+r'IP6.ADDRESS[1]:2001\:db8\:\:5/64'+'\n'+r'IP6.ADDRESS[2]:fe80\:\:5/64',
                 r'AA\:BB\:CC\:DD\:EE\:FF:*']
        m=SimpleNamespace(lock=threading.Lock(),nm=MagicMock(side_effect=replies),
                          profiles=SimpleNamespace(match=MagicMock(return_value={'name':'Home'})))
        info=d.connection(m)
        self.assertTrue(info['connected']);self.assertEqual(info['name'],'Home')
        self.assertEqual(info['ipv4'],['10.0.0.6/24'])
        self.assertEqual(info['ipv6'],['2001:db8::5/64'])
        self.assertEqual(info['gateway'],'10.0.0.1')
        for call in m.nm.call_args_list:
            self.assertNotIn('connect',call.args)
            self.assertNotIn('modify',call.args)

    def test_disconnected_has_no_invented_address(self):
        m=SimpleNamespace(lock=threading.Lock(),nm=MagicMock(return_value='wlan0:wifi:disconnected'))
        self.assertEqual(d.connection(m),{'connected':False})
