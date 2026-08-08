"""Tests for the repository's continuous-integration gates."""

import configparser
import unittest

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CiConfigurationTest(unittest.TestCase):
    def test_tox_exposes_all_ci_environments(self):
        config = configparser.ConfigParser()
        config.read(PROJECT_ROOT / 'tox.ini')

        self.assertEqual('lint, type, unit', config['tox']['env_list'])
        self.assertEqual('ruff check src tests fuzzers', config['testenv:lint']['commands'].strip())
        self.assertEqual('mypy src', config['testenv:type']['commands'].strip())
        self.assertEqual(
            'python -m unittest discover -s tests',
            config['testenv:unit']['commands'].strip(),
        )

    def test_workflow_runs_all_tox_environments_on_supported_versions(self):
        workflow = (PROJECT_ROOT / '.github/workflows/ci.yml').read_text()

        self.assertIn('push:', workflow)
        self.assertIn('pull_request:', workflow)
        self.assertIn("python-version: ['3.10', '3.11', '3.12', '3.13', '3.14']", workflow)
        self.assertIn('python -m tox run -e lint,type,unit', workflow)

    def test_ruff_profile_keeps_grammarinator_style_without_strict_extras(self):
        pyproject = (PROJECT_ROOT / 'pyproject.toml').read_text()
        lint_config = pyproject.split('[tool.ruff.lint]', 1)[1].split('[tool.mypy]', 1)[0]

        for rule in ('"E"', '"F"', '"W"', '"I"', '"B"', '"D100"', '"D104"'):
            self.assertIn(rule, lint_config)
        for strict_group in ('"D"', '"PTH"', '"SIM"', '"RET"', '"T20"', '"UP"'):
            self.assertNotIn(strict_group, lint_config)


if __name__ == '__main__':
    unittest.main()
