# O22 ground-reference experiment — v0.4.7

Optional, bundled, offline experiment. No region selector, no network access on the Pi, no changes to normal receiver operation. No weather display is implemented.

Install the full package, then start the moving demo collector and display in separate terminals:

```sh
/usr/local/Fishfinder/.venv/bin/python3 /usr/local/Fishfinder/FishFinder.py --demo
/usr/local/Fishfinder/.venv/bin/python3 /usr/local/Fishfinder/traffic_display.py --demo --demo-map --fullscreen
```

Use the Map button below Setup to cycle LOW → NORMAL → OFF. Touch to wake hidden controls as usual. The preference is temporary and resets to LOW on the next --demo-map launch. Omit --demo-map for the existing black background. --demo-map requires the moving --demo, not the old --sample-demo. A receiver/database identified as live never renders this experiment.

Major roads (motorway/trunk/primary/secondary), river lines, and lake/reservoir shorelines around O22. No street names, buildings, navigation/chart content, railway layer, weather, or filled water polygons. Relation member boundaries are retained as outlines to avoid incorrectly filling islands. Tiny closed ponds are omitted. Partial coverage is indicated when the visible scope crosses the extract boundary. This is general orientation, not navigation data; completeness and positions are not independently verified.

Bounds: south 37.65°, west -120.95°, north 38.40°, east -119.90°. Some edges of the 20 NM scope can fall outside coverage during the ownship orbit. No user download or setup is required for this demo.

Actual packaged map: 239,806 bytes (about 234 KiB), 1,278 paths, 9,398 retained vertices. Original Overpass response about 8.8 MB. The build uses ~65 m geometric simplification, five-decimal-degree coordinates, and excludes small closed water outlines under ~0.48 NM maximum extent. Some artifacts from fragmented OSM geometry may remain; evaluate at all four range settings.

Loading and geographic projection occur in a daemon worker. The main display reads an immutable projected snapshot, translates/rotates it with current ownship, and clips strokes to the circular scope. Projection refreshes at most once per second; traffic continues at its existing cadence. Screen strokes still use Tk on the main thread. Worker failure leaves traffic usable, with a map-unavailable notice. The small local translation approximation between projection updates affects background only.

Desktop recorded-canvas drawing preparation measured about 7 ms without map and 10.5 ms with map in one demo scene. This excludes real Tk drawing, screen refresh, and Pi costs; it is NOT a hardware performance claim. Test responsiveness, update smoothness, and readability on the Pi. The previews show idle mode and use a separate image renderer, so fonts/line appearance may differ slightly from the actual display.

## Data attribution and reproducibility

© OpenStreetMap contributors. OSM data is made available under the Open Database License 1.0 (ODbL): https://www.openstreetmap.org/copyright and https://opendatacommons.org/licenses/odbl/1-0/ . The derived geometry pack is distributed under ODbL 1.0 as well. This map licence does not change the application-code licence.

The complete source response is provided in map-source/o22-overpass-2026-10-14.json.gz. The exact query and transformation are in build_demo_ground.py. The extract was obtained via https://maps.mail.ru/osm/tools/overpass/api/interpreter . Source database timestamp is recorded in demo_ground.json.

To reproduce without another download:

```sh
gunzip -c map-source/o22-overpass-2026-10-14.json.gz > /tmp/o22-source.json
python3 build_demo_ground.py /tmp/o22-source.json demo_ground.json
```

The source copy is included for reproducibility/licence access, not loaded by the display. No runtime dependencies beyond the existing Python/Tk environment were added.

## Questions for the trial

Does water/road context help recognize relative aircraft positions at a glance? Does LOW compete with gray aircraft or range rings? Is NORMAL too busy? Is the display still responsive when ownship rotates and changes range? If the background adds little value, the experiment can be dropped by omitting its flag.

A future shipping feature should work automatically without requiring pilots to manage regions. No regional-update/user-selection workflow is implemented in this experiment.
