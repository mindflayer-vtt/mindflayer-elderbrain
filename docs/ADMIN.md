# Administration

SSH is root/public-key only on port 22. Password and keyboard-interactive authentication are disabled. Useful commands:

```sh
elderbrain status
elderbrain restart-foundry
elderbrain restart-mindflayer
elderbrain restart-browser-session
elderbrain logs mindflayer-server
elderbrain backup
```

`elderbrain status` and the setup UI diagnostics include the configured Mindflayer image reference as well as running/health state. To independently inspect what Docker resolved, run:

```sh
docker compose --env-file /opt/mindflayer-elderbrain/appliance.env -f /opt/mindflayer-elderbrain/compose.yaml images
docker image inspect "$(sed -n 's/^MINDFLAYER_SERVER_IMAGE=//p' /opt/mindflayer-elderbrain/appliance.env)"
```

`elderbrain backup [destination]` now creates a versioned `.tar.zst` archive,
including Foundry data, appliance configuration and secrets, Mindflayer identity
and device credentials, firmware, Traefik state, browser state, managed service
configuration, SSH server configuration and the root/installer SSH directories
when present. The root-only administration CA authority is included so restored
appliances retain client trust; Traefik state contains only the public CA copy and
leaf serving material. Archives are mode 0600 but **not encrypted**; keep them private.
Password-encrypted CLI exports are available with `elderbrain backup-encrypted
[destination]`. GPG AES256 encryption wraps the `.tar.zst` as `.tar.zst.gpg`.
The CLI prompts without echo; automation can supply `--passphrase-fd N` using a
private inherited descriptor, never a password command-line argument. Use
`backup-preview-encrypted ARCHIVE` or `restore-encrypted ARCHIVE --confirm-restore`
for encrypted files. Decryption verifies integrity before publishing plaintext;
temporary decrypted staging is removed afterward. A root-private unencrypted local
snapshot remains on the appliance. The web panel also offers password-encrypted
exports with passphrase confirmation. Passwords travel to the host worker through
an inherited memory-backed descriptor, not command-line arguments or job records.
The web configuration-backup panel
starts persistent host jobs and offers authenticated streamed downloads when they
complete. Accept the downtime/secrets warning before starting. The administration
service stops during capture, so reconnect and sign in again afterward; job history
survives browser refresh. The host backup directory is not mounted into the UI.

The same panel accepts manual `.tar.zst` and encrypted `.tar.zst.gpg` uploads.
Encrypted uploads require their passphrase, which is cleared after submission;
successful decryption and archive validation produce a normal restore preview.
Wrong passwords or failed integrity checks never produce a restore candidate.
Validated plaintext is retained root-private for the confirmed restore, without
retaining the passphrase. Uploads stream to root-private
host storage and create a validation job without stopping services. Review the
resulting appliance identity, version and contents, then explicitly confirm
replacement to start a restore job. The upload checksum is checked again before
restore. Unfinished uploads are not published as restore candidates. Uploaded
archives and job diagnostics are retained locally; automatic cleanup is pending.

