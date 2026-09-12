"""Pending-only confirmation listener, separate from the rollback process."""
import json
import os
from pathlib import Path
import secrets
import threading
import time

from host_network import discover
from network_config import unicast
from network_https import ConfirmationServer
from network_tls import context
from network_worker import transaction
from admin_tls import ensure_address

PORT = 10444
STATUS = Path('/run/elderbrain-network-confirmation/status.json')


def selected(record, store, interfaces):
    if not record or record['phase'] != 'pending' or store.expired(record) or not record.get('confirmation'):
        return None
    binding = record['confirmation']
    links = [link for link in interfaces()['interfaces']
             if link['name'] == record['interface'] and not link.get('internal')]
    if len(links) != 1:
        return None
    source = 'Static' if binding['mode'] == 'static' else 'DHCP'
    addresses = [item['address'] for item in links[0]['addresses'] if item['source'] == source
                 and (source == 'DHCP' or item['address'] == binding['address'])]
    if len(addresses) != 1:
        return None
    return record['id'], record['interface'], unicast(addresses[0])


def publish(value):
    STATUS.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATUS.parent / ('.status-' + secrets.token_hex(8))
    with open(temporary, 'x') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump({**value, 'at': time.time()}, stream)
    os.replace(temporary, STATUS)


class Listener:
    def __init__(self, store, interfaces=discover, tls=context, server=ConfirmationServer, output=publish):
        self.store, self.interfaces, self.tls, self.factory, self.output = store, interfaces, tls, server, output
        self.active = self.server = self.thread = None

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
        self.active = self.server = self.thread = None
        self.output({'ready': False})

    def tick(self):
        try:
            wanted = selected(self.store.read(), self.store, self.interfaces)
            if wanted != self.active:
                self.close()
                if wanted:
                    identifier, interface, address = wanted
                    certificate = self.tls(address)
                    # Certificate generation may outlive the transaction deadline.
                    if selected(self.store.read(), self.store, self.interfaces) != wanted:
                        return
                    self.server = self.factory((address, PORT), certificate, self.store, interface=interface)
                    self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
                    self.thread.start()
                    self.active = wanted
            if self.active:
                self.output({'ready': True, 'id': self.active[0],
                             'url': f'https://{self.active[2]}:{PORT}/confirm'})
            else:
                self.output({'ready': False})
        except Exception:
            self.close()
            raise


def main():
    if os.geteuid() != 0:
        raise SystemExit('Network confirmation listener requires root')
    def prepare_tls(address):
        ensure_address(address)
        return context(address)
    listener = Listener(transaction(), tls=prepare_tls)
    while True:
        try:
            listener.tick()
        except Exception:
            print('Network confirmation unavailable; timed rollback remains active.', flush=True)
        time.sleep(1)


if __name__ == '__main__':
    main()
