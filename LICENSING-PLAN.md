# FishFinder: planned GPLv3 open-source release

Status as of 2026-10-23: **GPLv3 is the intended licensing model.** This document
records the plan; it does not itself grant a GPL license or relicense any file.
No project-wide `LICENSE` file or GPL source headers are installed by this pass.

The intended product is hardware, assembly and testing, with the software
available as open source. The code, documentation, third-party components and
map/reference data need their respective scope and notices stated clearly.

## Before formally applying the license

1. Confirm the legal copyright holder. The on-screen “FishFinder” label is the
   chosen display credit; it is not a substitute for identifying the licensor.
2. Confirm the exact grant: GPL version 3 only (`GPL-3.0-only`) or GPL version 3
   **or any later version** (`GPL-3.0-or-later`). Do not silently choose between them.
3. Add the unmodified GPLv3 license text and appropriate source/README notices,
   explicitly identifying which original FishFinder files the grant covers.
4. Assemble third-party notices and review the exact dependencies/artifacts
   shipped with each release, including any complete Pi/SD-card image.
5. Make matching corresponding source and the relevant installation/build
   information available for the distributed version, as applicable under GPLv3.
   A source archive/tag should identify the actual shipped build, not just a
   moving main branch.

## Keep other licenses distinct

- Preserve the bundled PMTiles reader's BSD-3-Clause license and original notices.
- Preserve applicable Python/Tk and WebSocket-client notices when those components
  are distributed; do not present them as original FishFinder code.
- Keep OpenStreetMap/Protomaps-derived map-data terms and attribution separate
  from the application-code license. Applying GPLv3 to our code does not replace
  ODbL obligations for the data.
- Retain airport-data source dates/provenance. A code license is not a promise
  that reference data is current, a product certification, or an endorsement.

No runtime behavior, installed-Pi service, tester-site publication, repository
access setting, third-party license, or source ownership has been changed by
recording this plan.

References for the eventual grant:

- [GNU GPLv3 text](https://www.gnu.org/licenses/gpl-3.0.html)
- [GPLv3 overview and conditions](https://choosealicense.com/licenses/gpl-3.0/)
- [GPL-3.0-only identifier](https://spdx.org/licenses/GPL-3.0-only.html)
- [GPL-3.0-or-later identifier](https://spdx.org/licenses/GPL-3.0-or-later.html)
- [OpenStreetMap licensing and attribution](https://www.openstreetmap.org/copyright)
