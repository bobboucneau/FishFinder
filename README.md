# FishFinder v0.4.0 — display, settings and connection recovery

This is a new testing package. v0.2.1 and the working baseline are preserved.

## Install on the Pi

Stop both the existing collector and display. Back up the SQLite database using SQLite backup, or stop all writers before copying it. Copy all files in this package into one directory. Keep FishFinder.py, traffic_display.py, settings.py, setup_screen.py, airport_data.py, update_airports.py and airports.json together.

Use the existing environment (Tkinter and websocket-client):

```bash
/usr/local/Fishfinder/.venv/bin/python3 traffic_display.py --demo --fullscreen
```

Live operation still runs two programs:

```bash
/usr/local/Fishfinder/.venv/bin/python3 FishFinder.py
/usr/local/Fishfinder/.venv/bin/python3 traffic_display.py --fullscreen
```

With HDMI attached and DSI beginning at x=1920:

```bash
/usr/local/Fishfinder/.venv/bin/python3 traffic_display.py --geometry 800x800+1920+0 --fullscreen
```

Database: /var/local/FishFinder/flying_objects.db. Interpreter: /usr/local/Fishfinder/.venv/bin/python3. Their capitalization differs intentionally. Both programs must read the same settings file. By default settings.json lives beside these scripts. To put settings elsewhere, set FISHFINDER_SETTINGS to the same absolute path for both processes. The display needs write permission to that settings directory and its airport cache. Saving settings uses atomic replacement. Configuration errors are shown on Save; invalid hand-edited settings fail startup rather than silently applying another IP.

The collector migrates reports and ownship by adding nullable comparison_alt and alt_ref columns, and adds receiver_status. Existing rows remain usable but cannot acquire a reliable altitude reference retroactively. The display remains a read-only database client.

## Display and setup

The outer range circle now has a 398-pixel radius on an 800-pixel screen. Controls stay at their prior coordinates and are drawn on top of traffic. Range means center-to-edge radius in nautical miles. North-up remains the map orientation. Setup is below the Airports toggle.

Setup offers Stratux IPv4 address, own tail number, default range (2/5/10/20 NM), vertical threshold (default 5,000 ft), vertical styling on/off, idle timeout (default 10 sec; zero disables), projection time (1–10 min), trail duration (30–300 sec), and airport visibility. Text fields open a touch keyboard. Save/Back validates and persists choices; Cancel/Back discards them. Restore defaults fills the form; Save applies those defaults. The collector picks up a changed IP automatically and reconnects. Own-tail filtering hides matching registration/callsign labels from this display; it does not change Stratux's ownship configuration or infer a new GPS location.

After ten untouched seconds on the primary map, buttons, headers and other interface text disappear. Aircraft labels, airport codes, range labels, symbols, trails, projections and circles remain. Airport names shorten to their code (for example O22). One touch wakes the controls and is consumed, so it cannot accidentally press Exit or select hidden controls. Setup and detail panels stay visible. Missing-ownship and receiver-unavailable notices remain visible even when idle.

## Hollow gray aircraft

Hollow gray diamonds and gray trails mean the observed vertical-rate model keeps the aircraft beyond the selected vertical threshold for the whole projection. If its climb/descent, including ownship's climb/descent, enters the threshold, it retains the usual green/yellow/red horizontal assessment. Gray targets remain selectable.

Only fresh pressure-to-pressure altitude comparisons qualify. Stratux traffic Alt is used only with an explicit false AltIsGNSS flag and a valid AgeLastAlt of at most 10 seconds. Ownship BaroPressureAltitude is used only with a fresh BaroLastMeasurementTime. Both histories must supply at least three matching pressure-altitude samples spanning ten seconds in the last twenty seconds. Missing altitude, missing motion history, stale measurements or unknown references disable gray styling. No usable ownship displayed altitude also disables it. Without an ownship fix, targets remain green as before and assessment is unavailable.

