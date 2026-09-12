# Beamer integration implementation notes

## Verified starting point

- The sibling `foundryvtt-mindflayer` repository is clean. Its `AGENTS.md` requires
  preserving submodule discovery, dependency ordering and selective reload.
- `src/js/modules/loader.js` discovers submodules by `index.js`; new Beamer
  ownership should live within this mechanism, not replace the loader.
- Existing `cameraControl` owns smooth player-token framing and depends on
  `ControllerManager`. Do not rewrite it for provisioning or authentication.
- Existing client settings include module enablement, broker connection and
  camera mode. There is no dedicated Beamer user creation/adoption implementation.
- Existing real-Foundry tests exercise the normal join form, using a selected user
  or username field and a password field. They are evidence of a test approach,
  not evidence that unattended Beamer login has been implemented.
- At inspection, no Foundry container was running on the host or disposable
  appliance VM. The module's Compose default is 14.367 and that image is cached,
  but its retained smoke world's manifest reports 12.331. Do not launch a newer
  core against that retained world in place. Use an isolated copy/new fixture and
  verify its running version before claiming compatibility.

## Implementation boundaries

1. Add a module-owned Beamer submodule and GM-only configuration action. Store
   the selected user ID per world, not a username-only match. Creation must refuse
   a name collision; adoption must be explicit and must not reset credentials.
2. Use the lowest usable player role and explicit individual permissions. Review
   effective permissions and document ownership as well as role: a Player label
   alone is not proof of least privilege. Reject GM/assistant-GM adoption and
   report configuration requiring manual review instead of silently downgrading.
3. Keep camera configuration in the existing camera submodule. Apply appropriate
   client settings only to the designated display client, preserving selective
   reload and independent normal administration-browser profiles.
4. Pair an appliance with a specific running world and module instance through
   an authenticated, explicit action. Keep the broker transport role unchanged;
   user-management semantics belong to Foundry, not the keypad broker.
5. Validate the normal join flow against an isolated real runtime before choosing
   unattended login. Do not assume a public REST login API exists. Never put
   credentials in URLs, logs, world-readable settings, or ordinary broker messages.
6. Expose distinct installation/world/module/pairing/login states in the Foundry
   page. A missing heartbeat alone must not be reported as a definitively missing
   module. Preserve existing users and recover safely after world switches.

## Evidence required before completion

- Real creation/adoption tests, including collisions, non-GM callers, preservation
  of existing credentials, per-world isolation and effective permission checks.
- Login against the actual running core version; no credential-bearing URL/log
  output; persistent isolated browser profile and safe credential-loss behavior.
- Module unavailable, world stopped, pairing revoked and world switched cases.
- Camera/door/torch/controller regression suite and physical display verification.

