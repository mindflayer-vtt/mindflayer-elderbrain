#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/elderbrain-provisioning.log) 2>&1
[[ $EUID -eq 0 ]] || { echo 'provisioning must run as root' >&2; exit 1; }
PAYLOAD_DIR=${PAYLOAD_DIR:-/opt/elderbrain-payload}
RUNTIME=/opt/mindflayer-elderbrain
STATE=/var/lib/mindflayer-elderbrain
MANAGEMENT_GROUP=elderbrain-management
MANAGEMENT_GID=31338
export DEBIAN_FRONTEND=noninteractive
python3 "$PAYLOAD_DIR/provisioning/compat/retire-legacy-browser.py" check

management_group_entry=$(getent group "$MANAGEMENT_GROUP" || true)
management_gid_entry=$(getent group "$MANAGEMENT_GID" || true)
if [[ -n $management_group_entry ]]; then
  [[ ${management_group_entry%%:*} == "$MANAGEMENT_GROUP" && $(cut -d: -f3 <<<"$management_group_entry") == "$MANAGEMENT_GID" ]] || {
    echo "$MANAGEMENT_GROUP must use reserved GID $MANAGEMENT_GID" >&2
    exit 1
  }
elif [[ -n $management_gid_entry ]]; then
  echo "reserved management GID $MANAGEMENT_GID is already assigned" >&2
  exit 1
else
  groupadd --system --gid "$MANAGEMENT_GID" "$MANAGEMENT_GROUP"
fi

if [[ -n ${ELDERBRAIN_STORAGE_RECEIPT:-} ]]; then
  (cd "$PAYLOAD_DIR" && python3 -m provisioning.storage_initialize --receipt "$ELDERBRAIN_STORAGE_RECEIPT")
fi
# Legacy live upgrades keep their existing layout until explicitly migrated.
# Once a persistent identity exists, missing/wrong storage is always fatal,
# before creating directories or allowing Docker's automatic restarts.
if [[ -e /etc/elderbrain/storage.json || -L /etc/elderbrain/storage.json ]]; then
  python3 "$PAYLOAD_DIR/appliance/lib/storage_guard.py"
  install -d -m 0755 "$RUNTIME"
  install -m 0644 "$PAYLOAD_DIR/appliance/lib/storage_guard.py" "$RUNTIME/storage_guard.py"
  for storage_writer in docker elderbrain-stack elderbrain-management elderbrain-graphics elderbrain-admin-console elderbrain-backup elderbrain-backup-retry elderbrain-display-watchdog elderbrain-network-recovery elderbrain-network-watchdog elderbrain-network-confirmation; do
    install -d -m 0755 "/etc/systemd/system/$storage_writer.service.d"
    install -m 0644 "$PAYLOAD_DIR/provisioning/systemd/storage-required.conf" "/etc/systemd/system/$storage_writer.service.d/10-storage-required.conf"
  done
  install -m 0644 "$PAYLOAD_DIR/provisioning/systemd/persistent-netplan.conf" /etc/systemd/system/elderbrain-network-recovery.service.d/20-persistent-netplan.conf
fi

