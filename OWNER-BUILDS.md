# Your FishFinder, your code: owner builds and normal updates

This is an operational guide, not a suggestion to improvise a Linux installation. Commands below target the FishFinder Raspberry Pi prototype: user **fish**, Debian/Raspberry Pi OS, X11 on the 800×800 DSI display. Use one Terminal session for each numbered procedure; variables do not carry into a new Terminal window.

**Ordinary FishFinder updates require no sudo after the one-time migration.** Linux packages, drivers, systemd configuration, and the initial console setup remain administrator work. No update downloads, dependency installation, or arbitrary post-install hooks run automatically.

A code update deliberately interrupts the display. Perform updates on the ground when the device is not needed. Retain the previous installation and access to the Pi console/SSH until you have tested startup and reboot.

## 1. Understand the folders

The managed installation is `/home/fish/.local/share/FishFinder`:

| Folder/file | Meaning |
|---|---|
| `bootstrap/` | Stable launcher, verifier, release/build commands and X-session wrapper. Ordinary app updates do not replace these. |
| `venv/` | User-owned Python runtime. The old `/usr/local/FishFinder/.venv` is retained separately. |
| `releases/` | One immutable-by-convention directory per build ID; active code never gets overwritten. |
| `shared/settings.json` | Settings used by both collector and display across releases. |
| `shared/networks.json` | Friendly network associations; passwords remain in NetworkManager. |
| `shared/airports.json` | Writable airport cache, retained across updates. |
| `shared/network-session.json` | Transient selected receiver association; recreated when needed. |
| `inbox/` | Packages, external manifests and optional signatures awaiting staging. |
| `state.json` | Current/previous release, startup trial and official sequence high-water mark. Do not edit while running. |
| `pending.json` | A staged release and its approval/defer policy. Staging alone never runs it. |
| `runtime/` | Logs, heartbeat and owner rollback request. |
| `trusted-keys/` | Public keys the owner has independently chosen to trust. No private signing keys belong here. |

Existing databases and the large map archive remain in `/var/local/FishFinder`. A code rollback does **not** undo changes to shared settings, airport data or databases. This release makes no database schema change; future incompatible migrations need their own backup/recovery plan.

## 2. One-time prototype migration (administrator step)

The prepared migration helper on this prototype contains the exact commands and paths. Run it from the Mac:

```bash
ssh -t -i ~/.ssh/fishfinder_ed25519 fish@10.0.0.6 'bash /home/fish/install-fishfinder-bootstrap-v0.4.30.bash'
```

It previews the fixed system service, then invokes the installer using sudo. Enter the **Pi user's sudo password**, not an SSH-key passphrase, when asked. This is the one-time administrator boundary.

The initial v0.4.30 package is intentionally an **owner build**: no publisher signing key has been configured yet. The helper explicitly supplies `--owner-build`; no unsigned package is described as an official signed release.

The installer verifies/extracts initial code as `fish`, copies existing settings/networks/airport cache to shared storage, validates the fixed systemd unit, then stops the old version-specific services and starts `fishfinder-appliance.service`. Existing version folders and the old virtual environment remain in place. Applications and subsequent package operations run as fish; the service's only fixed privileged startup command selects console VT8 before starting X as fish.

If preparing another Pi rather than this pre-staged prototype, first install the existing OS dependencies (Python with Tk/venv, Xorg/xinit/startx, xrandr, xinput, xset, util-linux/flock and NetworkManager). Obtain and extract the source release ZIP. As the normal Pi user, create the runtime:

```bash
FF="$HOME/.local/share/FishFinder"
python3 -m venv "$FF/venv"
"$FF/venv/bin/python3" -m pip install --only-binary=:all: -r /path/to/extracted/FishFinder-v0.4.30/requirements-bootstrap.txt
```

Then preview/install with explicit paths (replace `/path/to/...` with your actual downloaded/extracted locations; do not type those placeholders literally):

```bash
PY="$HOME/.local/share/FishFinder/venv/bin/python3"
APP=/path/to/extracted/FishFinder-v0.4.30
"$PY" "$APP/configure_bootstrap.py" --python "$PY" \
  --previous-app /path/to/your/working/FishFinder-folder \
  --archive /path/to/FishFinder-v0.4.30.zip \
  --manifest /path/to/FishFinder-v0.4.30.manifest.json --owner-build --demo
# Review that preview. Repeat the same arguments with sudo and --install:
sudo "$PY" "$APP/configure_bootstrap.py" --python "$PY" \
  --previous-app /path/to/your/working/FishFinder-folder \
  --archive /path/to/FishFinder-v0.4.30.zip \
  --manifest /path/to/FishFinder-v0.4.30.manifest.json --owner-build --demo --install
```

`--demo` selects the bench collector/database. Omit it from both commands for live operation. Ordinary code updates retain the mode chosen in this stable configuration. Changing the appliance's operating mode is separate from installing new code; it is not inferred from network availability.

