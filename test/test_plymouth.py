import struct
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PlymouthTests(unittest.TestCase):
    def test_theme_has_bounded_transparent_logo_and_spinner(self):
        logo = (ROOT / 'provisioning/plymouth/watermark.png').read_bytes()
        self.assertEqual(logo[:8], b'\x89PNG\r\n\x1a\n')
        width, height, depth, colour = struct.unpack('>IIBB', logo[16:26])
        self.assertEqual((width, height, depth, colour), (320, 320, 8, 6))
        theme = (ROOT / 'provisioning/plymouth/mindflayer.plymouth').read_text()
        self.assertIn('ModuleName=two-step', theme)
        self.assertIn('UseAnimation=true', theme)
        self.assertIn('BackgroundStartColor=0x090b13', theme)
        self.assertIn('BackgroundEndColor=0x090b13', theme)

    def test_install_selects_theme_and_rebuilds_boot_configuration(self):
        install = (ROOT / 'provisioning/install.sh').read_text()
        for expected in ('plymouth-theme-spinner', 'update-alternatives --install',
                         'update-alternatives --set default.plymouth',
                         'update-initramfs -u', 'update-grub'):
            self.assertIn(expected, install)
        grub = (ROOT / 'provisioning/plymouth/60-elderbrain-splash.cfg').read_text()
        self.assertIn('quiet splash', grub)
        self.assertNotIn('loglevel=0', grub)

    def test_graphics_handoff_retains_splash_and_failure_exposes_console(self):
        graphics = (ROOT / 'provisioning/systemd/elderbrain-graphics.service').read_text()
        self.assertLess(graphics.index('ExecStartPre=/opt/mindflayer-elderbrain/wait-ready'),
                        graphics.index('ExecStartPre=-+/usr/bin/plymouth quit --retain-splash'))
        self.assertLess(graphics.index('ExecStartPre=-+/usr/bin/plymouth quit --retain-splash'),
                        graphics.index('ExecStart=/usr/bin/sway'))
        self.assertIn('must not prevent display previews', graphics)
        self.assertIn('OnFailure=elderbrain-graphics-failure.service', graphics)
        failure = (ROOT / 'provisioning/graphics/boot-failure').read_text()
        self.assertIn('/usr/bin/plymouth quit', failure)
        self.assertIn('/dev/tty1', failure)
        self.assertIn('journalctl -b -u elderbrain-graphics.service', failure)
        quit_order = (ROOT / 'provisioning/plymouth/elderbrain-graphics.conf').read_text()
        self.assertIn('After=elderbrain-graphics.service', quit_order)

    def test_browser_loading_state_matches_boot_presentation(self):
        self.assertEqual((ROOT / 'setup/app/assets/mindflayer.png').read_bytes(),
                         (ROOT / 'provisioning/plymouth/watermark.png').read_bytes())
        app = (ROOT / 'setup/app/app.vue').read_text()
        self.assertIn('aria-label="Loading Elderbrain"', app)
        self.assertIn('bg-[#090b13]', app)
        self.assertIn('animate-spin', app)


if __name__ == '__main__':
    unittest.main()
