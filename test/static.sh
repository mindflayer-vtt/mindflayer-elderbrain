#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
bash -n "$root/iso/select-storage.sh"
bash -n "$root/test/qemu/preserve-baseline.sh"
bash -n "$root/test/qemu/offline-dependencies.sh"
# These are source files, not a Python virtual environment. A generic lib/
# ignore rule must never silently omit the privileged host implementation.
while IFS= read -r -d '' source; do
  if git -C "$root" check-ignore -q --no-index "$source"; then
    echo "Required host source is ignored by Git: $source" >&2
    exit 1
  fi
done < <(find "$root/appliance/lib" -maxdepth 1 -type f \( -name '*.py' -o -name 'management-server' \) -print0)
for script in "$root/iso/build.sh" "$root/provisioning/install.sh" "$root/provisioning/graphics/browser-launcher" "$root/provisioning/graphics/wait-ready" "$root/appliance/bin/elderbrain"; do bash -n "$script"; done
python3 -m py_compile "$root/provisioning/graphics/browser-session.py"
python3 -m py_compile "$root/provisioning/graphics/prepare-browser.py" "$root/test/qemu/browser-modes.py"
python3 -m py_compile "$root/appliance/lib/management-server"
python3 -m py_compile "$root/appliance/lib/host_bindings.py"
python3 -m py_compile "$root/test/qemu/storage-bindings.py"
python3 -m py_compile "$root/test/qemu/storage-inspection.py" "$root/test/qemu/foundry-volume.py"
python3 -m py_compile "$root/test/qemu/guest-storage.py" "$root/iso/storage_console.py"
python3 -m py_compile "$root/provisioning/storage_initialize.py"
python3 -m py_compile "$root/provisioning/host_persistence.py"
python3 -m py_compile "$root/provisioning/runtime_settings.py"
python3 -m py_compile "$root/iso/storage_plan.py" "$root/iso/storage_probe.py" "$root/iso/storage_existing.py" "$root/iso/storage_prepare.py" "$root/iso/storage_select.py" "$root/appliance/lib/storage_guard.py"
bash -n "$root/provisioning/prepare-admin" "$root/test/qemu/test-iso.sh" "$root/test/qemu/guest-checks.sh"
python3 -m py_compile "$root/test/qemu/guest-https.py"
python3 -m py_compile "$root/test/qemu/network-recovery.py"
python3 -m py_compile "$root/test/qemu/network-checkpoint-restore.py"
python3 -m py_compile "$root/test/qemu/network-transition.py"
python3 -m py_compile "$root/test/qemu/network-confirmation.py"
python3 -m py_compile "$root/test/qemu/admin-tls.py"
python3 -m py_compile "$root/test/qemu/network-external.py"
grep -q 'Install Mindflayer Elderbrain' "$root/iso/boot/elderbrain-grub.cfg"
grep -q 'authorized-keys' "$root/iso/build.sh"
image=$(sed -n 's/^MINDFLAYER_SERVER_IMAGE=//p' "$root/config/defaults/appliance.env")
[[ $image == mindflayervtt/server:0.4.1@sha256:* ]]
[[ $image != *:latest* ]]
[[ $image =~ @sha256:[0-9a-f]{64}$ ]]
[[ $(rg -l 'mindflayervtt/server(:|@)' "$root" --glob '!config/defaults/appliance.env' --glob '!docs/**' --glob '!test/static.sh' --glob '!test/test_server_image.py' --glob '!out/**' --glob '!cache/**' | wc -l) -eq 0 ]]
! find "$root" -path "$root/vendor/mindflayer-server-*" -print -quit | grep -q .
! rg -n --glob '!test/static.sh' --glob '!docs/**' --glob '!out/**' --glob '!cache/**' 'MINDFLAYER_(ARCHIVE|SHA256|COMMIT|CONTEXT)|vendor/source|UPSTREAM_COMMIT' "$root"
grep -q 'image: ${MINDFLAYER_SERVER_IMAGE:' "$root/compose/compose.yaml"
! grep -A3 '^  mindflayer-server:' "$root/compose/compose.yaml" | grep -q 'build:'
grep -q -- '--providers.file.directory=' "$root/compose/compose.yaml"
! grep -q -- '--providers.docker' "$root/compose/compose.yaml"
! grep -q '/var/run/docker.sock' "$root/compose/compose.yaml"
! grep -q 'traefik.http' "$root/compose/compose.yaml"
! grep -q '/traefik:/etc/traefik/dynamic' "$root/compose/compose.yaml"
! grep -q 'ca.key:/etc/traefik' "$root/compose/compose.yaml"
grep -q 'host/admin-ca' "$root/provisioning/prepare-admin"
! grep -q -- '-keyout "$tls/ca.key"' "$root/provisioning/prepare-admin"
! grep -q -- '-CAkey "$tls/ca.key"' "$root/provisioning/prepare-admin"
grep -q 'pull --ignore-buildable' "$root/provisioning/systemd/elderbrain-stack.service"
grep -q 'up -d --no-build.*--wait' "$root/provisioning/systemd/elderbrain-stack.service"
! rg -n --glob '!test/static.sh' 'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|FOUNDRY_PASSWORD=.+' "$root"
published=$(awk '/^[[:space:]]+ports:/{ports=1;next} ports && /^[[:space:]]+- "/{print} ports && !/^[[:space:]]+- /{ports=0}' "$root/compose/compose.yaml")
grep -q '80}:80' <<<"$published"; grep -q '443}:443' <<<"$published"; grep -q '10443}:10443' <<<"$published"
! grep -Eq '30000:30000|8080:8080' <<<"$published"
echo 'static checks passed'
