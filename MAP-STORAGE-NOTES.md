Measured minimal-world experiment (v0.4.13): **35,426,304 bytes installed** using generalized Natural Earth data. This is much less detailed than an OpenStreetMap basemap. See [WORLD-MAP.md](WORLD-MAP.md). The larger storage estimates below concern richer data and were not measured in this experiment.

# Worldwide background feasibility — 2026-10-14

The objective is a quiet orientation layer: selected roads, railways, coastlines, major rivers, lakes/reservoirs; no navigation/chart content, buildings, business POIs, terrain or imagery. The pilot should not select tiles before a flight. This note assesses feasibility; worldwide data is NOT included or implemented.

Verified reference: Protomaps describes a full planet vector basemap at roughly 120 GB for zoom levels 0–15. It includes far more detail/layers than FishFinder requires. Their documentation says each additional zoom roughly doubles file size. Accordingly an all-layer z0–12 archive might be on the order of 15 GB, or z0–11 around 7.5 GB. These are arithmetic estimates based on that published rule, NOT measured extracts; data distribution and deduplication change the actual sizes.
Source: https://docs.protomaps.com/basemaps/downloads

For a custom compressed vector pack retaining only our chosen features and moderate geometric detail, reserve 5–20 GB worldwide as a provisional engineering budget. The specific size must be measured from a build. It is not a promised file size or an available download. Adding dense road classes, small water bodies, all coastline detail, redundant zoom representations or railways can increase it. Lowering detail does not necessarily retain every feature present in the local O22 pack. A world map with equivalent practical detail must be built and compared at 2/5/10/20 NM, rather than merely trimming an arbitrary standard tileset.

The O22 pack (373,336 bytes, about 7,600 km² bounding-box area) must not be extrapolated linearly to the entire planet: it contains nonrepresentative road and reservoir density, duplicates shoreline/fill geometry, includes sea/land proportions irrelevant to other regions, and uses an uncompressed JSON prototype format.

Open ocean should be a solid fill/no features, not a stored image grid. Vector indexes plus deduplication avoid hundreds of empty-water tiles. Coastline geometry and islands remain necessary. Most display-time work depends on nearby geometry, not total archive size, provided the data is spatially indexed. Loading the whole global pack into RAM, as the small JSON experiment currently does, would be unsuitable. A shipping global-map feature needs a tiled/spatial-indexed reader and bounded raster cache.

64 GB media could plausibly hold a 5–20 GB map plus OS/application, depending on actual free space. Budget separately for installer staging/rollback, logs and databases; a full-file update might temporarily double the map allocation. Prefer independently replaceable internal chunks so updates need not duplicate the whole world. Internal tiles are an implementation detail, not user-visible region management.

Recommended user model: ship the complete simplified world preinstalled; GPS selects relevant geometry automatically; a saved on/off preference; optional occasional map updates during internet access. If measured storage exceeds budget, either use a larger card or ship broad continent packs (Americas, Europe/Africa, Asia/Oceania, etc.) selected once at purchase/setup, not before each flight. Display chooses among installed coverage automatically. Do not infer continent sizes from land area alone: dense networks and detailed water boundaries dominate.

Updates should be optional and less frequent than airport/aviation chart updates—six-monthly or annual builds are a reasonable initial product choice, subject to how users value freshness. Reservoir shorelines/water levels, roads and rail status still change; this layer is general orientation, not current operational information. Validate packs before replacing them; retain traffic functionality during missing coverage or map failures.

Natural Earth provides a much coarser alternative. Published downloads include global coastlines ~2.93 MB, lakes ~2.24 MB, rivers ~1.98 MB, but its roads/railroads pages describe North-American-only basic coverage. Those small files therefore cannot be used to claim an equally detailed complete-world replacement. At its 1:10-million cartographic scale, smaller landmarks and close-range geometry may be absent/generalized.
Sources:
https://www.naturalearthdata.com/downloads/10m-physical-vectors/
https://www.naturalearthdata.com/downloads/10m-cultural-vectors/roads/
https://www.naturalearthdata.com/downloads/10m-cultural-vectors/railroads/

Next decision: confirm map usefulness/readability and Pi responsiveness first. Then build a size-and-detail sample representing urban, rural, desert, island and lake-rich areas before committing to global manufacture/distribution. No worldwide download/build has been started.
