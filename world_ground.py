"""Read spatially indexed global ground data. Standard library only on the Pi."""

# READING THIS FILE: the earlier, compact SQLite world-map format.
#
# This reader opens the map read-only, checks its format identifier, and queries
# only features whose bounding rectangles touch the requested view. The geometry
# is compressed JSON, so decoding has explicit memory limits. A view can cross
# longitude +180/-180; query_bounds() then returns two longitude intervals.
# This format remains supported alongside the richer PMTiles map.

import json
import math
import sqlite3
import zlib
from pathlib import Path

DEFAULT_PATH=Path('/var/local/FishFinder/world_ground.sqlite')
APPLICATION_ID=0x46464D50
MAX_FEATURE_BYTES=8_000_000

# Decompress one map feature with a strict output-byte limit, then read its JSON coordinates.
def decode(blob):
    unpacker=zlib.decompressobj()
    try:raw=unpacker.decompress(blob,MAX_FEATURE_BYTES+1)
    except zlib.error as exc:raise ValueError('Invalid compressed map feature') from exc
    if len(raw)>MAX_FEATURE_BYTES or not unpacker.eof:raise ValueError('Oversized map feature')
    return json.loads(raw)

# Compute latitude limits and one or two longitude intervals for the circular view, including
# date-line crossings.
def query_bounds(origin,radius):
    lat,lon=origin
    if not(-90<=lat<=90 and -180<=lon<=180 and 2<=radius<=20):raise ValueError('Invalid map query')
    # Slight padding accommodates local projection at the edge of the scope.
    angular=math.radians(radius/60*1.05)
    south=max(-90,lat-math.degrees(angular));north=min(90,lat+math.degrees(angular))
    if south<=-90 or north>=90:ranges=[(-180,180)]
    else:
        delta=math.degrees(math.asin(min(1,math.sin(angular)/math.cos(math.radians(lat)))))
        west,east=lon-delta,lon+delta
        ranges=[(west,east)] if west>=-180 and east<=180 else ([(west+360,180),(-180,east)] if west<-180 else [(west,180),(-180,east-360)])
    return south,north,ranges

# A read-only connection to the legacy spatially indexed SQLite map.
class WorldMap:
    # Verify the database format identifier and schema before querying any features.
    def __init__(self,path):
        self.conn=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            if self.conn.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID:raise ValueError('Not a FishFinder map')
            self.metadata=dict(self.conn.execute('SELECT key,value FROM metadata'))
            if self.metadata.get('schema')!='1':raise ValueError('Unsupported world map schema')
        except Exception:
            self.conn.close();raise
    # Release the map database connection.
    def close(self):self.conn.close()
    # Fetch only intersecting features, decode them within a vertex budget, and separate
    # filled polygons from line paths.
    def query(self,origin,radius):
        south,north,ranges=query_bounds(origin,radius)
        rows={}
        for west,east in ranges:
            for ident,kind,blob in self.conn.execute('SELECT f.id,f.kind,f.geometry FROM bounds b JOIN features f ON f.id=b.id WHERE b.west<=? AND b.east>=? AND b.south<=? AND b.north>=?',(east,west,north,south)):
                rows[ident]=(kind,blob)
        paths=[];polygons=[];vertices=0
        for kind,blob in rows.values():
            coords=decode(blob)
            vertices+=sum(len(r) for r in coords) if kind=='water_fill' else len(coords)
            if vertices>250_000:raise ValueError('Map view exceeds geometry budget')
            if kind=='water_fill':polygons.append(coords)
            else:paths.append((kind,coords))
        return paths,polygons
