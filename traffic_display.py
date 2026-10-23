#!/usr/local/Fishfinder/.venv/bin/python3
"""Touch traffic plot for an 800x800 round display. Read-only SQLite client.

python3 traffic_display.py --demo
python3 traffic_display.py --fullscreen
All GUI operations stay on Tk's main thread; database reads run separately.
"""

# READING THIS FILE: the interactive traffic display.
#
# This program does not receive aircraft directly. A background reader obtains
# recent database rows and gives the Tkinter window a snapshot. Display.tick()
# is the repeating heartbeat; Display.draw() turns the newest snapshot into one
# picture. Only the window's main thread touches Tkinter widgets.
#
# The first group of functions deals with numbers and geometry, not pixels.
# Latitude/longitude become local east/north distances in nautical miles.
# Velocity is east/north distance per SECOND, although displayed speed is knots
# (nautical miles per HOUR). Altitudes are feet. Do not compare pressure altitude
# with GPS altitude as though they share the same reference.
#
# A trail joins past reports. A projected line extends the current velocity;
# it does not predict a planned turn. The five-minute proximity assessment is
# separate from the user-selectable length of that projected line. Unknown or
# stale data must stay visibly uncertain rather than quietly disappearing.
#
# The Display class holds window state: self means this particular display.
# Its drawing helpers convert the 800-by-800 design into actual screen pixels.
# The tap handlers decide whether a finger selected one target, a crowded group,
# a visible control, or the double-tap gesture that wakes hidden controls.

import argparse
import json
import settings
import demo_ground
import setup_screen
import math
import os
import queue
import sqlite3
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from airport_data import AirportCatalog, BLUE, rotate, runway_segments, freshness_label, airport_color

# Units matter throughout the geometry: Earth radius and horizontal distances are nautical
# miles; HORIZON/ages are seconds; altitudes and vertical thresholds are feet. FRAME_MS is
# milliseconds between requested UI updates.
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


# One timestamped position report. The immutable record keeps coordinates, speed, display
# altitude and separate comparison-altitude metadata together.
@dataclass(frozen=True)
class Point:
    # A dataclass supplies a convenient constructor for these named fields. The type labels
    # describe intended values; validation happens in point(), not automatically because a
    # field says float.
    id: int
    time: float
    lat: float
    lon: float
    speed: float
    altitude: float
    # Keep the source/reference of an altitude comparison with the number itself. An altitude
    # good enough to display is not automatically safe to compare against another source.
    comparison_alt: float = None
    alt_ref: str = None
    estimated: bool = False
    position_age: float = None


# A package of reports, ownship history, identity labels and receiver state handed from the
# reader to the window.
@dataclass
class Snapshot:
    reports: dict
    ownship: list
    error: str = ''
    demo: bool = False
    labels: dict = None
    receiver: tuple = None


# Convert a database value to a finite number; malformed or missing data becomes None.
def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


# Convert a SQLite row to a validated Point. Unknown altitude can remain None, but missing
# position/speed cannot become a plotted point.
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
    # Wrap longitude difference to -180..180 degrees so points on opposite sides of the date
    # line stay close. Trigonometry uses radians, not the degrees shown on maps.
    dl = math.radians((lon - origin[1] + 180) % 360 - 180)
    y = math.sin(dl) * math.cos(b)
    x = math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b) * math.cos(dl)
    hav = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(dl/2)**2
    distance = 2 * EARTH_NM * math.asin(math.sqrt(min(1, max(0, hav))))
    bearing = math.atan2(y, x)
    # Return a pair: positive east is right in a north-up map; positive north is up. Pixel
    # conversion later reverses the vertical sign because screen y grows downward.
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
    # Try the newest earlier observations first so a recent turn is not diluted by an average
    # over the whole trail. Skip nearly identical positions and implausible jumps.
    for previous in reversed(history[:-1]):
        dt = latest.time - previous.time
        if 0.2 <= dt <= 10:
            east, north = xy(latest.lat, latest.lon, (previous.lat, previous.lon))
            distance = math.hypot(east, north)
            # Reject tiny GPS jitter and implausible jumps rather than inventing track.
            if distance >= 0.002 and distance/dt*3600 <= max(600, latest.speed*3):
                # Knots are nautical miles per hour. Divide by 3,600 to multiply this
                # velocity by future seconds without introducing a 3,600-times distance
                # error.
                speed = latest.speed/3600
                return east/distance*speed, north/distance*speed
    return None


# Find when two straight, constant-velocity horizontal tracks pass closest during the five-
# minute horizon; return time and separation.
def closest_approach(relative, relative_velocity):
    # Work in relative motion: imagine ownship stationary and subtract its velocity from the
    # target's. The dot product tells whether their horizontal distance is decreasing. Clamp
    # the nearest time to now..five minutes.
    speed2 = sum(v*v for v in relative_velocity)
    t = 0 if speed2 < 1e-12 else max(0, min(HORIZON, -sum(a*b for a,b in zip(relative, relative_velocity))/speed2))
    return t, math.hypot(relative[0]+relative_velocity[0]*t, relative[1]+relative_velocity[1]*t)


def turn_possible(relative, own_velocity, speed):
    """Can a target at constant speed reach within 1 NM of ownship's path?

    Conservative envelope: instant turn, any direction, no turn-rate limit.
    Minimize the convex distance-minus-reachable-radius function over 5 min.
    """
    # At one future time, compare ownship distance with how far a target could travel after
    # an instantaneous turn.
    def gap(t):
        return math.hypot(relative[0]-own_velocity[0]*t, relative[1]-own_velocity[1]*t) - speed/3600*t
    # Search for the minimum gap between ownship's straight path and the target's reachable
    # circle. This deliberately allows an instantaneous turn; it is a conservative
    # possibility test, not a realistic turn prediction.
    lo, hi = 0.0, HORIZON
    for _ in range(50):
        a, b = (2*lo+hi)/3, (lo+2*hi)/3
        if gap(a) < gap(b):
            hi = b
        else:
            lo = a
    return min(gap(0), gap(HORIZON), gap((lo+hi)/2)) <= 1


