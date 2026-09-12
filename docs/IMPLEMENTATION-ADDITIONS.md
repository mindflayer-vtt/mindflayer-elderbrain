# Administration additions

Scope: implement all six additions requested in the attachment dated 2026-09-10.
USB provisioning initially uses devices attached to Elderbrain.

- [ ] Single administrator, unique local bootstrap password, forced password change,
  verified recovery email/SMTP, secure sessions, CSRF/rate limits, HTTPS, offline recovery.
- [ ] Persistent keypad inventory with desired/applied settings, last seen and unknown
  state on loss of server connectivity; central Wi-Fi and per-device configuration.
- [ ] Persistent host jobs and one-click trusted rBoot/application installation,
  preserved provisioning backup, explicit adoption, serial provisioning, online verification.
- [ ] Complete versioned tar.zst backup, optional encryption, restore preview,
  rollback, consistent service state, ownership restoration and health verification.
- [ ] Borgmatic NFS/SSH configuration, scheduling/retention, encryption, connection
  test, history, archive selection, shared restore engine and separate recovery kit.
- [ ] Authenticated Foundry log tail, pause/resume, search, timestamps and download.

Completion requires API authorization tests, hardware-operation tests with mocked
transports plus clearly recorded physical limitations, backup/restore round trips,
job interruption recovery, browser coverage and appliance integration verification.
No missing feature is considered complete merely because its UI exists.

## Verified progress (2026-09-10)

### Authorized cross-repository work (2026-09-11)

- Rebooted the same disposable VM after the tty1 fix and verified the new boot,
  executed Sway/Chrome, rendered sign-in page, healthy exact-pinned server,
  serial tooling and scoped host bridge. Rebuilt test ISO:
  `/tmp/elderbrain-fixed-iso.MgWGzC/mindflayer-elderbrain-e57c24f58122.iso`, SHA-256
  `872f3b80a757d0cbac3314c2b724fe3b421da056004c5ae21e30887c4bcb80df`.
  Extracted its graphics unit and appliance configuration and compared them
  byte-for-byte with the fixed local sources. This is test media containing a
  disposable SSH public key, not a production deployment image. Physical USB
  flashing/boot-button behavior and a licensed Foundry-world restore remain
  unverified. Hardware targets and a user-selected deployment SSH public key
  are required before physical installation. VM and host remain on; Elderbrain
  code remains local/unpushed.
- Fresh installed VM now passes HTTPS/auth/CSRF/logout, exact server-image,
  serial-tool and scoped bridge checks. Real backup covers all eleven roots and
  a private installation-journal canary; live restore reverts the canary, retains
  credential bytes/mode 0600, captures rollback and restores service health.
  Real loopback NFS/Borg backup/retrieval, recovery kit and wrong-export rejection
  pass. Fixed guest-test stdin consumption by container exec, ensuring later
  assertions actually run. Visual inspection then exposed a kiosk startup hang:
  systemd-executor waited for tty1 while getty owned it, despite an active unit.
  Added a getty@tty1 conflict/order dependency. Applied only to the disposable VM;
  Sway/Chrome now run and the sign-in page renders. Strengthened tests require
  an executed Sway binary plus Chrome, and pass. Cold-reboot verification and a
  rebuilt ISO containing this service fix remain pending. Existing test ISO is
  superseded, not deployment media. Elderbrain remains local and unpushed.
- User approved keypad signing; CI run 34585930042 completed successfully and
  firmware 1.2.0 is published. Elderbrain's production release lookup/downloader
  retrieved the actual serial bundle and verified its signature against the
  pinned public key, protocol 3, hardware ID, preserved provisioning sectors and
  allowed image layout (rBoot 2,688 bytes; application 439,360 bytes). No hardware
  was accessed. Added `ISO_OUT_DIR` to preserve prior test media and built fresh
  test media under `/tmp/elderbrain-iso-check.slkDjT/`. A fresh QEMU installation
  is running in `/tmp/elderbrain-current-vm/run.5cSbHK/`; console inspection shows
  normal Ubuntu installation progress. The harness now checks installed serial
  tooling, root-private installation storage and live server v3 capabilities.
  VM checks are not yet complete. Test media includes the disposable QEMU public
  key and is not deployment media. Elderbrain remains local and unpushed.
- Verified published server 0.4.1 at immutable multi-platform digest
  `sha256:251cc8f0735ddc7d4be788f20311578d0bda480449f63f9de2058bef5a845e64`.
  Its isolated amd64 container passes the actual capability, preparation,
  idempotent registration and online-verification CLI sequence against a
  simulated HMAC-authenticated v3 device. No host mounts, exposed ports or
  physical hardware were used; test containers and anonymous data volumes were
  removed. Updated Elderbrain's local server pin and build guidance. Full
  `make lint test compose-check` passes: 28 setup tests, 105 Python tests with
  five optional skips, typechecking/static/Compose checks. The separate published
  image integration passes with no skip. Elderbrain remains uncommitted/unpushed.
  Fresh appliance VM validation on this pin remains pending; keypad signing
  still requires user approval of CI run 34585930042's firmware-release stage.