Primary references: [Foundry User API](https://foundryvtt.com/api/classes/foundry.documents.User.html),
[v14 user data](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.UserData.html),
and [user permissions](https://foundryvtt.com/article/users/). These document user
data and permissions, not an appliance SSO contract.

## Isolated appliance-version fixture

The appliance defaults actually pin `ghcr.io/felddy/foundryvtt:14.365.0`, not the
module test Compose default. An isolated container named
`elderbrain-beamer-foundry-test` now uses that image, bound only to
`127.0.0.1:30001`. Its copied data lives at
`/tmp/elderbrain-beamer-foundry.gZhWKq/data`; the retained sibling smoke world was
not mounted or changed. The downloaded image digest is
`sha256:bb8402d7098d0dcc136bf47c8932c0a1de5e405e021ca1710691cdd0ebdff730`.

Sanitized runtime logs verify core **14.365**, and Docker reports healthy.
The existing private test environment supplied download credentials and explicit
EULA opt-in; neither credentials nor license contents are recorded here.
Initial HTTP entry reached `/license`; world launch, module compatibility and
Beamer-user behavior still require validation in this isolated fixture.

Further inspection found the current built module explicitly declares minimum
core **14.367**. Consequently 14.365 cannot validate this module without bypassing
its compatibility guard. Local appliance defaults have been corrected to 14.367
in both the default environment and Compose fallback; a regression test guards
that alignment. The physical appliance and existing ISO remain unchanged. The
14.365 isolated setup attempt ended unsuccessfully; its container/data are retained
for diagnosis, and it must be replaced or separately restarted on 14.367 before
the module integration tests can be meaningful. Never claim module support on
14.365 from a successful container health check alone.

The old `elderbrain-beamer-foundry-test` container is now stopped (not deleted).
Replacement `elderbrain-beamer-foundry-v14` was started with the 14.367 image and
explicit core version, using the same isolated copied data and loopback port.
Verify its core version and complete world setup before testing provisioning.

The first 14.367 runtime download exited after curl error 56 (connection reset),
not an authentication rejection. The same container was restarted only after
that terminal failure was verified. The copied module directory was an empty
placeholder; it now contains a copy of the sibling repository's built `dist/`
module (3.0.0, minimum 14.367). The copied libWrapper/socketlib versions are older
than that manifest's requirements and must be upgraded in the isolated fixture
before attempting the module smoke suite. The source fixture remains untouched.

The retry completed successfully: Docker is healthy and sanitized runtime logs
verify actual core **14.367**. Its initial route was `/license`; the existing
explicit test EULA opt-in is being applied through the repository helper.

Isolated dependencies are now libWrapper **1.13.5.1** and socketlib **v1.1.4**.
Real setup exposed test-harness incompatibilities with the delayed tour exit
control and the searchable system selector's hidden backing select. Local changes
to the sibling `test/foundry/setup-runtime.mjs` address those controls; syntax and
diff checks pass. The disposable `elderbrain-beamer` world has been created under
the copied data root. Launch/login and module activation still require verified
runtime results; directory creation alone is not a passing integration test.

The corrected harness now passes: actual core 14.367, world `elderbrain-beamer`,
Gamemaster login, active smoke scene and configured dependencies. The repeatable
`test/foundry/beamer-login.mjs` probe created a temporary Player through Foundry's
User document API, disabled all individual capabilities, and logged in through
the normal join form in an independent browser context. Observed result:

- role 1, not GM, cannot create users;
- no enabled individual capabilities;
- canvas initialized and Mindflayer active with its module instance loaded;
- the test password never appeared in an observed request URL;
- the temporary user was deleted after the probe.

This proves a usable low-privilege login on this fixture, not complete appliance
auto-login. It does not yet cover arbitrary-world document ownership/visibility,
secure pairing or the physical kiosk.

### Module-managed creation and adoption verified

The local sibling module now contains a loader-discovered `BeamerUsers`
submodule and a restricted, hidden world setting `beamerUserId`. Creation uses
a dedicated Player with all individual capabilities disabled. Adoption requires
explicit confirmation and rejects elevated roles, assigned characters, enabled
capabilities and world-document ownership requiring review. It changes only the
selected world user ID, not the existing user's credentials or document.

Module lint, all 54 unit tests and development build passed. A separate
`NODE_ENV=production npm run build` also passed: the ordinary check writes
development assets, not `dist/`. The first integration attempts copied stale
`dist/` assets and correctly failed the missing-submodule preflight. After the
production build was copied into the disposable fixture, the updated
`test/foundry/beamer-login.mjs` passed on actual Foundry **14.367**:

- module-managed creation selected a configured Beamer user;
- adoption without confirmation was rejected;
- explicit adoption preserved the complete existing user document;
- the original credentials still logged in through the normal join form;
- the Player had no enabled capabilities, could not create users and loaded the canvas;
- the test cleared its selection and deleted its temporary user afterward.

Secure credential transfer/storage, automatic
kiosk login, informative appliance integration states, arbitrary-world visibility
review and physical testing remain outstanding. No physical deployment or push
was performed for this test.

### GM configuration form

The local module now registers a restricted **Beamer display user** settings menu.
The form delegates policy to `BeamerUsers`, offers separate creation/adoption
modes, a password reveal button, disabled ineligible candidates with review
reasons, and an explicit adoption checkbox. Configured users are shown without
passwords. Raw Foundry errors are neither logged nor displayed because they may
contain submitted document data. The menu does not implement credential reset,
unpairing, or appliance pairing.

The real 14.367 probe now creates the user through this form, toggles password
reveal/hide, exercises the adoption form, then logs in through an independent
Player browser context. All passed, with the temporary selection/user cleaned up.
The restricted menu registration is also asserted. Lint, 54 unit tests, development
and production builds passed after adding the form. Localization and broader
keyboard/accessibility checks remain to be completed.

### Appliance credential storage (not connected to kiosk yet)

The local Foundry page now accepts one world ID, Beamer user ID and existing
password. Authenticated `GET/PUT/DELETE /api/foundry/beamer` stores the record in
`STATE_DIR/secrets/beamer.json` with mode 0600, atomic replacement and a fresh
revision on each save. Existing global HTTPS/session/CSRF middleware applies.
The record is separate from downloadable Foundry account credentials and browser
view configuration. No caller-supplied login destination is accepted.

Public responses expose only world/user identifiers and `pairing-required` or
`pending-verification`; never a password or a claimed successful login. The UI
explicitly says automatic kiosk login is not connected. Removing the appliance
record does not modify the Foundry user. Malformed request JSON receives a generic
error because parser diagnostics can quote submitted secrets.

Three focused storage tests pass (permissions/redaction/revision changes,
invalid-input preservation, corrupt/unsafe/symlink rejection), and Nuxt typecheck
passes. This is not evidence of production endpoint authorization tests, browser
interaction coverage, login verification, or credential delivery to Chromium;
those integration steps remain. The module menu should also expose world/user
IDs for copying so the administrator need not obtain them from developer tools.

### Reusable login verifier

`provisioning/graphics/beamer-login.mjs` now owns the tested normal-join flow.
It accepts a dedicated Playwright page and private credentials, requires HTTPS
(HTTP only for explicit loopback origins), rejects off-origin requests during
login, and never returns browser exceptions or credentials. The browser/context
owner must disable credential-bearing automation diagnostics and discard failed
contexts; the helper blanks failed pages but does not own browser shutdown.

Before submitting a password it checks the running world, actual core 14.367,
user existence and Player role using the public join-page user metadata. After
login it checks the exact world/user, individual capabilities, active loaded
Beamer submodule, selected world user, module permission review and initialized
canvas. It returns bounded state labels rather than browser diagnostics.

The real fixture probe now uses this helper for Player login. It passed, as did
two additional real join-page checks: a different requested world and a GM ID
are rejected before any POST, leaving a blank page. Creation/adoption form tests
and fixture cleanup still pass. Syntax and diff checks pass.

This helper is **not yet wired into the installed browser-session launcher**.
Worker packaging, private credential delivery, status persistence/expiry, browser
restart/reconnect behavior and display-profile lifecycle integration remain.
Only the successful login and wrong-world/GM guards have real-runtime coverage;
the other state branches still need targeted tests.

### Persistent-profile worker

`beamer-worker.mjs` launches a dedicated persistent player profile with Chromium
sandboxing enabled, clears existing cookies before fresh verification, and
monitors the exact user/world/permissions/module selection and socket connection
every five seconds. Failed verification or revoked selection closes the browser.
The production entry point accepts a bounded private stdin packet, not credential
arguments; output is limited to state labels and timestamps. Automation debug
environment variables are removed before loading Playwright or launching Chrome.

The real fixture test passed sandboxed headless persistent-profile login, a fresh
ready heartbeat, and detection of a GM clearing the selected Beamer user. The
worker returned `pairing-required` and closed its context. Temporary users and
test-owned profile directories were cleaned up.

A dedicated graphics runtime manifest pins the existing tested Playwright Core
1.63.0 and integrity hash. Offline `npm ci --ignore-scripts --omit=dev` passed.
The installer now installs Node/npm, checks Node >=20, and installs this runtime
beside the browser scripts without fetching another browser through Playwright.
The installer change is syntax-checked, not yet installed on a VM or physical host.

The kiosk launcher still needs the credential projection/pipe connection,
loopback-only Foundry route, per-profile restart backoff and status integration.
The worker is not yet invoked by the installed graphics session. Its production
entry point is intentionally limited to fixed executable/profile paths and the
planned loopback Foundry origin, rather than arbitrary credential destinations.

### Launcher connection (local, not yet VM-verified)

The local launcher now invokes the Node worker for player views and sends its
credential packet through stdin. Administration views retain normal tabbed Chrome.
A player view waits without reopening an old profile when no pairing exists;
credential revision changes stop/recreate only the affected player workers.
Failed worker exits have a 60-second restart backoff, bypassed by a new revision.
Player mode targets local Foundry, not the former configurable URL; the Displays
page now states this explicitly and offers URL configuration only in admin mode.

The restricted host `beamer-refresh` command projects only validated Beamer fields
from the private Setup record to root-owned, kiosk-group-readable mode-0640
`/run/elderbrain-browser/beamer.json`. It is serialized, atomically replaced,
removed on missing/corrupt source, and refreshed during graphics startup and
authenticated credential updates/removal. Bad pairing must not prevent opening
the administration browser. The main private configuration remains inaccessible
to the kiosk account. Compose adds **127.0.0.1:30000:30000**, never a LAN binding,
for the worker's fixed direct Foundry destination.

Ten focused Python projection/browser tests passed, covering private projection,
revocation, corruption, fixed packet destination, profile separation and existing
one/two-monitor planning. Python compilation, installer shell syntax, diff checks
and Nuxt typecheck passed. These do not prove an installed Wayland launch, live
Compose port binding, API-to-worker update, or process-tree cleanup under forced
termination. Those require VM integration testing next. Live status collection
and endpoint/UI propagation are also still outstanding; worker output is currently
discarded by the launcher and Setup continues to show pending verification.

### Per-view process cleanup

The VM inspection showed the PAM-created Sway session resides in a logind scope,
not the graphics service cgroup, and had no kiosk user manager running. Delegating
only the graphics service would therefore not contain its detached browsers.
The local implementation now uses transient **user services**, one per view,
with `KillMode=control-group` and a five-second stop timeout. The installer enables
kiosk lingering; graphics preparation starts its user manager. Each view receives
its original Wayland runtime variables, while management commands use the separate
`/run/user/<uid>` bus environment. Fixed service descriptions avoid journaling
browser URL arguments as unit descriptions. Startup stops stale view units before
replacement, and a failed cleanup verification prevents replacement.

`test/qemu/browser-cleanup.py` passed in the disposable VM: both a parent and its
detached child ignored SIGTERM, yet stopping their per-view service removed the
whole populated cgroup. The first attempt exposed a missing manager
`XDG_RUNTIME_DIR`; the leftover test service was explicitly stopped, the environment
was corrected, and the test passed. The VM kiosk user manager remains running;
the physical appliance was not changed. Eleven local browser/projection tests and
shell/diff checks pass. Full Wayland launch with these new per-view services,
credential stdin forwarding and live status reporting still needs verification.

### Wayland service and live status progress

`test/qemu/browser-wayland.py` passed with actual Google Chrome in the VM's
existing Sway session: a temporary profile produced one test window, and stopping
its per-view service removed that window. The profile was cleaned up. Inspection
confirmed PAM places the actual compositor sockets in `/run/user/999`, despite
the graphics unit's declared runtime environment. The test used the discovered
socket and did not replace the physical appliance or deployed graphics launcher.

The local launcher now captures bounded worker stdout, accepts only fixed state
labels, timestamps observations itself, and writes a private atomic runtime
status report. The root `beamer-status` command validates ownership, file size,
record shape, active credential revision and freshness. Overall reports and
individual ready heartbeats expire after 15 seconds; revisions never cross into
public responses. A missing connected player view is distinct from a missing
pairing. Failed worker exits cannot retain a ready state.

Setup polls authenticated status every five seconds, showing per-screen results
and useful world/module/login/review states. Failed polling clears a displayed
ready result, and polling does not modify credential form fields. Twelve focused
Python tests and Nuxt typecheck pass. Full deployed API/worker/Wayland end-to-end
verification, production browser tests and remaining failure-state coverage are
still required; the separate real-Foundry and real-Wayland tests do not substitute
for that combined check.

### Regression and pipe checks

`test/qemu/browser-pipe.py` passed through the production per-view helper in the
VM: a randomly generated private stdin field reached the test process, while its
stdout contained only a fixed status object. No private value was echoed. The
test service exited and cleanup was verified. This proves systemd pipe forwarding,
not the complete installed Node/Foundry login.

The broad host suite ran **196 tests, with five explicit skips**; all non-skipped
tests passed. Setup's **36 tests** passed. An additional local test then verified
fragmented worker-output parsing, state allowlisting, private-field removal and
oversized-output rejection.

The first browser regression run used an older `.output` build and is not evidence
for the latest changes. Setup was subsequently rebuilt successfully and the
expanded suite passed **all 28 browser tests** against that fresh build. New checks
cover unauthenticated Beamer reads/writes/deletion, CSRF and cross-origin rejection,
password reveal, save/removal, public response redaction and preservation of edits
during live status polling. The host status source is simulated in this browser
fixture; real installed status/Wayland/Foundry integration remains the next gate.

### Combined-test VM prepared

The disposable host Foundry container `elderbrain-beamer-foundry-v14` is now
**stopped**. Its consistent `Data`, `Config` and cached 14.367 runtime were copied
over SSH into the new private VM directory `/tmp/elderbrain-beamer-vm-fixture`.
The same existing image was transferred with Docker save/load; no different
Foundry version was downloaded. The VM runs `elderbrain-beamer-vm-foundry`, with
restart disabled and **127.0.0.1:30000** as its only published port. The appliance's
existing Foundry data directory was empty and remains untouched.

The first container startup failed its volume-permission preflight because the
new directory was mode 0700/root-owned. Only that directory's ownership was
corrected to the container's UID/GID 1000; the test container was explicitly
stopped/restarted after the correction. It is now **healthy**, and `/join` returns
HTTP 200. The host copy remains stopped to avoid two running copies of the world.

Node **22.22.1** and npm **9.2.0** were installed in the VM using the installer’s
apt packages. The exact locked worker files and already-verified Playwright Core
package were copied to `/opt/mindflayer-elderbrain/beamer`, then made root-owned.
Package readability is verified. These preparation results do not yet prove the
combined installed worker login; its real Wayland/private-pipe test is next.
No physical deployment or push was performed.

### Installed worker + VM Foundry + Wayland passed

The combined test uses a loopback SSH forward from host port 30001 to the VM's
local Foundry port 30000. The host fixture stays stopped. Initial login failed
because the VM was on `/license`; its HTTP-200 `/join` response was actually
Foundry's “no active game session” error page. The existing explicit
`FOUNDRY_EULA_ACCEPT=true` test opt-in was applied through `accept-eula.mjs`, then
the existing authenticated setup harness successfully launched the copied world.
The login verifier now recognizes that no-world error page as `world-not-running`.

`BEAMER_VM=1 node test/foundry/beamer-login.mjs` then passed:

- GM creation/adoption forms and unchanged existing user document;
- wrong-world/GM rejection before password submission;
- exact restricted Player login against VM Foundry core 14.367;
- installed `/opt/mindflayer-elderbrain/beamer/beamer-worker.mjs`, running with
  VM Node 22.22.1 and actual Google Chrome through the per-view user service;
- private credentials delivered by SSH stdin and then the worker stdin pipe;
- two ready observations and exactly one real `elderbrain-view-1` Sway window;
- stopping the installed worker removed that window;
- the separate persistent-profile revocation check still passed;
- the temporary world selection and user were removed afterward.

The VM runner is `test/qemu/beamer-installed.py`. The VM's player profile remains
as test runtime state; it contains no valid test user after cleanup. The loopback
SSH forward remains available for follow-on integration work (exec session 51027
when created; revalidate before reuse). Python/Node syntax and diff checks passed.

This combines the installed worker, real server and compositor, but the runner
supplies the credential packet directly. It does **not yet** prove the full Setup
save → root projection → continuously running launcher → authenticated status UI
path, nor restart/hotplug behavior with the complete updated installation. Those
remain the next VM integration checks before physical deployment.

### Full service stack updated in the VM

Built a separate local `elderbrain-setup:beamer-integration` image, ID
`sha256:2a6929e75f18847f9058c866eeb43a119392014d9c8013a73b4b947fbfba612a`,
and transferred it to the VM. The prior `elderbrain-setup:1` image remains
available. Compose recreated only the Setup service using the new tag; its
container is healthy and the prefixed health endpoint returns HTTP 200. That curl
check bypassed certificate validation and is not a TLS-trust verification.

Before updating host scripts, their previous versions were archived at
`/tmp/elderbrain-pre-beamer.ecSkVd/runtime.tar` in the VM. There was no saved
`elderbrain/config.json` to copy: absence is the original configuration state,
not a lost file. Installed the current management, Beamer projection, browser
launcher, per-view service helper and preparation scripts, enabled kiosk lingering,
and restarted only VM management/graphics. Both are active; graphics reports zero
automatic restarts and the actual administration view user service is active.

The installed `beamer-status` host command returns `pairing-required`, and the
new VM API returns HTTP 401 without a session. The VM has no stored Beamer pairing.
Its existing administrator/initial-password files have not been changed. A
controlled authenticated account/session is still needed for the end-to-end
save/projection/automatic login/status test. Physical hardware is untouched, and
no repository was pushed.

### Authenticated VM fixture

Read-only inspection confirmed the original VM account still requires its initial
password change and has no verified recovery email. It was not overwritten or
marked verified. `setup/test/vm-auth-fixture.ts` created a separate test account
through `AuthStore`, with a simulated mail callback; this is explicitly **not**
an SMTP/onboarding integration result.

The temporary host fixture is `/tmp/elderbrain-vm-auth-Ni7Ry3` (private password
file; never print its contents). Its account JSON is mounted read-only from VM
`/tmp/elderbrain-beamer-auth/admin.json` onto the Setup container's account path
using `test/qemu/beamer-auth.compose.yaml`. The original backing account file and
initial-password file remain unchanged. Remove this override by recreating Setup
with the original Compose file and `SETUP_IMAGE=elderbrain-setup:beamer-integration`
after the combined test; that restores normal onboarding and invalidates fixture
sessions.

`test/qemu/beamer-api.mjs` passed HTTPS login and authenticated Beamer status using
the installed appliance CA and normal hostname/IP verification (no TLS bypass).
The password traveled through SSH stdin, not arguments or logs. Status was
`pairing-required`, and the test session was logged out. The temporary account
mount remains for the next save/projection/automatic-view/status test. This fixture
has not been baked into an ISO, shipped, or deployed to physical hardware.

### Full API-to-display pipeline passed; restart race fixed

Extended `test/qemu/beamer-api.mjs` to save the temporary world user through
authenticated, CA-verified HTTPS, start a one-screen player configuration through
the normal timed display preview, and wait for the installed status endpoint to
report a ready view. Cleanup cancels its own preview and removes its own pairing;
it does not persist the temporary display layout.

The first combined run exposed a lifecycle race: the player reported `stopped`
during a graphics restart and never reached ready within the test deadline.
The old Sway launcher was observed still alive briefly after graphics stopped.
The launcher now holds a process-lifetime `flock`, including cleanup, before
reusing per-view unit names. This prevents the old launcher's cleanup from stopping
a replacement launcher's new view. The fix was installed only after the old VM
launcher exited. Thirteen focused host tests and diff checks passed.

The retry passed the full installed path:

`authenticated HTTPS save → private root projection → automatic launcher →
real VM Foundry/Wayland login → live ready status`.

The direct installed-worker test and permission/selection-revocation test also
passed. The temporary Beamer user was deleted. Verified afterward that
`elderbrain/config.json` and `secrets/beamer.json` are absent, as before the test.
Graphics remains active. Setup was recreated without the temporary account
override; container mount inspection confirms that override is gone. The original
account still requires its first password change, has no verified email, and its
initial-password file remains intact.

The updated VM runtime/image remains installed; test fixture files remain private
for reproducibility. No physical deployment or push occurred. Remaining gates
include broader world visibility/camera behavior, sustained reconnect/hotplug
tests, the rest of the goal's integrated network/UI checks, a rebuilt ISO and
physical-device verification. This result is not completion of the overall goal.

### Beamer camera startup and usable pairing identifiers

The GM form now exposes read-only world/user IDs with click/focus-to-select,
verified through the real form. It also explains that pairing does not grant
ownership or bypass scene lighting/fog; the GM still controls Player visibility.

Real inspection showed `cameraControl` is client-scoped, its value is `default`,
and a fresh Beamer's general module-enabled setting is false. Thus earlier login
proofs did not establish automatic camera startup. The selected Beamer now requests
the existing CameraControl submodule and its normal dependencies independently of
that broad feature toggle. Its default camera mode resolves to `focusPlayers`;
explicit choices including `off` remain unchanged, as do other users' defaults.
The framing algorithm and Socket/ControllerManager separation were not changed.

The first attempt used the User document during the init hook and failed the real
camera-loaded assertion. It now uses Foundry's public active `game.userId`, which
is available before the User collection. API reference:
[Foundry 14 Game](https://foundryvtt.com/api/v14/classes/foundry.Game.html).

Lint, **55 unit tests**, development and production builds passed. The real VM
probe verified camera loaded + `focusPlayers`, explicit off, and replacement of
the camera submodule through selective reload without refreshing the page. Pairing
IDs, installed Wayland worker login/cleanup and revocation checks passed too.
The existing real-Foundry compatibility smoke test passed (one comprehensive test,
14.5 seconds). Temporary Beamer users were removed. Arbitrary-world visibility,
real keypad-driven framing and physical display behavior still need verification.

### Persistent profile restart and credential revalidation

The current real-Foundry probe passed again against the isolated 14.367 world
with the latest local worker. It now first obtains two ready observations, stops
that worker, and reuses exactly the same persistent browser profile with a random
incorrect password. That attempt returns `login-failed` and never reports ready,
proving that retained cookies do not bypass fresh credential verification.
Reusing the profile with the correct password subsequently reaches ready again,
produces another heartbeat, and closes after the GM revokes the selected user.
The temporary user and selection were cleaned up. No production user, world,
physical appliance or module deployment was changed.

This is a real browser/Foundry worker restart check, not proof of sustained
network-disconnection recovery or physical display hotplug. Those remain open.
# Username-based appliance pairing

The appliance now asks for **Beamer username**, defaulting to `Beamer`, rather
than requiring the end user to retrieve Foundry's internal user ID. Names must
match exactly and be unique in the selected world. The login worker resolves
the name before submitting a password and retains the resolved ID for session
verification. Duplicate/missing names fail closed. The Foundry module still
tracks its selected account by ID, and permission checks are unchanged.
Existing private ID-based pairing records remain supported until re-saved.
This change is local and has not been deployed to the powered-off Lenovo.
