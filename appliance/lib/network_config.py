"""Validated IPv4 edits to a Netplan document; never apply networking here."""
import copy
import ipaddress
import re

KINDS = ('ethernets', 'wifis', 'bridges', 'bonds', 'vlans', 'tunnels', 'dummy-devices')


def unicast(value):
    if not isinstance(value, str):
        raise ValueError('Enter an IPv4 address')
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback or int(address) == 0xffffffff:
        raise ValueError('Use a unicast LAN IPv4 address')
    return str(address)


def request(value):
    if not isinstance(value, dict) or set(value) - {'interface', 'mode', 'address', 'prefix', 'gateway', 'dns'}:
        raise ValueError('Invalid IPv4 settings')
    interface = value.get('interface')
    if not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface) or interface == 'lo':
        raise ValueError('Invalid interface')
    mode = value.get('mode')
    if mode not in ('dhcp', 'static'):
        raise ValueError('Choose DHCP or static IPv4')
    dns = value.get('dns', [])
    if not isinstance(dns, list) or len(dns) > 6:
        raise ValueError('Use at most six IPv4 DNS servers')
    result = {'interface': interface, 'mode': mode, 'dns': list(dict.fromkeys(unicast(address) for address in dns))}
    if mode == 'static':
        address = unicast(value.get('address'))
        prefix = value.get('prefix')
        if type(prefix) is not int or not 1 <= prefix <= 32:
            raise ValueError('IPv4 prefix must be between 1 and 32')
        network = ipaddress.IPv4Network(f'{address}/{prefix}', strict=False)
        if prefix < 31 and ipaddress.IPv4Address(address) in (network.network_address, network.broadcast_address):
            raise ValueError('Address is the subnet or broadcast address')
        gateway = value.get('gateway', '')
        if gateway:
            gateway = unicast(gateway)
            if ipaddress.IPv4Address(gateway) not in network or gateway == address:
                raise ValueError('Gateway must be a different address on the selected subnet')
            if prefix < 31 and ipaddress.IPv4Address(gateway) in (network.network_address, network.broadcast_address):
                raise ValueError('Invalid gateway address')
        result.update(address=address, prefix=prefix, gateway=gateway)
    return result


def resolve(document, interface, mac=None):
    candidates = []
    for kind in KINDS:
        for name, config in document.get('network', {}).get(kind, {}).items():
            match = config.get('match', {})
            # A match rule can describe several adapters. Do not widen edits by guessing.
            if config.get('set-name') == interface or (not match and name == interface):
                candidates.append((kind, name))
            elif mac and str(match.get('macaddress', '')).lower() == mac.lower() and not config.get('set-name'):
                candidates.append((kind, name))
            elif match.get('name') == interface and not any(char in interface for char in '*?['):
                candidates.append((kind, name))
    if len(set(candidates)) != 1:
        raise ValueError('Interface must map unambiguously to one Netplan definition')
    return candidates[0]


def confirmation_settings(document, interface, mac=None):
    """Derive the reconnect destination from validated archived configuration.

    This only describes a confirmation endpoint, not an edit projection: retain
    all archived routes, IPv6, DNS and other adapters in the staged candidate.
    """
    kind, name = resolve(document, interface, mac)
    config = document['network'][kind][name]
    addresses = []
    for entry in config.get('addresses', []):
        value = next(iter(entry)) if isinstance(entry, dict) and len(entry) == 1 else entry
        address = ipaddress.ip_interface(value)
        if address.version == 4:
            addresses.append(address)
    dhcp = config.get('dhcp4', False)
    if type(dhcp) is not bool:
        raise ValueError('Invalid archived DHCP setting')
    if dhcp and not addresses:
        return request({'interface': interface, 'mode': 'dhcp'})
    if dhcp or len(addresses) != 1:
        raise ValueError('Choose an interface with unambiguous DHCP or one static IPv4 address for confirmation')
    address = addresses[0]
    return request({'interface': interface, 'mode': 'static', 'address': str(address.ip),
                    'prefix': address.network.prefixlen})


def ipv6_address(value):
    address = next(iter(value)) if isinstance(value, dict) and len(value) == 1 else value
    return ipaddress.ip_interface(address).version == 6


def main_ipv4_default(route):
    if route.get('table', 254) != 254:
        return False
    destination = route.get('to')
    if destination == '0.0.0.0/0':
        return True
    if destination == 'default':
        if not route.get('via'):
            raise ValueError('Default route family is ambiguous; preserve it with explicit CIDR notation')
        return ipaddress.ip_address(route['via']).version == 4
    return False


def edit(document, values, mac=None):
    values = request(values)
    kind, name = resolve(document, values['interface'], mac)
    result = copy.deepcopy(document)
    target = result['network'][kind][name]
    target['dhcp4'] = values['mode'] == 'dhcp'
    # Only replace IPv4 addresses/default routes/DNS on the selected interface.
    addresses = [address for address in target.get('addresses', []) if ipv6_address(address)]
    if values['mode'] == 'static':
        addresses.append(f"{values['address']}/{values['prefix']}")
    if addresses:
        target['addresses'] = addresses
    else:
        target.pop('addresses', None)
    routes = target.get('routes', [])
    defaults = [route for route in routes if main_ipv4_default(route)]
    if len(defaults) > 1:
        raise ValueError('Multiple main-table IPv4 gateways require explicit advanced configuration')
    kept = [route for route in routes if not main_ipv4_default(route)]
    if values['mode'] == 'static' and values['gateway']:
        route = copy.deepcopy(defaults[0]) if defaults else {'to': 'default'}
        route['via'] = values['gateway']
        kept.append(route)
    if kept:
        target['routes'] = kept
    else:
        target.pop('routes', None)
    target.pop('gateway4', None)
    nameservers = target.setdefault('nameservers', {})
    servers = [address for address in nameservers.get('addresses', []) if ipaddress.ip_address(address).version == 6]
    nameservers['addresses'] = servers + values['dns']
    if not nameservers['addresses']:
        nameservers.pop('addresses')
    if not nameservers:
        target.pop('nameservers', None)
    if values['mode'] == 'dhcp':
        target.setdefault('dhcp4-overrides', {})['use-dns'] = not bool(values['dns'])
        renderer = target.get('renderer', result['network'].get('renderer', 'networkd'))
        if target.get('dhcp6') is True and renderer == 'networkd':
            # networkd requires identical DHCPv4/v6 use-dns values. Surface this
            # coupled DNS change in the preview; do not disable DHCPv6 itself.
            target.setdefault('dhcp6-overrides', {})['use-dns'] = not bool(values['dns'])
    return result


def plan(document, values, mac=None):
    candidate = edit(document, values, mac)
    kind, name = resolve(document, values['interface'], mac)
    before = document['network'][kind][name]
    after = candidate['network'][kind][name]
    warnings = []
    if before.get('dhcp6-overrides', {}).get('use-dns', True) != after.get('dhcp6-overrides', {}).get('use-dns', True):
        warnings.append('Netplan requires DHCPv6 DNS acceptance to change together with DHCPv4 DNS on this interface. IPv6 addressing is preserved.')
    return {'configuration': candidate, 'warnings': warnings}
