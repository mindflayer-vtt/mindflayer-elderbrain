# Appliance lifecycle implementation

The September 11 lifecycle goal is implementation work, not yet included in the
qualified `6116339a` Ventoy image. Keep Elderbrain local and leave physical hosts on.

## Delivery sequence and acceptance gates

1. Persistent storage: explicit destructive fresh install and UUID/metadata-checked
   OS reinstall; reject ambiguous layouts. Separate ext4 OS (including disposable
   container images/cache) and Btrfs user state. Persist host configuration and
   credentials as well as container data. Gate every writer, including Docker
   automatic container restarts, on verified data mounting. Verify BIOS and UEFI
   fresh installs, populated reinstall with byte/identity preservation, missing
   data refusal and disk-selection negative cases in disposable VMs.
2. Coordinated read-only Btrfs checkpoints with retention: preferences, network
   with timed rollback, keypad preferences vs identities, whole Foundry instance,
   and explicit advanced security/recovery. Quiesce affected writers; capture
   subvolumes explicitly. Show keypad differences and separate physical reapply.
   Test restore failure recovery and coherent multi-component capture.
3. Signed coordinated releases: versioned host tooling/templates/migrations,
   prebuilt digest-pinned Setup and compatible dependency/schema manifests.
   Verify trust, compatibility, disk space and operation locks; checkpoint,
   stage without changing user config, activate, health-check, retain rollback.
   Ordinary boot must neither build nor pull; verify disconnected cold boot.
   Independently updated Setup must satisfy installed host API compatibility.
4. Authenticated/CSRF-protected System page: update check, versions/change notes/
   downtime, confirmed update/shutdown/reboot, durable root jobs, interlocks
   against firmware flashing, restores and update activation.
5. Backup policy: existing persistent scheduled timer, optional orderly shutdown
   (not reboot) and pre-update backups, interval/change deduplication. Local
   checkpoint before bounded remote attempt; retain pending work and retry next
   boot; expose successful remote backup age and pending uploads.
6. Plymouth Mindflayer logo/spinner, matching service/browser loading screen,
   useful phase text, Esc logs, bounded failure with recovery instructions,
   accessible recovery console, tested transition to login without a black gap.

## Current progress

`iso/storage_plan.py` implements a pure storage-plan generator with fail-closed
selection and preserve validation. It emits a stable four-partition GPT layout:
BIOS boot, EFI, 48 GiB OS and remaining Btrfs data (at least 24 GiB). Preserve mode
retains partition geometry, EFI and data filesystems, reformatting only OS.
Disk serial, filesystem UUID and appliance marker must agree; duplicate serials
and cloned data UUIDs are rejected. No disk operations are performed by this code.

`iso/storage_probe.py` now provides read-only live inventory with explicit tree
relationships, rejecting mounted descendants, swap and active holders as targets.
`appliance/lib/storage_guard.py` verifies an exact writable Btrfs top-level mount,
filesystem UUID and matching root-owned appliance identity; it never creates
replacement directories. The guard is not yet installed/enforced by services.

