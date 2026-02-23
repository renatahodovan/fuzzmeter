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

from fuzzmeter.snapshot.resource_telemetry import ResourceTelemetryCollector
from fuzzmeter.trial.models import ActiveTrial


class ResourceTelemetryTest(unittest.TestCase):
    '''Verify container telemetry is collected only for live trials.'''

    def test_replay_trials_skip_docker_stats(self) -> None:
        '''Replay trials have no live fuzzer container, so docker stats must not run.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial = _active_trial(Path(tmp_dir), replay=True)

            with patch.object(ResourceTelemetryCollector, '_docker_stats') as docker_stats:
                ResourceTelemetryCollector().collect(db=None, tick_idx=1, ts=100, active_trials=[trial])

            docker_stats.assert_not_called()

    def test_live_trials_collect_docker_stats(self) -> None:
        '''Live trials still collect CPU and memory data from their container.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial = _active_trial(Path(tmp_dir), replay=False)

            with patch.object(
                ResourceTelemetryCollector,
                '_docker_stats',
                return_value={'CPUPerc': '1.5%', 'MemUsage': '2MiB / 4MiB', 'MemPerc': '50%'},
            ) as docker_stats, \
                 patch.object(ResourceTelemetryCollector, '_du_hs', return_value=('1K', 1024)), \
                 patch('fuzzmeter.snapshot.resource_telemetry.db_resource_telemetry.upsert_resource_telemetry') as upsert:
                ResourceTelemetryCollector().collect(db=None, tick_idx=1, ts=100, active_trials=[trial])

            docker_stats.assert_called_once_with('container')
            upsert.assert_called_once()


def _active_trial(root: Path, *, replay: bool) -> ActiveTrial:
    trial_root = root / 'trial'
    return ActiveTrial(
        trial_row_id=1,
        trial_id='trial',
        container_name='replay-trial' if replay else 'container',
        fuzzer='aflplusplus',
        fuzzer_base='aflplusplus',
        benchmark='bench',
        fuzz_target='target',
        input_mode='file',
        rep=0,
        runner_image='runner',
        coverage_image='coverage',
        asan_image='asan',
        snapshot_preprocess_script=None,
        trial_root=trial_root,
        live_out=trial_root / 'work',
        fuzzer_log=trial_root / 'logs' / 'fuzzer.log',
        corpus_root=trial_root / 'work' / 'default' / 'queue',
        crashes_root=trial_root / 'work' / 'default' / 'crashes',
        snapshots_root=trial_root / 'snapshots',
        seed_root=None,
        repo_root=root,
        started_ts=100,
        replay_start_ts=100 if replay else None,
        replay_end_ts=200 if replay else None,
    )


if __name__ == '__main__':
    unittest.main()
