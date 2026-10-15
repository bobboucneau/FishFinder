# FishFinder display launchers and collector service — v0.4.11

These instructions are for the Raspberry Pi running Debian/X11, as the normal user who already runs FishFinder successfully. Nothing is installed on this Mac. Collector service and display are independent: closing the display does not stop collection.

## Files

| File | Runs | Default database |
|---|---|---|
| Display.bash | Production graphical display, mapped to DSI-1/Goodix | /var/local/FishFinder/flying_objects.db |
| DemoDisplay.bash | Moving demo graphical display, same screen/touch mapping | /var/local/FishFinder/demo_objects.db |
| Finder.bash | Production Stratux collector, foreground for systemd supervision | /var/local/FishFinder/flying_objects.db |
| DemoFinder.bash | Offline demo collector, foreground for systemd supervision | /var/local/FishFinder/demo_objects.db |

Both collector launchers use unbuffered output and `exec`, so systemd supervises the Python process directly. They are not backgrounded with `&`, `nohup`, or a shell restart loop. A shared flock on /var/local/FishFinder/collector.lock prevents two launcher-started collectors from running at the same time. The lock file can remain after shutdown; do not delete it while a collector is running. Kernel locks release when the process exits. A direct `python3 FishFinder.py` invocation bypasses this launcher lock—stop manually started collectors first.

## 1. Place the package

Extract the complete package to:

```
/usr/local/FishFinder/FishFinder-v0.4.11
```

Preserve the existing virtual environment at `/usr/local/FishFinder/.venv`. The launchers also detect a .venv inside their own folder or the previous `/usr/local/Fishfinder/.venv` spelling. Linux paths are case-sensitive. Change the commands below if your actual folder uses different capitalization.

From the new package folder:

```sh
cd /usr/local/FishFinder/FishFinder-v0.4.11
chmod +x Display.bash DemoDisplay.bash Finder.bash DemoFinder.bash
```

Keep/copy your existing settings.json into this version folder, or provide the same FISHFINDER_SETTINGS path to both collector and display. New service installation defaults to this version folder's settings.json. An environment variable from your interactive shell is not automatically inherited by systemd. The service's generated Environment lines show the paths it will use.

The normal user needs read/execute access to the application/venv, write access to /var/local/FishFinder and existing database/WAL/SHM/lock files, and write access to settings/airport directories for GUI updates. The installer probes the collector's database/lock permissions as that normal user. It creates and assigns a new data directory if absent; it does not recursively change ownership of existing files. If existing root-owned files fail the probe, correct those specific owners/permissions first. Do not run the applications as root to work around it.

## 2. Preview/install a collector service

Stop manually launched collectors first. Use ONE of these modes. There is only one service name, `fishfinder-collector.service`; reinstalling in the other mode replaces its configuration and restarts it after the previous process stops. It also enables the chosen mode for future boots. It does not change networking, launch X, or enable console autologin unless you separately request --boot-ui.

Production (real Stratux):

```sh
python3 configure_pi.py --app-dir "$PWD" --python /usr/local/FishFinder/.venv/bin/python3
sudo python3 configure_pi.py --app-dir "$PWD" --python /usr/local/FishFinder/.venv/bin/python3 --install
```

Demo (no Stratux required):

```sh
python3 configure_pi.py --app-dir "$PWD" --python /usr/local/FishFinder/.venv/bin/python3 --demo
sudo python3 configure_pi.py --app-dir "$PWD" --python /usr/local/FishFinder/.venv/bin/python3 --demo --install
```

The first command only previews. Omit --python to auto-detect the venv. Installation uses the normal user named by SUDO_USER; if already in a root shell, add `--user YOUR_NORMAL_PI_USERNAME`. A root application user is rejected. The service explicitly sets interpreter, settings path, database path, and common lock path. Updating the application folder requires rerunning the installer so the unit points at the new version.

Existing managed unit configuration is backed up once. No second production/demo service is created. If you already installed unrelated custom services for FishFinder, stop/disable those yourself before enabling this one.

## 3. Check/manage the service

```sh
systemctl status fishfinder-collector --no-pager
journalctl -u fishfinder-collector -f
```

Ctrl-C leaves the log viewer, not the collector. INFO traffic/save-decision lines appear in this journal.

```sh
sudo systemctl stop fishfinder-collector
sudo systemctl start fishfinder-collector
sudo systemctl restart fishfinder-collector
sudo systemctl disable --now fishfinder-collector
```

Restart=always restarts an unexpectedly exited collector after five seconds. Explicit `systemctl stop` stays stopped. SIGINT requests orderly Python shutdown; after 20 seconds systemd may force termination. Exit 75 means another launcher owns the lock and suppresses a restart loop; stop that collector and run systemctl start again. Unreachable Stratux is expected in production without its network: the existing collector waits/retries.

## 4. Launch the matching display manually

From the text console (no X session already running):

Production:

```sh
startx /usr/local/FishFinder/FishFinder-v0.4.11/Display.bash
```

Demo:

```sh
startx /usr/local/FishFinder/FishFinder-v0.4.11/DemoDisplay.bash
```

If already inside an X terminal, run `./Display.bash` or `./DemoDisplay.bash` directly instead of starting another X server. Do not use sudo startx. Both display launchers detect active DSI-1 geometry and map the named Goodix pointer, stopping if either fails. They do not turn on HDMI. Display Exit closes the app/X session; the service keeps running. Use the demo collector with DemoDisplay, and production collector with Display, so they read the same database.

To switch modes: stop the display, run the installer for the other collector mode, and start the matching display. There is no need to reboot. You can also run Finder.bash or DemoFinder.bash manually after stopping the service; stop the manual process before starting the service again.

Optional overrides for shell launchers: FISHFINDER_PYTHON (interpreter); FISHFINDER_TOUCH_DEVICE (display pointer name); FISHFINDER_SETTINGS (settings file). Collector wrappers additionally accept FISHFINDER_DATABASE and FISHFINDER_LOCK_FILE; avoid changing the common lock path between modes. Mode and --db arguments cannot be overridden through extra command-line options; choose the correct launcher. Other collector options such as --log-level DEBUG or --demo-seed 22 are forwarded. Do not pass --demo to Finder.bash.

## Verification and later headless startup

Automated tests cover both display mappings/databases, mode-specific collector arguments, shared-lock exclusion/release, generated one-service configuration, venv detection and shell syntax. They use test stubs on the Mac; actual Linux systemd startup/restart, lock utility, boot and Stratux networking must be checked on the Pi.

After the collector service and manual display launch pass, see PI-STARTUP.md for optional tty1/autologin/startx boot setup. That is separate from installing just the collector service.
