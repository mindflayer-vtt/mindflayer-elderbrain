import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_metrics', ROOT / 'appliance/lib/host_metrics.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MetricsTests(unittest.TestCase):
    def test_cpu_ram_storage_and_bounded_history(self):
        metrics = module.Metrics(paths=('/', '/data'))
        tick = 0

        def read(path):
            if path.name == 'stat':
                return f'cpu {100 + tick * 20} 0 0 {100 + tick * 80} 0 0 0 0 999 999\n'
            if path.name == 'meminfo':
                return 'MemTotal: 1000 kB\nMemAvailable: 250 kB\n'
            return '120.00 1.00\n'

        with patch.object(Path, 'read_text', read), patch.object(module.os, 'stat', return_value=SimpleNamespace(st_dev=1)), \
             patch.object(module.os, 'statvfs', return_value=SimpleNamespace(f_blocks=100, f_bfree=30, f_bavail=20, f_frsize=1024)), \
             patch.object(module.subprocess, 'run', return_value=SimpleNamespace(stdout='active\n')):
            metrics.sample()
            self.assertIsNone(metrics.snapshot()['history'][0]['cpu'])
            tick = 1
            metrics.sample()
            sample = metrics.snapshot()['history'][-1]
            self.assertAlmostEqual(sample['cpu'], 20)
            self.assertEqual(sample['ram'], {'total': 1024000, 'free': 256000, 'used': 768000})
            self.assertEqual(len(sample['disks']), 1)  # Same filesystem counted once.
            self.assertEqual(sample['disks'][0]['used'], 71680)
            self.assertEqual(sample['disks'][0]['free'], 20480)  # Excludes reserved blocks.
            for _ in range(725):
                metrics.sample()
            self.assertEqual(len(metrics.snapshot()['history']), 720)
            snapshot = metrics.snapshot()
            snapshot['history'].clear()
            self.assertEqual(len(metrics.snapshot()['history']), 720)
            with patch.object(module.time, 'time', return_value=sample['at'] + 4000):
                metrics.sample()
            self.assertEqual(len(metrics.snapshot()['history']), 1)

    def test_failures_are_unavailable_not_zero(self):
        metrics = module.Metrics(paths=('/missing',))
        with patch.object(Path, 'read_text', side_effect=OSError()), patch.object(module.os, 'stat', side_effect=OSError()), \
             patch.object(module.subprocess, 'run', side_effect=OSError()):
            metrics.sample()
        result = metrics.snapshot()
        self.assertIsNone(result['history'][0]['cpu'])
        self.assertIsNone(result['history'][0]['ram'])
        self.assertIsNone(result['uptime'])
        self.assertEqual(len(result['errors']), 3)
        self.assertTrue(all(item['state'] == 'unavailable' for item in result['services']))

    def test_installer_includes_sampler(self):
        self.assertIn('"$RUNTIME/host_metrics.py"', (ROOT / 'provisioning/install.sh').read_text())
        self.assertIn('METRICS.start()', (ROOT / 'appliance/lib/management-server').read_text())
