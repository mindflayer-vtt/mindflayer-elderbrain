"""Prepare Netplan source edits without applying or writing host networking."""
import copy
from pathlib import PurePosixPath
import yaml
from network_config import plan, resolve

LAYERS = {'lib': 0, 'etc': 1, 'run': 2}


def effective_sources(sources):
    selected = {}
    for filename in sources:
        path = PurePosixPath(filename)
        if len(path.parts) != 3 or path.parts[0] not in LAYERS or path.parts[1] != 'netplan' or path.suffix != '.yaml':
            raise ValueError('Invalid Netplan source path')
        previous = selected.get(path.name)
        if previous is None or LAYERS[path.parts[0]] > LAYERS[PurePosixPath(previous).parts[0]]:
            selected[path.name] = filename
    return [selected[name] for name in sorted(selected)]


def rewrite(sources, merged, values, mac=None):
    """Return only changed files and their exact original bytes for rollback.

    Netplan merges sequences across fragments. Remove the selected netdef from
    every effective origin, then emit its complete new definition in its last
    origin. Other netdefs and global settings retain their meanings and origins.
    Transient/vendor-owned origins are deliberately not mutated.
    """
    prepared = plan(merged, values, mac)
    kind, name = resolve(merged, values['interface'], mac)
    documents = {}
    origins = []
    for filename in effective_sources(sources):
        document = yaml.safe_load(sources[filename]) or {}
        if not isinstance(document, dict):
            raise ValueError('Invalid Netplan document')
        documents[filename] = document
        if name in document.get('network', {}).get(kind, {}):
            origins.append(filename)
    if not origins:
        raise ValueError('Netplan definition has no identifiable source file')
    if any(not filename.startswith('etc/netplan/') for filename in origins):
        raise ValueError('Selected interface has vendor or transient Netplan sources; persistent source ownership must be resolved before editing')
    result = {}
    for filename in origins:
        document = copy.deepcopy(documents[filename])
        target = document['network'][kind]
        del target[name]
        if filename == origins[-1]:
            target[name] = prepared['configuration']['network'][kind][name]
        if not target:
            del document['network'][kind]
        candidate = yaml.safe_dump(document, sort_keys=False).encode()
        result[filename] = {'before': sources[filename], 'after': candidate}
    return {'files': result, 'configuration': prepared['configuration'], 'warnings': prepared['warnings']}
