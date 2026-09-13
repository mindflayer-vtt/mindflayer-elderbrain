# Testing

## Latest local regression run

2026-09-13, after signed-update interruption qualification and branded boot work:

- Setup: 39 tests passed, including the production mail transport's loopback TLS test;
  Nuxt type checking and the production build also passed.
- Host: 625 tests discovered, 620 passed and five opt-in integrations skipped
  (Borg, Borgmatic, Borg-over-SSH, sibling serial release builder and server image).
- Production-build browser suite: all 40 tests passed. Its host/network/hardware
  operations use test fixtures; this is not physical integration evidence.
- Static safety and Compose configuration checks passed.
- GitHub Actions run `34743873482` passed the same complete workflow on the
  Ubuntu 26.04 hosted image with Python 3.14 and Node 24.

The installed Ubuntu 26.04 disposable VM also passed the branded Plymouth reboot,
graphical handoff and post-boot unit-health check. No production permission changes
were needed for local test sandbox limitations. Live network tests and their
remaining gates are in `NETWORK-SAFETY.md`; the separately approved physical
repair is summarized in the lifecycle implementation record.

## Commands and scope

`make test` runs setup configuration/protocol unit tests, Python host-service tests
(including real OpenSSL/GPG checks), and static safety checks. It requires `zstd`,
`openssl` and `gpg`. Optional real Borg integrations use the environment variables
documented in [implementation progress](IMPLEMENTATION-ADDITIONS.md).
`make compose-check` validates Compose without starting licensed Foundry.
`make test-iso` rebuilds the ISO with its disposable test key and boots a new
40 GiB QCOW2 disk with Internet access. SSH forwarding and unauthenticated test
VNC bind only to loopback. Each run retains its disk and monitor artifacts under
`test/.qemu/run.*`; earlier disks are not overwritten. The harness deliberately
selects the destructive Elderbrain installer entry only inside that disposable VM.
After installation it checks key-only root SSH, password rejection, container
image identity, the running stack, verified administration HTTPS and HTTP redirect,
unauthorized API access, first-login restrictions, secure session cookies, CSRF,
logout, setup-container access to the scoped management bridge, keypad TLS 10443,
graphical service state and absence of `ubuntu-desktop`. These checks do not yet
prove SMTP onboarding, full live restore or physical keypad behavior.

Use `QEMU_WORK_ROOT=/path/to/test-storage` to place new disposable disks on a
different filesystem when workspace disk space is limited. `KEEP_VM=1` leaves the
VM running for diagnosis after the harness returns. Otherwise the harness requests
a synced guest poweroff before falling back to stopping QEMU. Never edit the
running harness in place: Bash can read later portions of the file during execution.

For an additional VM, set `QEMU_SSH_PORT` (default 2222) and
`QEMU_VNC_DISPLAY` (default 0; VNC port is 5900 plus this number). Both listeners
stay loopback-only. `QEMU_SSH_PRIVATE_KEY` selects an existing key pair matching
an already-built ISO; it never creates or replaces that supplied key. Optional
`QEMU_DISK_ROOT` places only the newly allocated QCOW2 disk on another existing
storage directory, leaving monitor sockets and other runtime files under
`QEMU_WORK_ROOT`. Each disk receives a unique directory; existing disks are not
reused or overwritten.

Set `QEMU_FIRMWARE=uefi` to run the same destructive fresh-install qualification
under OVMF instead of legacy BIOS. Each run copies the OVMF variable-store template
into its private runtime directory; the host template is never modified. The
defaults are `/usr/share/edk2/x64/OVMF_CODE.4m.fd` and
`/usr/share/edk2/x64/OVMF_VARS.4m.fd`; distributions with different paths can use
`QEMU_OVMF_CODE` and `QEMU_OVMF_VARS`.

