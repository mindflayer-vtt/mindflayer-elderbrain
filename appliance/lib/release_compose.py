"""Render verified release images into a private runtime Compose configuration."""
from copy import deepcopy
import yaml

from appliance_release import validate


def render(template, release):
    """Caller supplies authenticated template/manifest; no environment is read.

User domain, ports, state paths, secrets and profile interpolation remain intact.
Only release-owned image/build/pull settings are replaced. Caller must run Compose
validation and persist the result in its staged release, never overwrite live
configuration merely because rendering succeeded.
"""
    validate(release)
    if not isinstance(template, bytes) or not 0 < len(template) <= 1024 * 1024:
        raise ValueError('Invalid release Compose template size')
    document = yaml.safe_load(template)
    if not isinstance(document, dict) or set(document) - {'name', 'services', 'networks', 'secrets', 'volumes'}:
        raise ValueError('Unsupported release Compose structure')
    services = document.get('services')
    references = {'elderbrain-setup': release['setup']['image'], **release['images']}
    if not isinstance(services, dict) or set(services) != set(references):
        raise ValueError('Release Compose services differ from signed image set')
    generated = deepcopy(document)
    for name, reference in references.items():
        service = generated['services'][name]
        if not isinstance(service, dict) or 'extends' in service or 'develop' in service:
            raise ValueError('Unsupported indirect release service configuration')
        service.pop('build', None)
        service['image'] = reference
        service['pull_policy'] = 'never'
    environment = generated['services']['elderbrain-setup'].get('environment')
    if not isinstance(environment, dict) or 'MINDFLAYER_SERVER_IMAGE' not in environment:
        raise ValueError('Setup requires explicit coordinated server image metadata')
    environment['MINDFLAYER_SERVER_IMAGE'] = references['mindflayer-server']
    return yaml.safe_dump(generated, sort_keys=False).encode()