`iso/storage_existing.py` inspects the selected block device directly, rejects
multi-device Btrfs, mounts privately with `ro,nologreplay,nosuid,nodev,noexec`
and explicitly selects the filesystem root. It unmounts on marker-read failure
and attempts exact unmount after a mount timeout. Cleanup never recursively
removes anything. `iso/storage_prepare.py` validates geometry before mounting,
requires the real volume marker, then probes again to reject changed disks or
newly attached clones. Unit tests cover these paths; real Btrfs inspection and
installer integration are still pending. The read-only mount explicitly disables
log replay because [Btrfs can replay logs even on a read-only mount](https://btrfs.readthedocs.io/en/latest/btrfs-man5.html).

`iso/storage_select.py` implements explicit console selection with no default
mode or disk. It requires an exact serial and `ERASE <serial>` for fresh install,
or the data UUID and `REINSTALL OS <serial>` for preserve. It produces a private
selection receipt and atomically replaces only the storage section of the
autoinstall configuration, preserving other installer settings. This executable
is not yet invoked by the ISO early commands.

`provisioning/storage_initialize.py` initializes a fresh identity only on an
empty verified Btrfs data mount; preserve mode requires the original marker and
never creates a replacement. Provisioning accepts `ELDERBRAIN_STORAGE_RECEIPT`
and checks any installed storage identity before creating state directories.
For this layout it installs storage verification dependencies for Docker and
all Elderbrain system services, bound to the dedicated mount. Legacy live
upgrades remain unchanged. These dependencies still need systemd/VM runtime
verification; unit/source tests are not proof of boot ordering.

`provisioning/host_persistence.py` prepares persistent Netplan and SSH directories
(server policy/host keys and root/installer authorized keys). Fresh mode copies
metadata-preserving contents; preserve mode refuses missing directories instead
of replacing them with installer defaults. It generates idempotent bind-mount
fstab entries and rejects existing conflicting targets. Actual mount activation
is not connected yet. Tests exercise real temporary-directory copies, permission
preservation, no-reseed behavior, symlink refusal and fstab conflict detection.

Restore orchestration now has an alias-refresh barrier before validation and
restart, repeated after rollback and interrupted-commit recovery. Failure tests
verify rollback on refresh failure and no writer restart if recovery refresh also
fails. `appliance/lib/host_bindings.py` supplies the fixed-target mount refresh
implementation (UUID/source validation, normal unmount, bind and inode check).
Host restore/recovery now detects and verifies the installed storage identity,
maps SSH restore targets to canonical persistent directories and supplies this
refresh barrier. Refresh supports aliases referencing either the previous tree
or the rejected tree during rollback. Five mount-command/mapping tests cover
ordering, interrupted unmount recovery, wrong-volume refusal and inode-check
failure. They mock mount syscalls: direct Btrfs/VM tests are still required and
these tests alone do not qualify mounted-directory restores.

Real Btrfs binding test passed on the existing disposable Ubuntu VM (SSH 2226),
using `unshare --mount --propagation private` and a newly created 256 MiB regular
file, not an appliance disk. `test/qemu/storage-bindings.py` exercised actual
journaled directory replacement, stale bind-inode visibility, refresh to new
data, rollback while the alias referenced the rejected tree, and recovery after
an interrupted unmount. Test mounts were unmounted normally. VM artifacts remain
at `/tmp/elderbrain-storage-bindings-lpjszv7p`; copied test code is at
`/tmp/elderbrain-storage-test-code-zJKeiKlT`. This verifies the mount mechanism,
not full host-service restore, fresh/reinstall boot or installer disk selection.

`provisioning/runtime_settings.py` now persists `appliance.env` and `sway.conf`
under `host/runtime`, with stable runtime symlinks. Provisioning for the new
layout uses this helper instead of overwriting persistent values. Restore maps
these settings to their canonical files, preserving symlinks and rename-based
atomic updates. Tests cover custom values surviving OS alias recreation,
permissions, missing-data refusal, conflicting OS settings and restored values
becoming visible through the aliases. Installed software/Compose stays on OS.

Host-directory activation is now wired into provisioning for identified data
volumes: validate/seed directories, publish conflict-checked fstab, then bind
mount and validate SSH configuration. The storage service requires these aliases
as well as the data mount. Persistent installations regenerate Netplan before
network recovery/network startup, because the early generator can otherwise read
OS-side defaults before the bind mounts exist. Activation failure tests verify
no fstab publication or mount calls when preserved directories are missing.
Boot ordering and real activation/reinstall still require VM validation.

The ISO source now invokes explicit selection on tty3 in early commands and
copies the verified receipt into the target before provisioning. Empty initial
storage configuration replaces the old automatic direct layout; selection
failure aborts. The VM harness now allocates 96 GiB and an explicit test disk
serial to meet the layout requirements. It still requires answering the console
prompts; automated selection and fresh/preserve VM qualification remain pending.
The existing Ventoy ISO is unchanged and still uses the old layout. Do not use
that image to attempt preserve-data reinstall. No new storage ISO is qualified.

Storage action semantics follow the
[Curtin storage documentation](https://curtin.readthedocs.io/en/latest/topics/storage.html).
Local snapshots and same-disk backups do not protect against physical disk loss.

## Storage ISO candidate and live test

Built candidate (not qualified, not on Ventoy):
`/mnt/local-hdd-Stores2/elderbrain-storage-iso-PGYvkyS4/mindflayer-elderbrain-e57c24f58122.iso`
SHA256 `b68707b599958bc40a8bd8976e57f4db193b699c6428c98b936a8da946c8961f`.
Ubuntu signature/checksum verified; build session 26683 completed successfully.
Host regression: 276 tests, 5 optional skips, no failures.

First QEMU launch exited before boot because serial was passed to the block
format rather than virtio device; harness corrected to explicit virtio-blk-pci.
Replacement harness session 20835 is running with SSH 2228/VNC 5904, work root
`/tmp/elderbrain-storage-vm-2xOWp33T`, fresh disk
`/mnt/local-hdd-Stores2/elderbrain-storage-iso-PGYvkyS4/elderbrain-disk.jgJFQQvB/disk.qcow2`.
VM runtime is `/tmp/elderbrain-storage-vm-2xOWp33T/run.NszwZp`, QEMU PID 1414650.
Console selection ran, but early commands terminated with
`ValueError: Expected an autoinstall document`: Subiquity normalizes
`/autoinstall.yaml` to the inner mapping. Read-only `lsblk /dev/vda` confirmed
the 96 GiB disk remained unpartitioned. Selector now accepts both wrapped and
normalized documents, covered by a regression test; this fix is NOT in candidate
`b68707b5`. Candidate therefore failed installation qualification.

The initial prompt on tty3 was obscured when Subiquity switched to tty1; manual
Ctrl+Alt+F3 revealed it. Improve prompt visibility before hardware handoff.
Live-installer diagnostic SSH was enabled using the ISO's public key, with
known-hosts `/tmp/elderbrain-storage-live-known-hosts`; an SSH response at 2228
is now the live installer, NOT proof of installed-appliance boot. Preserve VM
for diagnosis; a corrected ISO build and clean test are still required.

Corrected selector accepted the real live `/autoinstall.yaml` and freshly probed
`elderbrain-vm-test` inventory in a non-mutating check; the disk was still empty.
Prompt waiting now reclaims tty3 only when Subiquity switches to tty1; operator
diagnostic consoles remain accessible. Error tracebacks go to tty3. Storage
tests: 49 passing. Corrected ISO build started in
`/mnt/local-hdd-Stores2/elderbrain-storage-fixed-Jncwa4Ve`; qualification pending.

Corrected build session 34669 completed. Candidate SHA256:
`3fad5c99ded1edab53dd51588ffc05dbe05fe953232b46ed41cb0b95e2a94fcd`.
New clean VM harness session **88308**, SSH **2230**, VNC **5905**, PID **1419374**,
runtime `/tmp/elderbrain-storage-fixed-vm-TaScAsTI/run.7tYCh3`, disk
`/mnt/local-hdd-Stores2/elderbrain-storage-fixed-Jncwa4Ve/elderbrain-disk.PXKhCTRa/disk.qcow2`.
Latest observed screen: booting live installer, no selection submitted yet.
Full host regression passed: 280 tests, 5 optional skips.

Harness now waits for installed VERSION and storage identity, not merely SSH,
and runs `guest-storage.py` to verify persistent mount identity, separate OS
filesystem, directory aliases, runtime links and systemd storage dependencies.
These harness/test additions were made after ISO payload capture and run from
the host; they do not change installed code in this candidate.

Clean candidate `3fad5c99` displayed the tty3 selection prompt automatically
(no manual console switch). Fresh selection for `elderbrain-vm-test` was
submitted and accepted. Latest screen shows successful storage configuration
conversion/application and installer package setup in progress. Harness 88308
remains live waiting for installed-appliance SSH/identity. Continue this VM;
do not restart or treat slow package installation as terminal failure.

## Foundry ownership repair on physical appliance

User confirmed the reinstalled Lenovo is at **10.0.96.126**. Read-only checks
confirmed container `2410daa2498b` bound `/var/lib/mindflayer-elderbrain/foundry`
to `/data` writable, but the empty directory was `root:root 0755`. Corrected
only that directory to `1000:1000`, retained 0755, and restarted only Foundry.
It passed the volume check, completed startup, and is **healthy**, with local
HTTP **302** responding on port 30000. No software deployment or OS reboot.
Dedicated SSH known-hosts: `/tmp/elderbrain-hardware-126-known-hosts`.

Local provisioning now applies Foundry ownership explicitly, with a guest
access check. Real temporary-fixture test on VM 2226 reproduced the original
failure and verified UID/GID 1000 read/write, preserved file content and no
ownership traversal through an external symlink. Fixture retained at
`/tmp/elderbrain-foundry-permissions-b9i9txmg`. This fix is newer than candidate
`3fad5c99`; that ISO still needs the fix in a subsequent build.

Real read-only Btrfs inspection test uncovered that the guest kernel rejects
standalone `nologreplay`. Changed inspection to `rescue=nologreplay` (no recovery
or integrity bypass options). `test/qemu/storage-inspection.py` then passed:
correct identity, complete image SHA256 unchanged across inspection, wrong UUID
rejected, inspection mountpoints cleaned up. Fixture on VM 2226:
`/tmp/elderbrain-inspection-d6vt2v2p`. Source unit/static checks pass. This fix is
also newer than ISO `3fad5c99` and must be included before preserve-install tests.

## LAN domain routing repair

The Lenovo now has a permanent DHCP reservation at **10.0.96.90**, confirmed
by the user and the previously trusted SSH host key. DNS for
`foundry.home.viromania.com` correctly reaches it. The 404 was caused by the
Displays domain setting not being projected into Traefik's routing rules.

Added atomic, idempotent `domain_routes.py` projection of the committed domain
for Foundry, Mindflayer and Setup. Traefik watches the dynamic directory;
existing Docker services/middleware and default hostname routes are retained.
Only confirmation activates a new domain, and the display watchdog reconciles
on recovery/startup (including after restore). Preview/cancel never activate
an uncommitted domain. Domain labels are validated in both host and Setup.
This changes hostname routing, not external DNS or custom browser URLs, and
does not issue new HTTPS certificates. Foundry retains its existing HTTP route.

Deployed only the two host files and provider-directory change to the Lenovo;
original files are under `/root/elderbrain-domain-fix-UBa1Grfe`.
Recreated only Traefik, restarted management/display watchdog; Foundry stayed
running. Verified Foundry's new hostname returns HTTP302 to `/license`, Setup's
new hostname HTTPS200 (certificate verification bypassed for this test), and
all four containers remain healthy. Local GUI explanatory text/validation
will be included in the next build, not rebuilt on the physical appliance.
Elderbrain remains local/unpushed; current candidate ISO predates this fix.

The management restart exposed a second issue: systemd removed/recreated
`/run/elderbrain`, leaving Setup's bind mount on the old directory (host inode
5282, container inode 3076, socket missing). Added `RuntimeDirectoryPreserve=yes`
to management's unit locally and on hardware; backed up the original unit beside
the routing backup. Restarted only Setup to remount the current directory.
Verified identical directory inode and successful management query from inside
Setup; all containers healthy. Host regression: 284 tests, 5 optional skips
before adding the runtime unit regression; Setup: 36 tests and typecheck pass.

Follow-up browser issue: saved and projected URLs were correct, but
`configured=false` caused browser-session to discard all views and use defaults.
Saved views now apply independently of onboarding completion; missing first-boot
views still get the administration fallback. Added a regression using the
reported Foundry+Spotify tabs (10 browser unit tests pass). Deployed the single
browser-session file with original retained in the same hardware backup directory
and restarted only graphics to activate the saved tabs.

The user confirmed tabs opened correctly; process inspection also verified
the configured Foundry and Spotify URLs in the actual admin browser arguments.

## Persistent-storage clean boot evidence and compositor repair

VM2230 successfully installed and booted candidate `3fad5c99`: storage identity,
Btrfs state mount, all persistent host directory aliases, runtime symlinks and
data directory filesystem checks passed. Separate ext4 OS UUID and storage
dependencies were verified. The newer guest check correctly rejects Foundry
ownership in that older ISO; source already fixes it.

The compositor was repeatedly crashing: its persistent `sway.conf` symlink
traversed private `host/runtime` (0700), unreadable by the kiosk user. Added
a narrowly scoped Sway runtime projection in prepare-browser, and pointed
graphics at `/run/elderbrain-browser/sway.conf`. Actual VM repair (originals
under `/root/sway-storage-fix`) verified Sway active without restarts, Chrome
running, projected file root:kiosk0640, private runtime still root0700.
This is diagnostic repair, NOT clean-ISO qualification.

Intermediate ISO build `/mnt/local-hdd-Stores2/elderbrain-storage-next-stmJuYri`
completed but predates the compositor repair; do not install it for qualification.
Corrected build session **54561** uses
`/mnt/local-hdd-Stores2/elderbrain-storage-sway-bmduDTGg`; completion and a new
clean test remain pending. No new ISO has been placed on Ventoy.

Corrected build 54561 completed successfully. New clean harness session
**25376**, SSH **2232**, VNC **5906**, work root
`/tmp/elderbrain-storage-clean-AFS69C37`, disposable disk
`/mnt/local-hdd-Stores2/elderbrain-storage-sway-bmduDTGg/elderbrain-disk.8HbY3j8v/disk.qcow2`.
Boot launched; storage selection and qualification pending. Existing VM2230
passed the general guest checks after its explicitly documented runtime Sway
repair (container pins, private management bridge, serial/v3 tooling).

Clean candidate SHA256:
`0b058049da08dcb4ce3f13891f2ad97630dbe0d2248b8c580cb57566f4264761`.
VM2232 PID1435337, monitor
`/tmp/elderbrain-storage-clean-AFS69C37/run.IGGsVg/monitor.sock`.
Fresh selection submitted successfully; actual partitioning/formatting observed.
Continue harness25376; no installed-guest checks have passed for this ISO yet.

Added disposable-only `test/qemu/storage-unavailable.py`: runtime-mask the
data mount, stop it, verify writers stop and stack startup fails without creating
replacement data, then unmask and restore previously active services in finally.
Running in VM2230 as session42631; observed restoration reached mounted data and
active Docker, stack still starting (existing boot rebuild/pull behavior).
Do not restart the test merely because its output is buffered or restoration is
slow. The script's subprocess timeout does not cancel systemd's underlying job;
if it times out, inspect pending systemd jobs and finish restoration.

Session42631 completed exit0: **PASS** missing mount stops writers, rejects
stack startup, creates no replacement data; original mounts and active services
restored successfully. This verifies live mount-loss handling, not yet booting
with an absent partition or preserve-data reinstallation.

Added `test/qemu/storage-preserve.py` to seed disposable data fixtures and
capture a private baseline of content hashes, owners/modes, persistent runtime,
Netplan and SSH identity. Copy the baseline to the host before reinstall, then
verify it against the new OS; it requires a changed OS UUID and identical data
identity. Not yet executed: the clean guest is still extracting the OS image.
Provisioning now initializes Traefik TLS settings only if absent, using the
existing create-if-absent helper, instead of overwriting preserved settings.
Default-helper tests and static checks pass. This small preservation fix is
newer than ISO0b058049 and must be included in the preserve-reinstall candidate.

## Beamer username follow-up (local only)

User powered the Lenovo off; do not contact or deploy to it until told otherwise.
Implemented requested username form default `Beamer`, private credential storage
and host projection. Login resolves an exact unique name before password
submission, then checks the resolved ID against the module's selected Player;
the session watchdog retains that ID. Duplicate/missing names and privileged
accounts fail closed. Legacy ID records remain readable and operational.
Setup37 unit tests, typecheck, production build and targeted real-browser form
test pass. Host projection5 tests and login helper2 tests pass. Real Foundry
integration test now exercises username login but has not yet been rerun.
Initial browser test used an old production bundle and failed as expected;
after rebuild the updated default-name/save/privacy flow passed.
Clean VM2232 continued through bootloader and postinstall/cloud-init stages
while these tests ran; harness25376 remains the installation handle.

Real Foundry14.367 probe session68291 now passed username resolution/login,
least-privilege Player verification and camera settings. Persistent-profile
wrong-password and revocation checks are still running; preserve this process.
Only the isolated `elderbrain-beamer` fixture world on loopback30001 is used,
not the physical appliance. Its temporary test user is cleaned up by the probe.
VM2232 is still in Subiquity security updates; its live-installer SSH currently
rejects the installed root key (expected before late provisioning). The host key
in `/tmp/elderbrain-storage-2232-known-hosts` may therefore be the live installer,
not the final appliance identity. Do not interpret this as installation failure.

Session68291 completed exit0: real username login, cached-profile wrong-password
rejection, ready heartbeat and revocation shutdown all passed. Temporary test
user removed from the isolated world. No Lenovo deployment performed.

## Snapshot foundation (not yet wired into host jobs or UI)

Added `local_snapshots.py`: verified persistent storage, private root-owned
checkpoint directory, exclusive lock, minimum free space, mandatory quiesce
context, read-only snapshot creation/property verification, filesystem sync and
durable completion metadata. Incomplete snapshots are retained for diagnosis.
Unsupported nested user-data subvolumes are rejected rather than silently omitted
(Btrfs snapshots are nonrecursive; see
https://btrfs.readthedocs.io/en/latest/btrfs-subvolume.html).

Three unit tests pass. Real private-namespace Btrfs test on VM2226 passed:
prior data retained after source mutation, snapshot writes return EROFS, second
snapshot captures current content, nested data rejected. Test image retained at
`/tmp/elderbrain-snapshot-na8new83`; mount removed and loop device detached.
Still required: actual writer orchestration/durable jobs, list/retention/recovery,
component-selective restores, automatic checkpoints and UI. No claim of a
finished snapshot feature. VM2232 advanced to Elderbrain late provisioning.

Snapshot listing now validates private metadata, IDs, timestamps and actual
read-only Btrfs subvolumes. Explicit retention keeps at least the newest N and
caller-supplied protected IDs; verifies all records before deleting anything,
uses exact subvolume paths and committed Btrfs deletion, and preserves source
data. Corrupt/incomplete records block pruning for diagnosis. Four unit tests
pass; real Btrfs listing/protected retention/pruning passed on VM2226 fixture
`/tmp/elderbrain-snapshot-6siyxwck`. Only the old test snapshot was removed;
the newer fixture snapshot and image remain, unmounted with loop detached.
Durable pin ownership and interrupted-prune recovery still need orchestration.

Pruning now durably renames completion metadata to a deletion intent before
the Btrfs delete; explicit recovery revalidates the target and completes pending
deletions, including a crash after committed deletion but before metadata cleanup.
Real Btrfs interruption test passed on VM2226 at
`/tmp/elderbrain-snapshot-fr01z834`; only test checkpoints pruned, source intact,
newest checkpoint retained. Host-job boot recovery/pin orchestration still pending.

Enabled diagnostic root SSH only in VM2232's live installer using the ISO public
key (not a target payload change). Its existing known-hosts entry now works for
live-installer inspection. `/target/var/log/elderbrain-provisioning.log` showed
active Node/npm package unpacking, with a running dpkg process; not stalled.
The tty2 diagnostic shell is live-installer-only; do not screenshot tty2 after
the installed appliance boots. Harness25376 remains the clean qualification job.

Added `snapshot_service.py` coordinator using the existing durable Maintenance
window/host-service stop and recovery mechanism. Its optional exclusive context
holds existing display/network transaction locks, rejects pending settings, and
releases locks before service resume (graphics preparation reads those locks).
Maintenance locking excludes backup/restore/flashing. Two coordinator tests and
eight existing backup tests pass. Not yet installed or exposed as a host job/API;
full checkpoint pause/resume integration on an installed guest is still required.
VM2232 continued unpacking Node package306+ during this work.

Installed VM2230 integration passed using temporary code at
`/tmp/elderbrain-checkpoint-integration-lCQ5vtmj`: actual Compose containers and
graphics were proven stopped at capture, read-only checkpoint created, original
services resumed healthy, durable maintenance state completed. Retained private
checkpoint `c2f1f546018e4ecd2fb10c664ad6d159`; no user data deleted.
Added root CLI `snapshot-create/list/recover`, installation of the coordinator,
and allowlisted persistent host-job kinds for create/recovery. Worker result
only exposes public checkpoint metadata; 12 job tests pass. HTTP/UI wiring and
full end-to-end job test still pending; no hardware deployment. Full host suite
before the new job regression: 294 tests, 5 optional skips.

Clean ISO0b058049 VM2232 harness25376 completed exit0, with no installed-code
patches: general appliance checks, persistent storage identity/aliases/OS
separation, Foundry1000 ownership/access, HTTPS/CSRF/login gate, bootstrap,
visible admin browser and host metrics all passed. Installed SSH known-hosts:
`/tmp/elderbrain-storage-2232-installed-known-hosts`, fingerprint
`SHA256:Zm/rP5Lr230n39ZHTEyZkyhFCD22NtEOgF7IBtd0rRo`.
The separate older entry is the live installer key. Reboot test now requested
on this disposable VM; preserve-reinstall and missing-partition boot remain.

Added authenticated/CSRF-protected snapshot list/create/recover HTTP routes,
explicit downtime confirmation and a Nuxt UI Local checkpoints card on Backups.
It polls host jobs across temporary disconnection, lists verified checkpoints,
and clearly labels selective restore/retention controls as not available yet.
Setup typecheck passes. Production build + targeted browser test session68249
pending. No deployment of this newer source to the clean VM or physical Lenovo.

Checkpoint UI production build and targeted confirmation/list/job browser test
passed. Clean VM2232 rebooted from boot IDc3f3c3db-c3f7-45e8-adef-a3f97e7a5db6
to2933693e-34d8-4f61-a8a3-e8046f053bc3; general appliance/browser checks and all
persistent-storage checks passed again without code patches. Preserve-data OS
reinstall and absent-partition boot tests remain, along with UEFI qualification.

The user has powered off the Lenovo; leave it untouched until they report it on.
VM2232 preserve-reinstall baseline was seeded once and copied privately to the
host at `/tmp/elderbrain-storage-clean-AFS69C37/preserve-baseline.json` (27 files).
New ISO at `/mnt/local-hdd-Stores2/elderbrain-preserve-iso-wIGsVkGC/`
`mindflayer-elderbrain-e57c24f58122.iso` is readable, includes snapshot_service,
and has SHA256 `5c0427b507b79b9656eca96c86f6ae228a26499344296ab0b4ca827fbfed1b5b`.
Inserted it into VM2232's unused virtual CD and gracefully rebooted, selected
the Elderbrain installer, then restored subsequent boot order to disk. Preserve
selection and baseline verification remain pending; no new ISO copied to Ventoy.

VM2232 preserve selection was accepted with disk serial `elderbrain-vm-test`
and data UUID `84f7219a-b5db-4127-8ea8-2e6850746cf8`. Curtin has replaced the
OS filesystem (new UUID `a2040e32-aa13-4baa-9164-7a29ab1aab01`) and mounted
the unchanged Btrfs data UUID at the target path. Installation is still running
in curthooks; this is not yet a full preservation pass. Live-installer-only SSH
was enabled using the ISO public key, with separate known-hosts file
`/tmp/elderbrain-preserve-2232-live-known-hosts`; installed-host trust remains
separate. Returned the screen to tty1. Host regressions: 295 tests passed with
5 optional skips; static checks passed. Startup inspection confirms build/pull
commands remain in the stack unit and need replacement by installation/update
image preparation, not merely removal without providing installed images.

Checkpoint retention now honors private durable per-operation reservations
(`update`, `restore`, `pending-backup`), in addition to caller-supplied pins.
Creation can reserve a checkpoint under the same lock before publishing its
completion metadata. Reservations do not expire automatically; only matching
owner/purpose release them. Multiple owners are supported. Malformed metadata
and deletion-intent/reservation conflicts block deletion. Workflow integration
and user-facing retention settings remain to implement.

Real Btrfs test passed on VM2226 fixture `/tmp/elderbrain-snapshot-_u3g0bsk`:
store reopening preserves reservations, idempotent acquisition, multiple owners,
wrong-purpose release rejection, corrupt-pin fail-closed retention, readonly
snapshots and interrupted deletion recovery. Only obsolete fixture checkpoints
were deleted; source data stayed unchanged, newest fixture checkpoint/image
retained, filesystem unmounted and loop detached. Five snapshot unit tests and
static checks pass. This code is newer than the currently reinstalling ISO.

Added opt-in automatic checkpoint retention (disabled by default, suggested
keep=10, valid range 1–1000). Private atomic settings live in snapshots/.retention.
After a successful capture and writer resume, retention runs under the store
lock and protects the newly captured checkpoint plus all durable reservations.
Saving settings itself never deletes checkpoints. The Backups Nuxt UI card now
has an explicit automatic-deletion checkbox and count; authenticated/CSRF API
requires deletion confirmation to enable it. No arbitrary delete-path API.

Verification: production Setup build and typecheck passed; all 3 checkpoint
browser/API tests passed; 297 host tests passed, 5 optional skips; static checks
passed. Real Btrfs fixture `/tmp/elderbrain-snapshot-rm6l_hjs` proved settings
survive store reopening, saving alone does not prune, successful captures enforce
the count, and pinned checkpoints survive beyond the count. Obsolete fixture
checkpoints removed only; source intact, newest/protected snapshots and image
retained, filesystem unmounted and loop detached. No hardware deployment.
Retention settings still need inclusion in manual/remote configuration archives
and selective preferences restore; do not claim full backup coverage yet.

VM2232 preserve reinstall is now running unattended OS upgrades after successful
curthooks and GRUB installation. Keep polling this existing install, not restarting
it. The private host baseline remains the authoritative post-reinstall comparison.

2026-09-12: the host's temporary directories and VM processes were lost. The
VM2232 disk survived, but its host baseline did not. Booting the retained disk
confirmed installation was interrupted while unpacking Chrome, before runtime
installation. This run cannot qualify preservation. Cached-package recovery is
running as guest unit elderbrain-test-package-recovery. No Lenovo access.
Resumed VM: SSH2232/VNC5906, monitor
`/tmp/elderbrain-resume-9411P7Th/monitor.sock`; SSH trust now retained at
`test/.qemu/resumed-2232-known-hosts`.

Added `test/qemu/preserve-baseline.sh` seed/verify helper. It requires a persistent
absolute host directory, creates it exclusively, copies and syncs the private
baseline out of the guest, and records a checksum. Verification uses that saved
copy and SSH host identity. Set QEMU_SSH_PRIVATE_KEY and optionally QEMU_SSH_PORT;
invoke with seed or verify and the same evidence directory. Reinstall is initiated
separately. Unique fixture filenames preserve earlier test artifacts. Full helper
verification awaits a healthy guest; syntax checks pass.

The previous commit also added retention policy export/restore through
service-config/checkpoint-retention.json, rollback coverage and maintenance
exclusion for policy writes. Unit tests passed; the root-owned VM fixture test
was interrupted before its result was observed and still needs verification.

Root-owned retention archive verification now passed on VM2232 in isolated
fixture code at `/root/elderbrain-policy-test-AVrqN1Jn`: all eight backup-service
tests passed, including policy round-trip, rollback archive policy, legacy archive
behavior, private file permissions, and semantic rejection of an invalid keep=0
policy before services stop or live configuration changes. The same tests passed
locally. This fixture does not modify the installed appliance configuration.

Package recovery completed successfully. Provisioning recovery is still running
as elderbrain-test-provision-recovery.service, currently installing remaining
dependencies. It uses the original ISO payload, not newer local source. The
preserve-reinstall baseline helper still awaits a healthy starting installation.

Added pure selective-restore projections in checkpoint_components.py. Explicit
component selection rejects arbitrary Foundry subpaths, requires network alone,
and requires explicit consent for security/device identities. Preference merging
preserves current onboarding/controller state. Keypad preference merging retains
current device identities and installation history, avoids resurrecting absent
devices, advances revision and invalidates old applied proofs/expectations.
Three boundary tests pass. These are private staging primitives only; they are
not yet wired to checkpoint reads, transaction activation or an API/UI. Full
selective rollback remains incomplete, including security, network and Foundry
activation paths. Provisioning recovery remains active on VM2232.

Added checkpoint_staging.py private staging for preferences, keypad settings and
the whole Foundry data directory. It uses the component projections, emits fixed
target maps and private fsynced JSON, preserves live files, validates canonical
paths and rejects links in JSON paths plus unsafe links/special files in Foundry.
Six projection/staging tests pass. Staging has no activation/API entry point;
the coordinator must still verify/pin checkpoint identity and schema compatibility,
quiesce writers, create a rollback checkpoint, activate/recover and release pins.
Network/security/device identity coordinators remain required. This intermediate
module is not yet installed by provisioning or available to end users.

New host-created checkpoints now capture compatibility metadata while writers
are stopped: appliance version, Compose file SHA256 and actual container image
IDs (including stopped containers). Added strict compatibility comparison;
missing metadata or mismatched runtime is rejected, and Foundry restore requires
a recorded Foundry image. Legacy checkpoints remain listable; no compatibility
is invented for them. The new helper is installed by provisioning. Seven
checkpoint projection/staging/compatibility tests plus six snapshot tests and
static checks pass, including capture timing and persisted compatibility data.
The future activation coordinator must enforce this check and later add explicit
migration support; exact comparison alone is not a completed coordinated updater.

Manual/remote restore on persistent installations now creates a protected
before-restore Btrfs checkpoint while writers are stopped, before the existing
rollback archive and live file replacement. Display/network settings locks cover
mutation and release before service resume. Checkpoint protection is released
only after completed restore or recovered rollback; the checkpoint remains for
retention. Generic restore recovery preserves commit-vs-rollback behavior. New
ordering/failure tests pass; full host suite: 308 tests, 5 optional skips.
Actual Btrfs integration of this new restore hook is still pending. This does not
yet expose selective checkpoint activation or replace the manual archive path.

VM2232 provisioning recovery completed. General appliance/browser/management
bridge checks and all persistent-storage checks passed on the recovered install.
Reloaded ssh.service so it serves the preserved host key, then successfully seeded
a new test with preserve-baseline.sh. Persistent private evidence directory:
`test/.qemu/preserve-20260912` (baseline.json, baseline.sha256, known_hosts).
Use that exact directory for verification after the next OS reinstall. The old
/tmp-baseline run remains unqualified; this is a new test. Current guest software
is the old ISO payload; newer restore hooks are not deployed there.

New preserve-test ISO built successfully from 4d07fc3008ac (working-tree dirty
marker reflects the user's unrelated .gitignore edit):
`/mnt/local-hdd-Stores2/elderbrain-preserve-current-CLRYutzI/mindflayer-elderbrain-4d07fc3008ac.iso`
SHA256 `fb2d327f223a4b7101464430ea49593cc5430e40c61a9517b34db15b4eb2e805`.
Verified the persistent baseline checksum, inserted the ISO into the empty
virtual CD, gracefully rebooted VM2232, selected the Elderbrain installer and
reset subsequent boot order to disk. Preserve console selection is next; no
formatting has been confirmed yet. Verify afterward using the existing
`test/.qemu/preserve-20260912` baseline, never reseed that directory.

The preserve selection was subsequently confirmed on the live VM after matching
disk serial elderbrain-vm-test and data UUID
84f7219a-b5db-4127-8ea8-2e6850746cf8 against the checksum-verified baseline.
The installer completed its storage configuration and reached OS image extraction.
Post-install baseline comparison remains pending; this is not yet a preservation
pass. No physical appliance or Ventoy changes were made.

Restore recovery now releases pins by the terminal operation's durable ID and
restore purpose, even if a crash prevented rollbackCheckpoint from reaching the
outer maintenance journal. Other owners/purposes remain protected, corrupt pins
block cleanup, and checkpoint data is never deleted by this operation. Release
requires completed/rolled-back state and tolerates repeated recovery. Twenty
focused restore/snapshot tests pass, including the missing-journal-ID crash
window. This newer fix is not included in the ISO currently installing.

Selective checkpoint activation now has a root CLI path for preferences, keypad
settings and whole Foundry data. Example (after inspecting snapshot list):
`sudo python3 /opt/mindflayer-elderbrain/snapshot_service.py restore --checkpoint ID --component preferences --confirm-restore`.
Repeat --component to combine supported components. Network, security and device
identities still require their dedicated coordinators and remain unavailable.
The host flow verifies compatibility before downtime, pins/rechecks the source
under maintenance, stages after writers stop, captures rollback state, activates
using the existing durable transaction, checks health and rolls back on failure.
Preference activation and recovery also regenerate the domain's Traefik routes.
Snapshot recover dispatches interrupted restores through fixed-target recovery.
These modules are now installed by provisioning; API/UI integration and real
Btrfs/Foundry activation tests remain pending. The current VM ISO predates this.
Full host suite passed 315 tests with 5 optional skips before the route-refresh
addition; all 29 checkpoint/restore tests passed afterward, including route
activation/rollback. VM2232 remains in kernel installation, not yet verified.

Setup now exposes preferences/keypad-settings/whole-Foundry checkpoint restore
through the authenticated, CSRF-protected API and allowlisted host-job bridge.
The Nuxt UI requires checkpoint/component selection plus separate replacement
and downtime consent, resets replacement consent on selection changes, reports
jobs, and warns that physical keypad state must be reapplied separately. Root
admission and worker validation reject unsupported selections and extra fields;
public job results omit internal restore journals. Keypad flashing now rejects
every unfinished maintenance state, including selective-restore staging.
Fifteen host-job tests, four checkpoint browser tests, Setup typecheck/production
build, Python syntax, shell syntax and whitespace checks passed. Browser tests
use the production Setup build and a fake management bridge: real Btrfs/Foundry
activation remains unqualified. Worker cgroup durability and dedicated
network/security/device-identity restore paths remain outstanding.
The same VM reinstall has progressed through GRUB/security updates to running
the Elderbrain provisioning script. Preserve-data verification is still pending.

Host job workers now launch in uniquely named systemd scopes instead of remaining
inside management.service's cgroup. The scope preserves inherited worker-lock and
memory-only passphrase descriptors; no secret is added to unit properties or argv.
Sixteen host-job tests pass. `python3 test/host-job-scope.py` also passed against
real, disposable user systemd units: stopping the launcher service did not stop
the worker or release its inherited lock, and the memory-only input survived.
The test cleans up only its unique fixture units. Root system-manager/appliance
restart testing remains pending; local root access requires a password. Jobs
still require recovery after power loss and can be interrupted before scope
handoff; no automatic replay of destructive operations is introduced.

Live-installer diagnostics now confirmed active package installation, not a hung
provisioner: bash PID21305, apt PID24531 and dpkg PID24762 were running, with
advancing package logs and disk I/O while unpacking Node tooling. The OS UUID is
now 589bfe02-676f-427d-857c-6f5608a7b29e; the Btrfs UUID remains
84f7219a-b5db-4127-8ea8-2e6850746cf8. This is partial storage evidence, not the
post-install preservation pass. The existing baseline remains untouched.
Diagnostic SSH uses `test/.qemu/preserve-20260912/live-installer-known-hosts`,
whose temporary key was verified on the confirmed live installer console:
SHA256:pGtBpr6dJcEufxdDY3tM+UWXb/wu+LoY0lHKQT6PBkU.
The saved appliance trust remains in the separate `known_hosts` file. The ISO's
public authorized key was copied into the live installer only; tty1 was restored
after diagnostics. Do not trust the temporary key as the installed appliance key.

The scope-survival fixture now also supports root only on the disposable QEMU
disk (DMI and exact disk serial checks). It passed against the live VM's system
manager from `/root/elderbrain-scope-test-z9moOWxT/host-job-scope.py`: stopping its
launcher service preserved the worker, inherited lock and memory-only input.
Only uniquely named test units were stopped; provisioning and target data were
untouched. This closes the root-vs-user scope mechanism check, not the remaining
installed management-service restart test. No new ISO was built or deployed.

`test/qemu/checkpoint-restore.py` passed in the live VM with current modules,
inside a private mount namespace and a fresh 1 GiB sparse loopback Btrfs image.
Evidence directory: `/tmp/elderbrain-checkpoint-restore-8oyj9e14` (unmounted and
loop device detached afterward). Real Btrfs snapshots/pins, private staging,
archive validation, transaction replacement and recovery passed: preferences
restore preserved current onboarding/unselected Foundry data; automatic rollback
checkpoint retained old preferences read-only; simulated Foundry health failure
and process loss restored the previous whole data directory and released pins.
The fixture simulates service health/runtime metadata and host alias refresh;
it does not qualify actual Foundry containers or OS mount aliases. Production
storage guards remain unchanged; the fixture checks its own mounted UUID.
The installation disk, preserve baseline and running installer were untouched.

Network transaction journals now represent absent files distinctly from empty
files, allowing validated candidates to add/remove Netplan sources and recover
exact previous contents/modes after timeout or process loss. External edits block
rollback instead of being overwritten. All 55 network tests pass, including four
new addition/deletion tests. This is groundwork for checkpoint network restore;
checkpoint source preparation, timed restore entry point and UI remain pending.

The preserve-test installer rebooted into the installed appliance. Console shows
management started and stack startup running. SSH now presents
SHA256:EkwA/FqKM4IDJd5cmOt1Ob4c1iYl+S0DY/2cmKO6gwk, unlike both the temporary live
installer key and saved appliance identity. Neither trust file has been replaced.
This requires diagnosis before claiming preserve-reinstall success; do not reseed
the existing baseline or treat a new key as proof of preservation. Installed tty2
may contain the bootstrap password and must not be captured.

Preserve failure diagnosed: first-boot cloud-init cc_ssh logged removal and
regeneration of all host keys at 09:21:02 through the persistent /etc/ssh bind.
Read-only comparison of the original 27-file baseline found exactly six changes:
RSA/ECDSA/Ed25519 private/public host keys. All other tracked files and the
appliance/data identity matched. This run fails SSH identity preservation.
Diagnostics use `reinstalled-diagnostic-known-hosts` in the same test directory,
after verifying the QEMU process owns the exact loopback forwarding and disk;
the original appliance and temporary installer trust files remain unchanged.

Provisioning now installs a cloud-init policy with ssh_deletekeys: false before
binding persistent host directories. The installed cc_ssh source skips generation
when the corresponding key already exists. The policy passes the installed
cloud-init schema validator (an initially attempted empty ssh_genkeytypes list
was rejected and removed); two local policy/order tests and shell checks pass.
No policy was applied to the VM and no keys were restored or baseline reseeded.
A new ISO/preserve reinstall must verify this fix end to end before qualification.

New independent SSH-fix preservation run seeded at
`test/.qemu/preserve-sshfix-20260912` after stack/management/graphics were healthy
and guest-storage.py passed. Its baseline checksum passes. Previous failed-run
evidence remains untouched. New baseline OS UUID is
589bfe02-676f-427d-857c-6f5608a7b29e, persistent data UUID remains
84f7219a-b5db-4127-8ea8-2e6850746cf8, and expected host key is
SHA256:EkwA/FqKM4IDJd5cmOt1Ob4c1iYl+S0DY/2cmKO6gwk.
Fixed ISO built successfully from b3213854c772 (dirty marker only the unrelated
user .gitignore edit):
`/mnt/local-hdd-Stores2/elderbrain-ssh-preserve-xGN4gEA1/mindflayer-elderbrain-b3213854c772.iso`
SHA256 a03d8bd0c5dab3f91a246cda1867ca6a3c4afeb0d70ea3628316f862edead3ae.
Verified Ubuntu signature/checksum, changed the VM's ide1-cd0 to the new ISO,
set next boot to CD and requested a graceful reboot. Installer selection and
preserve confirmation remain pending. Reset boot order to disk after selecting
the installer. Do not reseed the new baseline. No Ventoy/Lenovo changes.

The VM reached the ISO GRUB menu and is now booting the live installer. A down/
enter selection was sent near the menu timeout, so verify that the Elderbrain
storage prompt actually appears (do not assume the selected entry). Subsequent
boot order is reset to disk. No preserve inputs or formatting confirmation have
been entered for this new run yet.

The first boot was confirmed to be the generic Ubuntu language screen, with no
installation started. Reset that idle live session, interrupted the GRUB timeout,
and explicitly selected Elderbrain. Its storage prompt appeared. Entered preserve,
verified displayed disk serial and both OS/data UUIDs against the SSH-fix baseline,
then confirmed `REINSTALL OS elderbrain-vm-test`. The new preserve install is now
authorized; continue observing this run, not restarting it. Boot order is disk.
Final verification must use `test/.qemu/preserve-sshfix-20260912` unchanged.

Network staging now accepts a complete archived /etc/netplan YAML file set and
validates it in a private temporary root with the current compatible vendor/run
layers. It emits additions/removals/replacements for the existing timed journal,
rejects unsafe names/oversized values and concurrent source changes, and never
writes live network files. Returned merged configuration/bytes stay private.
All 24 staging/transaction tests pass, including file-set restoration and source
conflicts. This does not yet connect checkpoints to the network coordinator or
expose a network-restore UI. The fixed-ISO preserve install reached OS extraction.

Private network_service.restore_files now passes the complete validated archive
candidate to the existing timed transaction worker, deriving its confirmation
binding from the selected archived interface instead of current/requested IPs.
It checks recovery services before and after validation, requires an active
noninternal interface, rejects mixed DHCP/static or ambiguous IPv4 destinations,
and returns only the one-time token/public transaction status and generic warnings.
The archived configuration itself is not projected or exposed. All 60 network
tests pass. The checkpoint coordinator must still supply verified/pinned files,
compatibility checks, recovery checkpoint and maintenance exclusion before this
private entry point can be exposed; no new network-restore API/UI exists yet.
The same fixed-ISO preserve install has reached kernel installation.

Checkpoint staging now reads network YAML only from fixed host/netplan, with
descriptor-relative no-follow traversal through both directories and files,
bounded regular-file reads, filename validation and no live/empty fallback.
Credential-bearing contents remain private and require a caller-held source pin.
Thirteen checkpoint tests pass, including missing scope, directory/file symlinks
and FIFO rejection. This supplies the source reader for the pending checkpoint
network coordinator; it does not expose network restore on its own.

Timed network journals can now retain a validated private restore-owner ID and
run retryable cleanup only after durable confirmation/rollback. Cleanup runs
outside the network lock to avoid inversion with snapshot capture. Failed cleanup
retains the terminal record and prevents a new transaction from overwriting it;
successful cleanup is durably acknowledged for that same transaction. All 63
network tests pass, including backend rollback failure, cleanup retry, lock
release and owner validation. The production checkpoint-owner cleanup callback
and full network checkpoint coordinator are still not wired; ordinary networking
has no owner/callback and keeps its existing behavior. The VM reached GRUB and
OpenSSH installation in the same preserve run.

The same SSH-fix preserve run is now executing Elderbrain provisioning in the
live installer, not yet booted into the installed appliance. Console-verified
live SSH fingerprint is SHA256:0P8t8AYsmNoYB6/+tZDo/xH/INMIhuVyVbMltm3Lf/U,
saved separately as `live-installer-known-hosts` in the SSH-fix evidence directory.
The appliance `known_hosts` and baseline remain unchanged. Live processes 21289
(provisioning), 24511 (apt) and 24736 (dpkg) were confirmed running; dpkg reached
node-corepack unpacking at 09:48:23. Returned the live console to tty1. Do not
restart this installer or interpret its temporary key as an appliance regression.

The preservation verifier now requires a nonempty, non-symlink saved trust file,
checks the baseline checksum before remote activity, and uses strict SSH checking
with no global trust fallback. Only initial seeding permits accept-new. Five
regression tests pass for missing/empty/linked trust, corrupt/missing checksum,
and strict verification arguments; shell syntax and diff checks pass. End-to-end
preserve qualification still awaits this installation's completion.

Private `network_checkpoint_restore` now coordinates source pinning, repeated
storage/runtime compatibility checks, writer quiescing, a pinned before-restore
checkpoint, service resumption outside settings locks, and durable handoff to
the timed network journal. Its production factory uses verified persistent
storage and the fixed-scope Netplan reader. Network staging carries the private
restore-owner ID; neither credentials nor the one-time token enter maintenance
records. Pending network work retains maintenance exclusion and both pins.
Generic backup recovery rejects this operation rather than resuming it blindly.

Terminal cleanup releases pins without starting services, making the callback
suitable for early boot. Private per-owner completion receipts permit retry if
another maintenance operation replaced the terminal global record before the
network worker acknowledged cleanup. Tests cover process loss before/after
handoff, stage response failure, validation failure, service-resume failure,
cleanup retry, maintenance reuse, incompatible/changed storage, and early-boot
callback safety. All 77 network tests pass; backup-service tests also pass.
Shell syntax and diff checks pass. The module is installed by provisioning but
the production network-worker callback, dedicated recovery routing and API/UI
admission are still not connected; network checkpoint restore is not exposed yet.

The same live installer processes 21289/24511/24736 remain active; dpkg advanced
to node-gyp at 09:52:14. No reinstall restart, baseline replacement, Ventoy copy
or physical Lenovo access was performed.

Network workers now lazily attach the checkpoint cleanup callback to their exact
journal, including boot rollback and normal deadline/confirmation processing.
Ordinary networking never constructs the checkpoint coordinator. Completed
cleanup is skipped rather than rewriting/fsyncing its acknowledgment every tick.
The snapshot recovery command routes network restores through their dedicated
coordinator and does not run snapshot recovery if networking is still pending.
All 79 network tests and the five snapshot-coordination tests pass. Production
API/UI admission and real-VM network checkpoint restore qualification remain.

The SSH-fix preserve reinstall completed and booted with the expected saved
appliance host key. `preserve-baseline.sh verify` against the unchanged
`test/.qemu/preserve-sshfix-20260912` baseline passed: OS replaced; data identity,
fixture contents, SSH identity and settings preserved. The baseline checksum
also passed. `guest-storage.py` passed its persistent aliases, OS/data separation,
directory ownership/access and storage service dependency checks on that guest.
This qualifies the populated BIOS preserve case for the b3213854c772 ISO, not
UEFI, missing-data boot, offline startup or newer network-restore code. General
installed-service/browser checks are running through exec session 29808.

General installed-guest qualification (session 29808) completed successfully:
stack/management/graphics, Sway/Chrome, all three expected healthy containers,
the pinned server image and v3 capabilities, serial tooling, private installation
journals, routing/TLS probes, and the Setup container's actual host bridge access.
This VM has no running licensed Foundry instance, so this does not qualify actual
Foundry restore. The immutable SSH-fix preservation baseline remains available.

Authenticated `POST snapshots/restore-network` now admits a durable independent
host job after explicit replacement/downtime consent and checkpoint/interface
validation. Setup generates a random confirmation capability, returns it once
to the caller, and sends only its SHA-256 digest through the host bridge/job.
The worker repeats admission validation, starts the verified coordinator and
exposes only transaction ID/phase/deadline/interface, never raw staging output.
The archived candidate determines the address binding; the supplied digest only
binds the initiating browser's capability. A lost response still results in timed
rollback, not an unauthenticated confirmation route.

Thirty-seven focused host tests pass. Setup typecheck/build and a production API
test pass, including anonymous 401, CSRF 403, missing consent/invalid selection,
no-store response and verification that job history contains only the token hash.
The host bridge is syntax-checked; real systemd job/network restore and UI flows
remain to qualify. No network-restore UI control has been added yet.

The Network page now offers a separate Nuxt UI checkpoint selector and explicit
network replacement/downtime consent, using the selected active interface and
existing direct-address confirmation panel. Selection changes reset consent;
submission focuses the address field. Queued restore polling does not erase the
capability on an older idle/terminal network response. Failed/interrupted jobs
without their own network transaction direct users to maintenance recovery.

The host job ID is now the preallocated network transaction ID, validated through
coordinator/staging and protected against reuse of the current journal ID. Thus
the browser has its ID/token before services stop and can confirm at a manually
entered new IPv4 even if the old address becomes unreachable before job-result
polling. Only network activation starts the host's confirmation deadline. A
missing browser-side deadline does not prevent a direct attempt; the host still
enforces its real deadline, token binding and connection destination.

All five selected network browser tests pass, including queued-token retention,
disconnection/direct confirmation with the preallocated ID, API auth/CSRF,
ordinary static settings, lost responses and reload/token loss. Fifty-nine
focused host tests pass; Setup typecheck/build and diff checks pass. Actual VM
network checkpoint restore remains unqualified, and the physical Lenovo stays
untouched. The Backups page now points to Network for this separate restore.

Real installed-VM network checkpoint restore confirmation passed. Verified QEMU
DMI/serial and healthy services first; backed up previous installed host modules
at `/root/elderbrain-network-qualification-uVAuzb0L/previous-host-modules.tar.gz`,
then deployed current host Python modules/management bridge (no Setup container
rebuild or physical-host changes). The QEMU-only fixture captured an actual
readonly checkpoint, appended only a comment to the live Netplan source, admitted
the restore through the management socket, and restarted management while its
independent worker was running. The job completed with its preallocated ID.
Actual netplan activation and the dedicated TLS listener confirmed the token over
a CA-verified direct host connection. Source bytes matched the archived version,
the before-restore checkpoint retained the modified version, maintenance completed
and owner pins were released. Required services were active afterward.

Confirmation evidence: `/root/network-restore-evidence-tjb93wnj`, job
`1a4db4591157420fbb38584f03b827c4`. The fixture retains private originals and
checkpoint IDs, never logs the capability, and rejects non-QEMU/nonmatching disks.
A second run of the same fixture with `--rollback` is running in exec session
5064 (guest test PID 14123), network ID `963de7516bb9498dac6e91235c78ef79`, pending
at its real deadline 1789207946.1120281. Do not restart it. Its final verification
must prove exact pre-restore bytes, released pins and restored services before
removing only the fixture comment. This stable-IP test does not qualify an actual
address transition or reboot mid-restore. All 361 host tests pass (five skipped),
including 80 network tests; fixture syntax/diff checks pass.

The second run completed successfully without confirmation. The independent
watchdog reached its actual deadline, rolled back the exact pre-restore Netplan
bytes, completed maintenance cleanup and released owner pins. The recovery
checkpoint contents and active services passed; the fixture then removed only
its own verified comment. Evidence: `/root/network-restore-evidence-w5pr5yt4`.
Session 5064 exited zero; it is no longer running. Both real stable-IP confirmation
and deadline rollback now pass, including management restart while each worker
was live. Address-changing and reboot-mid-restore qualification remain separate.

Coordinated release groundwork now verifies exact signed manifest bytes with a
separately supplied pinned appliance public key before JSON parsing. Format 1
binds independently versioned host/Setup components, a host archive size/hash,
digest-pinned Setup and dependency images, platform/schema, host API compatibility,
release notes and downtime estimate. Duplicate/unknown fields, mutable image
references and mismatched package bytes fail closed. Setup-only compatibility
checks the installed host API. Nine tests pass using real temporary RSA/OpenSSL
signatures, tampering, schema/platform/API failures and unsafe host paths/types.
See `RELEASE-FORMAT.md` for the contract and remaining activation/trust boundaries.
No production signing key/release was created. Packaging, trusted download,
migration/checkpoint/activation/rollback and replacing ordinary boot builds/pulls
remain implementation work; this verifier alone does not enable updates.

Host release staging now authenticates metadata, copies the compressed artifact
privately and verifies that exact copy before bounded decompression. A trusted
caller inventory determines every accepted file and normalized mode. Regular-file
only extraction rejects traversal, duplicates, missing/unexpected files, links,
devices, sparse/PAX entries and privileged mode bits. Kernel output-size and
process-time limits constrain decompression; files/count/total have separate
bounds. No live install path or service is touched. Sixteen release/staging tests
pass, including real signed zstd extraction, hash-before-decompression ordering,
private-directory cleanup and an actual kernel-enforced decompression failure.
The production inventory/builder and durable activation coordinator remain next;
this private staging helper is not yet installed or exposed through the updater.

Added reviewed `release/host-files.json` (83 source entries) and a deterministic
unsigned host-code builder. It adds the independent host VERSION, writes sorted
regular USTAR entries with normalized owner/time/mode, compresses with zstd and
publishes via an exclusive hard link after fsync. Missing/nonregular/symlinked
sources and duplicate/reserved inventory paths fail closed. Live environment and
Sway settings are not runtime payload entries; defaults are templates. Private
ISO configuration, signing keys, Setup source/caches and installed dependency
directories are excluded. Four builder tests pass, including reproducibility,
no overwrite and a full 84-file real signature/staging round trip. A local
unsigned 0.0.0 test artifact exists at `/tmp/elderbrain-host.tar.zst`; it is not a
production release and was not deployed or published. Prebuilt Setup/dependency
packaging, release signing/publication and actual installation remain pending.

Local release assembly now joins the reviewed host builder, manifest validation,
detached signing and independent-pin/package-staging verification in one command.
Artifact size/hash are computed, not accepted as metadata overrides. Private key
ownership/mode checks precede signing; no key is generated or copied into output.
Exclusive output directories preserve existing releases, files are fsynced, and
the manifest is made visible last only after successful end-to-end verification.
Five tests pass using temporary real keys: reproducible complete artifacts,
wrong independent pin with no manifest publication, existing-output preservation,
unpinned images/metadata overrides, and insecure private-key permissions.
Only temporary test-key releases were assembled. No production key, publication,
registry write, installation or host hardware change occurred. Image existence/
import, complete offline host dependencies and activation remain unimplemented.

Signed release image preparation now defaults to local inspection only; missing
images require explicit download permission. Pulls use only the signed digest and
platform and are followed by registry-digest/local-ID/platform verification.
Setup image version/API labels must match the signed manifest, and Setup-only
preparation requires compatibility with the installed host API. No builds,
container starts, tag changes or pruning occur. Added Setup Dockerfile metadata
arguments and included the helper in the reviewed host package inventory.
Seven tests cover offline/missing images, exact explicit pull/reinspection,
signature ordering, digest/platform/label mismatches and API compatibility.
Read-only inspection of the VM's real cached Mindflayer server image passed with
no pull or container action; helpers were copied only into its private test folder.
This is not yet integrated into ordinary startup, installation or update activation;
no newly labelled Setup image or complete signed production release was built.

Added release Compose rendering: signed digest literals replace all four image
references, Setup build configuration is removed, all services prohibit implicit
pulls, and Setup's server-image metadata matches the coordinated release. Exact
comparison tests prove all unrelated configuration/interpolation is preserved.
The reviewed host package now carries a release-specific stack unit with no
build/pull precommands, explicit --no-build/--pull never and bounded health/startup
waits. Five tests pass, including real Docker Compose validation with Foundry's
profile enabled (no daemon/container action). Host package round-trip tests pass.
The installer bootstrap unit remains unchanged; activation still must render,
validate and install this release runtime after prebuilt image/dependency setup.
No live unit changed, and disconnected cold boot is not yet qualified.
