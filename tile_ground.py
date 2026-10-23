"""Offline landmark PMTiles reader and bounded MVT decoder; stdlib only.

Reads our filtered layers, not arbitrary cartographic styles. PMTiles indexing
is provided by the bundled BSD-licensed upstream reader. MVT follows Mapbox's
public 2.1 specification (protobuf fields and delta geometry commands).
"""

# READING THIS FILE: the richer offline PMTiles map reader.
#
# The upstream PMTiles reader locates compressed tiles inside the archive.
# Our own bounded decoder then reads vector-tile fields and turns compact
# integer drawing commands into coordinates. This avoids requiring a large GIS
# software stack on the Pi. The build tools and the Pi runtime have different
# dependency needs: this runtime uses the Python standard library plus the
# bundled reader, whose original license lives in vendor_pmtiles/.
#
# A tile is a small square part of a zoom level. Its integers are not latitude
# or longitude until converted. 'varint' means a variable-length integer;
# protobuf field tags identify what each piece of the binary message contains.
# Malformed or oversized input raises an exception rather than consuming
# unbounded memory or pretending to contain valid landmarks.

from functools import lru_cache
import math
from pathlib import Path
import zlib
from vendor_pmtiles.reader import Reader
from vendor_pmtiles.tile import TileType,Compression

DEFAULT_RICH_PATH=Path('/var/local/FishFinder/world_landmarks.pmtiles')
MAX_BYTES=8_000_000

# Decode binary integers stored seven useful bits at a time; stop on malformed or overlong
# encodings.
def varints(data):
    result=shift=0
    for byte in data:
        result|=(byte&127)<<shift
        if byte<128:yield result;result=shift=0
        else:
            shift+=7
            if shift>63:raise ValueError('Oversized map integer')
    if shift:raise ValueError('Truncated map integer')

# Walk a protobuf message, yielding field numbers and raw values while checking lengths and
# wire types.
def fields(data):
    offset=0
    # Read one integer from the current binary offset and advance that shared offset.
    def number():
        nonlocal offset
        value=shift=0
        while offset<len(data):
            byte=data[offset];offset+=1;value|=(byte&127)<<shift
            if byte<128:return value
            shift+=7
            if shift>63:break
        raise ValueError('Invalid map field')
    while offset<len(data):
        tag=number();key,wire=tag>>3,tag&7
        if not key:raise ValueError('Invalid map field tag')
        if wire==0:yield key,number()
        elif wire in (1,2,5):
            length=number() if wire==2 else 8 if wire==1 else 4
            end=offset+length
            if end>len(data):raise ValueError('Truncated map field')
            yield key,data[offset:end];offset=end
        else:raise ValueError('Unsupported map field')

# Interpret move/line/close commands, accumulate coordinate changes, and enforce a geometry
# budget.
def geometry(commands,feature_type):
    values=iter(varints(commands) if isinstance(commands,(bytes,bytearray)) else commands);x=y=0;parts=[];part=[];count=0
    for command in values:
        kind,n=command&7,command>>3
        if not n:raise ValueError('Empty geometry command')
        if kind in (1,2):
            if kind==2 and not part:raise ValueError('Line before geometry start')
            for _ in range(n):
                try:a,b=next(values),next(values)
                except StopIteration:raise ValueError('Truncated geometry') from None
                x+=(a>>1)^-(a&1);y+=(b>>1)^-(b&1)
                count+=1
                if count>250_000:raise ValueError('Oversized map geometry')
                if kind==1 and feature_type!=1:
                    if part:parts.append(part)
                    part=[]
                part.append((x,y))
        elif kind==7 and n==1 and feature_type==3:
            if not part:raise ValueError('Invalid polygon closure')
            if part[-1]!=part[0]:part.append(part[0])
        else:raise ValueError('Invalid geometry command')
    if part:parts.append(part)
    return parts

# Decompress and decode a bounded tile into landmark paths, water polygons and town labels.
def decode_tile(raw,z,x,y):
    unzip=zlib.decompressobj(16+zlib.MAX_WBITS)
    data=unzip.decompress(raw,MAX_BYTES+1)
    if len(data)>MAX_BYTES or not unzip.eof:raise ValueError('Oversized map tile')
    paths=[];polygons=[];labels=[];total=0
    for key,layer in fields(data):
        if key!=3:continue
        name='';extent=4096;features=[];keys=[];values=[]
        for key,value in fields(layer):
            if key==1:name=value.decode('utf-8')
            elif key==2:features.append(value)
            elif key==3:keys.append(value.decode('utf-8'))
            elif key==4:values.append(next((v.decode('utf-8') for k,v in fields(value) if k==1),''))
            elif key==5:extent=value
        if name not in ('ground_water','ground_urban','ground_river','ground_road','ground_rail','ground_place'):continue
        if not(256<=extent<=65536):raise ValueError('Invalid map extent')
        # Convert a tile-local point into latitude/longitude at this tile coordinate and
        # zoom.
        def position(p):
            lon=(x+p[0]/extent)/(1<<z)*360-180
            lat=math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+p[1]/extent)/(1<<z)))))
            return lat,(lon+180)%360-180
        for feature in features:
            typ=0;commands=b'';tags=[]
            for key,value in fields(feature):
                if key==2:tags=list(varints(value))
                elif key==3:typ=value
                elif key==4:commands=value
            parts=geometry(commands,typ);total+=sum(map(len,parts))
            if total>250_000:raise ValueError('Map tile exceeds geometry budget')
            if typ==2:
                kind={'ground_road':'road','ground_rail':'rail','ground_river':'river'}.get(name)
                if kind:
                    paths.extend((kind,[position(p) for p in part]) for part in parts if len(part)>=2)
            elif typ==3 and name in ('ground_water','ground_urban'):
                group=[]
                for part in parts:
                    if len(part)<4 or part[0]!=part[-1]:raise ValueError('Unclosed map polygon')
                    area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(part,part[1:]))
                    if area>0:
                        if group:polygons.append({'kind':name,'rings':group})
                        group=[]
                    elif not group:continue
                    group.append([position(p) for p in part])
                if group:polygons.append({'kind':name,'rings':group})
            elif typ==1 and name=='ground_place':
                title=''
                for i in range(0,len(tags)-1,2):
                    if tags[i]<len(keys) and tags[i+1]<len(values) and keys[tags[i]]=='name':title=values[tags[i+1]][:48]
                if title:
                    for part in parts:
                        labels.extend((*position(p),title) for p in part)
    return paths,polygons,labels,total

