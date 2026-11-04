# FishFinder 0.4.40 — one-step saved home network connection

Choosing an enrolled BSSID and tapping Connect now starts connection immediately,
without another Connect/Retry screen. On startup a saved home/FBO network then
continues without naming/saving again, even if Stratux is absent or Internet
reachability is unconfirmed. Existing BSSID verification remains in Manager.
A saved receiver that no longer responds still offers receiver troubleshooting.
Setup can still edit saved friendly names after connection. New networks still
require their enrollment/password steps, and different-device name replacement
still requires explicit confirmation.

Tests add saved-home/no-Internet continuation and one-step saved-network selection.
Physical startup on a home network remains the user acceptance check.
