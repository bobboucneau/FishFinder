"""Export the existing seeded Python scenario and airport reference for the web demo."""
from pathlib import Path
import json,sys,math
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from demo_traffic import Scenario,local
from airport_reference import runways,pattern_altitude,pattern,simple_airport
from airport_data import runway_segments
from traffic_display import xy

out=Path(__file__).resolve().parent/'dist'
s=Scenario(seed=22);flights={}
for t in range(0,2401,10):
 s.advance(t)
 for f in s.flights:
  if f.end>=300 and f.start<=2400:flights[(f.address,f.start)]=f
result=[]
for f in flights.values():
 begin=max(300,f.start);end=min(2400,f.end)
 if end<=begin:continue
 times=[begin]+list(range(math.ceil(begin/3)*3,math.floor(end/3)*3+1,3))+[end]
 points=[]
 for t in sorted(set(times)):
  p=f.sample(t)
  if p:points.append([round(t-600,3),round(p[0],5),round(p[1],5),round(p[2],1),round(p[3],2)])
 result.append(dict(id=f'{f.address:x}-{f.start:.2f}',tail=f.tail,kind=f.kind,points=points))
airports=[]
for a in s.airports.values():
 e,n=local(s.origin,a['lat'],a['lon']);strips=runways(a);refs=[]
 for r in strips:
  altitude,source=pattern_altitude(a,r)
  refs.append(dict(le=r['le_ident'],he=r['he_ident'],length=r.get('length_ft'),width=r.get('width_ft'),patterns={end:pattern(a,end) for end in (r['le_ident'],r['he_ident'])},altitude=altitude,altitudeSource=source))
 segments=[]
 for r,p,q,schematic in runway_segments(dict(a,runways=strips),xy):segments.append(dict(le=r['le_ident'],he=r['he_ident'],p=p,q=q,schematic=schematic))
 airports.append(dict(code=a['code'],name=a['name'],e=e,n=n,elevation=float(a['elevation_ft']),frequencies=a.get('frequencies',[]),runways=refs,segments=segments,simple=simple_airport(a),source=a.get('reference',{}),defaultRunway=max(range(len(strips)),key=lambda i:float(strips[i].get('length_ft') or 0))))
(out/'demo.json').write_text(json.dumps(dict(version='0.1.0',basedOn='0.4.18',origin=s.origin,start=600,end=1800,flights=result,airports=airports),separators=(',',':')))
ground=json.loads((ROOT/'demo_ground.json').read_text())
# Optional build-only source for settlement labels; never copy the world archive.
if '--world-map' in sys.argv:
 from tile_ground import TileMap
 path=Path(sys.argv[sys.argv.index('--world-map')+1])
 world=TileMap(path)
 try:
  world.query(s.origin,20)
  ground['places']=world.labels
 finally:world.close()
(out/'ground.json').write_text(json.dumps(ground,separators=(',',':')))

print('Exported',len(result),'flights and',len(airports),'airports;', (out/'demo.json').stat().st_size,'bytes')
