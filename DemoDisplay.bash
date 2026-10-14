#!/bin/bash
# Start the moving demo on DSI-1 and map its Goodix pointer before launching.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

for command in xrandr xinput; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command missing: $command" >&2
        exit 1
    fi
done

GEOMETRY=$(xrandr --query | awk '$1 == "DSI-1" && $2 == "connected" { for (i=3; i<=NF; i++) if ($i ~ /^[0-9]+x[0-9]+[+-][0-9]+[+-][0-9]+$/) { print $i; exit } }')
if [[ -z "$GEOMETRY" ]]; then
    echo 'DSI-1 is not active. Current display configuration:' >&2
    xrandr --query >&2
    exit 1
fi

# IDs can change between X sessions. The pointer prefix disambiguates the
# identically named keyboard device; this name matches Bob's Goodix hardware.
TOUCH_DEVICE=${FISHFINDER_TOUCH_DEVICE:-pointer:10-0014 Goodix Capacitive TouchScreen}
if ! xinput map-to-output "$TOUCH_DEVICE" DSI-1; then
    echo "Could not map touchscreen '$TOUCH_DEVICE' to DSI-1." >&2
    xinput list >&2
    exit 1
fi

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

echo "FishFinder demo: display=$GEOMETRY touch=$TOUCH_DEVICE python=$PYTHON"
exec "$PYTHON" "$SCRIPT_DIR/traffic_display.py" --demo \
    --db /var/local/FishFinder/demo_objects.db --geometry "$GEOMETRY" --fullscreen "$@"
