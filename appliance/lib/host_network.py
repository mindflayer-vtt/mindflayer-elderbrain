"""Read-only host interface discovery; never infer DHCP from address shape."""
import ipaddress
import json
import re
import subprocess
import time


def command(args):
    return json.loads(subprocess.run(args, check=True, capture_output=True, text=True, timeout=5).stdout)


def ipv4(value):
    try:
        return str(ipaddress.IPv4Address(bytes(value) if isinstance(value, list) else value))
    except (ValueError, TypeError):
        return None


def normalize(links, routes, networkd):
    metadata = {link['Index']: link for link in networkd.get('Interfaces', []) if 'Index' in link}
    result = []
    for link in links:
        name = link.get('ifname', '')
        if 'LOOPBACK' in link.get('flags', []):
            continue
        info = metadata.get(link.get('ifindex'), {})
        sources = {ipv4(item.get('Address')): item.get('ConfigSource') for item in info.get('Addresses', []) if item.get('Family') == 2}
        addresses = []
        for item in link.get('addr_info', []):
            address = ipv4(item.get('local'))
            if item.get('family') != 'inet' or not address:
                continue
            source = sources.get(address)
            addresses.append({'address': address, 'prefix': item.get('prefixlen'), 'scope': item.get('scope'),
                              'source': 'DHCP' if source == 'DHCPv4' else 'Static' if source == 'static' else 'Unknown'})
        defaults = [route for route in routes if route.get('dev') == name and route.get('dst') == 'default' and 'linkdown' not in route.get('flags', [])]
        internal = name == 'docker0' or bool(re.fullmatch(r'br-[a-f0-9]{12}', name)) or info.get('Kind') == 'veth' or name.startswith('veth')
        result.append({'name': name, 'index': link.get('ifindex'), 'state': link.get('operstate', 'UNKNOWN'),
                       'internal': internal, 'addresses': addresses, 'defaultRoute': bool(defaults),
                       'gateways': list(dict.fromkeys(address for route in defaults if (address := ipv4(route.get('gateway'))))),
                       'dns': list(dict.fromkeys(address for item in info.get('DNS', []) if item.get('Family') == 2 and (address := ipv4(item.get('Address')))))})
    return sorted(result, key=lambda item: (item['internal'], not item['defaultRoute'], item['name']))


def discover():
    links = command(['ip', '-j', '-4', 'address', 'show'])
    routes = command(['ip', '-j', '-4', 'route', 'show', 'default'])
    errors = []
    try:
        networkd = command(['networkctl', '--json=short', 'status'])
    except (OSError, ValueError, subprocess.SubprocessError):
        networkd = {}
        errors.append('Address source and DNS unavailable from systemd-networkd')
    return {'at': time.time(), 'interfaces': normalize(links, routes, networkd), 'errors': errors}