install -d -m 0755 "$RUNTIME" "$STATE"/{foundry,elderbrain,mindflayer,firmware,traefik,backups,browser}
install -d -m 0700 "$STATE/elderbrain/secrets"
install -d -m 0700 "$STATE/keypad-installations"
python3 "$PAYLOAD_DIR/provisioning/initialize-default.py" "$STATE/elderbrain/secrets/foundry-config.json" --empty-json
apt-get update
apt-get install -y ca-certificates curl gnupg openssh-server python3 python3-venv python3-yaml jq ufw unattended-upgrades openssl libnss3-tools zstd borgbackup nfs-common
python3 -m venv "$RUNTIME/borgmatic-venv"
"$RUNTIME/borgmatic-venv/bin/pip" install -r "$PAYLOAD_DIR/config/defaults/borgmatic-requirements.txt"
python3 -m venv "$RUNTIME/serial-venv"
"$RUNTIME/serial-venv/bin/pip" install -r "$PAYLOAD_DIR/config/defaults/serial-requirements.txt"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub -o /tmp/google-linux-signing-key.pub
gpg --batch --yes --dearmor -o /etc/apt/keyrings/google-chrome.gpg /tmp/google-linux-signing-key.pub
echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main' > /etc/apt/sources.list.d/google-chrome.list
apt-get update
apt-get install -y sway google-chrome-stable
apt-get install -y nodejs npm
node -e 'if (Number(process.versions.node.split(".")[0]) < 20) process.exit(1)'
install -d -m 0755 "$RUNTIME/beamer"
install -m 0644 "$PAYLOAD_DIR/provisioning/graphics/"{package.json,package-lock.json,beamer-worker.mjs,beamer-login.mjs} "$RUNTIME/beamer/"
npm ci --prefix "$RUNTIME/beamer" --ignore-scripts --omit=dev --no-audit --no-fund
install -d -m 0755 /etc/opt/chrome/policies/managed
install -m 0644 "$PAYLOAD_DIR/provisioning/chrome/elderbrain.json" /etc/opt/chrome/policies/managed/elderbrain.json
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
arch=$(dpkg --print-architecture)
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

cp "$PAYLOAD_DIR/compose/compose.yaml" "$RUNTIME/compose.yaml"
cp -a "$PAYLOAD_DIR/setup" "$RUNTIME/setup"
if [[ -f /etc/elderbrain/storage.json ]]; then
  runtime_settings_args=(--payload "$PAYLOAD_DIR")
  if [[ -n ${ELDERBRAIN_STORAGE_RECEIPT:-} ]]; then runtime_settings_args+=(--receipt "$ELDERBRAIN_STORAGE_RECEIPT"); fi
  (cd "$PAYLOAD_DIR" && python3 -m provisioning.runtime_settings "${runtime_settings_args[@]}")
else
  python3 "$PAYLOAD_DIR/provisioning/initialize-default.py" "$RUNTIME/appliance.env" "$PAYLOAD_DIR/config/defaults/appliance.env"
fi
cp "$PAYLOAD_DIR/VERSION" "$RUNTIME/VERSION"
if [[ -f "$PAYLOAD_DIR/config/private/smtp.json" && ! -e "$STATE/elderbrain/secrets/default-smtp.json" ]]; then
  install -d -m 0700 -o 1000 -g 1000 "$STATE/elderbrain/secrets"
  install -m 0600 -o 1000 -g 1000 "$PAYLOAD_DIR/config/private/smtp.json" "$STATE/elderbrain/secrets/default-smtp.json"
