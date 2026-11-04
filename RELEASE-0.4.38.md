# FishFinder 0.4.38 — update prompt and checkbox alignment

Setup Display checkboxes now share the form grid and align just inside its label
column, instead of starting at the far-left edge of the containing page.

The bootstrap update prompt uses the same rounded controls as the application:
separate heading, prominent release ID, owner/signature classification, explanatory
text, and equal-width Install now / Next startup buttons with Later underneath.
Approval and deferral behavior is unchanged.

The prompt belongs to the stable launcher. Ordinary app installation does not
replace that launcher. For this prototype we back up its bootstrap.py, then install
the matching bootstrap.py and ff_controls.py as fish, using same-directory atomic
renames. The currently running Python process keeps its old code until the next
normal reboot. No system unit, sudo permission, trusted key, or release-manager
file is replaced. Future new-device provisioning includes ff_controls.py.

Checks: native 800×800 previews of both screens, focused launcher/settings and
application tests on Mac/Pi. No test invokes a real installation approval or reboot.
