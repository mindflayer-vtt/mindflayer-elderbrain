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

Durable release preparation now connects signature/platform/schema validation,
private archive staging, explicit image preparation, generated pinned Compose and
config-only validation. It takes a private preparation lock, checks staging space,
refuses existing versions, fsyncs its complete tree and publishes via directory
rename. It retains the authenticated archive/manifest/signature for re-verification
and records image identities without copying the persistent environment. No live
runtime or service is touched. Seven tests pass with real signed package assembly
and extraction plus mocked Docker: success, tampered artifact before image work,
Compose failure with no published version, existing-version preservation, low
space, concurrent preparation and private parent enforcement. Receipts explicitly
remain dependenciesPrepared=false/activationReady=false: complete offline host
dependencies and actual update activation/rollback are still unimplemented.

Read-only VM inspection found Python 3.14.4 and Node 22.22.1; both installed
Python environments passed pip check. Pinned serial's full 14-package runtime set
to these qualified versions rather than leaving esptool transitive resolution
open. Added a target-platform dependency builder: exact runtime pins, no runtime
dependency resolution, reviewed browser graph plus SHA-512 lock integrity, and
per-artifact/input hash receipts. Four input/platform tests pass.

Real Ubuntu VM build completed in session 74336: 27 Python wheels plus the locked
playwright-core archive at
`/root/elderbrain-network-qualification-uVAuzb0L/dependencies-build-1`.
Fresh disposable serial/borgmatic environments and browser helper then installed
successfully under `unshare --net`, pip --no-index/--no-deps and npm --offline.
Both pip checks passed; esptool 4.9.0, borgmatic 2.1.7 and Playwright import checks
passed. Evidence environments remain at `/root/elderbrain-offline-deps-8C13ePwE`.
Added the reusable QEMU-only offline check script with a network-namespace guard.
No live runtime environment changed. All 409 host tests pass (five skipped).

This qualifies the built dependency inputs, not complete release delivery:
dependencies.json is still unsigned and intentionally reports verification false.
The signed manifest/archive chain and durable preparation must incorporate and
reverify these dependencies before any activationReady flag can become true.
OS-level packages/Chrome/Docker compatibility and activation/rollback also remain.

Format-2 signed releases now require a dependency archive descriptor, cp314 ABI
and bounded exact file inventory (names, sizes and SHA-256). A dependency packager
checks freshly built bytes against their receipt, emits deterministic regular-file
tar/zstd, and local assembly computes/signs dependency metadata rather than accepting
caller overrides. Both host and dependency archives are verified/staged before the
manifest is published. Staging checks the compressed archive hash and every signed
file hash, rejects unsupported path scopes, and never executes dependency code.
Six signed-dependency tests pass, including the real signature/staging chain,
changed payload/receipt, missing format-2 dependency directory, unsafe inventory
and an intentionally inconsistent signed per-file hash. Existing format-1 tests
remain supported for code-only development. Durable preparation/offline install
integration remains next; activationReady remains false and no production release
or signing key was created or published.

Durable preparation now requires the signed dependency archive for format 2 and
rejects unsigned extra dependency archives for format 1. Before Docker activity,
it verifies/stages dependency bytes, checks the receipt target and exact signed
file inventory, and binds its three input hashes to the staged host requirements
and browser lockfile. Verified inputs and the exact authenticated compressed
archive are retained in the atomically published prepared release. Receipts now
report dependencyInputsVerified separately; dependenciesPrepared/activationReady
remain false even if a builder claims offlineInstallVerified=true. Six new tests
cover successful retention, missing/extra archives, host-lock mismatch, tampering
and invalid Python target. All 421 host tests pass (five skipped) with local socket
permission; the initial sandbox run failed only the 12 socket-dependent tests.
No live runtime changed. Offline installation integration and activation/rollback
remain next.

Added independent signed offline dependency installation at an exclusive stable
version prefix. It re-stages both authenticated archives, checks input/lock hashes,
installs exact wheel pins without network/dependency resolution, installs the
locked browser tarball with scripts disabled, and checks versions/imports/pip
consistency. All subprocesses use unshare --net and a sanitized environment.
Completion is fsynced only after installed files; partial prefixes remain without
a completion marker and cannot be overwritten or relocated. Activation remains
false; live runtime links/permissions and update recovery are not yet connected.

Real QEMU qualification passed using the existing 27-wheel/browser input bundle.
Evidence: /root/elderbrain-signed-deps-s8pogki6 (fresh private source directories
were used per attempt).
The test signs only disposable test artifacts with non-deliverable image refs;
no production release or live service changed. Both Python environments passed
offline checks, browser import passed, and borgmatic 2.1.7 ran after staging
cleanup. Earlier retained failures exposed a missing file in the test source copy,
USTAR's filename limit for a real wheel, and npm rejecting a shared /dev/null
configuration pathname. Fixed packaging with dependency-only path PAX metadata
under the exact signed allowlist and separate empty npm configuration files.
Added four installer tests, one long-filename archive regression and the reusable
QEMU signed-dependency qualification. The full host suite runs 426 tests with five
skipped; the focused post-npm-fix tests pass as well.

Release preparation now optionally drives the authenticated offline installer
using a separate stable dependency directory. After image/Compose validation it
passes the retained verified archives, checks the returned release/manifest/prefix,
and creates stable runtime links for both Python environments and browser modules.
Only successful installation publishes runtime-prepared/dependenciesPrepared=true;
activationReady stays false. User configuration remains absent from the code tree.
Nested dependency/preparation directories are rejected; installation or receipt
failure publishes no runtime, and installer evidence remains at its stable path.
Four integration regressions cover links/settings preservation, failed installs,
overlapping directories and mismatched receipts. The combined preparation/installer
suite passes 21 tests. This turn did not modify the VM or physical appliance.
Live settings aliases, service/unit switching, deployment permissions and durable
update recovery remain unimplemented.

Added an internal update activation transaction with a distinct update maintenance
record, fixed host target mapping, signed format-2 admission, required checkpoint,
journaled replacement and health-before-commit. The existing replacement engine
retains old code trees. Recovery records possible data mutation before new service
startup, then restores both old code and the checkpoint if health/startup fails.
Stop or checkpoint-restore failure leaves recovery-required without restarting
writers; a committed switch survives a crash before maintenance completion.
Generic backup recovery now refuses update records. Ten tests use real signed
manifests and real temporary-directory switches with fake service/checkpoint
adapters, covering healthy retention, health rollback, missing checkpoint, crashes
mid-rename/during-health/after-commit, stop and checkpoint-restore failures,
signature rejection and settings-lock release before restart. The full suite
passed 438 tests (five skipped) before the final two focused recovery tests.
No live deployment occurred. Trusted prepared-runtime verification, fixed actual
host targets, checkpoint adapter, update-specific service health/interlocks and
stable boot-recovery worker wiring remain before enabling activation.

Added UpdateServices for update-specific worker/Compose control. It requires the
stack's stable active/exited state, saves an explicit worker allowlist, stops all
listed workers and affected containers, and restores only the previously active
set. Recovery stopping uses project labels, not a potentially broken new Compose
file. Validation rejects builds, mutable images, implicit pulls and service-set
changes; recreation explicitly forbids builds/pulls and runs container/worker plus
required API health checks before graphics. It deliberately does not invoke stack
startup, backup rescheduling or secret/certificate mutation during health recovery.
Seven command-level tests pass; the combined service/activation/package suite
passes 21 tests. Read-only QEMU systemctl checks confirm the actual stack is
active/exited and all five allowlisted host workers are active. No service was
stopped or changed. Concrete health/interlock/checkpoint adapters, offline legacy
rollback preparation and stable boot recovery remain pending before live use.

Activation now defaults to job admission -> maintenance -> stable-settings locks.
The admission gate checks actual worker locks, excludes live/queued host jobs
(including flashing), and permits only an explicitly identified live update owner
to exempt itself. Settings preflight moved ahead of the first update journal write,
so an unconfirmed network/display change does not create a spurious interrupted
update. Network/display start entry points in management now acquire maintenance
before transaction locks, preventing starts during update health checks. The new
shared module is included in both fresh provisioning and the reviewed host package.
Five new tests cover live flashing, stale worker records, owner/gate validation,
live/interrupted maintenance exclusion and pending settings with no service stop
or update journal. No VM or physical appliance changed this turn; stable-worker
admission and actual update API/recovery wiring remain pending.