fi
install -m 0755 "$PAYLOAD_DIR/provisioning/prepare-admin" "$RUNTIME/prepare-admin"
install -m 0644 "$PAYLOAD_DIR/provisioning/admin-console.py" "$RUNTIME/admin-console.py"
install -m 0644 "$PAYLOAD_DIR/provisioning/generate-admin-password.py" "$RUNTIME/generate-admin-password.py"
install -m 0644 "$PAYLOAD_DIR/setup/shared/bootstrap-words.json" "$RUNTIME/bootstrap-words.json"
python3 "$PAYLOAD_DIR/provisioning/initialize-default.py" "$STATE/traefik/admin-tls.yaml" "$PAYLOAD_DIR/config/defaults/admin-tls.yaml"
cp "$PAYLOAD_DIR/appliance/lib/management-server" "$RUNTIME/management-server"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/release_interlocks.py" "$RUNTIME/release_interlocks.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/host_metrics.py" "$RUNTIME/host_metrics.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/beamer_runtime.py" "$RUNTIME/beamer_runtime.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/host_network.py" "$RUNTIME/host_network.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_config.py" "$RUNTIME/network_config.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_sources.py" "$RUNTIME/network_sources.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_transaction.py" "$RUNTIME/network_transaction.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_staging.py" "$RUNTIME/network_staging.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_worker.py" "$RUNTIME/network_worker.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_confirmation.py" "$RUNTIME/network_confirmation.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_https.py" "$RUNTIME/network_https.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_tls.py" "$RUNTIME/network_tls.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_listener.py" "$RUNTIME/network_listener.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_service.py" "$RUNTIME/network_service.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/admin_tls.py" "$RUNTIME/admin_tls.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/host_displays.py" "$RUNTIME/host_displays.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/display_preview.py" "$RUNTIME/display_preview.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/domain_routes.py" "$RUNTIME/domain_routes.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/kiosk_keyboard.py" "$RUNTIME/kiosk_keyboard.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/backup_archive.py" "$RUNTIME/backup_archive.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/backup_crypto.py" "$RUNTIME/backup_crypto.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/backup_service.py" "$RUNTIME/backup_service.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/backup_pending.py" "$RUNTIME/backup_pending.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/restore_transaction.py" "$RUNTIME/restore_transaction.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/restore_service.py" "$RUNTIME/restore_service.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/host_bindings.py" "$RUNTIME/host_bindings.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/storage_guard.py" "$RUNTIME/storage_guard.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/host_jobs.py" "$RUNTIME/host_jobs.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/power_service.py" "$RUNTIME/power_service.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/appliance_release.py" "$RUNTIME/appliance_release.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/update_request.py" "$RUNTIME/update_request.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/release_catalog.py" "$RUNTIME/release_catalog.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/local_snapshots.py" "$RUNTIME/local_snapshots.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/checkpoint_compatibility.py" "$RUNTIME/checkpoint_compatibility.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/checkpoint_components.py" "$RUNTIME/checkpoint_components.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/checkpoint_staging.py" "$RUNTIME/checkpoint_staging.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/checkpoint_restore.py" "$RUNTIME/checkpoint_restore.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/network_checkpoint_restore.py" "$RUNTIME/network_checkpoint_restore.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/snapshot_service.py" "$RUNTIME/snapshot_service.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/keypad_inventory.py" "$RUNTIME/keypad_inventory.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/serial_bundle.py" "$RUNTIME/serial_bundle.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/serial_release.py" "$RUNTIME/serial_release.py"
install -m 0644 "$PAYLOAD_DIR/config/defaults/firmware-signing-public.pem" "$RUNTIME/firmware-signing-public.pem"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/serial_install.py" "$RUNTIME/serial_install.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/installation_job.py" "$RUNTIME/installation_job.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/installation_server.py" "$RUNTIME/installation_server.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/installation_backend.py" "$RUNTIME/installation_backend.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/serial_provision.py" "$RUNTIME/serial_provision.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/esptool-runner.py" "$RUNTIME/esptool-runner.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/backup_uploads.py" "$RUNTIME/backup_uploads.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/borg_settings.py" "$RUNTIME/borg_settings.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/borg_repository.py" "$RUNTIME/borg_repository.py"
install -m 0644 "$PAYLOAD_DIR/appliance/lib/borg_service.py" "$RUNTIME/borg_service.py"
cp "$PAYLOAD_DIR/provisioning/graphics/browser-launcher" "$RUNTIME/browser-launcher"
install -m 0644 "$PAYLOAD_DIR/provisioning/graphics/browser-session.py" "$RUNTIME/browser-session.py"
install -m 0644 "$PAYLOAD_DIR/provisioning/graphics/browser_process.py" "$RUNTIME/browser_process.py"
install -m 0644 "$PAYLOAD_DIR/provisioning/graphics/prepare-browser.py" "$RUNTIME/prepare-browser.py"
cp "$PAYLOAD_DIR/provisioning/graphics/wait-ready" "$RUNTIME/wait-ready"
if [[ ! -f /etc/elderbrain/storage.json ]]; then
  cp "$PAYLOAD_DIR/provisioning/graphics/sway.conf" "$RUNTIME/sway.conf"
