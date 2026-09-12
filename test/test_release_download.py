import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test.test_appliance_release as fixture
from release_download import artifact, download_prepare


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        sample = fixture.ApplianceReleaseTests()
        sample.setUp()
        self.release = sample.value
        self.connection = self.enterContext(patch('release_download.http.client.HTTPSConnection')).return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.getheader.side_effect = lambda key, default=None: default
        self.response.read1.return_value = b'fixture'
        self.response.read.return_value = b''

    def test_verified_artifact_is_private_and_exact(self):
        result = artifact('https://example.test/stable/', self.release, 'host', self.root)
        self.assertEqual(result.read_bytes(), b'fixture')
        self.assertEqual(result.stat().st_mode & 0o777, 0o600)
        self.connection.request.assert_called_once_with('GET', '/stable/elderbrain-host.tar.zst', headers={'Accept-Encoding': 'identity'})
        self.connection.close.assert_called_once()

    def test_redirect_truncation_checksum_and_excess_bytes_rejected(self):
        for mode in ('redirect', 'truncated', 'checksum', 'excess'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                self.response.status = 302 if mode == 'redirect' else 200
                self.response.read1.return_value = b'' if mode == 'truncated' else b'changed' if mode == 'checksum' else b'fixture'
                self.response.read.return_value = b'x' if mode == 'excess' else b''
                with self.assertRaises(ValueError):
                    artifact('https://example.test/stable/', self.release, 'host', directory)

    def test_changed_confirmation_prevents_artifact_fetch_and_preparation(self):
        config = self.root / 'etc/elderbrain'
        config.mkdir(parents=True)
        (config / 'release-source.json').write_text(json.dumps({'baseUrl': 'https://example.test/stable/'}))
        with patch('release_download.fetch', side_effect=[b'changed', b'signature']), \
                patch('release_download.artifact') as fetch_artifact, patch('release_download.prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'changed after user confirmation'):
                download_prepare({'version': '1.2.3', 'manifestSha256': hashlib.sha256(b'original').hexdigest()},
                                 b'key', {}, root=self.root, releases=self.root,
                                 dependencies=self.root / 'dependencies', current={}, progress=Mock())
            fetch_artifact.assert_not_called()
            prepare.assert_not_called()

    def test_verified_downloads_feed_offline_preparation_before_activation(self):
        config = self.root / 'etc/elderbrain'
        config.mkdir(parents=True)
        (config / 'release-source.json').write_text(json.dumps({'baseUrl': 'https://example.test/stable/'}))
        release = {**self.release, 'format': 2, 'dependencies': {'artifact': {'size': 12}}}
        selected = {'version': release['version'], 'manifestSha256': hashlib.sha256(b'manifest').hexdigest()}
        progress = Mock()
        with patch('release_download.fetch', side_effect=[b'manifest', b'signature']), \
                patch('release_download.verify', return_value=release), \
                patch('release_download.require_compatible') as compatible, \
                patch('release_download.artifact', side_effect=[self.root / 'host', self.root / 'deps']) as fetch_artifact, \
                patch('release_download.prepare', return_value={'state': 'runtime-prepared'}) as prepare, \
                patch('release_download.shutil.disk_usage', return_value=Mock(free=10 ** 12)):
            result = download_prepare(selected, b'key', {}, root=self.root, releases=self.root,
                                      dependencies=self.root / 'dependencies', current={'os': 'fixture'}, progress=progress)
        self.assertEqual(result['state'], 'runtime-prepared')
        compatible.assert_called_once()
        self.assertEqual([call.args[2] for call in fetch_artifact.call_args_list], ['host', 'dependencies'])
        self.assertTrue(prepare.call_args.kwargs['allow_download'])
        self.assertEqual(prepare.call_args.kwargs['dependency_archive'], self.root / 'deps')
        self.assertEqual(prepare.call_args.kwargs['dependency_directory'], self.root / 'dependencies')
        self.assertEqual([call.args[0] for call in progress.call_args_list], ['downloading-host', 'downloading-dependencies', 'preparing-runtime'])


if __name__ == '__main__':
    unittest.main()
