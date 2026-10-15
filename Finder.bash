#!/bin/bash
# Run in foreground: systemd supervises this process; do not append & here.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
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


for arg in "$@"; do
    case "$arg" in
        --demo|--demo=*|--db|--db=*) echo 'Mode and database are selected by this launcher, not extra arguments.' >&2; exit 2 ;;
    esac
done
if ! command -v flock >/dev/null 2>&1; then
    echo 'flock is required (Debian package: util-linux).' >&2
    exit 1
fi
DATABASE=${FISHFINDER_DATABASE:-/var/local/FishFinder/flying_objects.db}
LOCK_FILE=${FISHFINDER_LOCK_FILE:-/var/local/FishFinder/collector.lock}
# Descriptor 9 survives exec and releases automatically when the collector exits.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo 'Another Finder/DemoFinder launcher already holds the collector lock. Stop it first.' >&2
    exit 75
fi
echo "FishFinder production collector: database=$DATABASE python=$PYTHON"
exec "$PYTHON" -u "$SCRIPT_DIR/FishFinder.py" --db "$DATABASE" "$@"
