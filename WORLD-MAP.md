# Minimal worldwide map experiment — v0.4.13

The optional world file is separate from the code package and GitHub. One file
covers the world offline; no region selection, flight-time internet, or tile
preloading is needed. Turn the map on/off in Setup. Traffic remains above it.

## Measured result, October 15, 2026

| Item | Actual bytes | Decimal MB |
| --- | ---: | ---: |
| Installed world_ground.sqlite | 35,426,304 | 35.43 |
| Separate transfer ZIP (unpack on the Pi) | 19,792,575 | 19.79 |
| Five downloaded source ZIPs (Mac build only) | 31,811,455 | 31.81 |

The indexed map contains 206,389 pieces: 67,143 roads, 30,503 railway pieces,
10,736 river pieces, and 98,007 lake/ocean polygons. Only nearby pieces are read.
Shapefile attributes, names, unused fields, and minor detail are discarded.
Geometry is simplified with a 0.002-degree tolerance (about 220 m in latitude),
rounded to five decimals, split to at most one degree per piece, and compressed.
The simplification tolerance is not an accuracy guarantee.

This is **Natural Earth 1:10-million**, substantially more generalized than our
local OpenStreetMap experiment. Global coverage does not mean every feature is
present: even some substantial reservoirs near O22 are absent, roads/railways
have uneven detail, and coastlines are coarse at short ranges. At 2–5 NM it can
be very sparse. It is an orientation experiment, not a navigation chart. The
existing bundled O22 demo remains available for comparing richer detail.

Colors: amber roads, dashed violet railways, cyan rivers, blue lake/ocean fills.
Low/Normal changes brightness. Aircraft/conflict colors are unchanged.

## Install on the Pi

Extract FishFinder-v0.4.13.zip into a new application folder. Copy the separately
provided world_ground.sqlite file to `/var/local/FishFinder/world_ground.sqlite`.
Use the normal `fish` account; the file must be readable (644 is appropriate),
and its directory must allow traversal. The display opens it read-only.
Do not put it in the Git checkout.

Launch the new Display.bash or DemoDisplay.bash as usual and enable **Show ground
map (experiment)** in Setup. Both live and demo modes can use the global file.
With the file in that default location, no extra launch argument is needed.

For a different location, either append `--map-data /path/world_ground.sqlite`
to a display launcher, or set `FISHFINDER_MAP_DATA` to that path. An explicitly
saved Setup off preference wins over command-line opt-in. A missing/invalid
selected map reports "Map unavailable" while the traffic display keeps working.
`--demo-map` explicitly selects the old bundled O22 demo-only map, even when a
worldwide file is installed; use it without `--map-data` for comparison.

These are map-reader/display changes; the collector service needs no changes.

## Rebuild on the Mac

Build-only packages (not needed on the Pi): `pyshp>=2.3,<4`, `shapely>=2,<3`.
For example, create a dedicated virtual environment under the local cache,
install those packages there, and run:

```bash
python3 build_world_ground.py --download
```

The macOS default output is
`~/Library/Caches/FishFinder/world-map-experiment/world_ground.sqlite`.
Sources, build report, and generated data stay there. On Bob's Mac the parent
FishFinder cache is verified excluded from Time Machine and is outside iCloud
Desktop/Documents. Third-party backup applications may use their own rules.
Caches can be purged by macOS; this data can be rebuilt. Linux defaults to
`~/.cache/FishFinder/world-map-experiment`.

The builder refuses source/output locations inside its code directory. Git
also ignores SQLite maps, PMTiles, and the world-map experiment directories.
Only builder, parser, renderer, tests, and documentation go to GitHub. Existing
small O22 demonstration files are unaffected. Source SHA-256 digests, feature
counts, and build settings are recorded in the database and `.report.json`.
The download URLs point to Natural Earth's current release; a future rebuild
may differ. Preserve source hashes/archives when reproducing this exact build.
The complete candidate database is checked before atomically replacing an old
map. Download/build dependencies are never imported by the Pi display.

## Architecture and checks

SQLite R-tree selects nearby geometry, including queries across the date line.
The existing separate spawned map process performs decompression, projection,
and rasterization. Tk receives one cached image at most once per second and
never waits for a map query. Geometry/decompression budgets bound malformed or
unexpectedly dense views; worker failures are shown without blocking controls.

Mac checks: 51 automated tests pass. Eight worldwide viewport samples queried
in 0.06–0.78 ms and rasterized in 0.78–6.56 ms. A six-second native Tk check with
busy demo traffic handled 112 simulated taps with no callback errors; median
GUI draw time 11.38 ms, maximum 28.30 ms. These are Mac observations, not Pi
performance guarantees. Real Pi touch responsiveness and in-flight usefulness
still need testing. Weather display remains on hold.

Data: [Natural Earth downloads](https://www.naturalearthdata.com/downloads/),
[public-domain terms](https://www.naturalearthdata.com/about/terms-of-use/).
"10m" here means **1:10 million map scale**, not ten-meter resolution.
