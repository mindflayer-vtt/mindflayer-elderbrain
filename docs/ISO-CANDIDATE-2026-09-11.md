# Updated ISO candidate

Built successfully on 2026-09-11 from the local dirty worktree:

`/tmp/elderbrain-updated-iso-ektFHt1g/mindflayer-elderbrain-e57c24f58122.iso`

SHA-256:
`bdd25aee69c5e25c0598663b77f22f6ca25f49a8eb2d20e1b1d0f61b339919e4`

The cached Ubuntu 26.04.1 base matched the freshly fetched, signed Ubuntu
checksum manifest. The finished image has BIOS and UEFI El Torito boot entries.
The extracted payload matched the build-time source using checksum-based rsync
comparison (excluding the intentionally generated VERSION). The embedded SSH
public key exactly matches `/home/g749/.ssh/g749-servers.pub`. No SMTP defaults
were selected; they remain configurable through `SMTP_CONFIG` for another build.
Inspection found no `.env` variants, local secret files, agent state, SSH private
directory, node_modules, private SMTP directory or disposable QEMU data.

This candidate includes the newer browser launcher, root display projection,
Chrome policy, network UI/reconnection link, and provisioning preservation and
legacy-repair migration changes. It is not evidence that the physical Lenovo has
those changes installed. The locally modified Foundry module is a separate
artifact and is not bundled by this ISO build.

Still required: clean-install/boot qualification of this exact ISO, broader
physical feature verification, and a coordinated deployment. Do not describe
the image as fully qualified based only on payload and boot-catalog inspection.
No Ventoy device was visible at build time, so the image was not copied to USB.
The artifact is in temporary storage and will not survive a host reboot; the
development PC remains on. Original ISO artifacts were not overwritten.

