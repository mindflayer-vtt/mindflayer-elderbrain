"""Host-side disposable VM offline reboot test; restores its link in finally."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time
import uuid


def monitor(path, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        connection.connect(str(path))
        connection.sendall((command + '\n').encode())
        result = bytearray()
        while True:
            try:
                chunk = connection.recv(8192)
            except TimeoutError:
                break
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > 65536:
                raise ValueError('Unexpected monitor output')
        value = result.decode()
        if 'Error' in value or 'not found' in value:
            raise ValueError('Monitor command failed')
        return value


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--monitor', type=Path, required=True)
parser.add_argument('--identity', type=Path, required=True)
parser.add_argument('--known-hosts', type=Path, required=True)
args = parser.parse_args()
ssh = ['ssh', '-i', str(args.identity), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
       '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(args.known_hosts),
       '-o', 'ConnectTimeout=5', '-p', '2232', 'root@127.0.0.1']
check = subprocess.check_output([*ssh, 'cat /sys/class/dmi/id/product_name; lsblk -dn -o SERIAL /dev/vda'], text=True)
assert check.startswith('Standard PC') and check.splitlines()[-1] == 'elderbrain-vm-test'
assert 'virtio-net-pci.0:' in monitor(args.monitor, 'info network')
timer = 'elderbrain-offline-test-' + uuid.uuid4().hex
subprocess.run([*ssh, 'systemd-run --unit=' + timer + ' --on-active=5s /usr/bin/systemctl reboot'], check=True)
try:
    monitor(args.monitor, 'set_link virtio-net-pci.0 off')
    print(json.dumps({'phase': 'link-disconnected', 'epoch': time.time()}), flush=True)
    for elapsed in range(30, 211, 30):
        time.sleep(30)
        assert 'running' in monitor(args.monitor, 'info status')
        print(json.dumps({'phase': 'offline-vm-running', 'elapsedSeconds': elapsed}), flush=True)
finally:
    monitor(args.monitor, 'set_link virtio-net-pci.0 on')
    print(json.dumps({'phase': 'link-restored', 'epoch': time.time()}), flush=True)
