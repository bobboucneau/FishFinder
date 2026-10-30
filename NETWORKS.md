# Named Wi-Fi and receiver selection — v0.4.29

## What the user sees

Setup → Receiver / Updates → Wi-Fi / Internet opens a scan of nearby access points. Duplicate SSIDs remain separate rows, with signal strength and the final BSSID bytes; selecting one shows its full SSID, BSSID and security before connecting. A vertical scrollbar handles busy locations. Password fields are masked and have a touch keyboard with lowercase/uppercase, numbers, spaces and symbols.

After association, FishFinder checks that the actual BSSID matches the selection. It probes the configured Stratux IPv4 address and actual IPv4 gateway (not an assumed subnet .1). A recognizable Stratux situation JSON response is required. Receiver IP allows a custom address and another probe. Lack of receiver GPS reception is not itself a failed receiver probe.

Internet reachability and airport-update-source reachability are shown separately. The small HTTPS checks reject ordinary captive-portal HTML; no map or airport dataset is downloaded by these checks. Results are point-in-time checks, not guarantees about every Internet destination. Airport updates are now manual only using the existing Update airports button; code update hosting remains unconfigured.

Enter a friendly name after connecting. Make preferred Stratux is offered only when a receiver is detected. A name already associated with a different BSSID prompts Replace existing, Change name or Cancel. Comparison ignores case and normalizes repeated whitespace. Replacement preserves preferred status if the new association has a receiver. Saving another name retains both. Cancelling does not remove the old saved association, but does not undo a Wi-Fi connection already explicitly made.

Live startup opens the chooser once after the splash. An available saved preferred BSSID is the only automatic choice. A sole saved alternative is offered for confirmation; multiple alternatives, first-time setup or no known access points require selection. Wait / Retry rescans; Other networks shows all access points; Skip continues without forcing a connection. A receiver still warming up can be checked again with Wait / Recheck after association. No periodic startup popup appears after Skip.

Moving demo startup leaves Wi-Fi alone. The chooser is still available in Setup for bench testing. Demo mode does not become live simply because a receiver is found; changing collector demo/live mode remains the existing explicit service procedure.

## Credentials and persistence

FishFinder stores friendly name, SSID, BSSID, NetworkManager UUID, last-tested capabilities and preferred association in networks.json beside settings.json. Passwords are supplied to nmcli --ask on stdin, never process arguments, logs or FishFinder JSON. NetworkManager owns the saved credentials. Personal/open Wi-Fi is supported; enterprise/WEP networks require an administrator-prepared NetworkManager profile. Hidden-SSID provisioning and captive-portal browser login are not provided by this release.

Selected profiles are pinned to their BSSID. NetworkManager automatic selection is disabled on the selected Wi-Fi interface and the selected profile; FishFinder retries only its currently selected profile/BSSID every ten seconds. Other network profiles and other interfaces are not deleted or reconfigured. No privileged policy, passwordless sudo or permission broadening is installed. Local-session NetworkManager permissions must allow scan/connection/profile modification; failures remain visible rather than invoking sudo.

After at least one FishFinder profile is saved, the collector requires a current-boot network-session.json association and matching active BSSID before accepting receiver HTTP traffic. Its WebSocket watchdog also checks this association (cached for at most two seconds). A boot-ID mismatch or a home connection without a detected Stratux fails closed. Before initial enrollment, legacy collector IP behavior is retained. BSSID is an association identifier, not cryptographic proof of a receiver's identity.

For upgrades, copy settings.json AND networks.json to the new version folder. Do not copy network-session.json: it is a transient association gate and will be recreated when the connection is selected. NetworkManager UUIDs and credentials stay with the operating system. Both metadata files and runtime locks are excluded from Git.

## Implementation reading order

network_manager.py: escaped nmcli parsing → friendly-name policy → atomic profile persistence → selection decision → bounded NetworkManager operations → separate probes → selected-only reconnect → collector association gate.

network_screen.py: list/scan → full AP confirmation/password → connect/probe result → friendly name → duplicate-name choice → save. A queue hands worker results back to the Tk thread. Slow scans, connection attempts and HTTP operations never execute in the touch handler.

## Validation boundaries

37 focused tests cover network policy, BSSID parsing/pinning/mismatches, secret argument handling, replacement/preference preservation, receiver-shaped JSON versus unrelated servers, captive portals, collector association checks, health indicators, display touch regression and service launchers. They do not switch real access points or allocate large datasets. Native Mac layout inspected; Pi scan/probe checks are read-only.

The prototype has no local Stratux during this release's testing. Actual password entry, NetworkManager authorization, reconnect across radio loss, and receiver discovery must be verified on the Pi with the relevant networks before claiming those paths hardware-tested. Switching its sole Wi-Fi interface can disconnect SSH, even when working correctly. Keep local touch access and the previous release available.
