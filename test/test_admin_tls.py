from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from admin_tls import ensure_address, ensure_domain, install_authority, migrate_layout, names, openssl, validate_layout


class AdminTLSTests(unittest.TestCase):
    def test_import_custom_ca_and_root_reissues_existing_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tls, ca = root / 'tls', root / 'admin-ca'
            tls.mkdir(); ca.mkdir(mode=0o700); (root / 'dynamic').mkdir(mode=0o700)
            openssl(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', ca / 'ca.key',
                     '-out', ca / 'ca.crt', '-days', '1', '-subj', '/CN=old',
                     '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
            openssl(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', tls / 'admin.key',
                     '-out', root / 'request.pem', '-subj', '/CN=elderbrain',
                     '-addext', 'subjectAltName=DNS:elderbrain,IP:127.0.0.1'])
            openssl(['x509', '-req', '-in', root / 'request.pem', '-CA', ca / 'ca.crt', '-CAkey', ca / 'ca.key',
                     '-set_serial', '1', '-days', '1', '-copy_extensions', 'copy', '-out', tls / 'admin.crt'])
            (tls / 'ca.crt').write_bytes((ca / 'ca.crt').read_bytes())
            (root / 'dynamic/admin-tls.yaml').write_text('tls: {}\n')
            openssl(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', root / 'root.key',
                     '-out', root / 'root.crt', '-days', '3', '-subj', '/CN=custom root',
                     '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
            openssl(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', root / 'signer.key',
                     '-out', root / 'signer.csr', '-subj', '/CN=custom signer'])
            (root / 'ca-ext').write_text('basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n')
            openssl(['x509', '-req', '-in', root / 'signer.csr', '-CA', root / 'root.crt', '-CAkey', root / 'root.key',
                     '-set_serial', '2', '-days', '2', '-extfile', root / 'ca-ext', '-out', root / 'signer.crt'])
            old = (ca / 'ca.crt').read_bytes()
            with self.assertRaises(ValueError):
                install_authority((root / 'signer.crt').read_text(), (root / 'root.key').read_text(),
                                  (root / 'root.crt').read_text(), root, ca, publish_trust=False)
            self.assertEqual((ca / 'ca.crt').read_bytes(), old)
            with self.assertRaises(ValueError):
                install_authority((root / 'signer.crt').read_text(), (root / 'signer.key').read_text(),
                                  old.decode(), root, ca, publish_trust=False)
            self.assertEqual((ca / 'ca.crt').read_bytes(), old)
            self.assertEqual(install_authority((root / 'signer.crt').read_text(),
                             (root / 'signer.key').read_text(), (root / 'root.crt').read_text(),
                             root, ca, publish_trust=False)['state'], 'installed')
            self.assertEqual(validate_layout(root, ca), {'state': 'valid'})
            self.assertEqual(names(tls / 'admin.crt'), ['DNS:elderbrain', 'IP:127.0.0.1'])
            openssl(['verify', '-CAfile', ca / 'trust-root.crt', '-untrusted', ca / 'ca.crt',
                     '-verify_hostname', 'elderbrain', tls / 'admin.crt'])
            self.assertTrue(ensure_address('10.0.2.20', root, ca))
            openssl(['verify', '-CAfile', ca / 'trust-root.crt', '-untrusted', ca / 'ca.crt',
                     '-verify_ip', '10.0.2.20', tls / 'admin.crt'])

    def test_refresh_preserves_names_key_ca_config_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tls = root / 'tls'
            ca = root / 'admin-ca'
            tls.mkdir(); ca.mkdir(mode=0o700)
            (root / 'dynamic').mkdir(mode=0o700)
            openssl(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', ca / 'ca.key',
                     '-out', ca / 'ca.crt', '-days', '1', '-subj', '/CN=test-CA',
                     '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
            openssl(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', tls / 'admin.key',
                     '-out', tls / 'request.pem', '-subj', '/CN=elderbrain',
                     '-addext', 'subjectAltName=DNS:elderbrain,DNS:localhost,IP:127.0.0.1,IP:10.0.2.15,IP:::1'])
            openssl(['x509', '-req', '-in', tls / 'request.pem', '-CA', ca / 'ca.crt', '-CAkey', ca / 'ca.key',
                     '-set_serial', '1', '-days', '1', '-copy_extensions', 'copy', '-out', tls / 'admin.crt'])
            (tls / 'ca.crt').write_bytes((ca / 'ca.crt').read_bytes())
            config = root / 'dynamic/admin-tls.yaml'
            config.write_text('# Existing custom settings must remain intact\ntls: {}\n')
            (tls / 'admin.crt').chmod(0o640)
            preserved = {path: path.read_bytes() for path in (ca / 'ca.crt', ca / 'ca.key',
                                                               tls / 'ca.crt', tls / 'admin.key', config)}
            before = names(tls / 'admin.crt')
            self.assertEqual(validate_layout(root, ca), {'state': 'valid'})
            self.assertTrue(ensure_address('10.0.2.20', root, ca))
            self.assertEqual(names(tls / 'admin.crt'), before + ['IP:10.0.2.20'])
            self.assertEqual((tls / 'admin.crt').stat().st_mode & 0o777, 0o640)
            openssl(['verify', '-CAfile', tls / 'ca.crt', '-verify_ip', '10.0.2.20', tls / 'admin.crt'])
            refreshed = (tls / 'admin.crt').read_bytes()
            self.assertFalse(ensure_address('10.0.2.20', root, ca))
            self.assertEqual((tls / 'admin.crt').read_bytes(), refreshed)
            self.assertTrue(ensure_domain('table.example', root, ca))
            self.assertIn('DNS:elderbrain.table.example', names(tls / 'admin.crt'))
            self.assertIn('DNS:foundry.table.example', names(tls / 'admin.crt'))
            self.assertIn('DNS:mindflayer.table.example', names(tls / 'admin.crt'))
            openssl(['verify', '-CAfile', tls / 'ca.crt', '-verify_hostname',
                     'foundry.table.example', tls / 'admin.crt'])
            openssl(['verify', '-CAfile', tls / 'ca.crt', '-verify_hostname',
                     'mindflayer.table.example', tls / 'admin.crt'])
            self.assertFalse(ensure_domain('table.example', root, ca))
            for path, original in preserved.items():
                self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(tls.glob('.refresh-*')))

    def test_validator_rejects_ca_key_in_served_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tls, ca = root / 'tls', root / 'admin-ca'
            tls.mkdir(); ca.mkdir(mode=0o700); (root / 'dynamic').mkdir(mode=0o700)
            (tls / 'ca.key').write_text('exposed')
            with self.assertRaisesRegex(ValueError, 'must not be present'):
                validate_layout(root, ca)

    def test_legacy_dynamic_config_migrates_without_exposing_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / 'admin-tls.yaml'
            legacy.write_text('certFile: /etc/traefik/dynamic/tls/admin.crt\n')
            self.assertTrue(migrate_layout(root))
            target = root / 'dynamic/admin-tls.yaml'
            self.assertEqual(target.read_text(), 'certFile: /etc/traefik/tls/admin.crt\n')
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertFalse(migrate_layout(root))
