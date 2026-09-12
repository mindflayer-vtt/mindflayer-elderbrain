"""Standalone update recovery entry point; must run from a stable private bundle."""
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import sys

# Support isolated Python startup from the independently retained recovery tree.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_service import Maintenance
from release_activation import Activation
from release_checkpoints import UpdateCheckpoints
from release_services import UpdateServices
from release_targets import targets
from release_baseline_install import Migration
from release_recovery_bundle import RECOVERY_API
from release_bootstrap import commit_candidate
from release_policy import ReleasePolicy
from restore_service import persistent_identity


def health(saved, state, *, management_socket=Path('/run/elderbrain/management.sock')):
    """Read-only bridge and CA-verified proxy/Setup checks; never follow redirects."""
    if 'elderbrain-management.service' in saved['hostUnits']:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(10)
            connection.connect(str(management_socket))
            _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != 0:
                raise ValueError('Management health peer is not root')
            connection.sendall(b'host-metrics\n')
            with connection.makefile('rb') as stream:
                response = stream.readline(1024 * 1024 + 1)
            if len(response) > 1024 * 1024 or not response.endswith(b'\n'):
                raise ValueError('Invalid management health response')
            result = json.loads(response)
            if not isinstance(result, dict) or result.get('ok') is not True:
                raise ValueError('Management bridge health failed')
            metrics = json.loads(result.get('output', 'null'))
            if not isinstance(metrics, dict) or not isinstance(metrics.get('history'), list):
                raise ValueError('Management metrics API is unavailable')
    if 'elderbrain-setup' in saved['compose']:
        context = ssl.create_default_context(cafile=str(Path(state) / 'host/admin-ca/ca.crt'))
        connection = http.client.HTTPSConnection('127.0.0.1', timeout=10, context=context)
        try:
            connection.request('GET', '/elderbrain/health', headers={'Accept': 'application/json'})
            response = connection.getresponse()
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                raise ValueError('Setup proxy health failed')
            result = json.loads(body)
            if not isinstance(result, dict) or set(result) != {'ok'} or result['ok'] is not True:
                raise ValueError('Setup proxy health failed')
        finally:
            connection.close()


def recover(action, *, host_root=Path('/')):
    if action not in ('files', 'finish'):
        raise ValueError('Unknown update recovery phase')
    host_root = Path(host_root).absolute()
    state = host_root / 'var/lib/mindflayer-elderbrain'
    runtime = host_root / 'opt/mindflayer-elderbrain'
    if persistent_identity(state, host_root) is None:
        raise ValueError('Update recovery requires verified persistent storage')
    services = UpdateServices(runtime, health_check=lambda saved: health(
        saved, state, management_socket=host_root / 'run/elderbrain/management.sock'))
    maintenance = Maintenance(state / 'maintenance', services)
    previous = maintenance.previous()
    if previous.get('operation') == 'baseline':
        record = Migration(maintenance, host_root=host_root).recover(early=action == 'files')
        return {key: record[key] for key in ('id', 'state')}
    if previous.get('operation') != 'update':
        return {'state': 'no-update-recovery-needed'}
    if previous.get('recoveryApi') != RECOVERY_API:
        raise ValueError('Update journal requires a different recovery transaction API')
    checkpoints = UpdateCheckpoints(state, runtime, maintenance, host_root=host_root)
    activation = Activation(maintenance, targets(host_root), checkpoint=checkpoints.checkpoint,
        restore_checkpoint=checkpoints.restore, release_checkpoint=checkpoints.release,
        refresh=checkpoints.guard, recovery_api=RECOVERY_API,
        candidate_bootstrap=previous.get('candidateBootstrap'),
        commit_release=ReleasePolicy(state).commit)
    record = activation.recover_files() if action == 'files' else activation.recover()
    if action == 'finish' and record.get('state') == 'completed' and record.get('candidateBootstrap'):
        # The admitted worker is gone after a boot. Ordinary admission first
        # classifies its unlocked record as interrupted and excludes any new job;
        # never pretend boot recovery still owns the dead worker's lock.
        commit_candidate(record['candidateBootstrap'], state=state, host_root=host_root)
    if action == 'finish' and record.get('jobId'):
        from host_jobs import JobStore
        with maintenance.locked():
            # A new maintenance operation may have begun after recovery released
            # its lock. Never reconcile its outcome against the previous job.
            current = maintenance.previous()
            if current.get('id') == record.get('id'):
                JobStore(state / 'jobs').reconcile_update(current)
    return {key: record[key] for key in ('id', 'state', 'version') if key in record}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('files', 'finish'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Update recovery requires root')
    print(json.dumps(recover(args.phase)))
