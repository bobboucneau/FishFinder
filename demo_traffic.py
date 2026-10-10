"""Seeded, offline flight scenarios. Coordinates are local nautical miles."""
from dataclasses import dataclass
import bisect
import json
import math
from pathlib import Path
import random

MPH_TO_KNOTS = 0.868976242
AIRPORTS = [('O22','17',2100,2,330), ('E45','27',2933,1,600),
            ('KCPU','31',1325,2,350), ('O27','28',234,1,600)]


def geographic(origin, east, north):
    radius=3440.065
    distance=math.hypot(east,north)/radius
    bearing=math.atan2(east,north)
    lat,lon=map(math.radians,origin)
    target=math.asin(math.sin(lat)*math.cos(distance)+math.cos(lat)*math.sin(distance)*math.cos(bearing))
    longitude=lon+math.atan2(math.sin(bearing)*math.sin(distance)*math.cos(lat),math.cos(distance)-math.sin(lat)*math.sin(target))
    return math.degrees(target),(math.degrees(longitude)+180)%360-180


def local(origin, lat, lon):
    # Adequate for these short simulator routes; display uses great-circle mapping.
    return ((lon-origin[1])*60*math.cos(math.radians(origin[0])),(lat-origin[0])*60)


@dataclass
class Flight:
    address: int
    tail: str
    kind: str
    start: float
    nodes: list  # (seconds, east NM, north NM, altitude ft, speed kt)

    @property
    def end(self): return self.start+self.nodes[-1][0]

    def sample(self, now):
        t=now-self.start
        if t<0 or t>self.nodes[-1][0]:return None
        index=min(len(self.nodes)-2,max(0,bisect.bisect_right([n[0] for n in self.nodes],t)-1))
        a,b=self.nodes[index:index+2];ratio=(t-a[0])/(b[0]-a[0])
        return tuple(a[i]+(b[i]-a[i])*ratio for i in range(1,5))


def route(address,tail,kind,start,waypoints):
    nodes=[];elapsed=0
    for i,p in enumerate(waypoints):
        if i:
            previous=waypoints[i-1]
            elapsed+=math.hypot(p[0]-previous[0],p[1]-previous[1])*3600/((p[3]+previous[3])/2)
        nodes.append((elapsed,*p))
    return Flight(address,tail,kind,start,nodes)


def rounded_route(address,tail,kind,start,waypoints):
    """Replace pattern corners with tangent circular arcs at 3 degrees/second."""
    omega=math.radians(3);corners={}
    for i in range(1,len(waypoints)-1):
        a,b,c=waypoints[i-1:i+2]
        incoming=(b[0]-a[0],b[1]-a[1]);outgoing=(c[0]-b[0],c[1]-b[1])
        la,lb=math.hypot(*incoming),math.hypot(*outgoing)
        u=(incoming[0]/la,incoming[1]/la);v=(outgoing[0]/lb,outgoing[1]/lb)
        theta=math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1])
        if abs(theta)<.01:continue
        radius=b[3]/3600/omega;distance=radius*math.tan(abs(theta)/2)
        if distance>=min(la,lb):raise ValueError('Pattern leg too short for a standard-rate turn')
        entry=(b[0]-u[0]*distance,b[1]-u[1]*distance,b[2]+(a[2]-b[2])*distance/la,b[3])
        exit=(b[0]+v[0]*distance,b[1]+v[1]*distance,b[2]+(c[2]-b[2])*distance/lb,b[3])
        sign=1 if theta>0 else -1
        center=(entry[0]-u[1]*radius*sign,entry[1]+u[0]*radius*sign)
        corners[i]=(entry,exit,center,theta,radius)
    nodes=[(0,*waypoints[0])]
    def straight(p):
        previous=nodes[-1];distance=math.hypot(p[0]-previous[1],p[1]-previous[2])
        if distance<1e-9:return
        nodes.append((previous[0]+distance*3600/((p[3]+previous[4])/2),*p))
    for i in range(1,len(waypoints)):
        if i not in corners:straight(waypoints[i]);continue
        entry,exit,center,theta,radius=corners[i];straight(entry)
        start_time=nodes[-1][0];duration=abs(theta)/omega
        initial=math.atan2(entry[1]-center[1],entry[0]-center[0])
        steps=math.ceil(duration)
        for j in range(1,steps+1):
            fraction=j/steps;angle=initial+theta*fraction
            nodes.append((start_time+duration*fraction,center[0]+radius*math.cos(angle),
                          center[1]+radius*math.sin(angle),entry[2]+(exit[2]-entry[2])*fraction,entry[3]))
    return Flight(address,tail,kind,start,nodes)


