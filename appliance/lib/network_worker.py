"""Independent rollback worker. No HTTP or permissive confirmation endpoint."""
import os
import signal
import subprocess
import sys
import time

from network_staging import fingerprint, snapshot
from network_transaction import NetworkTransaction


def run_netplan(operation, timeout=30):
    if operation not in ('apply', 'generate'):
        raise ValueError('Unsupported network operation')
    # Discard output: backend errors may contain private Wi-Fi configuration.
    # Kill the entire process group on timeout, not only the netplan parent.
    # Generated backend files must be readable by the systemd-network user.
    # Netplan sets stricter modes itself for credential-bearing artifacts.
    with subprocess.Popen(['netplan', operation], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True, umask=0o022) as process:
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise RuntimeError('Network operation timed out') from None
    if status:
        raise RuntimeError('Network operation failed')


def transaction():
    from network_confirmation import verify
    store = NetworkTransaction('/var/lib/mindflayer-elderbrain/network-transaction',
        '/etc/netplan', apply=lambda: run_netplan('apply'),
        verify_confirmation=lambda proof, _public: verify(proof, store.read()),
        verify_sources=lambda expected: fingerprint(snapshot()) == expected)
    return store


def main():
    if os.geteuid() != 0:
        raise SystemExit('Network worker requires root')
    store = transaction()
    if sys.argv[1:] == ['recover-boot']:
        store.recover_boot(lambda: run_netplan('generate'))
        return
    if sys.argv[1:]:
        raise SystemExit('Unsupported network worker arguments')
    while True:
        try:
            store.tick()
        except Exception:
            # Keep retrying rollback, including after a temporary backend failure.
            print('Network transaction needs recovery; retrying.', file=sys.stderr, flush=True)
        time.sleep(1)


if __name__ == '__main__':
    main()