# Choose the horizontal proximity color and an explanation. Stale/missing-track data is
# uncertain; red requires being within 1 NM and closing.
def assess(relative, target_velocity, own_velocity, speed, stale=False):
    distance = math.hypot(*relative)
    if stale:
        return YELLOW, 'STALE: proximity assessment unavailable', None
    if own_velocity is None or target_velocity is None:
        return YELLOW, 'Ground track unavailable: proximity uncertain', None
    # The same absolute heading can still produce closing motion if speeds differ. Subtract
    # both east and north components before calculating closest approach.
    rv = (target_velocity[0]-own_velocity[0], target_velocity[1]-own_velocity[1])
    cpa = closest_approach(relative, rv)
    closing = sum(a*b for a,b in zip(relative, rv)) < -1e-6
    # Red has the narrow, explicit rule 'already within 1 NM and closing horizontally'. A
    # future close pass or a possible turn is yellow. This model is advisory and does not
    # know the pilot's intentions.
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
    # Estimate a vertical rate only from enough fresh observed pressure-altitude samples;
    # otherwise return unknown.
    def state(history):
        latest=history[-1]
        if latest.estimated: return None
        if latest.comparison_alt is None or latest.alt_ref != 'pressure': return None
        # A single altitude cannot establish a climb/descent rate. Require several recent
        # samples with the same pressure reference; estimated points are not used to justify
        # removing a target.
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
    # Compare separation now and at the end of the five-minute constant-rate interval. The
    # signs must agree, and both separations must exceed the threshold. Crossing levels would
    # fail this test.
    delta=t[0]-o[0]; end=delta+(t[1]-o[1])*horizon
    return delta*end>0 and min(abs(delta),abs(end))>threshold


# Open the collector database read-only, read recent histories and labels, then close the
# connection. The display does not own database cleanup.
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


# Keep recent trail samples, then discard targets whose newest report is too old to be
# active.
def active_histories(reports, now):
    histories={k:[p for p in ps if 0<=now-p.time<=TRAIL_AGE] for k,ps in reports.items()}
    return {k:ps for k,ps in histories.items() if ps and now-ps[-1].time<=REPORT_AGE}


def select_ownship(snapshot,histories,config,now):
    """Prefer fresh observed ADS-B for the configured tail; never extrapolated fixes."""
    tail=config['own_tail'];matching={k for k in histories if tail and tail in
        [name.strip().upper() for name in (snapshot.labels or {}).get(k,k).split(' / ')]}
    candidates=[]
    for key in matching:
        observed=[p for p in histories[key] if not p.estimated and
                  (p.position_age is None or 0<=p.position_age<=5)]
        if observed and 0<=now-observed[-1].time<=5:candidates.append(observed)
    adsb=max(candidates,key=lambda ps:ps[-1].time) if candidates else []
    stratux=[p for p in snapshot.ownship if 0<=now-p.time<=TRAIL_AGE]
    if not stratux or now-stratux[-1].time>OWN_AGE:stratux=[]
    if config['ownship_source']=='adsb-first':own,source=(adsb,'ADSB') if adsb else (stratux,'STRATUX GPS')
    else:own,source=(stratux,'STRATUX GPS') if stratux else (adsb,'ADSB')
    return {k:v for k,v in histories.items() if k not in matching},own,source


# Make the older fixed display-only sample scene. This differs from the moving collector demo
# database.
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


# Poll the database in a background thread and replace the queued snapshot with the newest
# one. Convert read errors into displayable status.
def reader(stop, out, path):
    while not stop.is_set():
        try:
            snapshot = read_snapshot(path)
        except Exception as exc:
            # A Snapshot carries values, not Tk widgets. Reader errors become status text in
            # a snapshot, allowing the UI thread to remain alive and responsive.
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
    # Map splash artwork coordinates to the current screen dimensions.
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


