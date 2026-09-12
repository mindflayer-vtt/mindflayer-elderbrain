from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from admin_tls import ensure_address, names, openssl


class AdminTLSTests(unittest.TestCase):
    def test_refresh_preserves_names_key_ca_config_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tls = root / 'tls'
            tls.mkdir()
            openssl(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', tls / 'ca.key',
                     '-out', tls / 'ca.crt', '-days', '1', '-subj', '/CN=test-CA',
                     '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
            openssl(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', tls / 'admin.key',
                     '-out', tls / 'request.pem', '-subj', '/CN=elderbrain',
                     '-addext', 'subjectAltName=DNS:elderbrain,DNS:localhost,IP:127.0.0.1,IP:10.0.2.15,IP:::1'])
            openssl(['x509', '-req', '-in', tls / 'request.pem', '-CA', tls / 'ca.crt', '-CAkey', tls / 'ca.key',
                     '-set_serial', '1', '-days', '1', '-copy_extensions', 'copy', '-out', tls / 'admin.crt'])
            config = root / 'admin-tls.yaml'
            config.write_text('# Existing custom settings must remain intact\ntls: {}\n')
            (tls / 'admin.crt').chmod(0o640)
            preserved = {path: path.read_bytes() for path in (tls / 'ca.crt', tls / 'ca.key', tls / 'admin.key', config)}
            before = names(tls / 'admin.crt')
            self.assertTrue(ensure_address('10.0.2.20', root))
            self.assertEqual(names(tls / 'admin.crt'), before + ['IP:10.0.2.20'])
            self.assertEqual((tls / 'admin.crt').stat().st_mode & 0o777, 0o640)
            openssl(['verify', '-CAfile', tls / 'ca.crt', '-verify_ip', '10.0.2.20', tls / 'admin.crt'])
            refreshed = (tls / 'admin.crt').read_bytes()
            self.assertFalse(ensure_address('10.0.2.20', root))
            self.assertEqual((tls / 'admin.crt').read_bytes(), refreshed)
            for path, original in preserved.items():
                self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(tls.glob('.refresh-*')))
