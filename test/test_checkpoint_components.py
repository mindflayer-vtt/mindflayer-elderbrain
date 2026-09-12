from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from checkpoint_components import selection, preferences, keypad_settings


class ComponentBoundaryTests(unittest.TestCase):
    def test_network_is_separate_and_security_requires_explicit_consent(self):
        self.assertEqual(selection(['foundry']), ('foundry',))
        for values in (['foundry/worlds'], ['network', 'foundry'], ['security'], ['keypad-identities'], ['foundry', 'foundry']):
            with self.assertRaises(ValueError):
                selection(values)
        self.assertEqual(selection(['security'], confirm_security=True), ('security',))

    def test_preferences_preserve_current_onboarding_and_controller_fields(self):
        current = {'version': 1, 'configured': True, 'domain': 'current.local',
                   'views': [{'url': 'http://current.local', 'mode': 'admin'}],
                   'controllers': {'one': {'name': 'current'}}, 'futureField': 'keep'}
        archived = deepcopy(current)
        archived.update(configured=False, domain='old.local', controllers={})
        archived['views'][0]['url'] = 'http://old.local'
        result = preferences(current, archived)
        self.assertTrue(result['configured'])
        self.assertEqual(result['controllers'], current['controllers'])
        self.assertEqual(result['domain'], 'old.local')
        self.assertEqual(result['futureField'], 'keep')
        self.assertEqual(current['domain'], 'current.local')

    def test_keypad_preferences_keep_identity_and_invalidate_old_applied_proofs(self):
        settings = {'revision': 8, 'ssid': 'Table', 'psk': 'fixture-password',
                    'serverHost': 'table.local', 'serverPort': 10443}
        current = {'one': {'id': 'one', 'name': 'New', 'seat': '', 'desiredRevision': 12,
                          'appliedRevision': 12, 'registration': 'registered',
                          'chipMac': 'aa:bb:cc:dd:ee:ff', 'installationVerifiedAt': 400,
                          'configurationDigest': 'new-proof', 'connection': 'connected'}}
        archived = {'one': {'id': 'one', 'name': 'Old', 'seat': 'North', 'desiredRevision': 2,
                           'chipMac': 'must-not-restore', 'installationVerifiedAt': 1},
                    'retired': {'id': 'retired', 'desiredRevision': 1}}
        result = keypad_settings(settings, current, {**settings, 'revision': 2}, archived)
        self.assertEqual(result['settings']['revision'], 13)
        record = result['records']['one']
        self.assertEqual(record['name'], 'Old')
        self.assertEqual(record['chipMac'], current['one']['chipMac'])
        self.assertEqual(record['installationVerifiedAt'], 400)
        self.assertIsNone(record['appliedRevision'])
        self.assertIsNone(record['configurationDigest'])
        self.assertEqual(result['expectations'], {})
        self.assertEqual(result['absentDeviceIds'], ['retired'])
        self.assertNotIn('retired', result['records'])
        self.assertEqual(current['one']['name'], 'New')
