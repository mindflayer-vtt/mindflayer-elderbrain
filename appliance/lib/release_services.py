"""Update-specific host service control; requires a stable external update worker."""
import json
import re

from appliance_release import IMAGE
from backup_service import HostServices


class UpdateServices(HostServices):
    # Stack is a completed oneshot, not a resident writer. Leave it active so
    # neither its legacy ExecStop nor startup/build commands run during switching.
    # The coordinator must install the offline release unit before the next boot.
    UNITS = ('elderbrain-display-watchdog.service', 'elderbrain-network-watchdog.service',
             'elderbrain-network-confirmation.service', 'elderbrain-management.service',
             'elderbrain-admin-console.service')

    def __init__(self, runtime, *, health_check):
        super().__init__(runtime)
        self.health_check = health_check

    def snapshot(self):
        # A running/restarting stack unit could race our direct Compose control.
        state = self.run(['systemctl', 'show', 'elderbrain-stack.service',
                          '--property=ActiveState,SubState']).stdout.splitlines()
        if set(state) != {'ActiveState=active', 'SubState=exited'}:
            raise RuntimeError('Update requires a stable completed stack unit')
        saved = super().snapshot()
        units = []
        for unit in self.UNITS:
            result = self.run(['systemctl', 'is-active', unit], check=False)
            state = result.stdout.strip()
            if state not in ('active', 'inactive', 'failed'):
                raise RuntimeError('Host worker is missing or changing state')
            if state == 'active':
                units.append(unit)
        saved['hostUnits'] = units
        return saved

    def checked(self, saved):
        super().checked(saved)
        units = saved.get('hostUnits')
        if (not isinstance(units, list) or any(not isinstance(unit, str) for unit in units)
                or len(units) != len(set(units)) or not set(units) <= set(self.UNITS)
                or type(saved.get('graphics')) is not bool):
            raise ValueError('Invalid saved update service state')

    def stop(self, saved):
        self.checked(saved)
        # Stop every allowlisted worker, including ones a failed start may have
        # launched. The independent update worker must not belong to these units.
        self.run(['systemctl', 'stop', *self.UNITS])
        super().stop(saved)

    def assert_quiescent(self):
        # containerd can keep containers alive when Docker uses live restore.
        # Early recovery must precede both engines, not merely Docker's unit.
        units = ('docker.service', 'containerd.service', 'elderbrain-stack.service',
                 'elderbrain-graphics.service', 'elderbrain-backup.service',
                 'elderbrain-network-recovery.service', *self.UNITS)
        for unit in units:
            result = self.run(['systemctl', 'is-active', unit], check=False)
            if result.stdout.strip() not in ('inactive', 'failed') or result.returncode != 3:
                raise RuntimeError('Early update recovery requires all writer services inactive')

    def validate(self):
        super().validate()
        document = json.loads(self.run([*self.compose, 'config', '--format', 'json']).stdout)
        services = document.get('services')
        if not isinstance(services, dict) or set(services) != self.ALLOWED:
            raise ValueError('Update runtime must contain the exact coordinated service set')
        for service in services.values():
            if (not isinstance(service, dict) or 'build' in service
                    or service.get('pull_policy') != 'never'
                    or not re.fullmatch(IMAGE, str(service.get('image', '')))):
                raise ValueError('Update runtime must use offline digest-pinned images without builds')

    def resume_restored(self, saved):
        self.checked(saved)
        self.run(['systemctl', 'daemon-reload'])
        # Restore only workers that were running before the update. Management
        # must be available before Setup is recreated against its host socket.
        if saved['hostUnits']:
            self.run(['systemctl', 'start', *saved['hostUnits']])
        if saved['compose']:
            self.run([*self.compose, 'up', '-d', '--no-build', '--pull', 'never', '--no-deps',
                      '--force-recreate', '--wait', '--wait-timeout', '120', *saved['compose']])
        # Reuse bounded per-container health checks, postponing graphics until
        # the host-specific API checks succeed. No backup rescheduling, secret
        # generation, package installation or certificate mutation occurs here.
        super().resume({**saved, 'graphics': False})
        for unit in saved['hostUnits']:
            self.run(['systemctl', 'is-active', unit])
        self.health_check(saved)
        if saved['graphics']:
            self.run(['systemctl', 'start', 'elderbrain-graphics.service'])
            self.run(['systemctl', 'is-active', 'elderbrain-graphics.service'])
