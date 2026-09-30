/* Auto-generated static bundle for file:// report viewing. */

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
const THEME_STORAGE_KEY = 'fuzzmeter-report-theme';
const FM_APP = {
  data: null,
  rawData: null,
  state: {
    theme: 'dark',
    fuzzerColors: new Map(),
    selectedFuzzers: new Set(),
    selectedBenchmarks: new Set(),
    coverageByTarget: new Map(),
    targetTableSort: new Map(),
    comparisonMode: 'any',
    summarySort: { key: 'coverage_score', direction: 'desc' },
  },
  sections: [],
  redrawCharts: () => {},
  activeTocCleanup: null,
  activeNavCleanup: null,
};

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * DOM and browser utility helpers for the report UI.
 */
function byId(id) {
  return document.getElementById(id);
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function fromTemplate(id) {
  const template = byId(id);
  if (!(template instanceof HTMLTemplateElement)) {
    throw new Error(`Missing template: ${id}`);
  }
  return template.content.firstElementChild.cloneNode(true);
}
function part(root, name) {
  return root.querySelector(`[data-part='${name}']`);
}
function aLink(text, href) {
  const a = document.createElement('a');
  a.href = href;
  a.textContent = text;
  a.target = '_blank';
  a.rel = 'noreferrer';
  return a;
}
function sanitizeId(value) {
  return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}
async function fetchJSON(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}
function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Filters report matrix payloads to selected fuzzers.
 */
function cloneMatrixForSelected(matrixData, selectedSet) {
  if (!matrixData || !Array.isArray(matrixData.fuzzers)) return null;
  const indices = matrixData.fuzzers
    .map((fuzzer, index) => [String(fuzzer), index])
    .filter(([fuzzer]) => selectedSet.has(fuzzer));
  if (!indices.length) return null;
  const filterNumericMatrix = (matrix) => (
    Array.isArray(matrix)
      ? indices.map(([, rowIndex]) => indices.map(([, colIndex]) => {
        const value = (matrix[rowIndex] || [])[colIndex];
        return finiteOrNull(value);
      }))
      : undefined
  );
  const filterTextMatrix = (matrix) => (
    Array.isArray(matrix)
      ? indices.map(([, rowIndex]) => indices.map(([, colIndex]) => (
        (matrix[rowIndex] || [])[colIndex]
      )))
      : undefined
  );
  const filterNumericValues = (values, defaultValue = null) => (
    Array.isArray(values)
      ? indices.map(([, index]) => {
        const value = values[index];
        if (!isFiniteNumber(value)) return defaultValue;
        return Number(value);
      })
      : undefined
  );
  const filteredMatrix = filterNumericMatrix(matrixData.matrix);
  const pairwiseAny = filterNumericMatrix(matrixData.pairwise_unique_any);
  const pairwiseAll = filterNumericMatrix(matrixData.pairwise_unique_all);
  const numericValues = [filteredMatrix, pairwiseAny, pairwiseAll]
    .filter(Array.isArray)
    .flat(2)
    .filter((value) => isFiniteNumber(value))
    .map(Number);
  const exclusive = matrixData.exclusive ? {
    ...matrixData.exclusive,
    exclusive_any: filterNumericValues(matrixData.exclusive.exclusive_any),
    exclusive_all: filterNumericValues(matrixData.exclusive.exclusive_all),
    exclusive_any_bounds: Array.isArray(matrixData.exclusive.exclusive_any_bounds)
      ? indices.map(([, index]) => matrixData.exclusive.exclusive_any_bounds[index])
      : undefined,
    exclusive_all_bounds: Array.isArray(matrixData.exclusive.exclusive_all_bounds)
      ? indices.map(([, index]) => matrixData.exclusive.exclusive_all_bounds[index])
      : undefined,
  } : undefined;
  return {
    ...matrixData,
    fuzzers: indices.map(([fuzzer]) => fuzzer),
    matrix: filteredMatrix,
    pairwise_unique_any: pairwiseAny,
    pairwise_unique_all: pairwiseAll,
    pairwise_unique_any_bounds: filterTextMatrix(matrixData.pairwise_unique_any_bounds),
    pairwise_unique_all_bounds: filterTextMatrix(matrixData.pairwise_unique_all_bounds),
    exclusive,
    covered_counts: filterNumericValues(matrixData.covered_counts),
    unique_counts: filterNumericValues(matrixData.unique_counts),
    sample_sizes: filterNumericValues(matrixData.sample_sizes, 0),
    usable_sample_sizes: filterNumericValues(matrixData.usable_sample_sizes, 0),
    max_value: Math.max(0, ...numericValues),
    has_data: numericValues.some((value) => value > 0) || indices.length > 0,
  };
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Provides shared row comparators for report tables.
 */
function compareNumericRows(left, right, key, direction) {
  const leftValue = left?.[key];
  const rightValue = right?.[key];
  const leftMissing = leftValue === null || leftValue === undefined || Number.isNaN(Number(leftValue));
  const rightMissing = rightValue === null || rightValue === undefined || Number.isNaN(Number(rightValue));
  if (leftMissing && rightMissing) return String(left?.fuzzer || '').localeCompare(String(right?.fuzzer || ''));
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  const delta = Number(leftValue) - Number(rightValue);
  if (delta === 0) return String(left?.fuzzer || '').localeCompare(String(right?.fuzzer || ''));
  return direction === 'asc' ? delta : -delta;
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * DOM-independent statistical helpers for report data.
 */

// Missing values (null, undefined, '') stay missing: Number() would silently turn them into 0.
function finiteOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function isFiniteNumber(value) {
  return finiteOrNull(value) !== null;
}
function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined
    ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
    : sorted[base];
}
function median(values) {
  const sorted = (values || []).filter((value) => isFiniteNumber(value)).map(Number).sort((a, b) => a - b);
  return quantile(sorted, 0.5);
}
function cleanFloats(values) {
  return (values || [])
    .filter((value) => isFiniteNumber(value))
    .map(Number);
}
function rankdataDesc(values) {
  const indexed = values
    .map((value, index) => [index, value])
    .filter(([, value]) => isFiniteNumber(value))
    .map(([index, value]) => [index, Number(value)]);
  if (!indexed.length) return values.map(() => null);
  indexed.sort((left, right) => right[1] - left[1]);
  const ranks = values.map(() => null);
  let pos = 1;
  let i = 0;
  while (i < indexed.length) {
    let j = i + 1;
    while (j < indexed.length && indexed[j][1] === indexed[i][1]) j += 1;
    const avgRank = (pos + (pos + (j - i) - 1)) / 2;
    for (let k = i; k < j; k += 1) {
      ranks[indexed[k][0]] = avgRank;
    }
    pos += j - i;
    i = j;
  }
  return ranks;
}
function mannWhitneyUPValue(xValues, yValues) {
  const x = cleanFloats(xValues);
  const y = cleanFloats(yValues);
  const n1 = x.length;
  const n2 = y.length;
  if (n1 < 2 || n2 < 2) return null;
  const combined = x.map((value) => [value, 0]).concat(y.map((value) => [value, 1]));
  combined.sort((left, right) => left[0] - right[0]);
  const ranks = new Array(combined.length).fill(0);
  let i = 0;
  while (i < combined.length) {
    let j = i + 1;
    while (j < combined.length && combined[j][0] === combined[i][0]) j += 1;
    const avg = (i + 1 + j) / 2;
    for (let k = i; k < j; k += 1) ranks[k] = avg;
    i = j;
  }
  let r1 = 0;
  combined.forEach(([, grp], index) => {
    if (grp === 0) r1 += ranks[index];
  });
  const u1 = r1 - (n1 * (n1 + 1)) / 2;
  const u2 = n1 * n2 - u1;
  const u = Math.min(u1, u2);
  let tieSum = 0;
  i = 0;
  while (i < combined.length) {
    let j = i + 1;
    while (j < combined.length && combined[j][0] === combined[i][0]) j += 1;
    const t = j - i;
    if (t > 1) tieSum += t ** 3 - t;
    i = j;
  }
  const mu = (n1 * n2) / 2;
  const n = n1 + n2;
  const sigmaSq = (n1 * n2 / 12) * (n + 1 - tieSum / (n * (n - 1)));
  if (sigmaSq <= 0) return null;
  const z = (u - mu + 0.5) / Math.sqrt(sigmaSq);
  const pOne = 0.5 * (1 + erf(z / Math.sqrt(2)));
  return Math.max(0, Math.min(1, 2 * Math.min(pOne, 1 - pOne)));
}
function erf(value) {
  const sign = value < 0 ? -1 : 1;
  const x = Math.abs(value);
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;
  const t = 1 / (1 + p * x);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return sign * y;
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Number and duration formatters for report views.
 */
function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}
function fmtPct(value, digits = 2) {
  return value === null || value === undefined ? '—' : `${fmt(value, digits)}%`;
}
function fmtInt(value) {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : `${Math.round(Number(value))}`;
}
function formatGroupedNumber(value, options = {}) {
  if (!isFiniteNumber(value)) return '—';
  const parts = new Intl.NumberFormat(undefined, options).formatToParts(Number(value));
  return parts.map((part) => (part.type === 'group' ? ' ' : part.value)).join('');
}
function formatShortNumber(value) {
  if (!isFiniteNumber(value)) return '';
  const n = Number(value);
  const abs = Math.abs(n);
  if (abs < 1000) return String(Math.round(n));
  if (abs < 1e6) return `${(n / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}k`;
  if (abs < 1e9) return `${(n / 1e6).toFixed(abs >= 1e8 ? 0 : 1)}M`;
  return `${(n / 1e9).toFixed(1)}B`;
}
function maximum(values) {
  const clean = cleanFloats(values);
  return clean.length ? Math.max(...clean) : null;
}
function minimum(values) {
  const clean = cleanFloats(values);
  return clean.length ? Math.min(...clean) : null;
}
function formatExecCount(value) {
  if (!isFiniteNumber(value)) return '—';
  const n = Number(value);
  const abs = Math.abs(n);
  if (abs < 1e3) return fmtInt(n);
  if (abs < 1e6) return `${(n / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}k`;
  if (abs < 1e9) return `${(n / 1e6).toFixed(abs >= 1e8 ? 0 : 1)}M`;
  return `${(n / 1e9).toFixed(abs >= 1e11 ? 0 : 1)}B`;
}
function formatDuration(seconds, { coarse = false } = {}) {
  if (coarse) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return '—';
    if (value < 3600) return `${Math.round(value / 60)}m`;
    if (value < 86400) {
      const hours = Math.floor(value / 3600);
      const minutes = Math.round((value % 3600) / 60);
      return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
    }
    const days = Math.floor(value / 86400);
    const hours = Math.round((value % 86400) / 3600);
    return hours ? `${days}d ${hours}h` : `${days}d`;
  }
  if (!isFiniteNumber(seconds)) return '—';
  const value = Math.max(0, Math.round(Number(seconds)));
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (secs || !parts.length) parts.push(`${secs}s`);
  return parts.join(' ');
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * DOM-independent report domain helpers and color assignment.
 */
function tickFailureNotice(overview) {
  const count = Number(overview?.failed_snapshot_ticks || 0);
  if (!Number.isFinite(count) || count <= 0) return null;
  return `Warning: ${count} snapshot tick${count === 1 ? '' : 's'} failed. Coverage and crash curves may contain unmeasured gaps.`;
}
function comparisonMetric(stats, mode) {
  const strict = mode === 'all';
  const valueKey = strict ? 'exclusive_all' : 'exclusive_any';
  const boundKey = `${valueKey}_bound`;
  const value = stats?.[valueKey];
  if (isFiniteNumber(value)) {
    return {
      value: Number(value),
      bound: String(stats?.[boundKey] || 'exact'),
    };
  }
  if (!strict && isFiniteNumber(stats?.total)) {
    return { value: Number(stats.total), bound: 'exact' };
  }
  return { value: null, bound: 'unknown' };
}
function comparisonMatrix(matrixData, mode) {
  if (!matrixData) return null;
  const strict = mode === 'all';
  const matrixKey = strict ? 'pairwise_unique_all' : 'pairwise_unique_any';
  const boundsKey = `${matrixKey}_bounds`;
  const selected = Array.isArray(matrixData[matrixKey])
    ? matrixData[matrixKey]
    : (!strict && Array.isArray(matrixData.matrix) ? matrixData.matrix : []);
  const numericValues = selected.flat().filter((value) => (
    isFiniteNumber(value)
  )).map(Number);
  return {
    ...matrixData,
    matrix: selected,
    cell_bounds: Array.isArray(matrixData[boundsKey]) ? matrixData[boundsKey] : undefined,
    max_value: Math.max(0, ...numericValues),
    comparison_mode: strict ? 'all' : 'any',
  };
}
const FM_PALETTE = [
  'rgba(120,180,255,0.95)',
  'rgba(255,160,120,0.95)',
  'rgba(130,220,150,0.95)',
  'rgba(255,220,120,0.95)',
  'rgba(188,156,255,0.95)',
  'rgba(110,226,240,0.95)',
  'rgba(255,160,210,0.95)',
  'rgba(190,200,215,0.95)',
  'rgba(255,116,143,0.95)',
  'rgba(147,214,76,0.95)',
  'rgba(255,191,87,0.95)',
  'rgba(93,173,226,0.95)',
  'rgba(165,105,189,0.95)',
  'rgba(72,201,176,0.95)',
  'rgba(245,176,65,0.95)',
  'rgba(236,112,99,0.95)',
  'rgba(84,153,199,0.95)',
  'rgba(88,214,141,0.95)',
  'rgba(229,152,102,0.95)',
  'rgba(133,193,233,0.95)',
];
const COVERAGE_METRICS = [
  ['branches', 'Branch coverage'],
  ['lines', 'Line coverage'],
  ['functions', 'Function coverage'],
  ['regions', 'Region coverage'],
];
const MATRIX_PAYLOAD_KEYS = Object.freeze({
  uniqueMatrix: 'unique_matrix',
  relcovMatrix: 'relcov_matrix',
  branchMwuMatrix: 'branch_mwu_matrix',
  branchA12Matrix: 'branch_a12_matrix',
  relcovScoreByFuzzer: 'relcov_score_by_fuzzer',
  uniqueBugTable: 'unique_bug_table',
  uniqueBugMatrix: 'unique_bug_matrix',
  relbugMatrix: 'relbug_matrix',
  relbugScoreByFuzzer: 'relbug_score_by_fuzzer',
});
const VALUE_OPTIONS = [['abs', 'Absolute'], ['pct', 'Percent']];
function pctValue(covered, total) {
  if (
    covered == null ||
    total == null ||
    !isFiniteNumber(covered) ||
    !isFiniteNumber(total) ||
    Number(total) <= 0
  ) {
    return null;
  }
  return 100 * Number(covered) / Number(total);
}
function metricLabel(metric) {
  const found = COVERAGE_METRICS.find(([value]) => value === metric);
  return found ? found[1] : 'Coverage';
}
function hashString(value) {
  let hash = 2166136261;
  const text = String(value || '');
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
function fuzzerColor(label) {
  const mapped = FM_APP.state.fuzzerColors.get(String(label || ''));
  if (mapped) return mapped;
  const idx = hashString(label) % FM_PALETTE.length;
  return FM_PALETTE[idx];
}
function assignFuzzerColors(data) {
  const names = [];
  (data.targets || []).forEach((target) => {
    (target.fuzzers || []).forEach((fuzzer) => {
      const name = String(fuzzer.fuzzer || '');
      if (name && !names.includes(name)) names.push(name);
    });
  });

  const colors = new Map();
  names.forEach((name, index) => {
    if (index < FM_PALETTE.length) {
      colors.set(name, FM_PALETTE[index]);
      return;
    }
    const hue = (index * 137.508) % 360;
    colors.set(name, `hsla(${hue.toFixed(1)}, 68%, 62%, 0.95)`);
  });
  FM_APP.state.fuzzerColors = colors;
}
function buildCoverageSeries(fuzzers, metric, mode) {
  const coveredKey = `${metric}_cov_median`;
  const lowCoveredKey = `${metric}_cov_min`;
  const highCoveredKey = `${metric}_cov_max`;
  const pctKey = `${metric}_pct_median`;
  const lowPctKey = `${metric}_pct_min`;
  const highPctKey = `${metric}_pct_max`;

  return (fuzzers || []).map((fuzzer) => {
    const baseline = fuzzer.seed_baseline || {};
    const baselineY = mode === 'pct'
      ? pctValue(baseline[`cov_${metric}_covered`], baseline[`cov_${metric}_total`])
      : finiteOrNull(baseline[`cov_${metric}_covered`]);
    return {
      label: fuzzer.fuzzer,
      color: fuzzerColor(fuzzer.fuzzer),
      baselineY,
      points: (fuzzer.curve || [])
        .map((point) => ({
          x: Number(point.elapsed_s),
          y: mode === 'pct'
            ? finiteOrNull(point[pctKey])
            : finiteOrNull(point[coveredKey]),
          lo: mode === 'pct'
            ? finiteOrNull(point[lowPctKey])
            : finiteOrNull(point[lowCoveredKey]),
          hi: mode === 'pct'
            ? finiteOrNull(point[highPctKey])
            : finiteOrNull(point[highCoveredKey]),
        }))
        .filter((point) => point.y != null && Number.isFinite(point.y)),
    };
  });
}
function buildCurveSeries(fuzzers, baseKey) {
  const centerKey = `${baseKey}_median`;
  const lowKey = `${baseKey}_min`;
  const highKey = `${baseKey}_max`;
  return (fuzzers || []).map((fuzzer) => {
    return {
      label: fuzzer.fuzzer,
      color: fuzzerColor(fuzzer.fuzzer),
      points: (fuzzer.curve || [])
        .map((point) => ({
          x: Number(point.elapsed_s),
          y: finiteOrNull(point[centerKey]),
          lo: finiteOrNull(point[lowKey]),
          hi: finiteOrNull(point[highKey]),
        }))
        .filter((point) => point.y != null && Number.isFinite(point.y)),
    };
  });
}
function metricCovKey(metric) {
  return `${metric}_cov`;
}
function metricTotalKey(metric) {
  return `${metric}_total`;
}
function finalMetricValue(fuzzer, metric, mode) {
  if (mode === 'pct') {
    const percent = fuzzer.final?.[`${metric}_pct_median`];
    return finiteOrNull(percent);
  }
  const covered = fuzzer.final?.[`${metricCovKey(metric)}_median`];
  return finiteOrNull(covered);
}
function distributionValues(fuzzer, metric, mode) {
  if (mode === 'pct') {
    return (fuzzer.distribution?.[`${metric}_pct`] || [])
      .filter((value) => isFiniteNumber(value))
      .map(Number);
  }
  return (fuzzer.distribution?.[metricCovKey(metric)] || [])
    .filter((value) => isFiniteNumber(value))
    .map(Number);
}
function dedupeBugCount(bugs) {
  return new Set((bugs || []).map((bug) => String(bug?.bug_key || '')).filter(Boolean)).size;
}
function per10kExec(covered, execsDone) {
  if (
    covered == null ||
    execsDone == null ||
    !isFiniteNumber(covered) ||
    !isFiniteNumber(execsDone) ||
    Number(execsDone) <= 0
  ) {
    return null;
  }
  return 10000 * Number(covered) / Number(execsDone);
}
function configPayload(versions) {
  const payload = {};
  if (versions?.build_config && Object.keys(versions.build_config).length) {
    payload.build = versions.build_config;
  }
  if (versions?.runtime_config && Object.keys(versions.runtime_config).length) {
    payload.runtime = versions.runtime_config;
  }
  return Object.keys(payload).length ? payload : null;
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Stateful report UI helpers for cells, modals, search, and theme.
 */
function renderAggregateCell(cell, primaryText, detailsText) {
  if (primaryText === '—') {
    cell.textContent = '—';
    return cell;
  }
  const wrap = el('div', 'aggregate-cell');
  wrap.appendChild(el('div', 'aggregate-primary', primaryText));
  (detailsText || []).forEach(([label, value]) => {
    wrap.appendChild(el('div', 'aggregate-detail', `${label} ${value}`));
  });
  cell.appendChild(wrap);
  return cell;
}
function setTooltip(node, text) {
  if (!node || !text) return node;
  node.title = text;
  return node;
}
function ensureConfigModal() {
  const modal = byId('configModal');
  const title = byId('configModalTitle');
  const body = byId('configModalBody');
  const runtimeTab = byId('configModalRuntimeTab');
  const metadataTab = byId('configModalMetadataTab');
  const close = byId('configModalClose');
  if (!modal || !title || !body || !runtimeTab || !metadataTab || !close) return null;
  if (!modal.dataset.bound) {
    close.addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', (event) => {
      if (event.target === modal) modal.classList.add('hidden');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') modal.classList.add('hidden');
    });
    modal.dataset.bound = '1';
  }
  return { modal, title, body, runtimeTab, metadataTab };
}

function metadataPayload(fuzzer) {
  const metadata = fuzzer?.metadata || {};
  const payload = {};
  if (metadata.config && Object.keys(metadata.config).length) payload.config = metadata.config;
  if (metadata.source && Object.keys(metadata.source).length) payload.source = metadata.source;
  if (metadata.environment && Object.keys(metadata.environment).length) payload.environment = metadata.environment;
  if (metadata.digests && Object.keys(metadata.digests).length) payload.digests = metadata.digests;
  return Object.keys(payload).length ? payload : null;
}

function setConfigModalTab(refs, tabName, runtimePayload, sourcePayload) {
  const isRuntime = tabName === 'runtime';
  refs.runtimeTab.classList.toggle('active', isRuntime);
  refs.metadataTab.classList.toggle('active', !isRuntime);
  refs.runtimeTab.setAttribute('aria-selected', String(isRuntime));
  refs.metadataTab.setAttribute('aria-selected', String(!isRuntime));
  refs.body.textContent = JSON.stringify((isRuntime ? runtimePayload : sourcePayload) || {}, null, 2);
}
function openConfigModal(fuzzer) {
  const refs = ensureConfigModal();
  if (!refs) return;
  const runtimePayload = configPayload(fuzzer?.versions);
  const sourcePayload = metadataPayload(fuzzer);
  refs.title.textContent = `${fuzzer?.fuzzer || 'Fuzzer'} details`;
  refs.runtimeTab.disabled = !runtimePayload;
  refs.metadataTab.disabled = !sourcePayload;
  refs.runtimeTab.onclick = () => setConfigModalTab(refs, 'runtime', runtimePayload, sourcePayload);
  refs.metadataTab.onclick = () => setConfigModalTab(refs, 'metadata', runtimePayload, sourcePayload);
  setConfigModalTab(refs, runtimePayload ? 'runtime' : 'metadata', runtimePayload, sourcePayload);
  refs.modal.classList.remove('hidden');
}
function createConfigLink(fuzzer) {
  const payload = configPayload(fuzzer.versions);
  if (!payload) return document.createTextNode('—');
  const link = el('button', 'link-btn', 'view');
  link.type = 'button';
  link.addEventListener('click', () => openConfigModal(fuzzer));
  return link;
}
function createFuzzerNameButton(fuzzer) {
  const runtimePayload = configPayload(fuzzer.versions);
  const sourcePayload = metadataPayload(fuzzer);
  if (!runtimePayload && !sourcePayload) return el('div', null, fuzzer.fuzzer);
  const button = el('button', 'link-btn fuzzer-name-btn', fuzzer.fuzzer);
  button.type = 'button';
  button.addEventListener('click', () => openConfigModal(fuzzer));
  return button;
}
function applySearch() {
  const query = String(byId('searchBox')?.value || '').trim().toLowerCase();
  FM_APP.sections.forEach((section) => {
    if (!query) {
      section.el.style.display = '';
      return;
    }
    const matches =
      String(section.target.key || '').toLowerCase().includes(query) ||
      (section.target.fuzzers || []).some((fuzzer) => String(fuzzer.fuzzer || '').toLowerCase().includes(query));
    section.el.style.display = matches ? '' : 'none';
  });
}

// Theme persistence is a convenience: blocked storage must not stop the report from rendering.
function preferredTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_STORAGE_KEY);
  } catch {}
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function syncThemeToggle() {
  const button = byId('themeToggle');
  if (!button) return;
  button.textContent = FM_APP.state.theme === 'light' ? 'Dark mode' : 'Light mode';
}
function applyTheme(theme) {
  FM_APP.state.theme = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', FM_APP.state.theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, FM_APP.state.theme);
  } catch {}
  syncThemeToggle();
  FM_APP.redrawCharts();
}

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
{ aLink, byId, debounce, el, fetchJSON, fromTemplate, part, sanitizeId };
{ fmt, fmtInt, fmtPct, formatDuration, formatExecCount, formatGroupedNumber, formatShortNumber, maximum, minimum };
{ COVERAGE_METRICS, FM_PALETTE, MATRIX_PAYLOAD_KEYS, VALUE_OPTIONS, assignFuzzerColors, buildCoverageSeries, buildCurveSeries };
{ comparisonMatrix, comparisonMetric, configPayload, dedupeBugCount, distributionValues, finalMetricValue, fuzzerColor, hashString };
{ metricCovKey, metricLabel, metricTotalKey, pctValue, per10kExec };
{ FM_APP, THEME_STORAGE_KEY };
{ cleanFloats, erf, mannWhitneyUPValue, median, quantile, rankdataDesc };
{ applySearch, applyTheme, createConfigLink, createFuzzerNameButton, ensureConfigModal };
{ openConfigModal, preferredTheme, renderAggregateCell, setTooltip };

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Declarative chart, table, matrix, and export rendering utilities.
 */