# All window state and drawing/touch behavior for one round FishFinder screen.
class Display:
    # Construct the window and touch bindings, load settings/data paths, prepare queues/map
    # state, then start the repeating update.
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
        # Create a stop signal and a one-slot handoff queue. Keeping only one snapshot favors
        # current state over a backlog of already-outdated pictures.
        self.stop=threading.Event(); self.out=queue.Queue(maxsize=1)
        self.snapshot=Snapshot({},[])
        # Load validated settings once for this window. self.config holds the choices;
        # self.radius_nm and similar fields hold the currently applied display state.
        self.config=settings.load()
        try:self.version=json.loads((Path(__file__).resolve().parent/'VERSION.json').read_text())['version']
        except (OSError,ValueError,KeyError):self.version='unknown'
        # Check permissions under the real current user. Report trouble in Setup; do not make
        # everything world-writable or silently change ownership.
        from fs_checks import write_problem
        self.permission_issues=[issue for issue in (write_problem(settings.SETTINGS_PATH,atomic=True),write_problem(args.airports,atomic=True)) if issue]
        self.radius_nm=args.range if args.range is not None else self.config['default_range']
        self.last_touch=time.monotonic(); self.idle=False
        self.touch_debug=getattr(args,"touch_debug",False);self.touch_mark=None
        if self.touch_debug:print(f"TOUCH DEBUG script={Path(__file__).resolve()} DISPLAY={os.environ.get('DISPLAY','')} requested_geometry={args.geometry}",flush=True)
        self.setup_panel=None; self.update_status=''
        global TRAIL_AGE
        self.projection_seconds=self.config['horizon_minutes']*60
        TRAIL_AGE=self.config['trail_seconds']
        self.target_choices=[]; self.choice_page=0; self.choice_buttons=[]
        self.selected=None; self.hits=[]; self.buttons=[]
        self.exit_pending=False
        self.catalog=AirportCatalog(args.airports)
        from update_airports import AutomaticUpdates
        self.airport_updates=None if args.demo else AutomaticUpdates(args.airports)
        self.airport_selected=None; self.airport_runways=False; self.airport_page=0
        self.airports_visible=self.config['airports_visible']; self.airport_hits=[]; self.airport_buttons=[]
        self.airport_query=None; self.airport_query_time=0.0; self.near_airports=[]
        self.anchor=None; self.last_own=None
        self.map_heading=0.0
        self.worker=None
        self.demo_initialized=False
        # First-time CLI opt-in preserves the old demo-map launch behavior.
        # Once saved in Setup, the user's on/off preference wins on restart.
        if getattr(args,"demo_map",False) and not settings.explicit('ground_map'):
            self.config['ground_map']=True
        from world_ground import DEFAULT_PATH
        from tile_ground import DEFAULT_RICH_PATH
        selected_map=getattr(args,'map_data',None) or os.environ.get('FISHFINDER_MAP_DATA')
        self.ground_path=(demo_ground.PACK if getattr(args,'demo_map',False) else
                          Path(selected_map) if selected_map else DEFAULT_RICH_PATH if DEFAULT_RICH_PATH.is_file() else
                          DEFAULT_PATH if DEFAULT_PATH.is_file() else demo_ground.PACK)
        self.ground_global=self.ground_path.suffix in ('.sqlite','.pmtiles')
        if selected_map and not getattr(args,'demo_map',False) and not settings.explicit('ground_map'):self.config['ground_map']=True
        self.ground_level=1 if self.config['ground_map'] else 0
        self.ground=None
        self.ground_request_time=0.0
        self.ground_image=None;self.ground_image_state=None;self.ground_seen=None;self.ground_image_time=0.0
        self.ground_request_key=None
        self.ground_labels=()
        # The --demo database mode still uses the normal reader. main() adjusts the
        # legacy/sample-demo flags before constructing Display; the fixed snapshot path is
        # separate from a live collector database.
        if not args.demo:
            self.worker=threading.Thread(target=reader,args=(self.stop,self.out,args.db),daemon=True,name='database-reader')
            self.worker.start()
        self.splash_until=time.monotonic()+getattr(args,"splash_seconds",0)
        self.tick()

    # Signal workers to stop, close the map renderer and destroy the window. Closing the
    # display does not stop the separate collector service.
    def close(self):
        self.stop.set()
        if self.ground:self.ground.close()
        self.root.destroy()

    # Draw text at logical 800-by-800 coordinates, scaled for the actual screen size.
    def text(self,x,y,text,fill=WHITE,size=12,**kwargs):
        return self.canvas.create_text(self.cx+(x-400)*self.unit,self.cy+(y-400)*self.unit,
            text=text,fill=fill,font=('DejaVu Sans',max(9,int(size*self.unit))),**kwargs)

    def rim_attribution(self,text,center_angle=math.pi/4):
        """Readable text along the inside of the lower-right circular rim."""
        font=('DejaVu Sans',max(10,int(10*self.unit)))
        key=(text,font)
        if not hasattr(self,'rim_cache'):self.rim_cache={}
        if key not in self.rim_cache:
            if isinstance(self.root,tk.Misc):
                import tkinter.font as tkfont
                measured=tkfont.Font(root=self.root,font=font)
                widths=[measured.measure(char) for char in text]
            else:widths=[font[1]*(.35 if char==' ' else .6) for char in text]
            self.rim_cache[key]=widths
        widths=self.rim_cache[key]
        radius=390*self.unit;progress=-sum(widths)/2
        for char,width in zip(text,widths):
            phi=center_angle-(progress+width/2)/radius
            if not char.isspace():
                self.canvas.create_text(self.cx+radius*math.cos(phi),self.cy+radius*math.sin(phi),
                    text=char,fill=MUTED,font=font,angle=90-math.degrees(phi),tags='map-attribution')
            progress+=width

    # Draw a rectangle using logical coordinates instead of repeating screen-scaling
    # arithmetic everywhere.
    def rect(self,x1,y1,x2,y2,**kwargs):
        return self.canvas.create_rectangle(self.cx+(x1-400)*self.unit,self.cy+(y1-400)*self.unit,
            self.cx+(x2-400)*self.unit,self.cy+(y2-400)*self.unit,**kwargs)

    # Rotate a local east/north segment, clip it to the circular scope, then draw it in
    # screen pixels.
    def line(self,a,b,color,**kwargs):
        a,b=rotate(a,self.map_heading),rotate(b,self.map_heading)
        clipped=clip_segment(a,b,self.radius_nm)
        if clipped:
            aa,bb=clipped
            self.canvas.create_line(self.cx+aa[0]*self.pixels,self.cy-aa[1]*self.pixels,
                self.cx+bb[0]*self.pixels,self.cy-bb[1]*self.pixels,fill=color,**kwargs)

    def trail_lines(self,points,color,uncertain=None,**kwargs):
        """One Tk polyline per continuous style/run, rather than per report."""
        points=[rotate(p,self.map_heading) for p in points]
        batch=[];style=None
        # Send one continuous batch of trail points to Tkinter. Fewer Canvas objects keep Pi
        # redraws cheaper.
        def flush():
            if len(batch)<4:return
            screen=[]
            for i in range(0,len(batch),2):
                screen.extend((self.cx+batch[i]*self.pixels,self.cy-batch[i+1]*self.pixels))
            self.canvas.create_line(*screen,fill=ESTIMATED if style else color,width=2,
                                    **({'dash':(3,4)} if style else {}),**kwargs)
        for i,(a,b) in enumerate(zip(points,points[1:])):
            newstyle=bool(uncertain and uncertain[i])
            clipped=clip_segment(a,b,self.radius_nm)
            if clipped is None:
                flush();batch=[];style=None;continue
            a,b=clipped
            if batch and (style!=newstyle or math.dist(batch[-2:],a)>1e-8):
                flush();batch=[]
            style=newstyle
            if not batch:batch.extend(a)
            batch.extend(b)
        flush()

    # Receive the newest snapshot/update state, draw a frame, and ask Tkinter to call tick
    # again later. This is not a blocking while loop.
    def tick(self):
        if self.airport_updates:
            result=self.airport_updates.poll()
            if result:
                success,message=result
                print(message,flush=True)
                if success:
                    self.catalog=AirportCatalog(self.args.airports);self.airport_query=None
                    if self.airport_selected not in self.catalog.airports:self.airport_selected=None
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
        # Schedule the next update and return control to Tkinter. Returning is what allows
        # queued touch/button events to run between frames.
        self.root.after(FRAME_MS,self.tick)

    # Build one picture in layers: background, rings, airports/runways, ownship/traffic,
    # labels, controls, popups and persistent attribution.
    def draw(self):
        # Start a new Canvas frame. Drawing order is layering order: later items cover
        # earlier ones. Map processing is elsewhere; this method should mainly issue bounded
        # drawing commands.
        c=self.canvas;c.delete('all')
        w,h=c.winfo_width(),c.winfo_height()
        # Design in an 800-by-800 coordinate system, then scale with unit. cx/cy are the
        # actual center; pixels is how many physical pixels represent one nautical mile at
        # the selected range.
        self.unit=max(0.1,min(w,h)/800); self.cx=w/2;self.cy=h/2
        radius=398*self.unit;self.pixels=radius/self.radius_nm
        self.hits=[]; self.buttons=[];self.label_boxes=[];now=time.time()
        self.label_factor=settings.label_scale(self.config,self.radius_nm)
        self.idle=bool(self.config['idle_seconds'] and time.monotonic()-self.last_touch>=self.config['idle_seconds'] and
                       not (self.exit_pending or self.setup_panel))
        snap=self.snapshot
        # Limit the usable trail and choose an ownship source before drawing. Matching
        # ownship traffic is removed from the ordinary target list so the same aircraft is
        # not shown twice.
        histories=active_histories(snap.reports,now)
        histories,own,self.own_source=select_ownship(snap,histories,self.config,now)
        # Do not keep calling a stale last-known position a current ownship fix. Without a
        # usable fix, choose a reference center and make uncertainty visible.
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
        if fix:mode=self.own_source+' · '+('TRACK UP' if self.config['orientation']=='track-up' and own_heading is not None else 'NORTH UP')
        if self.ground:self.ground.poll()
        # A bundled local demo map is not a worldwide chart. Decide whether this map source
        # applies before drawing it; the separate worldwide archive is handled as global
        # coverage.
        ground_allowed=snap.demo or bool(snap.receiver and snap.receiver[2].startswith("DEMO:")) or self.ground_global
        if ground_allowed and self.ground_level and self.ground is None:
            self.ground=demo_ground.GroundLayer(self.ground_path)
        # Town names are placed after traffic and airports have claimed label space. Their
        # font grows with zoom, but town text yields when it would overlap a more important
        # label.
        if origin and ground_allowed and self.ground and self.ground_level:
            self.draw_ground(origin)
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
            # Look beyond the screen by roughly an extension length. A runway just off-screen
            # may still have a 3 NM centerline extension entering the visible circle.
            extension_margin=3.2 if self.config['runway_extensions'] else .2
            key=(round(origin[0],3),round(origin[1],3),self.radius_nm,extension_margin)
            query_now=time.monotonic()
            if key != self.airport_query or query_now-self.airport_query_time>=AIRPORT_REFRESH_SECONDS:
                # Slightly wider cache envelope; final clipping uses exact current origin.
                self.near_airports=self.catalog.nearby(origin,self.radius_nm+extension_margin,xy)
                self.airport_query=key;self.airport_query_time=query_now
            for _,airport,_ in self.near_airports:
                pos=rotate(xy(airport['lat'],airport['lon'],origin),self.map_heading)
                if self.config['runway_extensions']:
                    offset=xy(airport['lat'],airport['lon'],origin)
                    # Runway endpoints are relative to their airport, while the display uses
                    # offsets relative to ownship/reference. Add the airport offset before
                    # extending. Reject schematic/closed strips.
                    for runway,a,b,schematic in runway_segments(airport,xy):
                        if schematic or runway.get('closed')=='1':continue
                        length=math.dist(a,b)
                        if length<1e-5:continue
                        # Normalize the runway direction to length one. Multiplying it by 3
                        # then means exactly three nautical miles, regardless of the runway's
                        # length or screen zoom.
                        v=((b[0]-a[0])/length,(b[1]-a[1])/length)
                        aa=(offset[0]+a[0],offset[1]+a[1]);bb=(offset[0]+b[0],offset[1]+b[1])
                        self.line((aa[0]-3*v[0],aa[1]-3*v[1]),aa,'#687578',width=1,dash=(4,5),tags='runway-extension')
                        self.line(bb,(bb[0]+3*v[0],bb[1]+3*v[1]),'#687578',width=1,dash=(4,5),tags='runway-extension')
                        self.line(aa,bb,airport_color(airport),width=3*self.unit,tags='runway-strip')
                if math.hypot(*pos)>self.radius_nm:continue
                x,y=self.cx+pos[0]*self.pixels,self.cy-pos[1]*self.pixels;sz=7*self.unit
                c.create_rectangle(x-sz,y-sz,x+sz,y+sz,outline=airport_color(airport),fill=airport_color(airport),width=2)
                self.airport_hits.append((x,y,airport['ident']))
            # Labels nearest first, with collision avoidance and circular clipping.
            # Reserve space for higher-priority symbols/labels. Each box is left, top, right,
            # bottom in pixels. Collision checks keep airport/town names from being painted
            # on top of reserved content.
            boxes=[(self.cx-20*self.unit,self.cy-20*self.unit,self.cx+20*self.unit,self.cy+20*self.unit)] if fix else []
            # Reserve the existing traffic symbol and label areas before airport labels.
            for tail,history in histories.items():
                pos=rotate(xy(history[-1].lat,history[-1].lon,origin),self.map_heading)
                if math.hypot(*pos)>self.radius_nm: continue
                tx,ty=self.cx+pos[0]*self.pixels,self.cy-pos[1]*self.pixels
                text=(snap.labels or {}).get(tail,tail)+(' · OLD' if now-history[-1].time>10 else '')
                tw=len(text)*7*self.unit*self.label_factor
                left=tx-12*self.unit-tw if pos[0]>=0 else tx+12*self.unit
                boxes.extend([(left,ty-20*self.unit*self.label_factor,left+tw,ty),(tx-10*self.unit,ty-10*self.unit,tx+10*self.unit,ty+10*self.unit)])
            for x,y,ident in self.airport_hits:
                airport=self.catalog.airports[ident]
                label=airport['code'] if self.idle else airport['code']+' · '+airport['name'][:18]
                if not self.idle and len(airport['name'])>18: label+='…'
                width=len(label)*6.5*self.unit*self.label_factor
                side=-1 if x>=self.cx else 1
                left=x-10*self.unit-width if side<0 else x+10*self.unit
                top=y+7*self.unit; box=(left,top,left+width,top+16*self.unit*self.label_factor)
                corners=[(box[a],box[b]) for a in (0,2) for b in (1,3)]
                if any(math.hypot(px-self.cx,py-self.cy)>radius-5*self.unit for px,py in corners): continue
                if any(box[0]<b[2] and box[2]>b[0] and box[1]<b[3] and box[3]>b[1] for b in boxes): continue
                c.create_text(left,top,text=label,anchor='nw',fill=airport_color(airport),font=('DejaVu Sans',max(9,int(11*self.unit*self.label_factor))),tags='map-label')
                boxes.append(box)
            self.label_boxes=boxes
        if origin:
            if fix:
                self.hits.append((self.cx,self.cy,'__ownship__'))
                self.trail_lines([xy(p.lat,p.lon,origin) for p in own],WHITE,tags="ownship-trail")
                if ov is not None:
                    self.line((0,0),(ov[0]*self.projection_seconds,ov[1]*self.projection_seconds),WHITE,dash=(4,5),width=1,tags="ownship-projection")
                # Original small aircraft silhouette, drawn above its trail/projection.
                angle=(own_heading or 0)-self.map_heading
                shapes={
                    'high-wing':[(-2,16),(2,16),(3,5),(14,0),(14,-4),(3,-2),(2,-10),
                                 (7,-12),(7,-15),(1,-13),(0,-17),(-1,-13),(-7,-15),
                                 (-7,-12),(-2,-10),(-3,-2),(-14,-4),(-14,0),(-3,5)],
                    'low-wing':[(-2,16),(2,16),(3,0),(14,-4),(13,-8),(3,-5),(2,-11),
                                (7,-13),(6,-15),(1,-13),(0,-17),(-1,-13),(-6,-15),
                                (-7,-13),(-2,-11),(-3,-5),(-13,-8),(-14,-4),(-3,0)],
                    'twin':[(-2,16),(2,16),(3,4),(17,0),(17,-4),(3,-3),(2,-11),
                            (8,-13),(8,-16),(1,-14),(0,-17),(-1,-14),(-8,-16),
                            (-8,-13),(-2,-11),(-3,-3),(-17,-4),(-17,0),(-3,4)]}
                # Choose an original vector airplane outline. Rotate the artwork by ground
                # course relative to map orientation; no external copyrighted aircraft image
                # is loaded.
                style=self.config['ownship_symbol'];outline=shapes[style]
                # Rotate the original ownship airplane outline and convert its points into
                # screen pixels.
                def aircraft_points(points):
                    return [n for x,y in (rotate(p,-angle) for p in points)
                            for n in (self.cx+x*self.unit,self.cy-y*self.unit)]
                c.create_polygon(*aircraft_points(outline),outline=WHITE,fill=WHITE,width=1,tags='ownship-symbol')
                if style=='twin':
                    for side in (-1,1):
                        engine=[(side*7-1.5,7),(side*7+1.5,7),(side*7+1.5,-5),(side*7-1.5,-5)]
                        c.create_polygon(*aircraft_points(engine),outline=WHITE,fill=WHITE,tags='ownship-symbol')
                        c.create_line(*aircraft_points([(side*7-3,8),(side*7+3,8)]),fill=WHITE,width=1,tags='ownship-symbol')
                c.create_polygon(*aircraft_points([(-1.4,9),(1.4,9),(1.5,3),(-1.5,3)]),
                                 outline=BG,fill=BG,tags='ownship-symbol')
            else:
                c.create_oval(self.cx-5*self.unit,self.cy-5*self.unit,self.cx+5*self.unit,self.cy+5*self.unit,outline=MUTED)
                if not self.idle: self.text(400,420,'REFERENCE',fill=MUTED,size=9)
            # For each active aircraft: use its latest position, infer recent movement,
            # decide uncertainty/color, then draw its past trail and straight projected
            # track.
            for tail,history in histories.items():
                p=history[-1];pos=xy(p.lat,p.lon,origin);tv=velocity(history);age=max(0,now-p.time)
                if fix:
                    color,reason,cpa=assess(pos,tv,ov,p.speed,age>10)
                else:
                    color,reason,cpa=GREEN,'No ownship fix: assessment unavailable',None
                clear=bool(fix and vertical_clear(history,own,self.config['vertical_threshold_ft'],HORIZON))
                if clear and self.config['hide_vertical']:continue
                separated=clear and self.config['vertical_filter']
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
                indices=list(range(0,len(history),step))
                if indices[-1]!=len(history)-1:indices.append(len(history)-1)
                trail=[history[i] for i in indices]
                counts=[0]
                for report in history:counts.append(counts[-1]+bool(report.estimated))
                uncertain=[counts[b+1]>counts[a] for a,b in zip(indices,indices[1:])]
                self.trail_lines([xy(q.lat,q.lon,origin) for q in trail],color,uncertain)
                if tv is not None:
                    end=(pos[0]+tv[0]*self.projection_seconds,pos[1]+tv[1]*self.projection_seconds)
                    self.line(pos,end,ESTIMATED if p.estimated else color,dash=(5,4),width=1,arrow=tk.LAST)
                screen_pos=rotate(pos,self.map_heading)
                x,y=self.cx+screen_pos[0]*self.pixels,self.cy-screen_pos[1]*self.pixels
                sz=7*self.unit
                blink=color==RED and int(now*2)%2==0
                c.create_polygon(x,y-sz,x+sz,y,x,y+sz,x-sz,y,fill=BG if separated else WHITE if blink else color,outline=color,width=2)
                # Readable registration/callsign comes from the identity table, not the
                # internal ICAO key. EST and OLD tell the user why smoothly moving data may
                # still be uncertain.
                label=(snap.labels or {}).get(tail,tail)+(' · EST' if p.estimated else '')+(' · OLD' if age>10 else '')
                # Keep the label inside the scope even near its perimeter.
                side=-1 if screen_pos[0]>=0 else 1
                c.create_text(x+side*12*self.unit,y-10*self.unit,text=label,anchor='e' if side<0 else 'w',
                    fill=color,font=('DejaVu Sans',max(9,int(10*self.unit*self.label_factor))),tags='map-label')
                self.hits.append((x,y,tail))
        if origin and ground_allowed and self.ground and self.ground_level:self.draw_town_labels(origin)
        # Remember where the control overlay starts. Idle mode can remove buttons/general
        # text while preserving aircraft labels, airport labels and range-ring distances.
        overlay_start=len(c.find_all())
        self.rect(215,50,585,131,fill=BG,outline='')
        self.text(400,68,'FISHFINDER'+(' · DEMO' if snap.demo or (snap.receiver and snap.receiver[2].startswith('DEMO:')) else ''),size=17)
        self.text(400,96,mode,fill=WHITE if fix else YELLOW,size=12)
        self.text(400,119,f'{self.config["horizon_minutes"]} min · purple dashed = estimated · gray = distant',fill=MUTED,size=10)
        self.rect(318,158,482,185,fill='#10253d',outline=BLUE)
        airport_status='Airports unavailable' if self.catalog.error else 'Airports ON' if self.airports_visible else 'Airports OFF'
        self.text(400,171,airport_status,fill=BLUE,size=10)
        self.buttons.append((318,158,482,185,self.toggle_airports))
        if self.ground and ground_allowed:
            self.rect(318,226,482,257,fill='#10251f',outline='#345247')
            self.text(400,242,'Map '+('OFF','LOW','NORMAL')[self.ground_level],size=11)
            self.buttons.append((318,226,482,257,self.cycle_ground))
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
        if self.ground and ground_allowed and self.ground_level:
            notice='Map unavailable' if self.ground.error else 'Map loading...' if self.ground_image is None or time.monotonic()-self.ground_image_time>3 else 'Map coverage partial' if origin and self.ground.bounds and not self.ground.covers(origin,self.radius_nm) else ''
            if notice:self.text(400,585,notice,fill=MUTED,size=9)
        if self.permission_issues:
            self.text(400,620,'Write access needs attention · see Setup',fill=YELLOW,size=10,width=330*self.unit)
        # Popups are drawn above the scope. A reserved ownship selection opens ownship
        # details; an ordinary key opens a traffic target. The crowded-target chooser has its
        # own stable list.
        if self.selected:
            self.ownship_details(fix,own,now) if self.selected=='__ownship__' else self.details(infos.get(self.selected))
        if self.airport_selected:
            self.airport_details()
        if self.target_choices:self.draw_target_choices()
        attribution=''
        if not self.airport_selected and self.ground and ground_allowed and self.ground_level:
            attribution='Natural Earth' if self.ground_global and self.ground_path.suffix=='.sqlite' else 'Map data © OpenStreetMap contributors'
        self.rim_attribution('v'+self.version+(' · '+attribution if attribution else ''))
        if not self.airport_selected:self.rim_attribution('© 2026 FishFinder',3*math.pi/4)
        if self.touch_debug and self.touch_mark and time.monotonic()-self.touch_mark[2]<3:
            tx,ty,_=self.touch_mark
            c.create_oval(tx-5,ty-5,tx+5,ty+5,outline='#ff88ff',width=2)
            self.text(400,655,f'Touch received at {tx}, {ty}',fill='#ff88ff',size=10)
        if self.exit_pending:
            self.rect(210,285,590,515,fill='#071710',outline=WHITE,width=2)
            self.text(400,326,'Close traffic display?',size=19)
            self.text(400,376,'The collector keeps running.',fill=MUTED,size=13)
            self.rect(245,435,390,485,fill='#183b2d',outline=GREEN,width=2)
            self.text(318,460,'Cancel',size=14)
            self.rect(410,435,555,485,fill='#3b181b',outline=RED,width=2)
            self.text(482,460,'Exit',size=14)

    # Cycle map brightness/off state and redraw without changing the traffic data.
    def cycle_ground(self):
        self.ground_level=(self.ground_level+1)%3
        self.config["ground_map"]=bool(self.ground_level)
        self.draw()

    # Ask the background renderer for the view, accept only compatible results, and draw its
    # cached image while it remains fresh.
    def draw_ground(self,origin):
        self.ground.poll()
        size=max(64,min(512,round(398*self.unit)))
        # The map image's identity includes range, brightness and raster size. A result from
        # the previous zoom cannot be reused as though it represented this new zoom.
        key=(self.radius_nm,self.ground_level,size)
        state=(origin,self.map_heading,self.radius_nm,self.ground_level,size)
        now=time.monotonic()
        if key!=self.ground_request_key or now-self.ground_request_time>=1:
            self.ground.request(state)
            self.ground_request_key=key;self.ground_request_time=now
        result=self.ground.result
        if result is not None and result is not self.ground_seen:
            result_state,ppm=result[:2]
            # Discard outdated zoom/brightness results instead of showing a wrong scale.
            # Accept a completed image only if its non-position view parameters still match.
            # Origin/heading may lag briefly between background renders; age is also bounded
            # before the image is shown.
            if result_state[2:]==state[2:]:
                try:
                    image=tk.PhotoImage(data=ppm,format='PPM').zoom(2,2)
                except tk.TclError as exc:
                    self.ground.error=str(exc);self.ground_level=0;return
                self.ground_image=image;self.ground_image_state=result_state;self.ground_image_time=now
                self.ground_labels=result[2] if len(result)>2 else ()
            self.ground_seen=result
        if self.ground_image is not None and self.ground_image_state[2:]==state[2:] and now-self.ground_image_time<=3:
            # One image item per traffic frame; no map paths or pixel work in Tk.
            self.canvas.create_image(self.cx,self.cy,image=self.ground_image)

    # Place town names after traffic/airport labels have reserved space. Skip colliding names
    # rather than hiding higher-priority targets.
    def draw_town_labels(self,origin):
        if self.ground_image is None or time.monotonic()-self.ground_image_time>3:return
        occupied=list(self.label_boxes)
        # Traffic and airport labels take priority; reserve traffic even if airports are off.
        for x,y,tail in self.hits:
            if tail=='__ownship__':
                occupied.append((x-20*self.unit,y-20*self.unit,x+20*self.unit,y+20*self.unit));continue
            label=(self.snapshot.labels or {}).get(tail,tail)
            width=len(label)*7*self.unit*self.label_factor
            left=x-12*self.unit-width if x>=self.cx else x+12*self.unit
            occupied.append((left,y-22*self.unit*self.label_factor,left+width,y+5*self.unit))
        count=0
        for lat,lon,name in getattr(self,'ground_labels',()):
            pos=rotate(xy(lat,lon,origin),self.map_heading)
            if math.hypot(*pos)>self.radius_nm*.86:continue
            x,y=self.cx+pos[0]*self.pixels,self.cy-pos[1]*self.pixels+8*self.unit
            width=min(200,len(name)*5.5)*self.unit*self.label_factor
            height=9*self.unit*self.label_factor
            box=(x-width/2-4,y-height,x+width/2+4,y+height)
            if any(math.hypot(box[a]-self.cx,box[b]-self.cy)>self.radius_nm*self.pixels-5*self.unit for a in (0,2) for b in (1,3)):continue
            if any(box[0]<b[2] and box[2]>b[0] and box[1]<b[3] and box[3]>b[1] for b in occupied):continue
            self.canvas.create_text(x,y,text=name,fill='#728082',font=('DejaVu Sans',max(9,int(10*self.unit*self.label_factor))),tags='town-label')
            occupied.append(box);count+=1
            if count>=12:break

    # Toggle airport overlays and redraw. The loaded reference catalog remains available.
    def toggle_airports(self):
        self.airports_visible=not self.airports_visible;self.draw()

    # Dispatch a button action from the airport page: close, switch strip, switch page, or
    # move through reference data.
    def airport_action(self,action):
        if action=='close': self.airport_selected=None
        elif action.startswith('runway:'): self.airport_runway_index=int(action.split(':')[1])
        elif action=='view': self.airport_runways=not self.airport_runways;self.airport_page=0
        elif action=='next': self.airport_page+=1
        elif action=='prev': self.airport_page=max(0,self.airport_page-1)
        self.draw()

    # Delegate the selected airport reference page to airport_reference.py.
    def airport_details(self):
        from airport_reference import draw
        draw(self,self.catalog.airports[self.airport_selected])

    # Draw a touch button and register its clickable rectangle only when enabled.
    def airport_button(self,x1,y1,x2,y2,label,action,enabled=True):
        self.rect(x1,y1,x2,y2,fill='#10253d' if enabled else '#111b24',outline=BLUE if enabled else '#35434f')
        self.text((x1+x2)/2,(y1+y2)/2,label,size=11,fill=WHITE if enabled else '#63717c')
        if enabled:
            self.airport_buttons.append((x1,y1,x2,y2,action))

    # Draw the older runway-layout view using airport-relative geometry and a scale fitted to
    # its content.
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
        # Convert runway-layout east/north coordinates into the drawing area for this
        # particular diagram.
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

    # Show a confirmation panel instead of immediately destroying the display on a single
    # accidental touch.
    def request_exit(self):
        self.exit_pending=True
        self.draw()

    # Select the radius in nautical miles and redraw at the new scale.
    def set_range(self,value):
        self.radius_nm=value;self.draw()

    # Forget an old fallback anchor so the next frame can choose a current reference center.
    def recenter(self):
        self.anchor=None;self.last_own=None;self.draw()

    # Show our own altitude, speed, inferred true ground course, source and age; explicitly
    # report a fix that has become stale.
    def ownship_details(self,fix,history,now):
        self.rect(176,209,624,614,fill='#071710',outline=WHITE,width=2)
        self.text(400,241,'Ownship',size=22)
        if fix:
            movement=velocity(history)
            heading=math.degrees(math.atan2(movement[0],movement[1]))%360 if movement is not None and math.hypot(*movement)>1e-10 else None
            lines=[f'Altitude: {fix.altitude:,.0f} ft' if fix.altitude is not None else 'Altitude: unavailable',
                   f'Ground speed: {fix.speed:.0f} kt',
                   'Course: unavailable' if heading is None else f'Course: {heading:.0f}° true · ground track',
                   f'Position age: {max(0,now-fix.time):.1f} seconds',
                   f'Source: {self.own_source}']
            for i,line in enumerate(lines):self.text(400,295+i*35,line,size=12)
            self.text(400,513,'Course is over the ground, not magnetic heading.',fill=MUTED,size=10,width=390*self.unit)
        else:
            self.text(400,390,'Ownship position is no longer fresh',fill=YELLOW,size=12)
        self.rect(322,571,478,602,fill='#183b2d',outline=GREEN)
        self.text(400,587,'Close',size=12)

    # Show information for the selected traffic target, including data age and the reason for
    # its current proximity color.
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
                lines.append(f'Ownship altitude: {fix.altitude:,.0f} ft · {self.own_source}')
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

    # Check write permissions again and open the settings panel with actionable status
    # messages.
    def open_setup(self):
        from fs_checks import write_problem
        self.permission_issues=[issue for issue in (write_problem(settings.SETTINGS_PATH,atomic=True),write_problem(self.args.airports,atomic=True)) if issue]
        self.setup_panel=setup_screen.Setup(self)

    # Validate/save user choices, update active display options, and reset cached map state
    # when necessary.
    def apply_settings(self,values):
        previous_map=self.config['ground_map']
        self.config=settings.save(values)
        if self.config['ground_map']!=previous_map or not self.config['ground_map']:
            self.ground_level=1 if self.config['ground_map'] else 0
            if not self.config['ground_map'] and self.ground:
                self.ground.close();self.ground=None
                self.ground_image=None;self.ground_seen=None
                self.ground_request_key=None
        self.radius_nm=self.config['default_range']; self.airports_visible=self.config['airports_visible']
        global TRAIL_AGE
        self.projection_seconds=self.config['horizon_minutes']*60; TRAIL_AGE=self.config['trail_seconds']
        self.last_touch=time.monotonic(); self.draw()

    # Optionally log raw and logical touch coordinates to diagnose mapping issues on the Pi
    # screen.
    def trace_touch(self,event):
        if not self.touch_debug:return
        self.touch_mark=(event.x,event.y,time.monotonic())
        cx=getattr(self,"cx",self.canvas.winfo_width()/2);cy=getattr(self,"cy",self.canvas.winfo_height()/2)
        unit=getattr(self,"unit",max(.1,min(self.canvas.winfo_width(),self.canvas.winfo_height())/800))
        x=(event.x-cx)/unit+400;y=(event.y-cy)/unit+400
        matches=[getattr(action,'__name__','button') for x1,y1,x2,y2,action in self.buttons if x1<=x<=x2 and y1<=y<=y2]
        print(f"TOUCH pixel=({event.x},{event.y}) logical=({x:.1f},{y:.1f}) "
              f"root=({getattr(event,'x_root','?')},{getattr(event,'y_root','?')}) "
              f"canvas={self.canvas.winfo_width()}x{self.canvas.winfo_height()} "
              f"idle={self.idle} buttons={len(self.buttons)} match={','.join(matches) or '-'} "
              f"exit={self.exit_pending} target={self.selected} airport={self.airport_selected}",flush=True)

    # Decide whether this touch is an immediate button action or might be part of a double
    # tap. Capture target positions before the brief delay.
    def tap(self,event):
        self.trace_touch(event)
        now=time.monotonic()
        if now<self.splash_until:
            self.splash_until=0;self.last_touch=now;self.draw();return
        x=(event.x-self.cx)/self.unit+400;y=(event.y-self.cy)/self.unit+400
        # Visible controls and popup actions never wait for a second tap.
        popup=bool(self.selected or self.airport_selected or self.target_choices)
        immediate=(self.exit_pending or self.target_choices or
            (self.selected and 322<=x<=478 and 571<=y<=602) or
            (self.airport_selected and any(x1<=x<=x2 and y1<=y<=y2
                for x1,y1,x2,y2,_ in self.airport_buttons)) or
            (not popup and any(x1<=x<=x2 and y1<=y<=y2
                for x1,y1,x2,y2,_ in self.buttons)))
        # A single finger tap waits briefly because a second nearby tap could be the wake-
        # controls gesture. Visible control buttons bypass that delay so they feel immediate.
        pending=getattr(self,'pending_tap',None)
        if immediate:
            if pending:self.root.after_cancel(pending[0]);self.pending_tap=None
            self.single_tap(event);return
        if pending:
            self.root.after_cancel(pending[0]);self.pending_tap=None
            if now-pending[1]<=.3 and math.hypot(event.x-pending[2].x,event.y-pending[2].y)<=32*self.unit:
                self.last_touch=now;self.selected=None;self.airport_selected=None;self.target_choices=[]
                self.draw();return
        # Capture hit positions now: moving targets may shift during the delay.
        # Freeze candidate positions at touch time. Aircraft may move before the delayed
        # callback runs; use what the user touched, not where the symbol moved afterward.
        hits=tuple(self.hits);airports=tuple(self.airport_hits)
        # Complete a pending single tap using the hit positions captured when the finger
        # landed, not newer moving-target positions.
        def finish():
            self.pending_tap=None
            self.single_tap(event,hits,airports)
        token=self.root.after(300,finish)
        self.pending_tap=(token,now,event)

    # Handle confirmed single touches: popups first, then visible controls, then nearby
    # objects. Several objects open a chooser.
    def single_tap(self,event,hits=None,airport_hits=None):
        if time.monotonic()<self.splash_until:
            self.splash_until=0;self.last_touch=time.monotonic();self.draw();return
        if not self.idle:self.last_touch=time.monotonic()
        x=(event.x-self.cx)/self.unit+400;y=(event.y-self.cy)/self.unit+400
        if self.exit_pending:
            if 410<=x<=555 and 435<=y<=485:
                self.close()
            elif 245<=x<=390 and 435<=y<=485:
                self.exit_pending=False
                self.draw()
            return
        if self.target_choices:
            for x1,y1,x2,y2,action in self.choice_buttons:
                if x1<=x<=x2 and y1<=y<=y2:
                    if action=='cancel':self.target_choices=[]
                    elif action=='prev':self.choice_page-=1
                    elif action=='next':self.choice_page+=1
                    else:self.select_target(self.target_choices[action]);return
                    self.draw();return
            return
        if self.airport_selected:
            for x1,y1,x2,y2,action in self.airport_buttons:
                if x1<=x<=x2 and y1<=y<=y2:
                    self.airport_action(action);return
            return
        if self.selected:
            if 322<=x<=478 and 571<=y<=602 or not(176<=x<=624 and 209<=y<=614):
                self.selected=None;self.draw()
            return
        for x1,y1,x2,y2,action in self.buttons:
            if x1<=x<=x2 and y1<=y<=y2:
                if self.touch_debug:print(f"TOUCH ACTION {getattr(action,'__name__','button')}",flush=True)
                action();return
        hits=self.hits if hits is None else hits
        airport_hits=self.airport_hits if airport_hits is None else airport_hits
        # Consider both airports and aircraft inside the touch radius. Do not always prefer
        # aircraft: at wide range a finger may cover an airport plus several pattern
        # aircraft.
        candidates=[]
        for kind,items in [('aircraft',hits),('airport',airport_hits)]:
            for hx,hy,ident in items:
                distance=math.hypot(event.x-hx,event.y-hy)
                if distance<=28*self.unit:candidates.append((distance,kind,ident))
        # Sort by touch distance once. If there is more than one candidate, show large
        # selectable rows; retain this order while the live display continues updating.
        candidates.sort(key=lambda item:item[0])
        if len(candidates)>1:
            self.target_choices=candidates;self.choice_page=0;self.draw()
        elif candidates:self.select_target(candidates[0])

    # Open the chosen aircraft or airport and close the intermediate target list.
    def select_target(self,target):
        _,kind,ident=target
        self.target_choices=[]
        if kind=='aircraft':self.selected=ident
        else:self.airport_selected=ident;self.airport_runway_index=None;self.airport_page=0;self.airport_runways=False
        self.draw()

    # Draw a stable, paged list of large target buttons so crowded icons do not require
    # precise fingers.
    def draw_target_choices(self):
        # Four large rows per page keep every choice inside the round display.
        self.rect(185,180,615,625,fill='#071710',outline=WHITE,width=2)
        self.text(400,209,'Which one?',size=22)
        self.text(400,239,'Several objects are near your tap',fill=MUTED,size=11)
        pages=(len(self.target_choices)+3)//4
        self.choice_page=max(0,min(self.choice_page,pages-1));self.choice_buttons=[]
        for row,index in enumerate(range(self.choice_page*4,min(len(self.target_choices),self.choice_page*4+4))):
            _,kind,ident=self.target_choices[index]
            top=260+row*68
            if kind=='airport':
                airport=self.catalog.airports.get(ident,{})
                title=airport.get('local_code') or ident
                detail='Airport · '+airport.get('name',ident)
            elif ident=='__ownship__':title='Ownship';detail='Your aircraft'
            else:
                title=(self.snapshot.labels or {}).get(ident,ident)
                history=self.snapshot.reports.get(ident,[])
                p=history[-1] if history else None
                detail='Aircraft'+(f' · {p.altitude:,.0f} ft · {p.speed:.0f} kt' if p and p.altitude is not None else '')
            self.rect(210,top,590,top+58,fill='#183b2d',outline=GREEN)
            self.text(400,top+17,title[:32],size=14)
            self.text(400,top+41,detail[:46],fill=MUTED,size=10)
            self.choice_buttons.append((210,top,590,top+58,index))
        for left,right,label,action in [(215,315,'Prev','prev'),(325,475,'Cancel','cancel'),(485,585,'Next','next')]:
            enabled=action=='cancel' or (action=='prev' and self.choice_page>0) or (action=='next' and self.choice_page+1<pages)
            self.rect(left,545,right,590,fill='#183b2d',outline=GREEN if enabled else MUTED)
            self.text((left+right)/2,568,label,fill=WHITE if enabled else MUTED,size=12)
            if enabled:self.choice_buttons.append((left,545,right,590,action))
        self.text(400,610,f'Page {self.choice_page+1} of {pages}',fill=MUTED,size=10)


