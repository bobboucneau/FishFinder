# Richer worldwide landmark map experiment — v0.4.14

The Natural Earth world experiment is too sparse for our landmark goal. This
version adds a separately stored OpenStreetMap-based map with lake/reservoir
outlines, rivers, streams, canals, major roads, physical railways, settlement
names, and subdued built-up-area shading. Mountains and weather are excluded.
Individual buildings, addresses, shops, footpaths, road labels, and minor
residential streets are discarded. This remains a ground-reference experiment.

One offline file covers the basemap's worldwide Web Mercator extent (about
85.05°S to 85.05°N). No pilot region selection or preflight tile loading is
required. Polar areas outside that extent are blank and marked partial coverage;
traffic display remains available there. OpenStreetMap coverage and quality
vary, and intermittent waterways may be dry. Built-up areas use mapped
residential/commercial/industrial land-use footprints, not inferred city limits.
Small waterways are retained where available in the source detail level; this
is not a complete inventory of every stream or pond.

## Measured build

The installed map is **2,849,245,701 bytes: 2.85 GB (2.65 GiB)**. This is
larger than the initial ~2 GB estimate, but well within the 64 GB card's total
capacity; check actual free space before copying. The map keeps zoom levels
9/11/13 and processed 14,531,307 source index entries. Filtering took 662.5
seconds on this Mac with eight workers, after source download/recovery.

SHA-256: `8b54fb0f236493bf3b630b970ff1290649ba84f2de5ce4201191d87b661fd2f2`.
The completed archive passes the official PMTiles verifier. All four ranges
loaded around O22, Tokyo, London, Cape Town, Sydney, São Paulo, Delhi, Anchorage,
and the date line; polar views return a blank background as intended.

On the completed file, O22 rasterization was 4–27 ms, cached queries below
0.4 ms, and a fresh benchmark process peaked at 32.31 MB on this Mac. The final
native Tk check with busy traffic over Tokyo handled 112 simulated taps, no
callback errors, and median/maximum GUI draw times of 12.34/18.43 ms. These
are Mac measurements, not promises of Pi performance. The code suite passed
56 tests; the Pi touchscreen and flight test remain outstanding.

The ~36 GB working source is NOT the installed Pi map: it contains many layers
we discard. Sources and experimental outputs remain outside GitHub, in Bob's
local backup-excluded Mac cache. The original 35.43 MB Natural Earth result
remains documented in WORLD-MAP.md for comparison.

## Install and compare

1. Extract FishFinder-v0.4.14.zip into a new application folder.
2. Copy the separate `world_landmarks.pmtiles` file into `/var/local/FishFinder/`
   on the Pi. It is already compressed. Make it readable by `fish` (644 is
   appropriate); its parent directory must allow traversal.
3. Launch the new Display.bash or DemoDisplay.bash normally and enable **Show
   ground map (experiment)** in Setup. No new Python packages are needed on the Pi.

The display prefers `/var/local/FishFinder/world_landmarks.pmtiles`, then the
older `/var/local/FishFinder/world_ground.sqlite`. The map is opened read-only.
An explicitly saved off setting is respected on restart. Low/Normal/Off remain
available; Low is the first enabled brightness. The collector is unchanged.

For an alternate file, append `--map-data /path/map.pmtiles` to a launcher or set
`FISHFINDER_MAP_DATA`. This accepts our filtered landmark archives, not arbitrary
Protomaps archives. To compare the older world experiment, use `--map-data
/var/local/FishFinder/world_ground.sqlite`. To compare the bundled local O22 map,
use DemoDisplay.bash with `--demo-map` and without `--map-data`.

Colors: amber roads, dashed violet railway lines, matching muted-blue watercourses and water
fills, subdued gray built-up areas and settlement names. Traffic, ownship, range
rings, and airports remain above the background. Place names are limited and
spaced to reduce clutter; aircraft/airport information retains priority.

## Indexed loading and responsiveness

File size is independent of the amount loaded for a view. The reader seeks to
nearby tiles, keeps bounded directory/geometry caches, filters features beyond
the view, and uses different detail at different ranges: zoom 13 for 2/5 NM,
zoom 11 for 10 NM, and zoom 9 for 20 NM. The source's smaller streams appear at
zoom 13; wide views omit that fine linework. Map rendering stays in a separate
spawned process at at most one request per second. Tk receives one cached image
plus at most 12 town labels and never waits for the worker.

