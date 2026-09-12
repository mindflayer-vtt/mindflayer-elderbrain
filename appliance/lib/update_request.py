"""Small update request validator shared by the bridge and stable worker."""
import re
from appliance_release import VERSION


def request(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'manifestSha256', 'confirmUpdate', 'confirmDowntime'}
            or not isinstance(value['version'], str) or len(value['version']) > 128 or not re.fullmatch(VERSION, value['version'])
            or not isinstance(value['manifestSha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['manifestSha256'])
            or value['confirmUpdate'] is not True or value['confirmDowntime'] is not True):
        raise ValueError('Update requires a version, exact manifest digest and explicit downtime confirmation')
    return dict(value)
