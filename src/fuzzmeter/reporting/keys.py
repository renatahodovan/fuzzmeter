# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Define shared reporting metric and field names.'''

from __future__ import annotations

BRANCH_COVERAGE_METRIC = 'branches'
COV_METRICS = (BRANCH_COVERAGE_METRIC, 'lines', 'functions', 'regions')

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
    BRANCH_COVERAGE_METRIC: ('cov_branches_covered', 'cov_branches_total'),
    'lines': ('cov_lines_covered', 'cov_lines_total'),
    'functions': ('cov_functions_covered', 'cov_functions_total'),
    'regions': ('cov_regions_covered', 'cov_regions_total'),
}

UNIQUE_MATRIX_KEY = 'unique_matrix'
RELCOV_MATRIX_KEY = 'relcov_matrix'
BRANCH_MWU_MATRIX_KEY = 'branch_mwu_matrix'
BRANCH_A12_MATRIX_KEY = 'branch_a12_matrix'
RELCOV_SCORE_BY_FUZZER_KEY = 'relcov_score_by_fuzzer'
UNIQUE_BUG_TABLE_KEY = 'unique_bug_table'
UNIQUE_BUG_MATRIX_KEY = 'unique_bug_matrix'
RELBUG_MATRIX_KEY = 'relbug_matrix'
RELBUG_SCORE_BY_FUZZER_KEY = 'relbug_score_by_fuzzer'

MATRIX_PAYLOAD_KEYS = (
    UNIQUE_MATRIX_KEY,
    RELCOV_MATRIX_KEY,
    BRANCH_MWU_MATRIX_KEY,
    BRANCH_A12_MATRIX_KEY,
    RELCOV_SCORE_BY_FUZZER_KEY,
    UNIQUE_BUG_TABLE_KEY,
    UNIQUE_BUG_MATRIX_KEY,
    RELBUG_MATRIX_KEY,
    RELBUG_SCORE_BY_FUZZER_KEY,
)
