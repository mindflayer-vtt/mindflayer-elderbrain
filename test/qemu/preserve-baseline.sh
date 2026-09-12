#!/bin/bash
# Capture evidence outside the guest and /tmp before an explicit OS reinstall.
set -euo pipefail
umask 077
root=$(cd "$(dirname "$0")/../.." && pwd)
operation=${1:-}
run=${2:-}
[[ $run == /* ]] || { echo 'Run directory must be absolute.' >&2; exit 2; }
run=$(realpath -m -- "$run")
[[ $operation == seed || $operation == verify ]] || { echo 'Usage: bash test/qemu/preserve-baseline.sh seed|verify RUN_DIRECTORY' >&2; exit 2; }
[[ $run == /* && $run != /tmp && $run != /tmp/* && $run != /var/tmp && $run != /var/tmp/* ]] || { echo 'Use an absolute persistent host directory, e.g. test/.qemu/preserve-RUN (expanded to its full path).' >&2; exit 2; }
port=${QEMU_SSH_PORT:-2232}
[[ $port =~ ^[0-9]{4,5}$ ]] && ((10#$port >= 1024 && 10#$port <= 65535)) || { echo 'Invalid VM SSH port' >&2; exit 2; }
key=${QEMU_SSH_PRIVATE_KEY:-$root/test/.qemu/id_ed25519}
[[ -f $key ]] || { echo 'Set QEMU_SSH_PRIVATE_KEY to the VM key.' >&2; exit 2; }
if [[ $operation == seed ]]; then
  mkdir -m 0700 "$run" # exclusive: never replace an earlier baseline
else
  [[ -d $run && ! -L $run && -f $run/baseline.json ]] || { echo 'Saved baseline not found.' >&2; exit 2; }
fi
ssh_args=(-i "$key" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$run/known_hosts")
remote=(ssh "${ssh_args[@]}" -p "$port" root@127.0.0.1)
guest=$("${remote[@]}" 'mktemp -d /root/elderbrain-preserve-test-XXXXXXXX')
[[ $guest =~ ^/root/elderbrain-preserve-test-[A-Za-z0-9]{8}$ ]] || { echo 'Invalid guest test directory.' >&2; exit 2; }
if [[ $operation == seed ]]; then
  "${remote[@]}" "python3 - seed $guest/baseline.json" < "$root/test/qemu/storage-preserve.py"
  scp "${ssh_args[@]}" -p -P "$port" "root@127.0.0.1:$guest/baseline.json" "$run/baseline.json"
  chmod 0600 "$run/baseline.json"
  (cd "$run" && sha256sum baseline.json > baseline.sha256)
  sync -f "$run/baseline.json"
  sync -f "$run"
  echo "Baseline retained at $run. Reinstall must be started separately."
else
  (cd "$run" && sha256sum --check baseline.sha256)
  scp "${ssh_args[@]}" -p -P "$port" "$run/baseline.json" "root@127.0.0.1:$guest/baseline.json"
  "${remote[@]}" "python3 - verify $guest/baseline.json" < "$root/test/qemu/storage-preserve.py"
fi
