from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CloudSSHIdentityTests(unittest.TestCase):
    def test_first_boot_preserves_existing_keys(self):
        settings = yaml.safe_load((ROOT / 'provisioning/cloud/99-elderbrain-ssh-identity.cfg').read_text())
        self.assertIs(settings['ssh_deletekeys'], False)
        # Keep cloud-init's default missing-key handling; an empty generation
        # list is rejected by its schema. Existing keys are skipped, not replaced.
        self.assertNotIn('ssh_genkeytypes', settings)
        self.assertNotIn('ssh_keys', settings)

    def test_policy_installed_before_persistent_aliases_and_key_validation(self):
        install = (ROOT / 'provisioning/install.sh').read_text()
        policy = install.index('install -m 0644 "$PAYLOAD_DIR/provisioning/cloud/99-elderbrain-ssh-identity.cfg"')
        binding = install.index('python3 -m provisioning.host_persistence')
        validation = install.index('sshd -t', binding)
        self.assertLess(policy, binding)
        self.assertLess(binding, validation)


if __name__ == '__main__':
    unittest.main()
