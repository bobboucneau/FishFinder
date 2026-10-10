#!/usr/local/Fishfinder/.venv/bin/python3
"""Touch traffic plot for an 800x800 round display. Read-only SQLite client.

python3 traffic_display.py --demo
python3 traffic_display.py --fullscreen
All GUI operations stay on Tk's main thread; database reads run separately.
"""
import argparse
import settings
import setup_screen
import math
import queue
import sqlite3
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from airport_data import AirportCatalog, BLUE, rotate, runway_segments, freshness_label

EARTH_NM = 3440.065
HORIZON = 300.0
REPORT_AGE = 60.0
TRAIL_AGE = 300.0
OWN_AGE = 15.0
FRAME_MS = 250
AIRPORT_REFRESH_SECONDS = 1.0
GREEN, YELLOW, RED = '#50ef97', '#ffd45c', '#ff565e'
ESTIMATED = '#c58aff'
WHITE, MUTED, BG = '#e0f2ef', '#7b9a95', '#030909'


@dataclass(frozen=True)
class Point:
    id: int
    time: float
    lat: float
    lon: float
    speed: float
    altitude: float
    comparison_alt: float = None
    alt_ref: str = None
    estimated: bool = False
    position_age: float = None


@dataclass
class Snapshot:
    reports: dict
    ownship: list
    error: str = ''
    demo: bool = False
    labels: dict = None
    receiver: tuple = None


def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def point(row):
    values = [finite(row[k]) for k in ('time', 'latitude', 'longitude', 'speed', 'asl')]
    if any(v is None for v in values[:4]):
        return None
    t, lat, lon, speed, alt = values
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and speed >= 0):
        return None
    return Point(row['id'], t, lat, lon, speed, alt, finite(row['comparison_alt']) if 'comparison_alt' in row.keys() else None, row['alt_ref'] if 'alt_ref' in row.keys() else None, bool(row['estimated']) if 'estimated' in row.keys() else False, finite(row['position_age']) if 'position_age' in row.keys() else None)


def xy(lat, lon, origin):
    """Great-circle distance/bearing mapped to a local east/north plane, NM."""
    a, b = map(math.radians, (origin[0], lat))
    dl = math.radians((lon - origin[1] + 180) % 360 - 180)
    y = math.sin(dl) * math.cos(b)
    x = math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b) * math.cos(dl)
    hav = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(dl/2)**2
    distance = 2 * EARTH_NM * math.asin(math.sqrt(min(1, max(0, hav))))
    bearing = math.atan2(y, x)
    return distance * math.sin(bearing), distance * math.cos(bearing)


def offset(origin, east, north):
    """Destination for an east/north vector in NM (used by the demo)."""
    distance, bearing = math.hypot(east, north)/EARTH_NM, math.atan2(east, north)
    lat, lon = map(math.radians, origin)
    newlat = math.asin(math.sin(lat)*math.cos(distance) + math.cos(lat)*math.sin(distance)*math.cos(bearing))
    newlon = lon + math.atan2(math.sin(bearing)*math.sin(distance)*math.cos(lat), math.cos(distance)-math.sin(lat)*math.sin(newlat))
    return math.degrees(newlat), (math.degrees(newlon)+180)%360-180


def velocity(history):
    """Infer ground track from distinct recent positions; use reported knots."""
    latest = history[-1]
    if latest.speed <= 0.5:
        return (0.0, 0.0)
    for previous in reversed(history[:-1]):
        dt = latest.time - previous.time
        if 0.2 <= dt <= 10:
            east, north = xy(latest.lat, latest.lon, (previous.lat, previous.lon))
            distance = math.hypot(east, north)
            # Reject tiny GPS jitter and implausible jumps rather than inventing track.
            if distance >= 0.002 and distance/dt*3600 <= max(600, latest.speed*3):
                speed = latest.speed/3600
                return east/distance*speed, north/distance*speed
    return None


def closest_approach(relative, relative_velocity):
    speed2 = sum(v*v for v in relative_velocity)
    t = 0 if speed2 < 1e-12 else max(0, min(HORIZON, -sum(a*b for a,b in zip(relative, relative_velocity))/speed2))
    return t, math.hypot(relative[0]+relative_velocity[0]*t, relative[1]+relative_velocity[1]*t)


def turn_possible(relative, own_velocity, speed):
    """Can a target at constant speed reach within 1 NM of ownship's path?

    Conservative envelope: instant turn, any direction, no turn-rate limit.
    Minimize the convex distance-minus-reachable-radius function over 5 min.
    """
    def gap(t):
        return math.hypot(relative[0]-own_velocity[0]*t, relative[1]-own_velocity[1]*t) - speed/3600*t
    lo, hi = 0.0, HORIZON
    for _ in range(50):
        a, b = (2*lo+hi)/3, (lo+2*hi)/3
        if gap(a) < gap(b):
            hi = b
        else:
            lo = a
    return min(gap(0), gap(HORIZON), gap((lo+hi)/2)) <= 1


