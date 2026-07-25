# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Expose container coverage set helpers to host-side reporting.'''

from ..resources.entrypoints.coverage_sets import (
    COVERAGE_METRICS,
    coverage_metrics_from_export,
    coverage_summary_from_export,
    read_covered_keys,
    write_coverage_sets,
)

__all__ = [
    'COVERAGE_METRICS',
    'coverage_metrics_from_export',
    'coverage_summary_from_export',
    'read_covered_keys',
    'write_coverage_sets',
]
