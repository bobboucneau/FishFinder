"""Offline OurAirports cache, spatial lookup and runway geometry."""
import json
from datetime import date, datetime, timezone
import math
from pathlib import Path

BLUE = '#62b6ff'


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def coordinates(lat, lon):
    a, b = number(lat), number(lon)
    return (a, b) if a is not None and b is not None and -90 <= a <= 90 and -180 <= b <= 180 else None


class AirportCatalog:
    def __init__(self, path):
        self.error = ''; self.date = 'unavailable'; self.bands = {}; self.airports = {}
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if data.get('schema') != 1:
                raise ValueError('Unsupported airport cache format')
            self.date = data['downloaded_utc'][:10]
            for a in data['airports']:
                pos = coordinates(a.get('lat'), a.get('lon'))
                if pos is None or not a.get('ident'):
                    continue
                a['lat'], a['lon'] = pos
                self.airports[a['ident']] = a
                self.bands.setdefault(math.floor(a['lat']), []).append(a)
            if not self.airports:
                raise ValueError('No usable airports')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.error = f'Airport data unavailable: {exc}'
            self.airports = {}; self.bands = {}

    def nearby(self, origin, radius, xy):
        if origin is None:
            return []
        margin = math.degrees(radius / 3440.065) + 0.01
        result = []
        for band in range(math.floor(max(-90, origin[0]-margin)), math.floor(min(90, origin[0]+margin))+1):
            for a in self.bands.get(band, []):
                pos = xy(a['lat'], a['lon'], origin)
                distance = math.hypot(*pos)
                if distance <= radius:
                    result.append((distance, a, pos))
        return sorted(result, key=lambda v: (v[0], v[1]['ident']))


def rotate(pos, track):
    """East/north vector in a view whose up axis is true ground track."""
    angle = math.radians(track)
    e, n = pos
    return e*math.cos(angle)-n*math.sin(angle), e*math.sin(angle)+n*math.cos(angle)


def runway_segments(airport, xy):
    """Real endpoints where known; independent centered schematic otherwise."""
    result = []
    origin = (airport['lat'], airport['lon'])
    for runway in airport.get('runways', []):
        le = coordinates(runway.get('le_latitude_deg'), runway.get('le_longitude_deg'))
        he = coordinates(runway.get('he_latitude_deg'), runway.get('he_longitude_deg'))
        schematic = False
        if le is not None and he is not None:
            a, b = xy(*le, origin), xy(*he, origin)
            if math.hypot(b[0]-a[0], b[1]-a[1]) < 0.00001:
                continue
        else:
            length = number(runway.get('length_ft'))
            heading = number(runway.get('le_heading_degT'))
            if heading is None:
                h = number(runway.get('he_heading_degT'))
                heading = None if h is None else (h+180)%360
            if length is None or length <= 0 or heading is None:
                continue
            half = length / 6076.11549 / 2
            e, n = half*math.sin(math.radians(heading)), half*math.cos(math.radians(heading))
            a, b = (-e, -n), (e, n)
            schematic = True
        result.append((runway, a, b, schematic))
    groups={}
    import re
    for index,(r,a,b,schematic) in enumerate(result):
        match=re.fullmatch(r'(\d{1,2})([LRC])',r.get('le_ident',''))
        heading=number(r.get('le_heading_degT'))
        if match and heading is not None and not schematic:
            groups.setdefault(match[1],[]).append((index,heading,match[2]))
    for group in groups.values():
        if len(group)<2 or len({g[2] for g in group})!=len(group): continue
        base=group[0][1]
        if any(abs((h-base+180)%360-180)>1 for _,h,_ in group): continue
        heading=math.radians(base)
        for index,_,_ in group:
            r,a,b,schematic=result[index]
            center=((a[0]+b[0])/2,(a[1]+b[1])/2)
            length=number(r.get('length_ft'))
            half=length/6076.11549/2 if length and length>0 else math.dist(a,b)/2
            v=(half*math.sin(heading),half*math.cos(heading))
            r=dict(r,_aligned=True)
            result[index]=(r,(center[0]-v[0],center[1]-v[1]),(center[0]+v[0],center[1]+v[1]),schematic)
    return result


def freshness_label(download_date, today=None):
    """Snapshot age, not validation age of individual airport records."""
    try:
        downloaded=date.fromisoformat(download_date)
        age=((today or datetime.now(timezone.utc).date())-downloaded).days
    except (ValueError, TypeError):
        return 'Last updated: unknown — refresh airport data', True
    if age < 0:
        return f'Last updated: {download_date} — check device clock', True
    suffix=f'{age} days old' if age != 1 else '1 day old'
    if age > 30: suffix+=' · refresh recommended'
    return f'Last updated: {download_date} · {suffix}', age > 30