def assess(relative, target_velocity, own_velocity, speed, stale=False):
    distance = math.hypot(*relative)
    if stale:
        return YELLOW, 'STALE: proximity assessment unavailable', None
    if own_velocity is None or target_velocity is None:
        return YELLOW, 'Ground track unavailable: proximity uncertain', None
    rv = (target_velocity[0]-own_velocity[0], target_velocity[1]-own_velocity[1])
    cpa = closest_approach(relative, rv)
    closing = sum(a*b for a,b in zip(relative, rv)) < -1e-6
    if distance <= 1 and closing:
        return RED, 'Within 1 NM and closing (horizontal)', cpa
    if cpa[1] <= 1:
        return YELLOW, 'Projected within 1 NM in five minutes (horizontal)', cpa
    if turn_possible(relative, own_velocity, speed):
        return YELLOW, 'A turn could bring this target within 1 NM', cpa
    return GREEN, 'Outside five-minute horizontal reach envelope', cpa


def vertical_clear(target, own, threshold, horizon=300):
    """Require fresh matching references and observed rates on both tracks.

    Do not infer a zero rate from one sample or suppress unknown/stale altitude.
    """
    if not own or not target or own[-1].altitude is None: return False
    def state(history):
        latest=history[-1]
        if latest.estimated: return None
        if latest.comparison_alt is None or latest.alt_ref != 'pressure': return None
        recent=[p for p in history if 0<=latest.time-p.time<=20 and
                p.comparison_alt is not None and p.alt_ref==latest.alt_ref]
        if len(recent)<3: return None
        previous=recent[0]; dt=latest.time-previous.time
        if dt<10: return None
        rate=(latest.comparison_alt-previous.comparison_alt)/dt
        if abs(rate)>200: return None
        return latest.comparison_alt,rate
    if time.time()-target[-1].time>10 or time.time()-own[-1].time>OWN_AGE: return False
    t,o=state(target),state(own)
    if t is None or o is None: return False
    delta=t[0]-o[0]; end=delta+(t[1]-o[1])*horizon
    return delta*end>0 and min(abs(delta),abs(end))>threshold


def read_snapshot(path):
    # mode=ro prevents accidentally creating a database at a misspelled path.
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True, timeout=0.5)
    conn.row_factory = sqlite3.Row
    try:
        now = time.time()
        conn.execute('BEGIN')  # A coherent view of both tables; short read transaction.
        reports = {}
        for row in conn.execute('SELECT * FROM reports WHERE time >= ? ORDER BY time, id', (now-TRAIL_AGE,)):
            p = point(row)
            if p and isinstance(row['tail'], str) and row['tail'].strip():
                reports.setdefault(row['tail'].strip(), []).append(p)
        ownship = [p for row in conn.execute('SELECT * FROM ownship WHERE time >= ? ORDER BY time, id', (now-TRAIL_AGE,)) if (p := point(row))]
        labels = {}
        # Accept both the original schema and the upgraded collector schema.
        columns = {row[1] for row in conn.execute('PRAGMA table_info(aircraft)')}
        if {'registration', 'callsign'} <= columns:
            for row in conn.execute('SELECT tail, registration, callsign FROM aircraft'):
                names = list(dict.fromkeys(name for name in (row['registration'], row['callsign']) if name))
                labels[row['tail']] = ' / '.join(names) or row['tail']
        receiver=None
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='receiver_status'").fetchone():
            row=conn.execute('SELECT time,available,message FROM receiver_status WHERE id=1').fetchone()
            if row: receiver=tuple(row)
        return Snapshot(reports, ownship, labels=labels, receiver=receiver)
    finally:
        conn.close()


def active_histories(reports, now):
    histories={k:[p for p in ps if 0<=now-p.time<=TRAIL_AGE] for k,ps in reports.items()}
    return {k:ps for k,ps in histories.items() if ps and now-ps[-1].time<=REPORT_AGE}


def demo_snapshot(no_ownship=False):
    now = time.time()
    origin = (37.3, -121.9)
    own_speed = 100/3600
    own = []
    for i in range(101):
        ago = (100-i)*3
        lat, lon = offset(origin, 0, -own_speed*ago)
        own.append(Point(i, now-ago, lat, lon, 100, 3500, 3500, 'pressure'))
    reports = {}
    targets = [('N123AB', 0, -0.7, 0, 140, 3700),
               ('N456CD', 3.5, 3, 270, 180, 4200),
               ('N789EF', -8, 1, 270, 40, 6500),
               ('N246GH', 2, -4, 20, 115, 3000), ('N900HI', -3, 2, 90, 250, 14000)]
    for tail,e,n,heading,speed,alt in targets:
        ve = math.sin(math.radians(heading))*speed/3600
        vn = math.cos(math.radians(heading))*speed/3600
        reports[tail] = []
        for i in range(61):
            ago=(60-i)*5
            lat,lon=offset(origin,e-ve*ago,n-vn*ago)
            reports[tail].append(Point(i,now-ago,lat,lon,speed,alt,alt,'pressure'))
    return Snapshot(reports, [] if no_ownship else own, demo=True)


def reader(stop, out, path):
    while not stop.is_set():
        try:
            snapshot = read_snapshot(path)
        except Exception as exc:
            snapshot = Snapshot({}, [], f'{type(exc).__name__}: {exc}')
        try:
            out.get_nowait()
        except queue.Empty:
            pass
        out.put_nowait(snapshot)
        stop.wait(1)


