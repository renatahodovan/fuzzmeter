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

import {
  COVERAGE_METRICS,
  FM_APP,
  MATRIX_PAYLOAD_KEYS,
  byId,
  cleanFloats,
  comparisonMetric,
  el,
  rankdataDesc,
} from './report-utils.js';
import { filterExtraSections } from './extras.js';
import { cloneMatrixForSelected } from './matrix.js';

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

export function allFuzzerNames(data) {
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

export function allBenchmarkNames(data) {
  if (Array.isArray(data?.filters?.benchmarks) && data.filters.benchmarks.length) {
    return data.filters.benchmarks.map((name) => String(name)).filter(Boolean);
  }
  return Array.from(new Set((data?.targets || []).map((target) => String(target?.benchmark || '')).filter(Boolean))).sort();
}

export function cloneUniqueBugTableForSelected(tableData, selectedSet) {
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
        return Number.isFinite(Number(value)) ? Number(value) : null;
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

export function cloneUniqueCoverageMatrix(uniqueMatrix, selectedSet) {
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

export function cloneMetricMatrixGroup(matrixGroup, selectedSet) {
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

export function enrichTargetForSelection(target) {
  const fuzzers = (target.fuzzers || []).map((fuzzer) => ({ ...fuzzer }));
  COVERAGE_METRICS.forEach(([metric]) => {
    const values = fuzzers.map((fuzzer) => {
      const value = fuzzer.final?.[`${metric}_pct_median`];
      return Number.isFinite(Number(value)) ? Number(value) : null;
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

export function computeSummary(targets, comparisonMode = FM_APP.state.comparisonMode) {
  const fuzzers = Array.from(new Set(
    targets.flatMap((target) => (target.fuzzers || []).map((entry) => entry.fuzzer)),
  )).sort();
  const hasPairwiseFuzzers = fuzzers.length > 1;
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
  targets.forEach((target) => {
    const medians = (target.fuzzers || [])
      .map((entry) => entry.final?.regions_pct_median)
      .filter((value) => Number.isFinite(Number(value)))
      .map(Number);
    const aucMedians = (target.fuzzers || [])
      .map((entry) => entry.final?.branches_cov_auc_median)
      .filter((value) => Number.isFinite(Number(value)))
      .map(Number);
    const best = medians.length ? Math.max(...medians) : null;
    const bestAuc = aucMedians.length ? Math.max(...aucMedians) : null;
    (target.fuzzers || []).forEach((entry) => {
      const medianValue = entry.final?.regions_pct_median;
      if (best != null && best > 0 && Number.isFinite(Number(medianValue))) {
        scores.get(entry.fuzzer)?.push(100 * Number(medianValue) / best);
      }
      const aucValue = entry.final?.branches_cov_auc_median;
      if (bestAuc != null && bestAuc > 0 && Number.isFinite(Number(aucValue))) {
        aucScores.get(entry.fuzzer)?.push(100 * Number(aucValue) / bestAuc);
      }
      if (hasPairwiseFuzzers && Number.isFinite(Number(target[relcovScoreByFuzzer]?.[entry.fuzzer]))) {
        relcovScores.get(entry.fuzzer)?.push(Number(target[relcovScoreByFuzzer][entry.fuzzer]));
      }
      if (hasPairwiseFuzzers && Number.isFinite(Number(target[relbugScoreByFuzzer]?.[entry.fuzzer]))) {
        relbugScores.get(entry.fuzzer)?.push(Number(target[relbugScoreByFuzzer][entry.fuzzer]));
      }
      addComparisonTotal(exclusiveCoverage, entry.fuzzer, entry.exclusive_coverage, comparisonMode);
      uniqueBugs.set(
        entry.fuzzer,
        Number(uniqueBugs.get(entry.fuzzer) || 0) + Number(entry.final?.accumulated_bug_count || 0),
      );
      addComparisonTotal(exclusiveBugs, entry.fuzzer, entry.exclusive_bugs, comparisonMode);
      if (Number.isFinite(Number(entry.final?.execs_done_median))) {
        execs.get(entry.fuzzer)?.push(Number(entry.final.execs_done_median));
      }
    });
  });
  return {
    rankings: fuzzers.map((fuzzer) => {
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

export function deriveReportData(rawData, selectedFuzzers) {
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
        [relcovScoreByFuzzer]: hasPairwiseFuzzers ? target[relcovScoreByFuzzer] : {},
        [relbugScoreByFuzzer]: hasPairwiseFuzzers ? target[relbugScoreByFuzzer] : {},
        extra_sections: filterExtraSections(target.extra_sections, selectedSet),
      });
      enrichedTarget.fuzzers = enrichedTarget.fuzzers.map((entry) => ({
        ...entry,
        extra_sections: filterExtraSections(entry.extra_sections, selectedSet),
      }));
      return enrichedTarget;
    })
    .filter(Boolean);
  return {
    ...rawData,
    targets,
    summary: computeSummary(targets),
  };
}

export function selectedFuzzerNames() {
  return Array.from(FM_APP.state.selectedFuzzers);
}

export function selectNewFilterEntries(previous, next) {
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

export function renderFuzzerFilterOptions(data, onChange) {
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

export function renderBenchmarkFilterOptions(data, onChange) {
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

export function installFuzzerFilter(data, onChange) {
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
    names.forEach((name) => FM_APP.state.selectedFuzzers.add(name));
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

export function installBenchmarkFilter(data, onChange) {
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
    names.forEach((name) => FM_APP.state.selectedBenchmarks.add(name));
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
