#!/bin/bash
# Run in foreground: systemd supervises this process; do not append & here.
# Shell-reading guide: $NAME reads a variable; ${NAME:-fallback} supplies a
# default; "$@" forwards the caller's arguments individually, preserving spaces.
# Exit on failed commands, unset variables, and failures inside a pipeline.
set -euo pipefail
# Find the folder containing THIS launcher, independent of where it was called.
# Keeping the program folder separate from /var/local/FishFinder preserves data.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
# Prefer the explicitly selected virtual environment; do not accidentally use a
# system interpreter missing the collector/display dependencies.
PYTHON=${FISHFINDER_PYTHON:-}
if [[ -z "$PYTHON" ]]; then
    for candidate in "$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/../.venv/bin/python3" /usr/local/FishFinder/.venv/bin/python3 /usr/local/Fishfinder/.venv/bin/python3; do
        if [[ -x "$candidate" ]]; then PYTHON=$candidate; break; fi
    done
fi
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
    echo 'Cannot find the FishFinder virtual-environment Python. Set FISHFINDER_PYTHON to its full path.' >&2
    exit 1
fi


# Reject arguments that would contradict the mode/database chosen by this
# launcher. A production service and demo service must not share live records.
for arg in "$@"; do
    case "$arg" in
        --demo|--demo=*|--db|--db=*) echo 'Mode and database are selected by this launcher, not extra arguments.' >&2; exit 2 ;;
    esac
done
if ! command -v flock >/dev/null 2>&1; then
    echo 'flock is required (Debian package: util-linux).' >&2
    exit 1
fi
DATABASE=${FISHFINDER_DATABASE:-/var/local/FishFinder/demo_objects.db}
LOCK_FILE=${FISHFINDER_LOCK_FILE:-/var/local/FishFinder/collector.lock}
# Descriptor 9 survives exec and releases automatically when the collector exits.
# Open a numbered file handle and take a nonblocking exclusive lock. This keeps
# Finder and DemoFinder from accidentally starting competing collectors.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo 'Another Finder/DemoFinder launcher already holds the collector lock. Stop it first.' >&2
    exit 75
fi
echo "FishFinder demo collector: database=$DATABASE python=$PYTHON"
# exec replaces this shell with Python. The service tracks the real program,
# and signals/exit status reach it directly. -u makes log output appear promptly.
exec "$PYTHON" -u "$SCRIPT_DIR/FishFinder.py" --demo --db "$DATABASE" "$@"
