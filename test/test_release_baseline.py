import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
from backup_service import save_record
from release_baseline import prepare, render, SERVICES

ROOT = Path(__file__).resolve().parents[1]


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        self.template = (ROOT / 'compose/compose.yaml').read_bytes()
        (self.runtime / 'compose.yaml').write_bytes(self.template)
        (self.runtime / 'appliance.env').write_text('PRIVATE=never-persist-resolved\n')
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.destination = self.root / 'baselines'
        self.destination.mkdir(mode=0o700)
        self.images = {name: 'sha256:' + str(index) * 64 for index, name in enumerate(sorted(SERVICES))}
        self.calls = []
        self.enterContext(patch('release_baseline.persistent_identity', return_value='fixture'))

    def command(self, args, **options):
        self.calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            result = [{'Id': self.images[args[-1]], 'Os': 'linux', 'Architecture': 'amd64'}]
        else:
            document = yaml.safe_load(Path(args[args.index('-f') + 1]).read_bytes())
            for name, service in document['services'].items():
                if not service['image'].startswith('sha256:'):
                    service['image'] = name
            document['services']['elderbrain-setup']['environment']['PRIVATE'] = 'never-persist-resolved'
            result = document
        return SimpleNamespace(stdout=json.dumps(result), returncode=0)

    def prepare(self, **options):
        return prepare(self.runtime, state=self.state, directory=self.destination,
                       host_root=self.root, run=options.get('run', self.command))

    def test_baseline_is_private_durable_and_does_not_change_live_runtime(self):
        result = self.prepare()
        self.assertEqual(result['state'], 'baseline-prepared')
        self.assertFalse(result['activationReady'])
        directory = Path(result['directory'])
        self.assertEqual(json.loads((directory / 'baseline.json').read_text())['images'], self.images)
        self.assertEqual((self.runtime / 'compose.yaml').read_bytes(), self.template)
        self.assertEqual((directory / 'previous-compose.yaml').read_bytes(), self.template)
        for file in directory.iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(b'never-persist-resolved', file.read_bytes())
        self.assertEqual({args[1] for args in self.calls}, {'compose', 'image'})
        self.assertTrue(all('config' in args or args[1:3] == ['image', 'inspect'] for args in self.calls))

    def test_all_non_image_configuration_is_preserved(self):
        original = yaml.safe_load(self.template)
        generated = yaml.safe_load(render(self.template, self.images))
        for name in SERVICES:
            self.assertEqual(generated['services'][name]['image'], self.images[name])
            self.assertEqual(generated['services'][name]['pull_policy'], 'never')
            for key in ('image', 'build', 'pull_policy'):
                original['services'][name].pop(key, None)
                generated['services'][name].pop(key, None)
        self.assertEqual(generated, original)

    def test_missing_cache_fails_without_publishing_or_downloading(self):
        def missing(args, **options):
            if args[:3] == ['docker', 'image', 'inspect']:
                raise subprocess.CalledProcessError(1, args)
            return self.command(args, **options)
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare(run=missing)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_resolved_settings_drift_rejects_publication(self):
        def drift(args, **options):
            result = self.command(args, **options)
            if '-f' in args and Path(args[args.index('-f') + 1]).parent != self.runtime:
                value = json.loads(result.stdout)
                value['services']['foundry']['hostname'] = 'unexpected'
                result.stdout = json.dumps(value)
            return result
        with self.assertRaisesRegex(ValueError, 'changes settings'):
            self.prepare(run=drift)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_unfinished_maintenance_and_absent_storage_are_rejected(self):
        directory = self.state / 'maintenance'
        directory.mkdir(mode=0o700)
        save_record(directory / 'maintenance.json', {'state': 'working'})
        with self.assertRaisesRegex(RuntimeError, 'Recover maintenance'):
            self.prepare()
        self.assertEqual(self.calls, [])
        with patch('release_baseline.persistent_identity', return_value=None):
            with self.assertRaisesRegex(ValueError, 'verified persistent storage'):
                self.prepare()

    def test_unexpected_services_and_mutable_pins_are_rejected(self):
        with self.assertRaises(ValueError):
            render(self.template, {**self.images, 'foundry': 'foundry:latest'})
        document = yaml.safe_load(self.template)
        document['services']['traefik']['extends'] = {'file': 'other.yaml'}
        with self.assertRaises(ValueError):
            render(yaml.safe_dump(document).encode(), self.images)


if __name__ == '__main__':
    unittest.main()
