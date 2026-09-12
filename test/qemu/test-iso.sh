#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
ssh_port=${QEMU_SSH_PORT:-2222}
vnc_display=${QEMU_VNC_DISPLAY:-0}
[[ $ssh_port =~ ^[0-9]{1,5}$ && $vnc_display =~ ^[0-9]{1,2}$ ]] || { echo 'Invalid QEMU port/display' >&2; exit 2; }
[[ ${QEMU_STORAGE_PROMPTS_AUTOMATED:-0} =~ ^[01]$ ]] || { echo 'QEMU_STORAGE_PROMPTS_AUTOMATED must be 0 or 1' >&2; exit 2; }
((10#$ssh_port >= 1024 && 10#$ssh_port <= 65535)) || { echo 'SSH port must be 1024..65535' >&2; exit 2; }
ssh_port=$((10#$ssh_port)); vnc_display=$((10#$vnc_display))
for command in qemu-system-x86_64 qemu-img ssh ssh-keygen nc; do command -v "$command" >/dev/null || { echo "missing QEMU test dependency: $command" >&2; exit 2; }; done
test_state="$ROOT/test/.qemu"; mkdir -p "$test_state"
work_base=${QEMU_WORK_ROOT:-$test_state}
mkdir -p "$work_base"
work=$(mktemp -d "$work_base/run.XXXXXX")
if [[ -n ${QEMU_SSH_PRIVATE_KEY:-} ]]; then
  key=$QEMU_SSH_PRIVATE_KEY
  [[ -f $key && -f $key.pub ]] || { echo 'Supplied SSH key pair is missing' >&2; exit 2; }
else
  key="$test_state/id_ed25519"; [[ -f $key ]] || ssh-keygen -q -t ed25519 -N '' -f "$key"
fi
if [[ -n ${ISO:-} ]]; then
  iso=$ISO
else
  iso=$(make -s -C "$ROOT" iso APPLIANCE_VERSION="${APPLIANCE_VERSION:-1.0.0}" \
    APPLIANCE_RELEASE_SEQUENCE="${APPLIANCE_RELEASE_SEQUENCE:-1}" SSH_PUBLIC_KEY="$key.pub" | tail -1)
fi
[[ -f $iso ]] || { echo "ISO not found: $iso" >&2; exit 2; }
disk_work=$work
if [[ -n ${QEMU_DISK_ROOT:-} ]]; then
  [[ -d $QEMU_DISK_ROOT ]] || { echo 'QEMU_DISK_ROOT must already exist' >&2; exit 2; }
  disk_work=$(mktemp -d "$QEMU_DISK_ROOT/elderbrain-disk.XXXXXXXX")
fi
disk="$disk_work/disk.qcow2"; qemu-img create -f qcow2 "$disk" 96G
echo "Disposable disk: $disk"
accel=(-accel tcg); [[ -r /dev/kvm && -w /dev/kvm ]] && accel=(-enable-kvm)
monitor="$work/monitor.sock"
cleanup() {
  if [[ ${KEEP_VM:-0} == 1 ]]; then
    echo "VM retained for diagnostics: $work"
    return
  fi
  if [[ -v ssh_cmd ]] && "${ssh_cmd[@]}" 'sync; systemctl poweroff' >/dev/null 2>&1; then
    for attempt in $(seq 1 20); do [[ -S $monitor ]] || return; sleep 1; done
  fi
  if [[ -S $monitor ]]; then printf 'quit\n' | nc -q 0 -U "$monitor" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
echo 'Starting QEMU; the test explicitly selects the second, destructive Elderbrain boot entry.'
echo 'At the storage console choose fresh, serial elderbrain-vm-test, then ERASE elderbrain-vm-test. This applies only to the newly created disposable disk above.'
qemu-system-x86_64 "${accel[@]}" -m 4096 -smp 2 -drive "file=$disk,if=none,id=appliance-disk" -device virtio-blk-pci,drive=appliance-disk,serial=elderbrain-vm-test -cdrom "$iso" -boot once=d \
  -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$ssh_port-:22" -vnc "127.0.0.1:$vnc_display" -monitor "unix:$monitor,server,nowait" -daemonize -pidfile "$work/qemu.pid"
for attempt in $(seq 1 20); do [[ -S $monitor ]] && break; sleep 0.25; done
sleep 15
printf 'sendkey down\nsendkey ret\n' | nc -q 0 -U "$monitor" >/dev/null
if [[ ${QEMU_STORAGE_PROMPTS_AUTOMATED:-0} != 1 ]]; then
  printf '%s\n' 'Complete the fresh/preserve, exact serial and final confirmation prompts in the VM console.'
  printf '%s' 'Press Enter here only after submitting the final storage confirmation: '
  read -r
fi
ready=0
for attempt in $(seq 1 180); do
  if ssh -i "$key" -p "$ssh_port" -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o ConnectTimeout=3 root@127.0.0.1 'test -f /opt/mindflayer-elderbrain/VERSION && test -f /etc/elderbrain/storage.json' 2>/dev/null; then
    ready=1
    break
  fi
  sleep 10
done
((ready == 1)) || { echo 'Installed appliance did not become SSH-ready within 30 minutes after storage confirmation' >&2; exit 1; }
ssh_cmd=(ssh -i "$key" -p "$ssh_port" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@127.0.0.1)
"${ssh_cmd[@]}" 'bash -s' < "$ROOT/test/qemu/guest-checks.sh"
"${ssh_cmd[@]}" 'python3 -' < "$ROOT/test/qemu/guest-storage.py"
"${ssh_cmd[@]}" 'python3 -' < "$ROOT/test/qemu/guest-https.py"
"${ssh_cmd[@]}" 'python3 -' < "$ROOT/test/qemu/guest-admin-ui.py"
if ssh -p "$ssh_port" -o BatchMode=yes -o ConnectTimeout=5 -o PreferredAuthentications=password -o PubkeyAuthentication=no -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@127.0.0.1 true 2>/dev/null; then echo 'password SSH unexpectedly succeeded' >&2; exit 1; fi
echo 'QEMU appliance checks passed'
echo "Retained disposable VM artifacts: $work"
