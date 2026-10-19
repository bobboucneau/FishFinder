Web v0.1.1 centers runway choices, uses an original straight-wing GA ownship symbol, and adds live ownship details on a single tap.

# FishFinder iPad usability demo 0.1.0

Static, touch-friendly browser demo based on Pi v0.4.18. Intended for early
usability feedback, not live traffic, navigation or collision avoidance.
No changes to the running Pi are required.

## Try / share

Open the published link in Safari on iPad. The site is public to anyone with
the URL at Bob's request; it is marked noindex, not access protected. Bob shares
the link himself. No invitations or messages are sent by the application.

- Single-tap an aircraft/airport for information; double-tap the background
  to reveal controls. Visible buttons respond to a single tap.
- The simulation starts already airborne, runs for 30 minutes and loops.
  Pause, Restart and 1×/2×/4× playback are outside the instrument.
- Settings persist in browser-local storage. Restore defaults resets the form;
  Save applies it. No ownship disables altitude filtering and uses display-only
  green traffic. Trails and projections are independent settings.
- How to test includes direct O22/KCPU/E45/O27 reference shortcuts.
- My notes saves locally. Export produces a text file for the tester to share
  manually. The app has no notes upload, account system, analytics, location
  request or live Stratux connection.
- After a complete first load and the offline-cached status, the assets can be
  reused offline. Safari may evict browser storage. Add to Home Screen through
  Safari's Share menu for a standalone-looking window.

The four airport references are a dated FAA/OurAirports demo snapshot, not a
live airport update service. Standard-derived MSL altitudes remain amber with
an asterisk; O22 11/29 uses its published runway-specific exception. Red U arrows
point toward the approach threshold. This web demo does not replace current
FAA publications. The local map has partial coverage at wider ranges; it is not
the 2.85 GB worldwide Pi archive. Includes OpenStreetMap attribution and links.

## Maintain / rebuild

The Python collector and Pi display remain shared canonical implementations.
This browser renderer and calculation port are separate; changes affecting
behavior need parity review. `build_demo_data.py` exports the existing seeded
Python Scenario rather than inventing different flight paths in JavaScript.
It samples trajectories every three seconds; browser interpolation animates them.

From the FishFinder repository root:

```bash
python3 ipad-demo/build_demo_data.py
# Optional build-only settlement label source; never copy that world archive:
python3 ipad-demo/build_demo_data.py --world-map /path/world_landmarks.pmtiles
cd ipad-demo
node --test test-engine.mjs
python3 -m http.server 8765 --bind 127.0.0.1 --directory dist
```

No Node packages or web build step are required. Node is only used for pure
engine tests and Sites publishing helpers. `dist/` holds the deployable files.
Version lives in package.json, dist/engine.mjs and the service-worker cache key;
change all three when updating a published demo. Increment the cache key to
replace a prior offline install. Source records Pi base version in demo.json.
The .openai/hosting.json project ID identifies its existing Sites project;
never create a second project when it is present. Hosting uses a dedicated
checkout outside this GitHub repo; source sync excludes credentials and Git
metadata. Exporting from the standalone Sites checkout requires the parent
FishFinder Python sources, so rebuild from the canonical GitHub repo.

## Verification / limits

Seven dependency-free Node tests pass: settings validation, ordered/finite
scenario data, ownship/course agreement, proximity/vertical/no-ownship logic,
left/right U geometry, sampled synthetic separation, and altitude provenance.
Browser QA checked landscape 1024×768 and portrait 768×1024, setup save/reload,
restore defaults, pause, airport shortcuts/runway switching, and offline reload
with the local server stopped. Real iPad Safari, physical touch comfort, Home
Screen installation and note-export file handling still need tester validation.
Mac/in-app-browser performance is not a Pi or iPad performance guarantee.
