# FishFinder 0.4.48 — Config and Support

- Fresh Start appears after a startup corruption check fails. It saves the latest damaged database and its SQLite sidecars, then restarts FishFinder with a clean database. Each successful recovery replaces the previous damaged archive and clears the previous support export.
- Support can create a local ZIP with recent collector/display logs and release state. Including the latest damaged database is optional. Sending requires confirmation and a configured SFTP destination. Provision the device's SSH identity and verify the destination's host key before using upload.
- Rollback can restore the immediately previous release once, provided its data architecture matches the running release. Maintain the architecture identifier in VERSION.json and increment it whenever old code cannot safely use the new persistent data. Version 0.4.47 is the explicitly supported legacy baseline.

Existing appliances need the updated stable launcher and one reboot. Install the staged release using the usual approval screen.