Added release_runtime.candidate: reconstructs private code directly from the
retained reauthenticated archives, ignores loose prepared code, checks dependency
input binding and installation receipt identity, reruns seven offline dependency
checks, verifies cached signed images without downloads, regenerates pinned Compose
and validates it using persistent environment aliases. Storage identity is checked
before and after preparation. Persistent settings are linked, never copied or
overwritten; dependency links retain stable prefixes. Six tests cover ignoring a
tampered loose code tree, archive tampering, mismatched installation receipt,
missing/changed storage and broken dependencies before image work. Tests use real
signature/archive reconstruction with mocked execution/storage, not live activation.
Deployment permissions, fixed target/checkpoint adapters and the stable recovery
worker remain pending. No appliance was changed this turn.

Resolved the candidate's kiosk permissions boundary. The unprivileged graphics
service cannot traverse private stable dependency prefixes, so candidate creation
now copies only relocatable browser modules into its code tree, checks bounded
installer-owned regular/relative-link entries, rejects unsafe permissions/escapes,
and rechecks the copied module. Code directories and copied JS receive public
read/execute permissions; Python prefixes and persistent settings are untouched.
Two new regressions cover escaping links and writable browser code, and the
candidate test checks private-prefix and secret-file modes remain unchanged.
Real QEMU qualification ran Node as elderbrain-kiosk and imported the copied
Playwright module successfully while the original dependency prefix stayed 0700.
Evidence: /tmp/elderbrain-browser-deployment-t33btsb9 in the VM. The reusable
test/qemu/browser-deployment.py leaves isolated evidence and changes no live runtime.
Fixed deployment targets, checkpoint adapter and stable boot recovery remain next.

Added a fixed code-owned deployment map covering runtime, CLI, ten managed units,
individual storage/network drop-ins, Chrome policy and cloud-init SSH-identity
policy. Manifest content cannot choose destinations. Preflight rejects symlinked
sources/targets, unsafe source modes, missing parent directories and unexpected
target types. It never creates missing OS structure or selects persistent settings,
SSH credentials or user-created overrides. Added the previously omitted Chrome
policy to the signed host inventory. Six tests cover inventory completeness,
real temporary-directory multi-target switch/rollback, preserved settings and
user overrides, rejected aliased targets, missing/writable parents and unsafe sources.
No live appliance changes; checkpoint and stable worker/boot integration remain.

Added UpdateCheckpoints capture/restore/release hooks. Capture creates a read-only
before-update snapshot pinned to the update operation. Release requires terminal
state and unpins by owner even when capture finished before its ID was journaled.
Data rollback checks storage, checkpoint reason/completion and previous runtime
version/Compose hash, then journal-switches fixed application/host settings scopes
without replacing snapshots/jobs/maintenance/backups. Host bind aliases refresh
before commit. Partial restore attempts are themselves reversed and retained,
then retried from the same checkpoint; committed retries only refresh aliases.
Five tests cover owned pins, preserved control-plane files, repeated restore,
interruption after data switching, incompatible/missing source and changed storage.
Btrfs/storage hooks are mocked in these tests; directory replacement is real.
No live appliance changes. Actual combined VM update/data rollback qualification
and stable worker/boot admission remain pending.

Real Btrfs update-checkpoint qualification now passes in the disposable QEMU VM.
test/qemu/update-checkpoints.py creates a fresh 1 GiB sparse file-backed filesystem
inside a private mount namespace, captures a real read-only pinned checkpoint,
changes every fixed data scope, injects process loss after directory switching,
then retries and replays the data rollback. Real SSH/Netplan bind aliases in the
isolated host fixture are refreshed and checked by inode; pin cleanup retains the
checkpoint and interrupted-attempt journal. Evidence filesystem:
/tmp/elderbrain-update-checkpoints-ls8koan4/fixture.btrfs in the VM. All test mounts
were unmounted and the loop device detached. Actual storage identity is checked by
fixture mount UUID; runtime compatibility metadata is simulated. No live runtime,
Foundry workload or appliance data was modified. This qualifies the data rollback
adapter, not full update activation or boot-time power-loss recovery.

Separated early update file recovery from running-service recovery. The shared
rollback step is now used by recover_files, which checks all managed writers plus
Docker/containerd are inactive before file changes, restores code/data and aliases,
and leaves a files-recovered maintenance record with pins retained. No Docker,
Compose validation or service start is attempted before boot writers are allowed.
Normal recovery subsequently verifies health and completes/unpins. Four new tests
cover early recovery without starts/pin release, rejection of active writers,
repeat recovery without repeated data restoration and inactive/unknown unit checks.
The focused activation/service suite passes 22 tests. Stable external worker and
boot ordering are still required; this turn did not alter appliance boot units.

Added the standalone root-only release_recovery files/finish entry point wiring
fixed targets, UpdateCheckpoints and UpdateServices. Storage is verified before
maintenance directories are opened; non-update state is a no-op, and output omits
internal service/checkpoint details. Concrete read-only health probes validate the
management Unix peer UID and bounded metrics reply, and CA-verified localhost
Setup health through Traefik without redirects. Six tests cover probes, invalid
peer/redirect/oversize/nonboolean replies, inactive components, fixed coordinator
wiring/redaction and missing storage. Both actual probes passed in the running
QEMU VM from a private source copy under isolated Python; no recovery or service
change was invoked. Independent stable-bundle installation and boot units remain.

Added stable recovery-bundle publication from a caller-authenticated host tree and
reviewed module inventory. Bounded hashes define a content-addressed private tree;
isolated Python imports the complete recovery closure without invoking recovery,
then bytes/permissions are rechecked and fsynced before atomic publication. Reuse
verifies exact content and refuses damaged/extra files; no active selector or live
runtime is changed. Five tests include real signed host staging, real isolated
imports both before publication and after source staging is gone, repeat reuse,
tampering, failed import, unexpected files and parent permissions. No VM or host
appliance mutation occurred. Active bundle selection/launcher and boot integration
remain pending, as does complete combined update/rollback qualification.

Added maintenance-guarded active recovery bundle selection and a minimal stdlib
bootstrap launcher. Selection verifies the content-addressed bundle and refuses
unfinished maintenance before atomically updating active.json. The launcher checks
selector schema, manifest hash, exact bounded module inventory, hashes and private
permissions before any bundle import, then executes isolated Python with bytecode
disabled and a clean environment. It ships in bootstrap/, not the replaceable
runtime map. Four new tests cover verified launch arguments, protected selection,
tampering before execution and unsafe selector/module permissions. The focused
bundle/package suite passes 13 tests. No live selector or boot files were changed;
bootstrap installation and boot dependency ordering remain pending.

Added packaged bootstrap recovery/finish units, a Requires+After writer gate and
a release-specific storage unit. Inspection found the original storage unit launched its
guard from /opt/mindflayer-elderbrain, which can be absent mid-switch. The launcher's
new storage phase now uses the verified bundle guard. Early recovery runs after
the data mount/storage check but before host aliases, local-fs.target and networking;
finish follows normal workers so it can restart them without a dependency cycle.
Four new tests cover stable guard execution, storage/writer directives and a real
systemd-analyze dependency graph check. The graph test substitutes only unavailable
application executables and OS mount/service fixtures; no units are installed or
started. A direct development-host check first reported the expected missing data
mount/appliance executables; the complete modeled graph then passed. Bootstrap
installation and real VM boot qualification remain pending.

Extending the graph test to actual host bind-mount dependencies exposed a cycle:
the original storage unit waited for aliases whose directories recovery may need
to restore. A dependency-reset drop-in did not remove these relationships, as
confirmed by systemd-analyze. The complete release storage unit replaces that
dependency set instead; the expanded graph with all four gated alias mounts now
verifies successfully. The legacy provisioning storage unit remains unchanged
until the bootstrap installer can install the complete recovery prerequisites.

