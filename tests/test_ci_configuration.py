"""Tests for the repository's continuous-integration gates."""

import configparser
import unittest

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CiConfigurationTest(unittest.TestCase):
    def test_tox_exposes_all_ci_environments(self):
        config = configparser.ConfigParser()
        config.read(PROJECT_ROOT / 'tox.ini')

        self.assertEqual('lint, type, unit, cov', config['tox']['env_list'])
        self.assertEqual('ruff check src tests fuzzers', config['testenv:lint']['commands'].strip())
        self.assertEqual('mypy src', config['testenv:type']['commands'].strip())
        self.assertEqual(
            'python -m unittest discover -s tests',
            config['testenv:unit']['commands'].strip(),
        )
        self.assertEqual(
            'coverage erase\n'
            'coverage run --source=src/fuzzmeter -m unittest discover -s tests\n'
            'coverage report --skip-empty --precision=2 --fail-under=78.04\n'
            'coverage xml -o {envtmpdir}/coverage.xml',
            config['testenv:cov']['commands'].strip(),
        )

    def test_workflow_runs_all_tox_environments_on_supported_versions(self):
        workflow = (PROJECT_ROOT / '.github/workflows/ci.yml').read_text()

        self.assertIn('push:', workflow)
        self.assertIn('pull_request:', workflow)
        self.assertIn("python-version: ['3.10', '3.11', '3.12', '3.13', '3.14']", workflow)
        self.assertIn('python -m tox run -e lint,type,unit', workflow)
        self.assertIn('name: Coverage', workflow)
        self.assertIn('python -m tox run -e cov', workflow)
        self.assertIn('uses: coverallsapp/github-action@v2', workflow)
        self.assertIn('file: .tox/cov/tmp/coverage.xml', workflow)

        readme = (PROJECT_ROOT / 'README.rst').read_text()
        self.assertIn('coverallsCoverage/github/renatahodovan/fuzzmeter/main', readme)

    def test_ruff_profile_keeps_grammarinator_style_without_strict_extras(self):
        pyproject = (PROJECT_ROOT / 'pyproject.toml').read_text()
        lint_config = pyproject.split('[tool.ruff.lint]', 1)[1].split('[tool.mypy]', 1)[0]

        for rule in ('"E"', '"F"', '"W"', '"I"', '"B"', '"D100"', '"D104"'):
            self.assertIn(rule, lint_config)
        for strict_group in ('"D"', '"PTH"', '"SIM"', '"RET"', '"T20"', '"UP"'):
            self.assertNotIn(strict_group, lint_config)


if __name__ == '__main__':
    unittest.main()
