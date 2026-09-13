# Administration upgrade tracking

Scope: the user-approved goal attachment dated 2026-09-11. Elderbrain changes
remain local. Do not shut down the development PC or deploy during onboarding
without coordinating with the user.

## In progress

- Durable network transaction state machine stages original file bytes/permissions
  before writes; a separate worker can apply, confirm or roll back. Tests cover
  timeout, reboot, clock changes, partial writes, failed apply, wrong confirmation
  proof and external-edit conflicts. Production execution, independent watchdog,
  boot recovery and destination-bound TLS confirmation are wired into the local
  API/UI and tested on real VM networking. External Chromium CORS confirmation
  now passes with scoped test certificate-key exceptions, including actual
  DHCP-to-static application, loading Setup at the new IP, confirmation and exact
  DHCP restoration. The installed kiosk Chromium also passes ordinary private-CA
  trust and wrong-IP rejection at DHCP and new static addresses, without TLS
  exceptions. The actual authenticated form also passes old-page confirmation,
  fresh new-address login, cookie isolation and old-CSRF rejection in the VM.
  Remote-browser CA installation/routing and physical checks remain.
- Validated IPv4 Netplan transformation with preservation of other interfaces,
  IPv6 addresses, policy routes, Wi-Fi settings and DNS search domains. Coupled
  DHCPv4/v6 DNS changes required by networkd are identified for preview warnings.
  Real VM tests additionally cover DHCP/static application, confirmation and exact
  rollback. The latest interruption test kills the worker after real static apply
  but before its pending-state commit; production recovery restores DHCP and files.
- Origin-aware Netplan staging replaces split interface definitions without list
  accumulation, preserves untouched files byte-for-byte, and retains exact original
  bytes for rollback. Real Netplan validates the intended merged result and restores
  originals in isolated VM roots. Vendor/transient origins fail closed until their
  persistent ownership is resolved. The local form exposes only supported changes.
- Persistent display-preview transaction and independent watchdog implemented.
  Candidate settings are projected for preview without touching committed config;
  confirmation commits only against the unchanged original configuration. Timeout,
  reboot, cancellation and interrupted commits have regression coverage. Authenticated
  API/UI now use previews, direct config PUT is rejected, and confirmation controls
  survive page/browser reload. Production browser and real VM host-command tests
  passed. Full updated-appliance deployment and physical verification remain.
- Separate administration routes with shared responsive Nuxt UI navigation and
  authentication gating. Form guards cover appliance/Foundry, keypad settings and
  preferences, Borg, account and pending backup inputs. Network now has host-backed
  settings and timed confirmation rather than an unavailable placeholder.
- Host-side CPU, RAM and relevant filesystem measurements with five-second
  sampling and bounded one-hour in-memory history. Overview graphs replace raw
  JSON and report stale/unavailable values, uptime, versions and host service states.
  Local tests passed; physical appliance integration still needs verification.
- Read-only host IPv4 discovery on Network and Keypads, copy buttons, actual
  systemd-networkd DHCP/static attribution, gateway/DNS reporting, internal
  interface labeling and stale/error handling. Verified against the retained
  Ubuntu VM; changing addresses is implemented and VM-tested as described above.
- Sway monitor catalogue and output dropdowns with connector, make/model,
  resolution and active state. Missing selections are preserved and labeled
  disconnected; discovery failures disable selection without erasing it. Live
  read-only VM discovery verified. Physical monitor validation remains.
- Dedicated tty2 bootstrap display reserves tty2 from getty, refreshes temporary
  passwords and clears removed credentials. Installed and verified in the retained
  VM without printing credentials. Physical ThinkCentre deployment still pending.
- Browser mode/tab model, validation and controls; one/two views with safe HTTP(S)
  URLs and no embedded credentials. New browser launcher plans distinct connected
  outputs, reserves explicit assignments, skips disconnected screens, and separates
  admin/player profiles. Planner and UI tests cover this; real launcher integration
  now verified in the disposable VM, including a temporary second output and
  unplug reconciliation. Fixed private admin-config access using a root-prepared,
  display-only projection readable by the kiosk group. Physical two-screen testing
  is still required.
- Shared secret-entry reveal controls across login, recovery, SMTP, Foundry,
  backups, Borg and Wi-Fi settings.
- Empty-focus handling when forms appear; native invalid-field focus.
- Sixteen-word, hyphen-separated offline recovery codes; retain hashed storage,
  single-use reset and compatibility with existing codes.
- File-configured SMTP defaults selected with `SMTP_CONFIG` when building the ISO,
  private installation and optional custom SMTP fields. No actual provider or
  credentials have been supplied. Updated ISOs were built without SMTP defaults;
  see the lifecycle implementation record for prior VM qualification. Physical
  deployment of the broader upgrade remains pending.
- Beamer creation/explicit adoption, copyable pairing IDs, private credentials,
  automatic local Foundry login, per-view process cleanup and live status are
  implemented. The installed VM save → projection → Wayland login → status path
  passes over certificate-verified HTTPS. Camera startup, explicit off and selective
  reload pass real Foundry tests; framing logic is unchanged. See
  `BEAMER-INTEGRATION.md` for evidence and remaining visibility/physical checks.

## Remaining requirements

- Physical one/two-screen browser-mode, hotplug and preview/rollback verification.
- Finish live integration of the now-local DHCP/static IPv4 form, host transaction
  worker, and direct new-address TLS confirmation. Real VM timed rollback and boot
  recovery pass; real static/DHCP confirmation passes with a guest-local TLS client.
  Interrupted real apply now also passes recovery testing. Setup certificate refresh
  passes unit and live proxy-reload tests. External Chromium preflight, wrong-token
  rejection and confirmation pass through real VM ingress, including a real
  DHCP-to-static transition and independent restoration. Installed kiosk CA trust
  now passes without certificate exceptions. The full authenticated form and new-
  address session workflow pass in the VM. Remote-browser CA installation/routing
  and physical network transitions still need validation. See
  `NETWORK-SAFETY.md` for gates.
- Verify Beamer visibility and real keypad-driven camera behavior in representative
  worlds, plus sustained reconnect and one/two-screen hotplug with the new worker.
  Keep least privilege, existing credentials and the module architecture intact.
- Production/browser/host tests and coordinated physical testing. Include local
  login keyboard controls and managed Chrome password-saving policy in deployment.

Local source changes are not evidence that the installed ThinkCentre or its ISO
has been updated. Hardware/network/display and real Foundry integration checks
remain required before completion.