Added the internal release_bootstrap installer for caller-authenticated staged
trees. It checks storage before creating directories, checks fixed target types,
publishes/verifies a stable bundle and holds job/maintenance admission through
selection and installation. It installs the launcher, complete storage and
recovery units, all writer/alias gates and enablement links without starting
services. Replaced managed file bytes/modes are retained in private per-attempt
history; unrelated overrides remain untouched. Durable installing/installed
receipts always keep activationReady false. Seven tests use real signed staging,
bundle imports and temporary host file installation, covering repeat installation,
history, interrupted publication/retry, locked maintenance, unsafe targets/sources,
conflicting enablement and missing storage. Storage identity is mocked; no live
host or VM boot files were modified. Provisioning wiring, previous-runtime
migration, daemon reload and real VM boot/update qualification remain pending.

Wired trusted ISO provisioning into the recovery bootstrap installer after host
settings persistence and before daemon reload/writer enablement. The payload is
staged from the same reviewed inventory used by releases; no downloaded archive
is implicitly trusted. Fixed a discovered admission gap: absent persistent
identity returned None, which bootstrap now explicitly rejects. Added provisioning
and absent-identity tests. Full regression suite: 502 tests, five skipped, passing;
shell syntax and diff whitespace checks pass.

Installed the bootstrap on the identified disposable QEMU VM using
test/qemu/recovery-bootstrap.py. First transfer correctly rejected non-root source
ownership before installation; root-owned extraction succeeded. The real systemd
graph verifies with generators enabled (required for fstab mounts), the stable
storage guard passes, and both recovery phases report no-update-recovery-needed.
Previous managed files remain under recovery history
installation-7dbe4ccefed84da29b4e8e372ed82704; active bundle is
53e0cffe4581e7cc86f29d50d2f195be28b63761e5a1059b45c978b4d740c73c.
This installation retains activationReady false; complete update activation and
interrupted-update boot recovery are not yet qualified.

Rebooted only the disposable VM; boot ID changed from
8d6da1c5-c4ad-4454-8d1d-3caf885b7689 to 0ace5305-4483-4ae6-a57a-caef48324b28.
Storage/early recovery completed at monotonic 3.57/3.85 seconds, management at
8.81 seconds, legacy stack at 43.46 seconds, graphics at 43.61 seconds and finish
recovery at 43.77 seconds. All reported success, no failed units or pending jobs
remained, and CA-verified HTTPS Setup health returned exactly {"ok":true}.
This qualifies normal reboot with the installed gates and no pending update;
it does not qualify offline stack migration, Foundry workload, interrupted-update
rollback or a newly built ISO installation. Physical Lenovo remained off.

Added release_baseline.prepare to stage the legacy installation's offline
rollback Compose. Job/maintenance/settings locks protect inspection; all four
configured images must already exist for Linux amd64 and are pinned by immutable
local image ID. Only image/build/pull fields change, verified by comparing actual
Compose-resolved documents before/after. Expanded settings remain in memory;
private durable output contains original/generated Compose, hashes and image IDs,
with activationReady false. Six tests cover preservation, private publication,
missing cache, resolved-setting drift, maintenance/storage rejection and unsafe
service/pin structures. Full suite: 508 tests, five skipped, passing.

Actual VM preparation first correctly rejected the missing configured Foundry
image without changing live files. Explicitly cached ghcr.io/felddy/foundryvtt:14.367
(registry digest sha256:5004a67fbbef8e3f5f82afb01c8dbe06626c57519cad541a59b1bdce3c2a97ac)
as a separate test preparation operation; no Foundry container was started.
test/qemu/offline-baseline.py then passed against real Docker/Compose, retaining
evidence at /root/elderbrain-offline-baseline-ibx0g_er/0dc4cd35af924053a34d10f594b76812.
Live Compose remained byte-identical. Baseline installation, offline stack-unit
switching and rollback/boot qualification remain; signed release verification
requirements are unchanged. Nothing was pushed or changed on the physical Lenovo.

Added journaled baseline migration for fixed Compose/stack-unit targets, using
the retained-file RestoreTransaction. The internal caller must provide the
bootstrap prerequisite check and trusted offline unit. Source admission rechecks
prepared hashes/rendering, live Compose and current configured cached image IDs,
preventing stale preparation from hiding a changed image override/tag. Stable
stack state, config and existing application health precede commit; containers are
not restarted. Boot recovery now dispatches baseline records before the update
adapter, refuses late unfinished recovery and asserts writer quiescence before
early rollback. Generic backup recovery refuses baseline records. Runtime service
validation accepts immutable local image IDs in addition to registry digests;
signed-release validation was not weakened.

Tests use real file transactions with mocked host/storage hooks: successful
replacement, validation rollback, process loss after replacement, power loss
between the two replacements, commit/completion-record gap, missing bootstrap,
active-writer refusal, and actual prepared-source/cache revalidation. Recovery
routing and local-ID-versus-mutable-tag validation also pass. No VM files were
changed this turn. Concrete bootstrap-proof admission and real baseline switch,
offline reboot and full signed-update rollback qualification remain pending.

Added read-only installed-bootstrap verification against the caller-authenticated
module inventory, selected bundle, complete receipt, retained bytes, all fixed
boot files and enablement links. Added tests rejecting changed writer gates,
missing enablement and damaged retained migration code. Refactored trusted payload
staging into a reusable context without changing provisioning's trust boundary.
Full regression suite: 519 tests, five skipped, passing.

test/qemu/install-offline-baseline.py installed matching recovery in the identified
VM, checked actual loaded Requires/After gates for every writer and host alias,
reprepared cached images and completed migration f5f02ee2e19f460da203ece2d0694c1d.
Prepared evidence remains at
/root/elderbrain-baseline-migration-cjd60lu0/bb522b0371f645a8b8318efe51e214a2.
Live Compose now uses immutable local IDs and the stack unit disables build/pull.
Configuration/current application health passed before commit; old managed files
remain retained. ActivationReady remains false: this is not yet a signed release.

Actual disconnected-link reboot now passes for the migrated VM. Host-side
test/qemu/offline-reboot.py verifies VM identity, schedules its reboot, disconnects
virtio-net-pci.0 and restores it in finally after seven monitored 30-second waits.
Link-down epoch 1789216222.8313148 (12:30:22 UTC), link-restored epoch
1789216440.834378 (12:34:00 UTC). New boot ID is
2988c84a-2a8e-4695-80dd-dcdd92f29496. Storage/early recovery completed at 12:30:40,
management at 12:32:43 and stack/graphics/final recovery at 12:33:06, all before
network restoration. CA-verified HTTPS Setup health subsequently returned
{"ok":true}. No build/pull is present in the installed startup unit, and live
Compose pins cached local IDs. No licensed Foundry instance was started.

The deliberate missing link caused systemd-networkd-wait-online.service to time
out, delaying appliance startup by roughly two minutes; this remains a boot UX
improvement, not an image-download dependency. All Elderbrain units succeeded.
The virtual link is restored and the PC remains on; Lenovo was not contacted.
Interrupted-migration VM recovery, full signed-update activation/rollback and
fresh-ISO prebuilt-image provisioning remain unqualified. Final local suite after
strict proof metadata-permission checks: 519 tests, five skipped, passing.

Actual interrupted-baseline boot recovery is now qualified on the disposable VM.
test/qemu/interrupted-baseline.py installs matching independent recovery, prepares
an offline baseline and injects SystemExit immediately after the real rename of
live compose.yaml into its retained rollback location. The live Compose file is
deliberately absent, the stack unit unchanged and maintenance remains installing.
No archive/file-transaction/storage/service adapters are mocked; only the process
loss injection wraps os.rename. Evidence:
/root/elderbrain-interrupted-baseline-wx4ltz9i/evidence.json; migration
78a9ce529c2c4d9191b63a1ed38f6225; source fixture
/root/elderbrain-interruption-source-4QTwAsw7.

After a graceful VM reboot, early recovery reported rolled-back at 4.096 seconds,
before stack at 21.588 seconds, graphics at 21.761 seconds and finish at 21.927
seconds. The verification phase proved a changed boot ID, original SHA256 hashes
and inode numbers for both managed files, matching rolled-back maintenance ID,
offline Compose validation and live management/CA-verified Setup health. No jobs
or failed units remained. This tests process loss at a real file-switch boundary
followed by reboot, not physical abrupt power loss or full signed update/data
rollback. The existing offline baseline remains installed and functional. The
focused migration/recovery suite passes 15 tests; diff whitespace check passes.
The physical Lenovo was not contacted and the development PC remains on.

