from contextlib import nullcontext
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
import network_service as service


class NetworkServiceTests(unittest.TestCase):
    @patch.object(service, 'available')
    @patch.object(service, 'discover')
    @patch.object(service.Path, 'read_text', return_value='52:54:00:12:34:56')
    @patch.object(service, 'prepare_restore')
    @patch.object(service, 'transaction')
    def test_restore_uses_archived_address_and_keeps_configuration_private(self, transaction, prepare, _read, discover, available):
        discover.return_value = {'interfaces': [{'name': 'ens3', 'internal': False, 'state': 'UP'}]}
        changes = {'50-test.yaml': {'before': b'private-current', 'after': b'private-archived'}}
        prepare.return_value = {'changes': changes, 'fingerprint': 'a' * 64,
            'configuration': {'network': {'ethernets': {'ens3': {'addresses': ['10.0.2.20/24']}}}}}
        transaction.return_value.stage.return_value = {'id': 'b' * 32, 'phase': 'staged'}
        archived = {'50-test.yaml': b'private-archived'}
        result = service.restore_files(archived, 'ens3', restore_owner='c' * 32)
        prepare.assert_called_once_with(archived)
        call = transaction.return_value.stage.call_args
        self.assertEqual(call.args, (changes, 'ens3'))
        self.assertEqual(call.kwargs['confirmation']['address'], '10.0.2.20')
        self.assertEqual(call.kwargs['confirmation']['mode'], 'static')
        self.assertEqual(call.kwargs['restore_owner'], 'c' * 32)
        self.assertNotIn(result['token'], str(call.kwargs))
        self.assertNotIn('private-', str(result))
        self.assertEqual(available.call_count, 2)
        deferred = service.restore_files(archived, 'ens3', restore_owner='c' * 32, confirmation_digest='d' * 64)
        self.assertNotIn('token', deferred)
        self.assertEqual(transaction.return_value.stage.call_args.kwargs['confirmation']['digest'], 'd' * 64)
        prepare.return_value['configuration']['network']['ethernets']['ens3']['dhcp4'] = True
        transaction.reset_mock()
        with self.assertRaises(ValueError):
            service.restore_files(archived, 'ens3')
        transaction.assert_not_called()

    @patch.object(service, 'available')
    @patch.object(service, 'discover')
    @patch.object(service.Path, 'read_text', return_value='52:54:00:12:34:56')
    @patch.object(service, 'prepare')
    @patch.object(service, 'transaction')
    def test_authenticated_start_prepares_and_binds_token_once(self, transaction, prepare, _read, discover, available):
        discover.return_value = {'interfaces': [{'name': 'ens3', 'internal': False, 'state': 'UP'}]}
        prepare.return_value = {'changes': {'50-test.yaml': {}}, 'fingerprint': 'a' * 64, 'warnings': []}
        transaction.return_value.stage.return_value = {'id': 'b' * 32, 'phase': 'staged'}
        result = service.start({'interface': 'ens3', 'mode': 'dhcp'})
        self.assertEqual(available.call_count, 2)
        self.assertEqual(len(result['token']), 43)
        binding = transaction.return_value.stage.call_args.kwargs['confirmation']
        self.assertNotIn(result['token'], str(binding))
        self.assertEqual(binding['mode'], 'dhcp')
        self.assertEqual(transaction.return_value.stage.call_args.kwargs['fingerprint'], 'a' * 64)

    @patch.object(service, 'available')
    @patch.object(service, 'discover')
    @patch.object(service, 'prepare')
    def test_internal_or_inactive_interface_cannot_stage(self, prepare, discover, _available):
        for link in ({'name': 'ens3', 'internal': True, 'state': 'UP'},
                     {'name': 'ens3', 'internal': False, 'state': 'DOWN'}):
            discover.return_value = {'interfaces': [link]}
            with self.assertRaises(ValueError):
                service.start({'interface': 'ens3', 'mode': 'dhcp'})
        prepare.assert_not_called()

    @patch.object(service.time, 'time', return_value=100)
    @patch.object(service, 'STATUS')
    @patch.object(service, 'transaction')
    def test_status_exposes_only_fresh_matching_endpoint_and_never_token(self, transaction, status, _time):
        store = transaction.return_value
        store.locked.side_effect = nullcontext
        store.read.return_value = {'id': 'a' * 32, 'phase': 'pending', 'confirmation': {'digest': 'private'}}
        store.public.side_effect = lambda record: {key: record[key] for key in ('id', 'phase')}
        store.expired.return_value = False
        endpoint = {'id': 'a' * 32, 'ready': True, 'at': 99, 'url': 'https://10.0.2.20:10444/confirm'}
        status.read_text.return_value = json.dumps(endpoint)
        self.assertEqual(service.status()['confirmation'], endpoint['url'])
        for change in ({'id': 'b' * 32}, {'at': 90}, {'at': 101}, {'ready': False}):
            status.read_text.return_value = json.dumps({**endpoint, **change})
            self.assertIsNone(service.status()['confirmation'])
        self.assertNotIn('private', str(service.status()))

    @patch.object(service.subprocess, 'run')
    @patch.object(service.Path, 'is_file', return_value=True)
    def test_all_recovery_services_are_checked_individually(self, _file, run):
        service.available()
        self.assertEqual(run.call_count, 3)
        self.assertTrue(all(len(call.args[0]) == 4 for call in run.call_args_list))
