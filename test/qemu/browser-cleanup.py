"""Run as the kiosk user in the disposable VM, with the helper copied to /tmp."""
import importlib.util
from pathlib import Path
import subprocess
import time

spec = importlib.util.spec_from_file_location('browser_process', '/tmp/elderbrain-browser-process.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
code = ('import signal,subprocess,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
        'subprocess.Popen(["/usr/bin/python3","-c",'
        '"import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(600)"],start_new_session=True); '
        'time.sleep(600)')
child = helper.launch(1, ['/usr/bin/python3', '-c', code])
group = None
try:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = subprocess.run(['/usr/bin/systemctl', '--user', 'show', 'elderbrain-view-1.service', '-p', 'ControlGroup', '--value'],
                                env=helper.manager_environment(), capture_output=True, text=True)
        if result.stdout.strip():
            group = Path('/sys/fs/cgroup') / result.stdout.strip().lstrip('/')
            if (group / 'cgroup.procs').exists() and len((group / 'cgroup.procs').read_text().splitlines()) >= 2:
                break
        time.sleep(0.1)
    else:
        raise AssertionError('Detached descendant did not start')
    helper.terminate(child)
    assert not group.exists() or 'populated 0' in (group / 'cgroup.events').read_text()
    print('PASS: per-view service kills a detached descendant and parent that both ignore SIGTERM.')
finally:
    if child.poll() is None:
        helper.terminate(child)
