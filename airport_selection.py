"""Manual airport lookup and great-circle distance/initial true bearing.

Selecting an airport never changes ownship or the traffic-map center. The numbers
refer to the airport's reference coordinates, not a runway threshold or route.
"""
import math


def lookup(catalog,text):
    code=text.strip().upper()
    if not code or len(code)>7 or not code.isascii() or not code.isalnum():
        raise ValueError('Enter 1–7 letters or numbers, for example O22 or KGOO.')
    # Prefer an exact database identifier. Display/local codes can differ: O22
    # is stored as KO22 in this cache. Never silently pick an ambiguous alias.
    if code in catalog.airports:return catalog.airports[code]
    matches=[airport for airport in catalog.airports.values() if airport.get('code','').upper()==code]
    if len(matches)==1:return matches[0]
    if matches:raise ValueError('More than one airport matches. Use its full identifier.')
    raise ValueError('Airport not found. Check the code or update airport data.')


def distance_bearing(origin,destination):
    lat1,lat2=map(math.radians,(origin[0],destination[0]))
    delta=math.radians(destination[1]-origin[1])
    a=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(delta/2)**2
    distance=3440.065*2*math.asin(math.sqrt(max(0,min(1,a))))
    east=math.sin(delta)*math.cos(lat2)
    north=math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta)
    bearing=None if distance<.01 or math.hypot(east,north)<1e-12 else math.degrees(math.atan2(east,north))%360
    return distance,bearing


def navigation_text(fix,airport,now,max_age=15):
    if fix is None or not 0<=now-fix.time<=max_age:
        return 'Ownship position unavailable'
    distance,bearing=distance_bearing((fix.lat,fix.lon),(airport['lat'],airport['lon']))
    if bearing is None:return f'At airport · {distance:.1f} NM' if distance<.01 else f'Bearing unavailable · {distance:.1f} NM'
    # Rounding 359.8 must display 000 rather than the invalid heading 360.
    return f'{round(bearing)%360:03d}° TRUE · {distance:.1f} NM'