Ownship altitude display now prefers GPSAltitudeMSL, falling back to the older GPSAltitude field. A valid position without altitude can still be displayed. Pressure comparison altitude is stored separately from displayed GPS altitude. A Stratux without usable barometric altitude may never show gray targets: that is intentional rather than comparing unlike altitude references. This observed-rate model cannot anticipate a future change in vertical rate. It is experimental reference information, not collision avoidance guidance.

## Stratux reachability

The collector validates the /getSituation response before opening its traffic WebSocket. Network identity/SSID alone cannot establish that the correct receiver is reachable; the API response check does. With no receiver, it logs a transition to “Stratux not available. Waiting...” and retries every five seconds without repeated network tracebacks. The live display shows that message via the shared database. A reachable Stratux without a valid GPS fix is distinct from an unreachable receiver. Unexpected processing/database faults still produce diagnostic logs. All identifiable traffic frames, including saved=False, and ownship reports are logged at INFO. Use --log-level WARNING for a quieter console or DEBUG for additional diagnostics.

Both programs must be upgraded for connection status. An older collector cannot supply receiver_status; the display then says Waiting for collector. Existing reports expire normally. No automatic boot services are installed.

## Runway layout

Reid-Hillview's cached endpoint coordinates produce slightly different runway angles, although its two runway records both list 142.9 degrees true. The diagram now recognizes explicit parallel L/R/C runway designators with the same numeric end and agreeing published true headings (within one degree). It draws that group with the shared true heading, preserving each runway center and published length, and labels the view as a schematic. Other runway groups retain endpoint geometry. Source data is never edited.

Runway numbers alone do not provide a precise true heading and are not used to invent one. Missing endpoints still use the earlier dashed schematic fallback only with a usable true heading and length. No taxiways/obstacles or live closure status are supplied. Verify with current charts.

## Airport updates and saved internet Wi-Fi

OurAirports already publishes daily snapshots; a separate FishFinder data repository is unnecessary. Suggested user workflow: refresh weekly when convenient and before a trip; keep the existing 30-day age reminder. Refreshing daily usually adds little value for an offline Pi, and snapshot age does not certify each record's accuracy.

1. In Setup, open Wi-Fi / Internet. On a Pi with nm-connection-editor, this opens NetworkManager's profile editor. Save your internet network there and activate it through the desktop Wi-Fi menu. NetworkManager remembers credentials; FishFinder does not store passwords. If the editor is absent, the button gives instructions to use the desktop Wi-Fi menu. This is an integration with the existing desktop tools, not a custom touch-only Wi-Fi wizard.
2. Tap Update airport data. Downloads run in a worker so the UI stays responsive. HTTPS source reachability is checked by the downloads themselves.
3. The updater checks source columns, usable airports, runway/frequency presence and unexpected count loss (>20% under the same country scope). It installs using atomic replacement only after validation. Any failed download or validation preserves the previous cache. Existing regional filters are retained.
4. Success reloads the data immediately and shows the count. Rejoin the Stratux network afterwards. The update panel waits for the update to finish before allowing Back; downloads have bounded timeouts.

The command-line updater is also available:

```bash
/usr/local/Fishfinder/.venv/bin/python3 update_airports.py
```

Data source: https://ourairports.com/data/
Field definitions: https://ourairports.com/help/data-dictionary.html
NetworkManager: https://networkmanager.dev/docs/api/latest/nmcli.html

## Code update recommendation — not enabled yet

The Code updates button currently explains that no release server is configured. It does not download or install code. To enable it, first choose a FishFinder GitHub repository (or another HTTPS release host).

Recommended approach: versioned Releases containing a package and signed manifest. The Pi should check for a newer compatible release, show release notes, ask the user to install, verify a signature with a bundled public key, stage and validate all files, then switch between versioned installation directories and restart both programs. Keep the previous release for rollback; settings/database remain outside the replacement directory. Plain checksums verify transfer integrity but are not a substitute for signed authenticity. A Git repository is useful for code history and releases; the Pi should consume release packages rather than run git pull over a live installation.

Network selection remains user initiated. After joining remembered internet Wi-Fi, a future unified Updates page can check airports and code together, then offer separate install buttons. A complete unattended upgrade/restart workflow also needs an agreed installation directory and service launch method; this version keeps manual launching.

