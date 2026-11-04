# FishFinder 0.4.41 — on-screen Wi-Fi diagnostics

Setup → Wi-Fi / Internet now opens a read-only Current Connection page showing
the active Wi-Fi name, interface, IPv4 addresses, non-link-local IPv6 addresses,
and IPv4 gateway. Refresh reads NetworkManager again. Choose network opens the
existing connection workflow; the startup chooser behavior is unchanged.

Test host offers an editable IP/hostname with the on-screen keyboard and Stratux
and Gateway shortcuts. Ping runs two ICMP requests with a seven-second process
timeout and no shell. Failed ping is not called proof that a host is offline;
some devices block ICMP. Check Stratux uses the existing read-only Stratux/Internet
probe, reports the responding address, and never enrolls/authorizes a receiver.
All commands and probes run away from Tk's UI thread. No sudo rule is added.

The new diagnostic pages use larger text and shared rounded controls. Existing
enrollment/password screens retain their current layout for a later pass.
Saved network identities, credentials, actual ownship position and databases are
unchanged. No diagnostic data is uploaded.

Checks cover validation/argument safety, ping success/no reply/timeout/missing tool,
disconnected Wi-Fi, active friendly-name lookup, IPv4/gateway and escaped IPv6
parsing, alongside the existing network/reconnect regressions.
