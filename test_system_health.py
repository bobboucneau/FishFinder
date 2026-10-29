"""Health checks use fixed samples, never allocating large buffers or contacting a receiver."""
import unittest
from unittest.mock import patch
import subprocess
import system_health as h

class HealthTests(unittest.TestCase):
    def test_reclaimable_memory_and_malformed_input(self):
        self.assertEqual(h.memory_values('MemTotal: 900000 kB\nMemFree: 100 kB\nMemAvailable: 500000 kB'),(500000,900000))
        for text in ('', 'MemTotal: bad', 'MemTotal: 10\nMemAvailable: 20'):
            self.assertEqual(h.memory_values(text),(None,None))

    def test_connection_stale_missing_and_database_failure(self):
        self.assertEqual(h.indicators((100,True,''),100,101),[('Stratux','green'),('GPS','green')])
        self.assertEqual(h.indicators((100,True,''),100,116)[0][1],'red')
        self.assertEqual(h.indicators(None,None,101)[0][1],'unknown')
        self.assertEqual(h.indicators((100,False,''),None,101)[0][1],'red')
        self.assertEqual(h.indicators((100,True,''),100,101,database_error=True)[1][1],'unknown')

    def test_demo_never_claims_live_connectivity(self):
        self.assertEqual(h.indicators((100,True,''),100,101,demo=True),
                         [('Stratux DEMO','unknown'),('GPS DEMO','unknown')])

    def test_temperature_and_stale_monitor(self):
        for value,color in ((None,'unknown'),(50,'green'),(75,'amber'),(80,'red')):
            self.assertEqual(h.hardware_status(h.Health(100,value),101)[0][1],color)
        self.assertEqual(h.hardware_status(h.Health(100,50),116), (('Temp ?','unknown'),[]))

    def test_memory_warnings_only_when_needed(self):
        for available,expected in ((500000,None),(80000,'amber'),(30000,'red')):
            warnings=h.hardware_status(h.Health(100,50,available,900000),101)[1]
            self.assertEqual(warnings[0][1] if warnings else None,expected)
        self.assertEqual(h.hardware_status(h.Health(100,50,None,None),101)[1],[])

    def test_power_history_is_not_current_fault(self):
        self.assertEqual(h.hardware_status(h.Health(100,50,500000,900000,0x50000),101)[1],[])
        warnings=h.hardware_status(h.Health(100,50,500000,900000,5),101)[1]
        self.assertEqual([w[1] for w in warnings],['red','amber'])

    def test_failed_hardware_queries_are_unknown(self):
        with patch('system_health.shutil.which',return_value='/usr/bin/vcgencmd'), \
             patch('system_health.subprocess.run',side_effect=subprocess.TimeoutExpired('probe',1)), \
             patch('system_health.Path.read_text',side_effect=OSError):
            sample=h.sample()
        self.assertIsNone(sample.temperature)
        self.assertIsNone(sample.throttled)
        self.assertIsNone(sample.available_kib)

    def test_firmware_values(self):
        with patch('system_health.shutil.which',return_value='/usr/bin/vcgencmd'), \
             patch('system_health.subprocess.run',side_effect=[type('R',(),{'stdout':"temp=52.5'C"})(),type('R',(),{'stdout':'throttled=0x0'})()]), \
             patch('system_health.Path.read_text',return_value='MemTotal: 900000 kB\nMemAvailable: 500000 kB'):
            sample=h.sample()
        self.assertEqual(sample.temperature,52.5)
        self.assertEqual(sample.throttled,0)
        self.assertEqual(sample.available_kib,500000)

if __name__=='__main__':unittest.main()
