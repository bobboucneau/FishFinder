#!/usr/bin/env python3
"""Build the optional Natural Earth world map, never inside the repository.

Build-only dependencies: pyshp>=2.3,<4 and shapely>=2,<3.
The display needs neither package. Sources and output default to the Mac cache.
"""
import argparse
import collections
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request
import zipfile
import zlib
from world_ground import APPLICATION_ID

SOURCES={
 'roads':('10m_cultural','ne_10m_roads'),
 'railroads':('10m_cultural','ne_10m_railroads'),
 'rivers':('10m_physical','ne_10m_rivers_lake_centerlines'),
 'lakes':('10m_physical','ne_10m_lakes'),
 'ocean':('10m_physical','ne_10m_ocean'),
}

def build(source,output,tolerance=.002):
    import shapefile
    from shapely.geometry import shape,box
    from shapely import make_valid
    if not(0<tolerance<=.02):raise ValueError('Invalid simplification tolerance')
    source,output=Path(source),Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.building')
    if temporary.exists():raise ValueError(f'Unfinished build exists: {temporary}')
    counts=collections.Counter();vertices=collections.Counter();stats={};started=time.monotonic()
    conn=sqlite3.connect(temporary)
    try:
        conn.executescript(f'PRAGMA application_id={APPLICATION_ID}; CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE features(id INTEGER PRIMARY KEY,kind TEXT,geometry BLOB); CREATE VIRTUAL TABLE bounds USING rtree(id,west,east,south,north);')
        def insert(kind,geometry):
            if kind=='water_fill':
                coords=[list(geometry.exterior.coords)]+[list(r.coords) for r in geometry.interiors]
                # Omit clipped tile edges from outlines; fills have no tile seams.
                coords=[[[round(y,5),round(x,5)] for x,y in ring] for ring in coords]
                n=sum(map(len,coords))
            else:
                coords=[[round(y,5),round(x,5)] for x,y in geometry.coords];n=len(coords)
            blob=zlib.compress(json.dumps(coords,separators=(',',':'),allow_nan=False).encode(),9)
            ident=conn.execute('INSERT INTO features(kind,geometry) VALUES(?,?)',(kind,blob)).lastrowid
            west,south,east,north=geometry.bounds
            conn.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(ident,west,east,south,north))
            counts[kind]+=1;vertices[kind]+=n
        def parts(geometry,kind):
            if geometry.is_empty:return
            if geometry.geom_type in ('GeometryCollection','MultiPolygon','MultiLineString'):
                for g in geometry.geoms:parts(g,kind)
                return
            if geometry.geom_type not in ('Polygon','LineString'):return
            if kind=='water_fill' and geometry.geom_type!='Polygon':return
            west,south,east,north=geometry.bounds
            width,height=east-west,north-south
            # Bound projection and query work: every piece fits one degree,
            # including open-ocean rectangles and polar water.
            if max(width,height)<=1:
                insert(kind,geometry);return
            if width>=height:
                mid=(west+east)/2
                clips=[box(west,south,mid,north),box(mid,south,east,north)]
            else:
                mid=(south+north)/2
                clips=[box(west,south,east,mid),box(west,mid,east,north)]
            for clip in clips:parts(geometry.intersection(clip),kind)
        for layer,(_,stem) in SOURCES.items():
            archive=source/(layer+'.zip')
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            with zipfile.ZipFile(archive) as z:
                reader=shapefile.Reader(shp=io.BytesIO(z.read(stem+'.shp')),dbf=io.BytesIO(z.read(stem+'.dbf')),encodingErrors='replace')
                selected=0;continents=collections.Counter()
                for record in reader.iterShapeRecords():
                    attributes=record.record.as_dict()
                    if layer=='roads' and attributes.get('type') in ('Ferry Route','Ferry, seasonal','Track'):continue
                    kind={'roads':'road','railroads':'rail','rivers':'river','lakes':'water_fill','ocean':'water_fill'}[layer]
                    geometry=shape(record.shape.__geo_interface__)
                    if not geometry.is_valid:geometry=make_valid(geometry)
                    geometry=geometry.simplify(tolerance,preserve_topology=True)
                    parts(geometry,kind);selected+=1
                    if attributes.get('continent'):continents[attributes['continent']]+=1
                stats[layer]={'source_records':len(reader),'selected':selected,'sha256':digest,'continents':dict(continents)}
            conn.commit()
            print(f'{layer}: {selected} source features; {sum(counts.values()):,} indexed pieces',flush=True)
        metadata={'schema':'1','source':'Natural Earth 1:10 million','attribution':'Natural Earth · generalized reference','license':'Public domain','tolerance_degrees':str(tolerance),'source_manifest':json.dumps(stats,sort_keys=True),'counts':json.dumps(dict(counts)),'vertices':json.dumps(dict(vertices))}
        conn.executemany('INSERT INTO metadata VALUES(?,?)',metadata.items());conn.commit()
        conn.execute('VACUUM')
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Map integrity check failed')
        conn.close();temporary.replace(output)
    except BaseException:
        conn.close()
        temporary.unlink(missing_ok=True)
        raise
    result={'bytes':output.stat().st_size,'source_zip_bytes':sum((source/(k+'.zip')).stat().st_size for k in SOURCES),'counts':dict(counts),'vertices':dict(vertices),'elapsed_seconds':round(time.monotonic()-started,1),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'sources':stats}
    output.with_suffix('.report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    default=Path.home()/('Library/Caches/FishFinder/world-map-experiment' if sys.platform=='darwin' else '.cache/FishFinder/world-map-experiment')
    parser.add_argument('--cache',type=Path,default=default)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--download',action='store_true',help='Download missing source archives over HTTPS')
    parser.add_argument('--tolerance',type=float,default=.002,help='Simplify degrees (default .002, roughly 220 m latitude)')
    args=parser.parse_args();source=args.cache/'source';output=args.output or args.cache/'world_ground.sqlite'
    repository=Path(__file__).resolve().parent
    for candidate in (source,output):
        if candidate.resolve().is_relative_to(repository):parser.error('Keep worldwide sources/data outside the code repository')
    source.mkdir(parents=True,exist_ok=True)
    for layer,(category,stem) in SOURCES.items():
        dest=source/(layer+'.zip')
        if not dest.exists():
            if not args.download:parser.error(f'Missing {dest}; add --download')
            tmp=dest.with_suffix('.download')
            try:
                with urllib.request.urlopen(f'https://naturalearth.s3.amazonaws.com/{category}/{stem}.zip',timeout=120) as response,tmp.open('wb') as stream:
                    import shutil
                    shutil.copyfileobj(response,stream)
                with zipfile.ZipFile(tmp) as z:
                    if z.testzip():raise ValueError('Invalid source ZIP')
                tmp.replace(dest)
            finally:tmp.unlink(missing_ok=True)
    print(json.dumps(build(source,output,args.tolerance),indent=2))

if __name__=='__main__':main()
