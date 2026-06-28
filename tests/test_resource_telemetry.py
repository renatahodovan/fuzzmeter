# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for resource telemetry collection.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.snapshot.resource_telemetry import ResourceTelemetryCollector
from fuzzmeter.trial.models import TrialConfig, TrialImages, TrialInstance, TrialLayout


def _active_trial(root: Path, *, db_id: int = 1) -> TrialInstance:
    config = TrialConfig(
        fuzzer='aflplusplus',
        fuzzer_base='aflplusplus',
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
        images=TrialImages(fuzzer_name='aflplusplus', target_id='bench-target'),
    )
    layout = TrialLayout.from_config(trial_dir=root / 'trial', cfg=config)
    layout.fuzz_dir.mkdir(parents=True, exist_ok=True)
    return TrialInstance(
        db_id=db_id,
        config=config,
        layout=layout,
        container_name='container',
        fuzzers_root=root,
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
            trial_row_id=trial.db_id,
            idx=1,
            ts=100,
            container_name='container',
            cpu_percent=1.5,
            memory_usage_bytes=2 * 1024 * 1024,
            memory_limit_bytes=4 * 1024 * 1024,
            memory_percent=50.0,
            corpus_disk_usage_bytes=2 * 1024,
        )


if __name__ == '__main__':
    unittest.main()
