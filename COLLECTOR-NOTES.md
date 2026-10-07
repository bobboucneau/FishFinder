# Proposed FishFinder collector

`FishFinder.py` replaces the master collector and standalone OwnShip.py.

## Behavior

- One database path: `/var/local/FishFinder/flying_objects.db`.
- Separate traffic, ownship, and cleanup threads; each owns its SQLite connection.
- Ownship polls every three seconds with a five-second HTTP timeout.
- Cleanup waits three seconds between runs, retains five minutes of ownship/traffic history (110 ownship rows and 600 reports per tail as safety caps), and removes aircraft from the active table after sixty seconds without updates. Traffic positions are sampled at most once per second per aircraft.
- Traffic reconnects after the WebSocket exits, with a five-second delay.
- Ctrl+C requests shutdown and closes connections.
- Zero speed/altitude and valid coordinates that sum to zero are accepted. Explicit false position/speed validity flags and a zero GPS fix quality are rejected.

## Before running on the target machine

1. Stop the old master script and OwnShip.py, including any services that restart them.
2. Back up the existing database. If moving it from `/usr/local/FishFinder`, use SQLite's backup facility or stop all writers and checkpoint/close the database before copying it. Do not copy only the `.db` file while WAL writers are active.
3. Ensure `/var/local/FishFinder` exists and the account running the script can write the directory and database. WAL creates companion files in the same directory.
4. Ensure the target Python environment has `websocket-client` (imported as `websocket`). The unrelated `websocket` package is not a substitute.
5. Run `python3 FishFinder.py` and inspect logs and database contents.

## Compatibility and limits

Existing tables are reused without migrating their column types. Newly created tables use REAL for coordinates, speed, altitude, and timestamps; existing TEXT coordinate columns retain their original affinity. Table and column names remain compatible with the supplied scripts.

Ownship uses GPSAltitude exactly as supplied in the original code, with no unit conversion. Some Stratux versions also expose GPSAltitudeMSL; verify the desired field, altitude reference and units on your actual device before using altitude comparisons. Traffic Alt and ownship GPS altitude need not have the same reference.

Aircraft now use Icao_addr as a stable key when available. The legacy tail column stores keys such as icao:ABCDEF; new registration and callsign columns hold display labels. With no valid address, registration is the fallback, followed by callsign. Label-only fallback cannot reliably link later callsign changes. Unnamed targets with a valid address are collected. Existing rows are preserved and expire normally; they cannot be reliably linked without their missing original addresses.

Timestamps represent receipt/poll time, not the age of the underlying GPS fix or traffic observation. Explicit invalid flags are rejected when present; when flags are absent, numeric validation is used. Detecting stale fixes requires verification of your device's timestamp fields. No range filtering or report deduplication is added.

Verification used a temporary SQLite database and simulated data. Checked: zero values, cancelling coordinates, invalid fix flags, five-minute history, one-second sampling, separate sixty-second active timeout, retention safety caps, WAL, and simultaneous writer/cleanup connections. No live Stratux, production database, real network recovery, or hardware shutdown test was performed.

The expanded-history collector uses SQLite window functions and requires SQLite 3.25 or newer. Startup checks this before collecting.

Identity upgrade: stop both programs and back up the database before replacing the collector and display. Initialization adds registration/callsign columns to aircraft idempotently. Existing tail-based consumers will now see stable identity strings, not registration labels. No proximity-based merging is attempted.