Tile/decompression/geometry budgets bound unexpected inputs. A worker failure
shows Map unavailable while the traffic display continues; Setup off/on can
restart it.

Mac sample checks after simplification: the richer O22 background rasterized in
about 6–32 ms across 2/5/10/20 NM. A dense Tokyo sample took about 24–146 ms.
Repeat cached queries avoid decoding the map again. Simplifying O22 reduced its
three-level sample from 932,044 to 443,570 bytes; the union of mapped water area
changed by about +0.35% in the comparison region. This area check does not prove
that every shoreline or small water feature is preserved. A native Tk test over the Tokyo sample
with busy demo traffic handled 114 simulated taps without callback errors, including the curved rim
attribution; median GUI draw was 6.28 ms and maximum 18.91 ms. Pi performance and in-flight
readability still require testing. A larger file is not assumed to be fast simply
because it fits on the card.

To measure the map worker on the Pi without X or Stratux, run from the new
application folder:

```bash
/usr/local/FishFinder/.venv/bin/python3 benchmark_ground.py /var/local/FishFinder/world_landmarks.pmtiles
```

This reports first/cached query times, raster times, and peak process memory at
all four ranges around O22. `--lat` and `--lon` select another location. It does
not flush the operating system's disk cache or replace a real touchscreen test.

## Rebuild (Mac or other build computer)

Install the official [pmtiles CLI](https://docs.protomaps.com/pmtiles/cli) and
build-only packages `pmtiles==3.8.1` and `mapbox-vector-tile>=2.2,<3` in a dedicated
virtual environment. The latter provides the fast protobuf encoder; the Pi
uses our bounded decoder and bundled BSD-licensed PMTiles reader instead.

Find a current Version 4 archive at
[Protomaps builds](https://maps.protomaps.com/builds). The tested source is
`https://build.protomaps.com/20261015.pmtiles` (basemap version 4.15.2). Build URLs
are retained for a limited time; choose a current compatible build if it expires.
The extractor can report size without downloading using `--dry-run`.

```bash
pmtiles extract https://build.protomaps.com/20261015.pmtiles \
  "$HOME/Library/Caches/FishFinder/world-map-experiment/world-source-z13.pmtiles" \
  --maxzoom=13

python3 build_rich_ground.py \
  "$HOME/Library/Caches/FishFinder/world-map-experiment/world-source-z13.pmtiles" \
  "$HOME/Library/Caches/FishFinder/world-map-experiment/world_landmarks.pmtiles" \
  --workers 4

pmtiles verify "$HOME/Library/Caches/FishFinder/world-map-experiment/world_landmarks.pmtiles"
```

Use a different cache path on Linux. The filter refuses output inside its code
folder. Geometry uses an approximately 40 m grid plus line simplification;
small features below that scale can disappear. This is adjustable with
`--grid-meters` (0 preserves source geometry). Source and output must differ. A budget can be enforced with `--limit-gb
2`; exceeding it removes the candidate and preserves the old installed file.
Filtering uses bounded batches, four worker processes by default, SHA-256
content deduplication, and run-length indexing for repeated tiles. Unneeded
properties and feature identifiers are removed. A `.report.json` records actual
bytes, levels, elapsed build time, and output SHA-256. A complete candidate is
written before atomically replacing a prior file. No map data belongs in the
code ZIP or GitHub repository.

On Bob's Mac `~/Library/Caches/FishFinder` is verified excluded from Time Machine
and lies outside iCloud Desktop/Documents. Other backup software may have its
own rules. macOS can purge caches; keep the installed Pi copy and retain the
source/report when reproducing an experiment.

## Attribution and licenses

The OpenStreetMap attribution stays visible along the lower-right circular rim
when controls hide. Lakes and watercourses use the same softer blue.

Map data: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
through the [Protomaps basemap](https://docs.protomaps.com/basemaps/downloads).
The upstream describes these tiles as an ODbL Produced Work. Retain the map's
attribution and these source details when distributing it.

Bundled PMTiles Python reader 3.8.1: BSD-3-Clause, © 2021 Protomaps LLC; original
source and license are in vendor_pmtiles/. Our MVT decoder follows the
[Mapbox Vector Tile 2.1 specification](https://github.com/mapbox/vector-tile-spec/tree/master/2.1).
