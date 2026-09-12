"""Exercise the installer's offline/live linger branches without host changes."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallationLingerTests(unittest.TestCase):
    def run_branch(self, chroot, login_status=0, offline=False):
        source = (ROOT / 'provisioning/install.sh').read_text()
        start = 'if [[ ${ELDERBRAIN_OFFLINE_INSTALL:-0} == 1 ]]'
        block = start + source.split(start, 1)[1].split('\nfi', 1)[0] + '\nfi'
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'linger/elderbrain-kiosk'
            block = block.replace('/var/lib/systemd/linger', shlex.quote(directory) + '/linger')
            script = f'''set -eu
ELDERBRAIN_OFFLINE_INSTALL={1 if offline else 0}
systemd-detect-virt() {{ test "$*" = '--chroot --quiet'; return {0 if chroot else 1}; }}
loginctl() {{ test "$*" = 'enable-linger elderbrain-kiosk'; echo loginctl; return {login_status}; }}
{block}
'''
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True)
            if chroot or offline:
                self.assertEqual(marker.read_bytes(), b'')
                self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
                self.assertEqual(marker.parent.stat().st_mode & 0o777, 0o755)
                self.assertNotIn('loginctl', result.stdout)
            else:
                self.assertFalse(marker.exists())
                self.assertEqual(result.stdout.strip(), 'loginctl')
            return result.returncode

    def test_chroot_never_contacts_logind(self):
        self.assertEqual(self.run_branch(True, login_status=1), 0)

    def test_curtin_explicit_offline_mode_overrides_failed_detection(self):
        template = (ROOT / 'iso/autoinstall/user-data.in').read_text()
        self.assertIn('env ELDERBRAIN_OFFLINE_INSTALL=1 ELDERBRAIN_STORAGE_RECEIPT=', template)
        self.assertIn('bash /opt/elderbrain-payload/provisioning/install.sh', template)
        self.assertEqual(self.run_branch(False, login_status=1, offline=True), 0)

    def test_live_install_uses_login_manager(self):
        self.assertEqual(self.run_branch(False), 0)

    def test_live_failure_is_not_silenced(self):
        self.assertNotEqual(self.run_branch(False, login_status=1), 0)
