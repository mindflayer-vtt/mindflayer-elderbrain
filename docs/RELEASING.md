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

The publisher verifies every other reviewed runtime image, builds the Ubuntu
26.04/Python 3.14 offline dependency bundle, creates the reviewed host archive,
and signs the canonical manifest. It verifies the previous release signature and
requires a strictly greater sequence. The four fixed assets are uploaded to a
draft first; only after their exact names are confirmed does the workflow publish
the release and mark it latest:

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
  SSH_PUBLIC_KEY="$HOME/.ssh/g749-servers.pub" \
  UPDATE_SOURCE_CONFIG=config/releases/github-releases.json \
  UPDATE_PUBLIC_KEY=config/releases/appliance-release-public.pem
```

The baseline sequence is accepted during installation. The first online release
must therefore use sequence 2 or higher. Publishing remains unavailable while
the repository is private, but installing this baseline does not require a
GitHub credential; release discovery will begin working once the public channel
contains a newer signed release.
