from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from . import test_appliance_release as release_fixture
from release_images import canonical, prepare


class ReleaseImagesTests(unittest.TestCase):
    def setUp(self):
        fixture = release_fixture.ApplianceReleaseTests()
        fixture.setUp()
        self.release = fixture.value
        self.patch = patch('release_images.verify', return_value=self.release)
        self.verify = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.image = {'Id': 'sha256:' + 'b' * 64, 'RepoDigests': [self.release['setup']['image']],
            'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Env': ['PRIVATE=do-not-expose'], 'Labels': {
                'org.opencontainers.image.version': '2.0.0',
                'io.mindflayer.elderbrain.host-api-min': '1', 'io.mindflayer.elderbrain.host-api-max': '2'}}}
        self.run = Mock(side_effect=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps([self.image])))

    def prepare(self, **options):
        return prepare(b'manifest', b'signature', b'pinned-key', run=self.run, **options)

    def test_default_is_offline_inspection_only_and_hides_private_metadata(self):
        result = self.prepare()
        self.assertEqual(set(result['images']), {'elderbrain-setup', 'traefik', 'mindflayer-server', 'foundry'})
        self.assertTrue(all(call.args[0][:3] == ['docker', 'image', 'inspect'] for call in self.run.call_args_list))
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.verify.assert_called_once_with(b'manifest', b'signature', b'pinned-key')

    def test_missing_image_never_implicitly_pulls(self):
        self.run.side_effect = lambda *_args, **_kwargs: SimpleNamespace(returncode=1)
        with self.assertRaisesRegex(ValueError, 'unavailable locally'):
            self.prepare()
        self.assertEqual(self.run.call_count, 1)

    def test_explicit_download_pulls_exact_digest_and_reinspects(self):
        self.run.side_effect = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0),
                               SimpleNamespace(returncode=0, stdout=json.dumps([self.image]))]
        self.prepare(allow_download=True, setup_only=True, installed_host_api=1)
        self.assertEqual(self.run.call_args_list[1].args[0],
                         ['docker', 'pull', '--platform', 'linux/amd64', self.release['setup']['image']])
        self.assertEqual(self.run.call_args_list[2].args[0][:3], ['docker', 'image', 'inspect'])

    def test_digest_platform_and_setup_labels_must_match(self):
        original = deepcopy(self.image)
        for changes in ({'RepoDigests': []}, {'Architecture': 'arm64'}, {'Os': 'windows'},
                        {'Config': None}, {'Id': 'not-an-id'}, {'Config': {'Labels': {}}}):
            self.image = {**original, **changes}
            with self.assertRaises(ValueError):
                self.prepare(allow_download=True)
        self.assertTrue(all(call.args[0][1] == 'image' for call in self.run.call_args_list))

    def test_setup_only_checks_installed_api_before_docker(self):
        for installed in (None, True, 3):
            with self.assertRaises(ValueError):
                self.prepare(setup_only=True, installed_host_api=installed)
        self.run.assert_not_called()

    def test_invalid_signature_prevents_all_image_activity(self):
        self.verify.side_effect = ValueError('invalid signature')
        with self.assertRaises(ValueError):
            self.prepare(allow_download=True)
        self.run.assert_not_called()

    def test_docker_hub_aliases_preserve_digest_and_repository_binding(self):
        digest = '@sha256:' + 'a' * 64
        self.assertEqual(canonical('traefik:v3' + digest), 'docker.io/library/traefik' + digest)
        self.assertEqual(canonical('mindflayervtt/server' + digest), 'docker.io/mindflayervtt/server' + digest)
        self.assertEqual(canonical('ghcr.io/example/server:v1' + digest), 'ghcr.io/example/server' + digest)


if __name__ == '__main__':
    unittest.main()
