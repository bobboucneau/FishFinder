# FishFinder 0.4.45 — Demo controls in Setup

Setup → Demo provides an airport identifier, Start / restart demo, and Return to live traffic. Confirm the change to restart both application processes safely. A DEMO indicator remains visible. The chosen operation mode and airport persist across power cycles.

O22 retains the original four-airport scenario. Other airports use their published runway endpoints and field elevation for two synthetic C172 pattern aircraft, local helicopter trips, and passing traffic. Ownship circles five NM away at field elevation + 2,900 ft. These are invented demonstration patterns, not approved airport procedures. Airports without usable elevation/runway coordinates are rejected before stopping the application.

Live data and Wi-Fi profiles are preserved. Switching into demo resets ONLY demo_objects.db and its SQLite sidecars after both processes stop, removing trails from an earlier demo location. Returning to live uses flying_objects.db. No database paths are accepted from the display request.

## Existing appliance installation

Stage/install the application normally. Also replace the user-owned stable bootstrap.py and add demo_control.py in ~/.local/share/FishFinder/bootstrap/, preserving a backup. Reboot once to load this updated launcher. No new sudo permissions or system service changes are needed. New configure_bootstrap.py installations copy the helper automatically. An old launcher shows a restart message instead of silently ignoring mode requests.

To use: Setup → Demo → enter O22 or another airport code → Start / restart demo → Confirm change. Acknowledge the startup notice after restart. To resume receiver data: Setup → Demo → Return to live traffic → Confirm change. The normal network workflow applies in live mode.

The settings page and generated trajectories were checked on Mac; focused tests also run on the target Pi before staging. Touch interaction and live/demo round-trip remain hardware acceptance checks.
