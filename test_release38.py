"""Check update prompt layout and callbacks without installing or deferring a build."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from bootstrap import Launcher


class Surface:
    def __init__(self,parent,paint):
        self.paint=paint;self.scale=1;self.actions={};self.texts=[]
    def pack(self,**kwargs):self.paint()
    def start(self):pass
    def box(self,*args,**kwargs):pass
    def label(self,x,y,text,size,**kwargs):self.texts.append((text,size))
    def button(self,bounds,label,callback,*args):
        self.actions[label]=(bounds,callback)


class Tests(unittest.TestCase):
    def prompt(self,owner=True):
        launcher=Launcher.__new__(Launcher)
        launcher.prompt=None;launcher.root=MagicMock();launcher.store=MagicMock()
        launcher.install=MagicMock()
        with patch('bootstrap.tk.Frame'),patch('ff_controls.RoundScreen',Surface):
            launcher.update_prompt({'owner_build':owner,'release':'0.4.38'})
        # Retrieve the real Surface instance used by the method via the pack hook.
        return launcher

    def test_prompt_and_each_action_preserve_policies(self):
        for label,policy in (('Install now',None),('Next startup','next-start'),('Later','later')):
            surfaces=[]
            def create(parent,paint):
                item=Surface(parent,paint);surfaces.append(item);return item
            launcher=Launcher.__new__(Launcher)
            launcher.prompt=None;launcher.root=MagicMock();launcher.store=MagicMock()
            launcher.install=MagicMock()
            with patch('bootstrap.tk.Frame'),patch('ff_controls.RoundScreen',create):
                launcher.update_prompt({'owner_build':True,'release':'0.4.38'})
            view=surfaces[0]
            self.assertIn(('Update available',30),view.texts)
            self.assertIn(('0.4.38',35),view.texts)
            self.assertTrue(any(text=='Owner-modified build' for text,_ in view.texts))
            first=view.actions['Install now'][0];second=view.actions['Next startup'][0]
            self.assertEqual(first[2]-first[0],second[2]-second[0])
            view.actions[label][1]()
            if policy:
                launcher.store.defer.assert_called_once_with(policy)
                launcher.install.assert_not_called()
                self.assertIsNone(launcher.prompt)
            else:
                launcher.install.assert_called_once()
                launcher.store.defer.assert_not_called()
