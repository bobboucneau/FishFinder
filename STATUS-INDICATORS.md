# Display status indicators — v0.4.26

The main display keeps small Stratux, GPS and Temp indicators visible when controls hide. Green means current/normal, amber attention, red failed/critical and gray unknown. Demo receiver/position indicators explicitly say DEMO; hardware checks remain real.

Stratux reflects the collector situation/API reachability probe refreshed within 15 seconds. It does not prove the traffic WebSocket or radio is receiving; no nearby aircraft is not a fault. GPS reflects the usable ownship position selected by the display, including configured ADS-B ownship fallback; it does not specifically certify the receiver's GPS hardware.

Temperature is green below 75 C, amber at 75 C and red at 80 C. These are application warning thresholds. Raspberry Pi documents thermal throttling in the 80–85 C range: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html . A firmware temperature query is preferred, with Linux thermal-zone fallback. Missing/stale measurements are unknown.

Read-only hardware probes run off the touch/UI thread every five seconds. Firmware subprocesses have one-second timeouts. Current undervoltage and throttling/speed-limit flags produce warnings; historical flags do not masquerade as current faults.

Memory warnings use /proc/meminfo MemAvailable, not MemFree or the map file size. LOW: available below max(96 MiB, 10% RAM). CRITICAL: below max(48 MiB, 5% RAM). Warning clears on recovery. No normal memory indicator is displayed. This heuristic cannot guarantee warning before a rapid out-of-memory kill, and does not allocate memory or change swap/system configuration.

Database read failures and known startup write-permission failures remain visible. These checks do not constitute continuous disk-space, collector-write or filesystem-integrity monitoring.

Focused tests: python3 -m unittest -v test_system_health . These eight tests use fixed/mocked inputs, no data download and no large allocations. Do not use an unrestricted test discovery run on the memory-constrained Pi until the earlier download-heavy validation issue is resolved. Mac layout checked with the production Tk renderer; actual Pi touch and operational status transition checks remain required before claiming hardware validation.

Install using the existing version-folder procedure, retaining settings.json and the external map file. For the current prototype, the supplied activate-fishfinder-v0.4.26.bash switches the demo collector and launches the round display. v0.4.25 remains available for rollback. No startup/network selection changes and no web-demo changes are included.
