from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ContinuousIntegrationTests(unittest.TestCase):
    def test_ci_pins_actions_and_exercises_target_runtime(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("runs-on: ubuntu-26.04", workflow)
        self.assertIn('python-version: "3.14"', workflow)
        self.assertIn("apt-get install --no-install-recommends -y ripgrep", workflow)
        actions = re.findall(r"uses: (actions/[^@]+)@([^ #]+)", workflow)
        self.assertEqual({name for name, _ in actions},
                         {"actions/checkout", "actions/setup-python", "actions/setup-node"})
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in actions))

    def test_actionlint_is_version_and_digest_pinned_for_every_workflow(self):
        script = (ROOT / "test/actionlint.sh").read_text()
        makefile = (ROOT / "Makefile").read_text()
        self.assertRegex(script, r"rhysd/actionlint:1[.]7[.]10@sha256:[0-9a-f]{64}")
        self.assertIn("find \"$root/.github/workflows\" -maxdepth 1 -type f -name '*.yml'", script)
        self.assertIn("lint: workflow-lint", makefile)
        self.assertIn("workflow-lint:\n\t@./test/actionlint.sh", makefile)
        self.assertIn("actionlint-invalid-context.yml", makefile)
        self.assertIn("INVALID_PATH: ${{ runner.temp }}", (
            ROOT / "test/fixtures/actionlint-invalid-context.yml").read_text())

    def test_static_checks_preflight_required_tools_before_work(self):
        script = (ROOT / "test/static.sh").read_text()
        preflight = 'for required_tool in awk find git grep python3 rg sed wc; do'
        self.assertIn(preflight, script)
        self.assertLess(script.index(preflight), script.index('root=$(cd'))
        self.assertLess(script.index(preflight), script.index("echo 'static checks passed'"))

    def test_sibling_test_fixtures_do_not_use_ambiguous_top_level_imports(self):
        for source in (ROOT / "test").glob("test_*.py"):
            self.assertIsNone(re.search(r"^import test[.]test_", source.read_text(), re.MULTILINE), source.name)


if __name__ == "__main__":
    unittest.main()
