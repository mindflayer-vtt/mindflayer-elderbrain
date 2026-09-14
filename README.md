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
[installation](docs/INSTALL.md), [production releases](docs/RELEASING.md), and
[administration](docs/ADMIN.md).

The appliance exposes SSH on 22, Traefik web access on 80/443, and the intentionally LAN-facing keypad protocol on 10443. See [testing](docs/TESTING.md); documentation does not claim unperformed hardware validation.

## About the installation ISO

This project does **not** distribute a prebuilt Elderbrain installation ISO.

The ISO is created by _modifying_ an official Ubuntu Server installer image. While the build tooling is provided here, redistributing a _modified Ubuntu image_ is subject to Canonical's licensing and trademark policies.

To avoid redistributing Canonical's installer media, users build the Elderbrain ISO locally from an official Ubuntu Server ISO using the scripts in this repository.
