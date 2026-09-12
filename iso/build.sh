#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
UBUNTU_VERSION=${UBUNTU_VERSION:-26.04.1}
ISO_NAME="ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"
BASE_URL=${UBUNTU_BASE_URL:-https://releases.ubuntu.com/${UBUNTU_VERSION}}
CACHE="$ROOT/cache"; OUT=${ISO_OUT_DIR:-"$ROOT/out"}; WORK=$(mktemp -d)
trap 'chmod -R u+w "$WORK" 2>/dev/null || true; rm -rf "$WORK"' EXIT
for command in curl git gpg xorriso rsync tar unsquashfs sha256sum; do command -v "$command" >/dev/null || { echo "missing build dependency: $command" >&2; exit 2; }; done
version=${APPLIANCE_VERSION:-}
[[ $version =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || { echo 'APPLIANCE_VERSION must be a stable semantic version' >&2; exit 2; }
key=${SSH_PUBLIC_KEY:-}
if [[ -n ${UPDATE_SOURCE_CONFIG:-} || -n ${UPDATE_PUBLIC_KEY:-} ]]; then
  [[ -n ${UPDATE_SOURCE_CONFIG:-} && -n ${UPDATE_PUBLIC_KEY:-} ]] || { echo 'UPDATE_SOURCE_CONFIG and UPDATE_PUBLIC_KEY must be supplied together' >&2; exit 2; }
  python3 "$ROOT/iso/validate-release.py" "$UPDATE_SOURCE_CONFIG" "$UPDATE_PUBLIC_KEY"
fi
if [[ -n ${SMTP_CONFIG:-} ]]; then
  python3 "$ROOT/iso/validate-smtp.py" "$SMTP_CONFIG"
fi
if [[ -n $key ]]; then [[ -f $key ]] || { echo "SSH public key not found: $key" >&2; exit 2; }; grep -Eq '^ssh-(ed25519|rsa|ecdsa-sha2-)' "$key" || { echo 'SSH_PUBLIC_KEY is not a recognized public key' >&2; exit 2; }
elif [[ ${DEV_ALLOW_NO_SSH_KEY:-} != 1 ]]; then echo 'SSH_PUBLIC_KEY is required (or DEV_ALLOW_NO_SSH_KEY=1 for development only)' >&2; exit 2; fi
mkdir -p "$CACHE" "$OUT" "$WORK/tree"
if [[ ! -f "$CACHE/$ISO_NAME" ]]; then
  curl -fL --retry 3 -C - -o "$CACHE/$ISO_NAME.part" "$BASE_URL/$ISO_NAME"
  mv "$CACHE/$ISO_NAME.part" "$CACHE/$ISO_NAME"
fi
curl -fL --retry 3 -o "$WORK/SHA256SUMS" "$BASE_URL/SHA256SUMS"
curl -fL --retry 3 -o "$WORK/SHA256SUMS.gpg" "$BASE_URL/SHA256SUMS.gpg"
gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys 0xD94AA3F0EFE21092 >/dev/null 2>&1 || true
gpg --batch --verify "$WORK/SHA256SUMS.gpg" "$WORK/SHA256SUMS"
(cd "$CACHE" && grep -E "[ *]${ISO_NAME}$" "$WORK/SHA256SUMS" | sed 's/ \*/  /' | sha256sum -c -)
xorriso -osirrox on -indev "$CACHE/$ISO_NAME" -extract / "$WORK/tree" >/dev/null 2>&1
chmod -R u+w "$WORK/tree"
mkdir -p "$WORK/tree/elderbrain"
commit=$(git -C "$ROOT" rev-parse --verify 'HEAD^{commit}')
if [[ ${DEV_ALLOW_DIRTY_WORKTREE:-0} == 1 ]]; then
  rsync -a --exclude-from="$ROOT/iso/payload.exclude" "$ROOT/" "$WORK/tree/elderbrain/"
  tree=$(git -C "$ROOT" rev-parse --verify 'HEAD^{tree}')
  python3 - "$WORK/tree/elderbrain" "$version" "$commit" "$tree" <<'PY'
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('tracked_payload', root / 'iso/tracked-payload.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.metadata(root, sys.argv[2], sys.argv[3], sys.argv[4], development=True)
PY
  suffix=-dirty
else
  python3 "$ROOT/iso/tracked-payload.py" "$ROOT" "$WORK/tree/elderbrain" "$version"
  suffix=
fi
if [[ -n ${UPDATE_SOURCE_CONFIG:-} ]]; then
  install -d -m 0700 "$WORK/tree/elderbrain/config/private"
  install -m 0644 "$UPDATE_SOURCE_CONFIG" "$WORK/tree/elderbrain/config/private/release-source.json"
  install -m 0644 "$UPDATE_PUBLIC_KEY" "$WORK/tree/elderbrain/config/private/release-public.pem"
fi
if [[ -n ${SMTP_CONFIG:-} ]]; then
  install -d -m 0700 "$WORK/tree/elderbrain/config/private"
  install -m 0600 "$SMTP_CONFIG" "$WORK/tree/elderbrain/config/private/smtp.json"
fi
cp "$ROOT/iso/autoinstall/user-data.in" "$WORK/tree/user-data"
printf 'instance-id: elderbrain-%s-%s%s\nlocal-hostname: elderbrain\n' "$version" "${commit:0:12}" "$suffix" > "$WORK/tree/meta-data"
if [[ -n $key ]]; then
  cp "$key" "$WORK/tree/elderbrain/root-authorized-key"
  awk -v key="$(<"$key")" '/  ssh:/{print "  authorized-keys:\n    - " key} {print}' "$WORK/tree/user-data" > "$WORK/user-data"; mv "$WORK/user-data" "$WORK/tree/user-data"
else
  : > "$WORK/tree/elderbrain/root-authorized-key"
fi
for cfg in "$WORK/tree/boot/grub/grub.cfg" "$WORK/tree/boot/grub/loopback.cfg"; do
  [[ -f $cfg ]] || continue
  awk -v snippet="$ROOT/iso/boot/elderbrain-grub.cfg" '
    /^grub_platform$/ && !inserted { while ((getline line < snippet) > 0) print line; close(snippet); inserted=1 }
    { print }
    END { if (!inserted) { while ((getline line < snippet) > 0) print line; close(snippet) } }
  ' "$cfg" > "$WORK/grub.cfg"
  mv "$WORK/grub.cfg" "$cfg"
done
xorriso -as mkisofs -r -V 'MINDFLAYER' -o "$OUT/mindflayer-elderbrain-${version}-${commit:0:12}${suffix}.iso" \
  --grub2-mbr "--interval:local_fs:0s-15s:zero_mbrpt,zero_gpt:$CACHE/$ISO_NAME" \
  --protective-msdos-label -partition_cyl_align off -partition_offset 16 \
  --mbr-force-bootable -append_partition 2 28732ac11ff8d211ba4b00a0c93ec93b \
  "--interval:local_fs:5707520d-5717815d::$CACHE/$ISO_NAME" \
  -appended_part_as_gpt -iso_mbr_part_type a2a0d0ebe5b9334487c068b6b72699c7 \
  -c '/boot.catalog' -b '/boot/grub/i386-pc/eltorito.img' -no-emul-boot -boot-load-size 4 -boot-info-table \
  --grub2-boot-info -eltorito-alt-boot -e '--interval:appended_partition_2_start_1426880s_size_10296d:all::' -no-emul-boot "$WORK/tree"
echo "$OUT/mindflayer-elderbrain-${version}-${commit:0:12}${suffix}.iso"
