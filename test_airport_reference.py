# READING THE TESTS: this file checks behavior without requiring a flight.
# An assert... call states what must be true; a failed assertion means the
# observed result differs from the expected one. Mock/patch objects temporarily
# replace a dependency, so tests can exercise errors without changing hardware.
# These checks on a Mac do not replace touchscreen/GPS validation on the Pi.

import csv
from datetime import date,datetime,timedelta,timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import faa_airports as faa
import airport_reference as ref
import update_airports as updater
from test_airports import gui

class Tests(unittest.TestCase):
    def archive(self,flag='',tower='NON-ATCT',tpa='1000',remark=''):
        eff=datetime.now(timezone.utc).date().isoformat().replace('-','/')
        tables={
          'APT_BASE.csv':[dict(EFF_DATE=eff,SITE_NO='1',ARPT_ID='CPU',ICAO_ID='KCPU',LAT_DECIMAL='38.146',LONG_DECIMAL='-120.648',TPA=tpa,ELEV='1327.9',TWR_TYPE_CODE=tower)],
          'APT_RWY_END.csv':[dict(EFF_DATE=eff,SITE_NO='1',RWY_END_ID='13',RIGHT_HAND_TRAFFIC_PAT_FLAG=flag)],
          'APT_RMK.csv':[dict(SITE_NO='1',REF_COL_NAME='TPA' if remark else 'OTHER',REMARK=remark)]}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name,rows in tables.items():
                text=io.StringIO();w=csv.DictWriter(text,fieldnames=rows[0]);w.writeheader();w.writerows(rows);z.writestr(name,text.getvalue())
        return stream.getvalue()
    def candidate(self):return dict(airports=[dict(ident='KCPU',code='KCPU',country='US',lat=38.146,lon=-120.648)])
    # Check: u arrows point to threshold on correct pattern side.
    def test_u_arrows_point_to_threshold_on_correct_pattern_side(self):
        import math
        for heading in ((0,-1),(1,0),(0,1),(-1,0)):
            for direction in ('Left','Right'):
                threshold=(400,450);points=ref.pattern_arrow(threshold,heading,direction)
                tip=points[-1];before=points[-2]
                self.assertAlmostEqual(math.dist(tip,threshold),7)
                tangent=(tip[0]-before[0],tip[1]-before[1])
                self.assertGreater(tangent[0]*heading[0]+tangent[1]*heading[1],0)
                self.assertAlmostEqual(tangent[0]*heading[1]-tangent[1]*heading[0],0)
                right=(-heading[1],heading[0])
                offset=(points[0][0]-threshold[0],points[0][1]-threshold[1])
                self.assertGreater((offset[0]*right[0]+offset[1]*right[1])*(1 if direction=='Right' else -1),0)
                downwind=(points[1][0]-points[0][0],points[1][1]-points[0][1])
                self.assertLess(downwind[0]*heading[0]+downwind[1]*heading[1],0)

    # Check: effective cycle not preview.
    def test_effective_cycle_not_preview(self):
        html='<a href="/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/2026-10-29/">preview</a><a href="/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/2026-10-01/">current</a>'
        self.assertEqual(faa.cycle_links(html,date(2026,10,16))[0],date(2026,10,1))
    # Check: msl and present end default left.
    def test_msl_and_present_end_default_left(self):
        data=self.candidate();eff=datetime.now(timezone.utc).date().isoformat()
        faa.enrich(data,self.archive(),eff,'FAA');a=data['airports'][0]
        self.assertEqual(a['reference']['pattern_msl_ft'],2328)
        self.assertEqual(a['reference']['patterns']['13'],'Left')
        self.assertNotIn('31',a['reference']['patterns'])
        faa.enrich(data,self.archive(flag='Y',remark='TPA RWY 13 800 FT AGL.'),eff,'FAA')
        self.assertIsNone(a['reference']['pattern_msl_ft'])
        self.assertEqual(a['reference']['patterns']['13'],'Right')
    # Check: expiry tower unknown and complex suppress arrows.
    def test_expiry_tower_unknown_and_complex_suppress_arrows(self):
        obj=gui();a=obj.catalog.airports['KCPU']
        self.assertEqual(ref.current_reference(a,date(2026,10,29)),{})
        a=dict(a,reference=dict(a['reference'],effective=datetime.now(timezone.utc).date().isoformat(),expires=(datetime.now(timezone.utc).date()+timedelta(days=28)).isoformat()))
        self.assertEqual(ref.pattern(a,'31'),'Right')
        self.assertEqual(ref.pattern(a,'13'),'Left')
        for tower in ('towered','unknown'):
            a=dict(a,reference=dict(a['reference'],tower=tower));self.assertIsNone(ref.pattern(a,'31'))
        a=dict(a,type='large_airport');self.assertFalse(ref.simple_airport(a))
        obj.stop.set()
    # Check: full screen has no underlying targets.
    def test_full_screen_has_no_underlying_targets(self):
        obj=gui();obj.airport_selected='KO22';obj.airport_details()
        self.assertEqual(obj.buttons,[]);self.assertEqual(obj.hits,[]);self.assertEqual(obj.airport_hits,[])
        self.assertTrue(any(action.startswith('runway:') for *_,action in obj.airport_buttons))
        obj.airport_action('runway:0');self.assertEqual(obj.airport_runway_index,0)
        obj.airport_action('view');self.assertTrue(obj.airport_runways)
        obj.airport_action('close');self.assertIsNone(obj.airport_selected)
        obj.stop.set()
    # Check: red arrows and persistent version.
    def test_red_arrows_and_persistent_version(self):
        obj=gui();obj.airport_selected='KO22'
        # This checks arrow styling, not the wall-clock validity of a shipped
        # reference cache. Keep the in-memory fixture current as dates advance.
        obj.catalog.airports['KO22']['reference'].update(effective='2000-01-01',expires='2099-01-01')
        obj.draw()
        arrows=[kw for name,_,kw in obj.canvas.commands if name=='create_line' and kw.get('arrow')=='last']
        self.assertTrue(arrows);self.assertTrue(all(kw['fill']=='#ff3030' for kw in arrows))
        self.assertTrue(any(kw.get('tags')=='map-attribution' for _,_,kw in obj.canvas.commands))
        obj.airport_selected=None;obj.ground_level=0;obj.last_touch=0;obj.draw()
        chars=''.join(kw.get('text','') for _,_,kw in obj.canvas.commands if kw.get('tags')=='map-attribution')
        self.assertEqual(chars,'v'+obj.version+'©2026FishFinder')
        obj.stop.set()

    # Check: standard and runway specific altitude.
    def test_standard_and_runway_specific_altitude(self):
        obj=gui();a=obj.catalog.airports['KCPU']
        a=dict(a,reference=dict(a['reference'],effective=datetime.now(timezone.utc).date().isoformat(),expires=(datetime.now(timezone.utc).date()+timedelta(days=28)).isoformat()))
        altitude,source=ref.pattern_altitude(a,a['runways'][0])
        self.assertEqual(altitude,2328);self.assertTrue(source.startswith('Standard'))
        a=dict(a,reference=dict(a['reference'],pattern_remarks=['TPA RWY 13/31 800 FT AGL.']))
        altitude,source=ref.pattern_altitude(a,a['runways'][0])
        self.assertEqual(altitude,2128);self.assertTrue(source.startswith('Published'))
        a['reference']['pattern_remarks']=['TPA VARIES; SEE CHART SUPPLEMENT']
        self.assertIsNone(ref.pattern_altitude(a,a['runways'][0])[0])
        obj.stop.set()

    # Check: due 28 day and faa expiry.
    def test_due_28_day_and_faa_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'airports.json'
            d=dict(downloaded_utc='2026-10-16',airports=[dict(country='US')],faa=dict(effective='2026-10-01',expires='2026-10-29'))
            p.write_text(json.dumps(d));self.assertFalse(updater.update_due(p,date(2026,10,28)));self.assertTrue(updater.update_due(p,date(2026,10,29)))
            d['airports']=[];p.write_text(json.dumps(d));self.assertFalse(updater.update_due(p,date(2026,11,12)));self.assertTrue(updater.update_due(p,date(2026,11,13)))
    # Check: failed faa enrichment preserves cache.
    def test_failed_faa_enrichment_preserves_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'airports.json';p.write_text('{"airports":[]}');before=p.read_bytes()
            candidate=dict(schema=1,airports=[dict(country='US',runways=[{}],frequencies=[{}])])
            with patch.object(updater,'fetch',return_value=[]),patch.object(updater,'build',return_value=candidate),patch.object(faa,'fetch_enrichment',side_effect=OSError('offline')):
                with self.assertRaises(OSError):updater.refresh(p)
            self.assertEqual(p.read_bytes(),before)

if __name__=='__main__':unittest.main()
