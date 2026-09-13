# Network change safety requirements

The local Network page now has DHCP/static controls. Do not deploy these controls
to the physical appliance before the remaining live integration gates below pass.
Local code and mocked browser tests are not evidence of end-to-end hardware safety.

Implemented foundations:

- Validated IPv4 transformation preserving unrelated Netplan configuration.
- Source-aware replacement that avoids Netplan's sequence-append behavior.
- Private isolated hierarchy validation, merged-result verification, and a
  content/ownership/mode fingerprint checked again immediately before application.
- Persistent original bytes and permissions before any candidate write.
- Worker-driven transaction phases: staged, applying, pending, confirmed,
  rolling-back, rolled-back.
- Recovery of interrupted multi-file writes; wall-clock and monotonic deadlines;
  invalidation across boots; exact original restoration before reapplying networking.
- External edits are not silently overwritten. A conflict after application keeps
  rollback pending and requires resolution; an edit before application discards the
  candidate without applying any network changes.
- Worker entry point with bounded Netplan operations, process-group termination
  on timeout, and generic errors that do not log backend configuration.
- Boot-recovery operation restores unconfirmed sources and regenerates backend
  files without applying networking. Failed generation remains retryable.
  The installed recovery unit runs before network-pre.target; networkd and
  NetworkManager drop-ins require successful recovery. The independent watchdog
  restarts automatically. Ordering follows the upstream
  [systemd network-pre guidance](https://wiki.freedesktop.org/www/Software/systemd/NetworkTarget/).
- Disposable VM reboot verified a simulated interrupted, comment-only Netplan
  write: exact original hierarchy restored before networkd activation, terminal
  recovery record retained without private source bytes, and watchdog active.
  Reproduce with `test/qemu/network-recovery.py prepare`, reboot, then `check`
  inside a disposable QEMU guest with the current runtime installed. This does
  not yet prove real address-transition or NetworkManager recovery behavior.
- Real VM transition verified: DHCP `10.0.2.15` to static `10.0.2.20`, watchdog
  restart while pending, then automatic return to DHCP after the 45-second test
  deadline, with exact original source bytes/ownership/permissions restored.
  `test/qemu/network-transition.py` runs independently of the SSH connection.
  This test exposed and fixed inheritance of the worker's restrictive umask:
  Netplan subprocesses now use 0022 so networkd can read generated backend files;
  transaction recovery records remain private. A successful Netplan exit alone
  is not evidence that the requested live address took effect.
- Strengthened reboot test also passed after the umask fix: networkd selected the
  restored Netplan backend (not dracut fallback), and its unprivileged user could
  read the generated network file.
- Confirmation verifier checks a real connected host IPv4 socket's local
  destination against the selected interface's current address and DHCP/static
  source. Static confirmation also requires the exact requested address. A fresh
  256-bit token is represented only by a hash in private transaction state, and
  its binding is removed on confirmation or rollback. Real local-socket tests
  reject forged address fields, wrong tokens, wrong/stale interface addresses,
  unknown address sources, disconnected sockets and terminal transactions.
  This is not yet a user-facing confirmation path: the setup UI still needs
  integration and live confirmation validation. The
  management bridge must never accept a serialized socket/destination proof.
- Narrow HTTPS endpoint implementation accepts only a bounded JSON confirmation
  POST with the transaction ID and one-time token. Tokens are never in URLs or
  logs. It does not use cookies or proxy headers; cross-origin requests use only
  the capability token. TLS handshakes run in bounded concurrent worker threads,
  separately from the rollback watchdog. Local real-TLS tests cover confirmation,
  replay, forged destination headers, invalid bodies, and plaintext rejection.
- Short-lived leaf certificates use the existing appliance CA with the exact
  new IPv4 SAN. A real TLS handshake verifies that CA trust and exact SAN; the
  existing CA files remain unchanged and temporary leaf private files are removed.
- A separate installed systemd service manages the pending-only listener on TCP
  10444. It binds both the exact current IP and the selected Linux interface,
  discovers a unique DHCP lease, and closes on terminal/expired/missing-address
  state. Readiness is published privately with a timestamp and transaction ID.
  Generation and listener errors cannot block the separate rollback watchdog.
  Lifecycle unit tests pass; the disposable VM verifies service startup and no
  listening socket while idle. The installer permits the port through UFW, but
  the physical appliance has not received this change.
  Live pending/confirmed listener testing, browser trust/reconnection and updating
  the main setup certificate remain integration work.
- The authenticated setup API now exposes GET/POST `network/change` and POST
  `network/change/cancel` through the restricted management bridge. Staging checks
  each recovery service individually, rejects inactive/internal interfaces,
  validates the candidate, and returns the token only to the initiating response.
  Status never returns that token and advertises only a fresh matching listener.
  There is deliberately no proxied confirmation command. A lost initiating
  response leaves the change subject to timed rollback; do not automatically retry.
- Local Nuxt UI controls expose active interfaces, DHCP/static mode, prefix,
  gateway and DNS; timed confirmation and explicit revert; connection-loss and
  unknown-response states. A token stays in memory only and confirmation sends it
  in a credential-free, non-redirecting JSON POST to the new host endpoint. A
  reload cannot recover the token, but cancellation and timed rollback remain.
  Browser tests mock the new network endpoints; live browser/VM confirmation is
  still required. Polling does not replace a manually entered destination address.
- Real VM confirmation round trip passed through the production host service,
  worker, listener, certificate issuer and verifier: DHCP to static, wrong-token
  rejection, valid static confirmation, listener closure, static back to DHCP,
  lease discovery, previous-token rejection and valid DHCP confirmation. The TLS
  client trusts the existing appliance CA and verifies each exact IP. Test cleanup
  restored the exact original hierarchy. Reproduce with the detached VM-only
  `test/qemu/network-confirmation.py`. Its client runs inside the guest bound to
  ens3; this does not prove external browser/UFW reachability or setup reconnect.
- Setup certificate refresh now adds the new IP while retaining existing DNS/IP
  SANs, CA and leaf private key. Certificate and dynamic-configuration parent
  directories are mounted read-only into Traefik, so atomic replacement remains
  visible and re-publishing the unchanged configuration triggers its watcher. The listener
  prepares this before opening confirmation TLS. Unit tests verify preservation
  and idempotence. A live VM test (`test/qemu/admin-tls.py`) verified that Traefik
  actually served the new CA-verified certificate, then restored the original
  files and verified the original certificate was served again. Full external
  browser reconnection through a real address transition remains unverified.
- External host ingress passed using a temporary loopback-only QEMU port forward
  through the guest's ens3 interface and UFW rule. The host TLS client verified the
  appliance CA and exact guest IP, then confirmed the pending DHCP transaction.
  `test/qemu/network-external.py` restores original Netplan files and removes only
  its own forwarding/firewall rule. Combined with the guest-local static/DHCP
  round trip, this verifies network ingress and the production confirmation stack,
  but not browser CORS/private-network policy or cross-address login/reconnection.
- Follow-up `network-external.py --browser` passed with real Chromium, the actual
  HTTPS Setup origin and production confirmation listener. A CONNECT-only proxy
  routes exact guest-IP URLs to temporary loopback QEMU forwards; neither HTTP
  endpoint nor its response is mocked. Chromium observed the OPTIONS preflight,
  read a CORS 409 response for a wrong token, then read a CORS 200 confirmation.
  An independent host-service query verified the same transaction was confirmed.
  Both server leaves were first validated against the appliance CA and exact IP
  by the host TLS client. The disposable browser uses only their SPKI exceptions,
  **not** blanket certificate-error suppression. This does not prove normal
  browser CA installation, direct LAN/private-network permission behavior, the
  authenticated form workflow, or cross-address reconnection. The fixture stages
  DHCP at its existing address. Cleanup restored the original files, removed its
  forwards/firewall rule, and left both network services active with DHCP
  `10.0.2.15`. No physical appliance was changed.
- Real address-transition follow-up also passed:
  `test/qemu/network-browser-transition.py MONITOR BACKEND` starts a detached
  QEMU-only controller, applies static `10.0.2.20` through the production service,
  and routes Chromium to the actual new address. Both the Setup and confirmation
  leaves pass independent CA/exact-IP verification before scoped browser pins
  are permitted. Chromium loads Setup at the new IP, rejects a wrong token and
  confirms through the real listener. The detached controller independently
  observes `confirmed` with actual static IPv4, then restores DHCP and the exact
  hierarchy fingerprint even after a successful confirmation. Its private packet
  file is confined to a root-only temporary directory; no capability is logged.
  The host removes its three forwards and temporary firewall rule. Post-test
  inspection confirmed DHCP `10.0.2.15` and both production services active.
  This test uses a fresh browser at the new IP, not an authenticated old-address
  page surviving the transition: full form submission, cookie/session isolation,
  normal browser CA trust and physical LAN behavior remain separate gates.
  The VM listener was updated to the current local version for this test; its
  previous copy remains at `/tmp/elderbrain-network-listener-pre-static-browser.py`.

Required before exposing live changes:

Authenticated installed-UI gate subsequently passed in the VM. The new
`network-auth-browser.mjs` uses the actual login and Network forms in sandboxed
installed Chrome, with normal CA verification and no endpoint mocks. It signs
in at DHCP `10.0.2.15`, submits static `10.0.2.20`, retains the original page and
its in-memory capability, and confirms through the new address. At the new Setup
address, no old session cookie is present and unauthenticated configuration reads
return 401. Fresh login succeeds; reusing the old session's CSRF token returns
403; normal sign-out succeeds. The detached root `network-auth-controller.py`
captures the original transaction before permitting confirmation and independently
checks confirmed state, then restores DHCP and the exact Netplan fingerprint.

The successful service invocation on 2026-09-11 ended at 16:20:53 UTC, unit
`elderbrain-network-auth-3M5pj5Tr.service`; its private result directory contains
`{"passed":true,"restored":true}`. The first invocation stopped at login before
any network change, immediately after container recreation; the successful retry
followed a verified HTTPS health check. The controller now includes that readiness
check. A read-only temporary verified-account mount was used, not a real SMTP
onboarding flow. Afterward the override was removed and the original unverified,
must-change account and bootstrap file were verified preserved. Network and
graphics services remained active. The test loaded the new address directly;
the newly added reconnection hyperlink is covered separately by local UI tests.
Remote-client routing/CA setup and physical-network behavior remain unverified.

Normal appliance-browser trust gate now passes in the disposable VM:
`network-external.py MONITOR BACKEND --kiosk-browser` and
`network-browser-transition.py MONITOR BACKEND --kiosk-browser` both passed.
First copy `test/qemu/network-browser-trust.mjs` to
`/tmp/elderbrain-network-browser-trust.mjs` in the VM. These modes run installed
Google Chrome as the existing kiosk user, with Chromium sandboxing enabled and
no certificate-error overrides, SPKI exceptions, proxy, or TLS mocks. Its normal
installed CA trust accepts Setup and the confirmation listener at DHCP
`10.0.2.15` and newly applied static `10.0.2.20`. A wrong-IP request to
`127.0.0.2` fails with `ERR_CERT_COMMON_NAME_INVALID`; unauthenticated Setup config
still returns 401. Real CORS wrong-token rejection and confirmation succeed.
The detached static controller independently verified confirmation and restored
DHCP plus exact original files. This proves the installed kiosk trust setup,
not CA import in arbitrary remote browsers or the complete authenticated
old-address form/session transition. The test browser is headless, separate
from the visible kiosk session, and the physical Lenovo was not changed.

Local reconnection UI now offers an explicit HTTPS Setup link after a successful
direct confirmation response. It snapshots the destination before sending the
request; editing the address while the response is in flight cannot redirect the
resulting link. The link carries no credentials, uses `noopener noreferrer`, and
receives focus after the user's confirmation action. It warns that a new IP
requires a fresh sign-in (the session cookie is host-only). Four focused browser
tests pass, covering confirmation/link behavior, the delayed-response address
race, lost start responses and reload/token loss. These UI tests use mocked
network endpoints; they supplement, not replace, the real VM gates above. This
UI update has not been deployed to the Lenovo.

Interrupted-apply gate update: `test/qemu/network-interruption.py` passed against
the installed production watchdog. A test-only PATH wrapper ran real Netplan apply,
then paused before returning, leaving durable phase `applying` with actual static
IPv4 `10.0.2.20`. Killing the watchdog cgroup forced its automatic restart; the
production recovery branch restored DHCP `10.0.2.15`, the exact original hierarchy
fingerprint, and removed transaction originals. The detached test service exited
successfully. Its runtime override was removed and normal watchdog restarted.
No physical network was changed. This injects a pause after actual backend apply;
it does not claim to exercise every possible internal Netplan interruption point.

1. Verify the production staging and transaction integration against the VM's real
   Netplan hierarchy; unit tests alone do not prove live address-change safety.
2. Exercise the installed watchdog with real address changes and interrupted apply
   operations. Boot recovery has passed the comment-only interrupted-write test;
   DHCP-to-static-to-timeout rollback and a pending watchdog restart have passed.
   Static and DHCP confirmation now pass with a guest-local TLS client; the
   real post-apply/pre-commit interruption test described above also passes.
   The stronger boot/backend-readability check
   has passed. External client and scoped-certificate browser confirmation now
   pass as described above; ordinary browser trust/reconnection remain gates.
3. Confirm only through the selected interface's new current IPv4 address. The
   production verifier must use trusted connection-destination evidence and an
   authenticated, transaction-bound confirmation action. Do not accept a supplied
   Host/X-Forwarded-Host header or a submitted address as proof: the setup container
   sits behind Traefik, so its socket's local address is also insufficient.
4. Handle DHCP address discovery, TLS certificate coverage, reconnection and login
   at the new address. Never claim that already-provisioned keypads were updated.
5. Test real DHCP/static transitions, lost HTTP responses, rollback, confirmation,
   watchdog restarts and reboot recovery in the disposable VM before physical use.

`NetworkTransaction` deliberately requires an injected confirmation verifier. The
production worker uses `network_confirmation.verify`; existing transactions with
no token binding cannot be confirmed. Core transaction unit tests use fake apply
callbacks and temporary files; the QEMU tests above exercise the real worker.
