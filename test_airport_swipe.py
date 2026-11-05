"""Airport entry gestures without opening a real Tk window."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from airport_selector import Selector

class SwipeTests(unittest.TestCase):
    def setUp(self):
        self.s=Selector.__new__(Selector)
        self.s.screen=Mock(scale=1,offset=(0,0))
        self.s.spin=Mock()
        self.s.repeat_job=None

    def gesture(self,x,y,dx,dy):
        end=SimpleNamespace(x=x+dx,y=y+dy)
        self.s.wheel_press(SimpleNamespace(x=x,y=y))
        self.s.wheel_motion(end)
        self.s.wheel_release(end)

    def test_swipe_from_button_scrolls_without_tapping(self):
        self.gesture(650,430,0,-150)
        self.s.spin.assert_called_once_with(5)
        self.s.screen.tap.assert_not_called()

    def test_short_swipe_moves_one_character(self):
        self.gesture(120,230,0,30)
        self.s.spin.assert_called_once_with(-1)

    def test_tap_and_horizontal_drag(self):
        self.gesture(650,430,0,0)
        self.gesture(650,430,-150,10)
        self.s.screen.tap.assert_called_once()
        self.s.spin.assert_not_called()

    def test_drag_cancels_arrow_hold(self):
        self.gesture(400,320,0,90)
        self.s.screen.after_cancel.assert_called_once()
        self.s.spin.assert_called_once_with(-3)
