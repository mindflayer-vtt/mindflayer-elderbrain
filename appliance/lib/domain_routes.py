"""Project the committed LAN domain into Traefik without restarting containers."""
import json
import os
from pathlib import Path
import re
import secrets


def validate_domain(value):
    if not isinstance(value, str) or len(value) > 242 or not value:
        raise ValueError('Invalid LAN domain')
    if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
           for label in value.split('.')):
        raise ValueError('Invalid LAN domain')
    return value


def document(domain):
    domain = validate_domain(domain)
    routers = {}
    for name in ('foundry', 'mindflayer', 'elderbrain'):
        router = {'rule': f'Host(`{name}.{domain}`)', 'entryPoints': ['web'],
                  'service': name, 'priority': 100}
        if name == 'elderbrain':
            router['rule'] += ' || PathPrefix(`/elderbrain`)'
            router['middlewares'] = ['elderbrain-https']
            routers['lan-elderbrain-tls'] = {
                **router, 'entryPoints': ['websecure'], 'tls': {},
                'middlewares': ['elderbrain-strip']}
        routers['lan-' + name] = router
    services = {
        'elderbrain': {'loadBalancer': {'servers': [{'url': 'http://elderbrain-setup:8080'}]}},
        'mindflayer': {'loadBalancer': {'servers': [{'url': 'http://mindflayer-server:8080'}]}},
        'foundry': {'loadBalancer': {'servers': [{'url': 'http://foundry:30000'}]}},
    }
    middlewares = {
        'elderbrain-https': {'redirectScheme': {'scheme': 'https'}},
        'elderbrain-strip': {'stripPrefix': {'prefixes': ['/elderbrain']}},
    }
    return {'http': {'routers': routers, 'services': services, 'middlewares': middlewares}}


def reconcile(state):
    state = Path(state)
    try:
        config = json.loads((state / 'elderbrain/config.json').read_text())
    except FileNotFoundError:
        config = {}
    content = json.dumps(document(config.get('domain', 'elderbrain.local')), indent=2) + '\n'
    target = state / 'traefik/lan-routes.yaml'
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists() and target.read_text() == content:
        return
    temporary = target.parent / ('.routes-' + secrets.token_hex(16))
    try:
        with open(temporary, 'x') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    import sys
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise SystemExit('Route projection requires root and the appliance state directory')
    reconcile(sys.argv[1])