Added release_apply.activate wiring the existing signed Activation coordinator,
authenticated runtime reconstruction, fixed targets, UpdateCheckpoints and live
management/Setup health adapters. It refuses execution from the replaceable
runtime, requires verified persistent storage, proves installed recovery and
validates the previous offline runtime inside coordinator admission before any
service interruption. ExitStack retains candidate staging throughout transaction
copying/activation/rollback. Four wiring tests cover lifetime/redaction, absent
storage, failed recovery/previous-runtime preflight and changed candidate metadata.
These tests mock host adapters; existing component suites retain signature and
file-transaction coverage. Full local suite: 523 tests, five skipped, passing.

Built current Setup source as elderbrain-setup-release-test:1.0.1 inside the
disposable VM without changing the running stack or publishing externally.
Docker build and Nuxt production compilation passed. Labels prove version 1.0.1
and host API min/max 1. The local image store reports RepoDigest
elderbrain-setup-release-test@sha256:dc84e0a36a1b954ff6cd66a8880d045f9644ea1ec3bb764cdfbd5ba597e9186b,
so signed cached-image qualification does not require an external test registry.
npm reported one low-severity audit finding during installation; it was not
remediated in this activation-wiring change. Full real signed preparation and
activation/rollback qualification, plus the persistent public update job, remain.

Real signed activation now passes on the disposable VM through
test/qemu/signed-activation.py. Fresh disposable RSA keys sign a complete format-2
release assembled from current reviewed host sources, previously built dependency
inputs and real cached image digests. Preparation verifies signatures, installs
dependencies offline into separate stable prefixes and checks the cached labelled
Setup image; the current independent recovery bundle is installed before activation.
The real release_apply adapter captures its pinned Btrfs checkpoint, deploys fixed
targets and verifies live health. Update e4aafe18eb474e47a4f1aa7fd19a60ca completed
as version 1.0.1. Evidence: /root/elderbrain-signed-activation-2qvck2rh.
Installed VERSION is 1.0.1, stack/management/graphics are active, all three enabled
containers are healthy and CA-verified Setup health returns {"ok":true}. No image
was published externally and the optional licensed Foundry instance was not started.

The same fixture now qualifies real code AND data rollback after startup. A second
signed host release 1.0.2 reuses compatible Setup 1.0.1, captures a checkpoint with
a dedicated hidden fixture file under Foundry data, passes real health once,
writes changed fixture contents and injects a single health failure. All signing,
staging, dependency/image checks, service operations, Btrfs snapshots, file/data
transactions and bind-alias refreshes remain real; only the final health outcome
is deliberately failed. Update c61c7f08a7094215bd57a505a4db9dd0 rolled back with
dataRolledBack true. The fixture verified restored VERSION 1.0.1, exact original
Compose bytes and original fixture contents, then real restored-service health.
Evidence: /root/elderbrain-signed-activation-rc7pi8pr; checkpoint
37be6dfea92c82024a0f43aed083569a. Marker retained as test evidence:
/var/lib/mindflayer-elderbrain/foundry/.elderbrain-rollback-test-ceb12e066e9748b7952d82c828675d2f.
Final direct checks confirmed stack/management/graphics active, no failed units and
CA-verified Setup health {"ok":true}. This is live health-failure rollback, not
interrupted signed-update boot recovery or actual licensed Foundry schema migration.
Public persistent update jobs, production release/ISO integration and remaining
goal features are still pending. PC stays on; no physical Lenovo or external
repository/registry publication was involved.

Interrupted signed-update boot recovery now passes on the actual disposable VM.
The signed activation fixture's --interrupt mode prepared host 1.0.3, passed real
post-start health, fsynced changed contents to its dedicated data fixture and
raised SystemExit instead of initiating immediate rollback. The unfinished journal
remained verifying-update with dataMayHaveChanged true and its checkpoint pinned.
Evidence: /root/elderbrain-signed-activation-3gjyjmxq/interruption.json; operation
fabbe6edb6834f63bf66439dfa23de52; source fixture
/root/elderbrain-signed-boot-source-w5iy5LRJ.

After graceful VM reboot, early recovery restored code/data and reported
files-recovered at monotonic 73.537 seconds, before Docker at 78.309 seconds and
stack at 100.115 seconds. Final recovery completed at 127.979 seconds after real
service health. test/qemu/verify-signed-boot-recovery.py proves changed boot ID,
restored VERSION 1.0.1, original Compose SHA256, original fixture contents,
rolled-back/dataRolledBack state, released checkpoint pin, recovery-before-Docker
ordering, offline configuration validation and management/CA-verified Setup health.
No jobs or failed units remained. The fixture models process loss followed by a
graceful reboot; it is not a physical abrupt-power-loss test or a licensed Foundry
schema-migration test. Focused activation/recovery suite: 21 tests passing; diff
whitespace check passes. PC remains on; no physical Lenovo contact or publication.
Persistent update-job/API/UI integration and the remaining goal items are pending.

Added persistent `update` host jobs with exact version/manifest-digest and explicit
update/downtime confirmation. Only update jobs launch through the independently
verified bootstrap job entry; it verifies the queued kind/identity and inherited
lock-file inode before isolated host_jobs execution in the existing separate
systemd scope. The worker uses fixed OS release/dependency paths and installer-owned
public key/reviewed inventory, checks actual platform compatibility, installs
authenticated recovery and invokes release_apply with its live job owner. The
confirmed digest is checked again at activation. Other jobs remain excluded by
the existing lock-proven admission. Job progress/results are durable and redacted;
failures retain private diagnostics and update maintenance records include jobId.

Tests cover request rejection, stable scope arguments, verified worker launch and
wrong inherited descriptor, durable progress, private failures, fixed trust paths,
digest changes and key permissions, plus existing activation/boot regressions.
No VM or physical appliance changes this turn. Trust/preparation provisioning,
real scoped-worker VM qualification, boot outcome reconciliation and the public
System-page API/UI remain pending; no update-ready claim is made.

Review caught the legacy management runtime's limited module inventory: importing
the full update worker merely to validate a request would fail there. Moved request
validation into a small shared module and explicitly provisioned it plus its
stdlib-only release-metadata dependency. Actual execution still uses retained
recovery code; the management runtime never imports the activation closure during
submission. Shell syntax, request/worker/package tests and whitespace checks pass.

Real persistent update-job qualification now passes on the disposable QEMU VM.
The signed fixture's --job mode prepared host 1.0.4 with compatible Setup 1.0.1,
installed an exclusive disposable public trust pin and reviewed inventory at the
worker's fixed paths, and submitted confirmed version/digest through JobStore.
The submitting process exited; the independent stable worker completed job
19a9ede79f74441e89e7739727c1a042. Evidence:
/root/elderbrain-signed-activation-dakkxr47/job.json; source fixture
/root/elderbrain-job-source-G2hxE9WD.
The separate update-job-status.py verifier confirmed completed state, runtime
VERSION 1.0.4, a changed management service InvocationID, matching maintenance
job/operation IDs, offline Compose validation and actual management/CA-verified
Setup health. This proves the worker survives replacement/restart of management;
it does not yet qualify job reconciliation after boot or the public UI workflow.
No production trust key, repository push, registry publication or physical Lenovo
change was involved. The development PC remains on.

Added the authenticated System update submission API and bounded bridge transport.
Only the exact version/digest and two explicit boolean confirmations are accepted;
no user-controlled key, command or filesystem path is forwarded. Host JobStore
validation remains independent of Setup validation. The production-server
integration test proves anonymous 401, missing-CSRF 403, rejected invalid/extra
fields, accepted HTTP 202 with no-store, and subsequent job-list visibility using
a mock management peer. Actual bridge-handler tests cover payload limits, short
reads, unauthorized peer rejection and exact forwarding to JobStore. Nuxt
typecheck/build, request validator tests, 26 focused Python tests and whitespace
checks pass. This adds API integration, not release discovery or a finished System
page; those and power/backup controls remain pending. No live appliance changes.

