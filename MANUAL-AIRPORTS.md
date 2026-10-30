# Manual airport selection — v0.4.32

Wake the controls with a double tap, then choose Airport. Use the large A–Z/0–9 keys to enter O22, KGOO, KCPU or another 1–7-character code. Go validates the code before opening the same full-screen airport reference used by map taps. Back dismisses the selector; Clear and backspace permit corrections. Failed lookup preserves the entry. Display/local codes such as O22 resolve to their cached canonical identifier (KO22); ambiguous aliases are rejected instead of guessed.

Typed selections are saved as manual_airport in the shared settings file and restored on application restart. Back to traffic closes the visible page without forgetting the typed selection. Select airport on the reference page reopens the selector. Existing map taps remain ad-hoc browsing and do not change the remembered typed preference.

Nearby airports explicitly clears the pinned preference and offers the nearest 20 airports within 200 NM of a fresh ownship position, four per page. Prev/Next remain visible and disabled at the ends. The Nearby list is a snapshot at selection time so rows do not move under a finger; the selected airport's reference-page distance/bearing then updates with current ownship. A missing fix does not guess a location from nearby traffic.

Both typed and map-selected airport pages show initial great-circle bearing labeled TRUE and distance to the airport reference point in nautical miles. This is informational, not a route, heading instruction, magnetic bearing or runway-threshold distance. Computation uses the fresh ownship position selected by the display (including configured ADS-B ownship preference). No fresh usable position means Ownship position unavailable. Near-coincident positions show At airport rather than an arbitrary bearing.

Selection changes no actual GPS, traffic history, zoom/range or map-center setting. Existing data validity, tower status, pattern arrows, source and FAA cycle notices remain. This release does not add weather, flight planning or navigation functions.

Verification: seven new deterministic lookup/navigation/persistence tests plus existing airport/reference/touch/status regressions; native 800×800 keypad layout inspected. A pre-existing arrow-color test fixture now uses in-memory fixed validity dates so that the style test does not fail merely because the shipped FAA cycle expires. This does not change real airport data or its expiry checks. Physical Pi touch testing remains a user check after staging.
