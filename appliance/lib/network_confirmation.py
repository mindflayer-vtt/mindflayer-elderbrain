"""Transaction-bound confirmation using a direct host connection destination.

Only the dedicated host TLS listener may construct ConnectionProof. Never expose
a management command that accepts a submitted destination address as this proof.
"""
from dataclasses import dataclass
import hashlib
import hmac
import secrets
import socket

from host_network import discover
from network_config import request


@dataclass(frozen=True)
class ConnectionProof:
    connection: socket.socket
    token: str


def issue(settings):
    selected = request(settings)
    token = secrets.token_urlsafe(32)
    return token, {'digest': hashlib.sha256(token.encode()).hexdigest(),
                   'mode': selected['mode'], 'address': selected.get('address')}


def verify(proof, record, interfaces=discover):
    """Called while the transaction lock is held; no HTTP headers are consulted."""
    if not isinstance(proof, ConnectionProof) or not isinstance(proof.connection, socket.socket):
        return False
    if not isinstance(proof.token, str) or len(proof.token) != 43:
        return False
    expected = record.get('confirmation')
    if not expected or record.get('phase') != 'pending':
        return False
    digest = hashlib.sha256(proof.token.encode()).hexdigest()
    if not hmac.compare_digest(digest, expected.get('digest', '')):
        return False
    try:
        # A real accepted host socket, not a proxied container address or Host.
        if proof.connection.family != socket.AF_INET:
            return False
        destination = proof.connection.getsockname()[0]
        proof.connection.getpeername()  # Reject unconnected/listening sockets.
        candidates = [link for link in interfaces()['interfaces']
                      if link['name'] == record['interface'] and not link.get('internal')]
        if len(candidates) != 1:
            return False
        current = [item for item in candidates[0]['addresses'] if item['address'] == destination]
        if len(current) != 1:
            return False
        if expected['mode'] == 'static':
            return destination == expected['address'] and current[0]['source'] == 'Static'
        return expected['mode'] == 'dhcp' and current[0]['source'] == 'DHCP'
    except (OSError, ValueError, KeyError, TypeError):
        return False
