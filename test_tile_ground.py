# READING THE TESTS: this file checks behavior without requiring a flight.
# An assert... call states what must be true; a failed assertion means the
# observed result differs from the expected one. Mock/patch objects temporarily
# replace a dependency, so tests can exercise errors without changing hardware.
# These checks on a Mac do not replace touchscreen/GPS validation on the Pi.

import gzip
import json
from pathlib import Path
import tempfile
import math
import time
import unittest
import tile_ground as t
import demo_ground as g
from vendor_pmtiles.tile import serialize_header,serialize_directory,Entry,Compression,TileType,zxy_to_tileid

def uint(n):
    out=bytearray()
    while n>127:out.append((n&127)|128);n>>=7
    out.append(n);return bytes(out)
def field(k,value):
    return uint(k*8+(2 if isinstance(value,bytes) else 0))+(uint(len(value))+value if isinstance(value,bytes) else uint(value))
def commands(parts,closed=False):
    out=[];x=y=0
    def move(p):
        nonlocal x,y
        a,b=p[0]-x,p[1]-y;x,y=p
        return [(a<<1)^(a>>63),(b<<1)^(b>>63)]
    for part in parts:
        out.extend([9,*move(part[0])])
        if len(part)>1:
            out.append(((len(part)-1)<<3)|2)
            for p in part[1:]:out.extend(move(p))
        if closed:out.append(15)
    return b''.join(map(uint,out))
def layer(name,typ,parts,title=None):
    feature=field(3,typ)+field(4,commands(parts,typ==3))
    data=field(15,2)+field(1,name.encode())+field(5,4096)
    if title:
        feature+=field(2,b'\0\0');data+=field(3,b'name')+field(4,field(1,title.encode()))
    return field(3,data+field(2,feature))
def fixture(path):
    z,x,y=13,1355,3158
    raw=gzip.compress(layer('ground_road',2,[[(2048,2048),(2200,2200)]])+layer('ground_place',1,[[(2048,2048)]],'Test Town'))
    root=serialize_directory([Entry(zxy_to_tileid(z,x,y),0,len(raw),1)])
    meta=gzip.compress(json.dumps({'fishfinder_ground_schema':'1','zooms':[13]}).encode())
    header={'root_offset':127,'root_length':len(root),'metadata_offset':127+len(root),'metadata_length':len(meta),'tile_data_offset':127+len(root)+len(meta),'tile_data_length':len(raw),'clustered':True,'internal_compression':Compression.GZIP,'tile_compression':Compression.GZIP,'tile_type':TileType.MVT,'min_zoom':13,'max_zoom':13}
    path.write_bytes(serialize_header(header)+root+meta+raw)
    return t.decode_tile(raw,z,x,y)[2][0][:2]

class TileTests(unittest.TestCase):
    # Check: geometry polygon holes and names.
    def test_geometry_polygon_holes_and_names(self):
        outer=[(2000,2000),(2100,2000),(2100,2100),(2000,2100)]
        hole=[(2020,2020),(2020,2080),(2080,2080),(2080,2020)]
        raw=gzip.compress(layer('ground_water',3,[outer,hole])+layer('ground_place',1,[[(2048,2048)]],'Columbia'))
        paths,polygons,labels,count=t.decode_tile(raw,0,0,0)
        self.assertFalse(paths);self.assertEqual(len(polygons),1);self.assertEqual(len(polygons[0]['rings']),2)
        self.assertEqual(labels[0],(0,0,'Columbia'));self.assertGreater(count,8)
        # Filled water retains the center island after decoding.
        ppm=g.rasterize(paths,polygons,((0,0),0,20,1,100));self.assertTrue(ppm.startswith(b'P6'))
    # Check: attribution follows lower right rim and water matches.
    def test_attribution_follows_lower_right_rim_and_water_matches(self):
        from test_airports import gui
        obj=gui();obj.canvas.commands=[]
        obj.rim_attribution('© OpenStreetMap contributors')
        commands=obj.canvas.commands
        self.assertTrue(commands)
        angles=[]
        for name,coords,kwargs in commands:
            self.assertEqual(name,'create_text');x,y=coords
            self.assertGreater(x,obj.cx);self.assertGreater(y,obj.cy)
            self.assertAlmostEqual(math.hypot(x-obj.cx,y-obj.cy),390*obj.unit)
            angles.append(kwargs['angle'])
        self.assertGreater(max(angles)-min(angles),10)
        obj.stop.set()
        state=((0,0),0,10,1,100)
        fill=g.rasterize([],[[[[-.1,-.1],[-.1,.1],[.1,.1],[.1,-.1],[-.1,-.1]]]],state).split(b'\n',3)[3]
        river=g.rasterize([('river',[(0,-.1),(0,.1)])],[],state).split(b'\n',3)[3]
        blue=bytes((20,52,68))
        self.assertIn(blue,fill);self.assertIn(blue,river)

    # Check: reject truncation commands and bombs.
    def test_reject_truncation_commands_and_bombs(self):
        for raw in (b'\x80',b'\x0a\x05x',b'\x0f'):
            with self.assertRaises(ValueError):list(t.fields(raw))
        for raw in (b'\x09\x00',b'\x0a\x00\x00',b'\x00'):
            with self.assertRaises(ValueError):t.geometry(raw,2)
        with self.assertRaises(ValueError):t.decode_tile(gzip.compress(b'0'*8_000_001),0,0,0)
    # Check: build simplification removes small detail and keeps ring winding.
    def test_build_simplification_removes_small_detail_and_keeps_ring_winding(self):
        from build_rich_ground import simplify_geometry
        line=commands([[(0,0),(1,1),(2,0),(10,0)]])
        reduced=t.geometry(simplify_geometry(t.varints(line),2,4),2)
        self.assertEqual(len(reduced[0]),2)
        outer=[(0,0),(100,0),(100,100),(0,100)]
        hole=[(20,20),(20,80),(80,80),(80,20)]
        parts=t.geometry(simplify_geometry(t.varints(commands([outer,hole],True)),3,8),3)
        self.assertEqual(len(parts),2)
        def area(r):return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(r,r[1:]))
        self.assertGreater(area(parts[0]),0);self.assertLess(area(parts[1]),0)
        self.assertTrue(all(r[0]==r[-1] for r in parts))

    # Check: archive local query caches and subprocess.
    def test_archive_local_query_caches_and_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.pmtiles';origin=fixture(path)
            world=t.TileMap(path)
            try:
                paths,polygons=world.query(origin,2)
                self.assertEqual(len(paths),1);self.assertFalse(polygons)
                self.assertEqual(world.labels[0][2],'Test Town')
                world.query(origin,2);self.assertGreater(world.tile.cache_info().hits,0)
            finally:world.close()
            worker=g.GroundLayer(path)
            try:
                worker.request((origin,0,2,1,100));deadline=time.monotonic()+5
                while not worker.result and not worker.error and time.monotonic()<deadline:worker.poll();time.sleep(.01)
                self.assertFalse(worker.error);self.assertIsNotNone(worker.result)
                self.assertEqual(worker.result[2][0][2],'Test Town')
            finally:worker.close()

if __name__=='__main__':unittest.main()