- With explicit publishing permission, pushed server installation support
  (`fcb9b77`) plus Dependabot (`85e9264`) and keypad serial bundles/protocol v3
  (`df7d9d6`) plus Dependabot (`93b6b49`). Elderbrain remains entirely local;
  VTT module changes were unnecessary. Server 0.4.0 published successfully.
  A new opt-in test of the actual immutable published image found that its
  shipped verification CLI omitted `/ws`, although helper-level tests passed.
  Fixed it, added real CLI integration coverage and pushed `5ab7abc`; all 71
  server tests pass and server 0.4.1 is releasing through the existing workflow.
  Do not adopt 0.4.0 for one-click installation. Keypad CI passed but signing
  remains waiting for the user's protected `firmware-release` approval.
- Clean-source audit exported only tracked and non-ignored candidate source
  (137 files) into `/tmp/elderbrain-source-audit.L0rC63`, without workspace
  dependencies or build output. Its Python suite passes (104 tests, four optional
  skips); fresh locked `npm ci`, all 28 setup tests and production build pass.
  npm audit reports one low-severity Windows development-server advisory in
  fontless's nested esbuild 0.27.7, [GHSA-g7r4-m6w7-qqqr](https://github.com/advisories/GHSA-g7r4-m6w7-qqqr).
  A compatible fontless lockfile update tested only in the disposable snapshot
  did not resolve it; no dependency override or workspace lockfile change was
  applied. Release/push approval remains outstanding, and no published artifact
  or image pin has been changed.
- Deployment audit: fixed the inherited `lib/` Git ignore rule so privileged
  `appliance/lib/` source is included in normal source staging; Python caches
  remain ignored. Static checks now reject ignored host source and pass. Added
  missing server `led-state`/snapshot interface types and documentation; standalone
  TypeScript interface check passes. Read-only GitHub checks found keypad
  `v1.1.1` offers only `mindflayer-keypad-1.1.1-server-firmware.tar.gz` (no serial
  install bundle); server `v0.3.0` still has protocol v2 and lacks all four new
  installation scripts. The appliance remains pinned to the existing 0.2.0
  digest. Publishing the remaining changes and selecting a verified new image
  requires approval beyond the explicitly authorized `bb9f7b7` push. No release,
  tag, branch, Environment setting or appliance pin was changed by this audit.
- Added stage-specific failed/interrupted installation recovery instructions to
  the UI, including the full job ID and private record location. Guidance
  distinguishes pre-write failures, possible credential registration, partial
  firmware, uncertain provisioning and online verification failure. Unknown
  stages fail conservatively; no raw private diagnostics are rendered as
  instructions. [Keypad recovery](KEYPAD-RECOVERY.md) documents retained files,
  manual checks, lock safety and new-job versus resume semantics. All 28 setup
  tests, typechecking, production build and 15 browser tests pass. Full Python
  suite: 104 tests, four optional skips; the separate actual sibling bundle
  builder contract test also passes (five serial-bundle tests, no skips).
  Physical interrupted-write recovery remains unverified; no automatic resume
  was added and no hardware was opened or flashed.
- Connected firmware-confirmed LED colours to inventory and the Nuxt UI. Full
  desired revisions require both the current central provisioning digest and
  matching authenticated LED colours. Pending commands, colour overrides and
  loss of connectivity clear current LED confirmation; historical older applied
  revisions remain labelled as last confirmed. Receipt-based expectations are
  persisted in the existing private, backup-covered expectation store. All 27
  setup tests, typechecking, production build and 14 browser tests pass, including
  confirmed/overridden/unknown LED display cases. Recreated pinned PlatformIO
  6.1.19 in `/tmp/elderbrain-platformio-check`; all 64 native/sanitizer cases and
  normal/rBoot builds pass. LED parser is included in the random corpus. Normal
  RAM/flash: 40,512/449,639 bytes; rBoot: 41,948/439,279 bytes. No hardware was
  opened/flashed. New server/firmware releases and physical verification remain
  outstanding; these local changes are not pushed.
- Added protocol-v3 nonce-bound LED commands and acknowledgements. The server
  clears confirmed colours when sending, accepts only the current authenticated
  command's acknowledgement, ignores superseded/replayed acknowledgements, and
  includes confirmed colours in late receiver snapshots. All 71 server tests
  pass, including exact frames, malformed input, browser forgery and legacy
  protocol coverage. The setup monitor validates and normalizes authenticated
  colours, clearing them on pending commands and disconnection; all 26 setup
  tests and typechecking pass. Inventory/UI reconciliation remains pending.
  Firmware parsing/application changes and their native test are present, but
  the native test attempt could not run because the previous PlatformIO virtual
  environment is missing. This is not yet firmware-build or hardware evidence.
- Bound serial operations to the MAC inspected from the actual ESP8266. The
  pinned esptool wrapper checks that MAC inside the same connection before chip,
  flash-ID, read and write operations; swapping a different blank keypad behind
  an identical adapter can no longer pass on unchanged empty sectors alone.
  Installation records and inventory include this inspected chip identity.
  Four adapter tests, the guard test, six coordinator tests and three backend
  tests pass. The guarded wrapper's version command runs on real esptool 4.9.0;
  hardware operations remain mocked and physical testing is still required.
