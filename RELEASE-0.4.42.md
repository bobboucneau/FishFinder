# FishFinder 0.4.42 — quiet preferred-receiver startup

Startup shows Looking for preferred Stratux while scanning, then keeps the progress
page visible through BSSID-verified connection and receiver probing. A successful
saved receiver connection proceeds directly to the safety notice. The empty
network chooser is no longer rendered before the scan completes.

If the preferred receiver is absent, there are no saved networks, or scanning or
connection fails, show the chooser/recovery controls. Wait / Retry repeats the
preferred scan; Other networks explicitly lists choices without auto-connecting.
All network work remains on the existing background queue with bounded timeouts.
No saved profiles, permissions, actual IP choices or receiver data are changed.
