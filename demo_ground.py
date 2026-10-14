"""Offline map experiment: rasterize in a separate process, never in Tk.

Only standard-library modules are required. Output is a small binary PPM image;
Tk doubles it once and reuses that PhotoImage across traffic frames.
"""
import json
import math
import multiprocessing as mp
import queue
from pathlib import Path

PACK=Path(__file__).with_name('demo_ground.json')
BG=(3,9,9)

def load_pack(path=PACK):
    path=Path(path)
    if path.stat().st_size>2000000:raise ValueError('Demo pack too large')
    data=json.loads(path.read_text())
    if data.get('schema')!=2:raise ValueError('Unsupported ground pack')
    bounds=data['bounds']
    if len(bounds)!=4 or not all(math.isfinite(v) for v in bounds):raise ValueError('Invalid bounds')
    count=0
    def points(coords):
        nonlocal count
        count+=len(coords)
        if count>50000:raise ValueError('Demo pack too large')
        if any(len(p)!=2 or not all(math.isfinite(v) for v in p) or not(-90<=p[0]<=90 and -180<=p[1]<=180) for p in coords):raise ValueError('Invalid coordinates')
        return tuple(tuple(p) for p in coords)
    paths=[]
    for item in data['paths']:
        if item['kind'] not in ('road','water'):raise ValueError('Unknown map feature')
        coords=points(item['points'])
        if len(coords)>=2:paths.append((item['kind'],coords))
    polygons=[]
    for polygon in data.get('water_polygons',[]):
        rings=tuple(points(r) for r in polygon)
        if any(len(r)<4 or r[0]!=r[-1] for r in rings):raise ValueError('Unclosed water boundary')
        polygons.append(rings)
    return bounds,tuple(paths),tuple(polygons)

def project(lat,lon,origin):
    a,b=map(math.radians,(origin[0],lat));dl=math.radians((lon-origin[1]+180)%360-180)
    hav=math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(dl/2)**2
    distance=6880.13*math.asin(math.sqrt(min(1,max(0,hav))))
    bearing=math.atan2(math.sin(dl)*math.cos(b),math.cos(a)*math.sin(b)-math.sin(a)*math.cos(b)*math.cos(dl))
    return distance*math.sin(bearing),distance*math.cos(bearing)

def clip_rectangle(a,b,size):
    # Liang-Barsky: bound line work even for faraway source geometry.
    x,y=a;dx,dy=b[0]-x,b[1]-y;lo,hi=0.,1.
    for p,q in [(-dx,x),(dx,size-1-x),(-dy,y),(dy,size-1-y)]:
        if abs(p)<1e-12:
            if q<0:return None
        else:
            t=q/p
            if p<0:lo=max(lo,t)
            else:hi=min(hi,t)
            if lo>hi:return None
    return (x+lo*dx,y+lo*dy),(x+hi*dx,y+hi*dy)