- Connected backup-covered installation receipts to persistent inventory. The
  host projects only completed verified metadata and compares saved settings
  without exposing Wi-Fi credentials. Inventory records the last verified USB
  provisioning revision and confirms a full revision only when current settings
  match and no LED preferences remain unacknowledged. Historical receipts do not
  invent a live connection or overwrite newer observations; old jobs outside
  restored journals are not used as proof. All 25 setup tests, typechecking,
  six host inventory tests and six coordinator tests pass.
  Rebuilt production UI and all 13 browser tests pass, including completed
  installation appearing in inventory with its verified firmware/applied revision.
- Added authenticated release lookup and installation submission through the
  scoped host bridge, plus the Nuxt UI install flow. It shows the selected stable
  release and saved settings revision, offers one install button per appliance
  USB device, makes foreign adoption opt-in, and displays persistent job stages
  and results. Missing releases/unsaved settings/active jobs disable installation.
  Production build and typechecking pass; all 13 browser tests pass, including
  target/revision submission, secret exclusion, unavailable releases, unauthenticated
  access, CSRF and invalid-input rejection. Browser services are fixtures, not
  physical hardware. Inventory applied-revision integration and live appliance/
  hardware verification remain pending; this is not a hardware-readiness claim.
- Wired installation into persistent JobStore admission and workers. Admission
  snapshots central settings privately and rejects a stale requested revision;
  public records contain only sanitized request/progress/result fields. Workers
  hold both job and maintenance locks, inherited by child commands, and expose
  installation-specific interruption/recovery guidance. Eleven job tests pass.
  Added the root-private `keypad-installations` backup root: journals and sector
  backups are now covered. Eight backup/restore tests pass, including journal
  permissions, rollback retention and restoring pre-journal archives to an empty
  installation-record state. The initial full host run passed 100 tests (four
  optional integrations skipped); focused tests include later additions.
  Management/API/Nuxt UI integration still remains; no install endpoint is exposed.
- Connected the production backend to capability checks, verified downloads,
  passive USB revalidation, the signed serial installer, private server commands
  and bounded serial provisioning. The serial transport preserves upstream's
  RTS double-reset sequence while bounding writes and ACK buffering/timeouts;
  serial success still requires subsequent authenticated online proof. Thirteen
  coordinator/bridge/backend tests and five serial transport tests pass with
  mocked hardware. Installed esptool 4.9.0 in a disposable environment and ran
  the host wrapper's version command successfully; the version matches keypad's
  current tool package. Appliance installation and Dependabot discovery include
  this pin. Persistent JobStore admission/API/UI wiring and physical verification
  are still pending; no USB device was opened or flashed.
- Added official stable-release selection and bounded serial-bundle acquisition.
  It rejects drafts/prereleases, missing or duplicate serial artifacts, unexpected
  URLs/redirect hosts, oversize/truncated responses and wrong signatures. Downloads
  have socket and elapsed-time limits and do not overwrite existing artifacts.
  Five tests pass. The installed public signing key was compared byte-for-byte
  with keypad's authoritative public key and parsed successfully by OpenSSL;
  no private key was copied. Production backend composition and live acquisition
  verification remain pending; no published release availability is claimed.
- Added the host's private server-command adapter for preparation, credential
  registration and fresh online verification. Only fixed commands are allowed;
  secret input uses stdin and output uses anonymous private files with bounded
  parsing. Errors do not expose container stderr. The Docker client inherits the
  job lock, and container commands have independent deadlines as well as host
  timeouts. Ten coordinator/bridge tests and five private-command tests pass.
  Release acquisition, serial provisioning transport and the production backend
  composition still need connection before enabling install jobs in the UI.
- Added the private container-side online verification command. The server now
  timestamps accepted nonce-bound configuration reports and includes that time
  in authenticated receiver metadata. The coordinator records when serial
  provisioning begins; completion requires a proof accepted after that point,
  rejecting stale snapshots, untrusted/disconnected devices and wrong firmware,
  hardware or digest. All 70 server tests and six coordinator tests pass,
  including the real HMAC/proof/receiver path and stale-cache rejection.
- Added installation sequencing with an fsynced, mode-0600 private recovery
  journal and separate public stage/result projections. The prepared envelope
  and credential are saved before registration/flashing; failures retain them
  and prevent later stages. Completion requires authenticated matching ID,
  hardware, firmware and configuration digest, not just a serial ACK. Five
  coordinator tests cover ordering, adoption consent, envelope checks, preserved
  identity, failed-flash recovery data and public-output redaction. Production
  backend bindings, JobStore/API/UI integration and backup coverage for the
  final journal location remain unfinished; this does not expose an install API.
- Added private registration of prepared credentials: retries preserve identical
  secrets, conflicting identities are rejected, and an exclusive writer lock plus
  reload/atomic replacement/fsync avoids lost additions. Interrupted writer locks
  fail closed and require explicit administrator inspection. New authentication
  reloads the store without restarting existing keypad connections; corrupt stores
  reject new authentication instead of crashing the server. All 68 server tests
  pass; private-command documentation records secret handling and lock recovery.
  Host job orchestration still needs to persist and submit these prepared plans.
