# Build

Install `bash curl git gpg xorriso rsync tar squashfs-tools coreutils`, then run:

```sh
make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 \
  SSH_PUBLIC_KEY=/absolute/path/to/id_ed25519.pub
```

For example, to use your server administration key for a hardware test:

```sh
make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 \
  SSH_PUBLIC_KEY="$HOME/.ssh/g749-servers.pub"
```

The key is selected at build time, not hard-coded. Choose another public-key
path for another deployment; the corresponding private key is never embedded.
Copy the resulting ISO as a regular file onto Ventoy's data partition; do not
write it over the USB device or format the existing Ventoy installation.

Production media should also embed the reviewed GitHub Releases channel and its
independent public verification key:

```sh
make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 \
  SSH_PUBLIC_KEY="$HOME/.ssh/g749-servers.pub" \
  UPDATE_SOURCE_CONFIG=config/releases/github-releases.json \
  UPDATE_PUBLIC_KEY=config/releases/appliance-release-public.pem
```

See [production releases](RELEASING.md) for signing and publication controls.

The builder downloads and caches the pinned Ubuntu 26.04.1 live-server amd64
image, verifies Ubuntu's signed checksum and the ISO checksum, then embeds only
the files in the clean, committed Git tree. Staged or modified tracked files make
a production build fail; untracked files are not archive inputs. A generated
`build-metadata.json` binds the semantic appliance version, positive 63-bit release
sequence, source commit, source tree and a SHA-256 source identity. `VERSION`
contains only the supplied semantic version; version, sequence and commit appear
in the ISO filename. The sequence establishes the accepted update baseline and
must increase for each subsequently signed appliance release. The builder then
adds deliberately selected configuration inputs and recreates the hybrid BIOS/UEFI
ISO. It does not embed or build Mindflayer server source. `local.mk` may set the
build variables and is ignored. Only an SSH public key is accepted.

`DEV_ALLOW_DIRTY_WORKTREE=1` explicitly selects the old exclusion-filtered
worktree copy for development media. Such artifacts include `-dirty` in their
filename and record `development-worktree` as their input mode. This escape hatch
must not be used for production releases. `DEV_ALLOW_NO_SSH_KEY=1` remains a
separate test-only escape hatch.

The base installer is self-contained and does not clone this repository. Internet access is required during target provisioning for Ubuntu/Docker/Chrome packages and public runtime container pulls. Foundry also downloads its runtime after an owner supplies supported credentials or a timed URL. A registry or package failure leaves `elderbrain-stack.service` failed/retrying with diagnostics in `journalctl -u elderbrain-stack`; it is never reported healthy.

Set `ISO_OUT_DIR` to a separate output directory to preserve an earlier ISO or
avoid filling the workspace disk. It defaults to `out/`; the verified Ubuntu
download cache remains in `cache/`. Test media containing the disposable QEMU SSH
public key must not be used for deployment.

The one source of truth for the server image is `MINDFLAYER_SERVER_IMAGE` in `config/defaults/appliance.env`. It currently pins server 0.4.1 with its verified immutable multi-platform manifest digest. To update it, inspect upstream release/publishing metadata, select a compatible semantic tag plus manifest digest (or `edge` plus digest only when no suitable release exists), change that one value, then run the full test suite and fresh-install QEMU test.

Both Setup build stages retain the readable `node:24.16.0-alpine` tag and pin its
OCI index digest. The reviewed index maps linux/amd64 to
`sha256:bc23e6976e92708e9eadae437d7dd180b3fd47ed75edf322d6cfa36eba4a7fc8`;
production release builds explicitly select linux/amd64. Dependabot monitors the
Dockerfile, but a proposed tag or digest change still requires manifest/platform
review and the complete Setup image tests.

Before adopting a server image, pull its exact digest and run the opt-in
published-image installation check:

```sh
ELDERBRAIN_TEST_SERVER_IMAGE='mindflayervtt/server:VERSION@sha256:DIGEST' \
  python3 -m unittest discover -s test -p 'test_server_image.py' -v
```

This creates a disposable container with no host mounts, exposed ports or
external network access. It exercises the shipped capability, preparation,
registration and online-verification commands against a simulated authenticated
v3 keypad. The container and its anonymous data volume are removed afterward.
This catches packaging and CLI integration errors but does not replace physical
USB flashing or the full appliance VM check. The image must already be pulled;
the test refuses mutable tags without a digest.
# Default recovery email server

Copy `config/defaults/smtp.example.json` to `config/private/smtp.json` and fill in
your SMTP server, port, TLS mode, sender and optional credentials. The private
directory is Git-ignored and excluded from the ISO unless explicitly selected:

```sh
make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 \
  SSH_PUBLIC_KEY="$HOME/.ssh/g749-servers.pub" \
  SMTP_CONFIG=config/private/smtp.json
```

You can instead set `SMTP_CONFIG` in the ignored `local.mk`. There is no built-in
provider. Omitting the file requires custom SMTP settings during onboarding.
`secure: true` means immediate TLS (typically port 465); false requires STARTTLS.
The installer stores the selected settings as mode 0600 in
`/var/lib/mindflayer-elderbrain/elderbrain/secrets/default-smtp.json`, included in
configuration backups. Existing installed defaults are preserved on reprovisioning.
The UI exposes only availability, not default server credentials. Custom SMTP
remains optional when defaults exist; email verification is still mandatory.

Anyone with the ISO can extract included credentials, regardless of file modes.
Use a dedicated, restricted sending account and treat the ISO and backups as
sensitive. Do not distribute them publicly.

Production payloads come from `git archive` of the exact recorded commit. The
selected `SMTP_CONFIG`, update trust files and `SSH_PUBLIC_KEY` are added explicitly
afterward. `iso/payload.exclude` applies only to the opt-in dirty development mode;
its exclusions remain tested but are not treated as a production allowlist or a
general-purpose secret scanner.