Added the Nuxt UI System navigation/page and read-only signed release discovery.
The authenticated POST check accepts no browser-selected source or key. A fixed
installer-owned configuration supplies an HTTPS metadata directory; pinned-key
verification precedes publishing notes, versions and downtime. Missing source,
incompatible release and failed checks are distinct from a ready-to-install
release. No artifacts are downloaded, services changed or automatic update-ready
claims made. The page explicitly labels the current metadata-only stage.
Tests use actual signatures and cover tampering, source constraints, unsafe trust
files, response bounds/redirect rejection, complete/incomplete release compatibility
and host package inclusion. Ten focused Python tests, Nuxt typecheck/build, two
production-server browser/API tests, shell syntax and diff checks pass. Browser
coverage proves auth/CSRF, custom-source rejection and literal release-note text.
Artifact preparation/download and final update/power controls remain pending.

Connected confirmed online preparation to the stable update worker and enabled
the System page's Update now flow. Absent prepared versions trigger pinned-source
metadata revalidation before any artifact fetch, signed size/hash-checked HTTPS
downloads into private temporary storage, then existing offline dependency and
immutable image preparation. Existing prepared versions retain their offline path.
The owned job admission and maintenance locks exclude competing operations during
preparation; final activation retains its own independent gates/checkpoint flow.
The GUI requires both confirmations and known idle host-job status, displays
durable progress and resumes it after reload without automatic submit retries.
Focused tests cover transport corruption/redirect/length failures, stale confirmed
metadata, preparation wiring, owned job admission and offline-path regressions.
Nuxt typecheck/build and three production-server browser/API tests pass. Real
HTTPS download through activation, production ISO trust configuration, recovery
job reconciliation, power/backup controls and other goal requirements remain open.
No physical appliance, production key, registry or external repository was changed.
Full Python regression suite: 542 tests passed with five skipped; whitespace check
also passes. This does not replace the pending real HTTPS end-to-end qualification.

The real HTTPS-download-to-activation qualification now passes on the disposable
QEMU VM. Source: /root/elderbrain-https-source-0R0OUiKV; evidence:
/root/elderbrain-signed-activation-b3qn515x/job.json; job
16993f81a849425a85bb27f34a5c12c7. The fixture reuses the prior disposable signing
key, retains the old reviewed inventory and supplies the current reviewed one.
Version 1.0.5 and its dependency prefix were absent before submission. The worker
fetched manifest/signature and both archives over guest-CA-verified loopback HTTPS,
prepared offline dependencies and cached immutable images, then activated in a
separate live systemd scope after the submitter exited. The verifier confirmed
completed 1.0.5, changed management InvocationID, matching maintenance job/operation
IDs, offline Compose validation and real management/CA-verified Setup health.
No failed units were present during activation. The server journal records HTTP
200 for all four signed release files; images were cached, not registry-downloaded.

Guarded cleanup reverified terminal success/health and exact fixture paths, stopped
the transient HTTPS server and removed only its source configuration and guest TLS
trust certificate. Evidence and signed artifacts remain. Fixture syntax, 25
focused Python tests and whitespace checks pass. No production trust key, external
publication or physical Lenovo contact occurred; the development PC remains on.
Remaining goal work includes ISO trust provisioning, boot job reconciliation,
power/backup controls, remaining restore/storage qualification and branded boot.

Implemented final-phase persistent update-job reconciliation. New activation
journals retain the confirmed signed manifest digest. Recovery's final phase
rechecks the current maintenance operation under lock, then reconciles only an
unlocked update job matching job ID, version and exact digest. Terminal rollback
is represented as rolled-back, not update success; completed recovery can repair
a job interrupted before its final save. Early files-only recovery, live workers,
unrelated/mismatched records and already terminal results are not changed.
Legacy journals without digest correlation are deliberately left untouched.
Tests cover terminal outcomes/idempotence, stale errors, redaction, live lock
protection, phase ordering, maintenance replacement and digest persistence.
Real reboot qualification of this new correlation path remains pending; this
turn made no VM or physical-appliance changes.

Added explicit paired ISO UPDATE_SOURCE_CONFIG/UPDATE_PUBLIC_KEY inputs with
bounded source validation and OpenSSL public-key parsing/private-key rejection.
The normal private-payload exclusion is preserved; only explicitly selected public
update inputs are copied into the build. Provisioning requires verified persistent
storage, installs the reviewed payload inventory/source/key and creates private
release/dependency directories. Identical re-provisioning is allowed; changed
existing trust is refused rather than silently rotated. Release discovery
temporarily accepted Git/dirty version labels from source-built ISOs; the later
clean-baseline policy below removes that compatibility. Eleven focused tests, shell
syntax and whitespace checks pass. No ISO rebuild or live appliance mutation
occurred; complete initial offline-baseline/release integration and fresh-ISO
update testing remain pending.

Replaced the CLI's unguarded reboot/shutdown calls with a host power coordinator.
It requires verified persistent storage and holds job-admission, maintenance and
display/network settings locks while checking for active workers or unfinished
operations. Before requesting systemd power transition it durably records the
current boot ID, preventing subsequent host-job and interactive settings admission
in the acceptance-to-shutdown interval. Failed requests clear the pending state;
records from an earlier boot do not block work after restart. Accepted requests
are not claimed as physically completed; no power action was executed in tests.
Thirty-six focused tests verify live-worker exclusion, maintenance/storage guards,
pending settings, subsequent admission exclusion, failure and boot scoping. Shell
syntax and whitespace checks pass. This is the CLI safety foundation, not the
persistent power-job/UI or shutdown checkpoint/remote-backup workflow, which remain
pending. No VM, Lenovo or development-PC power operation was sent.

Added confirmed persistent `power` host jobs. Requests contain exactly action
(reboot or shutdown) and confirmPower true, and launch in the existing independent
systemd scope with the inherited live-worker lock. Execution uses the fixed
appliance state directory. The power coordinator admits only its own matching
confirmed live power job; it still rejects all other live jobs and preserves the
maintenance/settings gates. The durable power request now includes jobId.
The worker's completed result means the systemd request was accepted, not that
physical power transition was observed. Tests mock power commands and verify
confirmation rejection, scope launch, matching-owner exemption and redacted
request-acceptance results. Thirty-one focused tests and diff checks pass.
Authenticated UI/API, boot outcome reporting and shutdown backups remain pending.
No machine was rebooted or shut down, and no live appliance was changed.

Wired the persistent power jobs into the authenticated System page and Setup API.
Reboot and shutdown now require a deliberate action choice followed by a separate
confirmation checkbox; the API requires the authenticated admin session, normal
same-origin/CSRF protections and an exact confirmed request. The page submits with
automatic retries disabled, reports acceptance without claiming that power state
was physically observed, and polls both durable jobs and the current-boot pending
marker. A pending marker or any queued/running host job disables update and power
submission. The management bridge retains bounded payload reads and forwards only
the existing allowlisted power job. Browser/API tests cover anonymous and missing-
CSRF rejection, malformed requests, cancellation before confirmation, accepted
submission and pending state after reload. Host-side tests continue to mock the
systemd power command; 33 focused Python tests, Nuxt typecheck/build, all 39 Setup
unit tests and all 40 production-server browser/API tests pass. At that milestone,
the UI explicitly identified bounded pre-shutdown checkpoint/backup handling as
not implemented; the later backup-protection milestone below completes it. Boot
outcome reporting remained pending. No machine was rebooted or shut down, and no
live appliance was changed.

Split online recovery preparation from recovery authority publication. An
authenticated candidate's recovery modules are now imported, verified and retained
in the content-addressed store while `active.json` continues to name the known-good
bundle that admitted the update. Activation rechecks that exact active identity
under its maintenance lock. Only a `completed` activation result reaches the
separate selector commit; health failure, rollback, interruption or any other
result leaves the prior authority selected. Selector publication itself now occurs
only after the guarded selection block exits successfully. Online releases must
currently carry byte-identical fixed launcher, unit and writer-gate inputs; changing
that bootstrap generation is rejected until a transactional publication mechanism
is implemented. The clean-install provisioning path still establishes the initial
bundle and fixed boot files. Unit tests cover retained-but-unselected candidates,
post-commit selection, fixed-bootstrap rejection, active-identity drift, failed
selection blocks and failed/noncommitted activation. All 155 release tests pass;
the systemd unit-graph verifier required its normal host socket permissions and
passed separately outside the sandbox. No VM or physical appliance was changed.
Signed recovery API compatibility and post-activation/pre-selector interruption
reconciliation remain pending before this priority is complete.

