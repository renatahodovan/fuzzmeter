/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Shared report application state.
 */

export const THEME_STORAGE_KEY = 'fuzzmeter-report-theme';

export const FM_APP = {
  data: null,
  rawData: null,
  state: {
    theme: 'dark',
    fuzzerColors: new Map(),
    selectedFuzzers: new Set(),
    selectedBenchmarks: new Set(),
    coverageByTarget: new Map(),
    comparisonMode: 'any',
    summarySort: { key: 'coverage_score', direction: 'desc' },
  },
  sections: [],
  redrawCharts: () => {},
  activeTocCleanup: null,
  activeNavCleanup: null,
};
