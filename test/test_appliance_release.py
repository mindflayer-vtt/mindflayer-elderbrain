from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from appliance_release import verify, verify_host, validate, require_compatible


class ApplianceReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.private = cls.root / 'test-private.pem'
        cls.public = cls.root / 'test-public.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                        '-out', str(cls.private)], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(cls.private), '-pubout', '-out', str(cls.public)],
                       check=True, capture_output=True)

    def setUp(self):
        image = 'example.test/appliance/image@sha256:' + 'a' * 64
        self.value = {'format': 1, 'kind': 'mindflayer-elderbrain-release', 'version': '1.2.3',
            'platform': {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'},
            'host': {'version': '1.1.0', 'apiVersion': 2, 'artifact': {'file': 'elderbrain-host.tar.zst',
                'size': 7, 'sha256': hashlib.sha256(b'fixture').hexdigest()}},
            'setup': {'version': '2.0.0', 'image': image, 'hostApi': {'min': 1, 'max': 2}},
            'images': {name: image for name in ('traefik', 'mindflayer-server', 'foundry')},
            'configurationSchema': 1, 'notes': 'Test release', 'downtimeSeconds': 120}

    def sign(self, data):
        manifest = self.root / 'manifest.json'
        signature = self.root / 'manifest.sig'
        manifest.write_bytes(data)
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(self.private), '-out', str(signature),
                        str(manifest)], check=True, capture_output=True)
        return signature.read_bytes()

    def test_exact_signed_bytes_and_independent_component_versions(self):
        data = json.dumps(self.value).encode()
        signature = self.sign(data)
        self.assertEqual(verify(data, signature, self.public.read_bytes()), self.value)
        for modified in (data + b' ', data.replace(b'1.2.3', b'1.2.4'), b'not-json'):
            with self.assertRaisesRegex(ValueError, 'signature'):
                verify(modified, signature, self.public.read_bytes())

    def test_signed_duplicates_unknown_fields_and_boolean_format_rejected(self):
        for data in (json.dumps(self.value).replace('"format": 1', '"format": 1, "format": 1').encode(),
                     json.dumps({**self.value, 'trustedKey': 'attacker'}).encode(),
                     json.dumps({**self.value, 'format': True}).encode()):
            with self.assertRaises(ValueError):
                verify(data, self.sign(data), self.public.read_bytes())

    def test_signature_and_payload_bounds(self):
        for data, signature, key in ((b'a' * 65537, b'x', b'key'), (b'{}', b'x' * 1025, b'key'),
                                     (b'{}', b'x', b'')):
            with self.assertRaises(ValueError):
                verify(data, signature, key)

    def test_all_images_require_immutable_digest(self):
        for service in self.value['images']:
            value = deepcopy(self.value)
            value['images'][service] = 'image:latest'
            with self.assertRaises(ValueError):
                validate(value)
        self.value['setup']['image'] = 'setup:1'
        with self.assertRaises(ValueError):
            validate(self.value)

    def test_setup_cannot_exclude_its_coordinated_host(self):
        self.value['setup']['hostApi']['max'] = 1
        with self.assertRaisesRegex(ValueError, 'coordinated host'):
            validate(self.value)

    def test_platform_schema_and_independent_setup_compatibility(self):
        options = {'platform': self.value['platform'], 'configuration_schema': 1}
        require_compatible(self.value, **options, setup_only=True, installed_host_api=1)
        for changes in ({'configuration_schema': 2}, {'platform': {}},
                        {'setup_only': True, 'installed_host_api': 3},
                        {'setup_only': True, 'installed_host_api': True}):
            with self.assertRaises(ValueError):
                require_compatible(self.value, **{**options, **changes})

    def test_host_bytes_verified_without_extraction(self):
        host = self.root / 'host.bin'
        host.write_bytes(b'fixture')
        self.assertEqual(verify_host(host, self.value)['size'], 7)
        for content in (b'changed', b'too-long', b''):
            host.write_bytes(content)
            with self.assertRaises(ValueError):
                verify_host(host, self.value)

    def test_archive_name_traversal_and_wrong_types_rejected(self):
        for changes in ({'file': '../../etc/passwd'}, {'size': True}, {'size': 0}, {'sha256': 'not-digest'}):
            value = deepcopy(self.value)
            value['host']['artifact'].update(changes)
            with self.assertRaises(ValueError):
                validate(value)

    def test_host_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(b'fixture')
            link = Path(directory) / 'link'
            link.symlink_to(target)
            with self.assertRaises(OSError):
                verify_host(link, self.value)


if __name__ == '__main__':
    unittest.main()