Expected result: a brief splash/progress screen, then FishFinder. Check the displayed version, moving demo traffic, touch response, map and indicators. After 15 seconds of fresh display heartbeats with the collector process alive, the launcher records startup success. **That is a liveness check, not complete functional validation.** Once satisfied, reboot using your normal Pi procedure and check automatic launch. Reboot/hardware migration validation is required before declaring the installation complete.

## 3. Set up command shortcuts (no sudo)

Run these lines on the Pi in your normal-user terminal. They only assign shell variables:

```bash
FF="$HOME/.local/share/FishFinder"
PY="$FF/venv/bin/python3"
BOOT="$FF/bootstrap"
"$PY" "$BOOT/release_tools.py" --home "$FF" status
```

The status output shows `current`, `previous`, `trial`, `high_watermark`, and any pending update. `trial: null` means startup liveness was accepted. A non-null trial shortly after installation is normal.

## 4. Build your own modified version — exact prototype procedure

You do **not** need our signing key or permission to modify your installed application. The owner-build route bypasses publisher signature authentication only; it still checks hashes, archive paths, limits and compatibility fields.

First copy the currently selected source into a new, editable directory. This preserves the running release:

```bash
FF="$HOME/.local/share/FishFinder"
PY="$FF/venv/bin/python3"
BOOT="$FF/bootstrap"
CURRENT=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["current"])' "$FF/state.json")
SOURCE="$HOME/FishFinder-owner-source-$(date +%Y%m%d-%H%M%S)"
cp -a "$FF/releases/$CURRENT" "$SOURCE"
echo "Editable source: $SOURCE"
```

Edit your copy. A first harmless practice change can be an extra comment, rather than changing flight behavior:

```bash
nano "$SOURCE/traffic_display.py"
```

In nano, save with Ctrl+O, Enter, then exit with Ctrl+X. Check that Python can parse your edits:

```bash
"$PY" -m py_compile "$SOURCE/traffic_display.py"
```

No output means that file's syntax check passed. It does not establish correct behavior. Run relevant tests for the code you changed; focused updater/health tests are small:

```bash
cd "$SOURCE"
"$PY" -m unittest -q test_release_manager test_system_health test_screen_sleep
```

Do not run unrestricted test discovery on the small Pi until the earlier download-heavy tests have been addressed.

Give each build a **new ID**. Reusing an existing ID is refused, so an installed release is never silently replaced:

```bash
BUILD_ID="owner-$(date +%Y%m%d-%H%M%S)"
"$PY" "$BOOT/build_release.py" --source "$SOURCE" --id "$BUILD_ID" \
  --sequence 1 --output "$FF/inbox"
```

Expected output: paths to `FishFinder-$BUILD_ID.zip` and `FishFinder-$BUILD_ID.manifest.json`, followed by an unsigned-owner-build notice. The builder recalculates internal checksums after your edits. It packages only files explicitly listed in VERSION.json; it does not sweep settings, Git metadata, databases or arbitrary files from your directory.

If you add a new Python module, include it explicitly while building, for example `--include my_new_module.py`. Never include private data. Owner sequence numbers are recorded but do not advance the official-release high-water mark; a unique build ID is still mandatory.

Stage your build, explicitly acknowledging that it is owner-modified:

```bash
"$PY" "$BOOT/release_tools.py" --home "$FF" stage \
  "$FF/inbox/FishFinder-$BUILD_ID.zip" \
  --manifest "$FF/inbox/FishFinder-$BUILD_ID.manifest.json" --owner-build
```

No sudo. The display should offer:

- **Install now:** stop the apps, switch the selected release, restart and check liveness.
- **Next startup:** approve installation for the next launcher startup/power-on.
- **Later:** continue using the current release; ask again at the next startup.

Owner builds carry an `OWNER BUILD` label. Staging does not activate the code before your choice. If the launcher is not running, the pending update is considered at its next startup. The owner-built package still requires the already-installed OS/runtime dependencies. The updater will not install missing pip packages or run setup scripts on your behalf.

You can instead use Setup → Receiver / Updates → Code updates, choose the inbox ZIP, explicitly check **Owner-modified build**, then **Verify and stage**. The same launcher approval follows.

## 5. Restore the previous version (no sudo)

From a normal-user Pi terminal:

```bash
FF="$HOME/.local/share/FishFinder"
PY="$FF/venv/bin/python3"
BOOT="$FF/bootstrap"
"$PY" "$BOOT/release_tools.py" --home "$FF" rollback
```

This requests a controlled restart into the retained previous release. If the launcher is stopped, it processes the request at next startup. `rollback` refuses if no previous version exists. Inspect `status` afterward to confirm the selected version. It changes code selection only, not shared user data.

If a new release fails startup or stops heartbeating during its startup trial, the launcher automatically restores the previous code when available. A power interruption during an unaccepted trial also restores the previous release on next start. The first installation has no previous managed release; repeated startup failure leaves an explanatory progress screen and logs for diagnosis rather than inventing a fallback.

