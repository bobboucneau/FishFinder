# Release hosting, packaging and future maps

## Code update hosting

Use the existing bobboucneau/FishFinder GitHub repository's Releases as the download server. A separate VPS/server is unnecessary. Currently our changes are source commits and locally packaged ZIPs; the Code updates button is still a placeholder, not an installer.

For a stable release, tag the tested commit on main, create a draft GitHub Release, attach the exact release ZIP and a manifest, then publish. The manifest should identify version, compatible Pi architecture/OS, download URL, package SHA-256, size and required database migrations. The Pi can discover it through GitHub's releases API. Immutability can prevent a published release's assets/tag from being changed.

The update client still needs to be implemented: check availability in a worker, show version and notes, wait for the user's Install action, download to a writable staging directory, verify a signature with a pinned public key, validate archive paths and hashes, and stage the complete version. Checksums detect corruption but do not establish publisher identity. Keep private signing material off the Pi and out of Git. A signed manifest may use an offline publisher key; immutable-release attestations are another supported GitHub mechanism, with a matching client verification design.

Use version directories with a switchable current link and keep settings, airports and databases separately writable. A narrowly scoped privileged installer should stop/restart the collector and switch versions; the GUI should stay unprivileged and should not request arbitrary sudo shell commands. Keep the old version for rollback. Our current fixed installation needs that layout/service upgrade before automatic installation is safe and reversible.

Sources: https://docs.github.com/en/rest/releases/releases?apiVersion=latest and https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes

## Interpreted versus compiled Python

Recommendation: keep the existing virtual environment and interpreted Python for the first release. The current application is responsive, and it is easier to diagnose, upgrade and repair on the Pi. Compilation alone will not remove the cost of Tk canvas redraws, SQLite or networking. Benchmark a specific bottleneck before changing delivery formats.

Nuitka can produce standalone compiled distributions, including for supported Linux/ARM configurations, but packaging and compatibility must be tested against the exact Pi architecture, OS, Tk installation and dependencies. Start with standalone builds rather than a self-extracting one-file format if we evaluate it. Compilation is a packaging/maintenance decision as much as a speed decision. Source confidentiality is not a current reason to complicate this project.

Source: https://nuitka.net/user-documentation/user-manual.html

## Future offline maps — no map rendering added now

A regional offline background is feasible. Start with a subdued basic map (water, major roads, airport areas); consider sectionals later. Dense sectional labels and colors may compete with traffic visibility on an 800×800 round screen. Provide an easy background on/off toggle and retain high-contrast aircraft/trails.

64 GB should provide ample room for a regional cache, but determine the actual installed tile sizes and retain room for the OS, updates, logs and rollback versions. Avoid downloading a nationwide multi-resolution set without a measured budget. FAA distributes georeferenced VFR raster charts as GeoTIFF downloads; sectional charts update on a 56-day cycle. Keep chart edition/date visible if used.

Preprocess georeferenced charts into resolution levels/tiles away from the flight display. Read only the viewport and nearby tiles. Cache the decoded tiles and composited background, prepare them in a worker, and pass the finished image to Tk's main thread. Rotate/translate one composed background for track-up rather than redraw thousands of map features. Rebuild it only when position, zoom or orientation needs an update, at a rate independent of traffic rendering. Do not resample a full GeoTIFF every frame or depend on internet access in flight.

Measure frame time, CPU, memory and storage I/O on the actual Pi before committing to a renderer. Existing CPU headroom is encouraging but does not prove smooth map rotation. Map projection/georeferencing, airport alignment, chart edges, data-provider caching terms and edition maintenance also need explicit handling. A small regional benchmark is the next step when map work is requested.

Sources: https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/vfr/ and https://www.faa.gov/air_traffic/flight_info/aeronav/productcatalog/vfrcharts/sectional/