Added an explicit signed recovery transaction/API contract. Release manifests now
carry bounded `recoveryApi`; content-addressed recovery manifests use format 2 and
bind the same API to the verified module bytes. Candidate preparation requires the
signed API to match both the active authority and the locally supported
implementation. Activation writes that API into its durable journal before
stopping services, and both early and final boot recovery reject missing or
different APIs. Release discovery reports the API and marks a signed release
incompatible when it differs from the installed active bundle. Old Git/dirty host
version labels are no longer accepted as an update baseline; new installations
must establish a semantic version, with no migration path for pre-updater installs.
All 157 release tests pass, including API mismatch/tampering and systemd unit-graph
coverage. The monotonic release sequence and post-commit selector reconciliation
remain separate pending work. No VM or physical appliance was changed.

Implemented signed monotonic release ordering and the remaining selector recovery
window. Manifests now require a positive 63-bit `releaseSequence`, independent of
component versions. Discovery shows the installed/candidate sequences and marks
replayed or lower releases incompatible. The persistent worker rejects them again,
and activation repeats admission inside its maintenance lock. After health and file
transaction commit, but before maintenance becomes terminal, a private atomic
control-plane record advances the highest accepted sequence together with release
version and exact manifest digest. Recovery can repeat only that exact identity;
conflicting equal or lower values fail closed, and rolled-back activation never
advances it. The file sits outside every update checkpoint/selective restore target.
Update journals also retain the candidate recovery bundle, allowing final boot
recovery to finish its atomic selection when the original worker disappears after
activation commit. Rolled-back records never select the candidate. The reviewed
host inventory includes the policy implementation. All 163 release tests, Nuxt
typecheck/build and five production-server System/API browser tests pass. Initial
signed-sequence seeding in a clean ISO baseline and destructive reboot/interruption
qualification remain pending. No VM or physical appliance was changed.

Replaced the production ISO's exclusion-blacklist worktree copy with a clean,
tracked-commit input path. `iso/tracked-payload.py` rejects staged or modified
tracked files, exports the exact Git commit, rejects archive links/special entries,
and excludes untracked files by construction. Builds now require an explicit
semantic `APPLIANCE_VERSION`; generated `VERSION` no longer contains a Git hash.
`build-metadata.json` records version, source commit/tree, input mode and a canonical
SHA-256 source identity, while ISO filenames include semantic version and commit.
The previous rsync/exclusion path exists only behind
`DEV_ALLOW_DIRTY_WORKTREE=1`, records `development-worktree`, and adds `-dirty` to
the filename. SSH, SMTP and update-trust inputs remain deliberate post-archive
additions. Six focused payload/SMTP tests, three update-trust tests, shell syntax,
static checks and whitespace checks pass. No ISO was built or copied, and no VM,
Ventoy device or physical appliance was changed. A signed immutable first-runtime
baseline still needs integration before production ISO qualification.

Replaced independent recovery-bootstrap file publication with content-addressed,
atomic generations. A generation binds the candidate recovery bundle/API together
with the fixed launcher, storage/recovery units and all writer-gate drop-ins.
Clean installation establishes stable root-owned symlinks for those boot paths;
every path resolves through one `bootstrap-active` selector. Online preparation
fully writes, fsyncs and verifies a candidate generation without selecting it.
Only a completed activation switches the single selector, after which the private
installation receipt is refreshed idempotently. Boot recovery can repeat that
switch using the generation identity retained in the update journal. Changed fixed
bootstrap files are now supported instead of being rejected as byte-different.
Unit tests inject interruption before and after both the content-addressed generation
rename and the atomic selector replacement, proving that the old complete generation
or new complete generation remains selected and reruns converge. The real minimal
launcher is also tested against the generated selector. The complete 168-test
release suite, all 39 Setup tests, all 583 host tests and static checks pass; tests
requiring host systemd sockets were run outside the restricted sandbox.
No VM or physical appliance was changed, so destructive boot/power-loss qualification
of this publication mechanism remains pending.

Removed Traefik's Docker-daemon authority. Compose no longer enables the Docker
provider, carries routing labels or mounts `/var/run/docker.sock`. The existing
committed-domain projection now emits the complete file-provider configuration:
HTTP/HTTPS routers, redirect/strip middleware and fixed Compose-network URLs for
Setup, Mindflayer and Foundry. `prepare-admin` creates the projection before stack
startup, while the display watchdog continues to reconcile confirmed domain
changes and restore recovery. Static checks prevent the socket/provider/labels
from returning. Unit tests, Compose validation and the real Traefik 3.7.5 parser
all accepted the generated configuration; its API showed all five file routers,
three file services and two middleware definitions enabled. The parser test used
a disposable local container, which was stopped and auto-removed. No VM or physical
appliance was changed; signed-update and disconnected-boot qualification remain.

Separated administration CA signing authority from Traefik serving state. The CA
key and authoritative certificate now live in the private persistent
`host/admin-ca` directory. Traefik receives individual read-only bind mounts only
for its two dynamic documents and leaf certificate/key; neither the CA key nor its
parent directory is mounted. `prepare-admin` refuses legacy exposed-key layouts,
refuses silent trust rotation when a published CA has lost its key, publishes only
the public CA copy, and validates CA/key/leaf consistency before stack startup.
Host certificate refresh, temporary network-confirmation TLS and recovery health
now use the root-only authority. Manual/Borg source archives include `admin-ca`,
and restore validates the authority and public copy before stopping writers so
client trust survives a valid restore. Focused TLS, backup, restore and route tests,
Compose validation, all 39 Setup tests, all 584 host tests and static checks pass.
No VM or physical appliance was changed; live renewal, reinstall and restore
qualification remain pending.

Decoupled the privileged management bridge from generic UID 1000. Clean
installation now reserves `elderbrain-management` at fixed GID 31338 and fails
closed if either the name or numeric identity conflicts. The Setup image retains
its unprivileged Node UID for persistent-file compatibility but uses the dedicated
group as its primary group. The root bridge makes only its runtime directory and
0660 allowlisted socket group-accessible, resolves the installed group rather than
trusting a caller-controlled setting, and authorizes non-root peers by that group.
Regression tests reject UID 1000 with an ordinary group and accept a different
unprivileged UID carrying the capability. A production Setup container build
confirmed `uid=1000(node) gid=31338(elderbrain-management)`. Focused host tests,
installer syntax and whitespace checks pass. Fresh-install and signed-image VM
qualification remain pending; no VM or physical appliance was changed.

Strengthened the ordinary CI path for the target runtime. It now selects the
Ubuntu 26.04 hosted image and Python 3.14 explicitly, installs `ripgrep`, and pins
checkout, Python and Node setup actions to full reviewed release commit IDs while
retaining read-only repository permissions. Static checks preflight required
commands before any work. The host tests are now an explicit package discovered
from the repository root, and sibling fixtures use relative imports instead of
the environment-dependent `test.test_*` namespace; the corrected discovery runs
588 host tests rather than silently depending on import order. The local
CI-equivalent run passed all 588 host tests (5 explicit platform skips), 39 Setup
tests, typechecking, static checks, Compose validation, the production Nuxt build
and all 40 browser tests on Python 3.14. A hosted run remains unverified because
the Elderbrain branch is intentionally local and has not been pushed.

Implemented the backup trigger and power/update protection path. Borg settings
now independently select daily, post-boot, pre-update and pre-power behavior, an
explicit continue/block policy for pre-update failure, and a bounded 30–1800
second whole-attempt timeout. Every accepted reboot/shutdown creates a
read-only `before-shutdown` checkpoint before requesting power. Configured remote
protection pins that checkpoint, archives its exact immutable data generation,
and retains a private pending record plus local archive if the destination is
offline. Each later offline shutdown adds another pinned generation to the
durable queue. A boot-enabled systemd service retries the oldest exact generation;
lost records are reconstructed from their complete purpose-bound pins. Successful
upload is durably recorded before the pin is released, with an intermediate state
making that release restart-safe. Update activation attempts its configured remote
backup only after the mandatory rollback checkpoint and before transaction
preparation; the result is exposed without private paths, and a required failure
rolls back before candidate installation. UI settings/status and regression tests
cover policy validation, timeout propagation, retry, interrupted local archive,
lost-record reconstruction, pin retention/release, power interlocks, update
ordering and failure behavior. The full local suites pass 608 host tests (5
platform skips), 39 Setup tests, typechecking, static checks, Compose validation,
the production Nuxt build and all 40 browser scenarios. Installed VM
power/interruption qualification remains pending; no VM or physical appliance was
changed for this milestone.