# A bounded read-only map interface backed by the PMTiles archive and a small tile cache.
class TileMap:
    # Open the archive, check its metadata/format, and prepare a cached tile reader.
    def __init__(self,path):
        self.file=Path(path).open('rb');self.labels=[]
        self.size=Path(path).stat().st_size
        # Read exactly the requested archive byte range without loading the entire file.
        def read(offset,length):
            if offset<0 or length<0 or offset+length>self.size or length>MAX_BYTES:raise ValueError('Invalid map read')
            self.file.seek(offset);data=self.file.read(length)
            if len(data)!=length:raise ValueError('Truncated map file')
            return data
        # Directory/header cache only; feature data has a separate bounded cache.
        self.read=lru_cache(maxsize=64)(read)
        try:
            self.reader=Reader(self.read);h=self.reader.header();self.metadata=self.reader.metadata()
            if h['tile_type']!=TileType.MVT or h['tile_compression']!=Compression.GZIP or self.metadata.get('fishfinder_ground_schema')!='1':raise ValueError('Unsupported landmark map')
            self.zooms=sorted(set(self.metadata['zooms']))
            if not self.zooms or not all(isinstance(z,int) and 0<=z<=15 for z in self.zooms):raise ValueError('Invalid map levels')
            self.bounds=[h['min_lat_e7']/1e7,h['min_lon_e7']/1e7,h['max_lat_e7']/1e7,h['max_lon_e7']/1e7]
            self.tile=lru_cache(maxsize=128)(self._tile)
        except Exception:self.file.close();raise
    # Fetch and decode a single tile, allowing repeated nearby queries to reuse it.
    def _tile(self,z,x,y):
        raw=self.reader.get(z,x,y)
        if not raw:return [],[],[],0
        paths,polygons,labels,count=decode_tile(raw,z,x,y)
        # Find the enclosing latitude/longitude rectangle of decoded feature points.
        # Cache it so later queries can quickly skip features outside the view.
        def bounds(points):
            return min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)
        return ([(kind,points,bounds(points)) for kind,points in paths],
                [(polygon,bounds([p for r in polygon['rings'] for p in r])) for polygon in polygons],labels,count)
    # Release the file handle used to read the archive.
    def close(self):
        self.tile.cache_clear();self.read.cache_clear();self.file.close()
    # Choose the appropriate detail level and nearby tiles, then gather visible paths, water
    # and labels within limits.
    def query(self,origin,radius):
        from world_ground import query_bounds
        south,north,ranges=query_bounds(origin,radius)
        if abs(origin[0])>85.0511287:
            self.labels=[];return [],[]
        target=13 if radius<=5 else 11 if radius<=10 else 9
        z=min(self.zooms,key=lambda value:abs(value-target));n=1<<z
        # Convert latitude into the vertical tile-row coordinate for this zoom.
        def row(lat):
            lat=max(-85.0511287,min(85.0511287,lat))
            return max(0,min(n-1,math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)))
        yy=range(row(north),row(south)+1);tiles=set()
        for west,east in ranges:
            lo=max(0,min(n-1,math.floor((west+180)/360*n)));hi=max(0,min(n-1,math.floor((east+180)/360*n)))
            for x in range(lo,hi+1):
                for y in yy:tiles.add((z,x,y))
        if len(tiles)>1024:raise ValueError('Map view exceeds tile budget')
        paths=[];polygons=[];places={};total=0
        # Check whether a feature or label belongs in the geographic view before adding it.
        def visible(bounds):
            low,west,high,east=bounds
            return low<=north and high>=south and any(west<=right and east>=left for left,right in ranges)
        for key in sorted(tiles):
            a,b,c,count=self.tile(*key)
            for kind,points,bounds in a:
                if visible(bounds):paths.append((kind,points));total+=len(points)
            for polygon,bounds in b:
                if visible(bounds):polygons.append(polygon);total+=sum(map(len,polygon['rings']))
            if total>250_000:raise ValueError('Map view exceeds geometry budget')
            for lat,lon,name in c:places[(round(lat,4),round(lon,4),name)]=(lat,lon,name)
        # Bounded text list; exact circular clipping and spacing occur in Tk.
        self.labels=sorted(places.values(),key=lambda p:(p[0]-origin[0])**2+((p[1]-origin[1]+180)%360-180)**2*math.cos(math.radians(origin[0]))**2)[:24]
        return paths,polygons