## 6. Official signed updates

Obtain three matching files: `FishFinder-VERSION.zip`, `FishFinder-VERSION.manifest.json`, and `FishFinder-VERSION.sig`. Transfer all three to `$FF/inbox`. The name is a convenience; checksums and signatures, not the filename, establish the match.

A trusted **public key** must already have been installed independently. Compare its fingerprint with the publisher through a separate trusted channel. Do not trust a replacement key merely because an update download includes one.

As the owner, deliberately install an independently verified public key:

```bash
"$PY" "$BOOT/release_tools.py" --home "$FF" trust-key \
  /path/to/verified-publisher-public.pem --owner-authorized
```

That is a local owner decision, not a remote key-rotation mechanism. Additional keys can be installed this way; remove a retired key from `$FF/trusted-keys` only after verifying its replacement. No automatic signing-key rotation is implemented.

Stage the official release **without** `--owner-build`:

```bash
"$PY" "$BOOT/release_tools.py" --home "$FF" stage \
  "$FF/inbox/FishFinder-VERSION.zip" \
  --manifest "$FF/inbox/FishFinder-VERSION.manifest.json" \
  --signature "$FF/inbox/FishFinder-VERSION.sig"
```

Expected result: signature verification succeeds, a pending update is recorded, then the same approval screen appears. Missing/invalid signatures, damaged files, invalid paths, unsupported bootstrap API/Python/platform or non-newer official sequence numbers are rejected before activation. Failed verification leaves the current version running.

Official sequence numbers must increase. Retained local rollback is deliberately allowed; replaying an old official download as a new update is not. This small offline-friendly verifier does not implement the complete TUF protocol, online freshness/expiry metadata, revocation service or HTTPS download server. We have not configured an automatic release server yet. Offline startup never depends on reaching one.

## 7. Publishing/signing your own releases

Use a development machine with Python and the `cryptography` package installed. Never put a private key in the source tree, on GitHub, in an update ZIP or on distributed devices.

Create an encrypted Ed25519 private key once:

```bash
python3 release_tools.py keygen \
  --private "$HOME/FishFinder-signing/publisher-private.pem" \
  --public "$HOME/FishFinder-signing/publisher-public.pem"
```

The command prompts twice for a passphrase of at least 12 characters and refuses to overwrite existing keys. Keep an encrypted backup and the passphrase securely; losing either prevents signing with that identity. Share the public key and its verified fingerprint, not the private key. Devices need only the public key.

Build and sign using an increasing official sequence number:

```bash
python3 build_release.py --source /path/to/FishFinder-source \
  --id 0.4.31 --sequence 2026110101 --output "$HOME/FishFinder-published" \
  --private-key "$HOME/FishFinder-signing/publisher-private.pem"
```

The command prompts for the private-key passphrase. Expected outputs: ZIP, manifest and detached signature. Copy those three files to the chosen release host. A ZIP checksum is not an authenticity check by itself; the signature covers the exact external manifest bytes, including its ZIP checksum, size, release ID, sequence and compatibility fields. Do not edit or reformat a manifest after signing it.

## 8. Troubleshooting and recovery

- **Permission denied:** confirm you are the normal owner of `$FF` and using `$FF/venv/bin/python3`. Do not run normal updates as root; that creates ownership problems.
- **No trusted key / invalid signature:** obtain the matching files and independently verified public key. Do not silently switch an alleged official download to owner mode.
- **Release already installed:** choose a new owner build ID or deliberately roll back to a retained version.
- **Official release not newer:** check its sequence. Use local rollback for an old retained release; do not erase the high-water mark to defeat the check.
- **Update needs another bootstrap API/runtime:** follow separate, reviewed bootstrap/runtime upgrade instructions. Ordinary app packages cannot replace the stable launcher.
- **No popup:** run `status`; check the appliance service and `pending.json` policy. `defer ask` requests the normal prompt again on a new launcher startup; a Later choice is intentionally not repeatedly nagged during the same session.
- **Startup failures:** read `$FF/runtime/display.log` and `collector.log`, and `journalctl -u fishfinder-appliance -n 50 --no-pager`. These include technical details; the display shows the short explanation.
- **Normal Exit:** closes the display but leaves collector and launcher running. Restart the appliance service as an administrator or power-cycle to reopen the display; an approved update also restarts it.
- **Emergency return to pre-bootstrap setup:** as an administrator, stop/disable `fishfinder-appliance`, then run the retained `/home/fish/activate-fishfinder-v0.4.29.bash`. This restores the prior version-specific collector/display procedure. It requires sudo because it changes system services; ordinary managed app rollback does not.

The public-key checks protect release distribution. They are not a security boundary against someone who controls the fish account and can edit its launcher, keys, settings and code. Owners intentionally retain that control. Licensing decisions remain in LICENSING-PLAN.md; this mechanism does not apply a formal project license.