- Added the host serial-installer adapter and included it plus bundle verification
  in appliance installation. It checks the signed bundle and server capability,
  runs the bundled image preflight, saves original provisioning and requires
  identical records during the installer's second backup/readback. USB target
  changes stop commands. Subprocesses inherit the job lock; timeouts kill and
  reap the flasher process group, with diagnostics kept private. Nine focused
  tests pass, including the actual sibling signed packager/installer with only
  esptool transport mocked. This is not a physical hardware test or a completed
  job: credential registration, serial delivery, online proof and UI/job wiring
  remain to be connected. No real device was opened or flashed.
- Implemented private provisioning preparation and a container-side stdin/stdout
  command for the future host worker. Local identity/secret/debug settings are
  preserved; fresh or explicitly adopted keypads get new credentials. Damaged
  records require recovery rather than silent reinitialization. The command
  emits the exact envelope and digest only to private pipes, bounds input and
  suppresses secret-bearing exception details. It does not register credentials
  or flash hardware yet. All 63 server tests pass, including subprocess tests
  with a disposable certificate. Setup Wi-Fi validation now matches the actual
  firmware byte limits and rejects embedded NULs/non-string passwords.
- Added a read-only server-side provisioning-sector reader for the installation
  worker. It mirrors firmware commit/CRC/schema checks and A/B generation
  selection, including wraparound and ties. Ownership requires matching device
  ID, credential and server public-key pin. Blank flash is distinguished from
  damaged/unrecognized records so the worker cannot silently treat corruption
  as a new keypad. Tests cover interrupted/corrupt records, malformed CBOR with
  a valid CRC, generation selection and foreign credentials; all 59 server tests
  pass. This returns private credential material internally and is not a public
  API; worker integration and explicit adoption handling remain unfinished.
- Added an internal installation-job boundary that persists an expected
  canonical-envelope digest against a specific keypad revision. An authenticated,
  connected matching report can confirm only that revision; stale revisions,
  untrusted/offline reports and LED preferences cannot be acknowledged by this
  provisioning-only proof. Restart persistence and rejection cases are tested.
  The installation worker still needs to generate and register the expectation
  before sending its envelope; this internal method has no public API endpoint.
  All 24 setup tests and Nuxt typechecking pass.
- Committed the separately requested release Environment change in keypad as
  `bb9f7b7` (`fix(ci): protect firmware signing with release environment`). Only
  the release job binding and repository-setup documentation are included;
  formatting and release-note tests pass. Pushed only this commit to keypad
  `main` at the user's explicit request; remote HEAD verified as `bb9f7b7`.
  No GitHub settings change or approval was performed by the agent.

- Implemented protocol-v3 configuration proofs in keypad firmware and server:
  nonce-bound reports hash the canonical provisioning envelope reconstructed from
  boot-loaded settings. Server rejects forged/replayed/cross-session proofs and
  exposes the digest only as authenticated device metadata. Existing v1/v2
  keypads keep their previous frames and receive no new query. A capability
  endpoint and serial-bundle `deviceProtocol: 3` declaration support a required
  pre-flash compatibility check; new firmware must not be deployed before the
  matching server. No production image pin or release has been changed.
- Normal and rBoot firmware compile successfully (40512/41948 bytes static RAM;
  449303/438943 bytes application flash respectively). All 62 native/sanitizer
  tests and 56 server tests pass, including identical C++/Node provisioning
  digests. Elderbrain stores the proof but deliberately does not translate it to
  `appliedRevision` yet: the installation job must bind an exact expected envelope
  to a saved revision, and LED delivery needs its own acknowledgement. Setup/host
  tests pass (22 setup; 73 Python with 3 optional Borg integrations skipped).

- User authorized sibling keypad/server changes. Keypad release packaging now
  generates a separate RSA-2048/SHA-256-authenticated serial-install archive with
  rBoot, metadata A/B, unsigned application and the existing installer. Synthetic
  image/key tests prove packaging, wrong-key/OTA rejection and compatibility with
  Elderbrain's new bounded `serial_bundle.py` verifier. Five verifier tests cover
  signature/file tampering, unsafe addresses, decompression bounds and the actual
  sibling packager contract. This verifier is not yet wired to an installation job.
- Server receiver events now expose hardware/firmware with a server-derived
  authentication label; unauthenticated browser registrations cannot forge that
  label. Elderbrain accepts metadata only with that label and retains it offline.
  All 54 server tests, 43 keypad Python tests, 22 setup tests and setup typechecking
  pass. Applied configuration revisions still require a device protocol extension.
- Added schema-validated Dependabot configuration in all three repositories:
  Actions/npm everywhere, Docker for server/setup, pip for Borgmatic and PlatformIO.
  Keypad CI and releases consume the same new PlatformIO requirements file.
  Weekly grouped nonbreaking updates, separate security groups, no automatic merge.
  See `docs/DEPENDENCIES.md` for uncovered manual pins and activation limitations.
- Apart from the narrow Environment commit noted above, these additions remain
  uncommitted. No other pushes or GitHub settings changes were made. The existing
  appliance server image pin is unchanged and does not contain these local server
  changes yet. Next: configuration acknowledgement, persistent installation jobs,
  secure serial provisioning/adoption and connection verification. The complete
  goal remains active; these additions do not make hardware readiness proven.

