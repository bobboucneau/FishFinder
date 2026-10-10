# Raspberry Pi collector service and console display

Run applications as the same normal Pi user you tested manually. The installer runs as root only to register systemd files. It does not install packages, copy application code, change networking, or start X on this Mac.

Install the full FishFinder package in `/usr/local/Fishfinder`, preserving `.venv` and `settings.json`. The normal user must be able to write `/var/local/FishFinder`, settings and airport data. Stop any manually running collector before enabling the service, and stop the display before changing its launch configuration.

## 1. Collector only: try this first

From the FishFinder directory on the Pi, preview the generated service:

```sh
python3 configure_pi.py
```

Then install using the normal user who invoked sudo:

```sh
sudo python3 configure_pi.py --install
systemctl status fishfinder-collector --no-pager
journalctl -u fishfinder-collector -f
```

Use `--user YOUR_PI_USERNAME` if invoking from a root shell. For bench simulation add `--demo` to the installer; the service then uses demo_objects.db. Rerun without `--demo` for real Stratux collection. Every installation restarts the collector. GUI launching remains manual at this stage:

```sh
/usr/local/Fishfinder/.venv/bin/python3 /usr/local/Fishfinder/traffic_display.py --fullscreen
```

Use `--demo` for the display when the service is in demo mode. Stop, restart or disable collector autostart:

```sh
sudo systemctl stop fishfinder-collector
sudo systemctl restart fishfinder-collector
sudo systemctl disable --now fishfinder-collector
```

Restart=always keeps collection running after crashes; an explicit systemctl stop remains stopped. SIGINT permits the existing collector's orderly shutdown; after 20 seconds systemd can force termination. Initial lack of Stratux is normal: the collector waits and retries.

## 2. Console boot and automatic X/display

This is console X11 startup, not desktop/Wayland autostart. First ensure xinit/Xorg are installed and `startx` works as your normal console user, as in your current testing. Optional `openbox` provides a lightweight window manager for reliable fullscreen placement; xrandr and xinput handle DSI geometry and the Goodix pointer mapping. They are not installed by this script.

Select **console boot without autologin** using Raspberry Pi configuration (on Raspberry Pi OS, `sudo raspi-config`, System Options → Boot / Auto Login → Console). On other Debian installations choose the equivalent console boot setup. Reboot so the graphical display manager is no longer running. The installer refuses to add startx when a desktop display manager is active or an existing tty1 override needs review.

From a normal Pi-user shell, preview and then install:

```sh
python3 configure_pi.py --boot-ui
sudo python3 configure_pi.py --install --boot-ui
sudo reboot
```

Add `--demo` to both installer commands for the current bench test. This also updates the collector service and makes the display use the same demo database. Use exactly the same `--user` and `--app-dir` options in both commands if overriding defaults.

At boot, tty1 logs in automatically as that user and runs a managed X session through startx. **Anyone at the device can use that logged-in account**; this is an intentional appliance convenience. SSH sessions do not launch X. The installer appends a small source line to the existing bash login file and leaves `.xinitrc` untouched. Existing managed files are backed up once with `.fishfinder-backup` suffixes. Previously saved settings remain unchanged.

With only DSI attached, the display uses its 800×800 geometry. If HDMI is attached, the launcher discovers DSI-1's offset, makes DSI primary for this X session, and maps `pointer:10-0014 Goodix Capacitive TouchScreen` to it. A changed touchscreen name needs updating in `~/.local/bin/fishfinder-xsession`. The display waits for data independently of the collector, so startup order need not match.

Display/session logs:

```sh
tail -f ~/.local/state/fishfinder/display.log
```

Exit ends X and returns to the console; the collector continues. To launch the display again from the console:

```sh
startx "$HOME/.local/bin/fishfinder-xsession" -- :0 vt1
```

## Disabling or undoing automatic display startup

Disable it for subsequent console logins/boots:

```sh
touch ~/.fishfinder-no-autostart
```

Remove that file to re-enable. To undo console autologin as well:

```sh
sudo rm /etc/systemd/system/getty@tty1.service.d/fishfinder.conf
sudo systemctl daemon-reload
```

Keep any unrelated getty configuration. Remove the two FishFinder source lines from your bash login file if desired; removing the managed launcher alone while leaving the source lines will produce an error. Backups preserve prior contents, but restore them only after checking for your subsequent edits. Returning to desktop boot is a separate Pi configuration choice.

Validation: Python generation and shell syntax were checked on the Mac; application tests passed. Actual systemd, console-seat access, X startup, touchscreen and reboot behavior require Pi testing. Recommended order: collector service → manual startx launcher → optional boot setup → reboot with HDMI, keyboard and mouse disconnected.
