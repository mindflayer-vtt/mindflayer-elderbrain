import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from domain_routes import document, reconcile, validate_domain
from display_preview import DisplayPreview


class DomainRoutesTests(unittest.TestCase):
    def test_routes_and_injection_rejection(self):
        routes = document('home.viromania.com')['http']['routers']
        self.assertEqual(routes['lan-foundry']['rule'], 'Host(`foundry.home.viromania.com`)')
        self.assertEqual(routes['lan-foundry']['service'], 'foundry')
        self.assertEqual(routes['lan-mindflayer']['service'], 'mindflayer')
        self.assertEqual(routes['lan-elderbrain-tls']['tls'], {})
        self.assertEqual(routes['lan-elderbrain']['middlewares'], ['elderbrain-https'])
        self.assertIn('PathPrefix(`/elderbrain`)', routes['lan-elderbrain']['rule'])
        services = document('home.viromania.com')['http']['services']
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
        self.assertNotIn('/traefik:/etc/traefik/dynamic', compose)
        self.assertNotIn('ca.key:/etc/traefik', compose)
        self.assertIn('/traefik/tls/admin.key:/etc/traefik/dynamic/tls/admin.key:ro', compose)
        prepare = (Path(__file__).resolve().parents[1] / 'provisioning/prepare-admin').read_text()
        self.assertIn('python3 "$runtime/domain_routes.py" "$state"', prepare)

    def test_confirmation_recovery_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'elderbrain').mkdir()
            store = DisplayPreview(directory, reboot_id='test', apply=lambda: None)
            old = {'configured': True, 'domain': 'old.test', 'views': [{'url': 'http://foundry.old.test'}]}
            store.config.write_text(json.dumps(old))
            reconcile(root)
            target = root / 'traefik/lan-routes.yaml'
            before = target.read_bytes()
            pending = store.begin({**old, 'domain': 'home.viromania.com'})
            store.recover()
            self.assertEqual(target.read_bytes(), before)
            store.confirm(pending['id'])
            self.assertIn('foundry.home.viromania.com', target.read_text())
            timestamp = target.stat().st_mtime_ns
            store.recover()
            self.assertEqual(target.stat().st_mtime_ns, timestamp)
            # Rebuild a missing projection on boot/after restore from committed settings.
            target.unlink()
            store.recover()
            self.assertIn('foundry.home.viromania.com', target.read_text())

    def test_cancel_keeps_committed_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'elderbrain').mkdir()
            store = DisplayPreview(directory, reboot_id='test', apply=lambda: None)
            pending = store.begin({'configured': True, 'domain': 'new.test', 'views': [{'url': 'http://new.test'}]})
            store.cancel(pending['id'])
            store.recover()
            self.assertNotIn('new.test', (root / 'traefik/lan-routes.yaml').read_text())