- After successful post-restore service/bridge checks, the disposable VM was
  synced and powered off gracefully; loopback SSH/VNC ports are no longer open.
  Rebuilt `out/mindflayer-elderbrain-e57c24f58122.iso` with the tested LED UI.
  This is **development/test media containing the disposable test SSH public
  key**, not a hardware deployment image. Build deployment media with the owner's
  chosen SSH public key. The final LED-inclusive ISO has not been clean-installed;
  the preceding ISO passed the clean-install checks described below.
  Final test ISO SHA-256:
  `adea9b013c17e4b472ffa07231d66a9a205125d119974810069a8909d09c8ace`.
  The current VM disk is disposable `/tmp` storage and will not survive host
  shutdown; test conclusions are recorded here. Earlier workspace VM disks remain.

- Rechecked GitHub's latest keypad release after these tests: still `v1.1.0`,
  publishing `firmware.bin.signed`, `manifest.json`, the server-firmware archive,
  and `SHA256SUMS`, without a serial-install bundle. Completing one-click setup
  requires that trusted bundle or authority to extend the sibling keypad release
  packaging, plus setup-facing verified hardware/firmware reporting. No sibling
  repositories were changed and no releases were published. Physical USB/button
  behaviour, application of Wi-Fi/provisioning, and licensed Foundry-world recovery
  remain unverified. Do not mark the six-feature goal complete.

- Clean ISO installation in `/tmp/elderbrain-qemu/run.w1sPyc` passed without
  patching the installed appliance: all three containers healthy, exact server
  image pin, kiosk active, key-only SSH, setup-container management access, and
  verified administration CA/HTTPS/redirect/authentication/CSRF/logout checks.
  A live backup captured 10 roots, 34 entries and 612990 bytes. Restore passed
  credential preservation, system SSH symlink and rollback-capture checks; HTTPS
  passed again afterward. No licensed Foundry world or physical keypad was used.

- Real NFS integration passed inside that VM after installing the test-only NFS
  server: production mount verification, encrypted Borg backup and retrieval,
  recovery-kit generation, and rejection of a different configured export.
  The temporary loopback export and mount were removed by the test. The only test
  harness correction was creating `/etc/exports.d`, absent from the fresh package.
  Production backup code did not need patching. Latest LED UI changes are verified
  by production browser tests, not included in this clean-install baseline.

- Added optional persisted per-keypad LED colours using the existing upstream
  configuration protocol, with Nuxt UI colour controls. Offline preferences are
  sent once on reconnect, not on every key event. Saving reports sent/pending,
  never confirmed; disabling stops automatic sends without resetting colours.
  Desired revisions remain monotonic across LED and central Wi-Fi changes.
  Production build, typechecking, 21 setup tests and all 12 browser tests pass.
  This change postdates the ISO currently installing in `run.w1sPyc` and has not
  been tested on physical keypads. All 68 Python tests passed separately with real
  local Borg and SSH integration enabled.

- Rebuilt the ISO after the kiosk-startup and Borg archive-filter changes. A new
  clean installation is running with `KEEP_VM=1`, using temporary storage at
  `/tmp/elderbrain-qemu/run.w1sPyc`; earlier test disks remain untouched. Added a
  separate disposable-VM-only real NFS integration test, not yet executed.

- The second clean installation reached first boot, but the harness exited before
  reporting which service was not ready and forcibly stopped QEMU. On resuming
  that disk, Mindflayer's TLS key/certificate were zero-length and its container
  failed. No identity files were regenerated; the failed disk was shut down
  gracefully and retained. Clean-install success remains unproven. Guest checks
  now wait for each service and print failure diagnostics. Harness cleanup now
  requests a synced guest poweroff, with `KEEP_VM=1` available for diagnosis.
  Kiosk recovery is queued only after successful stack startup instead of a
  reciprocal Wants dependency, which had triggered repeated stack-start requests
  while the upstream container was failing. Static checks pass; another fresh
  ISO run is still required. The workspace has about 12 GiB free, so another VM
  disk should use temporary storage or explicit test-artifact cleanup.

- Real Borg-over-SSH integration now verifies encrypted backup/retrieval, access
  from an independent client reconstructed from the recovery kit with fresh cache
  state, and rejection of a changed host key. The loopback-only test sshd uses
  temporary keys and permits only a forced Borg command against the temporary
  repository; no normal SSH configuration is changed. This exposed Borgmatic's
  implicit identity/version archive filter hiding recovery backups on a replacement
  appliance. Restore listing now explicitly includes all Elderbrain archives;
  retention remains scoped to the current appliance across software versions.
  These two Borg-module changes postdate the currently running clean-install ISO.

  Run this opt-in test with
  `ELDERBRAIN_TEST_BORG_SSH=/path/to/isolated/bin/borgmatic`; Borg 1 must be beside
  that binary and `sshd`/`ssh-keygen` must be available. No external host is used.

- Added a real loopback SMTP integration test for the production Nodemailer
  sender. A child process trusts only the temporary test CA through Node's normal
  extra-CA mechanism; certificate verification is never disabled. Verification
  and password recovery complete over TLS, including session revocation after
  reset. Untrusted TLS and plaintext-only SMTP are rejected without saving email
  configuration. No messages leave the machine. All 19 setup tests pass. This
  verifies the mail sender, not an installed appliance's external SMTP provider.