Integrated the clean-install immutable release baseline. Production ISO builds now
require an explicit positive 63-bit `APPLIANCE_RELEASE_SEQUENCE`; generated source
metadata and artifact names bind that sequence alongside semantic version and Git
identity. Provisioning retains the authenticated metadata and a trusted copy of the
initial stack unit. After the initial online stack has fetched/built its images, the
new baseline boot service resolves their exact local SHA-256 IDs, transactionally
switches Compose to offline `pull_policy: never` operation through the existing
recoverable migration, and records the installed sequence only after that switch
commits. Management, graphics and pending-backup retry require this finalizer, so a
partial baseline fails closed. Its OS-local completion receipt makes later boots
idempotent and accepts a policy advanced by a successful online update. An explicit
preserve-data reinstall replaces that receipt and is therefore authorized to reset
retained anti-replay state to the selected ISO baseline; normal online updates retain
strict greater-than ordering. Focused baseline, recovery-bundle, release-policy,
payload, target and backup tests pass, and the installed systemd graph verifies
outside the restricted sandbox. Full local suites and clean-ISO/VM qualification
remain pending; no VM or physical appliance was changed for this milestone.

The first clean BIOS qualification of commit `7aff5f7` reached the installed OS
with the mutable bootstrap stack healthy, but the new baseline service failed
closed before policy publication, management or graphics. Its verified recovery
bundle contained `appliance_release.py`; the baseline script itself had not added
that bundle directory to isolated Python's import path. The finalizer now applies
the same explicit isolated-path setup as the main recovery entry point, and bundle
publication imports both entry points before selection. Thirty-five focused
baseline/bootstrap/bundle tests, including direct `runpy` execution under `-I`,
pass. The failed VM and ISO are diagnostic evidence only; a rebuilt ISO must repeat
clean installation before the baseline is qualified.

The corrected `02e9322` BIOS ISO then passed isolated recovery-module loading and
reached baseline image resolution, revealing that clean startup had not cached the
profile-gated Foundry container image. Baseline preparation correctly refused to
leave that future service mutable or to pull during its offline transaction, again
before policy publication or dependent service startup. Initial bootstrap startup
now includes the Foundry profile only for `pull --ignore-buildable`; the normal `up`
command remains profile-free, so Foundry is cached but not started before owner
configuration. Static coverage requires this exact distinction. Another clean ISO
build and installation are required to qualify the correction.

After manually caching that image, the finalizer reached migration and exposed an
omitted mandatory subprocess runner at its production call site. Preparation and
migration now receive the same explicit real or injected runner, with a regression
asserting the real default. Diagnostic completion on that retained VM then produced
immutable local SHA-256
references for all four services, committed sequence 1 and started management and
graphics. While rerunning the standard guest harness, its `esptool version` probe
was found able to consume the remaining SSH-streamed shell program from stdin,
creating a false early success before private keypad storage and management-bridge
checks. That probe and the Setup-group `compose exec` probe now receive `/dev/null`.
The corrected diagnostic harness reached its final explicit bridge-verification
marker; a clean unmodified-ISO run is still required.

Clean BIOS installation of commit `3e36652` passed the complete unmodified harness,
including its final bridge marker, persistent storage, HTTPS/authentication and
graphics. The resulting Compose contains all four services as local `sha256:` image
IDs with no build directives and `pull_policy: never`; release policy and the
OS-local receipt agree on sequence 1. A normal reboot changed boot ID and returned
baseline, management and graphics active. An additional abrupt reset with the QEMU
link disabled then exposed indefinite boot ordering on `network-online.target`.
The installed offline stack and local graphics no longer request or wait for that
target; initial bootstrap pulling and network backup services retain their network
ordering. Because Docker's vendor unit also requests `network-online.target`, a
reviewed drop-in replaces Netplan's generated unbounded command with the same
`--any --dns -o routable` readiness contract capped at 30 seconds. The drop-in is
installed on clean systems and is part of the signed fixed deployment map. Exit
status 1 is accepted as the bounded disconnected result so the local UI does not
leave an otherwise healthy appliance with a failed unit; the timeout remains in
the journal and network-dependent work retains explicit retries. A durability-synced
diagnostic installation returned the Chromium login page 45 seconds after an abrupt
QEMU reset with its link still disabled. After link restoration, baseline, stack,
management and graphics were all active; the wait journal recorded timeout at
30.1 seconds, treated it as a successful bounded result, and `systemctl --failed`
was empty.

A production tracked-commit ISO was then rebuilt from `4c53d74` with semantic
version 1.0.0, release sequence 1 and source identity
`3917ffe9d2531b351d6d726f5ed92efc490be07fc42a17e1ea2ecef717fd54cc`.
Its SHA-256 is `5eaa150ef722e8844a8218760731876977e31975993813480123a5d97f46a0b7`,
and inspection found both BIOS and EFI El Torito entries. A fresh BIOS install on
a new 96 GiB QCOW2 reached immutable baseline sequence 1 and passed the complete
guest checks for storage separation and identity, fixed aliases, coordinated
containers, v3 keypad tooling, the management bridge, administration CA/HTTPS,
authentication/CSRF/logout, bootstrap policy, graphical window and host metrics.
Password SSH was rejected. The production-installed wait-online drop-in exactly
matched the source digest. An abrupt reset with the virtual link disabled returned
the full Chromium login page from cached images before link restoration. The boot
ID changed, the wait timed out at 35.97 seconds with a successful unit result, all
baseline/stack/management/graphics/wait units were active, and no failed unit
remained.

That run also showed the old QEMU harness started its 30-minute readiness timer
before an operator completed the deliberately interactive destructive prompts.
The VM and installation remained healthy, but delayed human input exhausted the
observer and required running the same guest checks manually. The harness now
starts that timer only after explicit operator acknowledgement and reports a clear
terminal timeout instead of falling through to an ambiguous SSH error.

The same production `4c53d74` ISO also completed a fresh install under OVMF using
the explicit UEFI mode added to the host harness in `463cce0`. A diagnostic QEMU
monitor command unintentionally stopped the VM during first-boot provisioning;
the retained installation then resumed from the same disk and OVMF variable store
without repair. It completed provisioning and passed the full guest, persistent
storage, HTTPS/authentication and administration-UI checks. Runtime evidence
confirmed `/sys/firmware/efi`, the GPT ESP at `/dev/vda2` mounted as VFAT on
`/boot/efi`, separate ext4 OS and Btrfs persistent-data partitions, all baseline,
stack, management, graphics and bounded wait-online units active, and no failed
units. Password-only SSH was rejected. This qualifies fresh BIOS and UEFI install
and additionally demonstrates recovery from an abrupt interruption during UEFI
first boot; populated preserve reinstall and signed-update interruption matrices
remain separate acceptance gates.

The populated BIOS disk from that production qualification was then seeded with
the private `preserve-baseline.sh` fixture and reinstalled from the same `4c53d74`
ISO using the guarded preserve flow. The selector accepted only the exact disk
serial, retained data UUID `f5ed1b49-83f3-495c-8870-91581fff0489` and explicit
`REINSTALL OS elderbrain-vm-test` confirmation. The sealed host-side manifest
checksum passed after reinstall; its verifier proved a new OS filesystem UUID
while preserving the data identity, fixture bytes and metadata, SSH host identity,
and runtime settings. The full guest, storage, HTTPS/authentication and admin-UI
suites passed afterward. Release policy was re-established at version 1.0.0,
sequence 1; storage, baseline, stack, management and graphics were active with no
failed units, and password-only SSH remained rejected. This qualifies the current
production baseline's populated BIOS preserve reinstall. Populated UEFI preserve,
missing-data boot refusal and interrupted reinstall recovery remain outstanding
destructive-storage gates.

