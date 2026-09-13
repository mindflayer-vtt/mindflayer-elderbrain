# Installation

Write the ISO to USB, boot it, and select **Install Mindflayer Elderbrain**. Merely booting the medium does not authorize disk erasure. Subiquity's `direct` layout selects an install target and excludes its active installation medium; review the disk shown by firmware/installer on unusual storage hardware. This v1 must be treated as unsafe for machines containing data until its QEMU and target-hardware qualification is complete.

With Ventoy, copy the ISO file onto its existing data partition instead of
writing a raw image. Select the ISO in Ventoy, then select the Elderbrain install
entry. Installation is unattended and erases the selected target disk: back up
that disk and disconnect other data disks before starting. Remove the installer
USB after installation when rebooting into the installed system.

The storage console lists only unused, writable, non-removable disks with a unique
hardware serial. Each entry has a number, path, model, size and serial. Choose the
target by typing its number; the installer retains and revalidates the exact udev
`ID_SERIAL` used by Curtin rather than the shorter serial sometimes shown by
`lsblk`. A fresh install then requires `ERASE DISK N`, where `N` is the displayed
number. Preserve reinstall lists eligible Btrfs partitions and accepts their
displayed partition number before requiring `REINSTALL OS DISK N`. Installation
mode and confirmation phrases are case-insensitive. Invalid interactive input shows
a concise error and restarts selection without making changes; type `cancel` to stop.
Ambiguous, changed or missing identities still stop installation without choosing a
fallback disk.

One screen is sufficient for initial setup (verified in the single-output VM).
Physical GPU support and two-output placement still require hardware testing.
For the first login, use `admin` and read the unique initial password with
Ctrl+Alt+F2; Ctrl+Alt+F1 returns to the setup browser. Have working Internet/DNS
and SMTP account details available for the required recovery-email setup.

After selection, Subiquity performs the base installation from the ISO without cloning this repository. Provisioning requires working Internet and DNS to install packages and pull the pinned Traefik and Mindflayer containers; Foundry downloads later through its own container. On first boot, `elderbrain-baseline.service` resolves those cached images to immutable local IDs, transactionally installs the offline Compose/startup policy and records the ISO's release sequence before management or graphics start. A failed pull is visible in `systemctl status elderbrain-stack` and `journalctl -u elderbrain-stack`; a failed baseline is visible in `systemctl status elderbrain-baseline`. Both fail closed rather than presenting a partially healthy UI. Browse to `http://<appliance-ip>/elderbrain/` if local DNS is absent. The first display also opens this URL. DNS records for the configured hostnames must be created externally.

The host network contract is TCP 22 for SSH, 80/443 for Traefik, and intentionally LAN-facing 10443 for the Mindflayer keypad protocol.

## Reprovisioning defaults

The installer creates the initial Foundry configuration and `appliance.env` only
when they are absent. Existing regular files keep their contents and metadata;
symlinks or non-files at those paths stop initialization. New files are published
atomically with mode 0600, and a concurrent save is never replaced by a default.
Existing environment files are not automatically merged with newer defaults:
review new variables and image versions as part of a coordinated upgrade.
This protection does not make the full provisioning script a transactional
upgrade or remove the need for a verified backup before reprovisioning.
