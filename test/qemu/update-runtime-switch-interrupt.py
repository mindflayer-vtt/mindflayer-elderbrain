#!/usr/bin/env python3
"""Stop one exact disposable update at a selected runtime rename boundary."""
import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import save_record


class Registers(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        'r15', 'r14', 'r13', 'r12', 'rbp', 'rbx', 'r11', 'r10', 'r9', 'r8',
        'rax', 'rcx', 'rdx', 'rsi', 'rdi', 'orig_rax', 'rip', 'cs', 'eflags',
        'rsp', 'ss', 'fs_base', 'gs_base', 'ds', 'es', 'fs', 'gs')]


def ptrace(request, pid, address=0, data=0):
    result = libc.ptrace(ctypes.c_uint(request), ctypes.c_uint(pid),
                         ctypes.c_void_p(address), ctypes.c_void_p(data))
    if result == -1:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def string(pid, address):
    descriptor = os.open(f'/proc/{pid}/mem', os.O_RDONLY)
    try:
        value = os.pread(descriptor, 4096, address)
    finally:
        os.close(descriptor)
    return value.split(b'\0', 1)[0].decode()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('boundary', choices=('old-moved', 'new-installed'))
parser.add_argument('job')
parser.add_argument('version')
parser.add_argument('manifest')
args = parser.parse_args()
if (not re.fullmatch(r'[a-f0-9]{32}', args.job)
        or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', args.version)
        or not re.fullmatch(r'[a-f0-9]{64}', args.manifest)):
    raise ValueError('An exact job, version and manifest digest are required')
assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'

jobs = Path('/var/lib/mindflayer-elderbrain/jobs')
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    try:
        record = json.loads((jobs / (args.job + '.json')).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        time.sleep(0.01)
        continue
    if (record.get('id') == args.job and record.get('kind') == 'update'
            and record.get('state') in ('queued', 'running')
            and record.get('request', {}).get('version') == args.version
            and record.get('request', {}).get('manifestSha256') == args.manifest):
        break
    raise RuntimeError('Exact update job does not match the requested release')
else:
    raise TimeoutError('Exact next update job did not appear')

job = args.job
unit = 'elderbrain-job-' + job + '.scope'
pid = 0
while time.monotonic() < deadline:
    output = subprocess.run(['systemctl', 'show', unit, '--property=ControlGroup', '--value'],
                            text=True, capture_output=True)
    group = output.stdout.strip()
    processes = Path('/sys/fs/cgroup' + group) / 'cgroup.procs' if group.startswith('/') else None
    for value in processes.read_text().splitlines() if processes and processes.is_file() else ():
        candidate = int(value)
        try:
            command = Path(f'/proc/{candidate}/cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        script = next((index for index, part in enumerate(command)
                       if part.endswith(b'/host_jobs.py')), None)
        if (script is not None and len(command) > script + 3
                and command[script + 1] == b'worker'
                and command[script + 3].decode() == job):
            pid = candidate
            break
    if pid > 0:
        break
    time.sleep(0.01)
if pid <= 0:
    raise RuntimeError('Exact update worker did not start')

libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.restype = ctypes.c_long
PTRACE_ATTACH, PTRACE_CONT, PTRACE_GETREGS = 16, 7, 12
PTRACE_SETOPTIONS, PTRACE_SYSCALL, PTRACE_O_TRACESYSGOOD = 0x4200, 24, 1
ptrace(PTRACE_ATTACH, pid)
_, status = os.waitpid(pid, 0)
if not os.WIFSTOPPED(status):
    raise RuntimeError('Update worker did not stop for tracing')
ptrace(PTRACE_SETOPTIONS, pid, 0, PTRACE_O_TRACESYSGOOD)

entering = True
matched = False
pending_signal = 0
while time.monotonic() < deadline:
    ptrace(PTRACE_SYSCALL, pid, 0, pending_signal)
    pending_signal = 0
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status) or os.WIFSIGNALED(status):
        raise RuntimeError('Update worker exited before moving the old runtime')
    stopped = os.WSTOPSIG(status)
    if stopped != signal.SIGTRAP | 0x80:
        pending_signal = 0 if stopped == signal.SIGSTOP else stopped
        continue
    registers = Registers()
    ptrace(PTRACE_GETREGS, pid, 0, ctypes.addressof(registers))
    if entering:
        source_pointer = {82: registers.rdi, 264: registers.rsi, 316: registers.rsi}.get(registers.orig_rax)
        destination_pointer = {82: registers.rsi, 264: registers.r10, 316: registers.r10}.get(registers.orig_rax)
        if source_pointer and destination_pointer:
            source, destination = string(pid, source_pointer), string(pid, destination_pointer)
            old_moved = (source == '/opt/mindflayer-elderbrain'
                         and re.fullmatch(r'/opt/\.elderbrain-restore-[a-f0-9]{32}-mindflayer-elderbrain/previous', destination))
            new_installed = (re.fullmatch(r'/opt/\.elderbrain-restore-[a-f0-9]{32}-mindflayer-elderbrain/incoming', source)
                             and destination == '/opt/mindflayer-elderbrain')
            matched = old_moved if args.boundary == 'old-moved' else new_installed
    elif matched:
        if ctypes.c_longlong(registers.rax).value != 0:
            raise RuntimeError('Old runtime rename failed')
        break
    entering = not entering
else:
    raise TimeoutError('Old runtime was not moved before the deadline')

# The traced process is stopped at syscall exit, before it can install incoming.
os.kill(pid, signal.SIGKILL)
try:
    ptrace(PTRACE_CONT, pid)
except ProcessLookupError:
    pass  # SIGKILL may complete before the stopped tracee is resumed.
try:
    os.waitpid(pid, 0)
except ChildProcessError:
    pass
lock = os.open(jobs / (job + '.lock'), os.O_RDWR | os.O_NOFOLLOW)
try:
    for _ in range(200):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.01)
    else:
        raise RuntimeError('Interrupted worker retained its lock')
finally:
    os.close(lock)

maintenance = json.loads(Path('/var/lib/mindflayer-elderbrain/maintenance/maintenance.json').read_text())
transaction_path = Path('/var/lib/mindflayer-elderbrain/maintenance') / ('update-' + maintenance['id'] + '.json')
transaction = json.loads(transaction_path.read_text())
location = Path('/opt') / ('.elderbrain-restore-' + transaction['id'] + '-mindflayer-elderbrain')
runtime_exists = Path('/opt/mindflayer-elderbrain').is_dir()
previous_exists = (location / 'previous').is_dir()
incoming_exists = (location / 'incoming').is_dir()
expected_locations = ((False, True, True) if args.boundary == 'old-moved'
                      else (True, True, False))
if (maintenance.get('state') != 'installing-update' or transaction.get('state') != 'installing'
        or (runtime_exists, previous_exists, incoming_exists) != expected_locations):
    raise RuntimeError('Interruption did not preserve the exact mid-switch boundary')
evidence = Path(tempfile.mkdtemp(prefix='elderbrain-runtime-switch-interrupt-', dir='/root'))
save_record(evidence / 'interruption.json', {
    'job': job, 'boundary': args.boundary,
    'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'maintenanceId': maintenance['id'], 'maintenanceState': maintenance['state'],
    'transactionId': transaction['id'], 'transactionState': transaction['state'],
    'runtimeExists': runtime_exists, 'previousExists': previous_exists,
    'incomingExists': incoming_exists,
})
print(evidence, flush=True)
