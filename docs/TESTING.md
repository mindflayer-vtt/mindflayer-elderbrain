# Testing

## Latest local regression run

2026-09-11, after the network reconnection link and legacy Lenovo repair:

- Setup: 36 tests passed, including the production mail transport's loopback TLS test.
- Host (rerun after offline linger, default-preservation and payload fixes):
  211 tests discovered, 206 passed and five opt-in integrations skipped
  (Borg, Borgmatic, Borg-over-SSH, sibling serial release builder and server image).
- Production-build browser suite: all 29 tests passed. Its host/network/hardware
  operations use test fixtures; this is not physical integration evidence.
- Nuxt type checking and static safety checks passed.

The initial sandbox attempts could not create test sockets; reruns with socket
access passed. No production permission changes were needed for these tests.
Live network tests and their remaining gates are in `NETWORK-SAFETY.md`; the
separately approved physical repair is recorded in `LENOVO-BROWSER-REPAIR.md`.

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

## Real-hardware checklist

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