Borg CLI operations are available as `borg-settings`, `borg-configure` (JSON on
stdin), `borg-init`, `borg-test`, `borg-list`, `borg-backup`, and `borg-fetch NAME`,
all through `elderbrain`. Configuration supports a verified NFS mount or a
Borg-over-SSH repository; SSH requires a verified host public key and returns the
generated client public key for installation on the remote. Initialization uses
Borg 1 repokey-blake2 encryption. Never assume an arbitrary SFTP server supports Borg.
Automatic policy can independently enable a daily timer, a two-minute post-boot
timer, pre-update attempts, and pre-reboot/pre-shutdown protection. Every Borg
backup attempt—including local archive creation, validation, repository setup,
upload, prune and compact—shares the configured 30–1800 second deadline. A
pre-update failure either continues after recording the failure or blocks before
runtime installation, according to the explicit policy. Every accepted power
request first creates a read-only local checkpoint. When shutdown backup is
enabled, that checkpoint is pinned until its exact local `.tar.zst` has reached
the remote repository. Offline or interrupted uploads retain a private pending
record and retry one queued generation after boot; later shutdowns add their own
checkpoint instead of discarding or replacing earlier pending data. Retention
cannot delete any queued checkpoint. The
Borg GUI provides destination settings, trigger/timeout policy, schedule/retention, connection testing,
explicit initialization, manual remote backup, archive listing and retrieval into
the shared restore-preview workflow. Passphrases are cleared from the form after
saving and not returned by settings reads. The separate recovery-kit download is
available after initializing the repository: acknowledge its sensitivity, create
the kit, then download it from job history. The unencrypted JSON includes the
repository passphrase, exported Borg key, SSH private/public keys and verified host
key where applicable, plus recovery instructions. Keep it offline and regenerate
it when repository access changes. Normal job responses do not contain these
secrets. A real local Borg 1.4.3/Borgmatic 2.1.7 round trip now verifies encrypted
initialization, backup/list/fetch, restored file contents, key export/import, fresh-
cache recovery and rejection of an incorrect passphrase. Real SSH/NFS transport
and installed-appliance boot/power orchestration for the new trigger policy remain unverified.

Backup creation temporarily stops the running Compose services and kiosk, records
their previous state in a persistent maintenance journal, then restarts those
services and checks their health. An unconfigured Foundry service is not started.
If interrupted, inspect the appliance and run `elderbrain backup-recover` to resume
the recorded services. A pending recovery prevents another backup from starting.
`elderbrain backup-preview ARCHIVE` validates checksums and returns metadata without
extracting files or exposing their contents.

After reviewing `elderbrain backup-preview ARCHIVE`, use
`elderbrain restore ARCHIVE --confirm-restore` to restore a trusted backup from
the same appliance software version. This replaces application state, credentials,
SSH access and managed service configuration; archived administrative credentials
become active. Checksums detect corruption, not malicious modifications: do not
restore archives from untrusted sources.

Restore stages and validates the archive, stops writers, creates a rollback archive,
replaces fixed host targets, checks Compose/SSH configuration, recreates previously
running containers and checks health. Failed verification triggers rollback.
Previous trees remain in private `.elderbrain-restore-*` directories beside their
targets, and the rollback archive remains in the backup directory. No automatic
cleanup removes these recovery copies yet. Run `elderbrain restore-recover` after
an interrupted restore; `backup-recover` deliberately cannot resume a partial
restore. Do not extract archives directly over the appliance.

Temporary-filesystem integration tests and a live backup/restore round trip in a
clean-ISO disposable VM pass, including rollback capture, credential preservation
and post-restore HTTPS checks. Real loopback NFS and SSH Borg transport tests pass.
Licensed Foundry-world recovery and physical-hardware verification remain pending. Keep independent
recovery media and SSH access available when performing the initial hardware tests.

The web UI stores a Foundry timed URL or account credentials in a mode-0600 Docker `config.json` secret and never reads it back. Remove it from the UI once the distribution is cached. Foundry 14.365 and its matching felddy container 14.365.0 are deliberately coordinated. Upgrades require a release change, backup, image pull, and migration review; `elderbrain update` never performs an uncontrolled update.

Before a new Foundry instance starts, Elderbrain generates a separate four-word
Foundry administrator access key and stores it in the same private configuration.
The authenticated Foundry page can reveal that key; it is never returned to an
unauthenticated caller or included in logs. Foundry itself stores only a one-way
hash, so an administrator key created manually before this feature cannot be
recovered. Use **Reset and manage access key** to replace it explicitly and
restart Foundry. This key protects Foundry Administration and is distinct from
the passwords assigned to Gamemaster or Player users inside a world. Removing
download credentials retains the managed administrator key.

