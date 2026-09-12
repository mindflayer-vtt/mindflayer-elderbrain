"""Restricted management operations; never confirm through the proxy bridge."""
import json
from pathlib import Path
import subprocess
import time

from host_network import discover
from network_config import request, confirmation_settings
from network_confirmation import issue
from network_listener import STATUS
from network_staging import prepare, prepare_restore
from network_worker import transaction


def available():
    for unit in ('elderbrain-network-recovery', 'elderbrain-network-watchdog', 'elderbrain-network-confirmation'):
        subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True, timeout=5)
    for name in ('ca.crt', 'ca.key'):
        if not (Path('/var/lib/mindflayer-elderbrain/traefik/tls') / name).is_file():
            raise ValueError('Appliance TLS initialization is incomplete')


def start(values):
    settings = request(values)
    available()
    links = [link for link in discover()['interfaces']
             if link['name'] == settings['interface'] and not link['internal']]
    if len(links) != 1 or links[0]['state'] != 'UP':
        raise ValueError('Choose an active appliance network interface')
    mac = (Path('/sys/class/net') / settings['interface'] / 'address').read_text().strip()
    candidate = prepare(settings, mac=mac)
    available()  # Validation may take time; recovery must still be running.
    token, binding = issue(settings)
    result = transaction().stage(candidate['changes'], settings['interface'],
        fingerprint=candidate['fingerprint'], confirmation=binding)
    # Return the plaintext capability once, only to the authenticated initiator.
    return {**result, 'token': token, 'warnings': candidate['warnings']}


def restore_files(archived, interface):
    """Private entry point for a verified checkpoint coordinator, not a raw API.

    Caller owns source pin/compatibility, rollback checkpoint and maintenance
    exclusion. The independent network worker still owns activation/deadline.
    """
    request({'interface': interface, 'mode': 'dhcp'})  # Validate interface syntax.
    available()
    links = [link for link in discover()['interfaces'] if link['name'] == interface and not link['internal']]
    if len(links) != 1 or links[0]['state'] != 'UP':
        raise ValueError('Choose an active appliance network interface')
    mac = (Path('/sys/class/net') / interface / 'address').read_text().strip()
    candidate = prepare_restore(archived)
    settings = confirmation_settings(candidate['configuration'], interface, mac)
    available()
    token, binding = issue(settings)
    result = transaction().stage(candidate['changes'], interface,
        fingerprint=candidate['fingerprint'], confirmation=binding)
    return {**result, 'token': token, 'warnings': [
        'The complete archived Netplan configuration will replace current network settings.',
        'Confirm through the selected interface before the deadline or all network changes will roll back.']}


def status():
    store = transaction()
    with store.locked():
        record = store.read()
        value = store.public(record)
        value['confirmation'] = None
        if record and record['phase'] == 'pending' and not store.expired(record):
            try:
                endpoint = json.loads(STATUS.read_text())
                age = time.time() - endpoint['at']
                if endpoint.get('ready') is True and endpoint.get('id') == record['id'] and 0 <= age <= 5:
                    value['confirmation'] = endpoint['url']
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return value


def cancel(identifier):
    return transaction().cancel(identifier)
