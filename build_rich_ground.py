#!/usr/bin/env python3
"""Filter a Protomaps PMTiles archive to FishFinder landmarks, offline.

Build dependencies: pmtiles==3.8.1 and mapbox-vector-tile>=2.2,<3 (protobuf).
Usage: python build_rich_ground.py INPUT.pmtiles OUTPUT.pmtiles
Default levels: z9 for 20 NM, z11 for 10 NM, z13 for 2/5 NM. No geometry conversion needed.
"""
import argparse
from functools import lru_cache
from concurrent.futures import ProcessPoolExecutor
from collections import deque
import multiprocessing as mp
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

GROUPS=('ground_water','ground_river','ground_road','ground_rail','ground_urban','ground_place')

def simplify_geometry(values,typ,grid):
    from tile_ground import geometry
    parts=geometry(values,typ);encoded=[];cursor=(0,0);exterior_alive=False
    def area(points):return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]))
    def reduce(points):
        keep={0,len(points)-1};stack=[(0,len(points)-1)]
        while stack:
            lo,hi=stack.pop();a,b=points[lo],points[hi];dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
            best=grid*grid;index=None
            for j in range(lo+1,hi):
                px,py=points[j][0]-a[0],points[j][1]-a[1]
                t=max(0,min(1,(px*dx+py*dy)/den)) if den else 0
                distance=(px-t*dx)**2+(py-t*dy)**2
                if distance>best:best=distance;index=j
            if index is not None:keep.add(index);stack.extend(((lo,index),(index,hi)))
        return [points[i] for i in sorted(keep)]
    def delta(point):
        nonlocal cursor
        a,b=point[0]-cursor[0],point[1]-cursor[1];cursor=point
        return [(a<<1)^(a>>63),(b<<1)^(b>>63)]
    for original in parts:
        winding=area(original) if typ==3 else 0
        if typ==3 and winding>0:exterior_alive=False
        elif typ==3 and not exterior_alive:continue
        points=[]
        for x,y in original:
            p=(((x+grid//2)//grid)*grid,((y+grid//2)//grid)*grid)
            if not points or p!=points[-1]:points.append(p)
        if len(points)>2:points=reduce(points)
        if typ==3:
            if len(points)<4 or area(points)*winding<=0:continue
            if winding>0:exterior_alive=True
            points=points[:-1]
        elif len(points)<2:continue
        encoded.extend([9,*delta(points[0]),((len(points)-1)<<3)|2])
        for point in points[1:]:encoded.extend(delta(point))
        if typ==3:encoded.append(15)
    return encoded

def filter_tile(raw,keep_minor=False,grid=1):
    from mapbox_vector_tile.Mapbox import vector_tile_pb2 as pb
    source=pb.tile();source.ParseFromString(gzip.decompress(raw))
    target=pb.tile();groups={}
    for layer in source.layers:
        if layer.name not in ('water','roads','landuse','places'):continue
        try:kind_key=list(layer.keys).index('kind')
        except ValueError:continue
        try:name_key=list(layer.keys).index('name')
        except ValueError:name_key=-1
        try:detail_key=list(layer.keys).index('kind_detail')
        except ValueError:detail_key=-1
        for f in layer.features:
            tags=f.tags
            kind=next((layer.values[tags[i+1]].string_value for i in range(0,len(tags),2) if tags[i]==kind_key),'')
            detail=name=''
            if layer.name=='places':
                for i in range(0,len(tags),2):
                    if tags[i]==name_key:name=layer.values[tags[i+1]].string_value
                    elif tags[i]==detail_key:detail=layer.values[tags[i+1]].string_value
            group=None
            if layer.name=='water':
                if f.type==3 and kind not in ('swimming_pool','fountain'):group='ground_water'
                elif f.type==2 and kind in ('river','stream','canal'):group='ground_river'
            elif layer.name=='roads' and f.type==2:
                if kind in ('highway','major_road') or keep_minor and kind=='minor_road':group='ground_road'
                elif kind=='rail':group='ground_rail'
            elif layer.name=='landuse' and f.type==3 and kind in ('residential','commercial','industrial'):group='ground_urban'
            elif layer.name=='places' and f.type==1 and kind=='locality' and detail in ('city','town','village') and name:group='ground_place'
            if not group:continue
            if group not in groups:
                out=target.layers.add();out.name=group;out.version=2;out.extent=layer.extent
                groups[group]=(out,{})
                if group=='ground_place':out.keys.append('name')
            out,names=groups[group]
            if out.extent!=layer.extent:raise ValueError('Mixed tile extents')
            feature=out.features.add();feature.CopyFrom(f)
            feature.ClearField('tags');feature.ClearField('id')
            if grid>1 and f.type in (2,3):
                reduced=simplify_geometry(f.geometry,f.type,max(1,round(grid*layer.extent/4096)))
                if not reduced:del out.features[-1];continue
                feature.ClearField('geometry');feature.geometry.extend(reduced)
            if group=='ground_place':
                if name not in names:
                    names[name]=len(out.values);out.values.add().string_value=name
                feature.tags.extend([0,names[name]])
    for i in range(len(target.layers)-1,-1,-1):
        if not target.layers[i].features:del target.layers[i]
    return gzip.compress(target.SerializeToString(),compresslevel=6,mtime=0)

@lru_cache(maxsize=512)
def cached_filter(raw,keep_minor,grid):return filter_tile(raw,keep_minor,grid)

def filter_batch(rows,keep_minor,meters):
    from vendor_pmtiles.tile import tileid_to_zxy
    result=[]
    for start,count,raw in rows:
        z,x,y=tileid_to_zxy(start)
        latitude=math.atan(math.sinh(math.pi*(1-2*(y+.5)/(1<<z))))
        units=40075016.68557849*math.cos(latitude)/((1<<z)*4096)
        grid=1 if not meters else min(512,2**max(0,math.floor(math.log2(meters/units))))
        result.append((start,count,cached_filter(raw,keep_minor,grid)))
    return result

def ordered_batches(batches,keep_minor,workers,meters):
    if workers==1:
        for batch in batches:yield filter_batch(batch,keep_minor,meters)
        return
    with ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        pending=deque()
        for batch in batches:
            pending.append(pool.submit(filter_batch,batch,keep_minor,meters))
            if len(pending)>=workers*2:yield pending.popleft().result()
        while pending:yield pending.popleft().result()

def build(source_path,output_path,zooms=(9,11,13),keep_minor=False,limit_gb=None,workers=4,meters=40):
    from pmtiles.reader import Reader,MmapSource
    from pmtiles.tile import deserialize_directory,Entry,zxy_to_tileid
    from pmtiles.writer import Writer
    class SafeWriter(Writer):
        def write_run(self,tileid,data,count):
            digest=hashlib.sha256(data).digest()
            if digest in self.hash_to_offset:
                offset=self.hash_to_offset[digest]
                if self.tile_entries and tileid==self.tile_entries[-1].tile_id+self.tile_entries[-1].run_length and offset==self.tile_entries[-1].offset:self.tile_entries[-1].run_length+=count
                else:self.tile_entries.append(Entry(tileid,offset,len(data),count))
            else:
                self.tile_f.write(data);self.tile_entries.append(Entry(tileid,self.offset,len(data),count))
                self.hash_to_offset[digest]=self.offset;self.offset+=len(data)
            self.addressed_tiles+=count
    source_path,output_path=Path(source_path),Path(output_path)
    if workers<1:raise ValueError('Workers must be positive')
    if source_path.resolve()==output_path.resolve():raise ValueError('Source and output must differ')
    repo=Path(__file__).resolve().parent
    if output_path.resolve().is_relative_to(repo):raise ValueError('Keep map data outside Git')
    temporary=output_path.with_suffix('.building')
    if temporary.exists():raise ValueError(f'Unfinished build: {temporary}')
    zooms=sorted(set(zooms))
    selected=[(zxy_to_tileid(z,0,0),zxy_to_tileid(z+1,0,0)) for z in zooms]
    last_id=max(high for low,high in selected)
    started=time.monotonic();processed=0;last=started
    with source_path.open('rb') as source_file:
        get=MmapSource(source_file);reader=Reader(get);header=reader.header();metadata=reader.metadata()
        if not {'water','roads'}<={layer.get('id') for layer in metadata.get('vector_layers',[])}:raise ValueError('Expected an unfiltered Protomaps source')
        if header['max_zoom']<max(zooms):raise ValueError('Source lacks required detail')
        output_file=temporary.open('wb')
        writer=SafeWriter(output_file)
        def entries(offset,length):
            for entry in deserialize_directory(get(offset,length)):
                if entry.tile_id>=last_id:break
                if entry.run_length:yield entry
                else:yield from entries(header['leaf_directory_offset']+entry.offset,entry.length)
        def batches():
            batch=[]
            for entry in entries(header['root_offset'],header['root_length']):
                for low,high in selected:
                    start=max(low,entry.tile_id);end=min(high,entry.tile_id+entry.run_length)
                    if start>=end:continue
                    batch.append((start,end-start,get(header['tile_data_offset']+entry.offset,entry.length)))
                    if len(batch)>=128:yield batch;batch=[]
            if batch:yield batch
        try:
            for result in ordered_batches(batches(),keep_minor,workers,meters):
                for start,count,raw in result:
                    writer.write_run(start,raw,count);processed+=1
                now=time.monotonic()
                if now-last>15:
                    print(f'{processed:,} entries; {writer.offset/1e9:.3f} GB tile content; {now-started:.0f}s',flush=True);last=now
                if limit_gb and writer.offset>limit_gb*1e9:raise ValueError(f'Exceeded {limit_gb} GB build budget; candidate not installed')
            if not processed:raise ValueError('No matching source tiles')
            metadata={k:metadata[k] for k in ('attribution','bounds','description') if k in metadata}
            metadata.update({'name':'FishFinder OSM landmarks','fishfinder_ground_schema':'1','zooms':list(zooms),'source':'Protomaps OpenStreetMap basemap','source_archive':source_path.name,'minor_roads':keep_minor,'grid_meters':meters,'vector_layers':[{'id':n,'fields':{'name':'String'} if n=='ground_place' else {},'minzoom':min(zooms),'maxzoom':max(zooms)} for n in GROUPS]})
            # The upstream center may be zoom 0, outside our retained levels.
            header['center_zoom']=min(zooms)
            writer.finalize(header,metadata)
        except BaseException:
            writer.tile_f.close();temporary.unlink(missing_ok=True);raise
        finally:output_file.close()
    temporary.replace(output_path)
    with output_path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    report={'bytes':output_path.stat().st_size,'source_bytes':source_path.stat().st_size,'zooms':list(zooms),'entries_processed':processed,'grid_meters':meters,'elapsed_seconds':round(time.monotonic()-started,1),'sha256':digest}
    output_path.with_suffix('.report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);p.add_argument('--zooms',type=int,nargs='+',default=[9,11,13]);p.add_argument('--minor-roads',action='store_true');p.add_argument('--limit-gb',type=float);p.add_argument('--workers',type=int,default=4);p.add_argument('--grid-meters',type=float,default=40,help='Approximate simplification grid; 0 preserves source geometry')
    a=p.parse_args()
    if not(0<=a.grid_meters<=100):p.error('Grid must be 0..100 meters')
    if not(1<=a.workers<=16):p.error('Workers must be 1..16')
    if a.limit_gb is not None and a.limit_gb<=0:p.error('Build budget must be positive')
    if any(not(0<=z<=15) for z in a.zooms):p.error('Zooms must be 0..15')
    print(json.dumps(build(a.source,a.output,a.zooms,a.minor_roads,a.limit_gb,a.workers,a.grid_meters),indent=2))

if __name__=='__main__':main()
