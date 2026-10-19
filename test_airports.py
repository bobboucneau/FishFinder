import argparse
from datetime import date
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import airport_data as ad
import update_airports as updater
import traffic_display as display


class Canvas:
    def __init__(self,*args,**kwargs): self.commands=[]
    def pack(self,**kwargs): pass
    def bind(self,*args): pass
    def find_all(self):return tuple(range(1,len(self.commands)+1))
    def delete(self,*args):
        if args==('all',):self.commands=[]
        elif args==('map-label',):
            self.commands=[v for v in self.commands if v[2].get('tags')!='map-label']
        elif args and isinstance(args[0],int) and args[0]<=len(self.commands):
            self.commands[args[0]-1]=('deleted',(),{})
    def winfo_width(self): return 800
    def winfo_height(self): return 800
    def __getattr__(self,name):
        if name.startswith('create_'):
            def record(*coords,**kwargs):
                self.commands.append((name,coords,kwargs));return len(self.commands)
            return record
        raise AttributeError(name)


class Root:
    def __init__(self):self.callbacks={};self.counter=0
    def after(self,delay,callback):
        self.counter+=1;self.callbacks[self.counter]=callback;return self.counter
    def after_cancel(self,token):self.callbacks.pop(token,None)
    def fire(self,token):self.callbacks.pop(token)()
    def __getattr__(self,name): return lambda *a,**kw:None


def gui(no_ownship=False,path='airports.json'):
    args=SimpleNamespace(fullscreen=False,geometry='800x800',demo=True,no_ownship=no_ownship,range=10,airports=path)
    with patch.object(display.tk,'Canvas',Canvas):
        return display.Display(Root(),args)