## Verification

Twenty automated tests cover airport lookup and geometry, runway alignment, idle/wake touch behavior, expanded scope, settings validation/persistence, vertical closure and unknown-data handling, idempotent database migration, missing-altitude ownship, wrong-device API response, quiet disconnected retries, WebSocket keepalive/retry options and error diagnostics, INFO report logging, and preservation on failed/truncated data updates. WebSocket is stubbed for collector database/probe tests if websocket-client is absent on the test host; no live traffic stream is opened. Preview images render Canvas drawing commands and are illustrative.

Actual Tk widgets, the touch keyboard, NetworkManager window, Stratux firmware field availability, fullscreen monitor placement, and Pi performance still require on-device testing. The airport snapshot remains the October 6 snapshot; this release does not refresh it automatically.

Stratux field sources:
https://github.com/cyoung/stratux/blob/master/main/traffic.go
https://github.com/cyoung/stratux/blob/master/main/gps.go

## v0.3.1 connection changes

Client-generated WebSocket pings are disabled as a compatibility measure. v0.3 used a 30-second ping interval and a 10-second pong deadline; a late/missing pong could terminate that connection. This is a possible cause, not a diagnosis of the user's particular disconnect. TCP keepalive is enabled, using Linux idle/interval/count settings when supported. It detects broken links without treating a lack of aircraft reports as a failure. Local Stratux connections explicitly bypass proxy routing, and connection establishment has a five-second socket timeout.

Unexpected disconnects retain and log the underlying error, server close code/message when present, or an explicit no-close-frame message. A connection that ran at least ten seconds starts retrying after one second; repeated short failures back off to two, four and at most five seconds. Receiver verification and socket establishment add their own bounded request time to that delay. Shutdown and an IP change are logged as intentional closures. Live stability remains to be tested on the Pi.

References: https://websocket-client.readthedocs.io/en/latest/app.html and https://github.com/cyoung/stratux/blob/master/main/managementinterface.go

## v0.3.2 layout and repaint changes

In idle mode all four ring labels align at the same x coordinate. With controls visible, the two intermediate labels retain their offset to avoid the header/setup overlay. Setup checkbuttons use flat styling with no surrounding widget border or focus frame; the small check indicators remain. The four central action buttons fill equal-width columns with identical padding/height.

The map, including airports, repaints every 250 ms instead of every 500 ms. Nearby-airport lookup refreshes at least once per second, as well as whenever the center/range key changes. This redraws the existing offline data more frequently; it does not increase Stratux's GPS update rate or download airport records. Pi performance and actual native widget styling still need checking.

## v0.3.3 traffic logging and processing

Every identifiable traffic frame logs saved=True/False at INFO again. WebSocket callbacks parse and enqueue traffic promptly; a separate traffic-writer thread owns the database connection, so SQLite writes and per-report logging cannot block socket receipt. The queue is bounded to 1,024 observations and favors recent data if full; any overflow is reported when a connection ends. Receipt timestamps are preserved, so queued data is never made to look newer than it is. Processing that takes at least one second logs a diagnostic warning. A failed writer stops the collector rather than silently leaving a connection with no database updates.

A quiet traffic stream is normal when there are no local aircraft. No inactivity reconnect runs by default. An optional --traffic-idle-seconds 20 can refresh a previously active but quiet connection; it cannot distinguish a stalled stream from normal traffic silence and may cause unnecessary reconnects. Leave it at zero normally. There is no forced refresh before the first traffic frame. The GUI remains independent of the collector.

## v0.3.4 save diagnostics

Every traffic log now includes reason=accepted or one or more rejection reasons (invalid position/speed flags, coordinates, age, altitude, or the one-second sample interval). It also shows the raw Position_valid, Speed_valid, Age and ExtrapolatedPosition fields. Save/retention rules are unchanged. Missing flags/age continue to be accepted under the existing older-feed compatibility rules. These diagnostics distinguish sampling from stale/invalid data without inferring freshness from moving coordinates.