const FONT = '12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
const NUMERIC_KINDS = new Set(['int', 'float', 'pct', 'short', 'text-num']);
const EXPORT_FORMATS = [['png', 'Png'], ['pdf', 'Pdf'], ['latex', 'Latex']];
const EXPORT_BACKGROUND = '#ffffff';
const EXPORT_BORDER = 'rgba(148,163,184,.45)';
const EXPORT_HEADER_BG = 'rgba(241,245,249,.95)';
const EXPORT_TEXT = '#17212f';
const EXPORT_MUTED_TEXT = 'rgba(23,33,47,.68)';
const MIN_DISTRIBUTION_VIOLIN_VALUES = 20;
const CHART_PAD = {
  bar: [14, 16, 76, 56],
  distribution: [14, 16, 32, 56],
  line: [14, 14, 32, 56],
  stackedArea: [14, 14, 32, 56],
  stackedBar: [14, 16, 76, 56],
};

function cssColor(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function theme() {
  return {
    axis: cssColor('--chart-axis', 'rgba(255,255,255,.18)'),
    bg: cssColor('--canvas-bg', 'rgba(0,0,0,.12)'),
    empty: cssColor('--muted', 'rgba(255,255,255,.64)'),
    grid: cssColor('--chart-grid', 'rgba(255,255,255,.12)'),
    text: cssColor('--chart-text', 'rgba(255,255,255,.72)'),
  };
}

function withAlpha(color, alpha) {
  const value = Number(alpha).toFixed(3);
  if (String(color).startsWith('rgba(')) return String(color).replace(/rgba\(([^)]+),\s*[^,]+\)$/, `rgba($1, ${value})`);
  if (String(color).startsWith('rgb(')) return String(color).replace('rgb(', 'rgba(').replace(')', `, ${value})`);
  return color;
}

function number(value, fallback = 0) {
  return isFiniteNumber(value) ? Number(value) : fallback;
}

function labelFor(entry, index) {
  return String(entry?.label || entry?.id || entry?.fuzzer || entry?.name || `series ${index + 1}`);
}

function colorFor(entry, index) {
  return entry?.color || entry?.color_hint || fuzzerColor(labelFor(entry, index));
}

function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.font = FONT;
  return { ctx, width, height };
}

function drawNoData(ctx, width, height, message = 'No data') {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = theme().empty;
  ctx.font = FONT;
  ctx.fillText(message, 12, 22);
}

function formatElapsed(seconds) {
  const minutes = Math.round(Math.max(0, number(seconds)) / 60);
  if (minutes < 60) return `${minutes}m`;
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  if (!days) return rest ? `${hours}h ${rest}m` : `${hours}h`;
  return [`${days}d`, hours || !rest ? `${hours}h` : '', rest ? `${rest}m` : ''].filter(Boolean).join(' ');
}

function formatDateTime(value) {
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatExact(value, suffix = '') {
  if (!isFiniteNumber(value)) return '-';
  const n = Number(value);
  const abs = Math.abs(n);
  const maximumFractionDigits = abs >= 1000 ? 0 : (abs >= 100 ? 1 : (abs >= 10 ? 2 : 3));
  return `${formatGroupedNumber(n, { maximumFractionDigits })}${suffix}`;
}

function formatAxis(value, options = {}) {
  if (options.yClampPct || options.mode === 'pct') return `${Math.round(number(value))}%`;
  return formatShortNumber(value);
}

function formatX(value, options = {}) {
  if (options.xMode === 'time') return Math.abs(number(value)) >= 1e9 ? formatDateTime(value) : formatElapsed(value);
  return String(Math.round(number(value)));
}

function timeTickStep(span) {
  const target = Math.max(60, span / 5);
  return [60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800]
    .find((step) => step >= target) || 604800;
}

function xTicks(min, max, options = {}) {
  const span = max - min || 1;
  if (options.xMode !== 'time') return Array.from({ length: 6 }, (_entry, index) => min + span * (index / 5));
  const step = timeTickStep(span);
  const ticks = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 0.5; value += step) ticks.push(value);
  return ticks.length ? ticks : [min, max];
}

function normalizeSeries(series = []) {
  return series.map((entry, index) => ({
    baselineY: isFiniteNumber(entry.baselineY) ? Number(entry.baselineY) : null,
    color: colorFor(entry, index),
    label: labelFor(entry, index),
    points: (entry.points || [])
      .filter((point) => isFiniteNumber(point.x) && isFiniteNumber(point.y))
      .map((point) => ({
        hi: isFiniteNumber(point.hi) ? Number(point.hi) : null,
        lo: isFiniteNumber(point.lo) ? Number(point.lo) : null,
        x: Number(point.x),
        y: Number(point.y),
      })),
  })).filter((entry) => entry.points.length);
}

function normalizeRows(rows = []) {
  return rows.map((row, index) => ({
    color: colorFor(row, index),
    label: labelFor(row, index),
    value: Number(row.value),
  })).filter((row) => isFiniteNumber(row.value));
}

function normalizeGroups(groups = []) {
  return groups.map((group, groupIndex) => ({
    label: labelFor(group, groupIndex),
    segments: (group.segments || []).map((segment, segmentIndex) => ({
      color: colorFor(segment, segmentIndex),
      label: labelFor(segment, segmentIndex),
      value: number(segment.value),
    })),
  })).filter((group) => group.segments.length);
}

function normalizeDistributions(rows = []) {
  return rows.map((row, index) => ({
    color: colorFor(row, index),
    label: labelFor(row, index),
    values: cleanFloats(row.values).sort((left, right) => left - right),
  })).filter((row) => row.values.length);
}
function distributionDensitySegments(values = [], yMin = 0, yMax = 1, bins = 18) {
  const cleanValues = cleanFloats(values);
  const binCount = Math.max(1, Math.floor(number(bins, 18)));
  const min = number(yMin, 0);
  const span = number(yMax, min + 1) - min || 1;
  const histogram = new Array(binCount).fill(0);
  cleanValues.forEach((value) => {
    const ratio = Math.max(0, Math.min(0.999999, (value - min) / span));
    histogram[Math.floor(ratio * binCount)] += 1;
  });
  const peak = Math.max(...histogram, 1);
  const segments = [];
  let segment = [];
  histogram.forEach((count, bin) => {
    if (!count) {
      if (segment.length) segments.push(segment);
      segment = [];
      return;
    }
    const low = min + (bin / binCount) * span;
    const high = min + ((bin + 1) / binCount) * span;
    segment.push({
      density: count / peak,
      high,
      low,
      value: (low + high) / 2,
    });
  });
  if (segment.length) segments.push(segment);
  return segments;
}
function shouldDrawDistributionViolin(values = []) {
  return cleanFloats(values).length >= MIN_DISTRIBUTION_VIOLIN_VALUES;
}

function normalizeSpec(spec = {}) {
  const kind = spec.kind || 'line';
  const options = spec.options || {};
  if (kind === 'bar') return { ...spec, kind, options, rows: normalizeRows(spec.rows) };
  if (kind === 'stackedBar') return { ...spec, kind, options, groups: normalizeGroups(spec.groups) };
  if (kind === 'distribution') return { ...spec, kind, options, rows: normalizeDistributions(spec.rows) };
  return { ...spec, kind, options, series: normalizeSeries(spec.series) };
}

function seriesBounds(spec) {
  const values = spec.series.flatMap((entry) => [
    ...entry.points.flatMap((point) => cleanFloats([point.y, point.lo, point.hi])),
    ...cleanFloats([entry.baselineY]),
  ]);
  const xs = spec.series.flatMap((entry) => entry.points.map((point) => point.x));
  return {
    xMax: Math.max(...xs),
    xMin: Math.min(...xs),
    yMax: Math.max(...values),
    yMin: Math.min(...values),
  };
}

function chartBounds(spec) {
  if (spec.kind === 'bar') {
    const max = Math.max(...spec.rows.map((row) => row.value), 1);
    return { xMax: spec.rows.length, xMin: 0, yMax: number(spec.options.yMax, max * 1.08), yMin: 0 };
  }
  if (spec.kind === 'stackedBar') {
    const max = Math.max(...spec.groups.map((group) => group.segments.reduce((sum, segment) => sum + segment.value, 0)), 1);
    return { xMax: spec.groups.length, xMin: 0, yMax: number(spec.options.yMax, max * 1.08), yMin: 0 };
  }
  if (spec.kind === 'distribution') {
    const values = spec.rows.flatMap((row) => row.values);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = max > min ? (max - min) * 0.1 : (spec.options.mode === 'pct' ? 0.5 : 1);
    return {
      xMax: spec.rows.length,
      xMin: 0,
      yMax: spec.options.mode === 'pct' ? Math.min(100, max + pad) : max + pad,
      yMin: spec.options.mode === 'pct' ? Math.max(0, min - pad) : min - pad,
    };
  }
  if (spec.kind === 'stackedArea') {
    const xs = Array.from(new Set(spec.series.flatMap((entry) => entry.points.map((point) => point.x)))).sort((a, b) => a - b);
    const totals = xs.map((x) => spec.series.reduce((sum, entry) => sum + number(entry.points.find((point) => point.x === x)?.y), 0));
    return { xMax: xs.at(-1), xMin: xs[0], xValues: xs, yMax: number(spec.options.yMax, Math.max(0, ...totals) * 1.08), yMin: 0 };
  }
  const bounds = seriesBounds(spec);
  const pad = (bounds.yMax - bounds.yMin) * 0.08;
  let yMin = Math.max(0, bounds.yMin - pad);
  let yMax = bounds.yMax + pad;
  if (spec.options.yClampPct) {
    yMin = Math.max(0, yMin);
    yMax = Math.min(100, yMax);
  }
  if (!isFiniteNumber(yMin) || !isFiniteNumber(yMax) || yMin === yMax) {
    yMin = spec.options.yClampPct ? Math.max(0, number(bounds.yMin, 50) - 1) : 0;
    yMax = spec.options.yClampPct ? Math.min(100, number(bounds.yMax, 50) + 1) : 1;
  }
  return { ...bounds, yMax, yMin };
}

function hasRenderableData(spec) {
  if (spec.kind === 'bar') return spec.rows.length > 0;
  if (spec.kind === 'stackedBar') return spec.groups.some((group) => group.segments.some((segment) => segment.value > 0));
  if (spec.kind === 'distribution') return spec.rows.length > 0;
  return spec.series.length > 0;
}

function makeFrame(canvas, spec) {
  const prepared = prepareCanvas(canvas);
  const [top, right, bottom, left] = CHART_PAD[spec.kind] || CHART_PAD.line;
  const bounds = chartBounds(spec);
  const plotWidth = prepared.width - left - right;
  const plotHeight = prepared.height - top - bottom;
  const xSpan = bounds.xMax - bounds.xMin || 1;
  const ySpan = bounds.yMax - bounds.yMin || 1;
  return {
    ...prepared,
    ...bounds,
    bottom,
    canvas,
    left,
    plotHeight,
    plotWidth,
    right,
    spec,
    top,
    x(value) { return left + ((value - bounds.xMin) / xSpan) * plotWidth; },
    y(value) { return top + (1 - ((value - bounds.yMin) / ySpan)) * plotHeight; },
  };
}

function drawFrame(frame) {
  const style = theme();
  const { ctx, height, left, plotHeight, plotWidth, spec, top } = frame;
  ctx.clearRect(0, 0, frame.width, height);
  ctx.font = FONT;
  ctx.lineWidth = 1;
  for (let step = 0; step <= 5; step += 1) {
    const value = frame.yMin + (frame.yMax - frame.yMin) * (step / 5);
    const y = frame.y(value);
    ctx.strokeStyle = style.grid;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotWidth, y);
    ctx.stroke();
    ctx.fillStyle = style.text;
    ctx.fillText(formatAxis(value, spec.options), 8, y + 4);
  }
  ctx.strokeStyle = style.axis;
  ctx.beginPath();
  ctx.moveTo(left, top);
  ctx.lineTo(left, top + plotHeight);
  ctx.lineTo(left + plotWidth, top + plotHeight);
  ctx.stroke();
  if (spec.kind === 'bar' || spec.kind === 'stackedBar' || spec.kind === 'distribution') return;
  xTicks(frame.xMin, frame.xMax, spec.options).forEach((value) => {
    const x = frame.x(value);
    ctx.strokeStyle = style.grid;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = style.text;
    ctx.fillText(formatX(value, spec.options), x - 10, top + plotHeight + 18);
  });
}

function drawRotatedLabel(ctx, text, x, y) {
  ctx.save();
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.translate(x, y);
  ctx.rotate(-Math.PI / 4);
  ctx.fillText(String(text), 0, 0);
  ctx.restore();
}

function wrapLabelLines(ctx, text, maxWidth) {
  const tokens = String(text).split(/([\s/_-]+)/).filter(Boolean);
  if (!tokens.length) return [String(text)];
  const lines = [];
  let current = '';
  tokens.forEach((token) => {
    const candidate = current ? `${current}${token}` : token.trimStart();
    if (current && ctx.measureText(candidate).width > maxWidth) {
      lines.push(current.trim());
      current = token.trimStart();
    } else {
      current = candidate;
    }
  });
  if (current.trim()) lines.push(current.trim());
  return lines.length ? lines : [String(text)];
}

function drawWrappedLabel(ctx, text, centerX, topY, maxWidth, maxLines = 3, lineHeight = 14) {
  const lines = wrapLabelLines(ctx, text, maxWidth).slice(0, maxLines);
  ctx.save();
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  lines.forEach((line, index) => {
    ctx.fillText(line, centerX, topY + index * lineHeight, maxWidth);
  });
  ctx.restore();
}

