"""Verify the resources required by an installed FuzzMeter distribution."""

from __future__ import annotations

import tempfile
import unittest

from importlib import resources
from pathlib import Path

from fuzzmeter.paths import docker_resources, entrypoint_resources, instrumentation_resources
from fuzzmeter.reporting.assets import write_assets


class InstalledResourcesTest(unittest.TestCase):
    """Verify that package-data resources are available after installation."""

    def test_container_resources_are_installed(self) -> None:
        """Verify Docker files, entrypoints, and instrumentation profiles."""

        for root, files in (
            (
                docker_resources(),
                (
                    'benchmark-base.Dockerfile',
                    'build-base.Dockerfile',
                    'campaign.Dockerfile',
                    'clang-base.Dockerfile',
                    'instrumentation-runtime.Dockerfile',
                    'runtime-base.Dockerfile',
                    'runtime-tools.Dockerfile',
                ),
            ),
            (
                entrypoint_resources(),
                (
                    'campaign_build.py',
                    'coverage_sets.py',
                    'coverage_worker.py',
                    'crash_worker.py',
                    'run_fuzzer.py',
                ),
            ),
            (
                instrumentation_resources(),
                ('asan/Dockerfile', 'asan/build.py', 'coverage/Dockerfile', 'coverage/build.py'),
            ),
        ):
            for path in files:
                self.assertTrue(root.joinpath(*Path(path).parts).is_file(), path)

    def test_web_assets_are_installed(self) -> None:
        """Verify static-report export resolves and copies its packaged assets."""

        web_root = resources.files('fuzzmeter').joinpath('web')
        for path in ('templates/runs.html', 'static/runs.css', 'static/runs.js'):
            self.assertTrue(web_root.joinpath(*Path(path).parts).is_file(), path)

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir) / 'report'
            write_assets(report_dir, {})
            self.assertTrue((report_dir / 'report.html').is_file())
            self.assertTrue((report_dir / 'report.css').is_file())
            self.assertTrue((report_dir / 'report.js').is_file())
            self.assertTrue((report_dir / 'report' / 'app.js').is_file())
            self.assertTrue((report_dir / 'report' / 'favicon.png').is_file())
            self.assertTrue((report_dir / 'report' / 'favicon.svg').is_file())


if __name__ == '__main__':
    unittest.main()
