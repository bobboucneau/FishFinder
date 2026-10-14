# Touch diagnostics — v0.4.9

Wake-up touch works but button actions fail on the user's Pi in v0.4.7/0.4.8, including without the map. The main hit-test/button handler is unchanged since v0.4.5. The supplied launcher contained `map-to-output 10 DSI-1` without the required `xinput` command, and hard-coded the window at +1920+0 despite only DSI being active. These are concrete launcher errors; correcting them is the first step. Hardware confirmation is still required.

Native Mac Tk tests performed actual wake, range, airport toggle, Exit/Cancel/Exit actions with and without a map process; all passed with no callback errors. Desktop generated events do not validate the Goodix hardware or its X11 mapping.

## Corrected launcher

DemoDisplay.bash maps the named Goodix pointer with xinput, reads the active DSI-1 geometry instead of assuming an HDMI offset, and stops on mapping/configuration errors. It supports a version-folder installation or a flat app directory and finds the installed virtual environment. It does not activate HDMI. Extra arguments are forwarded to the display. Launcher tests cover DSI at +0+0, +1920+0, and -800+0, plus safe failure on inactive output or mapping error.

Replace the old launcher in the existing v0.4.8 folder and make it executable; no display update is necessary to try the launcher repair:

```sh
chmod +x /usr/local/FishFinder/Fishfinder-v0.4.8/DemoDisplay.bash
startx /usr/local/FishFinder/Fishfinder-v0.4.8/DemoDisplay.bash
```

Use --touch-debug only with the v0.4.9 display; v0.4.8 does not accept that diagnostic flag.

## Further diagnostics

In an existing X terminal, the mapping that previously worked for this device was:

```sh
xinput map-to-output "pointer:10-0014 Goodix Capacitive TouchScreen" DSI-1
```

This is session-specific; rebooting or changing connected monitors can require reapplying it. If the name/output differs, inspect `xinput list` and `xrandr --listmonitors` rather than choosing an unverified device ID. The `pointer:` prefix avoids the identically named keyboard device.

Run the display with diagnostic output, initially without the map:

```sh
./traffic_display.py --demo --fullscreen --touch-debug 2>&1 | tee /tmp/fishfinder-touch.log
```

Wake the controls, then tap the center of 2 NM and Exit. Each received press prints raw canvas pixel coordinates, normalized 800-coordinate layout position, root-window coordinates, canvas size, idle state, active button count, matching handler, and detail/exit state. A magenta marker briefly indicates the received pixel position. Actual callbacks print TOUCH ACTION. The script path at startup identifies which copy is running. Main buttons have no persistence side effects except Setup Save.

- Marker away from finger or incorrect coordinates: investigate screen mapping/rotation/window placement.
- Canvas other than 800x800 on the 800x800 screen: investigate fullscreen monitor and window geometry. The GUI scales, but it must occupy the correct output.
- Every press idle=True: inspect saved idle_seconds and elapsed time between touches.
- match=... followed by a traceback: share the traceback; callback failure is distinct from missed hit testing.
- No received presses after the wake: inspect input delivery/driver behavior.
- A tap that only wakes idle controls intentionally does not activate a hidden button. The next tap should act.

Share the TOUCH lines and any traceback along with the launch command and whether HDMI is attached. Omit --touch-debug for normal display behavior. No input calibration is changed automatically by this build.
