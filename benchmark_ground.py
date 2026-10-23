#!/usr/bin/env python3
"""Time local map queries/rasterization on the Pi without starting X or Stratux."""

# READING THIS FILE: measure map cost rather than guessing at performance.
#
# Open a chosen archive, query/render representative views, and report timing
# and memory information. These measurements describe the machine running this
# script. A fast Mac result does NOT prove the Raspberry Pi will feel fast.
# This is a development diagnostic, not a background service.

import argparse
import json
import math
from pathlib import Path
import resource
import statistics
import sys
import time
from demo_ground import rasterize

# Time representative map queries and rasterization, collecting measurements for this
# computer.
def benchmark(path,origin=(38.03,-120.41),iterations=3,heading=0):
    from tile_ground import TileMap
    from world_ground import WorldMap
    factory=TileMap if Path(path).suffix=='.pmtiles' else WorldMap
    result=[]
    for radius in (2,5,10,20):
        world=factory(path)
        try:
            queries=[];renders=[]
            for _ in range(iterations+1):
                start=time.perf_counter();paths,polygons=world.query(origin,radius);queries.append((time.perf_counter()-start)*1000)
                start=time.perf_counter();rasterize(paths,polygons,(origin,heading,radius,1,398));renders.append((time.perf_counter()-start)*1000)
            result.append({'range_nm':radius,'first_query_ms':round(queries[0],2),'cached_query_median_ms':round(statistics.median(queries[1:]),2),'render_median_ms':round(statistics.median(renders[1:]),2),'render_max_ms':round(max(renders),2),'paths':len(paths),'polygons':len(polygons)})
        finally:world.close()
    usage=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'map_bytes':Path(path).stat().st_size,'origin':origin,'heading':heading,'max_rss_mb':round(usage*(1 if sys.platform=='darwin' else 1024)/1e6,2),'views':result}

# Parse archive/range/repeat options and print the benchmark measurements.
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('map',type=Path);p.add_argument('--lat',type=float,default=38.03);p.add_argument('--lon',type=float,default=-120.41);p.add_argument('--heading',type=float,default=0);p.add_argument('--iterations',type=int,default=3)
    a=p.parse_args()
    if not(1<=a.iterations<=20) or not math.isfinite(a.heading):p.error('Use 1..20 iterations and a finite heading')
    print(json.dumps(benchmark(a.map,(a.lat,a.lon),a.iterations,a.heading),indent=2))

if __name__=='__main__':main()
