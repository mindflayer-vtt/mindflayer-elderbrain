"""Pure projections for selective restore; callers stage under maintenance locks.

Returned dictionaries may contain Wi-Fi credentials and must never be exposed
as a public preview. No filesystem replacement or physical keypad action occurs.
"""
from copy import deepcopy
import re

from display_preview import validate as validate_displays

COMPONENTS = {'preferences', 'network', 'keypad-settings', 'keypad-identities',
              'foundry', 'security'}
MAX_REVISION = 2 ** 53 - 1


def selection(values, *, confirm_security=False):
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or value not in COMPONENTS for value in values)
            or len(set(values)) != len(values)):
        raise ValueError('Choose supported logical restore components')
    if 'network' in values and len(values) != 1:
        raise ValueError('Restore network separately with timed confirmation')
    if {'security', 'keypad-identities'} & set(values) and confirm_security is not True:
        raise ValueError('Explicit confirmation required for identity or security restore')
    return tuple(sorted(values))


def preferences(current, archived):
    validate_displays(current)
    validate_displays(archived)
    if current.get('version') != 1 or archived.get('version') != 1:
        raise ValueError('Unsupported preferences schema')
    result = deepcopy(current)
    # Onboarding state and controller names belong to other restore boundaries.
    for key in ('domain', 'views'):
        result[key] = deepcopy(archived[key])
    return validate_displays(result)


def revision(value):
    if type(value) is not int or not 0 <= value < MAX_REVISION:
        raise ValueError('Invalid or exhausted keypad configuration revision')
    return value


def keypad_settings(current_settings, current_records, archived_settings, archived_records):
    if any(not isinstance(value, dict) for value in
           (current_settings, current_records, archived_settings, archived_records)):
        raise ValueError('Invalid keypad checkpoint configuration')
    settings = {key: archived_settings.get(key) for key in ('ssid', 'psk', 'serverHost', 'serverPort')}
    ssid, psk, host, port = (settings[key] for key in ('ssid', 'psk', 'serverHost', 'serverPort'))
    unconfigured = ssid == psk == host == '' and port == 10443
    if not unconfigured:
        if not isinstance(ssid, str) or '\0' in ssid or not 1 <= len(ssid.encode()) <= 32:
            raise ValueError('Invalid archived Wi-Fi SSID')
        if not isinstance(psk, str) or '\0' in psk or not 8 <= len(psk.encode()) <= 63:
            raise ValueError('Invalid archived Wi-Fi password')
        if not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9.:-]{1,253}', host):
            raise ValueError('Invalid archived keypad server address')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid archived keypad server port')
    revisions = [revision(current_settings.get('revision')), revision(archived_settings.get('revision'))]
    for records in (current_records, archived_records):
        for identifier, record in records.items():
            if (not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', identifier)
                    or not isinstance(record, dict) or record.get('id') != identifier):
                raise ValueError('Invalid keypad record')
            revisions.append(revision(record.get('desiredRevision')))
    settings['revision'] = max(revisions) + 1
    records = deepcopy(current_records)
    for identifier, record in records.items():
        previous = archived_records.get(identifier)
        if previous is not None:
            for key in ('name', 'seat'):
                value = previous.get(key, '')
                if not isinstance(value, str) or len(value) > 80:
                    raise ValueError('Invalid archived keypad label')
                record[key] = value
            colours = previous.get('ledPreferences')
            if colours is not None:
                if (not isinstance(colours, dict) or set(colours) != {'led1', 'led2'}
                        or any(not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value)
                               for value in colours.values())):
                    raise ValueError('Invalid archived keypad LED preferences')
                colours = {key: value.lower() for key, value in colours.items()}
            record['ledPreferences'] = colours
        record.update(desiredRevision=settings['revision'], appliedRevision=None,
                      appliedLeds=None, configurationDigest=None, connection='unknown')
    return {'settings': settings, 'records': records, 'expectations': {},
            'absentDeviceIds': sorted(set(archived_records) - set(current_records))}
