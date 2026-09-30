/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Compatibility export surface for report helper modules.
 */

import {
  aLink,
  byId,
  debounce,
  el,
  fetchJSON,
  fromTemplate,
  part,
  sanitizeId,
} from './dom.js';
import {
  fmt,
  fmtInt,
  fmtPct,
  formatDuration,
  formatExecCount,
  formatGroupedNumber,
  formatShortNumber,
  maximum,
  minimum,
} from './format.js';
import {
  COVERAGE_METRICS,
  FM_PALETTE,
  MATRIX_PAYLOAD_KEYS,
  VALUE_OPTIONS,
  assignFuzzerColors,
  buildCoverageSeries,
  buildCurveSeries,
  comparisonMatrix,
  comparisonMetric,
  configPayload,
  dedupeBugCount,
  distributionValues,
  finalMetricValue,
  fuzzerColor,
  hashString,
  metricCovKey,
  metricLabel,
  metricTotalKey,
  pctValue,
  per10kExec,
} from './report-data.js';
import { FM_APP, THEME_STORAGE_KEY } from './state.js';
import {
  cleanFloats,
  erf,
  mannWhitneyUPValue,
  median,
  quantile,
  rankdataDesc,
} from './stats.js';
import {
  applySearch,
  applyTheme,
  createConfigLink,
  createFuzzerNameButton,
  ensureConfigModal,
  openConfigModal,
  preferredTheme,
  renderAggregateCell,
  setTooltip,
} from './ui.js';

export { aLink, byId, debounce, el, fetchJSON, fromTemplate, part, sanitizeId };
export { fmt, fmtInt, fmtPct, formatDuration, formatExecCount, formatGroupedNumber, formatShortNumber, maximum, minimum };
export { COVERAGE_METRICS, FM_PALETTE, MATRIX_PAYLOAD_KEYS, VALUE_OPTIONS, assignFuzzerColors, buildCoverageSeries, buildCurveSeries };
export { comparisonMatrix, comparisonMetric, configPayload, dedupeBugCount, distributionValues, finalMetricValue, fuzzerColor, hashString };
export { metricCovKey, metricLabel, metricTotalKey, pctValue, per10kExec };
export { FM_APP, THEME_STORAGE_KEY };
export { cleanFloats, erf, mannWhitneyUPValue, median, quantile, rankdataDesc };
export { applySearch, applyTheme, createConfigLink, createFuzzerNameButton, ensureConfigModal };
export { openConfigModal, preferredTheme, renderAggregateCell, setTooltip };