fi
install -m 0755 "$PAYLOAD_DIR/appliance/bin/elderbrain" /usr/local/sbin/elderbrain
chmod 0755 "$RUNTIME"/{management-server,browser-launcher,wait-ready}
install -m 0644 "$PAYLOAD_DIR/provisioning/ssh/99-elderbrain.conf" /etc/ssh/sshd_config.d/99-elderbrain.conf
sshd -t

id elderbrain-kiosk >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin elderbrain-kiosk
# The installer runs in curtin's chroot: no target logind is available yet.
# Seed the same persistent marker logind reads on boot; live upgrades still
# use loginctl so the user manager is started immediately.
if [[ ${ELDERBRAIN_OFFLINE_INSTALL:-0} == 1 ]] || systemd-detect-virt --chroot --quiet; then
  install -d -m 0755 /var/lib/systemd/linger
  install -m 0644 /dev/null /var/lib/systemd/linger/elderbrain-kiosk
else
  loginctl enable-linger elderbrain-kiosk
fi
chown -R elderbrain-kiosk:elderbrain-kiosk "$STATE/browser"
chown -R 1000:1000 "$STATE/elderbrain"
chown -R 1000:1000 "$STATE/mindflayer"
# Foundry's image runs its volume checks as 1000:1000. The root-created
# directory otherwise stays 0755 root:root and fails its write check.
chown -hR 1000:1000 "$STATE/foundry"
chmod u+rwx "$STATE/foundry"
for service in "$PAYLOAD_DIR/provisioning/systemd/"*.service; do
  [[ ${service##*/} == elderbrain-storage.service ]] && continue
  install -m 0644 "$service" /etc/systemd/system/
done
python3 "$PAYLOAD_DIR/provisioning/compat/retire-legacy-browser.py" retire
for network_service in systemd-networkd NetworkManager; do
  install -d -m 0755 "/etc/systemd/system/$network_service.service.d"
  install -m 0644 "$PAYLOAD_DIR/provisioning/systemd/network-recovery.conf" "/etc/systemd/system/$network_service.service.d/elderbrain-recovery.conf"
done
if [[ -f /etc/elderbrain/storage.json ]]; then
  install -d -m 0755 /etc/cloud/cloud.cfg.d
  install -m 0644 "$PAYLOAD_DIR/provisioning/cloud/99-elderbrain-ssh-identity.cfg" /etc/cloud/cloud.cfg.d/99-elderbrain-ssh-identity.cfg
  host_storage_args=()
  if [[ -n ${ELDERBRAIN_STORAGE_RECEIPT:-} ]]; then host_storage_args+=(--receipt "$ELDERBRAIN_STORAGE_RECEIPT"); fi
  (cd "$PAYLOAD_DIR" && python3 -m provisioning.host_persistence "${host_storage_args[@]}")
  sshd -t
  # The ISO payload is trusted installer code. Publish independent recovery
  # before enabling writers; online releases require separate signature checks.
  python3 -I -B "$PAYLOAD_DIR/provisioning/recovery_bootstrap.py"
  python3 -I -B "$PAYLOAD_DIR/provisioning/update_trust.py"
fi
systemctl daemon-reload
systemctl mask getty@tty2.service autovt@tty2.service
systemctl enable ssh docker elderbrain-management elderbrain-stack elderbrain-graphics elderbrain-admin-console elderbrain-display-watchdog elderbrain-network-recovery elderbrain-network-watchdog elderbrain-network-confirmation elderbrain-backup-retry

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment SSH
ufw allow 80/tcp comment Traefik-HTTP
ufw allow 443/tcp comment Traefik-HTTPS
ufw allow 10443/tcp comment Mindflayer-keypad-TLS
ufw allow 10444/tcp comment Elderbrain-network-confirmation
ufw --force enable

# Docker is intentionally not contacted in the installer chroot. After reboot,
# the stack unit builds only the appliance-owned setup service, pulls all public
# runtime images, and fails visibly if the registry cannot be reached.
