# Mindflayer Elderbrain

Elderbrain turns an x86-64 PC into a minimal Ubuntu Server tabletop appliance: Docker services start, a native Wayland kiosk starts, and two independent Chromium profiles open the configured table views. The ISO carries the OS installer and appliance configuration, not Mindflayer server source. On first boot it requires Internet access and pulls the pinned `mindflayervtt/server` runtime image. Foundry binaries and credentials are never included.

## Quick start

```sh
make help
make test
make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 \
  SSH_PUBLIC_KEY="$HOME/.ssh/id_ed25519.pub"
```

Copy the resulting `out/mindflayer-elderbrain-<version>-r<sequence>-<commit>.iso` to USB,
boot it, and deliberately select **Install Mindflayer Elderbrain**. That selection
authorizes an unattended installation. See [build](docs/BUILD.md),
[installation](docs/INSTALL.md), and [administration](docs/ADMIN.md).

The appliance exposes SSH on 22, Traefik web access on 80/443, and the intentionally LAN-facing keypad protocol on 10443. See [testing](docs/TESTING.md); documentation does not claim unperformed hardware validation.