The harness pauses its installation-readiness timer until the operator confirms
that the final guarded storage prompt was submitted. This keeps human review time
outside the bounded 30-minute install/provisioning window. A separate controller
that submits all three prompts immediately may set
`QEMU_STORAGE_PROMPTS_AUTOMATED=1`; this only skips the terminal pause and does not
weaken or bypass any in-guest storage confirmation.

`test/qemu/live-nfs.py --confirm-disposable-vm` is an additional root-only test
for a disposable installed VM with `nfs-kernel-server` installed and
`nfs-server.service` active. Copy it into that VM and run it there, never on the
host or a production appliance. It adds a temporary loopback-only NFS export,
uses the installed Borg implementation to create/retrieve an encrypted backup,
checks wrong-export rejection, and unmounts/removes its temporary data afterward.
It does not change the appliance's configured backup destination. This test passed
on the clean-installed disposable VM on 2026-09-10. The test creates `/etc/exports.d`
when the distribution package has not created it; no production code was patched.

Pull failure is intentionally simple and observable: the initial stack unit runs
`docker compose --profile foundry pull --ignore-buildable` before startup. This
caches every coordinated image needed by immutable baseline finalization without
starting the profile-gated Foundry container. A nonzero pull is propagated, Docker's
registry error remains in the journal, and systemd retries after 30 seconds. An
unreachable or nonexistent image therefore cannot produce an active stack.
After baseline finalization, the installed offline stack and local graphical UI do
not order themselves after `network-online.target`; cached services can therefore
start when the appliance is disconnected. Network backup jobs retain their own
network ordering and bounded retry policy. The appliance caps Netplan's
`systemd-networkd-wait-online` command at 30 seconds so Docker's vendor dependency
cannot indefinitely hide the local UI when every link is disconnected. Its timeout
exit status is accepted as an intentional bounded-degradation result; the timeout
remains in the journal and network consumers retain explicit retries.

## Real-hardware checklist

The branded boot path should show the Mindflayer logo and spinner until the local
browser is ready. Press Esc during Plymouth to reveal boot messages. If graphical
startup repeatedly fails, tty1 must replace the splash with recovery instructions;
SSH must remain reachable. VM qualification verifies the installed theme,
initramfs contents, spinner animation, smooth browser handoff and healthy units,
but it does not replace a physical GPU/display check.

The setup service uses Nuxt, Vue, TypeScript and Nuxt UI. Its production browser
regressions run with `cd setup && npm run build && npm run test:browser` after
`npx playwright install chromium`. They exercise a proxy matching Traefik's
prefix stripping, form persistence, controller identification, restart actions,
credentials, and direct hostname access. See [setup development](../setup/README.md).

- Cold boot reaches the appliance without a login/desktop; backend services recover after reboot.
- Both outputs are detected; player views are fullscreen and administration views
  are normal tabbed browsers at the correct resolution/refresh. GPU acceleration
  works, assignments survive reboot, and disconnected outputs do not cause overlap.
- Killing Chromium restarts the kiosk; killing Sway causes systemd recovery without affecting Docker/SSH.
- Foundry, setup, and browser Mindflayer traffic work through Traefik; public
  listeners are limited to 22/80/443, required keypad TLS 10443 and the temporary
  pending-transaction confirmation listener on 10444. Foundry's direct 30000
  binding remains loopback-only. Confirmation closes after completion or rollback.
- Root key login succeeds and password login fails.
- Foundry downloads the pinned release, activates normally, and retains data through recreation.
- Real keypads authenticate, appear in setup, report the correct button, visibly identify via LEDs, and retain seat names after reboot.

Headless CI cannot prove GPU, two-display placement, Foundry licensing, or physical keypad behavior. Never record those as passed without real hardware.

The ordinary hosted job targets the appliance's Ubuntu 26.04/Python 3.14
environment, pins every GitHub Action to a reviewed commit, installs `ripgrep`
explicitly, and runs Setup unit/type/build/browser checks plus the complete
non-destructive host/static and Compose suites. `test/static.sh` also preflights
its command dependencies before performing any check, so a missing tool cannot
produce a misleading success message.
