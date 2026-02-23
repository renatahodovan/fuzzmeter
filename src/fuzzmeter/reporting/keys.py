# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

COV_METRICS = ('lines', 'branches', 'functions', 'regions')

FINAL_DIST_KEYS = (
    'lines_cov',
    'branches_cov',
    'functions_cov',
    'regions_cov',
    'lines_total',
    'branches_total',
    'functions_total',
    'regions_total',
    'lines_pct',
    'branches_pct',
    'functions_pct',
    'regions_pct',
    'execs_done',
    'execs_per_sec',
    'corpus_files_total',
    'unique_bugs_total',
    'bug_hits_total',
    'crashes_total',
    'resource_cpu_percent',
    'resource_memory_mib',
    'resource_memory_percent',
    'resource_corpus_disk_mib',
)

SNAPSHOT_COVERAGE_FIELDS = {
    'lines': ('cov_lines_covered', 'cov_lines_total'),
    'branches': ('cov_branches_covered', 'cov_branches_total'),
    'functions': ('cov_functions_covered', 'cov_functions_total'),
    'regions': ('cov_regions_covered', 'cov_regions_total'),
}

TRIAL_METADATA_FIELDS = (
    'fuzzer_image',
    'build_config_json',
    'runtime_config_json',
)