The retained populated UEFI disk was independently seeded and reinstalled from
the same production ISO. Its first boot attempt used the prior OVMF variable store
and returned to the installed OS because the persistent disk entry outranked the
one-time virtual CD preference; no installer prompt or disk mutation occurred.
Repeating with an isolated fresh OVMF variable store, equivalent to explicitly
choosing removable installation media in firmware, reached the guarded selector
and accepted only serial `elderbrain-vm-test`, retained data UUID
`0a052009-d8da-4aaf-9696-bf581557371c` and the exact preserve confirmation. The
sealed baseline then passed: OS UUID changed, while data/fixture bytes and metadata,
SSH identity and runtime settings remained exact. All four installed-appliance
suites passed. The reinstalled guest reported UEFI firmware and `/dev/vda2` as the
VFAT ESP mounted at `/boot/efi`; sequence 1 policy and every lifecycle service were
active, no failed unit remained, and password-only SSH was rejected. Current
production fresh and populated preserve installation are therefore qualified on
both BIOS and UEFI paths. Missing-data boot refusal and interrupted preserve
reinstall recovery remain outstanding destructive-storage gates.

Missing-data boot refusal was qualified on a copy-on-write overlay of the
production BIOS disk, leaving the qualified backing image inaccessible to guest
writes. While the Btrfs data volume was mounted, the overlay's on-disk GPT entry 4
was explicitly deleted without notifying the running kernel, synced, and powered
off. A normal boot then waited for the exact saved data UUID for the bounded
90-second device timeout and entered visible `emergency.target`; it did not fall
back to an OS directory or show the appliance browser. From the emergency shell,
Docker, stack, management and graphics were all inactive, `/dev/vda4` was absent,
the persistent path was not a mountpoint, and its OS-side directory was empty.
A second clean overlay of the untouched backing image still exposed partition 4
with UUID `f5ed1b49-83f3-495c-8870-91581fff0489`, matched the saved ED25519 host
key and passed the sealed preservation verifier; all lifecycle services returned
active. This qualifies fail-closed missing-partition boot without modifying the
retained production disk. The emergency shell's `systemctl poweroff` and a later
ACPI power event did not terminate within their observation windows, so the
disposable broken-storage VM was hard-stopped; bounded recovery shutdown and an
appliance-specific recovery message remain open usability work.

Wrong-storage-identity boot refusal was qualified with another clean overlay of
the untouched production disk. Before mutation, the mounted volume marker exactly
matched `/etc/elderbrain/storage.json`; only the overlay marker's disk serial was
changed, retaining its root ownership and mode 0600, then synced before reboot.
The volume still mounted from `/dev/vda4` as Btrfs, but stable recovery's storage
guard reported that its marker did not match the installed identity. Boot entered
visible emergency mode before update recovery, and Docker, stack, management and
graphics were all inactive. This isolates and qualifies the identity-mismatch
guard independently from missing-device handling. Emergency-shell poweroff again
failed to terminate within 30 seconds, confirming the bounded recovery-shutdown
defect rather than a one-off missing-device effect; only the disposable overlay
was hard-stopped.

Interrupted populated preserve reinstall recovery was qualified on a third
copy-on-write overlay of the same sealed BIOS baseline. Power was deliberately
cut after partitioning had completed, the OS filesystem had been reformatted and
Curtin had started extracting the replacement image. Rebooting that exact
interrupted overlay from the same production ISO still discovered only the
expected appliance disk and retained data UUID
`f5ed1b49-83f3-495c-8870-91581fff0489`; the guarded preserve selection and exact
confirmation were accepted again, and the reinstall completed without manual
repair. The normal 30-minute observer expired while the guest was still making
active disk progress, so the authoritative VM was left running and became ready
at approximately 36 minutes rather than being restarted. The sealed verifier
then proved a new OS UUID while preserving the persistent volume identity,
fixture bytes and metadata, SSH host identity and runtime settings. The complete
guest, storage, HTTPS/authentication and administration-UI suites passed. Storage,
baseline, stack, management, graphics and bounded wait-online services were all
active with no failed unit, password-only SSH was rejected, and the recovered VM
powered off cleanly. This qualifies recovery by safely rerunning a preserve
reinstall interrupted after destructive OS replacement had begun.

The corrected production-input BIOS ISO built from `90a961c` then qualified the
complete online update path on a fresh 96 GiB disposable disk. The ISO carried
semantic version 1.0.0, sequence 1, the deliberately supplied SSH key and a
disposable independently provisioned release key/source. Its unmodified install
passed the runtime, persistent-storage, HTTPS/authentication and physical admin-UI
suites with password SSH rejected. A signed 1.0.2/sequence-2 release was served
from the configured source over CA-verified HTTPS. A ready test administrator
used the real public System API to discover it, bind both confirmations to exact
manifest digest
`3c5876a2b9e356859b10c93330fb84a839ffb5cdfbbb8c71c1aa1d8d9d998974`, and
receive persistent job `2d0ce5f36f0d4b6bb95ca76c3ebbcdfc` with HTTP 202. The
submitting client exited immediately. The detached job downloaded and verified
the bounded artifacts, prepared runtime dependencies/images, created its required
pre-update checkpoint and backup result, activated, passed health, committed the
recovery candidate and reached a durable completed result. A fresh authenticated
client observed that terminal job before and after reboot. After reboot the host
reported version 1.0.2 and protected highest sequence 2 bound to that digest; all
lifecycle services were active, no unit had failed, and the runtime, storage,
ready-admin HTTPS/CSRF/logout and physical UI suites passed. Re-serving the same
signed sequence produced `compatible: false` through the authenticated System API
and created no staging data, qualifying live replay rejection after persistence.

Two qualification-only assumptions were corrected during this run. The signed
fixture now validates and reuses an already provisioned matching source instead
of attempting to overwrite it. Installed runtime checks compare immutable Docker
image IDs because the preserved install environment's tag-plus-digest spelling
and an activated Compose file's canonical digest-only spelling identify the same
image. First-boot HTTPS/UI scripts retain their original bootstrap assertions and
can additionally validate the intentionally established ready-administrator state
without exposing its credential. An initial disposable release was rejected before
activation because its locally built Setup image intentionally lacked the declared
OCI version label; rebuilding that test image with matching signed metadata was
required before the successful job, demonstrating that image metadata validation
fails closed.

Live power-control qualification on that same installed appliance found and fixed
one boot-boundary reporting defect. The protected HTTPS System API accepted a
confirmed reboot and created its mandatory `before-shutdown` checkpoint, but the
machine restarted before the worker could perform its final job-record write. The
generic orphan handling would have called that successfully requested reboot
`interrupted`. Recovery-owned `host_jobs.py` now reconciles an unlocked power job
to the deliberately limited `completed`/`power-requested` result only when the
root-private power record exactly names the job, action and safe backup fields,
has state `requested`, and names a different valid boot ID. Same-boot, mismatched,
protecting or extra-field records still become interrupted and cannot assert
success.

The fix was installed through a second real signed System update: version 1.0.3,
sequence 3, manifest
`791356727ec82364a8b160a30988342554fde4dd3402814945c402fb663dbe6b`.
Because this changed a recovery-owned module, successful activation moved the
transactional bootstrap selector from generation `ba5d7a52...` to `a8840ce2...`
and, only in the final committing-recovery stage, moved the active recovery bundle
from `8032f3c0...` to `30d0f203...`. The isolated recovery entry point and active
bundle verifier passed afterward with every lifecycle unit active and no failed
unit. This supplies live evidence that a candidate recovery generation can differ
and is selected only after the release commits.

A new API reboot then returned under a different boot ID. A fresh authenticated
client caused job `a802650ae73349c58e3debfd19a3e1a4` to reconcile as completed
with checkpoint `08999aa4d2b7e8c646e5f4cf221a4472`, whose live Btrfs metadata
reported reason `before-shutdown`. A subsequent authenticated shutdown job
`f2826e7e6598447e93b8b74e21cb9305` powered QEMU off cleanly in approximately
21 seconds. Restarting that exact disk produced another new boot ID; the shutdown
job reconciled identically and checkpoint `a436db5d9f458bdf478d2e6ca1f7e2e6`
was present with reason `before-shutdown`. Version 1.0.3, sequence 3 and zero
failed units persisted. These tests qualify the installed authenticated reboot
and shutdown paths, bounded local pre-power protection, physical VM power effects
and truthful next-boot job convergence. They do not claim a configured remote
repository was exercised; remote pending/retry behavior remains unit- and earlier
live-NFS-qualified separately.
