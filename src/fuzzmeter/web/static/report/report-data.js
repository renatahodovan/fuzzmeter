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

import { FM_APP } from './state.js';

export function tickFailureNotice(overview) {
  const count = Number(overview?.failed_snapshot_ticks || 0);
  if (!Number.isFinite(count) || count <= 0) return null;
  return `Warning: ${count} snapshot tick${count === 1 ? '' : 's'} failed. Coverage and crash curves may contain unmeasured gaps.`;
}

export function comparisonMetric(stats, mode) {
  const strict = mode === 'all';
  const valueKey = strict ? 'exclusive_all' : 'exclusive_any';
  const boundKey = `${valueKey}_bound`;
  const value = stats?.[valueKey];
  if (value !== null && value !== undefined && Number.isFinite(Number(value))) {
    return {
      value: Number(value),
      bound: String(stats?.[boundKey] || 'exact'),
    };
  }
  if (!strict && stats?.total !== null && stats?.total !== undefined && Number.isFinite(Number(stats.total))) {
    return { value: Number(stats.total), bound: 'exact' };
  }
  return { value: null, bound: 'unknown' };
}

export function comparisonMatrix(matrixData, mode) {
  if (!matrixData) return null;
  const strict = mode === 'all';
  const matrixKey = strict ? 'pairwise_unique_all' : 'pairwise_unique_any';
  const boundsKey = `${matrixKey}_bounds`;
  const selected = Array.isArray(matrixData[matrixKey])
    ? matrixData[matrixKey]
    : (!strict && Array.isArray(matrixData.matrix) ? matrixData.matrix : []);
  const numericValues = selected.flat().filter((value) => (
    value !== null && value !== undefined && Number.isFinite(Number(value))
  )).map(Number);
  return {
    ...matrixData,
    matrix: selected,
    cell_bounds: Array.isArray(matrixData[boundsKey]) ? matrixData[boundsKey] : undefined,
    max_value: Math.max(0, ...numericValues),
    comparison_mode: strict ? 'all' : 'any',
  };
}

