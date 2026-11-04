# FishFinder 0.4.39 — saved Stratux startup reconnection

After a successful startup connection to an enrolled BSSID with a responding
Stratux, reuse its saved friendly name and continue to the startup safety notice.
Do not require another name/save step, rewrite its profile, or require Internet
or a GPS fix. The existing BSSID verification in Manager.connect is retained.

If a receiver responds on a changed IP, apply that setting before continuing.
A missing receiver still leaves recovery/recheck choices available. Manually
opening network settings still allows editing an existing friendly name.
A different BSSID advertising the same SSID still requires enrollment, and
reusing a different device's name still requires explicit replacement.

Tests cover saved reconnect, changed IP, unavailable receiver, new BSSID,
manual editing, and same-device/same-name save. A real post-reboot reconnect
on the Pi remains the user acceptance check.
