# Private public-release readiness report

This report records the private qualification baseline prepared before the
repository is made public. The repository remained private throughout this work
and no production GitHub Release was created.

## History and repository audit

- Scanner: gitleaks 8.30.1, invoked by `make public-audit`.
- Audited commit: `92a2c9496dc6aa98497cb3139505970d8ecbe12d`.
- Scope: every remote branch and tag, all reachable Git history, and current
  tracked files (143 commits at the time of the recorded run).
- Result: pass; no leaks were found and no secret values were retained in audit
  output.
- Remediation: no genuine credential was found, so no credential rotation,
  revocation, or history rewrite was required. Public-facing documentation was
  separately reviewed and maintainer-specific paths and obsolete LAN handoff
  records were removed or generalized.

Run the audit again after any later documentation-only readiness commit and
record the resulting commit in the maintainer handoff before changing
visibility.

## Exact private baseline ISO

- Source commit: `6899cdade8c23b7ad8f07bc7b23cc9aa4b01d407`.
- Source tree: `a73650aa6c98da654efb0f4928f69675db5d1e62`.
- Tracked source identity: `ae4829290fc549ebd939436473bedfeec0616e967b23aaa7ca94a7b83355ae4a`.
- Appliance version: `0.1.0`.
- Initial accepted release sequence: `1`.
- ISO: `/tmp/elderbrain-baseline-output-final/mindflayer-elderbrain-0.1.0-r1-6899cdade8c2.iso`.
- ISO SHA-256: `8ab621d60e27cba254da6a043c4815060f6090752ee1aaf57f41b06e38ec4110`.
- Release public-key DER SHA-256 fingerprint:
  `da146820922e1eee1973dc6d91e036aa4e45de45a6904088c4830211b89fcb74`.
- Update source:
  `https://github.com/mindflayer-vtt/mindflayer-elderbrain/releases/latest/download/`.

The ISO was produced from a detached clean checkout through the normal tracked
production payload path. It contains a disposable QEMU public SSH key only for
this private qualification and is not a distributable production ISO. No
baseline GitHub Release was published.

## QEMU qualification

The exact ISO above was installed onto a new 96 GiB disposable disk whose serial
was `elderbrain-vm-test`. The following checks passed:

- clean numbered-disk installation and case-insensitive destructive
  confirmation;
- persistent storage identity, separate OS/data layout, installed semantic
  version `0.1.0`, and release policy sequence `1`;
- exact GitHub Releases source and committed release public key installed with
  the expected fingerprint;
- local release-status bridge returned the installed version and sequence, and
  the production browser suite verified that the System page renders this
  identity before contacting the release source;
- Docker, container stack, management bridge, graphical session, Chrome, Setup,
  Traefik, and Mindflayer services healthy;
- four-word one-time Setup bootstrap credential format, forced-change gate,
  private file permissions, secure session cookie, CSRF, logout, and disabled
  browser password manager;
- independently generated, persistent 12-word Foundry administrator key with
  mode `0600`, without printing either credential;
- permanent HTTP-to-HTTPS redirects for Elderbrain and Foundry, CA-verified TLS,
  the Foundry hostname SAN, and the Elderbrain route remaining healthy;
- the still-private GitHub release check failed safely as a source/network
  failure and created no update job;
- public-key-only recovery SSH remained usable and password SSH was rejected;
- a reboot changed the boot identity and completed with the outbound default
  route removed before Elderbrain services started; stack, management,
  graphics, Chrome, Elderbrain HTTPS, and Foundry HTTPS all became healthy from
  local state;
- the temporary offline control and route fixture were removed afterward, the
  Internet route was restored, and the retained disposable VM was left healthy.

The Foundry HTTPS and reboot checks used an isolated local upstream fixture on
the real Compose network because no licensed Foundry distribution credentials
were placed in the qualification VM. This verifies Traefik routing, TLS,
hostname resolution, restart persistence, and managed administrator-key
behavior, but not a licensed Foundry world. That external-product integration
limitation does not weaken the signed Elderbrain update-path qualification.