def clip_segment(a, b, radius):
    """Clip a segment to the scope circle; never draw over touch controls."""
    dx,dy=b[0]-a[0],b[1]-a[1]
    aa=dx*dx+dy*dy
    if aa < 1e-12:
        return (a,b) if math.hypot(*a)<=radius else None
    bb=2*(a[0]*dx+a[1]*dy)
    cc=a[0]*a[0]+a[1]*a[1]-radius*radius
    disc=bb*bb-4*aa*cc
    if disc<0:
        return None
    root=math.sqrt(disc)
    low=max(0,(-bb-root)/(2*aa)); high=min(1,(-bb+root)/(2*aa))
    if low>high:
        return None
    return ((a[0]+dx*low,a[1]+dy*low),(a[0]+dx*high,a[1]+dy*high))


def draw_splash(canvas,width,height):
    """Canvas artwork stays sharp on the round display without image dependencies."""
    canvas.delete('all');u=min(width,height)/800;cx=width/2;cy=height/2
    def point(x,y):return cx+(x-400)*u,cy+(y-400)*u
    for i in range(80):
        fraction=i/79
        color='#%02x%02x%02x'%(int(5+8*fraction),int(19+32*fraction),int(38+31*fraction))
        canvas.create_rectangle(0,height*i/80,width,height*(i+1)/80+1,fill=color,outline='')
    for radius,color in [(285,'#204550'),(220,'#275962'),(150,'#337078')]:
        x,y=point(400,370);r=radius*u
        canvas.create_oval(x-r,y-r,x+r,y+r,outline=color,width=2*u)
    # Quiet Sierra silhouettes, framed safely inside the circular screen.
    for vertices,color in [([(100,480),(225,340),(310,425),(405,300),(530,435),(635,365),(710,490)],'#183747'),
                           ([(105,505),(255,420),(350,475),(475,395),(620,475),(695,520)],'#24535b')]:
        canvas.create_polygon(*[n for x,y in vertices for n in point(x,y)],fill=color,outline='')
    canvas.create_line(*point(310,315),*point(400,275),*point(490,315),fill='#83d8ca',width=3*u)
    canvas.create_polygon(*[n for x,y in [(400,242),(413,280),(400,272),(387,280)] for n in point(x,y)],fill='#f3d3a0',outline='')
    for y,text,size,color in [(540,'FISHFINDER',30,'#ebf7f1'),(583,'A little perspective on the sky',13,'#9ed4cd'),(645,'Touch to begin',10,'#8daeb5')]:
        canvas.create_text(*point(400,y),text=text,fill=color,font=('DejaVu Sans',max(9,int(size*u))))


