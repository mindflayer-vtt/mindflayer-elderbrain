# Architecture

Ubuntu Server 26.04 LTS supplies SSH, Docker, systemd, and Sway; Google Chrome Stable comes from Google's signed apt repository because Ubuntu's Chromium package is a snap transition that cannot be installed reliably in the target chroot. `/opt/mindflayer-elderbrain` holds redeployable definitions; `/var/lib/mindflayer-elderbrain` holds state. `elderbrain-stack.service` starts Compose after networking and Docker. `elderbrain-graphics.service` separately waits for the setup route and supervises Sway/Chrome; backend or display failure does not disable SSH. Sway was chosen because output criteria can place two independently profiled kiosk windows on named connectors.

Traefik owns host ports 80/443. Its file-provider configuration declares the
fixed internal service endpoints, routers and middleware; it has no Docker
provider, container labels or Docker-socket mount. Foundry (30000) and the
browser-facing Mindflayer endpoint (8080, including `/ws`) remain on the `proxy`
network. Physical keypads are the documented exception: they use restricted-CBOR
WebSocket over a separate self-signed TLS identity at `/device/v1` on 10443.
Their firmware pins that identity, so host 10443 maps directly to the server.

The setup application registers as a receiver on the existing Mindflayer `/ws` protocol. Registration and key-event messages implement discovery/activity; existing `configuration` messages set both keypad LEDs for identification. Seat names belong to Elderbrain configuration; Foundry player/token mappings remain in the Foundry module.

The ISO carries appliance-owned definitions but no Mindflayer server source. Compose pulls the exact tag-and-digest reference in `config/defaults/appliance.env`; the target needs public Internet access but no repository or registry credentials.

The small `elderbrain` management command owns operations. A root Unix-socket bridge exposes an allowlist to the unprivileged setup container, preserving a future console UI path.