Clean-install qualification has now started for this exact image. The additional
VM uses SSH 2224, VNC display 2 and the existing `g749-servers` key pair. Runtime
directory: `/tmp/elderbrain-candidate-vm-GCfAaSQS/run.TstYBh`; disk:
`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/elderbrain-disk.l2oDRinM/disk.qcow2`.
This exact candidate **failed clean installation**: provisioning stopped at
`loginctl enable-linger elderbrain-kiosk` with `Could not enable linger: No such
process` inside curtin's target chroot. Do not install or distribute this image.
The local fix seeds the persistent linger marker offline, retaining loginctl
for live provisioning. Regression tests cover both branches and live errors;
first-boot qualification now also checks Linger=yes and the kiosk user manager.
The marker is the one checked by [systemd logind](https://github.com/systemd/systemd/blob/main/src/login/logind-user.c).
A rebuilt image must pass a new clean install; patching this guest would not
qualify the original ISO.
The older integration VM and physical Lenovo were not restarted or changed.

## Replacement with offline linger fix

Built successfully with the same requested public key and no SMTP defaults:
`/tmp/elderbrain-chroot-fixed-iso-an64B8CT/mindflayer-elderbrain-e57c24f58122.iso`.
SHA-256: `4c10cd1b22115a389a5f832c1688ecc56a91935e5dcbdb46d9e1f5a42a92ac4c`.
The signed base checksum and both BIOS/UEFI boot entries were checked again.
Seven focused linger/default-preservation/payload tests and static checks passed.

The failed VM and polling harness were stopped; its disk was preserved. A new
clean install is running on SSH 2224 / VNC 2, using a separate disk:
`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/elderbrain-disk.mqJC7FVX/disk.qcow2`.
This replacement is also **not yet qualified**; first boot and reboot checks
remain pending. A read-only Lenovo check confirmed graphics active, Chrome
processes present, and the legacy root:kiosk projection still mode 0640.

The replacement subsequently **failed provisioning with the same loginctl error**.
Automatic chroot detection selected the live branch under curtin. The next local
fix explicitly passes `ELDERBRAIN_OFFLINE_INSTALL=1` in the autoinstall late command;
its regression test covers failed detection with offline mode selected. Neither
ISO above is suitable for deployment. A further build and clean install are required.

## Explicit offline candidate

Successfully rebuilt at
`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/offline-iso-0PYtnk63/mindflayer-elderbrain-e57c24f58122.iso`.
SHA-256: `a84354b3eda90f63b21144e9422c6c56e209cb9a584e09d7affc1cf2011b60a1`.
Extracted user-data contains the explicit offline flag; the extracted provisioning
script and public key match their intended sources byte-for-byte. The signed
Ubuntu base checksum passed again. Host regressions: 206 passed, five skipped.

A fresh clean install has started on SSH 2224 / VNC 2 using a new disk:
`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/elderbrain-disk.L61Jpcsy/disk.qcow2`.
Both failed VM disks are preserved; their VM processes and polling harnesses were
stopped. The Lenovo and older integration VM are unchanged.

### Clean install and reboot results

The exact explicit-offline image passed the clean-install harness, first-boot
administration checks, and a complete VM reboot. After reboot, all three stack
containers were healthy and the management/graphics services were active.
Repeated installed-service and HTTPS tests passed, including server v3 capability
checks, serial tooling, the scoped host bridge, administration CA, unauthorized
API rejection, onboarding gate, secure cookies, CSRF and logout.

The UI check passed before and after reboot: exactly one normal administration
window, private root-owned display projection, eight-word bootstrap password,
tty2 service, disabled password saving, enabled kiosk linger/user manager, real
host DHCP attribution and CPU/RAM/filesystem readings. Screenshots showed Setup
first and Foundry second, with the password field focused and reveal control.

Visual inspection nevertheless found a Chrome “Restore pages?” bubble after
reboot. The existing `--disable-session-crashed-bubble` argument did not suppress
it. A subsequent local change uses Chromium's
[`--hide-crash-restore-bubble` switch](https://chromium.googlesource.com/chromium/src/+/refs/tags/138.0.7204.89/chrome/common/chrome_switches.cc)
in both browser launch paths. Nine launcher regression tests and worker syntax
checks pass. This change is **not in the ISO above**; the disposable guest's
launcher is patched separately for visual verification, with the original saved
as `/tmp/browser-session-original-iso.py`. A replacement ISO is required to include
the correction. The patched guest passed the administration checks again after
a graphics restart; its screenshot shows the focused login page without the
restore bubble. An intentional SIGKILL of only its browser's main process then
proved automatic single-window recovery without the bubble. A subsequent full
VM reboot passed installed-service and administration checks, and visual
inspection again showed no restore bubble.
Broader physical feature verification is still outstanding.

No Ventoy storage device was visible on the latest check, so no USB copy was made.
The successful candidate is on the persistent secondary drive; both PCs remain on.

## Browser-popup replacement

Built successfully, with BIOS/UEFI boot entries checked:
`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/browser-fixed-iso-ZPKGQuGR/mindflayer-elderbrain-e57c24f58122.iso`.
SHA-256: `6116339ab4aeec6991c81ba44f47149e50ed7bfc3a1253906e373565bc27c331`.
Both extracted browser launch sources and the requested SSH public key match the
local sources byte-for-byte. Autoinstall retains the explicit offline flag.
The signed Ubuntu base checksum passed. No SMTP defaults were selected.
All 206 enabled Python tests passed (five opt-in skips); static checks passed.

A separate fresh-install qualification is starting on SSH 2226 / VNC 3. The
earlier patched guest is retained on SSH 2224. Qualification of this exact new
image is pending; the patched earlier guest does not replace that check.
The Lenovo did not respond to a read-only SSH check at 10.0.96.125; no physical
changes or reboot were attempted during these tests.

The replacement's clean installation and first-boot harness **passed**. Runtime:
`/tmp/elderbrain-browser-fixed-vm-MMkfEK2h/run.UyZchT`; disk:
`/mnt/local-hdd-Stores2/elderbrain-iso-test-UNrRnBsx/elderbrain-disk.BnttSn4P/disk.qcow2`.
Installation plus first-boot checks took roughly 31 minutes on the secondary HDD.
All three containers were healthy. Installed v3 capabilities, serial tooling,
private journal storage, setup host bridge, HTTPS/CA, authentication/onboarding,
CSRF/logout and SSH password rejection passed. The harness now also runs the
administration UI/host check automatically: bootstrap word format/permissions,
tty2, password-manager policy, linger, private display projection, exactly one
normal browser, DHCP attribution and real host metrics all passed.
The first-boot screenshot shows Setup first, Foundry second, and the focused
password/reveal controls without a restore popup. No runtime patch was applied
to this guest. Its full reboot check also **passed**: boot ID changed from
`5360b7fd-f03c-43dc-8cf0-00baceceffee` to
`521010aa-07fd-4ba8-a49a-6430ab736b73`; stack, management and graphics all returned
active. Repeated installed-service, HTTPS/authentication and UI/host checks passed.
The screenshot after reboot shows one normal browser with the focused sign-in
page, Setup/Foundry tabs and no restore popup. This qualifies this exact image's
basic clean-install/first-boot/reboot path, not the outstanding physical network,
display/hotplug, or real keypad-driven Beamer behavior.
