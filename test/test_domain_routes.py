import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from domain_routes import document, publish, reconcile, validate_domain
from display_preview import DisplayPreview


class DomainRoutesTests(unittest.TestCase):
    def test_routes_and_injection_rejection(self):
        routes = document('table.example')['http']['routers']
        self.assertEqual(routes['lan-foundry']['rule'], 'Host(`foundry.table.example`)')
        self.assertEqual(routes['lan-foundry']['service'], 'foundry')
        self.assertEqual(routes['lan-foundry']['middlewares'], ['foundry-https'])
        self.assertEqual(routes['lan-foundry-tls']['tls'], {})
        self.assertEqual(routes['lan-foundry-tls']['entryPoints'], ['websecure'])
        self.assertEqual(routes['lan-mindflayer']['service'], 'mindflayer')
        self.assertEqual(routes['lan-elderbrain-tls']['tls'], {})
        self.assertEqual(routes['lan-elderbrain']['middlewares'], ['elderbrain-https'])
        self.assertIn('PathPrefix(`/elderbrain`)', routes['lan-elderbrain']['rule'])
        services = document('table.example')['http']['services']
        self.assertEqual(services['elderbrain']['loadBalancer']['servers'],
                         [{'url': 'http://elderbrain-setup:8080'}])
        self.assertEqual(services['mindflayer']['loadBalancer']['servers'],
                         [{'url': 'http://mindflayer-server:8080'}])
        self.assertEqual(services['foundry']['loadBalancer']['servers'],
                         [{'url': 'http://foundry:30000'}])
        for value in ['', 'a..b', '-a.test', 'a-.test', 'a`)', 'a\nb', 'a/b', 'a' * 64, None]:
            with self.assertRaises(ValueError):
                validate_domain(value)
        compose = (Path(__file__).resolve().parents[1] / 'compose/compose.yaml').read_text()
        self.assertNotIn('providers.docker', compose)
        self.assertNotIn('/var/run/docker.sock', compose)
        self.assertNotIn('traefik.http.', compose)
        self.assertIn('/traefik/dynamic:/etc/traefik/dynamic:ro', compose)
        self.assertIn('/traefik/tls:/etc/traefik/tls:ro', compose)
        self.assertNotIn('/host/admin-ca:/etc/traefik', compose)
        self.assertIn('FOUNDRY_PROXY_SSL: "true"', compose)
        self.assertIn('FOUNDRY_PROXY_PORT: "443"', compose)
        self.assertNotIn('FOUNDRY_HOSTNAME:', compose)
        self.assertIn('ELDERBRAIN_TRUSTED_PROXY_IP: 172.31.254.2', compose)
        self.assertIn('ipv4_address: 172.31.254.2', compose)
        self.assertIn('--entrypoints.websecure.forwardedheaders.notappendxforwardedfor=false', compose)
        prepare = (Path(__file__).resolve().parents[1] / 'provisioning/prepare-admin').read_text()
        self.assertIn('python3 "$runtime/domain_routes.py" "$state"', prepare)

    def test_confirmation_recovery_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'elderbrain').mkdir()
            store = DisplayPreview(directory, reboot_id='test', apply=lambda: None, publisher=reconcile)
            old = {'configured': True, 'domain': 'old.test', 'views': [{'url': 'http://foundry.old.test'}]}
            store.config.write_text(json.dumps(old))
            reconcile(root)
            target = root / 'traefik/dynamic/lan-routes.yaml'
            before = target.read_bytes()
            pending = store.begin({**old, 'domain': 'table.example'})
            store.recover()
            self.assertEqual(target.read_bytes(), before)
            store.confirm(pending['id'])
            self.assertIn('foundry.table.example', target.read_text())
            timestamp = target.stat().st_mtime_ns
            store.recover()
            self.assertEqual(target.stat().st_mtime_ns, timestamp)
            # Rebuild a missing projection on boot/after restore from committed settings.
            target.unlink()
            store.recover()
            self.assertIn('foundry.table.example', target.read_text())

    def test_publish_prepares_certificate_before_https_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'elderbrain').mkdir()
            (root / 'elderbrain/config.json').write_text(json.dumps({'domain': 'table.example'}))
            target = root / 'traefik/dynamic/lan-routes.yaml'
            def certificate(domain, tls, ca):
                self.assertEqual(domain, 'table.example')
                self.assertFalse(target.exists())
            with patch('admin_tls.ensure_domain', side_effect=certificate) as ensure:
                publish(root)
            ensure.assert_called_once_with('table.example', root / 'traefik', root / 'host/admin-ca')
            self.assertIn('lan-foundry-tls', target.read_text())

    def test_cancel_keeps_committed_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'elderbrain').mkdir()
            store = DisplayPreview(directory, reboot_id='test', apply=lambda: None, publisher=reconcile)
            pending = store.begin({'configured': True, 'domain': 'new.test', 'views': [{'url': 'http://new.test'}]})
            store.cancel(pending['id'])
            store.recover()
            self.assertNotIn('new.test', (root / 'traefik/dynamic/lan-routes.yaml').read_text())

    def test_reconcile_rejects_an_unsafe_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'traefik/dynamic/lan-routes.yaml'
            target.parent.mkdir(parents=True, mode=0o700)
            outside = root / 'outside'
            outside.write_text('unchanged')
            target.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'Unsafe LAN route projection'):
                reconcile(root)
            self.assertEqual(outside.read_text(), 'unchanged')