- The stack now requests the kiosk service as a dependency. Tested in the patched
  VM by stopping the kiosk and restarting the stack: both returned active without
  a manual kiosk start. Rebuilt the ISO with all current startup/authentication,
  backup and USB-discovery fixes; all 12 production browser tests pass. The patched
  VM was shut down gracefully and its disk retained. A new untouched installation
  is running under `test/.qemu/run.KLv0WE`; clean-install results are still pending.

- Live backup in the patched VM initially rejected Ubuntu's packaged absolute
  `/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf` link. The archive engine now
  permits that exact source/target pair only, preserves it during staging, and
  rejects traversal through it; arbitrary absolute links remain rejected. The
  regression test passes. A real backup then captured all ten present logical
  roots (35 entries, 612912 content bytes) and returned services healthy. The
  disposable-VM live restore check passes: replacement of post-backup test data,
  credential-byte preservation, the system SSH link and mandatory rollback capture
  are verified. Post-restore container health, host bridge and HTTPS/authentication
  checks also pass. All 66 Python tests pass (two optional Borg integrations skipped).
  Foundry
  remains unconfigured in this VM, so this does not verify licensed-world recovery.

- The resumed VM now has three healthy containers and passes image-pin, host-bridge,
  administration CA/HTTPS, unauthorized API, bootstrap onboarding, secure-cookie,
  CSRF and logout checks. Its kiosk needed a manual start after the earlier failed
  stack dependency. Guest checks also exposed an empty bootstrap-password file from
  interrupted boot: startup now regenerates empty initial files, AuthStore replaces
  incomplete bootstrap input, rejects empty/short login values even against legacy
  empty hashes, and fails closed on incomplete root-reset input. Two new regression
  tests pass (18 setup tests total plus typechecking). The VM credential was reset
  privately; the updated setup image is being built there. This is a patched-VM
  result, not yet proof that the current ISO installs cleanly without intervention.

- Fresh ISO installation reached first boot. Editing the shell harness while it
  was running caused a shell read error and abrupt VM shutdown; verification was
  resumed from the existing disposable disk, not a reinstall. This exposed empty
  certificate/serial files after the interruption. Startup now validates leaf/CA
  files, preserves a valid CA when regenerating an incomplete leaf, and uses a
  random serial instead of relying on a mutable serial-counter file. Real OpenSSL
  tests cover empty leaf, empty CA and empty legacy serial files. The patched VM
  verifies its leaf against the CA and successfully imports kiosk NSS trust; the
  Nuxt container build is underway. The ISO still needs rebuilding with this fix,
  and full guest HTTPS/bridge checks have not completed yet.

- Passive USB serial discovery now lists appliance-side ttyUSB/ttyACM devices via
  sysfs and a scoped authenticated host operation. The installation panel shows
  USB adapter identity without claiming verified ESP8266 geometry or enabling
  flashing before trusted serial artifacts exist. Discovery never opens or resets
  a serial port; tests cover hot-unplug, non-character files and sysfs escapes.
  All 12 production browser tests and typecheck/build pass. This change was made
  after the currently running test ISO was built, so that ISO does not include it.

- Installed-appliance audit found stray `+` arguments in the first-boot OpenSSL
  and NSS commands, which shell syntax checking had not detected. Corrected the
  commands and added a real OpenSSL regression test that executes the production
  certificate block in temporary state, verifies CA trust, hostnames/IP, key modes
  and repeat execution. This test passes; it does not prove NSS/browser integration.
  The QEMU harness now checks verified administration HTTPS, redirect behavior,
  unauthorized access, bootstrap onboarding, secure cookies, CSRF/logout and actual
  setup-container access to the management socket. Each run gets a fresh retained
  disk directory instead of overwriting prior test disks. These new guest checks
  are syntax-checked but have not yet run in a freshly rebuilt appliance.

- The host now exposes a read-only, validated projection of server-registered keypad
  IDs. The setup inventory imports devices that have never connected, preserves
  user labels when registrations disappear, and marks registration knowledge unknown
  during bridge failure. No device credentials cross the bridge, and registration
  does not claim confirmed firmware or applied settings. Three host tests and a
  setup unit test cover schema validation, secret omission and persistent merging.
  Full verification now passes 62 Python tests (including real local Borg), 16
  setup unit tests and 11 browser tests, plus typechecking, build and static checks.
  Browser tests share authenticated storage state instead of exceeding the real
  login rate limit; authentication tests still exercise unauthorized access.