### v0.3.5 estimated traffic

Install both FishFinder.py and traffic_display.py together. The collector migrates existing databases automatically. Valid Stratux extrapolations are saved at the normal one-second interval while position Age is at most 60 seconds; ordinary positions retain the 10-second limit. Invalid position/speed flags still reject reports. Estimated trail segments and projections are dashed purple, and aircraft labels show EST; symbols retain conflict colors. Estimated altitude never establishes vertical clearance. No extrapolation is invented when Stratux stops sending data. Existing rows default to observed. Twenty automated tests pass; Raspberry Pi display testing remains required.

### v0.3.6 Wi-Fi activation

Setup → Wi-Fi / Internet now lists saved Wi-Fi profiles. Tap a profile, then Connect to activate it; status reports success or failure. NetworkManager nmcli must be installed and the desktop user must have permission to activate connections. Add / edit network opens the profile editor; after saving, return and tap Refresh, then Connect. Saved credentials remain with NetworkManager. Connection work runs outside the GUI thread. Twenty existing tests and Python compilation pass; actual switching requires Pi testing.

### v0.4.0 offline flight simulator and splash

Stop the live collector before running these commands from the installed FishFinder directory (use two terminals):

```sh
./FishFinder.py --demo
./traffic_display.py --db /var/local/FishFinder/demo_objects.db --fullscreen --geometry 800x800
```

Use your existing DSI monitor geometry if HDMI is attached. Do not pass the display's old `--demo` flag: that remains the simple display-only demo, independent of the new collector simulator. The collector writes a separate demo_objects.db, never the live database by default. Both scripts accept `--db PATH` for a custom demo database with an existing parent directory. Stop the demo and restart the collector/display normally to return to Stratux.

The seed defaults to 22 (`FishFinder.py --demo-seed 123 --demo` changes it). Each run starts ten minutes into the scenario so aircraft are already airborne. Sampling, retention, identity tracking and database reads use the regular pipeline. Traffic is marked DEMO in the display and uses synthetic identifiers. No Stratux network request is made.

C172s fly two right-hand circuits per sortie, including a touch-and-go, at O22/17 (2 aircraft, 2,100 ft), E45/27 (1 aircraft, 2,933 ft), KCPU/31 (2 aircraft, 1,325 ft), O27/28 (1 aircraft, 234 ft). Runway threshold coordinates determine true alignment. Climb at 75 mph, about 500 fpm to 700 ft above the field; crosswind is 0.70 statute mile and climbs to 1,000 ft above the field. Downwind accelerates to 110 mph by midfield, slows to 70 mph by the base turn 0.5 statute mile before the approach threshold, descends to 500 ft above the field at final, then lands at the threshold. Speed changes interpolate; turns are the requested schematic right angles. All stored speeds are knots, heights feet, and map distances nautical miles. One-aircraft fields depart every ten minutes; two-aircraft fields alternate departures about every 5.5–5.8 minutes.

Airliners cross the region roughly once a minute at 28,000–32,000 ft and 480–510 kt. Random GA transits use 4,500–12,000 ft and 120–400 kt with a triangular distribution weighted toward slower speeds. Helicopters climb to 3,500 ft and fly at 80 kt between Columbia and E45, southwest out of the area, or southwest inbound. Ownship circles O22 at a 5 NM radius, 5,000 ft, 100 kt. Candidate flights are skipped if their one-second trajectory checks approach within 0.35 NM while less than 400 ft apart, including ownship; all simulated flights are geometrical scenarios, not terrain-aware route planning.

A calming blue/teal mountain splash displays for three seconds at startup. Tap to dismiss it, or use `--splash-seconds 0` to disable it. No new packages are needed beyond the existing Tkinter/websocket-client installation. Twenty-four automated tests pass, including an hour of separation checks, pattern geometry, deterministic generation, and the real database pipeline. Collector startup/shutdown was smoke-tested without network access. Raspberry Pi touch/fullscreen and visual testing remain required. Existing preview images depict earlier display examples; preview-splash.png shows the new splash artwork.
