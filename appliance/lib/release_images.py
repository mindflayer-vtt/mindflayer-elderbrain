"""Prepare signed release images explicitly; no builds, startup or pruning."""
import json
import re
import subprocess

from appliance_release import verify, require_compatible


def canonical(reference):
    repository, digest = reference.rsplit('@', 1)
    if ':' in repository.rsplit('/', 1)[-1]:
        repository = repository.rsplit(':', 1)[0]
    if '/' not in repository:
        repository = 'docker.io/library/' + repository
    elif not any(character in repository.split('/')[0] for character in '.:') and not repository.startswith('localhost/'):
        repository = 'docker.io/' + repository
    if repository.startswith('index.docker.io/'):
        repository = 'docker.io/' + repository[len('index.docker.io/'):]
    return repository + '@' + digest


def inspect(reference, release, service, *, run):
    result = run(['docker', 'image', 'inspect', reference], stdin=subprocess.DEVNULL,
                 capture_output=True, text=True, timeout=30)
    if result.returncode:
        return None
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('Image inspection exceeds limit')
    records = json.loads(result.stdout)
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ValueError('Invalid image inspection result')
    image = records[0]
    identity = image.get('Id')
    if not isinstance(identity, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', identity):
        raise ValueError('Invalid local image identity')
    digests = image.get('RepoDigests')
    if (not isinstance(digests, list) or any(not isinstance(value, str) or '@sha256:' not in value for value in digests)
            or canonical(reference) not in {canonical(value) for value in digests}):
        raise ValueError('Cached image does not prove the signed registry digest')
    if image.get('Os') != 'linux' or image.get('Architecture') != release['platform']['architecture']:
        raise ValueError('Release image platform mismatch')
    if service == 'elderbrain-setup':
        config = image.get('Config')
        labels = config.get('Labels') if isinstance(config, dict) else None
        setup = release['setup']
        expected = {'org.opencontainers.image.version': setup['version'],
                    'io.mindflayer.elderbrain.host-api-min': str(setup['hostApi']['min']),
                    'io.mindflayer.elderbrain.host-api-max': str(setup['hostApi']['max'])}
        if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
            raise ValueError('Setup image version/API metadata differs from signed release')
    return {'reference': reference, 'id': identity}


def prepare(manifest, signature, public_key, *, allow_download=False, setup_only=False, installed_host_api=None, run=subprocess.run):
    if type(allow_download) is not bool or type(setup_only) is not bool:
        raise ValueError('Explicit image preparation options required')
    release = verify(manifest, signature, public_key)
    if setup_only:
        require_compatible(release, platform=release['platform'], configuration_schema=release['configurationSchema'],
                           setup_only=True, installed_host_api=installed_host_api)
    references = {'elderbrain-setup': release['setup']['image']}
    if not setup_only:
        references.update(release['images'])
    prepared = {}
    for service, reference in references.items():
        image = inspect(reference, release, service, run=run)
        if image is None:
            if not allow_download:
                raise ValueError('Signed release image is unavailable locally; explicit preparation required')
            # Pull only the signed digest for the declared platform. Never build
            # source, run a container, change a tag or prune old rollback images.
            result = run(['docker', 'pull', '--platform', 'linux/' + release['platform']['architecture'], reference],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)
            if result.returncode:
                raise ValueError('Release image download failed')
            image = inspect(reference, release, service, run=run)
            if image is None:
                raise ValueError('Downloaded release image cannot be verified')
        prepared[service] = image
    return {'releaseVersion': release['version'], 'images': prepared}
