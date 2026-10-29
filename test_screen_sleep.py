"""Focused local tests; no X server, network downloads or large memory allocations."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import settings
import screen_sleep
import traffic_display as d
import system_health as h

class ScreenTests(unittest.TestCase):
    def test_sleep_default_and_validation(self):
        self.assertEqual(settings.validate({})['screen_sleep'],'never')
        for value in ('never','5','10','20','30','60'):
            self.assertEqual(settings.validate({'screen_sleep':value})['screen_sleep'],value)
        with self.assertRaises(ValueError):settings.validate({'screen_sleep':'-1'})

    def test_x11_commands(self):
        self.assertEqual(screen_sleep.commands('never'),[('s','off'),('-dpms',)])
        self.assertEqual(screen_sleep.commands('5'),[('s','300'),('+dpms',),('dpms','0','0','300')])

    def test_status_center_warnings_and_red_ring(self):
        # Record drawing requests rather than opening a window. Use a fixed font
        # measurement so exact centering can be checked independent of platform.
        for idle,y in ((True,62),(False,143)):
            obj=d.Display.__new__(d.Display)
            obj.root=None;obj.idle=idle;obj.unit=1;obj.cx=obj.cy=400
            obj.snapshot=d.Snapshot({},[],receiver=(100,True,''))
            obj.health_monitor=SimpleNamespace(latest=h.Health(100,81,30000,900000,0))
            obj.permission_issues=[]
            rectangles=[];texts=[];ovals=[]
            obj.rect=lambda *args,**kw:rectangles.append((args,kw))
            obj.text=lambda *args,**kw:texts.append((args,kw))
            obj.canvas=SimpleNamespace(create_oval=lambda *args,**kw:ovals.append((args,kw)))
            with patch('tkinter.font.Font',return_value=SimpleNamespace(measure=lambda label:len(label)*6)),patch('time.monotonic',return_value=101):
                obj.draw_system_status(SimpleNamespace(time=100),101)
            bounds=rectangles[0][0]
            self.assertAlmostEqual((bounds[0]+bounds[2])/2,400)
            self.assertEqual(texts[0][0][1],y)
            self.assertEqual(texts[-1][0][1],y+25)
            self.assertTrue(any(kw.get('outline')==d.RED and args==(2,2,798,798) for args,kw in ovals))

if __name__=='__main__':unittest.main()