export const FM_PALETTE = [
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

export const COVERAGE_METRICS = [
  ['branches', 'Branch coverage'],
  ['lines', 'Line coverage'],
  ['functions', 'Function coverage'],
  ['regions', 'Region coverage'],
];

export const MATRIX_PAYLOAD_KEYS = Object.freeze({
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

export const VALUE_OPTIONS = [['abs', 'Absolute'], ['pct', 'Percent']];

export function pctValue(covered, total) {
  if (
    covered == null ||
    total == null ||
    !Number.isFinite(Number(covered)) ||
    !Number.isFinite(Number(total)) ||
    Number(total) <= 0
  ) {
    return null;
  }
  return 100 * Number(covered) / Number(total);
}

export function metricLabel(metric) {
  const found = COVERAGE_METRICS.find(([value]) => value === metric);
  return found ? found[1] : 'Coverage';
}

export function hashString(value) {
  let hash = 2166136261;
  const text = String(value || '');
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function fuzzerColor(label) {
  const mapped = FM_APP.state.fuzzerColors.get(String(label || ''));
  if (mapped) return mapped;
  const idx = hashString(label) % FM_PALETTE.length;
  return FM_PALETTE[idx];
}

export function assignFuzzerColors(data) {
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

export function buildCoverageSeries(fuzzers, metric, mode) {
  const coveredKey = `${metric}_cov_median`;
  const lowCoveredKey = `${metric}_cov_min`;
  const highCoveredKey = `${metric}_cov_max`;
  const pctKey = `${metric}_pct_median`;
  const lowPctKey = `${metric}_pct_min`;
  const highPctKey = `${metric}_pct_max`;

  return (fuzzers || []).map((fuzzer) => {
    const baseline = fuzzer.seed_baseline || {};
    const curve = fuzzer.curve || [];
    const elapsedValues = curve.map((point) => Number(point.elapsed_s)).filter((value) => Number.isFinite(value));
    const baselineY = mode === 'pct'
      ? pctValue(baseline[`cov_${metric}_covered`], baseline[`cov_${metric}_total`])
      : (Number.isFinite(Number(baseline[`cov_${metric}_covered`])) ? Number(baseline[`cov_${metric}_covered`]) : null);
    return {
      label: fuzzer.fuzzer,
      color: fuzzerColor(fuzzer.fuzzer),
      baselineY,
      usesElapsed: elapsedValues.length > 0,
      points: curve
        .map((point) => ({
          x: Number.isFinite(Number(point.elapsed_s)) ? Number(point.elapsed_s) : Number(point.idx),
          y: mode === 'pct'
            ? (Number.isFinite(Number(point[pctKey])) ? Number(point[pctKey]) : null)
            : (Number.isFinite(Number(point[coveredKey])) ? Number(point[coveredKey]) : null),
          lo: mode === 'pct'
            ? (Number.isFinite(Number(point[lowPctKey])) ? Number(point[lowPctKey]) : null)
            : (Number.isFinite(Number(point[lowCoveredKey])) ? Number(point[lowCoveredKey]) : null),
          hi: mode === 'pct'
            ? (Number.isFinite(Number(point[highPctKey])) ? Number(point[highPctKey]) : null)
            : (Number.isFinite(Number(point[highCoveredKey])) ? Number(point[highCoveredKey]) : null),
          idx: Number.isFinite(Number(point.idx)) ? Number(point.idx) : null,
          ts: Number.isFinite(Number(point.ts_median)) ? Number(point.ts_median) : null,
          tooltipLabel: point.t || null,
        }))
        .filter((point) => point.y != null && Number.isFinite(point.y)),
    };
  });
}

export function buildCurveSeries(fuzzers, baseKey) {
  const centerKey = `${baseKey}_median`;
  const lowKey = `${baseKey}_min`;
  const highKey = `${baseKey}_max`;
  return (fuzzers || []).map((fuzzer) => {
    const curve = fuzzer.curve || [];
    const elapsedValues = curve.map((point) => Number(point.elapsed_s)).filter((value) => Number.isFinite(value));
    return {
      label: fuzzer.fuzzer,
      color: fuzzerColor(fuzzer.fuzzer),
      usesElapsed: elapsedValues.length > 0,
      points: curve
        .map((point) => ({
          x: Number.isFinite(Number(point.elapsed_s)) ? Number(point.elapsed_s) : Number(point.idx),
          y: Number.isFinite(Number(point[centerKey])) ? Number(point[centerKey]) : null,
          lo: Number.isFinite(Number(point[lowKey])) ? Number(point[lowKey]) : null,
          hi: Number.isFinite(Number(point[highKey])) ? Number(point[highKey]) : null,
          idx: Number.isFinite(Number(point.idx)) ? Number(point.idx) : null,
          ts: Number.isFinite(Number(point.ts_median)) ? Number(point.ts_median) : null,
          tooltipLabel: point.t || null,
        }))
        .filter((point) => point.y != null && Number.isFinite(point.y)),
    };
  });
}

export function metricCovKey(metric) {
  return `${metric}_cov`;
}

export function metricTotalKey(metric) {
  return `${metric}_total`;
}

export function finalMetricValue(fuzzer, metric, mode) {
  if (mode === 'pct') {
    const percent = fuzzer.final?.[`${metric}_pct_median`];
    return Number.isFinite(Number(percent)) ? Number(percent) : null;
  }
  const covered = fuzzer.final?.[`${metricCovKey(metric)}_median`];
  return Number.isFinite(Number(covered)) ? Number(covered) : null;
}

export function distributionValues(fuzzer, metric, mode) {
  if (mode === 'pct') {
    return (fuzzer.distribution?.[`${metric}_pct`] || [])
      .filter((value) => Number.isFinite(Number(value)))
      .map(Number);
  }
  return (fuzzer.distribution?.[metricCovKey(metric)] || [])
    .filter((value) => Number.isFinite(Number(value)))
    .map(Number);
}

export function dedupeBugCount(bugs) {
  return new Set((bugs || []).map((bug) => String(bug?.bug_key || '')).filter(Boolean)).size;
}

export function per10kExec(covered, execsDone) {
  if (
    covered == null ||
    execsDone == null ||
    !Number.isFinite(Number(covered)) ||
    !Number.isFinite(Number(execsDone)) ||
    Number(execsDone) <= 0
  ) {
    return null;
  }
  return 10000 * Number(covered) / Number(execsDone);
}

export function configPayload(versions) {
  const payload = {};
  if (versions?.build_config && Object.keys(versions.build_config).length) {
    payload.build = versions.build_config;
  }
  if (versions?.runtime_config && Object.keys(versions.runtime_config).length) {
    payload.runtime = versions.runtime_config;
  }
  return Object.keys(payload).length ? payload : null;
}
