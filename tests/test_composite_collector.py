# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite descriptor collection.'''

from __future__ import annotations

import unittest

from unittest.mock import patch

from fuzzmeter.composite import canonical_digest
from fuzzmeter.composite.collect import collect_config, collect_environment, metadata_for_case
from fuzzmeter.config import CampaignCase


class CompositeCollectorTest(unittest.TestCase):
    '''Verify collected composite descriptor metadata.'''

    def test_config_metadata_uses_target_identity_display_fields(self) -> None:
        '''Config metadata contains the target fields shown and diffed in the UI.'''
        case = _case()

        self.assertEqual(
            {
                'benchmark': 'zlib',
                'fuzz_target': 'compress',
                'input_mode': 'file',
                'timeout': 2.0,
            },
            collect_config(case),
        )

    def test_metadata_without_hooks_has_stable_digests_and_missing_source(self) -> None:
        '''Disabled source hooks are represented explicitly and digestable.'''
        metadata = metadata_for_case(
            case=_case(),
            environment={'host': {'system': 'Darwin'}},
            fuzzer_dirs={},
            benchmark_dirs={},
            source_info_enabled=False,
        )

        self.assertIsNotNone(metadata.environment_digest)
        self.assertIsNotNone(metadata.config_digest)
        self.assertIsNotNone(metadata.source_digest)
        self.assertEqual('missing', metadata.source['benchmark_source']['status'])
        self.assertEqual('missing', metadata.source['fuzzer_version']['status'])

    def test_environment_digest_ignores_volatile_docker_counters(self) -> None:
        '''Docker counters and timestamps are not part of the environment digest.'''
        docker_info = {
            'Architecture': 'x86_64',
            'KernelVersion': '6.8',
            'ServerVersion': '26',
            'SystemTime': 'now',
            'Images': 41,
        }
        docker_version = {'Server': {'Version': '26'}, 'Client': {'Version': '26'}}

        def docker_json(command: str) -> dict[str, object]:
            return dict(docker_version if command == 'version' else docker_info)

        with patch('fuzzmeter.composite.collect._docker_json', side_effect=docker_json), \
             patch('fuzzmeter.composite.collect._tool_version', return_value=None):
            first = collect_environment()

        docker_info['SystemTime'] = 'later'
        docker_info['Images'] = 43
        with patch('fuzzmeter.composite.collect._docker_json', side_effect=docker_json), \
             patch('fuzzmeter.composite.collect._tool_version', return_value=None):
            second = collect_environment()

        self.assertEqual(canonical_digest(first), canonical_digest(second))
        self.assertNotIn('SystemTime', first['docker']['info'])
        self.assertNotIn('Images', first['docker']['info'])


def _case() -> CampaignCase:
    return CampaignCase(
        fuzzer_name='libfuzzer',
        fuzzer_chain=('libfuzzer',),
        benchmark='zlib',
        fuzz_target='compress',
        input_mode='file',
        target_timeout_s=2.0,
    )


if __name__ == '__main__':
    unittest.main()