class Tests(unittest.TestCase):
    def test_ownship_tap_and_stale_details(self):
        d=gui();d.hits=[(400,400,'__ownship__')];d.airport_hits=[]
        d.tap(SimpleNamespace(x=400,y=400));d.root.fire(d.pending_tap[0])
        self.assertEqual(d.selected,'__ownship__')
        labels=[kw.get('text','') for _,_,kw in d.canvas.commands]
        self.assertIn('Ownship',labels)
        self.assertTrue(any(v.startswith('Course:') and 'true' in v for v in labels))
        self.assertTrue(any(v.startswith('Ground speed:') for v in labels))
        self.assertTrue(any(v.startswith('Altitude:') for v in labels))
        d.canvas.commands=[];d.ownship_details(None,[],time.time())
        self.assertTrue(any('no longer fresh' in kw.get('text','') for _,_,kw in d.canvas.commands))
        missing=gui(True)
        self.assertFalse(any(h[2]=='__ownship__' for h in missing.hits))

    def test_target_choice_paging_cancel_and_airport_selection(self):
        d=gui();d.last_touch=time.monotonic()-20;d.draw()
        d.hits=[(400,400,f'test{i}') for i in range(6)]
        d.airport_hits=[(401,401,'KRHV')]
        d.tap(SimpleNamespace(x=400,y=400));d.root.fire(d.pending_tap[0])
        self.assertEqual(len(d.target_choices),7);self.assertIsNone(d.selected)
        before=list(d.target_choices);d.draw();self.assertEqual(d.target_choices,before)
        def press(action):
            x1,y1,x2,y2,_=next(b for b in d.choice_buttons if b[-1]==action)
            d.tap(SimpleNamespace(x=(x1+x2)/2,y=(y1+y2)/2))
        press('next');self.assertEqual(d.choice_page,1)
        press(6);self.assertEqual(d.airport_selected,'KRHV');self.assertFalse(d.target_choices)
        d.airport_action('close');d.target_choices=before;d.draw()
        press('cancel');self.assertFalse(d.target_choices);self.assertIsNone(d.selected)
        d.single_tap(SimpleNamespace(x=400,y=400),[(400,400,'test0')],[])
        self.assertEqual(d.selected,'test0')

    def test_freshness(self):
        self.assertFalse(ad.freshness_label('2026-10-06',date(2026,10,6))[1])
        self.assertTrue(ad.freshness_label('2026-10-06',date(2026,11,7))[1])
        self.assertTrue(ad.freshness_label('2026-10-06',date(2026,10,5))[1])
        self.assertTrue(ad.freshness_label('bad')[1])

    def test_import_filter_and_join(self):
        row=dict(ident='TEST',type='small_airport',name='Test',latitude_deg='0',longitude_deg='0',iso_country='US')
        data=updater.build([row,dict(row,ident='CLOSED',type='closed_airport'),dict(row,ident='BAD',latitude_deg='nan')],
            [dict(airport_ident='TEST',le_ident='09',he_ident='27')],[dict(airport_ident='TEST',type='CTAF',frequency_mhz='123.0')],['US'])
        self.assertEqual(len(data['airports']),1)
        self.assertEqual(data['airports'][0]['runways'][0]['le_ident'],'09')
        self.assertEqual(data['airports'][0]['frequencies'][0]['frequency_mhz'],'123.0')
        with self.assertRaises(ValueError):updater.build([row],[],[],['CA'])

    def test_catalog_and_wrapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.json'
            p.write_text(json.dumps(dict(schema=1,downloaded_utc='2026-10-06',airports=[dict(ident='DATE',lat=0,lon=-179.95)])))
            c=ad.AirportCatalog(p)
            self.assertEqual(len(c.nearby((0,179.95),10,display.xy)),1)
            self.assertEqual(len(c.nearby((0,179.95),2,display.xy)),0)
            self.assertEqual(c.nearby(None,10,display.xy),[])
            self.assertTrue(ad.AirportCatalog(Path(tmp)/'missing').error)
            p.write_text('{');self.assertTrue(ad.AirportCatalog(p).error)

    def test_geometry_rotation_and_missing(self):
        self.assertAlmostEqual(ad.rotate((1,0),90)[1],1)
        self.assertAlmostEqual(ad.rotate((0,1),90)[0],-1)
        base=dict(lat=0,lon=0,runways=[dict(le_latitude_deg='0',le_longitude_deg='0',he_latitude_deg='0',he_longitude_deg='.01')])
        seg=ad.runway_segments(base,display.xy)[0]
        self.assertFalse(seg[3]);self.assertGreater(seg[2][0],seg[1][0])
        base['runways']=[dict(length_ft='6076.11549',he_heading_degT='270')]
        seg=ad.runway_segments(base,display.xy)[0]
        self.assertTrue(seg[3]);self.assertAlmostEqual(math.dist(seg[1],seg[2]),1)
        self.assertGreater(seg[2][0],seg[1][0])
        base['runways']=[dict(length_ft='1000')]
        self.assertEqual(ad.runway_segments(base,display.xy),[])

    def test_real_cache_touch_and_views(self):
        d=gui();self.assertFalse(d.catalog.error)
        self.assertTrue(d.airport_hits)
        self.assertAlmostEqual(d.airport_track,0)
        hit=next(h for h in d.airport_hits if h[2]=='KRHV')
        d.tap(SimpleNamespace(x=hit[0],y=hit[1]));d.root.fire(d.pending_tap[0])
        self.assertEqual(d.airport_selected,'KRHV')
        d.airport_action('view');self.assertTrue(d.airport_runways)
        d.draw();self.assertTrue(d.airport_buttons)
        d.airport_action('close');self.assertIsNone(d.airport_selected)
        # Overlapping aircraft and airport now offer an explicit choice.
        tx,ty,tail=d.hits[0];d.airport_hits=[(tx,ty,'KRHV')]
        d.tap(SimpleNamespace(x=tx,y=ty));d.root.fire(d.pending_tap[0])
        self.assertTrue(d.target_choices);self.assertIsNone(d.selected)
        choice=next(v for v in d.target_choices if v[1:] == ('aircraft',tail))
        d.select_target(choice);self.assertEqual(d.selected,tail)
        d.selected=None;d.toggle_airports();self.assertEqual(d.airport_hits,[])
        # Dataset remains available for selected details after changing range.
        d.airport_selected='KSJC';d.airport_runways=False;d.airport_page=100;d.airport_details()
        self.assertLess(d.airport_page,100)

    def test_no_fix_and_stationary_and_no_cache(self):
        d=gui(True);self.assertIsNone(d.airport_track)
        d.airport_selected='KCPU';d.airport_runways=False;d.draw()
        labels=[k.get('text','') for _,_,k in d.canvas.commands]
        self.assertTrue(any('NORTH UP' in t for t in labels))
        d=gui(path='not-there.json');self.assertTrue(d.catalog.error);self.assertTrue(d.hits)
        # Fresh fix at zero speed falls back north up rather than inventing heading.
        d=gui();now=time.time()
        d.snapshot=display.Snapshot({},[display.Point(1,now,37.3,-121.9,0,100)])
        d.draw();self.assertIsNone(d.airport_track)

    def test_updater_failure_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'airports.json';target.write_text('baseline')
            with patch('sys.argv',['update_airports.py','--output',str(target)]),patch.object(updater,'fetch',side_effect=OSError('network unavailable')):
                with self.assertRaises(OSError):updater.main()
            self.assertEqual(target.read_text(),'baseline')


if __name__=='__main__':
    unittest.main()
