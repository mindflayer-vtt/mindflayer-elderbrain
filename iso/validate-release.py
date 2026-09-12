"""Validate explicit ISO update-source inputs; never accept a private key."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import unique
from release_catalog import source_url


def validate(source, key):
    source, key = Path(source), Path(key)
    if not 0 < source.stat().st_size <= 4096 or not 0 < key.stat().st_size <= 16384:
        raise ValueError('Invalid release source/key size')
    config = json.loads(source.read_bytes(), object_pairs_hook=unique)
    if not isinstance(config, dict) or set(config) != {'baseUrl'}:
        raise ValueError('Release source requires exactly baseUrl')
    source_url(config['baseUrl'])
    public = key.read_bytes()
    if b'PRIVATE KEY' in public or not public.startswith(b'-----BEGIN PUBLIC KEY-----\n'):
        raise ValueError('Only a PEM public release key may be baked into the ISO')
    subprocess.run(['openssl', 'pkey', '-pubin', '-in', str(key), '-noout'], check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    return config, public


if __name__ == '__main__':
    validate(*sys.argv[1:])