function drawLine(frame) {
  const { ctx, spec } = frame;
  spec.series.forEach((entry) => {
    const band = entry.points.filter((point) => isFiniteNumber(point.lo) && isFiniteNumber(point.hi));
    if (band.length > 1) {
      ctx.fillStyle = withAlpha(entry.color, 0.16);
      ctx.beginPath();
      band.forEach((point, index) => {
        const x = frame.x(point.x);
        const y = frame.y(point.hi);
        if (!index) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      for (let index = band.length - 1; index >= 0; index -= 1) ctx.lineTo(frame.x(band[index].x), frame.y(band[index].lo));
      ctx.closePath();
      ctx.fill();
    }
    ctx.strokeStyle = entry.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    entry.points.forEach((point, index) => {
      const x = frame.x(point.x);
      const y = frame.y(point.y);
      if (!index) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    if (isFiniteNumber(entry.baselineY)) {
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = withAlpha(entry.color, 0.85);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(frame.left, frame.y(entry.baselineY));
      ctx.lineTo(frame.left + frame.plotWidth, frame.y(entry.baselineY));
      ctx.stroke();
      ctx.restore();
    }
  });
}

function drawStackedArea(frame) {
  const { ctx, spec, xValues } = frame;
  const cumulative = new Array(xValues.length).fill(0);
  spec.series.forEach((entry) => {
    const pointMap = new Map(entry.points.map((point) => [point.x, point.y]));
    const upper = xValues.map((x, index) => cumulative[index] + number(pointMap.get(x)));
    ctx.fillStyle = withAlpha(entry.color, 0.72);
    ctx.beginPath();
    xValues.forEach((x, index) => {
      const px = frame.x(x);
      const py = frame.y(upper[index]);
      if (!index) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    for (let index = xValues.length - 1; index >= 0; index -= 1) ctx.lineTo(frame.x(xValues[index]), frame.y(cumulative[index]));
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = withAlpha(entry.color, 0.95);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    xValues.forEach((x, index) => {
      const px = frame.x(x);
      const py = frame.y(upper[index]);
      if (!index) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
    upper.forEach((value, index) => {
      cumulative[index] = value;
    });
  });
}

function drawBars(frame) {
  const rows = frame.spec.rows;
  const slot = frame.plotWidth / Math.max(1, rows.length);
  const barWidth = Math.max(8, Math.min(48, slot * 0.64));
  frame.ctx.fillStyle = theme().text;
  rows.forEach((row, index) => {
    const x = frame.left + slot * (index + 0.5) - barWidth / 2;
    const y = frame.y(row.value);
    frame.ctx.fillStyle = row.color;
    frame.ctx.fillRect(x, y, barWidth, frame.top + frame.plotHeight - y);
    frame.ctx.fillStyle = theme().text;
    drawRotatedLabel(frame.ctx, row.label, x + barWidth / 2 + 4, frame.height - frame.bottom + 44);
  });
}

function drawStackedBars(frame) {
  const groups = frame.spec.groups;
  const slot = frame.plotWidth / Math.max(1, groups.length);
  const barWidth = Math.max(10, Math.min(56, slot * 0.7));
  groups.forEach((group, groupIndex) => {
    const x = frame.left + slot * (groupIndex + 0.5) - barWidth / 2;
    let accumulated = 0;
    group.segments.forEach((segment) => {
      const yTop = frame.y(accumulated + segment.value);
      const yBottom = frame.y(accumulated);
      frame.ctx.fillStyle = segment.color;
      frame.ctx.fillRect(x, yTop, barWidth, Math.max(1, yBottom - yTop));
      accumulated += segment.value;
    });
    frame.ctx.fillStyle = theme().text;
    drawRotatedLabel(frame.ctx, group.label, x + barWidth / 2 + 4, frame.height - frame.bottom + 44);
  });
}

function drawDistribution(frame) {
  const rows = frame.spec.rows;
  const slot = frame.plotWidth / Math.max(1, rows.length);
  const hitboxes = [];
  frame.ctx.fillStyle = theme().text;
  rows.forEach((row, index) => {
    const centerX = frame.left + slot * (index + 0.5);
    const min = row.values[0];
    const max = row.values.at(-1);
    const q1 = quantile(row.values, 0.25);
    const median = quantile(row.values, 0.5);
    const q3 = quantile(row.values, 0.75);
    const bins = Math.max(18, Math.min(42, row.values.length * 2));
    const maxHalfWidth = Math.max(16, Math.min(slot * 0.33, 40));
    if (shouldDrawDistributionViolin(row.values)) {
      frame.ctx.fillStyle = withAlpha(row.color, 0.24);
      frame.ctx.strokeStyle = withAlpha(row.color, 0.62);
      frame.ctx.lineWidth = 1.2;
      distributionDensitySegments(row.values, frame.yMin, frame.yMax, bins).forEach((segment) => {
        const left = [];
        const right = [];
        segment.forEach((bin) => {
          const half = bin.density * maxHalfWidth;
          left.push([centerX - half, frame.y(bin.low)], [centerX - half, frame.y(bin.high)]);
          right.push([centerX + half, frame.y(bin.low)], [centerX + half, frame.y(bin.high)]);
        });
        frame.ctx.beginPath();
        left.forEach(([x, y], pointIndex) => {
          if (!pointIndex) frame.ctx.moveTo(x, y);
          else frame.ctx.lineTo(x, y);
        });
        right.reverse().forEach(([x, y]) => frame.ctx.lineTo(x, y));
        frame.ctx.closePath();
        frame.ctx.fill();
        frame.ctx.stroke();
      });
    }
    frame.ctx.fillStyle = withAlpha(row.color, 0.72);
    const lanes = Math.max(3, Math.ceil(Math.sqrt(row.values.length)));
    row.values.forEach((value, valueIndex) => {
      const lane = valueIndex % lanes;
      const offset = lanes <= 1 ? 0 : ((lane / (lanes - 1)) - 0.5) * maxHalfWidth * 1.1;
      frame.ctx.beginPath();
      frame.ctx.arc(centerX + offset, frame.y(value), 4, 0, Math.PI * 2);
      frame.ctx.fill();
    });
    frame.ctx.strokeStyle = row.color;
    frame.ctx.beginPath();
    frame.ctx.moveTo(centerX, frame.y(min));
    frame.ctx.lineTo(centerX, frame.y(max));
    frame.ctx.moveTo(centerX - 8, frame.y(min));
    frame.ctx.lineTo(centerX + 8, frame.y(min));
    frame.ctx.moveTo(centerX - 8, frame.y(max));
    frame.ctx.lineTo(centerX + 8, frame.y(max));
    frame.ctx.stroke();
    frame.ctx.fillStyle = withAlpha(row.color, 0.28);
    frame.ctx.beginPath();
    frame.ctx.rect(centerX - 9, frame.y(q3), 18, Math.max(1, frame.y(q1) - frame.y(q3)));
    frame.ctx.fill();
    frame.ctx.stroke();
    frame.ctx.beginPath();
    frame.ctx.moveTo(centerX - 9, frame.y(median));
    frame.ctx.lineTo(centerX + 9, frame.y(median));
    frame.ctx.stroke();
    frame.ctx.fillStyle = theme().text;
    drawWrappedLabel(frame.ctx, row.label, centerX, frame.height - frame.bottom + 20, slot * 0.9, 3);
    hitboxes.push({ count: row.values.length, label: row.label, max, median, min, q1, q3, x0: centerX - slot * 0.45, x1: centerX + slot * 0.45, y0: frame.top, y1: frame.height - frame.bottom });
  });
  frame.canvas._distributionPayload = { hitboxes, mode: frame.spec.options.mode };
  frame.canvas.style.cursor = hitboxes.length ? 'pointer' : 'default';
}

const MARK_RENDERERS = {
  bar: drawBars,
  distribution: drawDistribution,
  line: drawLine,
  stackedArea: drawStackedArea,
  stackedBar: drawStackedBars,
};

function tooltip(canvas) {
  if (canvas._chartTooltip) return canvas._chartTooltip;
  const tip = el('div', 'chart-tooltip');
  tip.hidden = true;
  canvas.parentElement.appendChild(tip);
  canvas._chartTooltip = tip;
  return tip;
}

function hideTooltip(canvas) {
  if (canvas._chartTooltip) canvas._chartTooltip.hidden = true;
}

function installLineTooltip(canvas) {
  if (canvas._lineTooltipInstalled || !canvas.parentElement) return;
  canvas.addEventListener('mouseleave', () => hideTooltip(canvas));
  canvas.addEventListener('mousemove', (event) => {
    const payload = canvas._chartPayload;
    if (!payload || payload.kind !== 'line') return hideTooltip(canvas);
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (x < payload.left || x > payload.left + payload.plotWidth || y < payload.top || y > payload.top + payload.plotHeight) return hideTooltip(canvas);
    const targetX = payload.xMin + ((x - payload.left) / payload.plotWidth) * ((payload.xMax - payload.xMin) || 1);
    let anchor = null;
    payload.series.flatMap((entry) => entry.points).forEach((point) => {
      if (!anchor || Math.abs(point.x - targetX) < Math.abs(anchor.x - targetX)) anchor = point;
    });
    if (!anchor) return hideTooltip(canvas);
    const rows = payload.series.map((entry) => {
      const latest = entry.points.reduce((best, point) => (
        point.x <= anchor.x && (!best || point.x > best.x) ? point : best
      ), null);
      return latest ? { color: entry.color, label: entry.label, value: latest.y } : null;
    }).filter(Boolean).sort((left, right) => right.value - left.value);
    const tip = tooltip(canvas);
    tip.textContent = '';
    tip.appendChild(el('div', 'chart-tooltip-title', payload.options.xMode === 'time' ? formatX(anchor.x, payload.options) : String(Math.round(anchor.x))));
    const list = el('div', 'chart-tooltip-list');
    rows.forEach((row) => {
      const item = el('div', 'chart-tooltip-row');
      const label = el('div', 'chart-tooltip-label');
      const swatch = el('span', 'legend-swatch');
      swatch.style.background = row.color;
      label.appendChild(swatch);
      label.appendChild(el('span', null, row.label));
      item.appendChild(label);
      item.appendChild(el('div', 'chart-tooltip-value', formatExact(row.value, payload.options.yClampPct ? '%' : '')));
      list.appendChild(item);
    });
    tip.appendChild(list);
    tip.style.left = `${Math.min(Math.max(10, x + 12), Math.max(10, rect.width - 250))}px`;
    tip.style.top = `${Math.min(Math.max(10, y + 12), Math.max(10, rect.height - 220))}px`;
    tip.hidden = false;
  });
  canvas._lineTooltipInstalled = true;
}

// A single document listener closes open export menus and tooltips on outside clicks. Listeners bound
// per widget would keep every replaced report section, canvases included, alive after each re-render.
let outsideClickCloserInstalled = false;

function installOutsideClickCloser() {
  if (outsideClickCloserInstalled) return;
  outsideClickCloserInstalled = true;
  document.addEventListener('click', (event) => {
    document.querySelectorAll('.export-menu-host.open').forEach((host) => {
      if (host.contains(event.target)) return;
      host.classList.remove('open');
      host.querySelectorAll(':scope > .export-menu').forEach((menu) => { menu.hidden = true; });
      host.querySelectorAll(':scope > [aria-haspopup="menu"]').forEach((trigger) => trigger.setAttribute('aria-expanded', 'false'));
    });
    document.querySelectorAll('.chart-tooltip:not([hidden])').forEach((tip) => {
      if (!tip.parentElement.contains(event.target)) tip.hidden = true;
    });
  });
}

function installDistributionTooltip(canvas) {
  if (canvas._distributionTooltipInstalled || !canvas.parentElement) return;
  installOutsideClickCloser();
  canvas.addEventListener('click', (event) => {
    const payload = canvas._distributionPayload;
    if (!payload?.hitboxes?.length) return hideTooltip(canvas);
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = payload.hitboxes.find((entry) => x >= entry.x0 && x <= entry.x1 && y >= entry.y0 && y <= entry.y1)
      || payload.hitboxes.reduce((best, entry) => (Math.abs((entry.x0 + entry.x1) / 2 - x) < Math.abs((best.x0 + best.x1) / 2 - x) ? entry : best));
    const format = payload.mode === 'pct' ? ((value) => fmtPct(value, 2)) : formatShortNumber;
    const tip = tooltip(canvas);
    tip.textContent = '';
    tip.appendChild(el('div', 'chart-tooltip-title', hit.label));
    const table = el('table');
    [['Min', hit.min], ['Q1', hit.q1], ['Median', hit.median], ['Q3', hit.q3], ['Max', hit.max], ['Samples', hit.count]].forEach(([name, value]) => {
      const tr = el('tr');
      tr.appendChild(el('td', null, name));
      tr.appendChild(el('td', null, name === 'Samples' ? fmtInt(value) : format(value)));
      table.appendChild(tr);
    });
    tip.appendChild(table);
    tip.style.left = `${Math.min(Math.max(10, x + 12), Math.max(10, rect.width - 230))}px`;
    tip.style.top = `${Math.min(Math.max(10, y + 12), Math.max(10, rect.height - 160))}px`;
    tip.hidden = false;
  });
  canvas._distributionTooltipInstalled = true;
}

function exportPayload(frame) {
  const { spec } = frame;
  return {
    groups: spec.groups,
    kind: spec.kind,
    options: spec.options,
    rows: spec.rows,
    series: spec.series,
  };
}

function renderCanvasChart(canvas, rawSpec = {}) {
  if (!canvas) return null;
  const spec = normalizeSpec(rawSpec);
  const prepared = prepareCanvas(canvas);
  if (!hasRenderableData(spec)) {
    canvas._chartPayload = null;
    drawNoData(prepared.ctx, prepared.width, prepared.height, rawSpec.emptyMessage || 'No data');
    return null;
  }
  const frame = makeFrame(canvas, spec);
  if (frame.plotWidth <= 0 || frame.plotHeight <= 0) {
    canvas._chartPayload = null;
    drawNoData(frame.ctx, frame.width, frame.height, rawSpec.emptyMessage || 'No data');
    return null;
  }
  drawFrame(frame);
  MARK_RENDERERS[spec.kind]?.(frame);
  const payload = JSON.parse(JSON.stringify(exportPayload(frame)));
  canvas._chartPayload = { ...payload, left: frame.left, plotHeight: frame.plotHeight, plotWidth: frame.plotWidth, top: frame.top, xMax: frame.xMax, xMin: frame.xMin };
  if (spec.kind === 'line') installLineTooltip(canvas);
  if (spec.kind === 'distribution') installDistributionTooltip(canvas);
  return payload;
}

function renderLegend(host, series = []) {
  if (!host) return;
  host.textContent = '';
  series.forEach((entry, index) => {
    const item = el('div', 'legend-item');
    const swatch = el('span', 'legend-swatch');
    swatch.style.background = colorFor(entry, index);
    item.appendChild(swatch);
    item.appendChild(el('span', 'legend-text', labelFor(entry, index)));
    host.appendChild(item);
  });
}

/**
 * Create a select element bound to a change callback.
 */
function createSelect(options, value, onChange, className = 'select') {
  const select = document.createElement('select');
  select.className = className;
  options.forEach(([optionValue, label]) => {
    const option = document.createElement('option');
    option.value = optionValue;
    option.textContent = label;
    option.selected = optionValue === value;
    select.appendChild(option);
  });
  select.addEventListener('change', () => onChange(select.value));
  return select;
}

function downloadBlob(blob, fileName) {
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function canvasBlob(canvas, type = 'image/png', quality) {
  return new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), type, quality));
}

function safeComputedStyle(node) {
  return node instanceof Element ? getComputedStyle(node) : null;
}

function opaqueColor(color, fallback) {
  const value = String(color || '').trim();
  if (!value || value === 'transparent' || value === 'rgba(0, 0, 0, 0)') return fallback;
  return value;
}

function drawRoundedRect(ctx, x, y, width, height, radius = 0) {
  if (radius <= 0) {
    ctx.fillRect(x, y, width, height);
    return;
  }
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  ctx.fill();
}

function wrapCanvasText(ctx, text, maxWidth) {
  const value = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (!value) return [''];
  const words = value.split(' ');
  const lines = [];
  let current = '';
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (ctx.measureText(candidate).width <= maxWidth || !current) {
      current = candidate;
      return;
    }
    lines.push(current);
    current = word;
    while (ctx.measureText(current).width > maxWidth && current.length > 1) {
      let cut = current.length - 1;
      while (cut > 1 && ctx.measureText(`${current.slice(0, cut)}-`).width > maxWidth) cut -= 1;
      lines.push(`${current.slice(0, cut)}-`);
      current = current.slice(cut);
    }
  });
  if (current) lines.push(current);
  return lines;
}

function escapeLatex(value) {
  return String(value ?? '')
    .replace(/\\/g, '\\textbackslash{}')
    .replace(/([{}#$%&_])/g, '\\$1')
    .replace(/~/g, '\\textasciitilde{}')
    .replace(/\^/g, '\\textasciicircum{}');
}

function buildLatex(payload) {
  if (!payload?.kind) return null;
  const lines = [
    '\\documentclass[tikz]{standalone}',
    '\\usepackage{pgfplots}',
    ...(payload.kind === 'distribution' ? ['\\usepgfplotslibrary{statistics}'] : []),
    '\\pgfplotsset{compat=1.18}',
    '\\begin{document}',
    '\\begin{tikzpicture}',
    '  \\begin{axis}[width=\\linewidth,height=0.58\\linewidth,grid=both,legend style={draw=none,fill=none,font=\\small}]',
  ];
  if (payload.kind === 'line' || payload.kind === 'stackedArea') {
    (payload.series || []).forEach((entry) => {
      const coords = (entry.points || []).map((point) => `(${Number(point.x)},${Number(point.y)})`).join(' ');
      lines.push(`    \\addplot+[mark=none] coordinates { ${coords} };`);
      lines.push(`    \\addlegendentry{${escapeLatex(entry.label)}}`);
    });
  } else if (payload.kind === 'bar') {
    (payload.rows || []).forEach((row, index) => {
      lines.push(`    \\addplot+[ybar] coordinates { (${index + 1},${Number(row.value)}) };`);
      lines.push(`    \\addlegendentry{${escapeLatex(row.label)}}`);
    });
  } else if (payload.kind === 'stackedBar') {
    const segmentLabels = Array.from(new Set((payload.groups || []).flatMap((group) => group.segments.map((segment) => segment.label))));
    segmentLabels.forEach((label) => {
      const coords = payload.groups.map((group, index) => {
        const segment = group.segments.find((entry) => entry.label === label);
        return `(${index + 1},${Number(segment?.value || 0)})`;
      }).join(' ');
      lines.push(`    \\addplot+[ybar stacked] coordinates { ${coords} };`);
      lines.push(`    \\addlegendentry{${escapeLatex(label)}}`);
    });
  } else if (payload.kind === 'distribution') {
    (payload.rows || []).forEach((row, index) => {
      const sorted = row.values || [];
      lines.push(`    \\addplot+[boxplot prepared={lower whisker=${sorted[0]}, lower quartile=${quantile(sorted, 0.25)}, median=${quantile(sorted, 0.5)}, upper quartile=${quantile(sorted, 0.75)}, upper whisker=${sorted.at(-1)}}] coordinates {};`);
      lines.push(`    \\addlegendentry{${escapeLatex(row.label || `series ${index + 1}`)}}`);
    });
  }
  lines.push('  \\end{axis}', '\\end{tikzpicture}', '\\end{document}', '');
  return lines.join('\n');
}

function tableRows(element) {
  return Array.from(element.querySelectorAll('table tr'))
    .map((row) => Array.from(row.children).map((cell) => cell.textContent.trim()))
    .filter((row) => row.length);
}

function buildTableLatex(element) {
  const rows = tableRows(element);
  if (!rows.length) return null;
  const columnCount = Math.max(...rows.map((row) => row.length));
  return [
    '\\documentclass{standalone}',
    '\\begin{document}',
    `\\begin{tabular}{|${'l|'.repeat(columnCount)}}`,
    '\\hline',
    ...rows.flatMap((row) => [`${row.concat(new Array(columnCount - row.length).fill('')).map(escapeLatex).join(' & ')} \\\\`, '\\hline']),
    '\\end{tabular}',
    '\\end{document}',
    '',
  ].join('\n');
}

function bytesFromDataUrl(dataUrl) {
  const binary = window.atob((dataUrl.split(',', 2)[1] || ''));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function pdfBlob(jpegBytes, imageWidth, imageHeight) {
  const scale = Math.min((imageWidth >= imageHeight ? 792 : 612) / imageWidth, (imageWidth >= imageHeight ? 612 : 792) / imageHeight, 1);
  const pageWidth = Math.max(1, Math.round(imageWidth * scale));
  const pageHeight = Math.max(1, Math.round(imageHeight * scale));
  const enc = (value) => new TextEncoder().encode(value);
  const content = `q\n${pageWidth} 0 0 ${pageHeight} 0 0 cm\n/Im0 Do\nQ\n`;
  const objects = [
    [enc('<< /Type /Catalog /Pages 2 0 R >>')],
    [enc('<< /Type /Pages /Kids [3 0 R] /Count 1 >>')],
    [enc(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`)],
    [enc(`<< /Type /XObject /Subtype /Image /Width ${imageWidth} /Height ${imageHeight} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`), jpegBytes, enc('\nendstream')],
    [enc(`<< /Length ${content.length} >>\nstream\n${content}endstream`)],
  ];
  const chunks = [enc('%PDF-1.4\n')];
  const offsets = [0];
  let offset = chunks[0].length;
  objects.forEach((body, index) => {
    offsets.push(offset);
    const prefix = enc(`${index + 1} 0 obj\n`);
    const suffix = enc('\nendobj\n');
    chunks.push(prefix, ...body, suffix);
    offset += prefix.length + body.reduce((sum, chunk) => sum + chunk.length, 0) + suffix.length;
  });
  const rows = offsets.map((value, index) => (
    index === 0 ? '0000000000 65535 f \n' : `${String(value).padStart(10, '0')} 00000 n \n`
  ));
  chunks.push(enc(`xref\n0 ${rows.length}\n${rows.join('')}trailer\n<< /Size ${rows.length} /Root 1 0 R >>\nstartxref\n${offset}\n%%EOF\n`));
  return new Blob(chunks, { type: 'application/pdf' });
}

function canvasWithBackground(canvas, background = EXPORT_BACKGROUND) {
  const composed = document.createElement('canvas');
  composed.width = canvas.width || 1;
  composed.height = canvas.height || 1;
  const ctx = composed.getContext('2d');
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, composed.width, composed.height);
  ctx.drawImage(canvas, 0, 0);
  return composed;
}

async function exportCanvas(canvas, fileName, format, handle = null) {
  if (!canvas) return false;
  const sourceCanvas = handle?.surface || canvas;
  if (format === 'latex') {
    const latex = buildLatex(handle?.payload);
    if (!latex) return false;
    downloadBlob(new Blob([latex], { type: 'application/x-tex' }), `${fileName || 'chart'}.tex`);
    return true;
  }
  if (format === 'pdf') {
    const pdfCanvas = canvasWithBackground(sourceCanvas);
    const dataUrl = pdfCanvas.toDataURL('image/jpeg', 0.96);
    downloadBlob(pdfBlob(bytesFromDataUrl(dataUrl), pdfCanvas.width || 1, pdfCanvas.height || 1), `${fileName || 'chart'}.pdf`);
    return true;
  }
  const blob = await canvasBlob(sourceCanvas, 'image/png');
  if (!blob) return false;
  downloadBlob(blob, `${fileName || 'chart'}.png`);
  return true;
}

function extractTableModel(element) {
  const tables = element?.matches?.('table') ? [element] : Array.from(element?.querySelectorAll?.('table') || []);
  const table = tables[0];
  if (!table) return null;
  const rows = Array.from(table.querySelectorAll('tr')).map((row) => Array.from(row.children).map((cell) => {
    const style = safeComputedStyle(cell);
    const isHeader = cell.tagName.toLowerCase() === 'th';
    return {
      align: style?.textAlign || (isHeader ? 'center' : 'left'),
      background: opaqueColor(style?.backgroundColor, isHeader ? EXPORT_HEADER_BG : 'transparent'),
      bold: isHeader || Number(style?.fontWeight || 400) >= 600,
      color: isHeader ? EXPORT_MUTED_TEXT : EXPORT_TEXT,
      text: cell.textContent.trim(),
    };
  })).filter((row) => row.length);
  return rows.length ? { rows, style: safeComputedStyle(table) } : null;
}

function renderElementToCanvas(element) {
  const model = extractTableModel(element);
  if (!model) return null;

  const dpr = window.devicePixelRatio || 1;
  const scratch = document.createElement('canvas');
  const measure = scratch.getContext('2d');
  const paddingX = 9;
  const paddingY = 7;
  const lineHeight = 16;
  const gap = 0;
  const border = EXPORT_BORDER;
  const tableBg = EXPORT_BACKGROUND;
  const columnCount = Math.max(...model.rows.map((row) => row.length));
  const widths = new Array(columnCount).fill(44);

  model.rows.forEach((row) => {
    row.forEach((cell, index) => {
      measure.font = `${cell.bold ? 700 : 400} 12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
      widths[index] = Math.max(widths[index], Math.ceil(measure.measureText(cell.text || '-').width) + paddingX * 2);
    });
  });

  const maxColumnWidth = 230;
  for (let index = 0; index < widths.length; index += 1) {
    widths[index] = Math.min(maxColumnWidth, Math.max(56, widths[index]));
  }

  const rowHeights = model.rows.map((row) => {
    let height = lineHeight + paddingY * 2;
    row.forEach((cell, index) => {
      measure.font = `${cell.bold ? 700 : 400} 12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
      const lines = wrapCanvasText(measure, cell.text || '-', widths[index] - paddingX * 2);
      height = Math.max(height, lines.length * lineHeight + paddingY * 2);
    });
    return height;
  });

  const outerPad = 12;
  const width = Math.ceil(widths.reduce((sum, value) => sum + value, 0) + outerPad * 2 + gap * (widths.length - 1));
  const height = Math.ceil(rowHeights.reduce((sum, value) => sum + value, 0) + outerPad * 2 + gap * (rowHeights.length - 1));
  const canvas = document.createElement('canvas');
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = tableBg;
  drawRoundedRect(ctx, 0, 0, width, height, 10);

  let y = outerPad;
  model.rows.forEach((row, rowIndex) => {
    let x = outerPad;
    const rowHeight = rowHeights[rowIndex];
    row.forEach((cell, colIndex) => {
      const cellWidth = widths[colIndex];
      const bg = opaqueColor(cell.background, rowIndex === 0 ? EXPORT_HEADER_BG : 'transparent');
      if (bg !== 'transparent') {
        ctx.fillStyle = bg;
        ctx.fillRect(x, y, cellWidth, rowHeight);
      }
      ctx.strokeStyle = border;
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 0.5, y + 0.5, cellWidth, rowHeight);

      ctx.font = `${cell.bold ? 700 : 400} 12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
      ctx.fillStyle = cell.color;
      ctx.textBaseline = 'top';
      const lines = wrapCanvasText(ctx, cell.text || '-', cellWidth - paddingX * 2);
      const textX = cell.align === 'right'
        ? x + cellWidth - paddingX
        : (cell.align === 'center' ? x + cellWidth / 2 : x + paddingX);
      ctx.textAlign = cell.align === 'right' ? 'right' : (cell.align === 'center' ? 'center' : 'left');
      lines.forEach((line, lineIndex) => {
        ctx.fillText(line, textX, y + paddingY + lineIndex * lineHeight);
      });
      x += cellWidth + gap;
    });
    y += rowHeight + gap;
  });
  return canvas;
}

async function exportElement(element, fileName, format) {
  if (format === 'latex') {
    const latex = buildTableLatex(element);
    if (latex) {
      downloadBlob(new Blob([latex], { type: 'application/x-tex' }), `${fileName || 'table'}.tex`);
      return true;
    }
  }
  const canvas = renderElementToCanvas(element);
  if (!canvas) return false;
  return exportCanvas(canvas, fileName || 'table', format);
}

function installExportMenu(triggerButton, onSelect) {
  const host = triggerButton.parentElement;
  host.classList.add('export-menu-host');
  const menu = el('div', 'export-menu');
  EXPORT_FORMATS.forEach(([value, label]) => {
    const option = el('button', 'export-menu-item', label);
    option.type = 'button';
    option.addEventListener('click', async () => {
      menu.hidden = true;
      host.classList.remove('open');
      try {
        await onSelect(value);
      } catch (error) {
        console.error('Export failed:', error);
      }
    });
    menu.appendChild(option);
  });
  menu.hidden = true;
  host.appendChild(menu);
  triggerButton.textContent = 'Export';
  triggerButton.setAttribute('aria-haspopup', 'menu');
  triggerButton.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    const open = menu.hidden;
    menu.hidden = !open;
    host.classList.toggle('open', open);
    triggerButton.setAttribute('aria-expanded', String(open));
  });
  installOutsideClickCloser();
}

/**
 * Attach an export menu to an arbitrary table-like element.
 */
function installElementExportMenu(triggerButton, element, fileName) {
  installExportMenu(triggerButton, (format) => exportElement(element, typeof fileName === 'function' ? fileName() : fileName, format));
}

/**
 * Create a standard canvas chart card.
 */
function makeCanvasCard({ title, subtitle = '', withLegend = false, exportName = 'chart' }) {
  const card = fromTemplate('tplCanvasCard');
  const titleEl = part(card, 'title');
  const subtitleEl = part(card, 'subtitle');
  const canvas = part(card, 'canvas');
  const exportHandle = { payload: null, surface: null };
  const legend = part(card, 'legend');
  titleEl.textContent = title;
  subtitleEl.textContent = subtitle;
  legend.hidden = !withLegend;
  let currentExportName = exportName;
  installExportMenu(part(card, 'download'), (format) => exportCanvas(canvas, currentExportName, format, exportHandle));
  return {
    canvas,
    card,
    exportHandle,
    legend,
    setExportName(nextName) { currentExportName = nextName; },
    setSubtitle(nextSubtitle) { subtitleEl.textContent = nextSubtitle || ''; },
    setTitle(nextTitle) { titleEl.textContent = nextTitle; },
    subtitleEl,
    titleEl,
  };
}

function updateCanvasExportSurface(canvas, legend) {
  if (!canvas || !legend || legend.hidden || !legend.childElementCount) {
    return null;
  }
  const legendItems = Array.from(legend.querySelectorAll('.legend-item'));
  if (!legendItems.length) {
    return null;
  }
  const gap = 12;
  const dpr = window.devicePixelRatio || 1;
  const paddingX = 12;
  const paddingTop = 8;
  const paddingBottom = 10;
  const rowHeight = 18;
  const ctxMeasure = document.createElement('canvas').getContext('2d');
  ctxMeasure.font = FONT;
  const rows = [];
  let currentRow = [];
  let currentWidth = 0;
  legendItems.forEach((item, index) => {
    const label = item.querySelector('.legend-text')?.textContent || '';
    const swatchColor = item.querySelector('.legend-swatch')?.style.background || theme().text;
    const itemWidth = 10 + 6 + ctxMeasure.measureText(label).width + (currentRow.length ? gap : 0);
    if (currentRow.length && currentWidth + itemWidth > (canvas.width / dpr) - paddingX * 2) {
      rows.push(currentRow);
      currentRow = [];
      currentWidth = 0;
    }
    currentRow.push({ color: swatchColor, label });
    currentWidth += 10 + 6 + ctxMeasure.measureText(label).width + (currentRow.length > 1 ? gap : 0);
    if (index === legendItems.length - 1 && currentRow.length) rows.push(currentRow);
  });
  const cssWidth = canvas.width / dpr;
  const cssHeight = canvas.height / dpr;
  const legendHeight = paddingTop + rows.length * rowHeight + paddingBottom;
  const exportCanvasEl = document.createElement('canvas');
  exportCanvasEl.width = Math.round(cssWidth * dpr);
  exportCanvasEl.height = Math.round((cssHeight + legendHeight) * dpr);
  const exportCtx = exportCanvasEl.getContext('2d');
  exportCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  exportCtx.drawImage(canvas, 0, 0, cssWidth, cssHeight);
  exportCtx.font = FONT;
  exportCtx.textBaseline = 'middle';
  rows.forEach((row, rowIndex) => {
    let x = paddingX;
    const y = cssHeight + paddingTop + rowIndex * rowHeight + rowHeight / 2;
    row.forEach((entry) => {
      exportCtx.fillStyle = entry.color;
      exportCtx.fillRect(x, y - 5, 10, 10);
      exportCtx.strokeStyle = 'rgba(255,255,255,.14)';
      exportCtx.strokeRect(x, y - 5, 10, 10);
      x += 16;
      exportCtx.fillStyle = theme().text;
      exportCtx.fillText(entry.label, x, y);
      x += ctxMeasure.measureText(entry.label).width + gap;
    });
  });
  return exportCanvasEl;
}

/**
 * Create a standard matrix or table card.
 */
function makeMatrixCard({ title, subtitle = '' }) {
  const card = fromTemplate('tplMatrixCard');
  const titleEl = part(card, 'title');
  const subtitleEl = part(card, 'subtitle');
  const body = part(card, 'body');
  titleEl.textContent = title;
  subtitleEl.textContent = subtitle;
  let currentExportName = title.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  installExportMenu(part(card, 'download'), (format) => exportElement(body, currentExportName, format));
  return {
    body,
    card,
    setExportName(nextName) { currentExportName = nextName; },
    setSubtitle(nextSubtitle) { subtitleEl.textContent = nextSubtitle || ''; },
    setTitle(nextTitle) { titleEl.textContent = nextTitle; },
  };
}

function cellContent(kind, value) {
  if (value == null) return document.createTextNode('-');
  if (kind === 'int') return document.createTextNode(fmtInt(value));
  if (kind === 'float') return document.createTextNode(fmt(value, 2));
  if (kind === 'pct') return document.createTextNode(fmtPct(value, 2));
  if (kind === 'short') return document.createTextNode(formatShortNumber(value));
  if (kind === 'code') return el('code', 'mono', String(value));
  if (kind === 'link') return typeof value === 'string' ? aLink(value, value) : aLink(String(value.label || value.href), String(value.href));
  return document.createTextNode(String(value));
}

/**
 * Render a generic data table.
 */
function renderDataTable(host, columns, rows) {
  host.textContent = '';
  if (!rows?.length) {
    host.appendChild(el('div', 'matrix-empty', 'No data.'));
    return;
  }
  const table = el('table', 'table');
  const thead = el('thead');
  const headerRow = el('tr');
  (columns || []).forEach((column) => {
    const th = el('th', NUMERIC_KINDS.has(column.kind) ? 'num' : null, column.label);
    th.title = String(column.tooltip || column.label || '');
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);
  const tbody = el('tbody');
  rows.forEach((row) => {
    const tr = el('tr');
    (columns || []).forEach((column) => {
      const td = el('td', NUMERIC_KINDS.has(column.kind) ? 'num' : null);
      td.appendChild(cellContent(column.kind, row[column.key]));
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}

/**
 * Render a chart card from a declarative chart specification.
 */
function renderChartCard(card, spec = {}) {
  if (!card || !spec) return;
  if (card.canvas) {
    card.canvas._chartCard = card;
    card.canvas._chartSpec = spec;
  }
  if (spec.title !== undefined) card.setTitle?.(spec.title);
  if (spec.subtitle !== undefined) card.setSubtitle?.(spec.subtitle);
  if (spec.exportName !== undefined) card.setExportName?.(spec.exportName);
  if (card.canvas && spec.kind && card.exportHandle) card.exportHandle.payload = renderCanvasChart(card.canvas, spec);
  else if (card.canvas && spec.kind) renderCanvasChart(card.canvas, spec);
  if (card.legend && spec.legend !== false) renderLegend(card.legend, spec.legendSeries || spec.series || []);
  if (card.canvas && card.exportHandle) card.exportHandle.surface = updateCanvasExportSurface(card.canvas, card.legend);
}
function redrawCharts() {
  document.querySelectorAll('canvas').forEach((canvas) => {
    if (canvas._chartCard && canvas._chartSpec) renderChartCard(canvas._chartCard, canvas._chartSpec);
  });
}

/**
 * Render a matrix card from matrix data.
 */
function renderMatrixCard(card, matrixData, options = {}) {
  if (!card) return;
  if (options.title !== undefined) card.setTitle?.(options.title);
  if (options.subtitle !== undefined) card.setSubtitle?.(options.subtitle);
  if (options.exportName !== undefined) card.setExportName?.(options.exportName);
  renderMatrixTable(card.body, matrixData, options);
}

function matrixStyle(value, maxValue, tint) {
  if (!isFiniteNumber(value) || value <= 0 || !isFiniteNumber(maxValue) || maxValue <= 0) return '';
  return `background:${tint.replace('ALPHA', (0.10 + 0.55 * (value / maxValue)).toFixed(3))}; font-weight:700;`;
}

function matrixText(value, options) {
  if (typeof options.formatValue === 'function') return String(options.formatValue(value));
  if (options.formatter === 'pct') return `${fmt(value, 1)}%`;
  if (options.formatter === 'float') return fmt(value, options.fractionDigits ?? 3);
  return fmtInt(value);
}

/**
 * Render a generic fuzzer-by-fuzzer matrix table.
 */
function renderMatrixTable(host, matrixData, options = {}) {
  host.textContent = '';
  if (!matrixData?.fuzzers?.length || !matrixData?.matrix?.length) {
    host.appendChild(el('div', 'matrix-empty', options.emptyMessage || 'No data.'));
    return;
  }
  if (matrixData.note) host.appendChild(el('div', 'matrix-note muted small', matrixData.note));
  const labels = matrixData.fuzzers;
  const maxValue = isFiniteNumber(matrixData.max_value) ? Number(matrixData.max_value) : Math.max(0, ...matrixData.matrix.flat().map(number));
  const table = el('table', 'table matrix');
  const thead = el('thead');
  const headerRow = el('tr');
  headerRow.appendChild(el('th', null, ''));
  labels.forEach((label) => headerRow.appendChild(el('th', 'num', label)));
  thead.appendChild(headerRow);
  table.appendChild(thead);
  const tbody = el('tbody');
  labels.forEach((rowLabel, rowIndex) => {
    const tr = el('tr');
    tr.appendChild(el('td', null, rowLabel));
    labels.forEach((colLabel, colIndex) => {
      const rawValue = (matrixData.matrix[rowIndex] || [])[colIndex];
      const unknown = !isFiniteNumber(rawValue);
      const value = unknown ? null : number(rawValue);
      const self = rowIndex === colIndex;
      const bound = (matrixData.cell_bounds?.[rowIndex] || [])[colIndex] || 'exact';
      const formatted = unknown ? '?' : matrixText(value, options);
      const text = bound === 'lower' ? `≥${formatted}`
        : bound === 'upper' ? `≤${formatted}`
        : bound === 'indeterminate' ? `~${formatted}`
        : formatted;
      const td = el('td', 'num');
      td.appendChild(el('div', null, self && options.allowSelfDash !== false ? '-' : text));
      td.style.cssText = self && options.allowSelfDash !== false
        ? 'background:#ffffff; color:#111827; font-weight:700;'
        : (!unknown && typeof options.styleForValue === 'function'
          ? options.styleForValue(value, { colIndex, colLabel, matrixData, maxValue, rowIndex, rowLabel })
          : (!unknown ? matrixStyle(value, maxValue, options.tint || 'rgba(120,180,255,ALPHA)') : ''));
      td.title = self && options.allowSelfDash !== false
        ? `${rowLabel}: same row`
        : `${rowLabel} - ${colLabel}: ${unknown ? 'unknown' : text}`;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Renders user-provided extra report sections from plugin chart specs.
 */
const ALLOWED_CHART_TYPES = [
  'bar',
  'distribution',
  'line',
  'matrix',
  'stacked_area',
  'stacked_bar',
  'table',
];

function normalizeSeries(series) {
  return (series || []).map((entry) => ({
    ...entry,
    color: entry.color_hint || fuzzerColor(entry.label || entry.id),
  }));
}

function normalizeBarRows(chart) {
  const rows = chart.rows?.length ? chart.rows : chart.series;
  return (rows || []).map((row) => ({
    label: row.label || row.id || row.fuzzer || row.name,
    value: row.value ?? row.y ?? row.values?.[0] ?? row.points?.at(-1)?.y,
    color: row.color_hint || row.color || fuzzerColor(row.label || row.id || row.fuzzer || row.name),
  }));
}

function normalizeStackedGroups(chart) {
  const series = normalizeSeries(chart.series);
  const labels = Array.from(new Set(
    series.flatMap((entry) => (entry.points || []).map((point) => String(point.x))),
  ));
  return labels.map((label) => ({
    label,
    segments: series.map((entry) => {
      const point = (entry.points || []).find((candidate) => String(candidate.x) === label);
      return { label: entry.label, value: point?.y ?? 0, color: entry.color };
    }),
  }));
}

function createExtraChartCard(section, chart) {
  if (!ALLOWED_CHART_TYPES.includes(chart.type)) {
    return null;
  }
  if (chart.type === 'matrix') {
    const card = makeMatrixCard({ title: chart.title, subtitle: chart.subtitle || '' });
    return {
      card: card.card,
      render() {
        renderMatrixTable(card.body, chart.matrix || null);
      },
    };
  }
  if (chart.type === 'table') {
    const card = makeMatrixCard({ title: chart.title, subtitle: chart.subtitle || '' });
    return {
      card: card.card,
      render() {
        renderDataTable(card.body, chart.columns || [], chart.rows || []);
      },
    };
  }

  const card = makeCanvasCard({
    title: chart.title,
    subtitle: chart.subtitle || '',
    withLegend: chart.type === 'line' || chart.type === 'stacked_area' || chart.type === 'stacked_bar',
    exportName: `${section.id}-${chart.id}`,
  });
  const series = normalizeSeries(chart.series);
  const percentAxis = chart.y_mode === 'percent';
  const xMode = chart.x_mode === 'time' ? 'time' : 'index';
  return {
    card: card.card,
    render() {
      let spec = null;
      if (chart.type === 'line') {
        spec = { kind: 'line', series, options: { xMode, yClampPct: percentAxis } };
      } else if (chart.type === 'stacked_area') {
        spec = { kind: 'stackedArea', series, options: { xMode, yMax: percentAxis ? 100 : undefined } };
      } else if (chart.type === 'bar') {
        spec = { kind: 'bar', rows: normalizeBarRows(chart), options: { yClampPct: percentAxis } };
      } else if (chart.type === 'stacked_bar') {
        spec = {
          groups: normalizeStackedGroups(chart),
          kind: 'stackedBar',
          legendSeries: series,
          options: { yClampPct: percentAxis, yMax: percentAxis ? 100 : undefined },
        };
      } else if (chart.type === 'distribution') {
        spec = {
          kind: 'distribution',
          options: { mode: percentAxis ? 'pct' : 'abs' },
          rows: series.map((entry) => ({ color: entry.color, label: entry.label, values: entry.values || [] })),
        };
      }
      renderChartCard(card, spec);
    },
  };
}
function renderExtraSections(host, extraSections) {
  (extraSections || []).forEach((section) => {
    const block = fromTemplate('tplReportBlock');
    const blockTitle = section.owner_fuzzer
      ? `${section.title} (${section.owner_fuzzer})`
      : section.title;
    part(block, 'title').textContent = blockTitle;
    part(block, 'subtitle').hidden = true;
    part(block, 'controls').hidden = true;

    const singleStackedArea = section.charts.length === 1 && section.charts[0]?.type === 'stacked_area';
    const gridClass = singleStackedArea
      ? 'block-grid-2'
      : (section.charts.length === 1 ? 'block-grid-1'
        : (section.charts.length === 2 ? 'block-grid-2' : 'block-grid-3'));
    const grid = part(block, 'body');
    grid.className = gridClass;
    const renderers = [];
    (section.charts || []).forEach((chart) => {
      const chartCard = createExtraChartCard(section, chart);
      if (!chartCard) return;
      grid.appendChild(chartCard.card);
      renderers.push(chartCard.render);
    });
    host.appendChild(block);
    requestAnimationFrame(() => {
      renderers.forEach((render) => render());
    });
  });
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Applies client-side fuzzer filtering and recomputes filtered report data.
 */



const {
  uniqueMatrix,
  relcovMatrix,
  branchMwuMatrix,
  branchA12Matrix,
  relcovScoreByFuzzer,
  uniqueBugTable,
  uniqueBugMatrix,
  relbugMatrix,
  relbugScoreByFuzzer,
} = MATRIX_PAYLOAD_KEYS;

function medianOfValues(values) {
  const sorted = cleanFloats(values).sort((left, right) => left - right);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

function emptyMetricMatrixGroup() {
  return { by_metric: {}, has_data: false, available_metrics: [] };
}

function emptyMatrix() {
  return { fuzzers: [], matrix: [], max_value: 0, has_data: false };
}

function emptyUniqueBugTable() {
  return { fuzzers: [], rows: [], has_data: false };
}
function allFuzzerNames(data) {
  if (Array.isArray(data?.filters?.fuzzers) && data.filters.fuzzers.length) {
    return data.filters.fuzzers.map((name) => String(name)).filter(Boolean);
  }
  const names = [];
  (data?.targets || []).forEach((target) => {
    (target.fuzzers || []).forEach((fuzzer) => {
      const name = String(fuzzer?.fuzzer || '');
      if (name && !names.includes(name)) names.push(name);
    });
  });
  return names;
}
function allBenchmarkNames(data) {
  if (Array.isArray(data?.filters?.benchmarks) && data.filters.benchmarks.length) {
    return data.filters.benchmarks.map((name) => String(name)).filter(Boolean);
  }
  return Array.from(new Set((data?.targets || []).map((target) => String(target?.benchmark || '')).filter(Boolean))).sort();
}
function cloneUniqueBugTableForSelected(tableData, selectedSet) {
  if (!tableData || !Array.isArray(tableData.fuzzers) || !Array.isArray(tableData.rows)) return null;
  const indices = tableData.fuzzers
    .map((fuzzer, index) => [String(fuzzer), index])
    .filter(([fuzzer]) => selectedSet.has(fuzzer));
  if (!indices.length) return null;
  const fuzzers = indices.map(([fuzzer]) => fuzzer);
  const rows = (tableData.rows || [])
    .map((row) => {
      const cells = indices.map(([, index]) => {
        const value = (row.cells || [])[index];
        if (value === null || value === undefined) return null;
        return finiteOrNull(value);
      });
      const hitCounts = indices.map(([, index]) => Number((row.hit_counts || [])[index] || 0));
      if (!cells.some((value) => value !== null)) return null;
      return {
        ...row,
        cells,
        hit_counts: hitCounts,
      };
    })
    .filter(Boolean)
    // Reorder by the visible fuzzers only; the stable sort keeps the backend order on ties.
    .sort((left, right) => (
      Math.min(...left.cells.filter((value) => value !== null))
      - Math.min(...right.cells.filter((value) => value !== null))
    ))
    .map((row, index) => ({
      ...row,
      index: index + 1,
    }));
  const maxElapsedSeconds = Math.max(
    0,
    ...rows.flatMap((row) => (row.cells || []).map((value) => (value === null ? 0 : Number(value)))),
  );
  return {
    ...tableData,
    fuzzers,
    target_key: tableData.target_key,
    rows,
    has_data: rows.length > 0,
    max_elapsed_seconds: maxElapsedSeconds,
  };
}
function cloneUniqueCoverageMatrix(uniqueMatrix, selectedSet) {
  if (!uniqueMatrix?.by_metric) return uniqueMatrix || null;
  const byMetric = {};
  Object.entries(uniqueMatrix.by_metric).forEach(([metric, matrix]) => {
    byMetric[metric] = cloneMatrixForSelected(matrix, selectedSet);
  });
  return {
    ...uniqueMatrix,
    by_metric: byMetric,
    has_data: Object.values(byMetric).some((entry) => entry?.has_data),
    available_metrics: Object.entries(byMetric).filter(([, entry]) => entry?.has_data).map(([metric]) => metric),
  };
}
function cloneMetricMatrixGroup(matrixGroup, selectedSet) {
  if (!matrixGroup?.by_metric) return matrixGroup || null;
  const byMetric = {};
  Object.entries(matrixGroup.by_metric).forEach(([metric, matrix]) => {
    byMetric[metric] = cloneMatrixForSelected(matrix, selectedSet);
  });
  return {
    ...matrixGroup,
    by_metric: byMetric,
    has_data: Object.values(byMetric).some((entry) => entry?.has_data),
    available_metrics: Object.entries(byMetric).filter(([, entry]) => entry?.has_data).map(([metric]) => metric),
  };
}
function enrichTargetForSelection(target) {
  const fuzzers = (target.fuzzers || []).map((fuzzer) => ({ ...fuzzer }));
  COVERAGE_METRICS.forEach(([metric]) => {
    const values = fuzzers.map((fuzzer) => {
      const value = fuzzer.final?.[`${metric}_pct_median`];
      return finiteOrNull(value);
    });
    const ranks = rankdataDesc(values);
    fuzzers.forEach((fuzzer, index) => {
      fuzzer[`rank_${metric}_median`] = ranks[index];
    });
  });
  return {
    ...target,
    fuzzers,
  };
}

function addComparisonTotal(totals, fuzzer, stats, mode) {
  const metric = comparisonMetric(stats, mode);
  const current = totals.get(fuzzer);
  if (!current || metric.value === null) {
    if (current) current.unknown = true;
    return;
  }
  current.value += metric.value;
  current.hasValue = true;
  if (metric.bound !== 'exact') {
    current.bound = current.bound === 'exact' ? metric.bound : (
      current.bound === metric.bound ? current.bound : 'indeterminate'
    );
  }
}

function comparisonTotal(totals, fuzzer) {
  const total = totals.get(fuzzer);
  if (!total?.hasValue || total.unknown) return { value: null, bound: 'unknown' };
  return { value: total.value, bound: total.bound };
}
function computeSummary(targets, comparisonMode = FM_APP.state.comparisonMode) {
  const fuzzers = Array.from(new Set(
    targets.flatMap((target) => (target.fuzzers || []).map((entry) => entry.fuzzer)),
  )).sort();
  // Rank only on targets that every fuzzer ran, so averages and sums compare the same target set.
  const hasFuzzer = (target, fuzzer) => (target.fuzzers || []).some((entry) => entry.fuzzer === fuzzer);
  const rankedTargets = targets.filter((target) => fuzzers.every((fuzzer) => hasFuzzer(target, fuzzer)));
  const scores = new Map(fuzzers.map((fuzzer) => [fuzzer, []]));
  const aucScores = new Map(fuzzers.map((fuzzer) => [fuzzer, []]));
  const relcovScores = new Map(fuzzers.map((fuzzer) => [fuzzer, []]));
  const relbugScores = new Map(fuzzers.map((fuzzer) => [fuzzer, []]));
  const exclusiveCoverage = new Map(fuzzers.map((fuzzer) => [
    fuzzer,
    { value: 0, bound: 'exact', hasValue: false, unknown: false },
  ]));
  const uniqueBugs = new Map(fuzzers.map((fuzzer) => [fuzzer, 0]));
  const exclusiveBugs = new Map(fuzzers.map((fuzzer) => [
    fuzzer,
    { value: 0, bound: 'exact', hasValue: false, unknown: false },
  ]));
  const execs = new Map(fuzzers.map((fuzzer) => [fuzzer, []]));
  rankedTargets.forEach((target) => {
    const medians = (target.fuzzers || [])
      .map((entry) => entry.final?.regions_pct_median)
      .filter((value) => isFiniteNumber(value))
      .map(Number);
    const aucMedians = (target.fuzzers || [])
      .map((entry) => entry.final?.branches_cov_auc_norm_median)
      .filter((value) => isFiniteNumber(value))
      .map(Number);
    const best = medians.length ? Math.max(...medians) : null;
    const bestAuc = aucMedians.length ? Math.max(...aucMedians) : null;
    (target.fuzzers || []).forEach((entry) => {
      const medianValue = entry.final?.regions_pct_median;
      if (best != null && best > 0 && isFiniteNumber(medianValue)) {
        scores.get(entry.fuzzer)?.push(100 * Number(medianValue) / best);
      }
      const aucValue = entry.final?.branches_cov_auc_norm_median;
      if (bestAuc != null && bestAuc > 0 && isFiniteNumber(aucValue)) {
        aucScores.get(entry.fuzzer)?.push(100 * Number(aucValue) / bestAuc);
      }
      if (isFiniteNumber(target[relcovScoreByFuzzer]?.[entry.fuzzer])) {
        relcovScores.get(entry.fuzzer)?.push(Number(target[relcovScoreByFuzzer][entry.fuzzer]));
      }
      if (isFiniteNumber(target[relbugScoreByFuzzer]?.[entry.fuzzer])) {
        relbugScores.get(entry.fuzzer)?.push(Number(target[relbugScoreByFuzzer][entry.fuzzer]));
      }
      addComparisonTotal(exclusiveCoverage, entry.fuzzer, entry.exclusive_coverage, comparisonMode);
      uniqueBugs.set(
        entry.fuzzer,
        Number(uniqueBugs.get(entry.fuzzer) || 0) + Number(entry.final?.accumulated_bug_count || 0),
      );
      addComparisonTotal(exclusiveBugs, entry.fuzzer, entry.exclusive_bugs, comparisonMode);
      if (isFiniteNumber(entry.final?.execs_done_median)) {
        execs.get(entry.fuzzer)?.push(Number(entry.final.execs_done_median));
      }
    });
  });
  return {
    ranked_target_keys: rankedTargets.map((target) => target.key),
    unranked_targets: targets
      .filter((target) => !rankedTargets.includes(target))
      .map((target) => ({ key: target.key, missing: fuzzers.filter((fuzzer) => !hasFuzzer(target, fuzzer)) })),
    rankings: (rankedTargets.length ? fuzzers : []).map((fuzzer) => {
      const coverageExclusive = comparisonTotal(exclusiveCoverage, fuzzer);
      const bugExclusive = comparisonTotal(exclusiveBugs, fuzzer);
      return {
        fuzzer,
      coverage_score: scores.get(fuzzer)?.length
        ? cleanFloats(scores.get(fuzzer)).reduce((sum, value) => sum + value, 0) / scores.get(fuzzer).length
        : null,
      auc_score: aucScores.get(fuzzer)?.length
        ? cleanFloats(aucScores.get(fuzzer)).reduce((sum, value) => sum + value, 0) / aucScores.get(fuzzer).length
        : null,
      relcov_score: relcovScores.get(fuzzer)?.length
        ? cleanFloats(relcovScores.get(fuzzer)).reduce((sum, value) => sum + value, 0) / relcovScores.get(fuzzer).length
        : null,
      relbug_score: relbugScores.get(fuzzer)?.length
        ? cleanFloats(relbugScores.get(fuzzer)).reduce((sum, value) => sum + value, 0) / relbugScores.get(fuzzer).length
        : null,
      exclusive_coverage_count: coverageExclusive.value,
      exclusive_coverage_count_bound: coverageExclusive.bound,
      unique_bug_count: Number(uniqueBugs.get(fuzzer) || 0),
      exclusive_bug_count: bugExclusive.value,
      exclusive_bug_count_bound: bugExclusive.bound,
      median_execs_done: medianOfValues(execs.get(fuzzer) || []),
      };
    }),
  };
}
function deriveReportData(rawData, selectedFuzzers) {
  const selectedSet = new Set((selectedFuzzers || []).map((value) => String(value)));
  const selectedBenchmarks = new Set(Array.from(FM_APP.state.selectedBenchmarks).map((value) => String(value)));
  const targets = (rawData.targets || [])
    .map((target) => {
      if (!selectedBenchmarks.has(String(target.benchmark || ''))) return null;
      const filteredFuzzers = (target.fuzzers || []).filter((entry) => selectedSet.has(String(entry.fuzzer || '')));
      if (!filteredFuzzers.length) return null;
      const hasPairwiseFuzzers = filteredFuzzers.length > 1;
      const enrichedTarget = enrichTargetForSelection({
        ...target,
        fuzzers: filteredFuzzers,
        [uniqueMatrix]: hasPairwiseFuzzers
          ? cloneUniqueCoverageMatrix(target[uniqueMatrix], selectedSet)
          : emptyMetricMatrixGroup(),
        [relcovMatrix]: hasPairwiseFuzzers
          ? cloneMetricMatrixGroup(target[relcovMatrix], selectedSet)
          : emptyMetricMatrixGroup(),
        [branchMwuMatrix]: hasPairwiseFuzzers
          ? cloneMetricMatrixGroup(target[branchMwuMatrix], selectedSet)
          : emptyMetricMatrixGroup(),
        [branchA12Matrix]: hasPairwiseFuzzers
          ? cloneMetricMatrixGroup(target[branchA12Matrix], selectedSet)
          : emptyMetricMatrixGroup(),
        [uniqueBugTable]: hasPairwiseFuzzers
          ? cloneUniqueBugTableForSelected(target[uniqueBugTable], selectedSet)
          : emptyUniqueBugTable(),
        [uniqueBugMatrix]: hasPairwiseFuzzers
          ? cloneMatrixForSelected(target[uniqueBugMatrix], selectedSet)
          : emptyMatrix(),
        [relbugMatrix]: hasPairwiseFuzzers ? cloneMatrixForSelected(target[relbugMatrix], selectedSet) : emptyMatrix(),
      });
      return enrichedTarget;
    })
    .filter(Boolean);
  return {
    ...rawData,
    targets,
    summary: computeSummary(targets),
  };
}
function selectedFuzzerNames() {
  return Array.from(FM_APP.state.selectedFuzzers);
}
function selectNewFilterEntries(previous, next) {
  const previousFuzzers = new Set(allFuzzerNames(previous));
  allFuzzerNames(next).forEach((name) => {
    if (!previousFuzzers.has(name)) FM_APP.state.selectedFuzzers.add(name);
  });

  const previousBenchmarks = new Set(allBenchmarkNames(previous));
  allBenchmarkNames(next).forEach((name) => {
    if (!previousBenchmarks.has(name)) FM_APP.state.selectedBenchmarks.add(name);
  });
}

function syncFilterButton(allNames) {
  const button = byId('fuzzerFilterToggle');
  const count = byId('fuzzerFilterCount');
  if (!button || !count) return;
  const selected = selectedFuzzerNames().length;
  const total = allNames.length;
  button.textContent = `Fuzzers (${selected}/${total})`;
  count.textContent = `${selected} selected`;
}

function syncBenchmarkFilterButton(allNames) {
  const button = byId('benchmarkFilterToggle');
  const count = byId('benchmarkFilterCount');
  if (!button || !count) return;
  const selected = Array.from(FM_APP.state.selectedBenchmarks).length;
  const total = allNames.length;
  button.textContent = `Benchmarks (${selected}/${total})`;
  count.textContent = `${selected} selected`;
}

function setFilterPanelOpen(isOpen) {
  const panel = byId('fuzzerFilterPanel');
  const button = byId('fuzzerFilterToggle');
  if (!panel || !button) return;
  panel.classList.toggle('hidden', !isOpen);
  panel.setAttribute('aria-hidden', String(!isOpen));
  button.setAttribute('aria-expanded', String(isOpen));
}

function setBenchmarkFilterPanelOpen(isOpen) {
  const panel = byId('benchmarkFilterPanel');
  const button = byId('benchmarkFilterToggle');
  if (!panel || !button) return;
  panel.classList.toggle('hidden', !isOpen);
  panel.setAttribute('aria-hidden', String(!isOpen));
  button.setAttribute('aria-expanded', String(isOpen));
}
function renderFuzzerFilterOptions(data, onChange) {
  const names = allFuzzerNames(data);
  const host = byId('fuzzerFilterOptions');
  if (!host) return;
  host.textContent = '';
  names.forEach((name) => {
    const label = el('label', 'filter-option');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = FM_APP.state.selectedFuzzers.has(name);
    checkbox.value = name;
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) FM_APP.state.selectedFuzzers.add(name);
      else FM_APP.state.selectedFuzzers.delete(name);
      syncFilterButton(names);
      onChange();
    });
    label.appendChild(checkbox);
    label.appendChild(el('span', 'filter-option-label', name));
    host.appendChild(label);
  });
  syncFilterButton(names);
}
function renderBenchmarkFilterOptions(data, onChange) {
  const names = allBenchmarkNames(data);
  const host = byId('benchmarkFilterOptions');
  if (!host) return;
  host.textContent = '';
  names.forEach((name) => {
    const label = el('label', 'filter-option');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = FM_APP.state.selectedBenchmarks.has(name);
    checkbox.value = name;
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) FM_APP.state.selectedBenchmarks.add(name);
      else FM_APP.state.selectedBenchmarks.delete(name);
      syncBenchmarkFilterButton(names);
      onChange();
    });
    label.appendChild(checkbox);
    label.appendChild(el('span', 'filter-option-label', name));
    host.appendChild(label);
  });
  syncBenchmarkFilterButton(names);
}
function installFuzzerFilter(data, onChange) {
  const names = allFuzzerNames(data);
  const toggle = byId('fuzzerFilterToggle');
  const selectAll = byId('fuzzerFilterSelectAll');
  const clearAll = byId('fuzzerFilterClearAll');
  const panel = byId('fuzzerFilterPanel');
  if (!toggle || !selectAll || !clearAll || !panel) return;
  if (!FM_APP.state.selectedFuzzers.size) {
    names.forEach((name) => FM_APP.state.selectedFuzzers.add(name));
  }
  renderFuzzerFilterOptions(data, onChange);
  if (toggle.dataset.bound === '1') return;
  toggle.addEventListener('click', () => {
    const willOpen = panel.classList.contains('hidden');
    setFilterPanelOpen(willOpen);
  });
  selectAll.addEventListener('click', () => {
    allFuzzerNames(FM_APP.rawData).forEach((name) => FM_APP.state.selectedFuzzers.add(name));
    renderFuzzerFilterOptions(data, onChange);
    onChange();
  });
  clearAll.addEventListener('click', () => {
    FM_APP.state.selectedFuzzers.clear();
    renderFuzzerFilterOptions(data, onChange);
    onChange();
  });
  document.addEventListener('click', (event) => {
    const wrap = event.target?.closest?.('.filter-wrap');
    if (!wrap) setFilterPanelOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setFilterPanelOpen(false);
  });
  toggle.dataset.bound = '1';
}
function installBenchmarkFilter(data, onChange) {
  const names = allBenchmarkNames(data);
  const toggle = byId('benchmarkFilterToggle');
  const selectAll = byId('benchmarkFilterSelectAll');
  const clearAll = byId('benchmarkFilterClearAll');
  const panel = byId('benchmarkFilterPanel');
  if (!toggle || !selectAll || !clearAll || !panel) return;
  if (!FM_APP.state.selectedBenchmarks.size) {
    names.forEach((name) => FM_APP.state.selectedBenchmarks.add(name));
  }
  renderBenchmarkFilterOptions(data, onChange);
  if (toggle.dataset.bound === '1') return;
  toggle.addEventListener('click', () => {
    const willOpen = panel.classList.contains('hidden');
    setBenchmarkFilterPanelOpen(willOpen);
  });
  selectAll.addEventListener('click', () => {
    allBenchmarkNames(FM_APP.rawData).forEach((name) => FM_APP.state.selectedBenchmarks.add(name));
    renderBenchmarkFilterOptions(data, onChange);
    onChange();
  });
  clearAll.addEventListener('click', () => {
    FM_APP.state.selectedBenchmarks.clear();
    renderBenchmarkFilterOptions(data, onChange);
    onChange();
  });
  document.addEventListener('click', (event) => {
    const wrap = event.target?.closest?.('.filter-wrap');
    if (!wrap) setBenchmarkFilterPanelOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setBenchmarkFilterPanelOpen(false);
  });
  toggle.dataset.bound = '1';
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Builds the report page from reusable templates and report data.
 */





function createReportBlock({ title, subtitle = '', bodyClass = '' }) {
  const block = fromTemplate('tplReportBlock');
  const subtitleEl = part(block, 'subtitle');
  part(block, 'title').textContent = title;
  subtitleEl.textContent = subtitle;
  subtitleEl.hidden = !subtitle;
  const body = part(block, 'body');
  const controls = part(block, 'controls');
  controls.hidden = true;
  if (bodyClass) body.className = bodyClass;
  return {
    block,
    body,
    controls,
  };
}

function createFuzzerTable(section) {
  const { target } = section;
  const table = part(section.el, 'fuzzer-table');
  const sourceHead = part(section.el, 'source-head');
  let compatibilityHead = table.querySelector('[data-compatibility-head]');
  if (!compatibilityHead && sourceHead) {
    compatibilityHead = headerCell(
      'Compatibility',
      null,
      'Compatibility against the selected target reference metadata.',
    );
    compatibilityHead.dataset.compatibilityHead = '1';
    sourceHead.after(compatibilityHead);
  }
  return {
    table,
    tbody: part(section.el, 'fuzzer-body'),
    coverageHead: part(section.el, 'coverage-head'),
    sourceHead,
    compatibilityHead,
    target,
  };
}

function aggregateCellContent(primaryValue, distributionValues, formatter, detailLabels = ['min', 'max', 'median']) {
  const values = (distributionValues || []).filter((value) => isFiniteNumber(value)).map(Number);
  const primaryText = formatter(primaryValue);
  if (!values.length) {
    return { primaryText, detailsText: [] };
  }
  const summaryValues = {
    min: minimum(values),
    max: maximum(values),
    median: median(values),
  };
  const details = detailLabels.map((label) => [label, formatter(summaryValues[label])]);
  return {
    primaryText,
    detailsText: details,
  };
}

function appendAggregateCell(tr, primaryValue, distributionValues, formatter, detailLabels, primaryLabel = null) {
  const cell = el('td', 'num');
  const { primaryText, detailsText } = aggregateCellContent(primaryValue, distributionValues, formatter, detailLabels);
  const renderedPrimary = primaryLabel ? `${primaryLabel} ${primaryText}` : primaryText;
  tr.appendChild(renderAggregateCell(cell, renderedPrimary, detailsText));
}

function appendDerivedAggregateCell(tr, values, formatter, detailLabels = ['min', 'max'], primaryLabel = null) {
  const numericValues = (values || []).filter((value) => isFiniteNumber(value)).map(Number);
  const primaryValue = median(numericValues);
  const cell = el('td', 'num');
  const { primaryText, detailsText } = aggregateCellContent(primaryValue, numericValues, formatter, detailLabels);
  const renderedPrimary = primaryLabel ? `${primaryLabel} ${primaryText}` : primaryText;
  tr.appendChild(renderAggregateCell(cell, renderedPrimary, detailsText));
}

function appendCustomAggregateCell(tr, primaryText, values, formatter, detailLabels = ['min', 'max', 'median']) {
  const cell = el('td', 'num');
  const numericValues = (values || []).filter((value) => isFiniteNumber(value)).map(Number);
  const { detailsText } = aggregateCellContent(numericValues[0], numericValues, formatter, detailLabels);
  tr.appendChild(renderAggregateCell(cell, primaryText, detailsText));
}

function headerCell(label, className, tooltip) {
  return setTooltip(el('th', className, label), tooltip);
}

function statsDetailLines(stats, formatter, labelPrefix = '') {
  const lines = [];
  ['min', 'max', 'median'].forEach((label) => {
    const value = stats?.[label];
    if (value === null || value === undefined || Number.isNaN(Number(value))) return;
    lines.push([`${labelPrefix}${label}`, formatter(value)]);
  });
  return lines;
}

function exclusiveCoverageStats(target, fuzzer) {
  if (fuzzer.exclusive_coverage) return fuzzer.exclusive_coverage;
  const matrix = resolveCoverageMatrix(target.unique_matrix, 'branches');
  const index = (matrix?.fuzzers || []).map(String).indexOf(String(fuzzer.fuzzer || ''));
  if (index < 0) return {};
  const value = finiteOrNull((matrix.unique_counts || [])[index]);
  return {
    exclusive_any: value,
    exclusive_any_bound: value === null ? 'unknown' : 'exact',
  };
}

function formattedComparisonMetric(metric) {
  if (metric.value === null) return '?';
  if (metric.bound === 'lower') return `≥${fmtInt(metric.value)}`;
  if (metric.bound === 'upper') return `≤${fmtInt(metric.value)}`;
  if (metric.bound === 'indeterminate') return `~${fmtInt(metric.value)}`;
  return fmtInt(metric.value);
}

function hasMultipleFuzzers(target) {
  const fuzzers = (target.fuzzers || []).map((fuzzer) => String(fuzzer.fuzzer || '')).filter(Boolean);
  return new Set(fuzzers).size > 1;
}

function hasResourceTelemetry(target) {
  return (target.fuzzers || []).some((fuzzer) => (fuzzer.curve || []).some((point) => (
    isFiniteNumber(point.resource_memory_mib_median)
    || isFiniteNumber(point.resource_corpus_disk_mib_median)
  )));
}

function updateTargetSortIndicators(section) {
  section.fuzzerTable.table.querySelectorAll('th[data-sort-key]').forEach((th) => {
    const button = th.querySelector('button');
    const arrow = th.querySelector('.sort-arrow');
    const key = th.dataset.sortKey;
    const active = key === section.tableSort.key;
    if (button) {
      button.classList.toggle('active', active);
    }
    if (arrow) {
      arrow.textContent = active ? (section.tableSort.direction === 'asc' ? '▲' : '▼') : '';
    }
  });
}

function installTargetTableSorting(section) {
  section.fuzzerTable.table.querySelectorAll('th[data-sort-key]').forEach((th) => {
    if (th.dataset.bound === '1') return;
    const button = el('button', 'sort-btn target-sort-btn');
    button.type = 'button';
    while (th.firstChild) {
      button.appendChild(th.firstChild);
    }
    const arrow = el('span', 'sort-arrow');
    button.appendChild(arrow);
    th.appendChild(button);
    button.addEventListener('click', () => {
      const key = th.dataset.sortKey || 'branches_union';
      if (section.tableSort.key === key) {
        section.tableSort.direction = section.tableSort.direction === 'asc' ? 'desc' : 'asc';
      } else {
        section.tableSort = { key, direction: 'desc' };
      }
      FM_APP.state.targetTableSort.set(section.target.key, section.tableSort);
      renderFuzzerTable(section);
    });
    th.dataset.bound = '1';
  });
}
function shouldShowSourceColumn(target) {
  return (target?.fuzzers || []).some((fuzzer) => fuzzer?.origin === 'historical');
}
function shouldShowCompatibilityColumn(target) {
  return (target?.fuzzers || []).some((fuzzer) => compatibilityLevel(fuzzer) !== 'compatible');
}

function compatibilityLevel(fuzzer) {
  return String(fuzzer?.compatibility?.level || 'compatible');
}

function sourceDetailText(fuzzer) {
  const detail = fuzzer?.source_detail || {};
  const facts = [
    ['Source', detail.source_id || fuzzer?.source_id],
    ['Run', detail.run_id || fuzzer?.source_run_id],
    ['Original fuzzer', detail.source_fuzzer || fuzzer?.source_fuzzer],
    ['Runtime', detail.runtime_seconds == null ? null : formatDuration(detail.runtime_seconds)],
    ['Repetitions', detail.repetitions == null ? null : fmtInt(detail.repetitions)],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
  return facts.map(([label, value]) => `${label}: ${value}`).join('\n');
}

function appendSourceCell(tr, fuzzer, showSource) {
  if (!showSource) return;
  const cell = el('td', null, fuzzer.origin || 'fresh');
  cell.title = sourceDetailText(fuzzer);
  tr.appendChild(cell);
}

function appendCompatibilityCell(tr, target, fuzzer, showCompatibility) {
  if (!showCompatibility) return;
  const cell = el('td');
  if (!fuzzer?.compatibility) {
    cell.textContent = '—';
    tr.appendChild(cell);
    return;
  }
  const level = compatibilityLevel(fuzzer);
  const button = el('button', `compatibility-btn compatibility-${level}`, level);
  button.type = 'button';
  button.title = 'Show compatibility details';
  button.addEventListener('click', () => openCompatibilityModal(target, fuzzer));
  cell.appendChild(button);
  tr.appendChild(cell);
}

function identityLabel(identity) {
  if (!identity) return 'none';
  return `${identity.origin || 'source'} ${identity.fuzzer || identity.source_fuzzer || '-'} (${identity.source_id || '-'} / ${identity.run_id || '-'})`;
}

function ensureCompatibilityModal() {
  const modal = byId('compatibilityModal');
  const title = byId('compatibilityModalTitle');
  const subtitle = byId('compatibilityModalSubtitle');
  const body = byId('compatibilityModalBody');
  const close = byId('compatibilityModalClose');
  if (!modal || !title || !subtitle || !body || !close) return null;
  if (modal.dataset.bound) return { modal, title, subtitle, body };
  const hide = () => modal.classList.add('hidden');
  close.addEventListener('click', hide);
  modal.addEventListener('click', (event) => { if (event.target === modal) hide(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') hide(); });
  modal.dataset.bound = '1';
  return { modal, title, subtitle, body };
}
function openCompatibilityModal(target, fuzzer) {
  const refs = ensureCompatibilityModal();
  if (!refs) return;
  const valueText = (value) => {
    if (value === null || value === undefined || value === '') return '—';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  };
  const labels = { config: 'Target/config', source: 'Target source metadata', environment: 'Environment' };
  const groups = new Map();
  const compatibility = fuzzer?.compatibility || { level: 'compatible', diffs: [] };
  refs.title.textContent = `${fuzzer?.fuzzer || 'Fuzzer'} compatibility: ${compatibility.level || 'compatible'}`;
  refs.subtitle.textContent = [
    `${target?.benchmark || '-'} / ${target?.fuzz_target || target?.key || '-'}`,
    `Candidate: ${identityLabel({
      origin: fuzzer?.origin || 'fresh',
      source_id: fuzzer?.source_id,
      run_id: fuzzer?.source_run_id,
      fuzzer: fuzzer?.fuzzer,
      source_fuzzer: fuzzer?.source_fuzzer,
    })}`,
    `Reference: ${identityLabel(compatibility.reference)}`,
  ].join(' · ');
  refs.body.textContent = '';
  if (compatibility.comparison_note) {
    refs.body.appendChild(el('div', 'compatibility-note', compatibility.comparison_note));
  }
  (compatibility.diffs || []).forEach((row) => {
    const label = labels[row.domain] || String(row.domain || 'Other');
    groups.set(label, [...(groups.get(label) || []), row]);
  });
  if (!groups.size) {
    refs.body.appendChild(el('div', 'matrix-empty', 'No differences found.'));
  }
  groups.forEach((rows, label) => {
    const section = el('section', 'compatibility-section');
    section.appendChild(el('div', 'compatibility-section-title', label));
    const table = el('table', 'table compatibility-diff-table');
    const thead = el('thead');
    const head = el('tr');
    ['Field', 'Reference', 'Candidate', 'Impact'].forEach((text) => head.appendChild(el('th', null, text)));
    thead.appendChild(head);
    table.appendChild(thead);
    const tbody = el('tbody');
    rows.forEach((row) => {
      const tr = el('tr');
      [
        [row.path || '—', 'mono'],
        [valueText(row.reference), null],
        [valueText(row.candidate), null],
        [row.message || row.severity || '—', null],
      ].forEach(([value, cls]) => tr.appendChild(el('td', cls, value)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    section.appendChild(table);
    refs.body.appendChild(section);
  });
  refs.modal.classList.remove('hidden');
}

function renderFuzzerTable(section) {
  const { target, fuzzerTable } = section;
  const metric = 'branches';
  const mode = 'abs';
  fuzzerTable.coverageHead.textContent = 'Branches';
  fuzzerTable.tbody.textContent = '';
  const showSource = shouldShowSourceColumn(target);
  const showCompatibility = shouldShowCompatibilityColumn(target);
  if (fuzzerTable.sourceHead) fuzzerTable.sourceHead.hidden = !showSource;
  if (fuzzerTable.compatibilityHead) fuzzerTable.compatibilityHead.hidden = !showCompatibility;

  // Same AUC score as the overview ranking: time-averaged coverage relative to the best visible median.
  const bestAucNorm = Math.max(0, ...cleanFloats((target.fuzzers || [])
    .map((fuzzer) => fuzzer.final?.branches_cov_auc_norm_median)));
  const aucScores = (fuzzer) => (fuzzer.trials || []).map((trial) => (
    bestAucNorm > 0 && isFiniteNumber(trial.branches_cov_auc_norm)
      ? 100 * Number(trial.branches_cov_auc_norm) / bestAucNorm
      : null
  ));
  const rows = (target.fuzzers || []).map((fuzzer) => {
    const branch10kValues = (fuzzer.trials || []).map((trial) => per10kExec(trial.branches_cov, trial.execs_done));
    const exclusiveCoverage = exclusiveCoverageStats(target, fuzzer);
    const selectedCoverage = comparisonMetric(exclusiveCoverage, FM_APP.state.comparisonMode);
    const selectedBugs = comparisonMetric(fuzzer.exclusive_bugs, FM_APP.state.comparisonMode);
    return {
      ...fuzzer,
      _section: section,
      branches_union: Number(fuzzer.aggregate?.branches_covered),
      execs_per_sec_median: median(fuzzer.distribution?.execs_per_sec),
      execs_done_median: median(fuzzer.distribution?.execs_done),
      branch_per_10k_median: median(branch10kValues),
      auc_score_median: median(aucScores(fuzzer)),
      exclusive_coverage_total: selectedCoverage.value,
      corpus_median: median(fuzzer.distribution?.corpus_files_total),
      unique_bug_total: Number(fuzzer.final?.accumulated_bug_count ?? dedupeBugCount(fuzzer.bugs)),
      exclusive_bug_total: selectedBugs.value,
      all_bug_hits_median: median(fuzzer.distribution?.bug_hits_total),
    };
  });

  const sortKey = section.tableSort?.key || 'branches_union';
  const sortDirection = section.tableSort?.key === sortKey ? section.tableSort.direction : 'desc';
  rows.sort((left, right) => compareNumericRows(left, right, sortKey, sortDirection));
  rows.forEach((fuzzer) => {
    const tr = el('tr');
    const nameCell = el('td');
    const nameRow = el('div', 'fuzzer-name');
    const swatch = el('span', 'legend-swatch');
    swatch.style.background = fuzzerColor(fuzzer.fuzzer);
    nameRow.appendChild(swatch);
    const textWrap = el('div', 'fuzzer-meta');
    textWrap.appendChild(createFuzzerNameButton(fuzzer));
    if (fuzzer.coverage_report) {
      const coverageLine = el('div', 'muted small');
      coverageLine.appendChild(aLink('coverage report', fuzzer.coverage_report));
      textWrap.appendChild(coverageLine);
    }
    nameRow.appendChild(textWrap);
    nameCell.appendChild(nameRow);
    tr.appendChild(nameCell);
    appendSourceCell(tr, fuzzer, showSource);
    appendCompatibilityCell(tr, target, fuzzer, showCompatibility);

    const branchUnionValue = fuzzer.aggregate?.branches_covered;
    appendCustomAggregateCell(
      tr,
      `total ${fmtInt(branchUnionValue)}`,
      fuzzer.distribution?.branches_cov,
      fmtInt,
      ['min', 'max', 'median'],
    );
    appendDerivedAggregateCell(
      tr,
      (fuzzer.trials || []).map((trial) => per10kExec(trial.branches_cov, trial.execs_done)),
      (value) => fmt(value, 1),
      ['min', 'max'],
      'median',
    );
    appendDerivedAggregateCell(
      tr,
      aucScores(fuzzer),
      (value) => fmt(value, 1),
      ['min', 'max'],
      'median',
    );
    const exclusiveCoverage = exclusiveCoverageStats(target, fuzzer);
    const selectedCoverage = comparisonMetric(exclusiveCoverage, FM_APP.state.comparisonMode);
    tr.appendChild(renderAggregateCell(
      el('td', 'num'),
      `total ${formattedComparisonMetric(selectedCoverage)}`,
      statsDetailLines(exclusiveCoverage, fmtInt, 'trial '),
    ));
    appendAggregateCell(
      tr,
      median(fuzzer.distribution?.execs_done),
      fuzzer.distribution?.execs_done,
      formatExecCount,
      ['min', 'max'],
      'median',
    );
    appendAggregateCell(
      tr,
      median(fuzzer.distribution?.execs_per_sec),
      fuzzer.distribution?.execs_per_sec,
      formatExecCount,
      ['min', 'max'],
      'median',
    );
    appendAggregateCell(
      tr,
      median(fuzzer.distribution?.corpus_files_total),
      fuzzer.distribution?.corpus_files_total,
      fmtInt,
      ['min', 'max'],
      'median',
    );
    appendCustomAggregateCell(
      tr,
      `total ${fmtInt(fuzzer.final?.accumulated_bug_count ?? dedupeBugCount(fuzzer.bugs))}`,
      fuzzer.distribution?.unique_bugs_total,
      fmtInt,
      ['min', 'max', 'median'],
    );
    const selectedBugs = comparisonMetric(fuzzer.exclusive_bugs, FM_APP.state.comparisonMode);
    tr.appendChild(renderAggregateCell(
      el('td', 'num'),
      `total ${formattedComparisonMetric(selectedBugs)}`,
      statsDetailLines(fuzzer.exclusive_bugs, fmtInt, 'trial '),
    ));
    appendAggregateCell(
      tr,
      median(fuzzer.distribution?.bug_hits_total),
      fuzzer.distribution?.bug_hits_total,
      fmtInt,
      ['min', 'max'],
      'median',
    );
    fuzzerTable.tbody.appendChild(tr);
  });
  updateTargetSortIndicators(section);
}

function createCoverageBlock(section) {
  const { block, body, controls } = createReportBlock({
    title: 'COVERAGE ANALYSIS',
    // subtitle: 'Only this block refreshes when the local coverage selectors change.',
    bodyClass: 'block-grid-2',
  });
  block.classList.add('block-topic', 'block-topic-coverage');
  const metricSelect = createSelect(COVERAGE_METRICS, section.coverageState.metric, (value) => {
    section.coverageState.metric = value;
    FM_APP.state.coverageByTarget.set(section.target.key, { ...section.coverageState });
    renderCoverageBlock(section);
  });
  const valueSelect = createSelect(VALUE_OPTIONS, section.coverageState.value, (value) => {
    section.coverageState.value = value;
    FM_APP.state.coverageByTarget.set(section.target.key, { ...section.coverageState });
    renderCoverageBlock(section);
  });
  controls.hidden = false;
  controls.appendChild(metricSelect);
  const lineCard = makeCanvasCard({
    title: 'Coverage growth',
    subtitle: 'Across snapshots',
    withLegend: true,
    exportName: `${section.target.key}-coverage-growth`,
  });
  lineCard.card.querySelector('.chart-actions')?.prepend(valueSelect);
  const distCard = makeCanvasCard({
    title: 'Coverage distribution',
    subtitle: 'Click to inspect values',
    interactiveDistribution: true,
    exportName: `${section.target.key}-coverage-distribution`,
  });
  const matrixCard = hasMultipleFuzzers(section.target) ? makeMatrixCard({
    title: 'Unique coverage matrix',
    subtitle: 'Cell = coverage elements reached by the row fuzzer but never reached by the column fuzzer.',
  }) : null;
  const relCard = hasMultipleFuzzers(section.target) ? makeMatrixCard({
    title: 'RelCov matrix',
    subtitle: 'Cell = how much of the column fuzzer union coverage is also covered by the row fuzzer.',
  }) : null;

  body.appendChild(lineCard.card);
  body.appendChild(distCard.card);
  if (matrixCard) body.appendChild(matrixCard.card);
  if (relCard) body.appendChild(relCard.card);

  section.coverage = {
    block,
    metricSelect,
    valueSelect,
    lineCard,
    distCard,
    matrixCard,
    relCard,
  };
  matrixCard?.setExportName(`${section.target.key}-unique-branch-matrix`);
  relCard?.setExportName(`${section.target.key}-relcov-matrix`);
  return block;
}

function createPerformanceBlock(section) {
  const { block, body } = createReportBlock({
    title: 'THROUGHPUT & CORPUS',
    // subtitle: 'Corpus size and executed tests in one place.',
    bodyClass: 'block-grid-2',
  });
  block.classList.add('block-topic', 'block-topic-throughput');
  const corpusCard = makeCanvasCard({
    title: 'Corpus size growth',
    subtitle: 'Accumulated corpus files',
    withLegend: true,
    exportName: `${section.target.key}-corpus-growth`,
  });
  const execCard = makeCanvasCard({
    title: 'Executed tests growth',
    subtitle: 'Accumulated executions',
    withLegend: true,
    exportName: `${section.target.key}-exec-growth`,
  });
  body.appendChild(corpusCard.card);
  body.appendChild(execCard.card);
  section.performance = { block, corpusCard, execCard };
  return block;
}

function createSummaryTableBlock(section, exportButton) {
  const summary = createReportBlock({
    title: 'TRIAL SUMMARY',
    bodyClass: 'block-grid-1',
  });
  summary.block.classList.add('block-topic', 'block-topic-summary');
  summary.controls.hidden = false;
  if (exportButton) summary.controls.appendChild(exportButton);
  summary.body.appendChild(section.fuzzerTable.table);
  return summary.block;
}

function createTrialTableBlock(section) {
  const details = el('details', 'details');
  details.appendChild(el('summary', null, 'Per-trial runs'));
  const controls = el('div', 'chart-actions');
  const exportButton = el('button', 'btn', 'Export');
  exportButton.type = 'button';
  controls.appendChild(exportButton);
  details.appendChild(controls);
  const body = el('div');
  const columns = [
    ['Fuzzer', null, 'Fuzzer name for the trial row.'],
    ['Source', null, 'Whether this trial row comes from the active run or a historical measurement.'],
    ['Rep', 'num', 'Repetition index inside the fuzzer-target group.'],
    ['Run time', 'num', 'Elapsed runtime of the trial.'],
    ['Exec/sec', 'num', 'Executed tests per second at the end of the trial.'],
    ['Regions covered', 'num', 'Final covered region count for the trial.'],
    ['Branches covered', 'num', 'Final covered branch count for the trial.'],
    [
      'Convergence',
      'num',
      'Coverage convergence percentage: 100 times branch coverage-time AUC divided by max branch coverage times runtime.',
    ],
    ['Branches / 10k exec', 'num', 'Final branch coverage normalized to ten thousand executed tests.'],
  ].map(([label, cls, tooltip], index) => ({
    label,
    key: `c${index}`,
    kind: cls === 'num' ? 'text-num' : 'text',
    tooltip,
  }));
  details.appendChild(body);
  section.trialTable = { block: details, body, columns };
  installElementExportMenu(exportButton, body, () => `${section.target.key}-trial-runs`);
  return details;
}

function createBugBlock(section) {
  const { block, body } = createReportBlock({
    title: 'BUG FINDING',
    // subtitle: 'Unique bugs, monotonic overall crashes, and pairwise bug comparison matrices together.',
    bodyClass: 'block-stack',
  });
  block.classList.add('block-topic', 'block-topic-bugs');
  const topRow = el('div', 'block-grid-2');
  const bottomStack = el('div', 'block-grid-2');
  const growthCard = makeCanvasCard({
    title: 'Unique bug growth',
    subtitle: 'Across snapshots',
    withLegend: true,
    exportName: `${section.target.key}-bug-growth`,
  });
  const crashesCard = makeCanvasCard({
    title: 'Overall crashes',
    subtitle: 'Accumulated crash files over time',
    withLegend: true,
    exportName: `${section.target.key}-overall-crashes`,
  });
  const matrixCard = hasMultipleFuzzers(section.target) ? makeMatrixCard({
    title: 'Unique bug discovery table',
    subtitle: 'Rows are bugs in first-discovery order, columns are fuzzers, cells show first hit time.',
  }) : null;
  const pairwiseCard = hasMultipleFuzzers(section.target) ? makeMatrixCard({
    title: 'Pairwise unique bug matrix',
    subtitle: 'Cell = bugs found by the row fuzzer but not the column fuzzer.',
  }) : null;
  const relCard = hasMultipleFuzzers(section.target) ? makeMatrixCard({
    title: 'RelBug matrix',
    subtitle: 'Cell = how much of the column fuzzer bug set is also found by the row fuzzer.',
  }) : null;
  topRow.appendChild(growthCard.card);
  topRow.appendChild(crashesCard.card);
  if (matrixCard) bottomStack.appendChild(matrixCard.card);
  if (pairwiseCard) bottomStack.appendChild(pairwiseCard.card);
  if (relCard) bottomStack.appendChild(relCard.card);
  body.appendChild(topRow);
  if (matrixCard || relCard) body.appendChild(bottomStack);

  matrixCard?.setExportName(`${section.target.key}-unique-bug-matrix`);
  pairwiseCard?.setExportName(`${section.target.key}-pairwise-unique-bug-matrix`);
  relCard?.setExportName(`${section.target.key}-relbug-matrix`);
  section.bugsBlock = { block, growthCard, crashesCard, matrixCard, pairwiseCard, relCard };
  return block;
}

function createResourceTelemetryBlock(section) {
  const { block, body } = createReportBlock({
    title: 'RESOURCE TELEMETRY',
    // subtitle: 'CPU, memory, and live corpus disk usage sampled at tick save time.',
    bodyClass: 'block-grid-2',
  });
  block.classList.add('block-topic', 'block-topic-telemetry');
  // const cpuCard = makeCanvasCard({
  //   title: 'CPU usage',
  //   subtitle: 'docker stats CPU %',
  //   withLegend: true,
  //   exportName: `${section.target.key}-resource-cpu`,
  // });
  const memoryCard = makeCanvasCard({
    title: 'Memory usage',
    subtitle: 'docker stats memory usage',
    withLegend: true,
    exportName: `${section.target.key}-resource-memory`,
  });
  const diskCard = makeCanvasCard({
    title: 'Corpus disk usage',
    subtitle: 'du -hs on live corpus dir',
    withLegend: true,
    exportName: `${section.target.key}-resource-disk`,
  });
  // body.appendChild(cpuCard.card);
  body.appendChild(memoryCard.card);
  body.appendChild(diskCard.card);
  section.resourceTelemetry = { block, /*cpuCard,*/ memoryCard, diskCard };
  return block;
}

function createExtraSectionDebugDetails(target) {
  const rows = target.extra_section_debug || [];
  if (!rows.length) return null;
  const details = el('details', 'details');
  details.appendChild(el('summary', null, 'Extra section debug'));
  const pre = el('pre', 'modal-body mono');
  pre.textContent = JSON.stringify(rows, null, 2);
  details.appendChild(pre);
  return details;
}

function createCustomMetricsBlock(extraSections) {
  if (!extraSections.length) return null;
  const custom = createReportBlock({
    title: 'CUSTOM METRICS',
    bodyClass: 'block-stack',
  });
  custom.block.classList.add('block-topic', 'block-topic-custom');
  renderExtraSections(custom.body, extraSections);
  return custom.block;
}

function createDebugBlock(target) {
  const extraDebug = createExtraSectionDebugDetails(target);
  if (!extraDebug) return null;
  const debug = createReportBlock({
    title: 'DEBUG',
    bodyClass: 'block-grid-1',
  });
  debug.block.classList.add('block-topic', 'block-topic-debug');
  debug.body.appendChild(extraDebug);
  return debug.block;
}

function createStatisticsBlock(section) {
  if (!hasMultipleFuzzers(section.target)) return null;
  const statistics = createReportBlock({
    title: 'STATISTICS & SIGNIFICANCE',
    bodyClass: 'block-grid-2',
  });
  statistics.block.classList.add('block-topic', 'block-topic-statistics');
  const mwuCard = makeMatrixCard({
    title: 'Branch MWU p-value matrix',
    subtitle: 'Pairwise Mann-Whitney U p-values on final per-trial branch coverage.',
  });
  const a12Card = makeMatrixCard({
    title: 'Branch A12 matrix',
    subtitle: 'Pairwise Vargha-Delaney A12 effect sizes on final per-trial branch coverage.',
  });
  statistics.body.appendChild(mwuCard.card);
  statistics.body.appendChild(a12Card.card);
  section.statistics = {
    block: statistics.block,
    mwuCard,
    a12Card,
  };
  return statistics.block;
}

function resolveCoverageMatrix(uniqueMatrix, metric) {
  if (!uniqueMatrix) return null;
  if (uniqueMatrix.by_metric) return uniqueMatrix.by_metric[metric] || null;
  return uniqueMatrix;
}

function defaultCoverageMetric(target) {
  const hasMetricData = (metric) => (target.fuzzers || []).some((fuzzer) => (
    Number(fuzzer.aggregate?.[`${metric}_covered`]) > 0
    || (fuzzer.curve || []).some((point) => Number(point?.[`${metric}_cov`]) > 0)
  ));
  return COVERAGE_METRICS.find(([metric]) => hasMetricData(metric))?.[0] || COVERAGE_METRICS[0][0];
}

function renderUniqueCoverageMatrix(host, uniqueMatrix, metric, mode) {
  host.textContent = '';
  const matrix = comparisonMatrix(resolveCoverageMatrix(uniqueMatrix, metric), FM_APP.state.comparisonMode);
  if (!matrix || !matrix.fuzzers?.length || !matrix.matrix?.length) {
    host.appendChild(el(
      'div',
      'matrix-empty',
      FM_APP.state.comparisonMode === 'all'
        ? 'Strict per-trial coverage data is unavailable.'
        : 'No unique coverage data.',
    ));
    return;
  }

  const rendered = mode === 'pct' ? {
    ...matrix,
    matrix: (matrix.matrix || []).map((row, rowIndex) => row.map((value) => {
      if (!isFiniteNumber(value)) return null;
      const denominator = Number((matrix.covered_counts || [])[rowIndex] || 0);
      return denominator > 0 ? 100 * Number(value) / denominator : 0;
    })),
    max_value: null,
  } : matrix;
  renderMatrixTable(host, rendered, {
    formatter: mode === 'pct' ? 'pct' : 'int',
    emptyMessage: 'No unique coverage data.',
    tint: 'rgba(120,180,255,ALPHA)',
  });
}

function renderCoverageComparison(section) {
  const { target, coverageState, coverage } = section;
  if (!coverage.matrixCard) return;
  const metric = coverageState.metric;
  const metricName = metricLabel(metric).toLowerCase();
  renderUniqueCoverageMatrix(coverage.matrixCard.body, target.unique_matrix, metric, 'abs');
  coverage.matrixCard.setTitle(`Unique ${metricName} matrix`);
  coverage.matrixCard.setSubtitle(
    FM_APP.state.comparisonMode === 'all'
      ? `Cell = ${metricName} reached in every row-fuzzer trial but no column-fuzzer trial.`
      : `Cell = ${metricName} reached in any row-fuzzer trial but no column-fuzzer trial.`,
  );
  coverage.matrixCard.setExportName(`${section.target.key}-unique-${metric}-matrix`);
}

function branchPValueCellStyle(value) {
  if (!isFiniteNumber(value) || Number(value) > 0.05) return '';
  const clamped = Math.max(0, Math.min(0.05, Number(value)));
  const alpha = 0.10 + (0.55 * (1 - (clamped / 0.05)));
  return `background:rgba(78,183,118,${alpha.toFixed(3)}); font-weight:700;`;
}

function branchA12CellStyle(value) {
  if (!isFiniteNumber(value)) return '';
  const effect = Math.min(1, Math.abs(Number(value) - 0.5) * 2);
  if (effect <= 0) return '';
  const alpha = 0.10 + (0.55 * effect);
  const tint = Number(value) >= 0.5 ? '69,160,73' : '239,108,0';
  return `background:rgba(${tint},${alpha.toFixed(3)}); font-weight:700;`;
}

function lineChartSpec(series, overrides = {}) {
  const overrideOptions = overrides.options || {};
  // Aggregated curves are always keyed by elapsed campaign time.
  return {
    kind: 'line',
    series,
    ...overrides,
    options: {
      yClampPct: false,
      xMode: 'time',
      ...overrideOptions,
    },
  };
}

function renderLineCard(card, series, overrides = {}) {
  renderChartCard(card, lineChartSpec(series, overrides));
}

function uniqueBugHeatColor(elapsedSeconds, plannedDurationSeconds) {
  if (!isFiniteNumber(elapsedSeconds)) return '#ffffff';
  const duration = isFiniteNumber(plannedDurationSeconds) && Number(plannedDurationSeconds) > 0
    ? Number(plannedDurationSeconds)
    : Math.max(1, Number(elapsedSeconds));
  const ratio = Math.max(0, Math.min(1, Number(elapsedSeconds) / duration));
  const lightness = 82 - ((1 - ratio) * 40);
  const saturation = 56 + ((1 - ratio) * 16);
  return `hsl(144 ${saturation.toFixed(1)}% ${lightness.toFixed(1)}%)`;
}

function uniqueBugCellStyle(elapsedSeconds, plannedDurationSeconds) {
  const background = uniqueBugHeatColor(elapsedSeconds, plannedDurationSeconds);
  if (!isFiniteNumber(elapsedSeconds)) {
    return `background:${background}; color:#111827; font-weight:700;`;
  }
  const duration = isFiniteNumber(plannedDurationSeconds) && Number(plannedDurationSeconds) > 0
    ? Number(plannedDurationSeconds)
    : Math.max(1, Number(elapsedSeconds) || 1);
  const ratio = !isFiniteNumber(elapsedSeconds) ? 1 : Number(elapsedSeconds) / duration;
  const useLightText = ratio <= 0.45;
  return `background:${background}; color:${useLightText ? '#f7f8fa' : '#111827'}; font-weight:700;`;
}

function ensureBugModal() {
  const modal = byId('bugModal');
  const title = byId('bugModalTitle');
  const body = byId('bugModalBody');
  const close = byId('bugModalClose');
  if (!modal || !title || !body || !close) return null;
  if (!modal.dataset.bound) {
    close.addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', (event) => {
      if (event.target === modal) modal.classList.add('hidden');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') modal.classList.add('hidden');
    });
    modal.dataset.bound = '1';
  }
  return { modal, title, body };
}

function openBugModal(targetKey, row) {
  const refs = ensureBugModal();
  if (!refs) return;
  refs.title.textContent = `#${row.index}. ${row.bug_key || '(unknown)'}`;
  refs.body.textContent = '';

  const content = el('div', 'modal-copy');
  const meta = el('div', 'modal-meta');
  [
    ['First seen', row.global_first_seen_at || '—'],
    ['Type', row.issue_type || '—'],
    ['Top function', row.top_func || '—'],
    ['Bug key', row.bug_key || '—'],
  ].forEach(([label, value]) => {
    const line = el('div', 'modal-meta-row');
    line.appendChild(el('span', 'modal-meta-label', `${label}: `));
    line.appendChild(document.createTextNode(String(value)));
    meta.appendChild(line);
  });
  content.appendChild(meta);

  const framesWrap = el('div', 'modal-stack');
  framesWrap.appendChild(el('div', 'modal-stack-title', 'Stacktrace'));
  const frames = Array.isArray(row.frames) ? row.frames.filter(Boolean) : [];
  if (frames.length) {
    const list = el('ol', 'modal-stack-list');
    frames.forEach((frame) => {
      const item = el('li', 'modal-stack-item');
      item.appendChild(el('code', 'mono', frame));
      list.appendChild(item);
    });
    framesWrap.appendChild(list);
  } else {
    framesWrap.appendChild(el('div', 'muted small', 'No stacktrace frames stored.'));
  }
  content.appendChild(framesWrap);

  const outputWrap = el('div', 'modal-stack');
  outputWrap.appendChild(el('div', 'modal-stack-title', 'Crash output'));
  if (row.output) {
    const pre = el('pre', 'modal-output mono');
    pre.textContent = row.output;
    outputWrap.appendChild(pre);
  } else {
    outputWrap.appendChild(el('div', 'muted small', 'No crash output stored.'));
  }
  content.appendChild(outputWrap);

  refs.body.appendChild(content);
  refs.modal.classList.remove('hidden');
}

function renderUniqueBugTable(host, tableData) {
  host.textContent = '';
  if (!tableData || !tableData.fuzzers?.length || !tableData.rows?.length) {
    host.appendChild(el('div', 'matrix-empty', 'No unique bug discovery data.'));
    return;
  }

  const hasSnapshotSeconds = isFiniteNumber(tableData.last_snapshot_elapsed_seconds)
    && Number(tableData.last_snapshot_elapsed_seconds) > 0;
  const scaleSeconds = hasSnapshotSeconds
    ? Number(tableData.last_snapshot_elapsed_seconds)
    : Number(tableData.max_elapsed_seconds || 0);
  const scaleLabel = formatDuration(scaleSeconds);
  // const note = scaleSeconds > 0
  //   ? `Black means not found. Earlier hits are darker, later hits are lighter. The color scale spans ${scaleLabel}.`
  //   : 'Black means not found. Earlier hits are darker, later hits are lighter.';
  // host.appendChild(el('div', 'matrix-note muted small', note));

  const wrap = el('div', 'matrix-wrap');
  const table = el('table', 'table matrix unique-bug-table');
  const thead = el('thead');
  const headerRow = el('tr');
  headerRow.appendChild(headerCell('Bug', null, 'Bugs ordered by first discovery time across the visible fuzzers.'));
  (tableData.fuzzers || []).forEach((fuzzer) => {
    headerRow.appendChild(headerCell(fuzzer, 'num', `Elapsed time to first hit for ${fuzzer}.`));
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = el('tbody');
  (tableData.rows || []).forEach((row) => {
    const tr = el('tr');
    const labelCell = el('td', 'unique-bug-label');
    const fullLabel = `#${row.index}. ${row.bug_key || '(unknown)'}`;
    const trigger = el('button', 'unique-bug-trigger', fullLabel);
    trigger.type = 'button';
    trigger.title = fullLabel;
    trigger.addEventListener('click', () => openBugModal(tableData.target_key || 'Target', row));
    labelCell.appendChild(trigger);
    const meta = [row.issue_type, row.top_func].filter(Boolean).join(' • ');
    // if (meta) {
    //   labelCell.appendChild(el('div', 'muted small', meta));
    // }
    tr.appendChild(labelCell);

    (row.cells || []).forEach((elapsedSeconds, cellIndex) => {
      const td = el('td', 'num unique-bug-cell', elapsedSeconds === null ? '-' : formatDuration(elapsedSeconds));
      td.style.cssText = uniqueBugCellStyle(elapsedSeconds, scaleSeconds);
      const hitCount = Number((row.hit_counts || [])[cellIndex] || 0);
      const fuzzer = String((tableData.fuzzers || [])[cellIndex] || '');
      td.title = elapsedSeconds === null
        ? 'Bug not found by this fuzzer.'
        : `First hit after ${formatDuration(elapsedSeconds)}. ${fuzzer || 'This fuzzer'} found it ${fmtInt(hitCount)} times.`;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  host.appendChild(wrap);
}

function renderCoverageBlock(section) {
  const { target, coverageState, coverage } = section;
  const metric = coverageState.metric;
  const mode = coverageState.value;
  const lineSeries = buildCoverageSeries(target.fuzzers, metric, mode);
  renderLineCard(coverage.lineCard, lineSeries, {
    title: `${metricLabel(metric)} growth`,
    subtitle: `median across trials • ${mode === 'pct' ? 'percent' : 'absolute'}`,
    options: { yClampPct: mode === 'pct' },
  });
  renderFuzzerTable(section);

  const rows = (target.fuzzers || [])
    .map((fuzzer) => {
      const values = distributionValues(fuzzer, metric, mode).slice().sort((a, b) => a - b);
      if (!values.length) return null;
      return { label: fuzzer.fuzzer, values, median: median(values), color: fuzzerColor(fuzzer.fuzzer) };
    })
    .filter(Boolean)
    .sort((left, right) => (right.median ?? -1) - (left.median ?? -1));
  renderChartCard(coverage.distCard, {
    kind: 'distribution',
    rows,
    options: { mode },
    title: `${metricLabel(metric)} distribution`,
    subtitle: `Final snapshot • ${mode === 'pct' ? 'percent' : 'absolute'}`,
  });

  const metricName = metricLabel(metric).toLowerCase();
  renderCoverageComparison(section);
  if (coverage.relCard) {
    const relcovMatrix = resolveCoverageMatrix(target.relcov_matrix, metric);
    renderMatrixCard(coverage.relCard, relcovMatrix, {
      formatter: 'pct',
      emptyMessage: 'No relative coverage matrix data.',
      tint: 'rgba(110,226,240,ALPHA)',
      title: `RelCov ${metricName} matrix`,
      subtitle: relcovMatrix?.uses_aggregate_fallback
        ? 'Per-trial sets are unavailable for some fuzzers; aggregate coverage fallback is shown.'
        : 'Cell = how much of the column fuzzer union coverage is also covered by the row fuzzer.',
      exportName: `${section.target.key}-relcov-${metric}-matrix`,
    });
  }
}

function renderPerformanceBlock(section) {
  const { target, performance } = section;
  const corpusSeries = buildCurveSeries(target.fuzzers, 'corpus_files_total');
  const execSeries = buildCurveSeries(target.fuzzers, 'execs_done');
  renderLineCard(performance.corpusCard, corpusSeries, { subtitle: 'median across trials' });
  renderLineCard(performance.execCard, execSeries, { subtitle: 'median across trials' });
}

function renderBugComparison(section) {
  const { target, bugsBlock } = section;
  if (!bugsBlock.pairwiseCard) return;
  renderMatrixCard(
    bugsBlock.pairwiseCard,
    comparisonMatrix(target.unique_bug_matrix, FM_APP.state.comparisonMode),
    {
      formatter: 'int',
      emptyMessage: FM_APP.state.comparisonMode === 'all'
        ? 'Strict per-trial unique bug data is unavailable.'
        : 'No pairwise unique bug data.',
      tint: 'rgba(255,116,143,ALPHA)',
      title: 'Pairwise unique bug matrix',
      subtitle: FM_APP.state.comparisonMode === 'all'
        ? 'Cell = bugs found in every row-fuzzer trial but no column-fuzzer trial.'
        : 'Cell = bugs found in any row-fuzzer trial but no column-fuzzer trial.',
      exportName: `${section.target.key}-pairwise-unique-bug-matrix`,
    },
  );
}

function renderBugBlock(section) {
  const { target, bugsBlock } = section;
  const uniqueSeries = buildCurveSeries(target.fuzzers, 'unique_bugs_total');
  const crashSeries = buildCurveSeries(target.fuzzers, 'crashes_total');
  renderLineCard(bugsBlock.growthCard, uniqueSeries, { subtitle: 'median across trials' });
  renderLineCard(bugsBlock.crashesCard, crashSeries, { subtitle: 'median across trials' });
  if (bugsBlock.matrixCard) renderUniqueBugTable(bugsBlock.matrixCard.body, target.unique_bug_table || null);
  renderBugComparison(section);
  if (bugsBlock.relCard) {
    renderMatrixCard(bugsBlock.relCard, target.relbug_matrix || null, {
      formatter: 'pct',
      emptyMessage: 'No relative bug matrix data.',
      tint: 'rgba(255,116,143,ALPHA)',
    });
  }
}

function renderResourceTelemetryBlock(section) {
  const { target, resourceTelemetry } = section;
  if (!resourceTelemetry) return;
  const memorySeries = buildCurveSeries(target.fuzzers, 'resource_memory_mib');
  const diskSeries = buildCurveSeries(target.fuzzers, 'resource_corpus_disk_mib');
  renderLineCard(resourceTelemetry.memoryCard, memorySeries, { subtitle: 'median across trials (MiB)' });
  renderLineCard(resourceTelemetry.diskCard, diskSeries, { subtitle: 'median across trials (MiB)' });
}

function renderTrialTableBlock(section) {
  const tableSpec = section.trialTable;
  if (!tableSpec?.body) return;

  const rows = (section.target.fuzzers || [])
    .flatMap((fuzzer) => (fuzzer.trials || []).map((trial) => ({ ...trial, _fuzzer: fuzzer.fuzzer })))
    .sort((left, right) => {
      const fuzzerCmp = String(left._fuzzer || '').localeCompare(String(right._fuzzer || ''));
      if (fuzzerCmp) return fuzzerCmp;
      return Number(left.rep || 0) - Number(right.rep || 0);
    })
    .map((trial) => ({
      c0: String(trial._fuzzer || '—'),
      c1: String(trial.origin || 'fresh'),
      c2: formatGroupedNumber(trial.rep, { maximumFractionDigits: 0 }),
      c3: formatDuration(trial.elapsed_seconds),
      c4: trial.execs_per_sec == null ? '—' : formatGroupedNumber(trial.execs_per_sec, { maximumFractionDigits: 1 }),
      c5: formatGroupedNumber(trial.regions_cov, { maximumFractionDigits: 0 }),
      c6: formatGroupedNumber(trial.branches_cov, { maximumFractionDigits: 0 }),
      c7: trial.convergence_pct == null ? '—' : fmtPct(trial.convergence_pct, 1),
      c8: trial.execs_done == null ? '—' : formatGroupedNumber(per10kExec(trial.branches_cov, trial.execs_done), { maximumFractionDigits: 1 }),
    }));
  renderDataTable(tableSpec.body, tableSpec.columns, rows);
}

function renderStatisticsBlock(section) {
  const { target, statistics } = section;
  if (!statistics) return;
  // Final coverage is comparable only between trials that ran equally long, e.g. not mid-run with trial waves.
  const elapsed = cleanFloats((target.fuzzers || [])
    .flatMap((fuzzer) => (fuzzer.trials || []).map((trial) => trial.elapsed_seconds)));
  const runtimeNote = elapsed.length && Math.min(...elapsed) < 0.9 * Math.max(...elapsed)
    ? ` Trials ran for different times (${formatDuration(Math.min(...elapsed))} to `
      + `${formatDuration(Math.max(...elapsed))}); treat significance as provisional.`
    : '';
  const pairs = (target.fuzzers || []).length * ((target.fuzzers || []).length - 1) / 2;
  renderMatrixCard(statistics.mwuCard, resolveCoverageMatrix(target.branch_mwu_matrix, 'branches'), {
    formatter: 'float',
    fractionDigits: 4,
    emptyMessage: 'No branch Mann-Whitney U data.',
    styleForValue: branchPValueCellStyle,
    title: 'Branch MWU p-value matrix',
    subtitle: 'Green cells mark nominal p <= 0.05 per pair on final per-trial branch coverage, without '
      + `multiple-testing correction; with ${pairs} pairs, about ${fmt(0.05 * pairs, 2)} cells can turn green `
      + `by chance. Comparable only between trials of equal runtime.${runtimeNote}`,
    exportName: `${section.target.key}-branch-mwu-pvalue-matrix`,
  });
  renderMatrixCard(statistics.a12Card, resolveCoverageMatrix(target.branch_a12_matrix, 'branches'), {
    formatter: 'float',
    fractionDigits: 3,
    emptyMessage: 'No branch Vargha-Delaney A12 data.',
    styleForValue: branchA12CellStyle,
    title: 'Branch Vargha-Delaney A12 matrix',
    subtitle: 'Effect sizes on final per-trial branch coverage. Cells above 0.5 favor the row fuzzer, '
      + `cells below 0.5 favor the column fuzzer.${runtimeNote}`,
    exportName: `${section.target.key}-branch-a12-matrix`,
  });
}
function createTargetSection(target) {
  const targetId = sanitizeId(target.key);
  const sectionEl = fromTemplate('tplTargetSection');
  sectionEl.id = `t-${targetId}`;
  sectionEl.classList.add('report-target');
  part(sectionEl, 'title').textContent = target.key;
  part(sectionEl, 'title').classList.add('target-banner-title');
  part(sectionEl, 'subtitle').classList.add('target-banner-subtitle');
  if (target.aggregate_coverage_report) {
    const subtitle = part(sectionEl, 'subtitle');
    subtitle.textContent = '';
    subtitle.appendChild(aLink('aggregated coverage report', target.aggregate_coverage_report));
  }
  const header = sectionEl.querySelector('.card-header');
  header?.classList.add('target-banner');
  const titleHost = part(sectionEl, 'title').parentElement;
  if (target.provenance_warning && titleHost) {
    titleHost.appendChild(el('div', 'provenance-warning', target.provenance_warning));
  }
  if ((target.provenance_badges || []).length && titleHost) {
    const badges = el('div', 'row provenance-badges');
    (target.provenance_badges || []).forEach((badge) => {
      badges.appendChild(el(
        'span',
        `badge provenance-status-${badge.status || 'unavailable'}`,
        `${badge.fuzzer}: ${badge.label}`,
      ));
    });
    titleHost.appendChild(badges);
  }

  const section = {
    target,
    el: sectionEl,
    coverageState: { ...(FM_APP.state.coverageByTarget.get(target.key) || { metric: defaultCoverageMetric(target), value: 'abs' }) },
    tableSort: FM_APP.state.targetTableSort.get(target.key) || { key: 'branches_union', direction: 'desc' },
    renderCoverage() { renderCoverageBlock(section); },
    renderPerformance() { renderPerformanceBlock(section); },
    renderBugs() { renderBugBlock(section); },
    renderResourceTelemetry() { renderResourceTelemetryBlock(section); },
    renderStatistics() { renderStatisticsBlock(section); },
    renderTrials() { renderTrialTableBlock(section); },
    renderAll() {
      renderCoverageBlock(section);
      renderPerformanceBlock(section);
      renderBugBlock(section);
      if (section.resourceTelemetry) renderResourceTelemetryBlock(section);
      renderStatisticsBlock(section);
      renderTrialTableBlock(section);
    },
    renderComparisons() {
      renderFuzzerTable(section);
      renderCoverageComparison(section);
      renderBugComparison(section);
    },
  };

  const fuzzerTable = createFuzzerTable(section);
  section.fuzzerTable = fuzzerTable;
  installTargetTableSorting(section);
  const targetTableExport = part(sectionEl, 'target-table-export');
  const targetTableExportHost = targetTableExport.parentElement;

  const blocks = part(sectionEl, 'blocks');
  // A plugin section belongs to the fuzzer entry that carries it.
  const combinedExtraSections = (target.fuzzers || []).flatMap((fuzzer) => (fuzzer.extra_sections || [])
    .map((extraSection) => ({ ...extraSection, owner_fuzzer: fuzzer.fuzzer })));
  const trialSummaryBlock = createSummaryTableBlock(section, targetTableExport);
  trialSummaryBlock.id = `t-${targetId}-summary`;
  targetTableExportHost?.remove();
  installElementExportMenu(targetTableExport, fuzzerTable.table, () => `${section.target.key}-fuzzer-table`);
  const coverageBlock = createCoverageBlock(section);
  coverageBlock.id = `t-${targetId}-coverage`;
  const performanceBlock = createPerformanceBlock(section);
  performanceBlock.id = `t-${targetId}-throughput`;
  const bugBlock = createBugBlock(section);
  bugBlock.id = `t-${targetId}-bugs`;
  const resourceTelemetryBlock = hasResourceTelemetry(target) ? createResourceTelemetryBlock(section) : null;
  if (resourceTelemetryBlock) resourceTelemetryBlock.id = `t-${targetId}-telemetry`;
  const perTrialBlock = createTrialTableBlock(section);
  perTrialBlock.id = `t-${targetId}-trials`;
  const customMetricsBlock = createCustomMetricsBlock(combinedExtraSections);
  if (customMetricsBlock) customMetricsBlock.id = `t-${targetId}-custom`;
  const debugBlock = createDebugBlock(target);
  if (debugBlock) debugBlock.id = `t-${targetId}-debug`;
  const statisticsBlock = createStatisticsBlock(section);
  if (statisticsBlock) statisticsBlock.id = `t-${targetId}-statistics`;
  blocks.appendChild(trialSummaryBlock);
  blocks.appendChild(coverageBlock);
  blocks.appendChild(performanceBlock);
  blocks.appendChild(bugBlock);
  if (resourceTelemetryBlock) blocks.appendChild(resourceTelemetryBlock);
  blocks.appendChild(perTrialBlock);
  if (customMetricsBlock) blocks.appendChild(customMetricsBlock);
  if (statisticsBlock) blocks.appendChild(statisticsBlock);
  if (debugBlock) blocks.appendChild(debugBlock);

  section.navItems = [
    ['Summary', `#t-${targetId}-summary`],
    ['Coverage', `#t-${targetId}-coverage`],
    ['Throughput', `#t-${targetId}-throughput`],
    ['Bug finding', `#t-${targetId}-bugs`],
    resourceTelemetryBlock ? ['Telemetry', `#t-${targetId}-telemetry`] : null,
    ['Trials', `#t-${targetId}-trials`],
    customMetricsBlock ? ['Custom metrics', `#t-${targetId}-custom`] : null,
    statisticsBlock ? ['Statistics', `#t-${targetId}-statistics`] : null,
    debugBlock ? ['Debug', `#t-${targetId}-debug`] : null,
  ].filter(Boolean).map(([label, selector]) => ({ label, selector }));

  return section;
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Shared browser helpers for composite measurement payloads.
 */
function measurementKey(measurement) {
  return measurement?.key || measurement || {};
}
function measurementId(measurement) {
  const key = measurementKey(measurement);
  return measurement?.id || key.id || [
    key.source_id,
    key.run_id,
    key.fuzzer,
    key.benchmark,
    key.fuzz_target,
  ].filter(Boolean).join(':');
}
function measurementTitle(measurement, fallback = '—') {
  const key = measurementKey(measurement);
  return `${key.benchmark || fallback} / ${key.fuzz_target || fallback} / ${key.fuzzer || fallback}`;
}
function measurementSelection(measurement, origin) {
  return { key: measurementKey(measurement), origin };
}
function formatSourceFacts(source, formatDuration, fmtInt) {
  const facts = [];
  if (source.runtime_seconds != null) facts.push(`runtime ${formatDuration(source.runtime_seconds)}`);
  if (source.repetitions != null) facts.push(`repetitions ${fmtInt(source.repetitions)}`);
  const fuzzerInfo = source.metadata?.source?.fuzzer_version;
  if (fuzzerInfo && Object.keys(fuzzerInfo).length) facts.push('fuzzer info');
  return facts.join(' · ') || 'metadata only';
}
function invalidSourceText(source) {
  return `${source?.source_id || 'source'}: ${source?.error || 'Unknown discovery error.'}`;
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Controls temporary composite report view selection on dynamic reports.
 */


const COMPOSITE_STATE = {
  measurements: [],
  invalidSources: [],
  selected: new Set(),
  reloadReport: null,
};

function canUseCompositeApi() {
  return !window.FM_STATIC_DATA && Boolean(window.FM_RUN_ID || window.FM_VIEW_ID);
}

async function apiJSON(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${url}: ${response.status}`);
  }
  return response.json();
}

function setStatus(message) {
  const status = byId('compositeStatus');
  if (status) status.textContent = message || '';
}

function showModal(show) {
  const modal = byId('compositeModal');
  if (!modal) return;
  modal.classList.toggle('hidden', !show);
  modal.setAttribute('aria-hidden', show ? 'false' : 'true');
}

function setCurrentViewId(viewId) {
  window.FM_VIEW_ID = viewId || '';
  window.FM_DATA_URL = window.FM_VIEW_ID
    ? `/api/composite/views/${encodeURIComponent(window.FM_VIEW_ID)}/data`
    : (window.FM_RUN_ID ? `/api/run/${encodeURIComponent(window.FM_RUN_ID)}/data` : 'data.json');
  if (window.FM_RUN_ID && window.FM_VIEW_ID) {
    const url = new URL(window.location.href);
    url.searchParams.set('view', window.FM_VIEW_ID);
    window.history.replaceState({}, '', url);
  }
}

async function ensureView() {
  if (window.FM_VIEW_ID) return window.FM_VIEW_ID;
  if (!window.FM_RUN_ID) throw new Error('Open an active run before adding measurements.');
  const view = await apiJSON(`/api/composite/views/from-run/${encodeURIComponent(window.FM_RUN_ID)}`, {
    method: 'POST',
  });
  setCurrentViewId(view.view_id);
  return view.view_id;
}

function renderMeasurementOptions() {
  const host = byId('compositeMeasurementOptions');
  if (!host) return;
  host.textContent = '';
  if (!COMPOSITE_STATE.measurements.length) {
    host.appendChild(el(
      'div',
      'matrix-empty',
      'No measurements with composite metadata found. Runs created before composite descriptors were introduced appear as invalid sources.',
    ));
  }
  COMPOSITE_STATE.measurements.forEach((measurement) => {
    const id = measurementId(measurement);
    const key = measurementKey(measurement);
    const row = el('label', 'composite-option');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = COMPOSITE_STATE.selected.has(id);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) COMPOSITE_STATE.selected.add(id);
      else COMPOSITE_STATE.selected.delete(id);
      syncAddButton();
    });
    row.appendChild(checkbox);
    const body = el('div', 'composite-option-body');
    body.appendChild(el('div', 'composite-option-title', measurementTitle(measurement, '-')));
    body.appendChild(el('div', 'muted small', `Run ${key.run_id || '-'} · Source ${key.source_id || '-'} · ${formatSourceFacts(measurement, formatDuration, fmtInt)}`));
    row.appendChild(body);
    host.appendChild(row);
  });
  if (COMPOSITE_STATE.invalidSources.length) {
    const invalidList = el('div', 'invalid-source-list');
    COMPOSITE_STATE.invalidSources.forEach((source) => {
      invalidList.appendChild(el('div', 'invalid-source-row', invalidSourceText(source)));
    });
    host.appendChild(invalidList);
  }
  syncAddButton();
}

function syncAddButton() {
  const button = byId('compositeAddSelected');
  if (button) button.disabled = COMPOSITE_STATE.selected.size === 0;
}

async function loadMeasurements() {
  setStatus('Loading measurements...');
  const data = await apiJSON('/api/composite/sources/refresh', { method: 'POST' });
  COMPOSITE_STATE.measurements = data.measurements || [];
  COMPOSITE_STATE.invalidSources = data.invalid_sources || [];
  renderMeasurementOptions();
  setStatus(`${COMPOSITE_STATE.measurements.length} measurements. ${COMPOSITE_STATE.invalidSources.length} invalid source(s).`);
}

async function addSelectedMeasurements() {
  const selected = new Set(COMPOSITE_STATE.selected);
  const measurements = COMPOSITE_STATE.measurements.filter((measurement) => selected.has(measurementId(measurement)));
  if (!measurements.length) return;
  const button = byId('compositeAddSelected');
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = 'Adding...';
  }
  try {
    const viewId = await ensureView();
    await apiJSON(`/api/composite/views/${encodeURIComponent(viewId)}/measurements`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        measurements: measurements.map((measurement) => measurementSelection(measurement, 'historical')),
      }),
    });
    COMPOSITE_STATE.selected.clear();
    showModal(false);
    await COMPOSITE_STATE.reloadReport?.();
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}
function installCompositeControls(reloadReport) {
  COMPOSITE_STATE.reloadReport = reloadReport;
  const button = byId('compositeAddToggle');
  const close = byId('compositeModalClose');
  const add = byId('compositeAddSelected');
  if (!button || button.dataset.bound === '1') return;
  button.hidden = !canUseCompositeApi();
  button.addEventListener('click', async () => {
    showModal(true);
    try {
      await loadMeasurements();
    } catch (error) {
      setStatus(String(error));
    }
  });
  close?.addEventListener('click', () => showModal(false));
  add?.addEventListener('click', () => {
    addSelectedMeasurements().catch((error) => setStatus(String(error)));
  });
  byId('compositeRefreshSources')?.addEventListener('click', async () => {
    try {
      await loadMeasurements();
    } catch (error) {
      setStatus(String(error));
    }
  });
  button.dataset.bound = '1';
}

/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Boots the interactive report page and wires global controls.
 */








function updateSummarySortIndicators() {
  document.querySelectorAll('[data-sort-arrow]').forEach((node) => {
    const key = node.getAttribute('data-sort-arrow');
    const active = key === FM_APP.state.summarySort.key;
    node.textContent = active ? (FM_APP.state.summarySort.direction === 'asc' ? '▲' : '▼') : '';
    node.parentElement?.classList.toggle('active', active);
  });
}

function installSummarySorting(redraw) {
  document.querySelectorAll('[data-sort-key]').forEach((button) => {
    if (button.dataset.bound === '1') return;
    button.addEventListener('click', () => {
      const key = button.getAttribute('data-sort-key') || 'coverage_score';
      if (FM_APP.state.summarySort.key === key) {
        FM_APP.state.summarySort.direction = FM_APP.state.summarySort.direction === 'asc' ? 'desc' : 'asc';
      } else {
        FM_APP.state.summarySort = { key, direction: 'desc' };
      }
      redraw();
    });
    button.dataset.bound = '1';
  });
}

function installRankingExport() {
  if (byId('rankingExport')) return;
  const table = document.querySelector('.ranking-table');
  const controls = byId('summaryPanelActions');
  if (!table || !controls) return;

  const button = el('button', 'btn', 'Export');
  button.id = 'rankingExport';
  button.type = 'button';
  controls.appendChild(button);
  installElementExportMenu(button, table, 'fuzzer-ranking');
}

function hasPairwiseRankingScores(data) {
  return (data.summary?.rankings || []).some((row) => (
    isFiniteNumber(row.relcov_score) || isFiniteNumber(row.relbug_score)
  ));
}

function syncPairwiseRankingColumns(data) {
  const visible = hasPairwiseRankingScores(data);
  document.querySelectorAll('[data-sort-key="relcov_score"], [data-sort-key="relbug_score"]').forEach((button) => {
    const header = button.closest('th');
    if (header) header.hidden = !visible;
  });
  if (!visible && ['relcov_score', 'relbug_score'].includes(FM_APP.state.summarySort.key)) {
    FM_APP.state.summarySort = { key: 'coverage_score', direction: 'desc' };
  }
  return visible;
}

function buildSummaryRows(data) {
  const rankingsBody = byId('tblRankings');
  rankingsBody.textContent = '';
  const scope = byId('rankingScope');
  const unranked = data.summary?.unranked_targets || [];
  scope.textContent = '';
  scope.hidden = !unranked.length;
  if (unranked.length) {
    const rankedCount = (data.summary?.ranked_target_keys || []).length;
    scope.append(
      `Ranked on ${rankedCount} of ${rankedCount + unranked.length} visible targets that every visible fuzzer ran. Not ranked: `,
    );
    unranked.forEach((target, index) => {
      const link = el('a', null, target.key);
      link.href = `#t-${sanitizeId(target.key)}`;
      scope.append(index ? ', ' : '', link, ` (not run by ${target.missing.join(', ')})`);
    });
    scope.append('.');
  }
  const showPairwiseColumns = syncPairwiseRankingColumns(data);

  const rows = [...(data.summary?.rankings || [])].sort((left, right) => (
    compareNumericRows(left, right, FM_APP.state.summarySort.key, FM_APP.state.summarySort.direction)
  ));

  rows.forEach((row) => {
    const tr = el('tr');
    const nameCell = el('td');
    const nameRow = el('div', 'fuzzer-name');
    const swatch = el('span', 'legend-swatch');
    swatch.style.background = fuzzerColor(row.fuzzer);
    nameRow.appendChild(swatch);
    nameRow.appendChild(el('div', null, row.fuzzer));
    nameCell.appendChild(nameRow);
    tr.appendChild(nameCell);
    tr.appendChild(el('td', 'num', row.coverage_score === null ? '—' : fmt(row.coverage_score, 2)));
    tr.appendChild(el('td', 'num', row.auc_score === null ? '—' : fmt(row.auc_score, 2)));
    const relcovCell = el('td', 'num', row.relcov_score === null ? '—' : fmt(row.relcov_score, 2));
    relcovCell.hidden = !showPairwiseColumns;
    tr.appendChild(relcovCell);
    tr.appendChild(el(
      'td',
      'num',
      formatComparisonCount(row.exclusive_coverage_count, row.exclusive_coverage_count_bound),
    ));
    const relbugCell = el('td', 'num', row.relbug_score === null ? '—' : fmt(row.relbug_score, 2));
    relbugCell.hidden = !showPairwiseColumns;
    tr.appendChild(relbugCell);
    tr.appendChild(el('td', 'num', fmtInt(row.unique_bug_count)));
    tr.appendChild(el(
      'td',
      'num',
      formatComparisonCount(row.exclusive_bug_count, row.exclusive_bug_count_bound),
    ));
    tr.appendChild(el('td', 'num', formatExecCount(row.median_execs_done)));
    rankingsBody.appendChild(tr);
  });

  updateSummarySortIndicators();
  installRankingExport();
}

function formatComparisonCount(value, bound) {
  if (!isFiniteNumber(value)) return '—';
  if (bound === 'lower') return `≥${fmtInt(value)}`;
  if (bound === 'upper') return `≤${fmtInt(value)}`;
  if (bound === 'indeterminate') return `~${fmtInt(value)}`;
  return fmtInt(value);
}

function bestRowByKey(rows, key) {
  return [...rows]
    .filter((row) => isFiniteNumber(row?.[key]))
    .sort((left, right) => compareNumericRows(left, right, key, 'desc'))[0] || null;
}

function summarizeTargetMetric(targets, extractor) {
  const valuesByFuzzer = new Map();
  targets.forEach((target) => {
    (target.fuzzers || []).forEach((entry) => {
      const value = extractor(entry);
      if (!isFiniteNumber(value)) return;
      const bucket = valuesByFuzzer.get(entry.fuzzer) || [];
      bucket.push(Number(value));
      valuesByFuzzer.set(entry.fuzzer, bucket);
    });
  });
  return Array.from(valuesByFuzzer.entries()).map(([fuzzer, values]) => ({
    fuzzer,
    value: median(values),
  }));
}

function winnerCard(title, description, winner, formatter) {
  const card = el('article', 'winner-card');
  const titleRow = el('div', 'winner-title-row');
  const titleStack = el('div', 'winner-title-stack');
  titleStack.appendChild(el('div', 'winner-tooltip-content', description));
  titleStack.appendChild(el('div', 'winner-title', title));
  titleRow.appendChild(titleStack);
  card.appendChild(titleRow);
  const value = el('div', 'winner-value');
  const valueRow = el('div', 'winner-value-row');
  const swatch = el('span', 'winner-swatch');
  swatch.style.background = fuzzerColor(winner.fuzzer);
  valueRow.appendChild(swatch);
  const text = el('div', 'winner-value-text');
  text.appendChild(el('div', null, winner.fuzzer));
  text.appendChild(el('div', 'muted small', formatter(winner.value, winner)));
  valueRow.appendChild(text);
  value.appendChild(valueRow);
  card.appendChild(value);
  return card;
}

function buildWinnerCards(data) {
  const host = byId('summaryHighlights');
  if (!host) return;
  host.textContent = '';

  const rankingRows = data.summary?.rankings || [];
  const rankedKeys = new Set(data.summary?.ranked_target_keys || []);
  const execRows = summarizeTargetMetric(
    (data.targets || []).filter((target) => rankedKeys.has(target.key)),
    (entry) => entry.final?.execs_per_sec_median,
  );
  const relCovRows = rankingRows.map((row) => ({ fuzzer: row.fuzzer, value: row.relcov_score }));
  const exclusiveCoverageRows = rankingRows.map((row) => ({
    fuzzer: row.fuzzer,
    value: row.exclusive_coverage_count,
    bound: row.exclusive_coverage_count_bound,
  }));

  const cards = [
    {
      title: 'Highest Coverage',
      description: 'Reaches the strongest final coverage level across targets.',
      winner: bestRowByKey(rankingRows.map((row) => ({ fuzzer: row.fuzzer, coverage_score: row.coverage_score })), 'coverage_score'),
      formatter: (value) => `${fmt(value, 2)} score`,
      key: 'coverage_score',
    },
    {
      title: 'Early Coverage',
      description: 'Reaches high branch coverage early: the highest coverage averaged over the whole run.',
      winner: bestRowByKey(rankingRows.map((row) => ({ fuzzer: row.fuzzer, auc_score: row.auc_score })), 'auc_score'),
      formatter: (value) => `${fmt(value, 2)} score`,
      key: 'auc_score',
    },
    {
      title: 'Distinct Coverage',
      description: 'Contributes branch coverage that other fuzzers miss.',
      winner: bestRowByKey(relCovRows.map((row) => ({ ...row, value: row.value })), 'value'),
      formatter: (value) => `${fmt(value, 2)} relcov score`,
      key: 'value',
    },
    {
      title: 'Exclusive Coverage',
      description: FM_APP.state.comparisonMode === 'all'
        ? 'Reaches the largest branch set in every trial that no other fuzzer reaches in any trial.'
        : 'Reaches the largest branch set in any trial that no other fuzzer reaches in any trial.',
      winner: bestRowByKey(exclusiveCoverageRows.map((row) => ({ ...row, value: row.value })), 'value'),
      formatter: (value, winner) => `${formatComparisonCount(value, winner.bound)} branches`,
      key: 'value',
    },
    {
      title: 'Most Bug Finder',
      description: 'Finds the largest total set of distinct bugs.',
      winner: bestRowByKey(rankingRows.map((row) => ({ fuzzer: row.fuzzer, unique_bug_count: row.unique_bug_count })), 'unique_bug_count'),
      formatter: (value) => `${fmtInt(value)} unique bugs`,
      key: 'unique_bug_count',
    },
    {
      title: 'Distinct Bug Finder',
      description: 'Finds bugs that are less commonly shared with other fuzzers.',
      winner: bestRowByKey(rankingRows.map((row) => ({ fuzzer: row.fuzzer, relbug_score: row.relbug_score })), 'relbug_score'),
      formatter: (value) => `${fmt(value, 2)} relbug score`,
      key: 'relbug_score',
    },
    {
      title: 'Fastest Executor',
      description: 'Pushes through the highest sustained execution speed.',
      winner: bestRowByKey(execRows.map((row) => ({ ...row, value: row.value })), 'value'),
      formatter: (value) => `${fmt(value, 1)} exec/sec median`,
      key: 'value',
    },
  ];

  cards.forEach((card) => {
    if (!card.winner) return;
    const value = card.key === 'value' ? card.winner.value : card.winner[card.key];
    if (!isFiniteNumber(value)) return;
    host.appendChild(winnerCard(card.title, card.description, { ...card.winner, value }, card.formatter));
  });
}

function comparisonSampleSizes(data) {
  return (data.targets || []).flatMap((target) => {
    const matrixSizes = target.unique_bug_matrix?.sample_sizes;
    if (Array.isArray(matrixSizes)) return cleanFloats(matrixSizes);
    return (target.fuzzers || []).map((entry) => (entry.trials || []).length);
  });
}

function syncComparisonModeControl(data) {
  const anyButton = byId('comparisonModeAny');
  const allButton = byId('comparisonModeAll');
  const sampleLabel = byId('comparisonModeSamples');
  if (!anyButton || !allButton || !sampleLabel) return;
  const sizes = comparisonSampleSizes(data).filter((value) => value >= 0);
  const minN = sizes.length ? Math.min(...sizes) : 0;
  const maxN = sizes.length ? Math.max(...sizes) : 0;
  const inert = maxN <= 1;
  if (inert) FM_APP.state.comparisonMode = 'any';
  anyButton.classList.toggle('active', FM_APP.state.comparisonMode === 'any');
  allButton.classList.toggle('active', FM_APP.state.comparisonMode === 'all');
  anyButton.setAttribute('aria-pressed', String(FM_APP.state.comparisonMode === 'any'));
  allButton.setAttribute('aria-pressed', String(FM_APP.state.comparisonMode === 'all'));
  allButton.disabled = inert;
  // A uniform repetition count says nothing a reader can act on. Only report it
  // when the toggle cannot do anything, or when the fuzzers are not equally
  // sampled and their counts are therefore not directly comparable.
  const uneven = minN !== maxN;
  sampleLabel.textContent = inert ? `n=${maxN}` : uneven ? `n=${minN}–${maxN}` : '';
  sampleLabel.title = inert
    ? 'Strict and non-strict comparisons are identical when n=1.'
    : uneven
      ? 'Fuzzers have different repetition counts, so their counts are not directly comparable.'
      : '';
}

function renderComparisonMode() {
  if (!FM_APP.data) return;
  syncComparisonModeControl(FM_APP.data);
  FM_APP.data.summary = computeSummary(FM_APP.data.targets || [], FM_APP.state.comparisonMode);
  buildSummaryRows(FM_APP.data);
  buildWinnerCards(FM_APP.data);
  FM_APP.sections.forEach((section) => section.renderComparisons());
}

function installComparisonModeControl() {
  const anyButton = byId('comparisonModeAny');
  const allButton = byId('comparisonModeAll');
  if (!anyButton || !allButton || anyButton.dataset.bound === '1') return;
  anyButton.addEventListener('click', () => {
    FM_APP.state.comparisonMode = 'any';
    renderComparisonMode();
  });
  allButton.addEventListener('click', () => {
    if (allButton.disabled) return;
    FM_APP.state.comparisonMode = 'all';
    renderComparisonMode();
  });
  anyButton.dataset.bound = '1';
  allButton.dataset.bound = '1';
}

function installActiveTargetTracking() {
  const content = document.querySelector('.content');
  const overviewPanel = byId('overviewPanel');
  if (!content || !overviewPanel) return;

  FM_APP.activeNavCleanup?.();
  const sectionStates = new Map();
  const applyActiveKey = () => {
    const visible = Array.from(sectionStates.entries())
      .filter(([, state]) => state.isIntersecting)
      .sort((left, right) => {
        const topDelta = Math.abs(left[1].top) - Math.abs(right[1].top);
        if (topDelta !== 0) return topDelta;
        return right[1].ratio - left[1].ratio;
      });
    const activeKey = visible[0]?.[0] || 'overview';
    document.querySelectorAll('[data-nav-key]').forEach((node) => {
      node.classList.toggle('active', node.dataset.navKey === activeKey);
    });
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const key = entry.target.getAttribute('data-nav-section') || 'overview';
      sectionStates.set(key, {
        isIntersecting: entry.isIntersecting,
        ratio: entry.intersectionRatio,
        top: entry.boundingClientRect.top,
      });
    });
    applyActiveKey();
  }, {
    root: content,
    rootMargin: '-72px 0px -55% 0px',
    threshold: [0, 0.1, 0.25, 0.5, 0.75, 1],
  });

  overviewPanel.setAttribute('data-nav-section', 'overview');
  observer.observe(overviewPanel);
  FM_APP.sections.forEach((section) => {
    section.el.setAttribute('data-nav-section', section.target.key);
    observer.observe(section.el);
  });
  applyActiveKey();
  FM_APP.activeNavCleanup = () => {
    observer.disconnect();
  };
}

function installSidebarNavigation() {
  const content = document.querySelector('.content');
  if (!content) return;
  const offset = 76;
  document.querySelectorAll('a[data-scroll-target]').forEach((node) => {
    if (node.dataset.bound === '1') return;
    node.addEventListener('click', (event) => {
      event.preventDefault();
      const target = document.querySelector(node.dataset.scrollTarget || '');
      if (!target) return;
      const targetTop = target.getBoundingClientRect().top - content.getBoundingClientRect().top + content.scrollTop - offset;
      content.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' });
    });
    node.dataset.bound = '1';
  });
}

function renderMeasurementProvenance(data) {
  const provenance = data.measurement_provenance || {};
  const summary = byId('measurementProvenanceSummary');
  const warning = byId('measurementProvenanceWarning');
  const rows = byId('measurementProvenanceRows');
  if (!summary || !warning || !rows) return;
  summary.textContent = `${provenance.record_count || 0} coverage series • ${provenance.consistency || 'unavailable'}`;
  warning.textContent = provenance.warning || '';
  warning.hidden = !provenance.warning;
  rows.textContent = '';
  (provenance.threats_table || []).forEach((entry) => {
    const row = el('tr');
    row.appendChild(el('td', null, entry.field || '—'));
    row.appendChild(el('td', `provenance-status-${entry.status || 'unavailable'}`, entry.status || 'unavailable'));
    row.appendChild(el('td', entry.affected ? 'provenance-status-deviation' : null, entry.affected ? 'yes' : 'no'));
    row.appendChild(el('td', null, (entry.values || []).join(', ') || 'unavailable'));
    row.appendChild(el('td', 'muted small', entry.threat || ''));
    rows.appendChild(row);
  });
}

function renderView(data) {
  syncComparisonModeControl(data);
  data.summary = computeSummary(data.targets || [], FM_APP.state.comparisonMode);
  FM_APP.data = data;
  const meta = data.meta || {};
  const overview = data.overview || {};
  const subtitleParts = [];
  if (overview.elapsed_human) {
    subtitleParts.push(`fuzzing time ${overview.elapsed_human}`);
    if (overview.wall_elapsed_human) subtitleParts.push(`wall time ${overview.wall_elapsed_human}`);
  } else if (overview.created_at || meta.generated_at) subtitleParts.push(overview.created_at || meta.generated_at);
  // Put the run id last so a narrow header truncates the id, not the times.
  subtitleParts.push(meta.run_id || overview.run_id || 'run');
  byId('runSubtitle').textContent = subtitleParts.join(' • ');
  byId('runSubtitle').title = subtitleParts.join(' • ');
  const tickFailureWarning = byId('tickFailureWarning');
  const tickFailureMessage = tickFailureNotice(overview);
  tickFailureWarning.textContent = tickFailureMessage || '';
  tickFailureWarning.hidden = !tickFailureMessage;
  renderMeasurementProvenance(data);

  buildSummaryRows(data);
  buildWinnerCards(data);

  const tocOverview = byId('tocOverview');
  const tocTargets = byId('tocTargets');
  const targetsRoot = byId('targets');
  tocOverview.textContent = '';
  tocTargets.textContent = '';
  targetsRoot.textContent = '';
  FM_APP.sections = [];

  const rankingItem = el('a', null, 'Overview');
  rankingItem.href = '#overviewPanel';
  rankingItem.dataset.navKey = 'overview';
  rankingItem.dataset.scrollTarget = '#overviewPanel';
  tocOverview.appendChild(rankingItem);

  if (!(data.targets || []).length) {
    targetsRoot.appendChild(el('div', 'muted', 'No targets match the current filters.'));
  }

  (data.targets || []).forEach((target) => {
    const section = createTargetSection(target);
    FM_APP.sections.push(section);
    const tocGroup = el('div', 'toc-group');
    const tocItem = el('a', null, target.key);
    tocItem.href = `#t-${sanitizeId(target.key)}`;
    tocItem.dataset.navKey = target.key;
    tocItem.dataset.scrollTarget = `#t-${sanitizeId(target.key)}`;
    tocGroup.appendChild(tocItem);
    const subnav = el('div', 'toc-subnav');
    (section.navItems || []).forEach((entry) => {
      const subItem = el('a', 'toc-subitem', entry.label);
      subItem.href = entry.selector;
      subItem.dataset.scrollTarget = entry.selector;
      subnav.appendChild(subItem);
    });
    tocGroup.appendChild(subnav);
    tocTargets.appendChild(tocGroup);
    targetsRoot.appendChild(section.el);
  });

  FM_APP.sections.forEach((section) => section.renderAll());
  installSidebarNavigation();
  installActiveTargetTracking();
  applySearch();
}

function renderFromState() {
  if (!FM_APP.rawData) return;
  renderFuzzerFilterOptions(FM_APP.rawData, renderFromState);
  renderBenchmarkFilterOptions(FM_APP.rawData, renderFromState);
  const derived = deriveReportData(FM_APP.rawData, selectedFuzzerNames());
  renderView(derived);
}

async function render() {
  const data = window.FM_STATIC_DATA || await fetchJSON(window.FM_DATA_URL && window.FM_DATA_URL.length ? window.FM_DATA_URL : 'data.json');
  FM_APP.rawData = data;
  assignFuzzerColors(data);
  installFuzzerFilter(data, renderFromState);
  installBenchmarkFilter(data, renderFromState);
  installSummarySorting(renderFromState);
  installComparisonModeControl();
  FM_APP.redrawCharts = redrawCharts;
  byId('searchBox').oninput = applySearch;
  byId('themeToggle').onclick = () => applyTheme(FM_APP.state.theme === 'light' ? 'dark' : 'light');

  window.addEventListener('resize', debounce(redrawCharts, 120));
  applyTheme(preferredTheme());
  renderFromState();
  installCompositeControls(async () => {
    const previous = FM_APP.rawData;
    const next = await fetchJSON(window.FM_DATA_URL && window.FM_DATA_URL.length ? window.FM_DATA_URL : 'data.json');
    selectNewFilterEntries(previous, next);
    FM_APP.rawData = next;
    assignFuzzerColors(next);
    renderFromState();
  });
}

render().catch((error) => {
  console.error(error);
  const targetsRoot = byId('targets');
  if (targetsRoot) {
    targetsRoot.textContent = '';
    targetsRoot.appendChild(el('div', 'muted', String(error)));
  }
});
