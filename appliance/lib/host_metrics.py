"""Read-only host telemetry, sampled independently of browser connections."""
from collections import deque
import copy
import os
from pathlib import Path
import socket
import subprocess
import threading
import time


class Metrics:
    def __init__(self, proc=Path('/proc'), paths=None):
        self.proc = proc
        state = Path(os.environ.get('ELDERBRAIN_STATE_DIR', '/var/lib/mindflayer-elderbrain'))
        self.paths = paths if paths is not None else ['/', str(state)] + [
            str(state / name) for name in ('foundry', 'elderbrain', 'mindflayer', 'firmware', 'traefik', 'backups', 'browser')]
        self.history = deque(maxlen=720)
        self.previous_cpu = None
        self.lock = threading.Lock()
        self.latest = {}

    def sample(self):
        sample = {'at': time.time(), 'cpu': None, 'ram': None, 'disks': []}
        errors = []
        try:
            # guest counters are already included in user/nice: do not double count.
            counters = [int(value) for value in (self.proc / 'stat').read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(counters), counters[3] + counters[4]
            if self.previous_cpu:
                elapsed = total - self.previous_cpu[0]
                if elapsed > 0:
                    sample['cpu'] = max(0, min(100, 100 * (1 - (idle - self.previous_cpu[1]) / elapsed)))
            self.previous_cpu = total, idle
        except (OSError, ValueError, IndexError):
            self.previous_cpu = None
            errors.append('CPU unavailable')
        try:
            memory = {key: int(value.split()[0]) * 1024 for key, value in
                      (line.split(':', 1) for line in (self.proc / 'meminfo').read_text().splitlines())}
            sample['ram'] = {'total': memory['MemTotal'], 'free': memory['MemAvailable'],
                             'used': memory['MemTotal'] - memory['MemAvailable']}
        except (OSError, ValueError, KeyError):
            errors.append('RAM unavailable')
        seen = set()
        for path in self.paths:
            try:
                device = os.stat(path).st_dev
                if device in seen:
                    continue
                seen.add(device)
                usage = os.statvfs(path)
                total = usage.f_blocks * usage.f_frsize
                free = usage.f_bavail * usage.f_frsize
                used = (usage.f_blocks - usage.f_bfree) * usage.f_frsize
                sample['disks'].append({'path': path, 'total': total, 'free': free, 'used': used})
            except OSError:
                errors.append('Storage unavailable: ' + path)
        try:
            uptime = float((self.proc / 'uptime').read_text().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = None
        services = []
        for unit in ('elderbrain-stack', 'elderbrain-graphics', 'docker'):
            try:
                result = subprocess.run(['systemctl', 'is-active', unit + '.service'], capture_output=True, text=True, timeout=1)
                state = result.stdout.strip()
                if state not in ('active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading'):
                    state = 'unavailable'
            except (OSError, subprocess.TimeoutExpired):
                state = 'unavailable'
            services.append({'name': unit, 'state': state})
        with self.lock:
            self.history.append(sample)
            while self.history and self.history[0]['at'] < sample['at'] - 3600:
                self.history.popleft()
            self.latest = {'hostname': socket.gethostname(), 'uptime': uptime, 'services': services, 'errors': errors}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({**self.latest, 'history': list(self.history), 'interval': 5, 'retention': 3600})

    def start(self):
        def loop():
            while True:
                started = time.monotonic()
                try:
                    self.sample()
                except Exception:
                    # Preserve last data; the UI detects stale timestamps.
                    pass
                time.sleep(max(0.1, 5 - (time.monotonic() - started)))
        threading.Thread(target=loop, name='host-metrics', daemon=True).start()