# Parse display/database/geometry options, create the Tk window, and hand control to
# Tkinter's event loop.
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
    parser.add_argument('--demo-map',action='store_true',help='Optional bundled O22 roads/water experiment; demo only')
    parser.add_argument('--map-data',type=Path,help='External world_landmarks.pmtiles or world_ground.sqlite; also FISHFINDER_MAP_DATA; defaults under /var/local/FishFinder/')
    parser.add_argument('--touch-debug',action='store_true',help='Print received touch coordinates/actions and show a temporary touch marker')
    parser.add_argument('--no-ownship',action='store_true',help='Demo without an ownship fix')
    parser.add_argument('--range',type=int,choices=(2,5,10,20),default=None)
    parser.add_argument('--splash-seconds',type=float,default=3,help='Startup splash duration; 0 disables, tap dismisses')
    args=parser.parse_args()
    if args.map_data and args.demo_map:parser.error('Choose either --map-data or --demo-map')
    if args.map_data and args.map_data.suffix not in ('.sqlite','.pmtiles'):parser.error('--map-data must name a .sqlite or .pmtiles map file')
    if args.demo_map and not args.demo:parser.error("--demo-map requires the moving --demo")
    if not math.isfinite(args.splash_seconds) or args.splash_seconds<0:parser.error('Splash duration must be finite and nonnegative')
    if args.demo and args.db=='/var/local/FishFinder/flying_objects.db':
        args.db='/var/local/FishFinder/demo_objects.db'
    # Internally this flag remains the legacy sample renderer.
    # User-facing --demo means 'read the separate moving-demo database'. The
    # older internal args.demo field instead means 'make fixed sample objects'.
    # Keep this translation here so the rest of Display sees the legacy meaning.
    args.demo=args.sample_demo
    import signal
    root=tk.Tk();display=Display(root,args)
    signal.signal(signal.SIGTERM,lambda *_:root.after(0,display.close))
    root.mainloop()


# Enter the event loop only when launched, not when imported by tests/tools.
if __name__=='__main__':
    main()
