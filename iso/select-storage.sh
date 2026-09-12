#!/bin/bash
set -euo pipefail
cd /cdrom/elderbrain
# Reserve a dedicated console so installer progress cannot consume answers or
# overwrite the destructive-action confirmation. This affects only the live ISO.
systemctl mask --runtime getty@tty3.service autovt@tty3.service
systemctl stop getty@tty3.service
chvt 3
if ! python3 -m iso.storage_select --autoinstall /autoinstall.yaml --receipt /run/elderbrain-storage-receipt.json --console /dev/tty3 2>/dev/tty3; then
  echo 'Storage selection failed or was cancelled; no installation will proceed.' > /dev/tty3
  exit 1
fi
chvt 1
