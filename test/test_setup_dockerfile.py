from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupDockerfileTests(unittest.TestCase):
    def test_every_node_stage_retains_version_and_immutable_digest(self):
        lines = [line for line in (ROOT / 'setup/Dockerfile').read_text().splitlines()
                 if line.startswith('FROM ')]
        self.assertEqual(len(lines), 2)
        references = [line.split()[1] for line in lines]
        self.assertEqual(len(set(references)), 1)
        self.assertRegex(references[0], r'^node:24\.16\.0-alpine@sha256:[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