Administration now requires HTTPS and redirects HTTP requests. First boot prepares
a local CA and appliance certificate and installs local browser trust. Remote
clients need to trust the appliance CA after verifying it through a trusted local
channel, or use an externally managed certificate. The CA signing key is retained
under root-only host state and is not mounted into Traefik; only the separate
leaf-certificate directory is mounted read-only. Foundry retains its separate
login and routing. Installed-appliance TLS verification passed in a clean VM. Neither
public ACME nor external DNS is assumed.

The saved keypad inventory imports IDs from the server's credential registry,
including keypads that have never connected. Only IDs cross the host management
bridge; device secrets are never returned. Server registration is shown separately
from verified device provisioning and applied settings. A registry outage preserves
saved records and displays a warning rather than presenting them as a complete list.

Each saved keypad has optional two-colour LED preferences. These persist for
offline keypads and are sent using the existing controller configuration protocol
on save and reconnect. Sending a command does not confirm device application;
the applied revision remains unconfirmed. Foundry and Identify may subsequently
override these colours. Disabling the preference stops automatic sends without
resetting current colours. Saving central Wi-Fi settings alone does not apply them
to keypads; a USB install or provision-only job sends a snapshot of the selected revision.

The installation panel checks for the latest stable signed serial-install bundle.
An OTA download alone is insufficient: installation stays disabled if no suitable
bundle is available. Save Wi-Fi/appliance settings, select the attached device,
then click **Install & provision**. Foreign adoption is explicit; local identities
are preserved. The job checks server compatibility and hardware, backs up
provisioning, flashes rBoot/application, delivers settings and requires a fresh
authenticated firmware/configuration proof. Keep USB connected throughout.
For a keypad already running the selected stable protocol-v3 firmware,
**Provision settings only** performs the same identity inspection, sector backup,
credential preparation, USB delivery and authenticated proof without invoking the
firmware flash operation. A firmware-version mismatch fails verification and should
be resolved with **Install & provision** rather than treated as successful provisioning.
This flow has mocked/browser coverage but has not yet been verified on physical
hardware; some boards may require a boot/reset button.
The installation panel can passively scan USB serial devices attached to the
appliance (not the browser computer). Adapter names and USB IDs do not establish
the chip family or flash size. Scanning does not reset, flash or provision hardware.

Installation stages survive page reloads through the host jobs list. On failure
or interruption, retain `/var/lib/mindflayer-elderbrain/keypad-installations/JOB_ID`
and inspect its root-private journal and sector backups before retrying. These
records contain credentials and are included in configuration backups. Do not
post them in support logs. LED application still needs separate acknowledgement.

## Generated administrator passwords

Ctrl+Alt+F2 opens the dedicated temporary-password display, not a shell login.
The `elderbrain-admin-console` service reserves tty2, monitors the private initial
password file, and clears the terminal and scrollback when that file disappears
after password change. Root-reset passwords appear there too. No password is sent
to the service journal. Ctrl+Alt+F1 returns to the browser; Ctrl+Alt+F3 remains a
normal authenticated shell login. This console change must be deployed before it
will affect an appliance installed from an older ISO.

Displays selects outputs from the running kiosk's Sway catalogue. Entries show
connector, monitor make/model, current resolution and active/inactive state.
Previously selected connectors absent from discovery remain selectable as saved
disconnected entries; refreshes never clear an edit. If Sway is unavailable,
selection is disabled and saved values are retained.

Each of one or two configured views selects a player-map kiosk or a normal
administration browser. Administration opens Setup first, the configured Foundry
URL second, then up to ten additional tabs. Player kiosks open only their map URL;
Beamer automatic login is not implemented yet. Each view/mode has a separate
browser profile; older profiles are preserved, not deleted. Legacy views without
a mode keep kiosk behavior; new defaults use administration first and player second.
The launcher reserves explicitly assigned connectors before automatic assignments,
skips disconnected selections, and reconciles hotplug every two seconds. Saved
configuration is read on browser-session restart. Use **Preview display changes**:
the browsers restart with temporary settings, and **Keep display settings** must
be selected within 90 seconds. Confirmation is available on every admin page,
including after reopening Setup. **Revert display settings** cancels immediately.
Until confirmation, committed configuration is unchanged. The independent host
watchdog restores it on timeout even if the browser disconnects; reboot invalidates
pending previews. Direct `PUT /api/config` writes are rejected. Concurrent changes
to committed configuration prevent confirmation rather than being overwritten.
Physical appliance verification remains pending for this development build.

