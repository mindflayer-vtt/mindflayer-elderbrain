#!/usr/bin/env python3
"""Stage explicit ISO payload inputs and write reproducible source metadata."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def command(args, *, cwd, text=True):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          text=text, timeout=120)


def identity(repository):
    repository = Path(repository).resolve()
    status = command(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=repository).stdout
    if status:
        raise ValueError('Production ISO requires clean tracked and staged inputs')
    commit = command(['git', 'rev-parse', '--verify', 'HEAD^{commit}'], cwd=repository).stdout.strip()
    tree = command(['git', 'rev-parse', '--verify', 'HEAD^{tree}'], cwd=repository).stdout.strip()
    if not re.fullmatch(r'[a-f0-9]{40}', commit) or not re.fullmatch(r'[a-f0-9]{40}', tree):
        raise ValueError('Invalid Git source identity')
    return commit, tree


def extract_tracked(repository, destination, commit):
    repository, destination = Path(repository).resolve(), Path(destination).resolve()
    if any(destination.iterdir()):
        raise ValueError('ISO payload destination must be empty')
    with tempfile.TemporaryDirectory(prefix='elderbrain-payload-', dir=destination.parent) as temporary:
        archive = Path(temporary) / 'tracked.tar'
        command(['git', 'archive', '--format=tar', '--output=' + str(archive), commit], cwd=repository)
        with tarfile.open(archive, 'r:') as source:
            members = source.getmembers()
            if not members or len(members) > 8192:
                raise ValueError('Invalid tracked payload inventory')
            for member in members:
                name = PurePosixPath(member.name)
                if (name.is_absolute() or not member.name or member.name != name.as_posix()
                        or '..' in name.parts or not (member.isdir() or member.isfile())):
                    raise ValueError('Tracked payload contains unsupported entries')
            source.extractall(destination, members=members, filter='data')


def metadata(destination, version, commit, tree, *, development=False):
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise ValueError('APPLIANCE_VERSION must be a stable semantic version')
    for value in (commit, tree):
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{40}', value):
            raise ValueError('Invalid Git source identity')
    core = {'format': 1, 'version': version, 'sourceCommit': commit, 'sourceTree': tree,
            'inputMode': 'development-worktree' if development else 'tracked-commit'}
    encoded = json.dumps(core, sort_keys=True, separators=(',', ':')).encode()
    value = {**core, 'sourceIdentity': hashlib.sha256(encoded).hexdigest()}
    destination = Path(destination)
    (destination / 'VERSION').write_text(version + '\n')
    (destination / 'build-metadata.json').write_text(
        json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
    return value


def stage(repository, destination, version):
    commit, tree = identity(repository)
    extract_tracked(repository, destination, commit)
    return metadata(destination, version, commit, tree)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('version')
    args = parser.parse_args()
    print(json.dumps(stage(args.repository, args.destination, args.version), sort_keys=True))
