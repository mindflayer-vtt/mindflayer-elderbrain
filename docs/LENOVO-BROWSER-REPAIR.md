# Initial hardware ISO: browser missing after reboot

On 2026-09-11 the Lenovo at `10.0.96.125` booted into Sway with no browser
processes. Its original shell launcher read the full administration configuration
as kiosk UID 999. After configuration was saved, `config.json` was mode 0600,
owned by UID/GID 1000; kiosk readability failed. The launcher did not handle that
permission error. Sway stayed active, explaining the black screen and cursor.

With explicit user approval, a narrow compatibility repair was installed:

- `provisioning/compat/legacy-browser-prepare.py` runs as root before graphics,
  projecting only `configured` and the first two views' URL/output fields.
- `/run/elderbrain-legacy-browser/config.json` is root:kiosk 0640 in a 0750
  directory. The original private config remains 0600, owned by 1000:1000.
- The installed shell launcher's only modification is its configuration path.
- `30-legacy-browser-projection.conf` adds the privileged preparation step on
  every graphics start, including boot. This is a legacy compatibility repair,
  not a deployment of the newer browser-mode/Beamer implementation.

Backup and staged artifacts on the Lenovo:
`/root/elderbrain-browser-repair-hpKHysKc`. The original launcher is
`browser-launcher.original`; its SHA-256 before modification was
`0472648c3c33c94d83393db277776273e4c0a0b76bc8dfb66b230fe2b9facdb1`.
Reverting requires restoring that launcher and moving the matching service
drop-in out of the systemd directory, then daemon-reload and graphics restart.
Doing so also restores the original permission bug.

Verification: three projection tests passed; preparation and graphics restart
succeeded on the physical Lenovo. Both Chrome instances were running; Sway
reported `elderbrain-view-0` visible and fullscreen at 1920×1080. The old launcher
still starts a second browser even with one monitor (not visible in this check);
the newer local implementation addresses output-aware browser planning.
No reboot was performed for this repair. A complete reboot test remains to be
coordinated; startup wiring plus a graphics restart is not proof of that test.

The local installer now preflights this compatibility drop-in before making
installation changes. Once the new launcher, projection and graphics unit have
been installed, `provisioning/compat/retire-legacy-browser.py` renames the exact
known drop-in to a unique `.bak` file in the same directory. Its original bytes
and metadata are preserved; systemd does not load that backup as a drop-in.
Modified, symlinked, incorrectly owned or writable-by-others versions stop the
upgrade for review instead of being silently removed. Other drop-ins are not
touched. Fresh installs and repeat runs are no-ops for this migration. Six
compatibility tests and static checks pass locally. This migration has not been
run on the Lenovo; the working repair remains active there until the newer
launcher is deployed.
