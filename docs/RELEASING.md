# Production releases

Elderbrain uses the public GitHub repository's stable Release assets as its
production update channel. Appliances authenticate those assets with the reviewed
RSA public key in `config/releases/appliance-release-public.pem`; they never store
a GitHub token. Consequently, the repository and the
`mindflayer-elderbrain-setup` GHCR package must both be public before a production
release can complete.

## Signing authority

The appliance release key is independent of the keypad firmware signing key. Put
the complete private PEM only in the protected `appliance-release` GitHub
Environment as the Environment secret
`APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY`. Do not create a duplicate repository-level
Actions secret. Retain an encrypted or offline recovery copy outside the repository.

Configure the Environment to require approval and restrict deployments to
`main`. The workflow derives the public half of the supplied secret and compares
it byte-for-byte with the committed public key before signing anything. A key
mismatch fails the release. The workflow also queries GitHub and refuses to run
unless at least one required reviewer and exactly the `main` branch policy are
actually present.

Required-reviewer protection is unavailable for a private repository owned by a
GitHub Free organization. Add that rule immediately after making the repository
public and before dispatching the first production release; branch restriction
and the Environment secret can be configured while it remains private.

The workflow deliberately uses two fresh GitHub-hosted runners with different
authority:

```text
networked/untrusted build preparation
        |
        | fixed names + bounded SHA-256 receipt
        v
fresh protected signing runner
        |
        v
signed release
```

The `prepare` job has only `contents: read` and `packages: write`. It builds and
pushes the Setup image, runs pip/PEP 517 and npm packaging, builds both unsigned
archives, and uploads only the fixed prepared inputs. It never enters the
Environment and cannot read the signing secret or publish a GitHub Release.
Checkout credentials are not persisted, and its GitHub package credential is
passed only to the isolated registry step and removed afterward. PEP 517 build
isolation and downloaded upstream build dependencies remain a release-runner
trust boundary; this preparation is not claimed to be hermetic.

The `sign-and-publish` job has `actions: read`, `contents: write`, and
`packages: read`. It checks out the exact same commit without persisted Git
credentials, verifies the artifact receipt and every transferred file, rebuilds
the expected metadata from its own checkout, rechecks anonymous image access,
and authenticates the current publication sequence. Only then does one step
materialize the Environment key with mode `0600`, compare its derived public key
with the committed key, sign, and immediately delete both transient key files.
An `always()` cleanup is retained as a fallback. No dependency builder, Docker
build, pip download, or npm retrieval runs in the protected job.

## Publishing

Run **Actions → Appliance release → Run workflow** from `main`, supplying:

- a previously unused stable semantic `version`;
- a `release_sequence` greater than every published release; and
- plain-text end-user release notes.

After Environment approval, the workflow validates that the repository is public,
builds and pushes the amd64 Setup image, and proves that exact image digest is
anonymously readable. If its first run stops at that check, open the generated
package in the organization package settings, change its visibility to public,
and rerun the same workflow.

Preparation verifies every other reviewed runtime image, builds the Ubuntu
26.04/Python 3.14 offline dependency bundle, and creates the reviewed host
archive. The protected runner revalidates those bytes and signs the canonical
manifest. If a latest release exists, its manifest signature is authenticated
before its sequence is trusted. The four fixed assets are uploaded to a draft
first; only after their exact names are confirmed does the workflow publish the
release and mark it latest:

```text
manifest.json
manifest.sig
elderbrain-host.tar.zst
elderbrain-dependencies.tar.zst
```

A failed workflow never publishes a partial draft as latest. Inspect and remove
an incomplete draft/tag before retrying if failure occurred during the final
publication step. Never reuse a version for different content.

## Install baseline

Build production installation media with the same reviewed channel and key:

```sh
make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 \
  SSH_PUBLIC_KEY="$HOME/.ssh/elderbrain-admin.pub" \
  UPDATE_SOURCE_CONFIG=config/releases/github-releases.json \
  UPDATE_PUBLIC_KEY=config/releases/appliance-release-public.pem
```

The matching committed publication floor is
`config/releases/production-baseline.json`, currently version `0.1.0`, sequence
`1`. Production publication requires a sequence greater than the maximum of this
floor and the latest authenticated published manifest. The baseline is used only
when GitHub reports that no release exists; a malformed, missing, or invalidly
signed latest manifest fails closed. The first online release must therefore be
newer than `0.1.0` and use sequence 2 or higher; the planned qualification
release is exactly `0.1.1` / sequence `2`.

Publishing remains unavailable while the repository is private, but installing
this baseline does not require a GitHub credential; release discovery will begin
working once the public channel contains a newer signed release.
