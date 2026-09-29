# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for resource telemetry collection.'''

from __future__ import annotations

import subprocess
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.db.resource_telemetry import TelemetrySample
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.snapshot.resource_telemetry import ResourceTelemetryCollector
from fuzzmeter.trial.models import TrialInstance, TrialLayout
from tests.support.trials import make_trial_config


def _active_trial(root: Path, *, db_id: int = 1) -> TrialInstance:
    config = make_trial_config(
        fuzzer='aflplusplus',
        fuzzer_impl='aflplusplus',
        benchmark='bench',
        fuzz_target='target',
        fuzz_target_bin=root / 'target_bin',
        fuzz_target_input_mode='file',
        fuzz_target_timeout=1.0,
        rep_idx=0,
        trial_key='trial',
        output_paths=OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
        ),
        trial_timeout=300,
        snapshot_preprocess=None,
    )
    layout = TrialLayout.from_config(trial_dir=root / 'trial', cfg=config)
    layout.fuzz_dir.mkdir(parents=True, exist_ok=True)
    return TrialInstance(
        db_id=db_id,
        config=config,
        layout=layout,
        container_name='container',
        fuzzer_dirs={'aflplusplus': root / 'aflplusplus'},
        start_ts=100,
    )


class ResourceTelemetryTest(unittest.TestCase):
    '''Verify container telemetry is collected for active live trials.'''

    def test_live_trials_collect_docker_stats(self) -> None:
        '''Live trials collect CPU, memory, and disk telemetry.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial = _active_trial(Path(tmp_dir))

            with patch.object(
                ResourceTelemetryCollector,
                '_docker_stats_by_container',
                return_value={
                    'container': {
                        'Name': 'container',
                        'CPUPerc': '1.5%',
                        'MemUsage': '2MiB / 4MiB',
                        'MemPerc': '50%',
                    }
                },
            ) as docker_stats, \
                 patch.object(ResourceTelemetryCollector, '_du_sk', return_value=2), \
                 patch('fuzzmeter.snapshot.resource_telemetry.db_resource_telemetry.upsert_resource_telemetry') as upsert:
                ResourceTelemetryCollector().collect(db=None, tick_idx=1, ts=100, active_trials=[trial])

        docker_stats.assert_called_once_with(['container'])
        upsert.assert_called_once_with(
            None,
            TelemetrySample(
                trial_id=trial.db_id,
                idx=1,
                ts=100,
                container_name='container',
                cpu_percent=1.5,
                memory_usage_bytes=2 * 1024 * 1024,
                memory_limit_bytes=4 * 1024 * 1024,
                memory_percent=50.0,
                corpus_disk_usage_bytes=2 * 1024,
            ),
        )

    def test_exited_container_records_absent_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial = _active_trial(Path(tmp_dir))

            upsert_target = 'fuzzmeter.snapshot.resource_telemetry.db_resource_telemetry.upsert_resource_telemetry'
            with (
                patch.object(ResourceTelemetryCollector, '_docker_stats_by_container', return_value={}),
                patch.object(ResourceTelemetryCollector, '_du_sk', return_value=2),
                patch(upsert_target) as upsert,
            ):
                ResourceTelemetryCollector().collect(db=None, tick_idx=1, ts=100, active_trials=[trial])

        upsert.assert_called_once_with(
            None,
            TelemetrySample(
                trial_id=trial.db_id,
                idx=1,
                ts=100,
                container_name='container',
                cpu_percent=None,
                memory_usage_bytes=None,
                memory_limit_bytes=None,
                memory_percent=None,
                corpus_disk_usage_bytes=2 * 1024,
            ),
        )

    def test_docker_stats_failure_keeps_disk_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial = _active_trial(Path(tmp_dir))

            upsert_target = 'fuzzmeter.snapshot.resource_telemetry.db_resource_telemetry.upsert_resource_telemetry'
            failure = subprocess.CalledProcessError(1, 'docker', stderr='No such container: container')
            with (
                patch('fuzzmeter.snapshot.resource_telemetry.subprocess.run', side_effect=failure),
                patch.object(ResourceTelemetryCollector, '_du_sk', return_value=2),
                patch(upsert_target) as upsert,
            ):
                ResourceTelemetryCollector().collect(db=None, tick_idx=1, ts=100, active_trials=[trial])

        self.assertIsNone(upsert.call_args.args[1].cpu_percent)
        self.assertEqual(2 * 1024, upsert.call_args.args[1].corpus_disk_usage_bytes)


if __name__ == '__main__':
    unittest.main()
