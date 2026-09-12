"""First-boot HTTPS and auth checks; no passwords or cookies enter test output."""
import http.client
import json
from pathlib import Path
import ssl

state = Path("/var/lib/mindflayer-elderbrain")
settings = dict(line.split("=", 1) for line in Path("/opt/mindflayer-elderbrain/appliance.env").read_text().splitlines()
                if "=" in line and not line.startswith("#"))
host = settings["ELDERBRAIN_HOST"]
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
assert code in (301, 302, 307, 308), "HTTP administration did not redirect"
assert headers.get("location", "").startswith("https://"), "Redirect is not HTTPS"
for path in ("/health", "/elderbrain/health", "/elderbrain/"):
    assert request(path)[0] == 200, f"HTTPS route unavailable: {path}"
for prefix in ("/api/", "/elderbrain/api/"):
    for route in ("config", "jobs", "keypads", "logs/foundry", "borg/settings"):
        assert request(prefix + route)[0] == 401, "Unauthorized API access"
password = (state / "elderbrain/secrets/initial-password").read_text().strip()
assert len(password) >= 24, "Initial password is not unique-length random material"
code, headers, body = request("/elderbrain/api/auth/login", method="POST", data={"username": "admin", "password": password})
assert code == 200, "Bootstrap login failed"
session = json.loads(body)
assert session["authenticated"] and session["mustChange"] and not session["ready"], "First-login gate is missing"
cookie_header = headers.get("set-cookie", "")
assert all(flag in cookie_header.lower() for flag in ("secure", "httponly", "samesite=strict")), "Unsafe session cookie"
cookie = cookie_header.split(";", 1)[0]
assert request("/elderbrain/api/config", cookie=cookie)[0] == 403, "Onboarding did not gate administration"
assert request("/elderbrain/api/auth/logout", method="POST", data={}, cookie=cookie)[0] == 403, "Missing CSRF accepted"
assert request("/elderbrain/api/auth/logout", method="POST", data={}, cookie=cookie, csrf=session["csrf"])[0] == 200
assert request("/elderbrain/api/config", cookie=cookie)[0] == 401, "Logout did not revoke session"
print("Verified administration CA, HTTPS routes, initial-login gate, secure cookie, CSRF and logout")
