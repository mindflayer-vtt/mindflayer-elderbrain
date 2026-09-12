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
        self.assertEqual(routes['lan-foundry']['service'], 'foundry@docker')
        self.assertEqual(routes['lan-mindflayer']['service'], 'mindflayer@docker')
        self.assertEqual(routes['lan-elderbrain-tls']['tls'], {})
        self.assertEqual(routes['lan-elderbrain']['middlewares'], ['elderbrain-https@docker'])
        for value in ['', 'a..b', '-a.test', 'a-.test', 'a`)', 'a\nb', 'a/b', 'a' * 64, None]:
            with self.assertRaises(ValueError):
                validate_domain(value)

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