class Scenario:
    def __init__(self, airports_path=None, seed=22):
        path=airports_path or Path(__file__).with_name('airports.json')
        records=json.loads(Path(path).read_text())['airports']
        self.airports={a['code']:a for a in records if a['code'] in {x[0] for x in AIRPORTS}}
        if len(self.airports)!=4:raise ValueError('Demo requires O22, E45, KCPU and O27 in the airport cache')
        self.origin=(self.airports['O22']['lat'],self.airports['O22']['lon'])
        self.random=random.Random(seed);self.flights=[];self.rejected=0;self.serial=0
        self.next_departures=[0,75,150,225];self.departure_counts=[0]*4
        self.next_airline=20;self.next_ga=45;self.next_heli=100;self.generated_until=-1
        self.patterns=[self.pattern(*spec[:3]) for spec in AIRPORTS]

    def pattern(self,code,runway,elevation):
        airport=self.airports[code]
        r=next(r for r in airport['runways'] if runway in (r['le_ident'],r['he_ident']))
        end='le' if r['le_ident']==runway else 'he';other='he' if end=='le' else 'le'
        threshold=local(self.origin,float(r[end+'_latitude_deg']),float(r[end+'_longitude_deg']))
        far=local(self.origin,float(r[other+'_latitude_deg']),float(r[other+'_longitude_deg']))
        dx,dy=far[0]-threshold[0],far[1]-threshold[1];length=math.hypot(dx,dy)
        forward=(dx/length,dy/length);right=(forward[1],-forward[0])
        climb_speed=75*MPH_TO_KNOTS;cruise=110*MPH_TO_KNOTS;approach=70*MPH_TO_KNOTS
        upwind=climb_speed*(700/500*60)/3600
        crosswind=.80  # NM; room for two standard-rate turns at 75 mph
        # Ahead is runway direction; right is the side of a right-hand pattern.
        layout=[(0,0,0,climb_speed),(upwind,0,700,climb_speed),
                (upwind,crosswind,1000,climb_speed),(length/2,crosswind,1000,cruise),
                (-.5*MPH_TO_KNOTS,crosswind,1000,approach),
                (-.5*MPH_TO_KNOTS,0,500,approach),(0,0,0,approach)]
        return [(threshold[0]+a*forward[0]+b*right[0],threshold[1]+a*forward[1]+b*right[1],elevation+alt,speed) for a,b,alt,speed in layout]

    def ownship(self,t):
        speed=100.;angle=t*speed/(3600*5)
        return 5*math.cos(angle),5*math.sin(angle),5000.,speed

    def separated(self,flight):
        # Entire routes checked every second, with margins to cover interpolation.
        others=[f for f in self.flights if f.end>=flight.start and f.start<=flight.end]
        for t in range(math.floor(flight.start),math.ceil(flight.end)+1):
            p=flight.sample(t)
            if p is None:continue
            candidates=[self.ownship(t)]+[q for f in others if (q:=f.sample(t)) is not None]
            for q in candidates:
                if abs(p[2]-q[2])<400 and math.hypot(p[0]-q[0],p[1]-q[1])<.35:return False
        return True

    def admit(self,flight):
        if self.separated(flight):self.flights.append(flight);return True
        self.rejected+=1;return False

    def transit(self,start,kind):
        self.serial+=1;angle=self.random.uniform(0,2*math.pi)
        finish=angle+math.pi+self.random.uniform(-.7,.7)
        if kind=='airliner':alt=self.random.uniform(28000,32000);speed=self.random.uniform(480,510);prefix='JET'
        else:alt=self.random.uniform(4500,12000);speed=self.random.triangular(120,400,120);prefix='GA'
        points=[(32*math.cos(a),32*math.sin(a),alt,speed) for a in (angle,finish)]
        return route(0xD10000+self.serial,f'{prefix}{self.serial:04d}',kind,start,points)

    def helicopter(self,start):
        self.serial+=1;o22=self.airports['O22'];e45=self.airports['E45']
        col=local(self.origin,o22['lat'],o22['lon']);pine=local(self.origin,e45['lat'],e45['lon'])
        sw=(-24,-24);choice=self.random.randrange(3)
        endpoints=[(col,pine),(col,sw),(sw,col)][choice]
        # Cruise at 3,500 ft, with a brief climb/descent at the airport.
        a,b=endpoints;dist=math.hypot(b[0]-a[0],b[1]-a[1]);fraction=min(.15,1/dist)
        middle=lambda f:(a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f,3500,80)
        points=[(*a,2100 if a==col else 3500,80),middle(fraction),middle(1-fraction),(*b,2100 if b==col else 2933 if b==pine else 3500,80)]
        return route(0xD20000+self.serial,f'HELI{self.serial:03d}','helicopter',start,points)

    def advance(self,now):
        # Generate chronologically, independent of the caller's polling frequency.
        while True:
            times=self.next_departures+[self.next_airline,self.next_ga,self.next_heli]
            start=min(times)
            if start>now:break
            index=times.index(start)
            if index<4:
                code,runway,elev,count,interval=AIRPORTS[index]
                n=self.departure_counts[index];slot=n%count
                points=self.patterns[index]
                # Two circuits per sortie, including a touch-and-go.
                f=rounded_route(0xD00000+index*10+slot,f'DEMO-{code}-{slot+1}','C172',start,points+points[1:])
                self.admit(f);self.departure_counts[index]+=1
                self.next_departures[index]+=interval
            elif index==4:
                self.admit(self.transit(start,'airliner'));self.next_airline+=self.random.uniform(45,75)
            elif index==5:
                self.admit(self.transit(start,'GA'));self.next_ga+=self.random.uniform(90,160)
            else:
                self.admit(self.helicopter(start));self.next_heli+=self.random.uniform(300,480)
        self.generated_until=now
        self.flights=[f for f in self.flights if f.end>=now-300]

    def messages(self,now):
        self.advance(now)
        result=[]
        for f in self.flights:
            p=f.sample(now)
            if p is None:continue
            lat,lon=geographic(self.origin,p[0],p[1])
            result.append(dict(Icao_addr=f.address,Reg=f.tail,Tail=f.tail,Lat=lat,Lng=lon,
                Alt=p[2],Speed=p[3],Position_valid=True,Speed_valid=True,Age=0,
                ExtrapolatedPosition=False,AltIsGNSS=False,AgeLastAlt=0))
        p=self.ownship(now);lat,lon=geographic(self.origin,p[0],p[1])
        own=dict(GPSLatitude=lat,GPSLongitude=lon,GPSAltitudeMSL=p[2],GPSGroundSpeed=p[3],
                 GPSFixQuality=1,BaroPressureAltitude=p[2])
        return result,own


def run(stop,db_path,seed=22):
    import logging
    import time
    from contextlib import closing
    import FishFinder as collector
    scenario=Scenario(seed=seed);start=time.monotonic();last_own=-3
    logging.warning('DEMO MODE: synthetic traffic; no Stratux connection. Database %s',db_path)
    with closing(collector.connect_database(db_path)) as conn:
        while not stop.is_set():
            elapsed=time.monotonic()-start
            traffic,own=scenario.messages(elapsed+600)  # Start with flights already airborne.
            timestamp=time.time()
            with conn:conn.execute('INSERT OR REPLACE INTO receiver_status VALUES (1,?,?,?)',(timestamp,1,'DEMO: simulated traffic'))
            for message in traffic:collector.record_traffic(conn,message,timestamp)
            if elapsed-last_own>=3:
                own['BaroLastMeasurementTime']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(timestamp))
                collector.record_ownship(conn,own,timestamp);last_own=elapsed
            stop.wait(1)
