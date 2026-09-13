"""Loopback-only disposable-VM release fixture; exposes only signed artifacts."""
import http.server
from pathlib import Path
import shutil
import ssl
import sys
import time

root = Path(sys.argv[1]).resolve()
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/manifest.json', '/manifest.sig', '/elderbrain-host.tar.zst', '/elderbrain-dependencies.tar.zst'):
            self.send_error(404)
            return
        with (root / 'bundle' / self.path[1:]).open('rb') as data:
            self.send_response(200)
            self.send_header('Content-Length', str((root / 'bundle' / self.path[1:]).stat().st_size))
            self.end_headers()
            if (root / 'slow-artifacts').is_file() and self.path.endswith('.tar.zst'):
                while chunk := data.read(4096):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    time.sleep(0.01)
            else:
                shutil.copyfileobj(data, self.wfile)


server = http.server.ThreadingHTTPServer(('127.0.0.1', 18443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(root / 'tls.crt', root / 'tls.key')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
