from configparser import ConfigParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NetworkUnitTests(unittest.TestCase):
    def unit(self, name):
        config = ConfigParser(interpolation=None)
        config.read(ROOT / 'provisioning/systemd' / name)
        return config

    def test_recovery_is_early_and_backend_failure_is_not_ignored(self):
        unit = self.unit('elderbrain-network-recovery.service')
        self.assertEqual(unit['Unit']['DefaultDependencies'], 'no')
        self.assertIn('network-pre.target', unit['Unit']['Before'].split())
        self.assertIn('network-pre.target', unit['Unit']['Wants'].split())
        self.assertEqual(unit['Service']['RemainAfterExit'], 'yes')
        self.assertTrue(unit['Service']['ExecStart'].endswith('network_worker.py recover-boot'))
        dependency = self.unit('network-recovery.conf')['Unit']
        for key in ('Requires', 'After'):
            self.assertIn('elderbrain-network-recovery.service', dependency[key].split())

    def test_watchdog_is_independent_and_installed_for_boot(self):
        unit = self.unit('elderbrain-network-watchdog.service')
        self.assertEqual(unit['Service']['Restart'], 'always')
        self.assertEqual(unit['Service']['KillMode'], 'control-group')
        self.assertEqual(unit['Unit']['StartLimitIntervalSec'], '0')
        self.assertIn('elderbrain-network-recovery.service', unit['Unit']['Requires'].split())
        installer = (ROOT / 'provisioning/install.sh').read_text()
        enable = next(line for line in installer.splitlines() if line.startswith('systemctl enable'))
        for name in ('elderbrain-network-recovery', 'elderbrain-network-watchdog'):
            self.assertIn(name, enable.split())
        self.assertIn('for network_service in systemd-networkd NetworkManager;', installer)
