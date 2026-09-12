"""Narrow direct-host TLS endpoint for authenticated network confirmation.

The setup app supplies the transaction token in a JSON POST, never a URL. No
cookies are accepted, no request bodies/paths are logged, and no proxy headers
are used as destination evidence. Lifecycle/binding is owned by the host service.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import socket
import socketserver
import ssl
import threading

from network_confirmation import ConnectionProof


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *_args):
        pass

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        # Capability authentication only; never allow browser credentials here.
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.reply(200 if self.path == '/confirm' else 404, {})

    def do_GET(self):
        self.reply(200 if self.path == '/' else 404, {'service': 'Elderbrain network confirmation'})

    def do_POST(self):
        try:
            lengths = self.headers.get_all('Content-Length', [])
            types = self.headers.get_all('Content-Type', [])
            if (len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,4}', lengths[0])
                    or not 0 < int(lengths[0]) <= 4096
                    or self.headers.get('Transfer-Encoding') is not None):
                raise ValueError()
            # Consume small rejected bodies before closing TLS so the error
            # response is not lost to a TCP reset caused by unread request data.
            body = self.rfile.read(int(lengths[0]))
            if len(body) > 512 or types != ['application/json']:
                raise ValueError()
            if self.path != '/confirm':
                self.reply(404, {'error': 'Not found'})
                return
            value = json.loads(body)
            if (len(body) != int(lengths[0]) or not isinstance(value, dict)
                    or set(value) != {'id', 'token'}
                    or not isinstance(value['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['id'])
                    or not isinstance(value['token'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', value['token'])):
                raise ValueError()
        except (ValueError, TypeError):
            self.reply(400, {'error': 'Invalid confirmation request'})
            return
        try:
            self.server.store.confirm(value['id'], ConnectionProof(self.connection, value['token']))
        except Exception:
            self.reply(409, {'error': 'Confirmation rejected; reconnect before the rollback deadline'})
            return
        self.reply(200, {'phase': 'confirmed'})


class ConfirmationServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, context, store, interface=None):
        if not isinstance(context, ssl.SSLContext) or context.protocol != ssl.PROTOCOL_TLS_SERVER:
            raise ValueError('A server TLS context is required')
        self.context, self.store = context, store
        self.interface = interface
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def server_bind(self):
        if self.interface is not None:
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', self.interface):
                raise ValueError('Invalid confirmation interface')
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode() + b'\0')
        super().server_bind()

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(5)
            with self.context.wrap_socket(request, server_side=True) as connection:
                self.finish_request(connection, client_address)
        except Exception:
            # TLS/parse/disconnect failures must never dump a request or token.
            pass
        finally:
            self.shutdown_request(request)
            self.slots.release()