class Display:
    def __init__(self, root, args):
        self.root, self.args = root, args
        root.title('FishFinder Traffic')
        root.geometry(args.geometry)
        root.configure(bg=BG)
        if args.fullscreen:
            # Map at the requested position first, then ask the window manager
            # to fullscreen on that monitor. Wayland may require a compositor rule.
            root.after(350,lambda:root.attributes('-fullscreen',True))
        self.canvas=tk.Canvas(root,bg=BG,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Button-1>',self.tap)
        root.bind('<Escape>',lambda event:self.close())
        root.bind('f',lambda event:root.attributes('-fullscreen',not root.attributes('-fullscreen')))
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.stop=threading.Event(); self.out=queue.Queue(maxsize=1)
        self.snapshot=Snapshot({},[])
        self.config=settings.load()
        self.radius_nm=args.range if args.range is not None else self.config['default_range']
        self.last_touch=time.monotonic(); self.idle=False
        self.setup_panel=None; self.update_status=''
        global TRAIL_AGE
        self.projection_seconds=self.config['horizon_minutes']*60
        TRAIL_AGE=self.config['trail_seconds']
        self.selected=None; self.hits=[]; self.buttons=[]
        self.exit_pending=False
        self.catalog=AirportCatalog(args.airports)
        self.airport_selected=None; self.airport_runways=False; self.airport_page=0
        self.airports_visible=self.config['airports_visible']; self.airport_hits=[]; self.airport_buttons=[]
        self.airport_query=None; self.airport_query_time=0.0; self.near_airports=[]
        self.anchor=None; self.last_own=None
        self.map_heading=0.0
        self.worker=None
        self.demo_initialized=False
        if not args.demo:
            self.worker=threading.Thread(target=reader,args=(self.stop,self.out,args.db),daemon=True,name='database-reader')
            self.worker.start()
        self.splash_until=time.monotonic()+getattr(args,"splash_seconds",0)
        self.tick()

    def close(self):
        self.stop.set()
        self.root.destroy()

    def text(self,x,y,text,fill=WHITE,size=12,**kwargs):
        return self.canvas.create_text(self.cx+(x-400)*self.unit,self.cy+(y-400)*self.unit,
            text=text,fill=fill,font=('DejaVu Sans',max(9,int(size*self.unit))),**kwargs)

    def rect(self,x1,y1,x2,y2,**kwargs):
        return self.canvas.create_rectangle(self.cx+(x1-400)*self.unit,self.cy+(y1-400)*self.unit,
            self.cx+(x2-400)*self.unit,self.cy+(y2-400)*self.unit,**kwargs)

    def line(self,a,b,color,**kwargs):
        a,b=rotate(a,self.map_heading),rotate(b,self.map_heading)
        clipped=clip_segment(a,b,self.radius_nm)
        if clipped:
            aa,bb=clipped
            self.canvas.create_line(self.cx+aa[0]*self.pixels,self.cy-aa[1]*self.pixels,
                self.cx+bb[0]*self.pixels,self.cy-bb[1]*self.pixels,fill=color,**kwargs)

    def tick(self):
        if self.args.demo:
            self.snapshot=demo_snapshot(self.args.no_ownship)
        else:
            try:
                self.snapshot=self.out.get_nowait()
            except queue.Empty:
                pass
        if (not self.demo_initialized and self.snapshot.receiver
                and self.snapshot.receiver[2].startswith("DEMO:")):
            self.airports_visible=True
            if self.args.range is None:self.radius_nm=20
            self.demo_initialized=True
        if time.monotonic()<self.splash_until:
            draw_splash(self.canvas,self.canvas.winfo_width(),self.canvas.winfo_height())
        else:self.draw()
        self.root.after(FRAME_MS,self.tick)

    def draw(self):
        c=self.canvas;c.delete('all')
        w,h=c.winfo_width(),c.winfo_height()
        self.unit=max(0.1,min(w,h)/800); self.cx=w/2;self.cy=h/2
        radius=398*self.unit;self.pixels=radius/self.radius_nm
        self.hits=[]; self.buttons=[];now=time.time()
        self.idle=bool(self.config['idle_seconds'] and time.monotonic()-self.last_touch>=self.config['idle_seconds'] and
                       not (self.selected or self.airport_selected or self.exit_pending or self.setup_panel))
        snap=self.snapshot
        histories=active_histories(snap.reports,now)
        if self.config['own_tail']:
            histories={k:ps for k,ps in histories.items() if self.config['own_tail'] not in
                [(snap.labels or {}).get(k,k).upper().split(' / ')[0], (snap.labels or {}).get(k,k).upper().split(' / ')[-1]]}
        own=[p for p in snap.ownship if 0<=now-p.time<=TRAIL_AGE]
        fix=own[-1] if own and now-own[-1].time<=OWN_AGE and not snap.error else None
        if fix:
            origin=(fix.lat,fix.lon);self.last_own=origin
            ov=velocity(own)
            mode='OWN GPS · NORTH UP'
        else:
            ov=None
            if self.last_own:
                origin=self.last_own;mode='NO OWN GPS · LAST FIX CENTER'
            elif self.anchor:
                origin=self.anchor;mode='NO OWN GPS · ESTIMATED CENTER'
            elif histories:
                latest=[ps[-1] for ps in histories.values()]
                # Spherical mean handles the date line; never call this ownship.
                xx=sum(math.cos(math.radians(p.lat))*math.cos(math.radians(p.lon)) for p in latest)
                yy=sum(math.cos(math.radians(p.lat))*math.sin(math.radians(p.lon)) for p in latest)
                zz=sum(math.sin(math.radians(p.lat)) for p in latest)
                origin=(math.degrees(math.atan2(zz,math.hypot(xx,yy))),math.degrees(math.atan2(yy,xx)))
                self.anchor=origin;mode='NO OWN GPS · ESTIMATED CENTER'
            else:
                origin=None;mode='WAITING FOR POSITION DATA'
        own_heading=None if ov is None or math.hypot(*ov)<1e-10 else math.degrees(math.atan2(ov[0],ov[1]))%360
        self.map_heading=own_heading if self.config['orientation']=='track-up' and own_heading is not None else 0.0
        if fix:mode='OWN GPS · '+('TRACK UP' if self.config['orientation']=='track-up' and own_heading is not None else 'NORTH UP')
        for fraction in (0.25,0.5,0.75,1):
            r=radius*fraction
            c.create_oval(self.cx-r,self.cy-r,self.cx+r,self.cy+r,outline='#285449',width=1)
            self.text(580 if not self.idle and fraction in (0.5,0.75) else 426,400-398*fraction+13,f'{self.radius_nm*fraction:g} NM',fill=MUTED,size=9,anchor='w')
        c.create_line(self.cx-radius,self.cy,self.cx+radius,self.cy,fill='#112921')
        c.create_line(self.cx,self.cy-radius,self.cx,self.cy+radius,fill='#112921')
        for label,bearing in [('N',0),('E',90),('S',180),('W',270)]:
            vector=rotate((math.sin(math.radians(bearing)),math.cos(math.radians(bearing))),self.map_heading)
            self.text(400+378*vector[0],400-378*vector[1],label,fill=WHITE,size=12)
        outside=0; infos={}
        self.airport_origin=origin; self.airport_fix=fix
        self.airport_track=None if ov is None or math.hypot(*ov)<1e-10 or not fix or fix.speed<5 else math.degrees(math.atan2(ov[0],ov[1]))%360
        self.airport_hits=[]
        if origin and self.airports_visible:
            key=(round(origin[0],3),round(origin[1],3),self.radius_nm)
            query_now=time.monotonic()
            if key != self.airport_query or query_now-self.airport_query_time>=AIRPORT_REFRESH_SECONDS:
                # Slightly wider cache envelope; final clipping uses exact current origin.
                self.near_airports=self.catalog.nearby(origin,self.radius_nm+0.2,xy)
                self.airport_query=key;self.airport_query_time=query_now
            for _,airport,_ in self.near_airports:
                pos=rotate(xy(airport['lat'],airport['lon'],origin),self.map_heading)
                if math.hypot(*pos)>self.radius_nm: continue
                x,y=self.cx+pos[0]*self.pixels,self.cy-pos[1]*self.pixels
                sz=5*self.unit
                c.create_rectangle(x-sz,y-sz,x+sz,y+sz,outline=BLUE,fill='#10253d',width=2)
                self.airport_hits.append((x,y,airport['ident']))
            # Labels nearest first, with collision avoidance and circular clipping.
            boxes=[]
            # Reserve the existing traffic symbol and label areas before airport labels.
            for tail,history in histories.items():
                pos=rotate(xy(history[-1].lat,history[-1].lon,origin),self.map_heading)
                if math.hypot(*pos)>self.radius_nm: continue
                tx,ty=self.cx+pos[0]*self.pixels,self.cy-pos[1]*self.pixels
                text=(snap.labels or {}).get(tail,tail)+(' · OLD' if now-history[-1].time>10 else '')
                tw=len(text)*7*self.unit
                left=tx-12*self.unit-tw if pos[0]>=0 else tx+12*self.unit
                boxes.extend([(left,ty-20*self.unit,left+tw,ty),(tx-10*self.unit,ty-10*self.unit,tx+10*self.unit,ty+10*self.unit)])
            for x,y,ident in self.airport_hits:
                airport=self.catalog.airports[ident]
                label=airport['code'] if self.idle else airport['code']+' · '+airport['name'][:18]
                if not self.idle and len(airport['name'])>18: label+='…'
                width=len(label)*5.3*self.unit
                side=-1 if x>=self.cx else 1
                left=x-10*self.unit-width if side<0 else x+10*self.unit
                top=y+7*self.unit; box=(left,top,left+width,top+13*self.unit)
                corners=[(box[a],box[b]) for a in (0,2) for b in (1,3)]
                if any(math.hypot(px-self.cx,py-self.cy)>radius-5*self.unit for px,py in corners): continue
                if any(box[0]<b[2] and box[2]>b[0] and box[1]<b[3] and box[3]>b[1] for b in boxes): continue
                c.create_text(left,top,text=label,anchor='nw',fill=BLUE,font=('DejaVu Sans',max(9,int(9*self.unit))),tags='map-label')
                boxes.append(box)
        if origin:
            if fix:
                for a,b in zip(own,own[1:]):
                    self.line(xy(a.lat,a.lon,origin),xy(b.lat,b.lon,origin),WHITE,width=2,tags="ownship-trail")
                # Shape points forward; north-up rotates it to true track.
                angle=(own_heading or 0)-self.map_heading
                shape=[rotate((x,y),-angle) for x,y in [(0,12),(-8,-10),(0,-5),(8,-10)]]
                c.create_polygon(*[n for x,y in shape for n in (self.cx+x*self.unit,self.cy-y*self.unit)],outline=WHITE,fill=BG,width=2)
                if ov is not None:
                    self.line((0,0),(ov[0]*self.projection_seconds,ov[1]*self.projection_seconds),WHITE,dash=(4,5),width=1,tags="ownship-projection")
            else:
                c.create_oval(self.cx-5*self.unit,self.cy-5*self.unit,self.cx+5*self.unit,self.cy+5*self.unit,outline=MUTED)
                if not self.idle: self.text(400,420,'REFERENCE',fill=MUTED,size=9)
            for tail,history in histories.items():
                p=history[-1];pos=xy(p.lat,p.lon,origin);tv=velocity(history);age=max(0,now-p.time)
                if fix:
                    color,reason,cpa=assess(pos,tv,ov,p.speed,age>10)
                else:
                    color,reason,cpa=GREEN,'No ownship fix: assessment unavailable',None
                separated=bool(fix and self.config['vertical_filter'] and vertical_clear(history,own,self.config['vertical_threshold_ft'],HORIZON))
                if separated:
                    color=MUTED;reason=f'Observed vertical-rate model: beyond {self.config["vertical_threshold_ft"]:,} ft over projection'
                if not fix:
                    reason+=' (green is display-only)'
                heading=None if tv is None or math.hypot(*tv)<1e-10 else math.degrees(math.atan2(tv[0],tv[1]))%360
                if p.estimated: reason+=' · Estimated position from Stratux'
                infos[tail]=(p,color,reason,cpa,heading,age,math.hypot(*pos),fix)
                if math.hypot(*pos)>self.radius_nm:
                    outside+=1;continue
                # Bound Tk canvas work while preserving the full stored history.
                step=max(1,math.ceil(len(history)/90))
                trail=history[::step]
                if trail[-1]!=p:
                    trail.append(p)
                coords=[xy(q.lat,q.lon,origin) for q in trail]
                for i,(a,b) in enumerate(zip(coords,coords[1:])):
                    uncertain=any(q.estimated for q in history if trail[i].time<=q.time<=trail[i+1].time)
                    self.line(a,b,ESTIMATED if uncertain else color,width=2,**({'dash':(3,4)} if uncertain else {}))
                if tv is not None:
                    end=(pos[0]+tv[0]*self.projection_seconds,pos[1]+tv[1]*self.projection_seconds)
                    self.line(pos,end,ESTIMATED if p.estimated else color,dash=(5,4),width=1,arrow=tk.LAST)
                screen_pos=rotate(pos,self.map_heading)
                x,y=self.cx+screen_pos[0]*self.pixels,self.cy-screen_pos[1]*self.pixels
                sz=7*self.unit
                blink=color==RED and int(now*2)%2==0
                c.create_polygon(x,y-sz,x+sz,y,x,y+sz,x-sz,y,fill=BG if separated else WHITE if blink else color,outline=color,width=2)
                label=(snap.labels or {}).get(tail,tail)+(' · EST' if p.estimated else '')+(' · OLD' if age>10 else '')
                # Keep the label inside the scope even near its perimeter.
                side=-1 if screen_pos[0]>=0 else 1
                c.create_text(x+side*12*self.unit,y-10*self.unit,text=label,anchor='e' if side<0 else 'w',
                    fill=color,font=('DejaVu Sans',max(9,int(10*self.unit))),tags='map-label')
                self.hits.append((x,y,tail))
        overlay_start=len(c.find_all())
        self.rect(215,50,585,131,fill=BG,outline='')
        self.text(400,68,'FISHFINDER'+(' · DEMO' if snap.demo or (snap.receiver and snap.receiver[2].startswith('DEMO:')) else ''),size=17)
        self.text(400,96,mode,fill=WHITE if fix else YELLOW,size=12)
        self.text(400,119,f'{self.config["horizon_minutes"]} min · purple dashed = estimated · gray = distant',fill=MUTED,size=10)
        self.rect(318,158,482,185,fill='#10253d',outline=BLUE)
        airport_status='Airports unavailable' if self.catalog.error else 'Airports ON' if self.airports_visible else 'Airports OFF'
        self.text(400,171,airport_status,fill=BLUE,size=10)
        self.buttons.append((318,158,482,185,self.toggle_airports))
        if snap.error:
            self.text(400,450,'DATABASE UNAVAILABLE',fill=RED,size=15)
            self.text(400,476,snap.error,fill=MUTED,size=10,width=380*self.unit)
        elif not histories:
            self.text(400,470,'No recent aircraft reports',fill=MUTED,size=13)
        footer=f'{len(histories)} targets · {outside} outside range'
        if fix:
            footer+=f' · OWN {fix.altitude:,.0f} ft / {fix.speed:.0f} kt' if fix.altitude is not None else f' · OWN altitude unavailable / {fix.speed:.0f} kt'
        self.rect(230,669,570,696,fill=BG,outline='')
        self.text(400,683,footer,fill=MUTED,size=10)
        for i,scale in enumerate((2,5,10,20)):
            x=269+i*87
            self.rect(x-38,699,x+38,743,fill='#17372d' if scale==self.radius_nm else '#0a1814',outline=GREEN if scale==self.radius_nm else '#345247',width=2)
            self.text(x,721,f'{scale} NM',size=12)
            self.buttons.append((x-38,699,x+38,743,lambda s=scale:self.set_range(s)))
        self.rect(340,750,460,790,fill='#2e1718',outline=RED,width=2)
        self.text(400,770,'Exit',size=13)
        self.buttons.append((340,750,460,790,self.request_exit))
        if not fix:
            self.rect(302,631,498,657,fill='#10251f',outline='#345247')
            self.text(400,644,'Recenter traffic',size=10)
            self.buttons.append((302,631,498,657,self.recenter))
        self.rect(318,190,482,221,fill='#10251f',outline='#345247')
        self.text(400,205,'Setup',size=11)
        self.buttons.append((318,190,482,221,self.open_setup))
        if self.idle:
            # Main overlay controls are drawn last. Remove them without affecting map graphics.
            for item in c.find_all()[overlay_start:]: c.delete(item)
            self.buttons=[]
        if self.idle and not fix:
            self.text(400,96,'NO OWN GPS · reference center',fill=YELLOW,size=12)
        if not snap.demo:
            receiver=snap.receiver
            message='Waiting for collector...'
            if receiver and 0<=now-receiver[0]<=15:
                message='' if receiver[1] else receiver[2]
            if message:
                self.rect(195,365,605,435,fill='#071710',outline=YELLOW)
                self.text(400,400,message,fill=YELLOW,size=16,width=390*self.unit)
        if self.selected:
            self.details(infos.get(self.selected))
        if self.airport_selected:
            self.airport_details()
        if self.exit_pending:
            self.rect(210,285,590,515,fill='#071710',outline=WHITE,width=2)
            self.text(400,326,'Close traffic display?',size=19)
            self.text(400,376,'The collector keeps running.',fill=MUTED,size=13)
            self.rect(245,435,390,485,fill='#183b2d',outline=GREEN,width=2)
            self.text(318,460,'Cancel',size=14)
            self.rect(410,435,555,485,fill='#3b181b',outline=RED,width=2)
            self.text(482,460,'Exit',size=14)

    def toggle_airports(self):
        self.airports_visible=not self.airports_visible;self.draw()

    def airport_action(self,action):
        if action=='close': self.airport_selected=None
        elif action=='view': self.airport_runways=not self.airport_runways;self.airport_page=0
        elif action=='next': self.airport_page+=1
        elif action=='prev': self.airport_page=max(0,self.airport_page-1)
        self.draw()

    def airport_details(self):
        a=self.catalog.airports[self.airport_selected]
        self.airport_buttons=[]
        self.rect(176,205,624,620,fill='#07131f',outline=BLUE,width=2)
        self.text(400,233,a['code'],fill=BLUE,size=20)
        self.text(400,264,a['name'],size=12,width=420*self.unit)
        self.text(400,594,'Reference only — verify with current charts',fill=YELLOW,size=10)
        updated,stale=freshness_label(self.catalog.date)
        self.text(400,610,updated,fill=YELLOW if stale else MUTED,size=9)
        if self.airport_runways:
            self.draw_runways(a)
        else:
            altitude=a.get('elevation_ft') or 'unknown'
            distance=math.hypot(*xy(a['lat'],a['lon'],self.airport_origin)) if self.airport_origin else None
            self.text(400,297,f"Elevation: {altitude} ft MSL",size=12)
            label='ownship' if self.airport_fix else 'reference (no own GPS)'
            self.text(400,321,f'Range: {distance:.2f} NM to {label}' if distance is not None else 'Range unavailable',size=11)
            rows=[]
            for r in a.get('runways',[]):
                status=' · CLOSED in dataset' if r.get('closed')=='1' else ''
                rows.append(f"RWY {r.get('le_ident') or '?'} / {r.get('he_ident') or '?'} · {r.get('length_ft') or '?'} × {r.get('width_ft') or '?'} ft · {r.get('surface') or '?'}{status}")
            for f in a.get('frequencies',[]):
                rows.append(f"{f.get('type') or 'Radio'}: {f.get('frequency_mhz') or '?'} MHz · {f.get('description') or ''}")
            if not rows: rows=['No runway or frequency details in dataset']
            pages=max(1,math.ceil(len(rows)/6)); self.airport_page=min(self.airport_page,pages-1)
            for i,line in enumerate(rows[self.airport_page*6:(self.airport_page+1)*6]):
                self.text(400,352+i*26,line if len(line)<=64 else line[:63]+'…',size=10,width=420*self.unit)
            self.text(400,510,f'Page {self.airport_page+1}/{pages}',fill=MUTED,size=9)
            self.airport_button(210,525,295,568,'Prev','prev',enabled=self.airport_page>0)
            self.airport_button(505,525,590,568,'Next','next',enabled=self.airport_page<pages-1)
        if self.airport_runways:
            self.airport_button(210,525,295,568,'Prev','prev',enabled=False)
            self.airport_button(505,525,590,568,'Next','next',enabled=False)
        self.airport_button(303,525,395,568,'Details' if self.airport_runways else 'Runways','view')
        self.airport_button(405,525,497,568,'Close','close')

    def airport_button(self,x1,y1,x2,y2,label,action,enabled=True):
        self.rect(x1,y1,x2,y2,fill='#10253d' if enabled else '#111b24',outline=BLUE if enabled else '#35434f')
        self.text((x1+x2)/2,(y1+y2)/2,label,size=11,fill=WHITE if enabled else '#63717c')
        if enabled:
            self.airport_buttons.append((x1,y1,x2,y2,action))

    def draw_runways(self,a):
        track=self.airport_track or 0
        self.text(400,296,f'TRACK UP · {track:.0f}° true' if self.airport_track is not None else 'NORTH UP · track unavailable',fill=BLUE,size=11)
        segments=runway_segments(a,xy)
        if not segments:
            self.text(400,400,'No usable runway geometry',fill=MUTED,size=13)
            return
        # Center layout on its own bounding box; this is an airport diagram, not a moving map.
        rotated=[(r,rotate(p,track),rotate(q,track),schematic) for r,p,q,schematic in segments]
        points=[p for _,a,b,_ in rotated for p in (a,b)]
        mid=((min(p[0] for p in points)+max(p[0] for p in points))/2,(min(p[1] for p in points)+max(p[1] for p in points))/2)
        scale=min(300/max(0.01,max(p[0] for p in points)-min(p[0] for p in points)),150/max(0.01,max(p[1] for p in points)-min(p[1] for p in points)))
        def screen(p): return 400+(p[0]-mid[0])*scale,405-(p[1]-mid[1])*scale
        label_boxes=[]
        for r,p,q,schematic in rotated:
            x1,y1=screen(p);x2,y2=screen(q)
            color=MUTED if r.get('closed')=='1' else BLUE
            opts=dict(fill=color,width=5*self.unit)
            if schematic: opts['dash']=(5,4)
            self.canvas.create_line(self.cx+(x1-400)*self.unit,self.cy+(y1-400)*self.unit,self.cx+(x2-400)*self.unit,self.cy+(y2-400)*self.unit,**opts)
            for x,y,label in [(x1,y1-12,r.get('le_ident') or '?'),(x2,y2+12,r.get('he_ident') or '?')]:
                for shift in (0,-16,16,-32,32):
                    yy=max(315,min(490,y+shift));ww=len(label)*8
                    box=(x-ww/2,yy-7,x+ww/2,yy+7)
                    if not any(box[0]<b[2] and box[2]>b[0] and box[1]<b[3] and box[3]>b[1] for b in label_boxes):
                        break
                self.text(x,yy,label,size=10,fill=color);label_boxes.append(box)
        n=rotate((0,1),track)
        x,y=584,333
        self.canvas.create_line(self.cx+(x-400)*self.unit,self.cy+(y-400)*self.unit,self.cx+(x+n[0]*19-400)*self.unit,self.cy+(y-n[1]*19-400)*self.unit,fill=WHITE,arrow=tk.LAST)
        self.text(x+n[0]*29,y-n[1]*29,'N',size=10)
        note='SCHEMATIC: dashed runways centered; positions unknown' if any(v[3] for v in rotated) else 'Runway endpoints · no taxiways or obstacles'
        if any(v[0].get('closed')=='1' for v in rotated): note+=' · gray = CLOSED in dataset'
        if any(v[0].get('_aligned') for v in rotated): note='Parallel layout uses published true heading · schematic'
        self.text(400,501,note,fill=YELLOW if any(v[3] for v in rotated) else MUTED,size=9,width=415*self.unit)

    def request_exit(self):
        self.exit_pending=True
        self.draw()

    def set_range(self,value):
        self.radius_nm=value;self.draw()

    def recenter(self):
        self.anchor=None;self.last_own=None;self.draw()

    def details(self,info):
        self.rect(176,209,624,614,fill='#071710',outline=WHITE,width=2)
        title=(self.snapshot.labels or {}).get(self.selected,self.selected)
        self.text(400,241,title,size=18 if len(title)>14 else 22)
        if info:
            p,color,reason,cpa,heading,age,distance,fix=info
            lines=[f'Altitude: {p.altitude:,.0f} ft · reported' if p.altitude is not None else 'Altitude: unavailable',f'Ground speed: {p.speed:.0f} kt',
                'Track: unavailable' if heading is None else f'Track: {heading:.0f}° true · estimated',
                f'Range: {distance:.2f} NM '+('to ownship' if fix else 'to reference'),
                f'Report age: {age:.1f} seconds']
            if fix and fix.altitude is not None:
                lines.append(f'Ownship altitude: {fix.altitude:,.0f} ft · GPS')
            if cpa:
                lines.append(f'Closest pass: {cpa[1]:.2f} NM in {cpa[0]/60:.1f} min')
            for i,line in enumerate(lines):
                self.text(400,285+i*29,line,size=12)
            self.text(400,513,reason,fill=color,size=12,width=390*self.unit)
            self.text(400,549,'Vertical styling requires fresh matching pressure altitudes.\nUnknown altitude or rate retains proximity colors.',fill=MUTED,size=10)
        else:
            self.text(400,390,'Target no longer has recent data',fill=YELLOW,size=12)
        self.rect(322,571,478,602,fill='#183b2d',outline=GREEN)
        self.text(400,587,'Close',size=12)

    def open_setup(self):
        self.setup_panel=setup_screen.Setup(self)

    def apply_settings(self,values):
        self.config=settings.save(values)
        self.radius_nm=self.config['default_range']; self.airports_visible=self.config['airports_visible']
        global TRAIL_AGE
        self.projection_seconds=self.config['horizon_minutes']*60; TRAIL_AGE=self.config['trail_seconds']
        self.last_touch=time.monotonic(); self.draw()

    def tap(self,event):
        if time.monotonic()<self.splash_until:
            self.splash_until=0;self.last_touch=time.monotonic();self.draw();return
        self.last_touch=time.monotonic()
        if self.idle:
            self.idle=False; self.draw(); return  # Wake touch must not activate a hidden control.
        x=(event.x-self.cx)/self.unit+400;y=(event.y-self.cy)/self.unit+400
        if self.exit_pending:
            if 410<=x<=555 and 435<=y<=485:
                self.close()
            elif 245<=x<=390 and 435<=y<=485:
                self.exit_pending=False
                self.draw()
            return
        if self.airport_selected:
            for x1,y1,x2,y2,action in self.airport_buttons:
                if x1<=x<=x2 and y1<=y<=y2:
                    self.airport_action(action);return
            if not (176<=x<=624 and 205<=y<=620):
                self.airport_selected=None;self.draw()
            return
        if self.selected:
            if 322<=x<=478 and 571<=y<=602 or not(176<=x<=624 and 209<=y<=614):
                self.selected=None;self.draw()
            return
        for x1,y1,x2,y2,action in self.buttons:
            if x1<=x<=x2 and y1<=y<=y2:
                action();return
        if self.hits:
            hx,hy,tail=min(self.hits,key=lambda item:math.hypot(event.x-item[0],event.y-item[1]))
            if math.hypot(event.x-hx,event.y-hy)<=28*self.unit:
                self.selected=tail;self.draw();return
        if self.airport_hits:
            hx,hy,ident=min(self.airport_hits,key=lambda item:math.hypot(event.x-item[0],event.y-item[1]))
            if math.hypot(event.x-hx,event.y-hy)<=28*self.unit:
                self.airport_selected=ident;self.airport_page=0;self.airport_runways=False;self.draw()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='/var/local/FishFinder/flying_objects.db')
    parser.add_argument('--airports',default=str(Path(__file__).resolve().parent/'airports.json'),help='Offline airport cache; defaults beside display script')
    parser.add_argument('--fullscreen',action='store_true')
    parser.add_argument('--geometry',default='800x800',
        help='Initial Tk window size/position, e.g. 800x800+1920+0 on X11')
    demo_options=parser.add_mutually_exclusive_group()
    demo_options.add_argument('--demo',action='store_true',help='Read the moving collector demo database')
    demo_options.add_argument('--sample-demo',action='store_true',help='Legacy display-only fixed sample targets')
    parser.add_argument('--no-ownship',action='store_true',help='Demo without an ownship fix')
    parser.add_argument('--range',type=int,choices=(2,5,10,20),default=None)
    parser.add_argument('--splash-seconds',type=float,default=3,help='Startup splash duration; 0 disables, tap dismisses')
    args=parser.parse_args()
    if not math.isfinite(args.splash_seconds) or args.splash_seconds<0:parser.error('Splash duration must be finite and nonnegative')
    if args.demo and args.db=='/var/local/FishFinder/flying_objects.db':
        args.db='/var/local/FishFinder/demo_objects.db'
    # Internally this flag remains the legacy sample renderer.
    args.demo=args.sample_demo
    root=tk.Tk();Display(root,args);root.mainloop()


if __name__=='__main__':
    main()
