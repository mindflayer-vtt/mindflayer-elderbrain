from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicGovernanceTests(unittest.TestCase):
    def test_codeowners_assigns_release_security_surfaces_to_existing_maintainer(self):
        owners = (ROOT / ".github/CODEOWNERS").read_text()
        for pattern in (
                "*", "/.github/workflows/", "/release/", "/config/releases/",
                "/config/defaults/*requirements*", "/setup/Dockerfile",
                "/appliance/lib/release_*", "/appliance/lib/update_*",
                "/provisioning/update/", "/iso/"):
            self.assertIn(f"{pattern} @749", owners)

    def test_transition_checklist_orders_visibility_before_protections_and_release(self):
        document = (ROOT / "docs/PUBLIC-RELEASE-CHECKLIST.md").read_text()
        ordered = [
            "Confirm local and remote `main`", "Run `make public-audit`",
            "Make `mindflayer-vtt/mindflayer-elderbrain` public",
            "create or enable the `main` branch ruleset", "Require the green `test` status",
            "Require changes through a pull request", "Require review from CODEOWNERS",
            "Disable force pushes", "Disable branch deletion", "Open the `appliance-release`",
            "Require at least one approving reviewer", "exactly one deployment branch policy",
            "Add `APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY` only as an Environment secret",
            "public-key derivation check", "no repository or organization Actions secret duplicates",
            "change\n    package visibility to public", "approve and publish the first signed update",
        ]
        positions = [document.index(value) for value in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("version: 0.1.1", document)
        self.assertIn("release_sequence: 2", document)
        self.assertIn("actual public GitHub Release artifacts", document)

    def test_public_docs_state_non_hermetic_install_and_release_boundaries(self):
        build = (ROOT / "docs/BUILD.md").read_text()
        release = (ROOT / "docs/RELEASE-FORMAT.md").read_text()
        self.assertIn("may resolve newer packages from authenticated Ubuntu", build)
        self.assertIn("not a fully offline Linux distribution", build)
        self.assertIn("not a hermetic or bit-reproducible release build", release)
        self.assertIn("pip may therefore resolve upstream build-isolation inputs", release)
        self.assertIn("appliances install that bundle offline", release)


if __name__ == "__main__":
    unittest.main()
