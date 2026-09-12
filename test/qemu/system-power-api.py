#!/usr/bin/env python3
"""Submit one confirmed power action through a disposable appliance's live API."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import ssl
import urllib.request


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('base_url')
parser.add_argument('ca', type=Path)
parser.add_argument('password', type=Path)
parser.add_argument('action', choices=('reboot', 'shutdown'))
parser.add_argument('--status', metavar='JOB_ID')
args = parser.parse_args()
if args.base_url != 'https://127.0.0.1:24443/elderbrain':
    raise ValueError('This qualification helper accepts only the local disposable QEMU forward')
password = args.password.read_text().strip()
if not 12 <= len(password) <= 256:
    raise ValueError('Invalid disposable administrator credential')
context = ssl.create_default_context(cafile=str(args.ca))
cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                     urllib.request.HTTPCookieProcessor(cookies))


def request(path, *, body=None, csrf=None):
    data = None if body is None else json.dumps(body, separators=(',', ':')).encode()
    headers = {'Accept': 'application/json'}
    if body is not None:
        headers.update({'Content-Type': 'application/json', 'x-elderbrain-request': '1'})
    if csrf is not None:
        headers['x-csrf-token'] = csrf
    with opener.open(urllib.request.Request(args.base_url + path, data=data, headers=headers), timeout=45) as response:
        return response.status, response.headers, json.loads(response.read())


status, _, login = request('/api/auth/login', body={'username': 'admin', 'password': password})
assert status == 200 and login['authenticated'] is True and login['ready'] is True
status, _, session = request('/api/auth/session')
assert status == 200 and session['authenticated'] is True and session['ready'] is True
if args.status:
    status, _, jobs = request('/api/jobs')
    selected = next(job for job in jobs if job['id'] == args.status)
    assert status == 200 and selected['kind'] == 'power'
    assert selected['request'] == {'action': args.action, 'confirmPower': True}
    print(json.dumps({'state': 'live-system-power-visible', 'id': selected['id'],
                      'jobState': selected['state'], 'stage': selected.get('stage'),
                      'result': selected.get('result')}, sort_keys=True))
    raise SystemExit(0)
status, _, power = request('/api/system/power')
assert status == 200 and power['pending'] is False
selection = {'action': args.action, 'confirmPower': True}
status, headers, job = request('/api/system/power', body=selection, csrf=session['csrf'])
assert status == 202 and headers.get('Cache-Control') == 'no-store'
assert job['kind'] == 'power' and job['state'] in ('queued', 'running') and job['request'] == selection
print(json.dumps({'state': 'live-system-power-submitted', 'id': job['id'],
                  'action': args.action}, sort_keys=True))
