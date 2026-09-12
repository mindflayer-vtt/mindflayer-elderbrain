"""Wire signed candidate preparation to fixed host activation and recovery.

Internal host-worker API, not a network endpoint. Call from independently retained
code, with an independently pinned public key and authenticated bootstrap tree.
"""
from contextlib import ExitStack
from pathlib import Path
import subprocess

from backup_service import Maintenance
from release_activation import Activation
from release_bootstrap import verify_installed
from release_checkpoints import UpdateCheckpoints
from release_recovery import health
from release_runtime import candidate, private_directory, read_regular
from release_services import UpdateServices
from release_targets import sources, targets
from restore_service import persistent_identity


def activate(prepared, public_key, allowed_paths, *, dependency_directory, bootstrap_tree,
             platform, configuration_schema, parent, host_root=Path('/'), run=subprocess.run):
    root = Path(host_root).absolute()
    state, runtime = root / 'var/lib/mindflayer-elderbrain', root / 'opt/mindflayer-elderbrain'
    if Path(__file__).resolve().is_relative_to(runtime.resolve()):
        raise ValueError('Activation worker must run outside the replaceable runtime')
    identity = persistent_identity(state, root)
    if identity is None:
        raise ValueError('Release activation requires verified persistent storage')
    prepared = private_directory(prepared)
    manifest = read_regular(prepared / 'manifest.json', 65536)
    signature = read_regular(prepared / 'manifest.sig', 1024)
    services = UpdateServices(runtime, health_check=lambda saved: health(
        saved, state, management_socket=root / 'run/elderbrain/management.sock'))
    maintenance = Maintenance(state / 'maintenance', services)
    checkpoints = UpdateCheckpoints(state, runtime, maintenance, host_root=root)
    with ExitStack() as contexts:
        def prepare_sources(release):
            # Activation invokes this inside job, maintenance and settings locks,
            # before journaling or interrupting any service.
            if persistent_identity(state, root) != identity:
                raise ValueError('Persistent storage changed before activation')
            verify_installed(bootstrap_tree, allowed_paths, host_root=root)
            services.validate()  # Previous runtime must already be offline-safe.
            authenticated, tree = contexts.enter_context(candidate(prepared, public_key, allowed_paths,
                dependency_directory=dependency_directory, state=state, platform=platform,
                configuration_schema=configuration_schema, parent=parent, host_root=root, run=run))
            if authenticated != release:
                raise ValueError('Prepared release changed during activation admission')
            return sources(tree, root)
        activation = Activation(maintenance, targets(root), checkpoint=checkpoints.checkpoint,
            restore_checkpoint=checkpoints.restore, release_checkpoint=checkpoints.release,
            refresh=checkpoints.guard)
        record = activation.activate(manifest, signature, public_key, prepare_sources)
    return {key: record[key] for key in ('id', 'state', 'version')}
