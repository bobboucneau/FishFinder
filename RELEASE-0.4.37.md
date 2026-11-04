# FishFinder 0.4.37 — startup notice and usability

The display opens a flight safety notice after the splash/startup network screen.
It requires an explicit “I understand these limitations” tap each time the display
application starts, including after an application update or automatic restart.
Acknowledgement is not stored. It does not stop the collector from receiving data.
A Power button remains available without acknowledging.

The rounded Canvas shape and palette are shared in ff_controls.py. Airport entry,
the main controls, airport-page navigation, shutdown confirmation, the notice, and
Setup action buttons use them. Existing editable Setup fields remain native controls;
network and update pages have not all been converted to the new style.

Power is now centered on its own row. The shutdown prompt says “Wait 5–10 seconds
after the screen goes dark before unplugging.” This is guidance, not measured proof
of completed Linux shutdown. If shutdown hangs, the delay does not make unplugging
safe. The Pi ACT completion sequence remains the hardware cue; no automatic
“safe to unplug” assertion or hard power cut has been added. The existing scoped
sudo rule is unchanged.

Radios / data has a Back to airport button returning directly to the same airport.
Setup → Receiver / Updates adds fallback pattern height in feet AGL, default 1,000;
whole values from 500 to 3,000 are supported. Published values take precedence.
The calculated result remains MSL, amber, starred, and explained with its actual
selected AGL height. This selection is not a claim that all aircraft or airports
use a particular pattern altitude.

Map Low/Off/Normal is removed from the front map; Show ground map remains in Setup.

## Earlier local builds now included in source history

0.4.33–34: circular airport entry, shared rounded controls, arrow hold and wheel swipe.
0.4.35: collector SIGTERM requests cooperative worker closure; read-only SQLite
quick_check before initialization, failure warning and no writer startup; bounded
chunked airport download activity (including FAA) with stages and KB counts.
0.4.36: startup opens the map, retaining the saved airport for the selector.

No recovery/rebuild button or diagnostic uploading is included. Publisher signing
and security hardening remain separate work. The package is an explicit owner
build with checksums, not an authenticated publisher-signed release.

## Checks

Focused behavior checks cover acknowledgement gating, new display-session reset,
Power/Cancel without acknowledgement, direct radio return, calculated MSL/custom
AGL values, published-value precedence, settings validation, removed Map button,
and centered Power. Existing airport, touch, health and sleep regressions also run.

Mac native previews inspect the notice and Setup at 800×800. These are separate
from Pi checks; physical touch and boot/restart acknowledgement need user testing.
