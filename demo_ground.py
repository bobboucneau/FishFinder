"""Optional offline O22 orientation experiment. No network or Tk calls here."""
import json
import math
import queue
import threading
from pathlib import Path

PACK = Path(__file__).with_name('demo_ground.json')

def load_pack(path=PACK):
    data=json.loads(Path(path).read_text())
    if data.get('schema')!=1: raise ValueError('Unsupported ground pack')
    bounds=data['bounds']
    if len(bounds)!=4 or not all(math.isfinite(v) for v in bounds): raise ValueError('Invalid bounds')
    paths=[]
    count=0
    for item in data['paths']:
        if item['kind'] not in ('road','water'): raise ValueError('Unknown map feature')
        coords=item['points'];count+=len(coords)
        if count>30000: raise ValueError('Demo pack too large')
        if len(coords)<2:continue
        if any(len(p)!=2 or not all(math.isfinite(v) for v in p) or not(-90<=p[0]<=90 and -180<=p[1]<=180) for p in coords):
            raise ValueError('Invalid map coordinates')
        paths.append((item['kind'],coords))
    return bounds,paths

class GroundLayer:
    """Load and project in a worker; reuse latest geometry while traffic updates."""
    def __init__(self,stop,projector,path=PACK):
        self.stop=stop;self.projector=projector;self.path=path
        self.requests=queue.Queue(maxsize=1);self.result=None;self.error='';self.bounds=None
        threading.Thread(target=self.run,daemon=True,name='demo-ground').start()
    def request(self,origin):
        try:self.requests.put_nowait(origin)
        except queue.Full:pass
    def run(self):
        try:self.bounds,paths=load_pack(self.path)
        except (OSError,ValueError,KeyError,TypeError) as e:
            self.error=str(e);return
        while not self.stop.is_set():
            try:origin=self.requests.get(timeout=.5)
            except queue.Empty:continue
            result=tuple((kind,tuple(self.projector(lat,lon,origin) for lat,lon in points)) for kind,points in paths)
            self.result=(origin,result) # immutable snapshot; main thread only reads
    def covers(self,origin,radius):
        if not self.bounds:return False
        south,west,north,east=self.bounds
        lat,lon=origin;dl=radius/(60*max(.1,math.cos(math.radians(lat))))
        return south<=lat-radius/60 and lat+radius/60<=north and west<=lon-dl and lon+dl<=east
