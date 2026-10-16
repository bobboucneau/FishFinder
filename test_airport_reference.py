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
    def test_effective_cycle_not_preview(self):
        html='<a href="/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/2026-10-29/">preview</a><a href="/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/2026-10-01/">current</a>'
        self.assertEqual(faa.cycle_links(html,date(2026,10,16))[0],date(2026,10,1))
    def test_msl_and_present_end_default_left(self):
        data=self.candidate();eff=datetime.now(timezone.utc).date().isoformat()
        faa.enrich(data,self.archive(),eff,'FAA');a=data['airports'][0]
        self.assertEqual(a['reference']['pattern_msl_ft'],2328)
        self.assertEqual(a['reference']['patterns']['13'],'Left')
        self.assertNotIn('31',a['reference']['patterns'])
        faa.enrich(data,self.archive(flag='Y',remark='TPA RWY 13 800 FT AGL.'),eff,'FAA')
        self.assertIsNone(a['reference']['pattern_msl_ft'])
        self.assertEqual(a['reference']['patterns']['13'],'Right')
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
    def test_full_screen_has_no_underlying_targets(self):
        obj=gui();obj.airport_selected='KO22';obj.airport_details()
        self.assertEqual(obj.buttons,[]);self.assertEqual(obj.hits,[]);self.assertEqual(obj.airport_hits,[])
        self.assertTrue(any(action.startswith('runway:') for *_,action in obj.airport_buttons))
        obj.airport_action('runway:0');self.assertEqual(obj.airport_runway_index,0)
        obj.airport_action('view');self.assertTrue(obj.airport_runways)
        obj.airport_action('close');self.assertIsNone(obj.airport_selected)
        obj.stop.set()
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

    def test_due_28_day_and_faa_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'airports.json'
            d=dict(downloaded_utc='2026-10-16',airports=[dict(country='US')],faa=dict(effective='2026-10-01',expires='2026-10-29'))
            p.write_text(json.dumps(d));self.assertFalse(updater.update_due(p,date(2026,10,28)));self.assertTrue(updater.update_due(p,date(2026,10,29)))
            d['airports']=[];p.write_text(json.dumps(d));self.assertFalse(updater.update_due(p,date(2026,11,12)));self.assertTrue(updater.update_due(p,date(2026,11,13)))
    def test_failed_faa_enrichment_preserves_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'airports.json';p.write_text('{"airports":[]}');before=p.read_bytes()
            candidate=dict(schema=1,airports=[dict(country='US',runways=[{}],frequencies=[{}])])
            with patch.object(updater,'fetch',return_value=[]),patch.object(updater,'build',return_value=candidate),patch.object(faa,'fetch_enrichment',side_effect=OSError('offline')):
                with self.assertRaises(OSError):updater.refresh(p)
            self.assertEqual(p.read_bytes(),before)

if __name__=='__main__':unittest.main()
