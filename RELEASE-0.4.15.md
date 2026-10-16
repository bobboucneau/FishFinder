# FishFinder v0.4.15 — touch gestures and altitude filtering

- A single tap on an aircraft/airport opens its information after a 300 ms
  double-tap window, without revealing hidden main controls.
- Double-tap the map (within 300 ms and 32 scaled pixels) to reveal controls
  and restart the hide timer. Double-tapping a popup background also returns
  to the controls. Visible buttons and popup action buttons respond immediately
  to a single tap. The startup splash can still be dismissed with one tap.
- Setup → Display has an optional **Hide vertically distant aircraft** checkbox,
  initially off. Setup → Receiver / Updates → **Altitude limit (feet)** sets
  the shared gray/hide threshold (default 5,000 ft). Hiding takes precedence
  over gray styling. Collection and saved reports are unaffected.
- Hiding requires fresh, comparable pressure altitudes and observed rates on
  both tracks. Unknown/stale/estimated altitude stays visible. Traffic also
  remains visible if the observed vertical-rate projection crosses the limit
  within the configured projection window. This is an observed-rate model,
  not a prediction of future maneuvers.
- The curved notice now reads **Map data © OpenStreetMap contributors**.

Install the new version folder and preserve settings.json from your previous
folder. The existing world_landmarks.pmtiles file and virtual environment are
reused; no new map download is needed. Use the matching DemoDisplay.bash and
DemoFinder.bash (or Display.bash and Finder.bash for live operation). Repoint an
installed collector service using configure_pi.py as described in SERVICES.md.

Validation: 59 automated tests passed on the Mac. Native Tk map/traffic smoke
check handled 106 simulated taps with no callback errors. Physical touchscreen
comfort, particularly the double-tap timing, still needs user testing on the Pi.