The private administrator configuration remains mode 0600. A privileged graphics
startup step projects only display settings into `/run/elderbrain-browser/config.json`
(root-owned, mode 0640, kiosk group). The kiosk never receives general administrator
state or secret files. `test/qemu/browser-modes.py` verifies actual browser modes,
tab arguments, output placement and virtual hotplug in the disposable QEMU VM,
then restores its original display configuration. It is not a physical-device test.

Administration uses separate Overview, Displays, Foundry, Keypads, Network,
Backups, Logs and Account pages. On narrow screens open **Menu** to navigate.
Configuration forms warn before discarding unsaved edits when following a menu
link, signing out or leaving the page. Background inventory/status refreshes do
not replace edits. Address-changing network controls are still pending rollback
and confirmation protection.

Network and Keypads show actual host IPv4 observations via the restricted host
bridge. DHCP/static labels come from systemd-networkd's per-address configuration
source; unavailable or unmanaged sources are labeled Unknown, never guessed.
Default gateways and IPv4 DNS are displayed on Network. Docker bridge/veth
interfaces are labeled internal there and omitted from the compact keypad view.
The current address is not the address previously provisioned into any keypad.
Changing host networking does not automatically reprovision devices. Copy buttons
are disabled for stale, unavailable or down interfaces; observations refresh every
five seconds. Clipboard failures leave the address selectable for manual copying.

Overview measures the host, not the setup container. CPU utilization uses changes
in Linux CPU counters; RAM usage excludes available memory. Storage reports used
space, available space (excluding reserved blocks) and total capacity, not I/O
activity. Root and appliance data directories are checked, with one graph per
underlying filesystem. Measurements are sampled every five seconds independently
of browser sessions, keeping up to one hour in memory. Restarting the management
service clears history. Missing readings and data older than 20 seconds are marked
unavailable/stale, not displayed as zero usage. Service badges describe systemd
host units; they do not assert that a Foundry world has finished loading.

All password and secret-entry fields have a show/hide button. Clearing a field
hides it again. New forms focus their first editable field when focus is otherwise
empty; background refreshes do not interrupt an active field. Browser validation
focuses invalid required fields on submission.

On the appliance screen, the searchable
keyboard-layout selector changes the physical keyboard layout (including XKB
variants) for the current kiosk session, before login. It resets to the configured
Sway default when the kiosk restarts. Remote browsers must use their own operating
system's keyboard settings. A private, per-kiosk capability permits only this
narrow operation; it does not grant administrative access.

Switching to the tty2 bootstrap display temporarily removes Sway's active output,
but does not terminate or recreate the browser. Returning with Ctrl+Alt+F1 keeps
the current form contents and tabs intact.

Sway window decorations are disabled, avoiding a redundant title bar above
Chrome's own administration tabs and maximizing usable display height.

Chrome's managed `PasswordManagerEnabled: false` policy disables saving new
passwords and save-password prompts in the appliance browser. This does not erase
previously saved credentials; Chrome may still use those if a pre-existing profile
contains any. The policy is installed at
`/etc/opt/chrome/policies/managed/elderbrain.json`.

New first-login and root-reset passwords use four lowercase random words
separated by hyphens. Each word is independently selected using the operating
system's cryptographic random generator from a bundled list of 256 words
(32 bits of randomness). This credential is one-time, locally displayed,
rate-limited and forces an immediate password change. Existing eight-word
bootstrap passwords remain valid. New offline recovery codes use sixteen words
from the same list (128 bits of randomness). They remain single-use and only
their hash is stored. Existing offline codes continue to work until consumed or
replaced; session tokens and emailed recovery tokens are unchanged.
