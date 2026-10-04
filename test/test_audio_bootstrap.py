"""Analog audio must work on first boot without resetting later mixer choices."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'provisioning/graphics/prepare-browser.py'


class AudioBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('prepare_browser_audio', SOURCE)
        cls.audio = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.audio)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cards = self.root / 'cards'
        self.cards.write_text(' 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n'
                              ' 1 [HDMI           ]: HDA-Intel - HDA Intel HDMI\n')
        self.state = self.root / 'asound.state'
        self.commands = []
        self.master = 'Mono: Playback 0 [0%] [-65.25dB] [off]'

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        if command[:3] == ['amixer', '-c', 'PCH'] and command[3:] == ['sget', 'Master']:
            return subprocess.CompletedProcess(command, 0,
                f"Simple mixer control 'Master',0\n  {self.master}\n", '')
        if command[:3] == ['amixer', '-c', 'HDMI'] and command[3:] == ['sget', 'Master']:
            return subprocess.CompletedProcess(command, 1, '', 'Unable to find simple control')
        return subprocess.CompletedProcess(command, 0, '', '')

    def initialize(self):
        return self.audio.initialize_audio(cards_file=self.cards, state_file=self.state,
                                           run=self.run_command)

    def test_fresh_analog_card_is_unmuted_and_saved_without_touching_hdmi(self):
        self.assertEqual(self.initialize(), ['PCH'])
        self.assertIn(['amixer', '-c', 'PCH', 'sset', 'Master', '70%', 'unmute'], self.commands)
        self.assertIn(['alsactl', 'store', 'PCH'], self.commands)
        self.assertNotIn(['alsactl', 'store', 'HDMI'], self.commands)

    def test_saved_state_preserves_deliberate_mute(self):
        self.state.write_text('state.PCH {\n}\n')
        self.assertEqual(self.initialize(), [])
        self.assertNotIn(['amixer', '-c', 'PCH', 'sset', 'Master', '70%', 'unmute'], self.commands)

    def test_other_card_state_does_not_hide_new_analog_card(self):
        self.state.write_text('state.HDMI {\n}\n')
        self.assertEqual(self.initialize(), ['PCH'])

    def test_existing_nonzero_volume_is_not_overwritten(self):
        self.master = 'Mono: Playback 58 [67%] [-21.75dB] [on]'
        self.assertEqual(self.initialize(), ['PCH'])
        self.assertNotIn(['amixer', '-c', 'PCH', 'sset', 'Master', '70%', 'unmute'], self.commands)
        self.assertIn(['alsactl', 'store', 'PCH'], self.commands)

    def test_muted_nonzero_volume_is_unmuted(self):
        self.master = 'Mono: Playback 58 [67%] [-21.75dB] [off]'
        self.assertEqual(self.initialize(), ['PCH'])
        self.assertIn(['amixer', '-c', 'PCH', 'sset', 'Master', '70%', 'unmute'], self.commands)

    def test_zero_volume_with_switch_on_is_raised(self):
        self.master = 'Mono: Playback 0 [0%] [-65.25dB] [on]'
        self.assertEqual(self.initialize(), ['PCH'])
        self.assertIn(['amixer', '-c', 'PCH', 'sset', 'Master', '70%', 'unmute'], self.commands)

    def test_no_card_does_not_create_state(self):
        self.cards.write_text('--- no soundcards ---\n')
        self.assertEqual(self.initialize(), [])
        self.assertEqual(self.commands, [])

    def test_installer_and_release_carry_bootstrap_and_tools(self):
        installer = (ROOT / 'provisioning/install.sh').read_text()
        prepare = (ROOT / 'provisioning/graphics/prepare-browser.py').read_text()
        inventory = (ROOT / 'release/host-files.json').read_text()
        self.assertIn('apt-get install -y alsa-utils', installer)
        self.assertIn('install -m 0644 "$PAYLOAD_DIR/provisioning/graphics/prepare-browser.py"', installer)
        self.assertIn('initialize_audio()', prepare)
        self.assertIn('runtime/prepare-browser.py', inventory)


if __name__ == '__main__':
    unittest.main()
