from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

import test.test_appliance_release as release_fixture
from release_compose import render

ROOT = Path(__file__).resolve().parents[1]


class ReleaseComposeTests(unittest.TestCase):
    def setUp(self):
        fixture = release_fixture.ApplianceReleaseTests()
        fixture.setUp()
        self.release = fixture.value
        self.template = (ROOT / 'compose/compose.yaml').read_bytes()

    def test_signed_images_replace_overrides_and_disable_builds_and_pulls(self):
        generated = yaml.safe_load(render(self.template, self.release))
        for name, service in generated['services'].items():
            expected = self.release['setup']['image'] if name == 'elderbrain-setup' else self.release['images'][name]
            self.assertEqual(service['image'], expected)
            self.assertEqual(service['pull_policy'], 'never')
            self.assertNotIn('build', service)
        self.assertEqual(generated['services']['elderbrain-setup']['environment']['MINDFLAYER_SERVER_IMAGE'],
                         self.release['images']['mindflayer-server'])

    def test_every_non_release_setting_is_preserved(self):
        original = yaml.safe_load(self.template)
        generated = yaml.safe_load(render(self.template, self.release))
        expected = deepcopy(original)
        for name in expected['services']:
            for field in ('image', 'build', 'pull_policy'):
                expected['services'][name].pop(field, None)
                generated['services'][name].pop(field, None)
        expected['services']['elderbrain-setup']['environment'].pop('MINDFLAYER_SERVER_IMAGE')
        generated['services']['elderbrain-setup']['environment'].pop('MINDFLAYER_SERVER_IMAGE')
        self.assertEqual(generated, expected)
        self.assertIn('profiles: [foundry]', self.template.decode())

    def test_indirection_and_service_mismatches_rejected(self):
        for mutate in (lambda value: value.update(include='other.yaml'),
                       lambda value: value['services'].pop('foundry'),
                       lambda value: value['services']['traefik'].update(extends={'file': 'other.yaml'})):
            value = yaml.safe_load(self.template)
            mutate(value)
            with self.assertRaises(ValueError):
                render(yaml.safe_dump(value).encode(), self.release)

    def test_release_stack_unit_never_builds_or_pulls_and_bounds_health_wait(self):
        unit = (ROOT / 'release/elderbrain-stack.service').read_text()
        self.assertNotIn(' compose build ', unit)
        self.assertNotIn(' compose pull ', unit)
        self.assertIn('--no-build --pull never', unit)
        self.assertIn('--wait-timeout 120', unit)
        self.assertIn('TimeoutStartSec=300', unit)
        self.assertNotIn('ExecStartPre=/usr/bin/docker', unit)

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI unavailable')
    def test_rendered_configuration_passes_real_compose_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'compose.yaml'
            file.write_bytes(render(self.template, self.release))
            result = subprocess.run(['docker', 'compose', '--project-directory', str(ROOT),
                '--env-file', str(ROOT / 'config/defaults/appliance.env'), '-f', str(file),
                '--profile', 'foundry', 'config', '--quiet'], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
