import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / 'provisioning/update'
WRITERS = ('docker.service', 'docker.socket', 'containerd.service', 'elderbrain-stack.service',
           'elderbrain-graphics.service', 'elderbrain-backup.service',
           'elderbrain-backup-retry.service', 'elderbrain-management.service',
           'elderbrain-display-watchdog.service', 'elderbrain-network-watchdog.service',
           'elderbrain-network-confirmation.service', 'elderbrain-network-recovery.service',
           'elderbrain-admin-console.service')


class RecoveryBootTests(unittest.TestCase):
    def test_storage_unit_does_not_depend_on_live_runtime_or_alias_mounts(self):
        value = (ROOT / 'release/elderbrain-storage.service').read_text()
        self.assertIn('/usr/libexec/elderbrain-recovery.py storage', value)
        self.assertNotIn('/opt/mindflayer-elderbrain', value)
        self.assertNotIn('local-fs.target', value)
        self.assertNotIn('/etc/netplan', value)

    def test_writer_gate_requires_success_not_ordering_alone(self):
        value = (BOOT / 'writer-recovery.conf').read_text()
        self.assertIn('Requires=elderbrain-update-recovery.service', value)
        self.assertIn('After=elderbrain-update-recovery.service', value)
        early = (BOOT / 'elderbrain-update-recovery.service').read_text()
        self.assertIn('DefaultDependencies=no', early)
        self.assertIn('Requires=elderbrain-storage.service', early)
        self.assertIn('Before=local-fs.target network-pre.target shutdown.target', early)
        self.assertNotIn('After=local-fs.target', early)
        self.assertNotIn('/opt/mindflayer-elderbrain', early)

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd unit verifier unavailable')
    def test_proposed_installed_unit_graph_verifies_without_cycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            units = Path(temporary)
            for file in (ROOT / 'provisioning/systemd').glob('*.service'):
                # This host is not an installed appliance. Preserve actual unit
                # dependencies but substitute existing no-op executable paths.
                lines = [line.split('=', 1)[0] + '=/usr/bin/true' if line.startswith('Exec') else line
                         for line in file.read_text().splitlines()]
                (units / file.name).write_text('\n'.join(lines) + '\n')
            for name in ('elderbrain-update-recovery.service', 'elderbrain-update-finish.service'):
                shutil.copyfile(BOOT / name, units / name)
            # Stand-ins for OS services/mounts model dependencies only. Nothing
            # is mounted, enabled or started by systemd-analyze verify.
            (units / 'var-lib-mindflayer\\x2delderbrain.mount').write_text(
                '[Mount]\nWhat=tmpfs\nWhere=/var/lib/mindflayer-elderbrain\nType=tmpfs\n')
            for name in ('docker.service', 'containerd.service'):
                (units / name).write_text('[Service]\nExecStart=/usr/bin/true\n')
            (units / 'docker.socket').write_text('[Socket]\nListenStream=/run/elderbrain-fixture.sock\n')
            aliases = {'etc-netplan.mount': ('/etc/netplan', 'netplan'), 'etc-ssh.mount': ('/etc/ssh', 'ssh-server'),
                       'root-.ssh.mount': ('/root/.ssh', 'ssh-root'),
                       'home-elderbrain\\x2dinstaller-.ssh.mount': ('/home/elderbrain-installer/.ssh', 'ssh-admin')}
            for name, (where, source) in aliases.items():
                (units / name).write_text('[Unit]\nRequiresMountsFor=/var/lib/mindflayer-elderbrain\n'
                    '[Mount]\nWhat=/var/lib/mindflayer-elderbrain/host/' + source + '\nWhere=' + where + '\nType=none\nOptions=bind\n')
            for name in (*WRITERS, *aliases):
                directory = units / (name + '.d')
                directory.mkdir()
                shutil.copyfile(BOOT / 'writer-recovery.conf', directory / '20-update-recovery.conf')
            shutil.copyfile(ROOT / 'release/elderbrain-storage.service', units / 'elderbrain-storage.service')
            environment = {**os.environ, 'SYSTEMD_UNIT_PATH': str(units) + ':/usr/lib/systemd/system:/lib/systemd/system'}
            checked = [str(units / name) for name in (*WRITERS, *aliases, 'elderbrain-storage.service',
                       'elderbrain-update-recovery.service', 'elderbrain-update-finish.service')]
            result = subprocess.run(['systemd-analyze', 'verify', '--man=no', *checked],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
