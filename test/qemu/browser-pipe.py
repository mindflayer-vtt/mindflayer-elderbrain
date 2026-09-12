"""Disposable VM: verify private stdin/status stdout through the production helper."""
import importlib.util
import json
import secrets
import subprocess

spec = importlib.util.spec_from_file_location('browser_process', '/tmp/elderbrain-browser-process.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
secret = secrets.token_hex(24)
code = ('import json,sys; value=json.load(sys.stdin); '
        'assert len(value["password"]) == 48; print(json.dumps({"state":"ready"}),flush=True)')
child = helper.launch(1, ['/usr/bin/python3', '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
try:
    output, _ = child.communicate(json.dumps({'password': secret}).encode(), timeout=15)
    assert child.returncode == 0, 'Test service failed'
    assert json.loads(output) == {'state': 'ready'}, 'Unexpected worker output'
    assert secret.encode() not in output, 'Private input echoed into output'
    print('PASS: private stdin and bounded status stdout traverse the per-view service.')
finally:
    helper.terminate(child)
