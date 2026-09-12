import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test.test_appliance_release as fixture
from release_catalog import check, fetch, source_url


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        runtime = self.root / 'opt/mindflayer-elderbrain'
        runtime.mkdir(parents=True)
        (runtime / 'VERSION').write_text('1.0.0\n')
        self.config = self.root / 'etc/elderbrain'
        self.config.mkdir(parents=True)
        self.fixture = fixture.ApplianceReleaseTests()
        self.fixture.setUp()
        self.enterContext(patch('release_catalog.platform.freedesktop_os_release', return_value={'ID': 'ubuntu', 'VERSION_ID': '26.04'}))
        self.enterContext(patch('release_catalog.platform.machine', return_value='x86_64'))
        self.active = self.enterContext(patch('release_catalog.active_recovery', return_value={
            'bundle': 'a' * 64, 'recoveryApi': 1}))

    def configure(self):
        (self.config / 'release-source.json').write_text(json.dumps({'baseUrl': 'https://updates.example.test/stable/'}))
        (self.config / 'release-public.pem').write_bytes(self.fixture.public.read_bytes())

    def test_missing_source_does_not_contact_network(self):
        download = Mock()
        self.assertEqual(check(host_root=self.root, download=download)['state'], 'not-configured')
        download.assert_not_called()

    def test_old_source_built_iso_version_is_not_an_update_baseline(self):
        version = 'a' * 40 + '-dirty'
        (self.root / 'opt/mindflayer-elderbrain/VERSION').write_text(version + '\n')
        with self.assertRaisesRegex(ValueError, 'installed host version'):
            check(host_root=self.root)

    def test_signature_verified_before_public_notes_and_incomplete_release_not_eligible(self):
        self.configure()
        manifest = json.dumps(self.fixture.value).encode()
        signature = self.fixture.sign(manifest)
        download = Mock(side_effect=[manifest, signature])
        result = check(host_root=self.root, download=download)
        self.assertEqual(result['release']['notes'], 'Test release')
        self.assertEqual(result['release']['setupVersion'], '2.0.0')
        self.assertFalse(result['release']['compatible'])  # Format 1 lacks offline dependencies.
        with self.assertRaisesRegex(ValueError, 'signature'):
            check(host_root=self.root, download=Mock(side_effect=[manifest + b' ', signature]))

    def test_writable_or_symlinked_trust_rejected_before_download(self):
        self.configure()
        download = Mock()
        key = self.config / 'release-public.pem'
        key.chmod(0o666)
        with self.assertRaises(ValueError):
            check(host_root=self.root, download=download)
        key.unlink()
        key.symlink_to(self.fixture.public)
        with self.assertRaises(ValueError):
            check(host_root=self.root, download=download)
        download.assert_not_called()

    def test_complete_release_is_compatible_only_on_matching_platform_and_schema(self):
        self.configure()
        self.fixture.value.update(format=2, dependencies={
            'artifact': {'file': 'elderbrain-dependencies.tar.zst', 'size': 3, 'sha256': 'b' * 64},
            'pythonAbi': 'cp314', 'files': {name: {'size': 1, 'sha256': 'c' * 64} for name in (
                'dependencies.json', 'wheels/example-1.0-py3-none-any.whl', 'node/playwright-core-1.63.0.tgz')},
        })
        manifest = json.dumps(self.fixture.value).encode()
        signature = self.fixture.sign(manifest)
        self.assertTrue(check(host_root=self.root, download=Mock(side_effect=[manifest, signature]))['release']['compatible'])
        self.active.return_value['recoveryApi'] = 2
        self.assertFalse(check(host_root=self.root, download=Mock(side_effect=[manifest, signature]))['release']['compatible'])
        self.active.return_value['recoveryApi'] = 1
        with patch('release_catalog.platform.machine', return_value='aarch64'):
            self.assertFalse(check(host_root=self.root, download=Mock(side_effect=[manifest, signature]))['release']['compatible'])

    def test_replayed_sequence_is_visible_but_not_eligible(self):
        self.configure()
        self.fixture.value.update(format=2, dependencies={
            'artifact': {'file': 'elderbrain-dependencies.tar.zst', 'size': 3, 'sha256': 'b' * 64},
            'pythonAbi': 'cp314', 'files': {name: {'size': 1, 'sha256': 'c' * 64} for name in (
                'dependencies.json', 'wheels/example-1.0-py3-none-any.whl', 'node/playwright-core-1.63.0.tgz')},
        })
        policy = self.root / 'var/lib/mindflayer-elderbrain'
        policy.mkdir(parents=True)
        from release_policy import ReleasePolicy
        ReleasePolicy(policy).commit({'releaseSequence': 123, 'version': '1.2.3',
            'manifestSha256': 'd' * 64})
        manifest = json.dumps(self.fixture.value).encode()
        signature = self.fixture.sign(manifest)
        result = check(host_root=self.root, download=Mock(side_effect=[manifest, signature]))
        self.assertEqual(result['installedReleaseSequence'], 123)
        self.assertFalse(result['release']['compatible'])

    def test_source_rejects_credentials_insecure_urls_queries_and_controls(self):
        for value in ('http://example.test/', 'https://user:secret@example.test/',
                      'https://example.test/?key=x', 'https://example.test/#x',
                      'https://example.test/\n', 'https://example.test/latest', '//example.test/'):
            with self.assertRaises(ValueError):
                source_url(value)

    def test_https_transport_is_bounded_and_does_not_follow_redirects(self):
        with patch('release_catalog.http.client.HTTPSConnection') as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 302
            with self.assertRaises(ValueError):
                fetch('https://example.test/releases/', 'manifest.json', 64)
            response.read.assert_not_called()
            response.status = 200
            response.getheader.side_effect = lambda key, default=None: default
            response.read.return_value = b'x' * 65
            with self.assertRaises(ValueError):
                fetch('https://example.test/releases/', 'manifest.json', 64)
            response.read.assert_called_once_with(65)
            self.assertEqual(factory.call_args.kwargs['timeout'], 10)
            self.assertEqual(factory.return_value.close.call_count, 2)


if __name__ == '__main__':
    unittest.main()
