"""Protected monotonic release acceptance outside application rollback targets."""
import json
import os
from pathlib import Path
import re
import stat

from appliance_release import unique
from backup_service import save_record
from release_runtime import read_regular

MAX_SEQUENCE = 2 ** 63 - 1


def _record(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if (path.resolve() != path.absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError('Release policy state is not private and canonical')
    value = json.loads(read_regular(path, 4096), object_pairs_hook=unique)
    if (not isinstance(value, dict)
            or set(value) != {'format', 'highestSequence', 'version', 'manifestSha256'}
            or type(value['format']) is not int or value['format'] != 1
            or type(value['highestSequence']) is not int
            or not 1 <= value['highestSequence'] <= MAX_SEQUENCE
            or not isinstance(value['version'], str)
            or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', value['version'])
            or not isinstance(value['manifestSha256'], str)
            or not re.fullmatch(r'[a-f0-9]{64}', value['manifestSha256'])):
        raise ValueError('Invalid release policy state')
    return value


class ReleasePolicy:
    def __init__(self, state):
        self.path = Path(state).absolute() / 'release-policy.json'

    def current(self):
        value = _record(self.path)
        return value or {'highestSequence': 0}

    def require_new(self, release):
        sequence = release.get('releaseSequence') if isinstance(release, dict) else None
        if type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE:
            raise ValueError('Invalid signed release sequence')
        if sequence <= self.current()['highestSequence']:
            raise ValueError('Release sequence is not newer than the accepted baseline')
        return sequence

    def commit(self, record):
        if not isinstance(record, dict):
            raise ValueError('Invalid release acceptance record')
        sequence, version, digest = (record.get(name) for name in
                                     ('releaseSequence', 'version', 'manifestSha256'))
        if (type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE
                or not isinstance(version, str)
                or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', version)
                or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('Invalid release acceptance record')
        current = self.current()
        if sequence < current['highestSequence']:
            raise ValueError('Refusing to roll back accepted release sequence')
        selected = {'format': 1, 'highestSequence': sequence,
                    'version': version, 'manifestSha256': digest}
        if sequence == current['highestSequence']:
            if current != selected:
                raise ValueError('Release sequence identity conflicts with accepted state')
            return current
        save_record(self.path, selected)
        return selected
