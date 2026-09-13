import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'production_metadata', ROOT / 'release/production-metadata.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)
spec = importlib.util.spec_from_file_location(
    'verify_sequence', ROOT / 'release/verify-sequence.py')
sequence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sequence)


class ProductionReleaseTests(unittest.TestCase):
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

    def test_publisher_sequence_must_increase(self):
        sequence.require_new(9, 10)
        for proposed in (8, 9):
            with self.subTest(proposed=proposed), self.assertRaisesRegex(
                    ValueError, 'exceed the latest'):
                sequence.require_new(9, proposed)

    def test_release_workflow_is_manual_protected_and_sha_pinned(self):
        workflow = (ROOT / '.github/workflows/release.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('pull_request_target', workflow)
        self.assertIn('environment:\n      name: appliance-release', workflow)
        self.assertIn('APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY:', workflow)
        self.assertNotIn('${{ runner.temp }}', workflow)
        self.assertIn('echo "SIGNING_KEY=$RUNNER_TEMP/appliance-release-private.pem"', workflow)
        self.assertIn('if: github.event.repository.private', workflow)
        self.assertIn('select(.type == "required_reviewers")', workflow)
        self.assertIn(".branch_policies[0].name')\" = main", workflow)
        self.assertIn('permissions:\n  actions: read\n  contents: write\n  packages: write', workflow)
        self.assertIn('--draft --target "$GITHUB_SHA"', workflow)
        self.assertLess(workflow.index('gh release create'), workflow.index('gh release edit'))
        materialize = workflow.index("printf '%s\\n' \"$APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY\"")
        self.assertLess(workflow.index('Build offline dependencies and release metadata'), materialize)
        cleanup = workflow.index('Remove transient signing material')
        self.assertLess(materialize, cleanup)
        self.assertLess(cleanup, workflow.index('Publish complete release atomically'))
        self.assertIn('DOCKER_CONFIG="$ANONYMOUS_DOCKER_CONFIG"', workflow)
        self.assertLess(workflow.index('Anonymous GHCR inspection resolved'), materialize)
        actions = re.findall(r'uses:\s+[^\s@]+@([^\s]+)', workflow)
        self.assertTrue(actions)
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{40}', value) for value in actions))
        for name in ('manifest.json', 'manifest.sig', 'elderbrain-host.tar.zst',
                     'elderbrain-dependencies.tar.zst'):
            self.assertIn(name, workflow)


if __name__ == '__main__':
    unittest.main()
