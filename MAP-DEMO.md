# O22 ground-reference experiment — v0.4.8

Optional, bundled, offline experiment. No region selector or network access on the Pi. No weather display is implemented.

v0.4.7's individual map strokes overloaded the Pi GUI in hardware testing. v0.4.8 replaces them with a cached image rendered in a separate process, and batches aircraft/ownship trails into continuous polylines. This reduces GUI drawing work without removing traffic or history. Purple dashed estimated segments remain distinct.

Install the full package, then start the moving demo collector and display in separate terminals:

```sh
/usr/local/Fishfinder/.venv/bin/python3 /usr/local/Fishfinder/FishFinder.py --demo
/usr/local/Fishfinder/.venv/bin/python3 /usr/local/Fishfinder/traffic_display.py --demo --demo-map --fullscreen
```

Use the Map button below Setup to cycle LOW → NORMAL → OFF. Touch to wake hidden controls as usual. The preference is temporary and resets to LOW on the next --demo-map launch. Omit --demo-map to restore the black background. --demo-map requires the moving --demo, not the old --sample-demo. A receiver/database identified as live never renders this experiment. Trail batching applies to live and demo displays.

Major roads, river lines, and lake/reservoir outlines around O22. Complete water boundaries now have dark blue fill; islands are preserved using an even/odd fill rule. Member fragments are joined only at matching endpoints. Incomplete boundaries remain outlines; no invented closing edge or synthetic water area. Tiny closed ponds are omitted. No road names, buildings, railways, terrain, or aviation-chart content. General orientation only: data completeness and positions are not independently verified.

Bounds: south 37.65°, west -120.95°, north 38.40°, east -119.90°. Some edges of the 20 NM scope can fall outside coverage during the orbit; a partial-coverage notice appears. No user download/setup is required.

The geometry pack is about 365 KiB (373,336 bytes), with 1,278 outline/road paths and 47 fillable water groups (172 rings including islands). It uses ~65 m geometric simplification and five-decimal-degree coordinates. Incomplete source geometry can still leave gaps. The original Overpass response is about 8.8 MB, included compressed at ~1.4 MB for reproducibility.

## Responsiveness

A separate spawned process loads, projects, clips, and rasterizes the background using only Python's standard library. The GUI sends a small render request at most once per second, or when range/brightness/size changes. It never waits for that result. Tk receives a half-resolution PPM, doubles it once, and reuses the same PhotoImage across traffic frames. It draws one image item instead of hundreds of map strokes. No Pillow or additional runtime package is required. Main-thread image transfer/conversion is bounded but not free.

The background updates about once per second; traffic retains its existing cadence. It is less finely drawn than the old vector strokes. Wrong-range/brightness results are rejected. Cached images older than three seconds are hidden; map loading/unavailable status is shown. Renderer failure doesn't stop traffic. Exit terminates the renderer without waiting for a full render. A stopped renderer is not automatically restarted; relaunch if needed.

Continuous trails are batched, with separate polylines at estimation-style changes or clipping gaps. An estimated-point prefix count replaces repeated rescans of each full history. Historical data, sampling, aircraft selection, and threat logic are unchanged.

In the same recorded demo scene, canvas operations fell from ~1,659 to ~107. A six-second native Tk test on the Mac handled 111 generated touch events, drew a cached image, and exited normally without callback errors. Median draw callback ~13.5 ms, maximum ~26.6 ms; a nominal 50 ms event-loop probe peaked at ~70.8 ms. These are desktop observations, not a Pi performance guarantee. Pi testing remains required, especially during range changes, turning ownship, and busy traffic.

## Data attribution and reproducibility

© OpenStreetMap contributors. OSM data is available under the Open Database License 1.0 (ODbL): https://www.openstreetmap.org/copyright and https://opendatacommons.org/licenses/odbl/1-0/ . The derived geometry pack is distributed under ODbL 1.0. This data licence does not change the application-code licence.

The complete source response is in map-source/o22-overpass-2026-10-14.json.gz. The exact query and transformation are in build_demo_ground.py. Extract obtained via https://maps.mail.ru/osm/tools/overpass/api/interpreter . Source timestamp is recorded in demo_ground.json.

```sh
gunzip -c map-source/o22-overpass-2026-10-14.json.gz > /tmp/o22-source.json
python3 build_demo_ground.py /tmp/o22-source.json demo_ground.json
```

The source copy is not loaded by the display. No regional-update or user-selection workflow is implemented. A future shipping feature should work automatically.