def rasterize(paths,polygons,state):
    origin,heading,radius,level,size=state
    if not (2<=radius<=20 and level in (1,2) and 64<=size<=512):raise ValueError('Invalid render state')
    pixels=bytearray(bytes(BG)*(size*size));center=(size-1)/2;scale=center/radius
    angle=math.radians(heading);cos,sin=math.cos(angle),math.sin(angle)
    road=(39,51,50) if level==1 else (71,84,80)
    shore=(23,56,67) if level==1 else (37,85,106)
    water=(10,32,42) if level==1 else (16,49,65)
    def screen(points):
        result=[]
        for lat,lon in points:
            e,n=project(lat,lon,origin)
            result.append((center+(e*cos-n*sin)*scale,center-(e*sin+n*cos)*scale))
        return result
    def fill(rings):
        # Even/odd scanline rule fills complete outer rings and preserves islands.
        transformed=[screen(r) for r in rings]
        edges=[(a,b) for ring in transformed for a,b in zip(ring,ring[1:]) if a[1]!=b[1]]
        if not edges:return
        first=max(0,math.ceil(min(min(a[1],b[1]) for a,b in edges)-.5))
        last=min(size-1,math.floor(max(max(a[1],b[1]) for a,b in edges)-.5))
        for row in range(first,last+1):
            y=row+.5
            xs=sorted(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in edges if min(a[1],b[1])<=y<max(a[1],b[1]))
            for left,right in zip(xs[::2],xs[1::2]):
                lo=max(0,math.ceil(left-.5));hi=min(size-1,math.floor(right-.5))
                if hi>=lo:pixels[(row*size+lo)*3:(row*size+hi+1)*3]=bytes(water)*(hi-lo+1)
    for rings in polygons:fill(rings)
    def stroke(points,color):
        color=bytes(color)
        for a,b in zip(points,points[1:]):
            clipped=clip_rectangle(a,b,size)
            if not clipped:continue
            a,b=clipped;x,y=map(round,a);xx,yy=map(round,b)
            dx,dy=abs(xx-x),-abs(yy-y);sx=1 if x<xx else -1;sy=1 if y<yy else -1;err=dx+dy
            while True:
                i=(y*size+x)*3;pixels[i:i+3]=color
                if x==xx and y==yy:break
                twice=2*err
                if twice>=dy:err+=dy;x+=sx
                if twice<=dx:err+=dx;y+=sy
    for kind,points in paths:stroke(screen(points),road if kind=='road' else shore)
    # Round mask; outside is the same black as the traffic canvas.
    for row in range(size):
        half=math.sqrt(max(0,center*center-(row-center)**2))
        lo=max(0,math.ceil(center-half));hi=min(size-1,math.floor(center+half))
        pixels[(row*size)*3:(row*size+lo)*3]=bytes(BG)*lo
        pixels[(row*size+hi+1)*3:((row+1)*size)*3]=bytes(BG)*(size-hi-1)
    return f'P6\n{size} {size}\n255\n'.encode()+pixels

def latest_put(channel,message):
    try:channel.put_nowait(message)
    except queue.Full:
        try:channel.get_nowait()
        except queue.Empty:pass
        try:channel.put_nowait(message)
        except queue.Full:pass

def render_process(path,requests,results):
    # This module has no Tk import; spawn cannot inherit the GUI's Tk state.
    try:
        bounds,paths,polygons=load_pack(path)
        results.put(('ready',bounds))
        while True:
            state=requests.get()
            if state is None:return
            while True:
                try:new=requests.get_nowait()
                except queue.Empty:break
                if new is None:return
                state=new
            image=rasterize(paths,polygons,state)
            latest_put(results,('image',state,image))
    except Exception as exc:latest_put(results,('error',str(exc)))

class GroundLayer:
    def __init__(self,path=PACK):
        ctx=mp.get_context('spawn')
        self.requests=ctx.Queue(maxsize=1);self.results=ctx.Queue(maxsize=2)
        self.result=None;self.error='';self.bounds=None;self.closed=False
        self.process=ctx.Process(target=render_process,args=(str(path),self.requests,self.results),daemon=True,name='ground-raster')
        self.process.start()
    def request(self,state):
        if not self.closed and not self.error:latest_put(self.requests,state)
    def poll(self):
        # At most two tiny/one-image messages; no waits or geometry work in GUI.
        for _ in range(2):
            try:message=self.results.get_nowait()
            except queue.Empty:break
            if message[0]=='ready':self.bounds=message[1]
            elif message[0]=='error':self.error=message[1]
            else:self.result=message[1:]
        if self.process.exitcode is not None and not self.closed and not self.error:self.error='Map renderer stopped'
    def close(self):
        if self.closed:return
        self.closed=True
        if self.process.is_alive():self.process.terminate()
        self.process.join(timeout=.1)
        for channel in (self.requests,self.results):channel.cancel_join_thread();channel.close()
    def covers(self,origin,radius):
        if not self.bounds:return False
        south,west,north,east=self.bounds
        lat,lon=origin;dl=radius/(60*max(.1,math.cos(math.radians(lat))))
        return south<=lat-radius/60 and lat+radius/60<=north and west<=lon-dl and lon+dl<=east
