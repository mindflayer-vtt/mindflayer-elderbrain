"""Installer preflight: produce a plan only after fresh identity verification."""

from iso.storage_plan import plan, _uuid


def prepare(*, mode, serial, inventory_probe, marker_reader,
            erase_confirmed=False, data_uuid=None, uefi=True):
    before = inventory_probe()
    if mode == 'fresh':
        return {'storage': plan(before, mode=mode, serial=serial,
                                erase_confirmed=erase_confirmed, uefi=uefi),
                'identity': None}
    if mode != 'preserve':
        raise ValueError('Explicit fresh or preserve mode is required')
    data_uuid = _uuid(data_uuid)
    # Exercise all layout checks before mounting. The synthetic marker here is
    # NOT accepted as evidence: it only lets the pure planner validate geometry
    # and UUID uniqueness. The real marker is mandatory below.
    geometry_marker = dict(product='mindflayer-elderbrain', layout_version=1,
                           data_uuid=data_uuid, disk_serial=serial,
                           appliance_id='00000000-0000-0000-0000-000000000000')
    plan(before, mode=mode, serial=serial, data_uuid=data_uuid,
         metadata=geometry_marker, uefi=uefi)
    selected = next(disk for disk in before if disk['serial'] == serial)
    partition = next(part for part in selected['partitions'] if part['number'] == 4)
    identity = marker_reader(partition['path'], data_uuid)
    after = inventory_probe()
    selected_after = [disk for disk in after if disk.get('serial') == serial]
    if selected_after != [selected]:
        raise ValueError('Selected disk changed during data inspection; retry selection')
    return {'storage': plan(after, mode=mode, serial=serial, data_uuid=data_uuid,
                            metadata=identity, uefi=uefi), 'identity': identity}
