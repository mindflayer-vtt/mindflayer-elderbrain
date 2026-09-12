# Hardware test handoff — 2026-09-11

## Candidate

`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/browser-fixed-iso-ZPKGQuGR/mindflayer-elderbrain-e57c24f58122.iso`

SHA-256: `6116339ab4aeec6991c81ba44f47149e50ed7bfc3a1253906e373565bc27c331`.

This exact image passed a clean VM installation, first boot and full reboot,
including healthy containers, protected HTTPS administration, automatic normal
browser startup, word-password/tty2 checks, password-saving policy and host
metrics/network discovery. No runtime patch was needed. See
[the qualification record](ISO-CANDIDATE-2026-09-11.md) for evidence and earlier
failed images, which must not be installed.

The embedded public key is `/home/g749/.ssh/g749-servers.pub`; build selection
remains configurable through `SSH_PUBLIC_KEY`. No default SMTP file was supplied
for this build. Select `SMTP_CONFIG` for a build with private SMTP defaults, or
configure custom SMTP during onboarding. Recovery-email verification remains
mandatory. The separately modified Foundry module is not bundled in this ISO.

## Required before proceeding

- The user confirmed the Lenovo was deliberately switched off. Turn it on when
  ready for testing; its last known address was `10.0.96.125`.
- Ventoy was reconnected and the verified ISO copied as
  `mindflayer-elderbrain-hardware-2026-09-11-6116339a.iso`. The copied SHA-256
  matches the value above. All pre-existing USB files, including the older
  `b3332f58` Elderbrain image, were preserved. Select the new `6116339a` image.
- Preserve the Lenovo's current configuration before any upgrade/reinstallation.
  The ISO's appliance-install entry is destructive; do not select it until that
  is intended. The full installer is not a transactional in-place upgrade.

## Remaining verification

Physical one-screen startup/reboot, keyboard/reveal/focus, detected connector and
preview rollback; two-screen modes/hotplug when the second output is available;
real DHCP/static addressing with new-address confirmation and rollback; and
Beamer visibility, keypad-driven framing and reconnect behavior in the intended
world. VM results do not prove these physical requirements.

Elderbrain remains local/unpushed. The Lenovo currently has only the narrow
[legacy browser repair](LENOVO-BROWSER-REPAIR.md), not the broader upgrade.
No physical shutdown or reboot was performed during this qualification.
