"""Explicit console selection and atomic autoinstall storage configuration.

Run from the payload root as ``python3 -m iso.storage_select``. This prepares
Curtin configuration; it does not invoke Curtin or format any device itself.
"""

import argparse
import json
import os
from pathlib import Path
import tempfile

import yaml

from appliance.lib.storage_guard import read_identity
from iso.storage_existing import read_existing
from iso.storage_prepare import prepare
from iso.storage_probe import probe
from iso.storage_console import read_line


def choose(inventory, ask=input, tell=print):
    tell('Mindflayer Elderbrain installation')
    tell('Fresh: ERASES THE ENTIRE SELECTED DISK. Preserve: reinstalls OS only;')
    tell('requires an existing supported Elderbrain data volume. Back up first.')
    for disk in inventory:
        # JSON quoting prevents disk strings from injecting terminal controls.
        tell(json.dumps({key: disk.get(key) for key in
                         ('path', 'serial', 'size', 'removable', 'read_only', 'in_use')}))
    mode = ask('Type fresh or preserve (anything else cancels): ').strip()
    if mode not in ('fresh', 'preserve'):
        raise ValueError('Installation cancelled')
    serial = ask('Enter the exact target disk serial: ').strip()
    matches = [disk for disk in inventory if disk.get('serial') == serial]
    if not serial or len(matches) != 1:
        raise ValueError('Selected serial is missing or ambiguous')
    data_uuid = None
    if mode == 'preserve':
        tell('Existing partition identities:')
        tell(json.dumps(matches[0].get('partitions', [])))
        data_uuid = ask('Enter the persistent Btrfs filesystem UUID: ').strip()
    phrase = f'ERASE {serial}' if mode == 'fresh' else f'REINSTALL OS {serial}'
    if ask(f'Type {json.dumps(phrase)} to confirm: ') != phrase:
        raise ValueError('Confirmation did not match; installation cancelled')
    return dict(mode=mode, serial=serial, data_uuid=data_uuid,
                erase_confirmed=mode == 'fresh')


def configure(document, selection, *, inventory_probe=probe, marker_reader=None,
              uefi=True):
    if not isinstance(document, dict):
        raise ValueError('Expected an autoinstall document')
    # Subiquity's /autoinstall.yaml may contain the normalized inner mapping,
    # while cloud-config input contains an outer autoinstall key.
    wrapped = 'autoinstall' in document
    configuration = document.get('autoinstall') if wrapped else document
    if not isinstance(configuration, dict):
        raise ValueError('Expected an autoinstall document')
    if configuration.get('version') != 1:
        raise ValueError('Unsupported autoinstall version')
    if marker_reader is None:
        marker_reader = lambda device, uuid: read_existing(
            device, uuid, read_identity=read_identity)
    result = prepare(**selection, inventory_probe=inventory_probe,
                     marker_reader=marker_reader, uefi=uefi)
    configured = {**configuration, 'storage': result['storage']}
    updated = {**document, 'autoinstall': configured} if wrapped else configured
    receipt = {'version': 1, 'mode': selection['mode'], 'serial': selection['serial'],
               'identity': result['identity']}
    return updated, receipt


def atomic_write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing a symlink output file')
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--autoinstall', required=True)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--console', default='/dev/tty3')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Installer storage selection requires root')
    document = yaml.safe_load(Path(args.autoinstall).read_text())
    # TTYs are not seekable: use separate read/write streams, not BufferedRandom
    # (r+), which can reject the device before presenting the first prompt.
    with open(args.console, 'r') as input_console, open(args.console, 'w') as console:
        def tell(message):
            console.write(message + '\n')
            console.flush()

        def ask(message):
            console.write(message)
            console.flush()
            if args.console == '/dev/tty3':
                return read_line(input_console)
            response = input_console.readline()
            if not response:
                raise ValueError('Console closed; installation cancelled')
            return response.rstrip('\r\n')

        selection = choose(probe(), ask=ask, tell=tell)
        updated, receipt = configure(document, selection,
                                     uefi=Path('/sys/firmware/efi').exists())
        # Install receipt first. If the config write fails, early-command failure
        # aborts installation; there is never a preserve plan without a receipt.
        atomic_write(args.receipt, json.dumps(receipt) + '\n')
        atomic_write(args.autoinstall, '#cloud-config\n' + yaml.safe_dump(updated))
        tell('Storage selection verified. Continuing installation.')


if __name__ == '__main__':
    main()
