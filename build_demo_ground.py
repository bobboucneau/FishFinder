"""Build bundled O22 roads/water from Overpass JSON; run on development machine.

Download geometry with the documented query, then:
python3 build_demo_ground.py raw.json demo_ground.json
Relations are drawn as shoreline segments, including inner boundaries; no filled
polygons, so islands are not accidentally painted as water.
"""
import argparse
import json
import math
from datetime import datetime,timezone
from pathlib import Path

BOUNDS=[37.65,-120.95,38.4,-119.9]
QUERY='''[out:json][timeout:90];(way[highway~"^(motorway|trunk|primary|secondary)$"](37.65,-120.95,38.4,-119.9);way[waterway=river](37.65,-120.95,38.4,-119.9);way[natural=water](37.65,-120.95,38.4,-119.9);relation[natural=water](37.65,-120.95,38.4,-119.9););out geom;'''

def simplify(points,tolerance=.0006):
    """Iterative Douglas-Peucker, roughly 65m tolerance at O22 latitude."""
    if len(points)<3:return points
    keep={0,len(points)-1};stack=[(0,len(points)-1)]
    while stack:
        lo,hi=stack.pop();a,b=points[lo],points[hi]
        dx=(b[1]-a[1])*.788;dy=b[0]-a[0];den=dx*dx+dy*dy
        distance=-1;index=None
        for j in range(lo+1,hi):
            px=(points[j][1]-a[1])*.788;py=points[j][0]-a[0]
            t=max(0,min(1,(px*dx+py*dy)/den)) if den else 0
            d=(px-t*dx)**2+(py-t*dy)**2
            if d>distance:distance,index=d,j
        if distance>tolerance*tolerance:
            keep.add(index);stack.extend(((lo,index),(index,hi)))
    return [points[i] for i in sorted(keep)]

def build(raw):
    if raw.get('remark'):raise ValueError(raw['remark'])
    paths=[];seen=set();original=0
    for element in raw['elements']:
        tags=element.get('tags',{});kind='road' if 'highway' in tags else 'water'
        geometries=[element.get('geometry',[])] if element['type']=='way' else [m.get('geometry',[]) for m in element.get('members',[]) if m.get('type')=='way']
        for geometry in geometries:
            points=[[p['lat'],p['lon']] for p in geometry if 'lat' in p and 'lon' in p]
            if len(points)<2:continue
            # Remove small closed ponds/islands that clutter a cockpit overview.
            if kind=='water' and points[0]==points[-1] and max(max(p[0] for p in points)-min(p[0] for p in points),.788*(max(p[1] for p in points)-min(p[1] for p in points)))<.008:
                continue
            original+=len(points);points=simplify(points)
            rounded=[[round(lat,5),round(lon,5)] for lat,lon in points]
            key=json.dumps(rounded)
            if key in seen:continue
            seen.add(key);paths.append(dict(kind=kind,points=rounded))
    if not paths or not any(p['kind']=='water' for p in paths) or not any(p['kind']=='road' for p in paths):
        raise ValueError('Missing roads or water')
    return dict(schema=1,bounds=BOUNDS,downloaded_utc=datetime.now(timezone.utc).isoformat(),source='OpenStreetMap via Overpass',attribution='© OpenStreetMap contributors',license='ODbL 1.0',license_url='https://www.openstreetmap.org/copyright',source_timestamp=raw.get('osm3s',{}).get('timestamp_osm_base'),original_vertices=original,paths=paths)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('raw');parser.add_argument('output');args=parser.parse_args()
    data=build(json.loads(Path(args.raw).read_text()))
    Path(args.output).write_text(json.dumps(data,separators=(',',':')))
    print(len(data['paths']),'paths;',data['original_vertices'],'source vertices;',sum(len(p['points']) for p in data['paths']),'retained vertices;',Path(args.output).stat().st_size,'bytes')
