"""First-boot HTTPS and auth checks; no passwords or cookies enter test output."""
import http.client
import json
import os
from pathlib import Path
import ssl
import stat
import socket

state = Path("/var/lib/mindflayer-elderbrain")
settings = dict(line.split("=", 1) for line in Path("/opt/mindflayer-elderbrain/appliance.env").read_text().splitlines()
                if "=" in line and not line.startswith("#"))
host = settings["ELDERBRAIN_HOST"]
domain = json.loads((state / 'elderbrain/config.json').read_text()).get('domain', 'elderbrain.local')
foundry_host = 'foundry.' + domain
context = ssl.create_default_context(cafile=str(state / "traefik/tls/ca.crt"))


def request(path, *, method="GET", data=None, cookie=None, csrf=None, secure=True):
    connection = (http.client.HTTPSConnection("127.0.0.1", context=context, timeout=15)
                  if secure else http.client.HTTPConnection("127.0.0.1", timeout=15))
    headers = {"Host": host}
    if data is not None:
        headers.update({"Content-Type": "application/json", "x-elderbrain-request": "1"})
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["x-csrf-token"] = csrf
    try:
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, body
    finally:
        connection.close()


code, headers, _ = request("/elderbrain/", secure=False)
assert code in (301, 308), "HTTP administration did not redirect permanently"
assert headers.get("location", "").startswith("https://"), "Redirect is not HTTPS"
connection = http.client.HTTPConnection('127.0.0.1', timeout=15)
connection.request('GET', '/', headers={'Host': foundry_host})
response = connection.getresponse()
response.read()
assert response.status in (301, 308), 'HTTP Foundry did not redirect permanently'
assert response.getheader('Location', '').startswith('https://'), 'Foundry redirect is not HTTPS'
connection.close()
with socket.create_connection(('127.0.0.1', 443), timeout=15) as plain:
    with context.wrap_socket(plain, server_hostname=foundry_host) as secure:
        alternatives = secure.getpeercert().get('subjectAltName', ())
        assert ('DNS', foundry_host) in alternatives, 'Foundry hostname is absent from the served certificate'
for path in ("/health", "/elderbrain/health", "/elderbrain/"):
    assert request(path)[0] == 200, f"HTTPS route unavailable: {path}"
for prefix in ("/api/", "/elderbrain/api/"):
    for route in ("config", "jobs", "keypads", "logs/foundry", "borg/settings"):
        assert request(prefix + route)[0] == 401, "Unauthorized API access"
credential = os.environ.get("ELDERBRAIN_TEST_ADMIN_PASSWORD")
password_file = Path(credential) if credential else state / "elderbrain/secrets/initial-password"
if credential:
    assert password_file.parent.parent == Path("/root")
    assert password_file.parent.name.startswith("elderbrain-live-admin-")
    info = password_file.stat()
    assert info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
password = password_file.read_text().strip()
assert len(password) >= 24, "Initial password is not unique-length random material"
code, headers, body = request("/elderbrain/api/auth/login", method="POST", data={"username": "admin", "password": password})
assert code == 200, "Bootstrap login failed"
session = json.loads(body)
assert session["authenticated"], "Authenticated session is missing"
if credential:
    assert not session["mustChange"] and session["ready"], "Ready administrator state is missing"
else:
    assert session["mustChange"] and not session["ready"], "First-login gate is missing"
cookie_header = headers.get("set-cookie", "")
assert all(flag in cookie_header.lower() for flag in ("secure", "httponly", "samesite=strict")), "Unsafe session cookie"
cookie = cookie_header.split(";", 1)[0]
expected = 200 if credential else 403
assert request("/elderbrain/api/config", cookie=cookie)[0] == expected, "Administration readiness gate is incorrect"
assert request("/elderbrain/api/auth/logout", method="POST", data={}, cookie=cookie)[0] == 403, "Missing CSRF accepted"
assert request("/elderbrain/api/auth/logout", method="POST", data={}, cookie=cookie, csrf=session["csrf"])[0] == 200
assert request("/elderbrain/api/config", cookie=cookie)[0] == 401, "Logout did not revoke session"
print("Verified administration CA, HTTPS routes, authentication gate, secure cookie, CSRF and logout")