## Validation state

The final functional baseline commit passed GitHub CI, including actionlint,
Python/static tests, Setup tests and typechecking, Compose validation, production
Setup build, and browser tests. Local validation additionally passed 662 Python
and static tests (5 opt-in skips), 43 Setup tests, and 42 production browser
tests. The release workflow remains `workflow_dispatch`-only, and no production
release workflow was dispatched.

Clean installation may resolve newer authenticated Ubuntu and vendor packages;
the ISO is therefore not a byte-complete offline Linux distribution. The
coordinated Elderbrain application update is a separate signed, digest-pinned,
offline-prepared path, as detailed in `BUILD.md` and `RELEASE-FORMAT.md`.

## Release-control hardening

Production release preparation and signing now execute in separate fresh jobs.
The networked `prepare` job has only `contents: read` and `packages: write`; it
does all Docker, Python dependency, npm, host and dependency artifact work and
never receives the `appliance-release` Environment or signing secret. The
protected `sign-and-publish` job has `actions: read`, `contents: write`, and
`packages: read`. Both checkouts disable persisted credentials, and GitHub tokens
are provided only to the registry or GitHub API/publication steps that use them.

Five fixed prepared files cross the boundary. A strict receipt binds the source
commit/tree/identity, requested version and sequence, exact Setup digest,
dependency-source inputs, canonical metadata, and every transferred artifact by
bounded size and SHA-256. The receipt hash also crosses as a job output. The
protected runner rejects extra names, symlinks, special files, duplicate keys,
source mismatch, metadata drift and byte changes before exposing the key. It then
repeats anonymous Setup and runtime digest checks and sequence/tag validation.
The key exists only for signing, is removed immediately (plus defensive
`always()` cleanup), and the four final assets are independently verified after
removal.

`config/releases/production-baseline.json` records the already-installed
`0.1.0` / sequence `1` starting point. Publication requires a sequence above the
maximum of this committed floor and the latest authenticated signed manifest.
The baseline-only fallback applies solely when no GitHub Release exists; bad
latest-release metadata or signatures fail closed. Focused tests accept
`0.1.1` / `2`, reject proposed sequences `0` and `1`, accept sequence `3` after
an authenticated sequence `2`, reject `1` and `2` in that state, and exercise
malformed baseline/latest inputs.

This boundary prevents PEP 517 and other dependency build code from executing on
the protected signing runner. Preparation still downloads and executes upstream
build tooling and is intentionally not described as hermetic.

## Post-public transition

Follow `PUBLIC-RELEASE-CHECKLIST.md` in order. In particular, make the repository
public first, immediately protect `main`, require the green `test` check and
review/CODEOWNERS gates, then protect the `appliance-release` Environment with an
approving reviewer and a `main`-only deployment policy. Keep
`APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY` only in that Environment and establish
anonymous GHCR visibility before approving a release.

Use these first-update workflow inputs only after every transition gate passes:

```text
version: 0.1.1
release_sequence: 2
notes: Public-channel qualification update with an observable release marker.
```

Independently validate the four release assets, signature, sequence, immutable
Setup digest, all runtime digests, anonymous downloads, appliance update,
post-update offline reboot, and one real-channel interruption recovery exactly
as described in `PUBLIC-RELEASE-CHECKLIST.md`.

## Remaining external gates

These are intentional post-public actions, not private code defects:

- enable public `main` ruleset enforcement and Environment approval;
- confirm no duplicate repository/organization signing secret exists;
- make the Setup GHCR package anonymously readable and verify its exact digest;
- publish and exercise the harmless `0.1.1` / sequence `2` update;
- optionally exercise a licensed Foundry world and physical keypad/hardware as
  separate product-integration checks.

Until those gates are deliberately performed, keep the repository private and
do not publish a production release.
