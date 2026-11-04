"""Airport-centered map controls and a direct bearing reference to ownship.

This is an inspection view, not a route, runway approach, or flight instruction.
A missing/stale ownship fix never produces an invented bearing line.
"""
import math
from airport_selection import distance_bearing, navigation_text


def link_vector(origin,fix,radius):
    """Ownship within view gets an exact local endpoint; otherwise use true bearing."""
    from traffic_display import xy
    distance,bearing=distance_bearing(origin,(fix.lat,fix.lon))
    if bearing is None:return (0,0)
    if distance<=radius:return xy(fix.lat,fix.lon,origin)
    # At long distances a local equirectangular offset can distort direction.
    # A great-circle initial bearing gives the correct direction at the airport.
    return (radius*math.sin(math.radians(bearing)),
            radius*math.cos(math.radians(bearing)))


def draw_link(d,airport,fix):
    if fix is None:return
    endpoint=link_vector((airport['lat'],airport['lon']),fix,d.radius_nm)
    d.line((0,0),endpoint,'#8fceff',width=2*d.unit,tags='airport-ownship-link')


def controls(d,airport,fix,now):
    d.scope_button((275,165,525,219),'Back to airport',d.close_airport_map)
    d.text(400,68,airport['code']+' · AIRPORT CENTERED',size=16)
    d.text(400,96,'NORTH UP',size=12)
    d.text(400,119,('To '+airport['code']+': ' if fix else '')+navigation_text(fix,airport,now),size=11)
    d.text(400,651,'Direct bearing reference · not an approach path',size=10)
    for index,value in enumerate((2,5,10,20)):
        x=269+index*87
        d.scope_button((x-38,699,x+38,747),f'{value} NM',
                       lambda n=value:d.set_range(n),
                       'confirm' if value==d.radius_nm else 'nav',12)
