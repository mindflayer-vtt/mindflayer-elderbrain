import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml

from . import test_appliance_release as release_fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'production_metadata', ROOT / 'release/production-metadata.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)
spec = importlib.util.spec_from_file_location(
    'verify_sequence', ROOT / 'release/verify-sequence.py')
sequence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sequence)
spec = importlib.util.spec_from_file_location(
    'build_host', ROOT / 'release/build-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class ProductionReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        release_fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(release_fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        self.release_fixture = release_fixture.ApplianceReleaseTests()
        self.release_fixture.setUp()

    def test_reviewed_update_trust_is_valid_and_matches_production_channel(self):
        source = ROOT / 'config/releases/github-releases.json'
        public = ROOT / 'config/releases/appliance-release-public.pem'
        self.assertEqual(json.loads(source.read_text()), {
            'baseUrl': ('https://github.com/mindflayer-vtt/'
                        'mindflayer-elderbrain/releases/latest/download/')})
        result = subprocess.run(
            ['openssl', 'pkey', '-pubin', '-in', str(public), '-outform', 'DER'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(hashlib.sha256(result.stdout).hexdigest(),
                         'da146820922e1eee1973dc6d91e036aa4e45de45a6904088c4830211b89fcb74')

    def test_metadata_uses_only_digest_pinned_reviewed_images(self):
        setup = 'ghcr.io/mindflayer-vtt/mindflayer-elderbrain-setup:1.2.3@sha256:' + 'a' * 64
        value = production.create('1.2.3', 9, setup, 'Security and reliability update.',
                                  ROOT / 'config/defaults/appliance.env')
        self.assertEqual(value['version'], '1.2.3')
        self.assertEqual(value['releaseSequence'], 9)
        self.assertEqual(value['setup']['image'], setup)
        self.assertEqual(value['host'], {'version': '1.2.3', 'apiVersion': 1})
        self.assertTrue(all('@sha256:' in image for image in value['images'].values()))

    def test_metadata_rejects_mutable_images_bad_identity_and_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory) / 'images.env'
            images.write_text('TRAEFIK_IMAGE=traefik:v3@sha256:' + 'd' * 64
                              + '\nMINDFLAYER_SERVER_IMAGE=x@sha256:' + 'a' * 64
                              + '\nFOUNDRY_IMAGE=y@sha256:' + 'b' * 64 + '\n')
            setup = 'ghcr.io/example/setup:1@sha256:' + 'c' * 64
            for version, sequence, selected_setup, notes in (
                    ('commit-hash', 1, setup, 'notes'),
                    ('1.0.0', 0, setup, 'notes'),
                    ('1.0.0', 1, 'ghcr.io/example/setup:latest', 'notes'),
                    ('1.0.0', 1, setup, '')):
                with self.subTest(version=version, sequence=sequence, setup=selected_setup, notes=notes):
                    with self.assertRaises(ValueError):
                        production.create(version, sequence, selected_setup, notes, images)
            images.write_text('TRAEFIK_IMAGE=traefik:v3\nMINDFLAYER_SERVER_IMAGE=x@sha256:'
                              + 'a' * 64 + '\nFOUNDRY_IMAGE=y@sha256:' + 'b' * 64 + '\n')
            with self.assertRaises(ValueError):
                production.create('1.0.0', 1, setup, 'notes', images)

    def test_no_published_release_uses_committed_baseline_floor(self):
        configured = sequence.baseline(ROOT / 'config/releases/production-baseline.json')
        self.assertEqual(configured, {'format': 1, 'version': '0.1.0', 'releaseSequence': 1})
        self.assertEqual(sequence.require_new(configured, '0.1.1', 2), 1)
        for proposed in (0, 1):
            with self.subTest(proposed=proposed), self.assertRaises(ValueError):
                sequence.require_new(configured, '0.1.1', proposed)
        for version in ('0.1.0', '0.0.9'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'version'):
                sequence.require_new(configured, version, 2)

    def test_host_targets_remain_compatible_with_installed_production_baseline(self):
        baseline = json.loads((
            ROOT / 'config/releases/production-host-inventory.json').read_text())
        self.assertEqual(set(baseline), {'format', 'files', 'sha256'})
        self.assertEqual(baseline['format'], 1)
        paths = {entry['path']: entry['mode'] for entry in host.entries(
            ROOT / 'release/host-files.json')}
        paths['runtime/VERSION'] = 0o644
        encoded = json.dumps(
            paths, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        self.assertEqual(len(paths), baseline['files'])
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), baseline['sha256'])

    def test_authenticated_latest_release_and_baseline_form_maximum_floor(self):
        configured = {'format': 1, 'version': '0.1.0', 'releaseSequence': 1}
        self.assertEqual(sequence.require_new(configured, '0.1.2', 3, 2), 2)
        for proposed in (1, 2):
            with self.subTest(proposed=proposed), self.assertRaisesRegex(ValueError, 'floor'):
                sequence.require_new(configured, '0.1.2', proposed, 2)
        self.assertEqual(sequence.require_new(configured, '0.1.2', 6, 5), 5)

    def test_bad_latest_release_never_falls_back_to_baseline(self):
        value = self.release_fixture.value
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        signature = self.release_fixture.sign(raw)
        self.assertEqual(sequence.authenticated_sequence(
            raw, signature, self.release_fixture.public.read_bytes()), value['releaseSequence'])
        cases = [
            (b'{', signature),
            (raw, b'invalid-signature'),
        ]
        invalid = dict(value)
        invalid['releaseSequence'] = 0
        invalid_raw = json.dumps(invalid, sort_keys=True, separators=(',', ':')).encode()
        cases.append((invalid_raw, self.release_fixture.sign(invalid_raw)))
        for manifest, selected_signature in cases:
            with self.subTest(manifest=manifest[:20]), self.assertRaises(ValueError):
                sequence.authenticated_sequence(
                    manifest, selected_signature, self.release_fixture.public.read_bytes())

    def test_baseline_parser_rejects_noncanonical_schema_and_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            invalid = (
                b'{"format":1,"format":1,"version":"0.1.0","releaseSequence":1}',
                b'{"format":1,"version":"0.1.0","releaseSequence":1,"extra":true}',
                b'{"format":1,"version":"v0.1.0","releaseSequence":1}',
                b'{"format":1,"version":"0.1.0","releaseSequence":0}',
                b'{"format":1,"version":"0.1.0","releaseSequence":9223372036854775808}',
                b'{"format":true,"version":"0.1.0","releaseSequence":1}',
                b'{',
            )
            for content in invalid:
                path.write_bytes(content)
                with self.subTest(content=content), self.assertRaises((ValueError, json.JSONDecodeError)):
                    sequence.baseline(path)

    def test_release_workflow_is_manual_and_has_separate_authority_domains(self):
        raw = (ROOT / '.github/workflows/release.yml').read_text()
        workflow = yaml.load(raw, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertEqual(set(workflow['jobs']), {'prepare', 'sign-and-publish'})
        prepare, signing = workflow['jobs']['prepare'], workflow['jobs']['sign-and-publish']
        self.assertEqual(prepare['permissions'], {'contents': 'read', 'packages': 'write'})
        self.assertEqual(signing['permissions'], {
            'actions': 'read', 'contents': 'write', 'packages': 'read'})
        self.assertEqual(signing['needs'], 'prepare')
        self.assertNotIn('environment', prepare)
        self.assertEqual(signing['environment'], {'name': 'appliance-release'})
        self.assertNotIn('APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY', json.dumps(prepare))
        self.assertIn('${{ secrets.APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY }}', json.dumps(signing))
        for job in (prepare, signing):
            self.assertNotIn('GH_TOKEN', job.get('env', {}))
            checkouts = [step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@')]
            self.assertEqual(len(checkouts), 1)
            self.assertEqual(checkouts[0]['with']['persist-credentials'], 'false')
        prepare_commands = '\n'.join(step.get('run', '') for step in prepare['steps'])
        signing_commands = '\n'.join(step.get('run', '') for step in signing['steps'])
        self.assertIn('release/build-dependencies.py', prepare_commands)
        self.assertIn('docker build --pull', prepare_commands)
        self.assertNotIn('release/build-dependencies.py', signing_commands)
        self.assertNotIn('docker build --pull', signing_commands)
        self.assertNotIn('pip wheel', signing_commands)
        self.assertNotIn('npm pack', signing_commands)
        self.assertNotIn('/environments/appliance-release', signing_commands)
        self.assertIn('release/prepared-inputs.py verify', signing_commands)
        self.assertIn('config/releases/production-baseline.json', signing_commands)
        self.assertIn('DOCKER_CONFIG="$ANONYMOUS_DOCKER_CONFIG"', signing_commands)
        step_names = [step.get('name', '') for step in signing['steps']]
        deep = step_names.index('Deeply validate archives and prove host provenance')
        materialize = step_names.index('Materialize key, sign approved manifest, and immediately erase key')
        self.assertLess(step_names.index('Revalidate every prepared byte'), materialize)
        self.assertLess(deep, materialize)
        self.assertLess(step_names.index('Reverify Setup image anonymously by exact digest'), materialize)
        self.assertLess(step_names.index('Require available tag and authenticated sequence advance'),
                        materialize)
        self.assertLess(materialize, step_names.index('Verify signed release after key removal'))
        self.assertLess(step_names.index('Verify signed release after key removal'),
                        step_names.index('Publish complete release atomically'))
        sign_step = signing['steps'][materialize]
        self.assertEqual(set(sign_step['env']), {'APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY'})
        self.assertIn('cleanup_signing_material', sign_step['run'])
        self.assertLess(sign_step['run'].index('unset APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY'),
                        sign_step['run'].index('openssl pkey'))
        self.assertLess(sign_step['run'].index('unset APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY'),
                        sign_step['run'].index('release/sign-manifest.py'))
        sign_call = sign_step['run'].index('python3 release/sign-manifest.py')
        cleanup_call = sign_step['run'].index('cleanup_signing_material\n', sign_call)
        self.assertLess(sign_call, cleanup_call)
        for forbidden in ('zstd', 'tar ', 'verify-artifacts.py', 'verify-prepared-release.py'):
            self.assertNotIn(forbidden, sign_step['run'])
        deep_step = signing['steps'][deep]['run']
        self.assertIn("git diff --quiet", deep_step)
        self.assertIn("HEAD^{tree}", deep_step)
        helper = (ROOT / 'release/sign-manifest.py').read_text()
        for forbidden in ('release_staging', 'stage(', 'tarfile', 'zstd', 'prepared-inputs'):
            self.assertNotIn(forbidden, helper)
        publish = next(step for step in signing['steps'] if step.get('name') == 'Publish complete release atomically')
        self.assertEqual(set(publish['env']), {'GH_TOKEN'})
        self.assertIn('--draft --target "$GITHUB_SHA"', publish['run'])
        self.assertLess(publish['run'].index('gh release create'), publish['run'].index('gh release edit'))
        actions = re.findall(r'uses:\s+[^\s@]+@([^\s]+)', raw)
        self.assertTrue(actions)
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{40}', value) for value in actions))
        for name in ('manifest.json', 'manifest.sig', 'elderbrain-host.tar.zst',
                     'elderbrain-dependencies.tar.zst'):
            self.assertIn(name, publish['run'])


if __name__ == '__main__':
    unittest.main()