- Inspected the public [keypad v1.1.0 release](https://github.com/mindflayer-vtt/mindflayer-keypad/releases/tag/v1.1.0)
  and listed its server archive: only manifest.json and
  mindflayer-keypad-v1/1.1.0/firmware.bin.signed are present. The upstream installer
  requires trusted rboot.bin, metadata A/B and unsigned rboot-app.bin. Publishing
  this serial bundle is an external dependency for one-click fresh installation;
  no sibling repository or upstream release was modified by this task.

- Nuxt production build, TypeScript checking, 12 setup unit tests and all five
  browser tests pass. Browser coverage uses a prefix-stripping proxy and mocked
  management/controller peers, not physical devices or the installed appliance.
- Authentication, first-login recovery setup, log viewing and persistent observed
  keypad inventory are implemented. Appliance TLS integration remains unverified;
  desired keypad settings are not yet applied to devices.
- `appliance/lib/backup_archive.py` defines format 1: version/identity metadata,
  explicit logical roots, per-file SHA-256, ownership and permission metadata,
  relative links and secret-bearing `.tar.zst` output published with mode 0600.
  Eleven Python tests cover archive creation/validation, private restore staging
  with content/permission/ownership/link recovery, and rejection of malformed
  archives (including chained-link escapes). Decompression bounds include tar
  headers and padding. Archives are validated before publication; staging uses a
  private snapshot to avoid replacement between validation and extraction.
  These are archive/staging tests, **not complete appliance restore tests**.
- The CLI backup now uses this archive format and captures persistent application
  state/secrets, managed service files and SSH configuration. The maintenance
  coordinator journals service state before stopping services, resumes after
  exceptions, checks health and offers explicit interrupted-operation recovery.
  Seven additional tests cover coordination, locking, failures, restart recovery
  and the full logical source set in a temporary fixture (18 Python tests total).
  Docker/systemd effects remain mocked, so appliance integration is unverified.
- UI operations, encryption, live restore/rollback and Borg integration remain
  outstanding. The recovery command resumes interrupted **backup maintenance**;
  it is not a configuration restore command.
- `restore_transaction.py` adds a journaled replacement/rollback layer for fixed
  host targets. It prepares copies on each destination filesystem, preserves
  ownership, syncs journal/data, retains previous trees in private directories,
  and can recover interrupted multi-target replacements. Six temporary-filesystem
  tests cover exact replacement, rollback, retained data, interruptions and invalid
  mappings (24 Python tests total). It is not yet wired into host restore/service
  validation, so this does not establish end-to-end recovery readiness.
- `restore_service.py` now coordinates that transaction with maintenance: a
  rollback archive callback must succeed before replacement; restored validation
  and startup must succeed before commit; failed health triggers stopped-writer
  rollback and restart. Durable interrupted restores have their own recovery path,
  and backup recovery cannot incorrectly resume a half-restored configuration.
  Five additional tests exercise complete temporary-filesystem flows and simulated
  service/process failures (29 Python tests total). The live host adapter and CLI/API
  entry points are still pending; no live restore has been executed.
- Host CLI integration is now implemented: `restore ARCHIVE --confirm-restore`
  enforces matching software versions and required roots, maps archive entries to
  fixed destinations, creates the rollback archive inside maintenance, validates
  Compose/SSH and recreates services; `restore-recover` handles interruptions.
  Recovery stops containers by previously captured project identity rather than
  parsing potentially broken restored Compose configuration. Full-source fixture
  tests now cover restore plus rollback-archive content; 30 Python tests pass.
  Real Docker/systemd/TLS integration remains unverified, and web restore is pending.
- Persistent allowlisted host workers now support backup and recovery jobs.
  Admission and worker locks distinguish running work from interrupted jobs across
  bridge restarts. Jobs retain private diagnostics but return only bounded parsed
  results and generic failures. Authenticated `GET /api/jobs` and `POST /api/backups`
  are connected to the bridge; UI/download integration is next. Five worker tests
  bring the Python suite to 35 passing tests. The management socket now uses
  root/setup-UID peer checks and mode 0660 rather than world-connect permissions;
  installed-container access still needs appliance verification.
- The Nuxt UI backup panel now provides downtime/secrets consent, job history and
  authenticated streamed downloads. The bridge opens only completed backup job
  artifacts at a fixed backup-directory path, rejects symlinks/non-regular files,
  and streams over the scoped socket without exposing a host-directory mount.
  Typecheck/build, 14 setup unit tests, 36 Python tests and six browser tests pass.
  Browser tests cover consent, refresh persistence and download access control;
  transport tests cover split binary responses and truncation. These use mocked
  host operations, so installed-appliance maintenance/download verification remains
  pending. Upload restore, encryption and Borg UI are not implemented yet.
- Manual web restore is now connected: authenticated streamed upload to private
  host storage, persistent validation job, metadata preview, explicit replacement
  confirmation and the existing host restore worker. Restore references a completed
  preview rather than a caller-supplied path; SHA-256 is checked again before use.
  Upload limits, disk reserve, truncated-upload cleanup, binary transport and
  anonymous-access tests pass. Current totals: 39 Python tests, 15 setup unit tests,
  seven browser tests; build/typecheck pass. Browser host effects remain mocked.
  Encrypted exports, Borg integration and real appliance verification remain open.
- Borgmatic settings foundation now supports NFS and Borg-over-SSH destinations,
  generated/private repository passphrases, verified-host-key input, schedule and
  retention validation, and fixed-command configuration generation. Configuration
  is checked against the actual Borgmatic 2.1.7 schema in an isolated environment;
  43 Python tests pass with that verification enabled. The installer now includes
  Borg, NFS tools and a version-pinned Borgmatic environment. No remote repository
  has been contacted or modified. Repository actions, mounting, timer activation,
  recovery kit and GUI remain pending.
- `borg_repository.py` now implements encrypted Borg 1 repository initialization,
  listing, backup transfer followed by prune/compact, and fetching a single manual-
  format backup into the shared private-upload restore flow. SSH is noninteractive
  with pinned host keys. NFS operations verify exact mount source/type and refuse
  wrong mounts or local-disk fallback. Five adapter tests bring the suite to 48
  passing Python tests (including actual Borgmatic schema validation). Remote/Borg
  command effects are mocked, and CLI/jobs/UI wiring remains pending. The transfer
  currently stores the versioned compressed snapshot inside Borg; this prioritizes
  a shared restore format but deduplicates less efficiently than raw file snapshots.
- Borg CLI and persistent-job integration now exposes settings, explicit encrypted
  initialization, connection testing/listing, backup and archive retrieval. A fetched
  archive is validated and can be confirmed through the same restore job gate as a
  manual upload. Authenticated settings/action APIs are connected. Generated daily
  systemd timers run supervised jobs; schedule state is reapplied after restore.
  The backup service unit is included in manual backups. 51 Python tests and setup
  typechecking pass. GUI, recovery kit and real repository round-trip verification
  remain pending; no schedule or repository was activated in the development host.
- The Nuxt Borg GUI is now connected: destination/SSH host-key setup, schedule,
  retention, passphrase handling, explicit init/downtime confirmations, repository
  testing/listing, and archive retrieval into the common restore-preview controls.
  Eight production-browser tests and typechecking/build pass, including anonymous
  API rejection, settings redaction and remote archive selection. Host effects are
  mocked. The recovery kit and real remote round-trip tests remain outstanding.
- A separate repository recovery kit is now implemented and exposed as an explicit
  consent-gated host job plus authenticated streaming download. The private JSON
  artifact contains repository settings/passphrase, exported Borg key, applicable
  SSH credentials, identity/version and recovery instructions. Job responses expose
  only the artifact location, not its contents. 52 Python tests and eight browser
  tests pass, along with build/typechecking. Tests cover secret inclusion in the
  private artifact, consent, anonymous-download denial and job-response redaction.
  Actual key export and repository recovery are still mocked and require real Borg
  verification; encrypted manual exports and keypad provisioning remain open.
- Real local Borg 1.4.3 + Borgmatic 2.1.7 integration now passes, including encrypted
  repository initialization, backup/prune/compact, archive listing/retrieval,
  byte-for-byte snapshot recovery, exported-key import and repository access with
  fresh cache state using the recovery-kit passphrase. An incorrect passphrase is
  rejected. This caught and fixed missing staging-directory creation before init.
  New archive names carry appliance identity/version for listing; old names show
  unknown metadata. Staging copies now use unique temporary files so a failed copy
  does not permanently block subsequent backups. 53 Python tests pass with both
  opt-in integrations enabled; setup typechecking passes. Only the NFS transport
  guard is bypassed in this local integration test: SSH/NFS network behavior and
  installed-appliance orchestration still require separate verification.

Enable the real repository test with
`ELDERBRAIN_TEST_BORG_INTEGRATION=/path/to/isolated/bin/borgmatic`; a Borg 1 binary
must exist alongside it. All repository/cache/key artifacts are temporary, and no
external repository is contacted.
- Password-encrypted manual CLI exports now use GPG AES256 with integrity checking,
  disabled passphrase caching and stdin/descriptor passphrase delivery. Encrypted
  preview/restore decrypt into private temporary staging and reject wrong passwords,
  tampering and oversized plaintext without publishing partial results. Three real
  GPG tests pass (56 Python tests with all integrations enabled). CLI integration is
  implemented; GUI/job secret delivery still needs connecting. Existing root-private
  local plaintext snapshots are retained, while the exported artifact is encrypted.

Encryption option reference:
[GnuPG passphrase and unattended-operation options](https://www.gnupg.org/documentation/manuals/gnupg/GPG-Esoteric-Options.html).

- GUI encrypted export and encrypted upload previews are now connected to persistent
  host jobs. Passphrases use inherited memory-backed descriptors, never persisted
  job arguments. Encrypted uploads are integrity-checked and archive-validated
  before publishing a root-private plaintext restore candidate; confirmation uses
  the same checksum-checked restore engine without storing a password. The export
  consent checkbox now keeps its accessible name synchronized with encryption mode
  and changing mode resets consent. Real GPG job tests cover correct and incorrect
  passwords and temporary-stage cleanup. Verification: 59 Python tests (including
  real local Borg integrations), 15 setup unit tests, 10 production browser tests,
  typechecking and production build pass. Installed-appliance orchestration and
  one-click keypad provisioning remain unverified/unimplemented respectively.

Upstream reference used for the generated schema:
[Borgmatic configuration](https://torsion.org/borgmatic/reference/configuration/).
Run the optional real-schema test with `ELDERBRAIN_TEST_BORGMATIC=/path/to/borgmatic`
set while running the Python suite.

Run backup/restore tests with `python3 -m unittest discover -s test -p 'test_*.py' -v`
(requires the `zstd` executable).
