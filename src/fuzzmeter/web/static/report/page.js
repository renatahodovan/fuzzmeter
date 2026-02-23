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

import {
  aLink,
  buildCoverageSeries,
  buildCurveSeries,
  COVERAGE_METRICS,
  createFuzzerNameButton,
  dedupeBugCount,
  distributionValues,
  el,
  finalMetricValue,
  FM_APP,
  fmt,
  fmtInt,
  fmtPct,
  formatDuration,
  formatExecCount,
  formatGroupedNumber,
  fromTemplate,
  fuzzerColor,
  maximum,
  median,
  metricLabel,
  minimum,
  part,
  per10kExec,
  renderAggregateCell,
  sanitizeId,
  setTooltip,
  VALUE_OPTIONS,
  byId,
} from './report-utils.js';
import {
  createSelect,
  installElementExportMenu,
  makeCanvasCard,
  makeMatrixCard,
  renderChartCard,
  renderDataTable,
  renderMatrixCard,
  renderMatrixTable,
} from './charts.js';
import { renderExtraSections } from './extras.js';

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
  return {
    table,
    tbody: part(section.el, 'fuzzer-body'),
    coverageHead: part(section.el, 'coverage-head'),
    target,
  };
}

function aggregateCellContent(primaryValue, distributionValues, formatter, detailLabels = ['min', 'max', 'median']) {
  const values = (distributionValues || []).filter((value) => Number.isFinite(Number(value))).map(Number);
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
  const numericValues = (values || []).filter((value) => Number.isFinite(Number(value))).map(Number);
  const primaryValue = median(numericValues);
  const cell = el('td', 'num');
  const { primaryText, detailsText } = aggregateCellContent(primaryValue, numericValues, formatter, detailLabels);
  const renderedPrimary = primaryLabel ? `${primaryLabel} ${primaryText}` : primaryText;
  tr.appendChild(renderAggregateCell(cell, renderedPrimary, detailsText));
}

function appendCustomAggregateCell(tr, primaryText, values, formatter, detailLabels = ['min', 'max', 'median']) {
  const cell = el('td', 'num');
  const numericValues = (values || []).filter((value) => Number.isFinite(Number(value))).map(Number);
  const { detailsText } = aggregateCellContent(numericValues[0], numericValues, formatter, detailLabels);
  tr.appendChild(renderAggregateCell(cell, primaryText, detailsText));
}

function headerCell(label, className, tooltip) {
  return setTooltip(el('th', className, label), tooltip);
}

function statsDetailLines(stats, formatter) {
  const lines = [];
  ['min', 'max', 'median'].forEach((label) => {
    const value = stats?.[label];
    if (value === null || value === undefined || Number.isNaN(Number(value))) return;
    lines.push([label, formatter(value)]);
  });
  return lines;
}

function exclusiveCoverageStats(target, fuzzer) {
  if (fuzzer.exclusive_coverage) return fuzzer.exclusive_coverage;
  const matrix = resolveCoverageMatrix(target.unique_matrix, 'branches');
  const index = (matrix?.fuzzers || []).map(String).indexOf(String(fuzzer.fuzzer || ''));
  if (index < 0) return {};
  const value = Number((matrix.unique_counts || [])[index]);
  return {
    total: Number.isFinite(value) ? value : null,
  };
}

function hasMultipleFuzzers(target) {
  const fuzzers = (target.fuzzers || []).map((fuzzer) => String(fuzzer.fuzzer || '')).filter(Boolean);
  return new Set(fuzzers).size > 1;
}

function hasResourceTelemetry(target) {
  return (target.fuzzers || []).some((fuzzer) => (fuzzer.curve || []).some((point) => (
    Number.isFinite(Number(point.resource_cpu_percent))
    || Number.isFinite(Number(point.resource_memory_mib))
    || Number.isFinite(Number(point.resource_memory_percent))
    || Number.isFinite(Number(point.resource_corpus_disk_mib))
  )));
}

function compareTargetRows(left, right, key) {
  const leftValue = left?.[key];
  const rightValue = right?.[key];
  const leftMissing = leftValue === null || leftValue === undefined || Number.isNaN(Number(leftValue));
  const rightMissing = rightValue === null || rightValue === undefined || Number.isNaN(Number(rightValue));
  if (leftMissing && rightMissing) return String(left?.fuzzer || '').localeCompare(String(right?.fuzzer || ''));
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  const delta = Number(leftValue) - Number(rightValue);
  if (delta === 0) return String(left?.fuzzer || '').localeCompare(String(right?.fuzzer || ''));
  return sectionSortDirectionMultiplier(left._section, key) * delta;
}

function sectionSortDirectionMultiplier(section, key) {
  const direction = section.tableSort?.key === key ? section.tableSort.direction : 'desc';
  return direction === 'asc' ? 1 : -1;
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
      renderFuzzerTable(section);
    });
    th.dataset.bound = '1';
  });
}

function renderFuzzerTable(section) {
  const { target, fuzzerTable } = section;
  const metric = 'branches';
  const mode = 'abs';
  fuzzerTable.coverageHead.textContent = 'Branches';
  fuzzerTable.tbody.textContent = '';

  const rows = (target.fuzzers || []).map((fuzzer) => {
    const branch10kValues = (fuzzer.trials || []).map((trial) => per10kExec(trial.branches_cov, trial.execs_done));
    const convergenceValues = (fuzzer.trials || []).map((trial) => trial.convergence_pct);
    const exclusiveCoverage = exclusiveCoverageStats(target, fuzzer);
    return {
      ...fuzzer,
      _section: section,
      branches_union: Number(fuzzer.aggregate?.branches_covered),
      execs_per_sec_median: median(fuzzer.distribution?.execs_per_sec),
      execs_done_median: median(fuzzer.distribution?.execs_done),
      branch_per_10k_median: median(branch10kValues),
      convergence_median: median(convergenceValues),
      exclusive_coverage_total: exclusiveCoverage.total == null ? null : Number(exclusiveCoverage.total),
      corpus_median: median(fuzzer.distribution?.corpus_files_total),
      unique_bug_total: Number(fuzzer.final?.accumulated_bug_count ?? dedupeBugCount(fuzzer.bugs)),
      exclusive_bug_total: Number(fuzzer.exclusive_bugs?.total),
      all_bug_hits_median: median(fuzzer.distribution?.bug_hits_total),
    };
  });

  const sortKey = section.tableSort?.key || 'branches_union';
  rows.sort((left, right) => compareTargetRows(left, right, sortKey));
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
      (fuzzer.trials || []).map((trial) => trial.convergence_pct),
      (value) => fmtPct(value, 1),
      ['min', 'max'],
      'median',
    );
    const exclusiveCoverage = exclusiveCoverageStats(target, fuzzer);
    tr.appendChild(renderAggregateCell(
      el('td', 'num'),
      `total ${fmtInt(exclusiveCoverage.total)}`,
      statsDetailLines(exclusiveCoverage, fmtInt),
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
    tr.appendChild(renderAggregateCell(
      el('td', 'num'),
      `total ${fmtInt(fuzzer.exclusive_bugs?.total)}`,
      statsDetailLines(fuzzer.exclusive_bugs, fmtInt),
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
  const bottomStack = el('div', 'block-grid-1');
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
  const relCard = hasMultipleFuzzers(section.target) ? makeMatrixCard({
    title: 'RelBug matrix',
    subtitle: 'Cell = how much of the column fuzzer bug set is also found by the row fuzzer.',
  }) : null;
  topRow.appendChild(growthCard.card);
  topRow.appendChild(crashesCard.card);
  if (matrixCard) bottomStack.appendChild(matrixCard.card);
  if (relCard) bottomStack.appendChild(relCard.card);
  body.appendChild(topRow);
  if (matrixCard || relCard) body.appendChild(bottomStack);

  matrixCard?.setExportName(`${section.target.key}-unique-bug-matrix`);
  relCard?.setExportName(`${section.target.key}-relbug-matrix`);
  section.bugsBlock = { block, growthCard, crashesCard, matrixCard, relCard };
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

function createSignificanceDetails(target) {
  if (!(target.significance_vs_best || []).length) return null;
  const details = el('details', 'details');
  details.appendChild(el('summary', null, 'Sample statistics & significance (vs best fuzzer, Mann-Whitney U)'));
  const tableHost = el('div');
  renderDataTable(
    tableHost,
    [
      { label: 'Fuzzer', key: 'fuzzer', kind: 'text', tooltip: 'Fuzzer being compared against the best fuzzer on this target.' },
      { label: 'Compared to', key: 'vs', kind: 'text', tooltip: 'Best fuzzer on this target used as the reference sample.' },
      { label: 'p-value', key: 'pValue', kind: 'text-num', tooltip: 'Mann-Whitney U p-value for the difference between the two samples.' },
      { label: 'Cliff\'s δ', key: 'cliffsDelta', kind: 'text-num', tooltip: 'Cliff\'s delta effect size between the two samples.' },
    ],
    (target.significance_vs_best || []).map((row) => ({
      fuzzer: row.fuzzer,
      vs: row.vs,
      pValue: row.p_value === null ? '—' : fmt(row.p_value, 4),
      cliffsDelta: row.cliffs_delta === null ? '—' : fmt(row.cliffs_delta, 3),
    })),
  );
  details.appendChild(tableHost);
  details.appendChild(el(
    'div',
    'muted small',
    'p-value: smaller means the observed difference is less likely to be random under the null hypothesis. ' +
      'Cliff\'s δ: effect size in [-1, 1]; near 0 means little separation, near ±1 means strong separation.',
  ));
  return details;
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
  return ['branches', 'regions', 'lines', 'functions'].find(hasMetricData) || 'branches';
}

function renderUniqueCoverageMatrix(host, uniqueMatrix, metric, mode) {
  host.textContent = '';
  const matrix = resolveCoverageMatrix(uniqueMatrix, metric);
  if (!matrix || !matrix.fuzzers?.length || !matrix.matrix?.length) {
    host.appendChild(el('div', 'matrix-empty', 'No unique coverage data.'));
    return;
  }

  const rendered = mode === 'pct' ? {
    ...matrix,
    matrix: (matrix.matrix || []).map((row, rowIndex) => row.map((value) => {
      const denominator = Number((matrix.covered_counts || [])[rowIndex] || 0);
      return denominator > 0 ? 100 * Number(value || 0) / denominator : 0;
    })),
    max_value: null,
  } : matrix;
  renderMatrixTable(host, rendered, {
    formatter: mode === 'pct' ? 'pct' : 'int',
    emptyMessage: 'No unique coverage data.',
    tint: 'rgba(120,180,255,ALPHA)',
  });
}

function branchPValueCellStyle(value) {
  if (!Number.isFinite(Number(value)) || Number(value) > 0.05) return '';
  const clamped = Math.max(0, Math.min(0.05, Number(value)));
  const alpha = 0.10 + (0.55 * (1 - (clamped / 0.05)));
  return `background:rgba(78,183,118,${alpha.toFixed(3)}); font-weight:700;`;
}

function branchA12CellStyle(value) {
  if (!Number.isFinite(Number(value))) return '';
  const effect = Math.min(1, Math.abs(Number(value) - 0.5) * 2);
  if (effect <= 0) return '';
  const alpha = 0.10 + (0.55 * effect);
  const tint = Number(value) >= 0.5 ? '69,160,73' : '239,108,0';
  return `background:rgba(${tint},${alpha.toFixed(3)}); font-weight:700;`;
}

function lineChartSpec(series, overrides = {}) {
  const overrideOptions = overrides.options || {};
  const usesTime = series.some((entry) => (
    entry.usesElapsed
    || (entry.points || []).some((point) => Number.isFinite(Number(point.ts)))
    || (entry.points || []).some((point) => (
      Number.isFinite(Number(point.idx))
      && Number.isFinite(Number(point.x))
      && Number(point.x) !== Number(point.idx)
    ))
  ));
  return {
    kind: 'line',
    series,
    ...overrides,
    options: {
      yClampPct: false,
      xMode: usesTime ? 'time' : 'index',
      ...overrideOptions,
    },
  };
}

function renderLineCard(card, series, overrides = {}) {
  renderChartCard(card, lineChartSpec(series, overrides));
}

function uniqueBugHeatColor(elapsedSeconds, plannedDurationSeconds) {
  if (elapsedSeconds === null || elapsedSeconds === undefined || !Number.isFinite(Number(elapsedSeconds))) return '#ffffff';
  const duration = Number.isFinite(Number(plannedDurationSeconds)) && Number(plannedDurationSeconds) > 0
    ? Number(plannedDurationSeconds)
    : Math.max(1, Number(elapsedSeconds));
  const ratio = Math.max(0, Math.min(1, Number(elapsedSeconds) / duration));
  const lightness = 82 - ((1 - ratio) * 40);
  const saturation = 56 + ((1 - ratio) * 16);
  return `hsl(144 ${saturation.toFixed(1)}% ${lightness.toFixed(1)}%)`;
}

function uniqueBugCellStyle(elapsedSeconds, plannedDurationSeconds) {
  const background = uniqueBugHeatColor(elapsedSeconds, plannedDurationSeconds);
  if (elapsedSeconds === null || elapsedSeconds === undefined || !Number.isFinite(Number(elapsedSeconds))) {
    return `background:${background}; color:#111827; font-weight:700;`;
  }
  const duration = Number.isFinite(Number(plannedDurationSeconds)) && Number(plannedDurationSeconds) > 0
    ? Number(plannedDurationSeconds)
    : Math.max(1, Number(elapsedSeconds) || 1);
  const ratio = !Number.isFinite(Number(elapsedSeconds)) ? 1 : Number(elapsedSeconds) / duration;
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

  const hasSnapshotSeconds = Number.isFinite(Number(tableData.last_snapshot_elapsed_seconds))
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
  if (coverage.matrixCard) {
    renderUniqueCoverageMatrix(coverage.matrixCard.body, target.unique_matrix, metric, 'abs');
    coverage.matrixCard.setTitle(`Unique ${metricName} matrix`);
    coverage.matrixCard.setSubtitle(`Cell = ${metricName} covered by the row fuzzer but not the column fuzzer.`);
    coverage.matrixCard.setExportName(`${section.target.key}-unique-${metric}-matrix`);
  }
  if (coverage.relCard) {
    renderMatrixCard(coverage.relCard, resolveCoverageMatrix(target.relcov_matrix, metric), {
      formatter: 'pct',
      emptyMessage: 'No relative coverage matrix data.',
      tint: 'rgba(110,226,240,ALPHA)',
      title: `RelCov ${metricName} matrix`,
      subtitle: 'Cell = how much of the column fuzzer union coverage is also covered by the row fuzzer.',
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

function renderBugBlock(section) {
  const { target, bugsBlock } = section;
  const uniqueSeries = buildCurveSeries(target.fuzzers, 'unique_bugs_total');
  const crashSeries = buildCurveSeries(target.fuzzers, 'crashes_total');
  renderLineCard(bugsBlock.growthCard, uniqueSeries, { subtitle: 'median across trials' });
  renderLineCard(bugsBlock.crashesCard, crashSeries, { subtitle: 'median across trials' });
  if (bugsBlock.matrixCard) renderUniqueBugTable(bugsBlock.matrixCard.body, target.unique_bug_table || null);
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
      c1: formatGroupedNumber(trial.rep, { maximumFractionDigits: 0 }),
      c2: formatDuration(trial.elapsed_seconds),
      c3: trial.execs_per_sec == null ? '—' : formatGroupedNumber(trial.execs_per_sec, { maximumFractionDigits: 1 }),
      c4: formatGroupedNumber(trial.regions_cov, { maximumFractionDigits: 0 }),
      c5: formatGroupedNumber(trial.branches_cov, { maximumFractionDigits: 0 }),
      c6: trial.convergence_pct == null ? '—' : fmtPct(trial.convergence_pct, 1),
      c7: trial.execs_done == null ? '—' : formatGroupedNumber(per10kExec(trial.branches_cov, trial.execs_done), { maximumFractionDigits: 1 }),
    }));
  renderDataTable(tableSpec.body, tableSpec.columns, rows);
}

function renderStatisticsBlock(section) {
  const { target, statistics } = section;
  if (!statistics) return;
  renderMatrixCard(statistics.mwuCard, resolveCoverageMatrix(target.branch_mwu_matrix, 'branches'), {
    formatter: 'float',
    fractionDigits: 4,
    emptyMessage: 'No branch Mann-Whitney U data.',
    styleForValue: branchPValueCellStyle,
    title: 'Branch MWU p-value matrix',
    subtitle: 'Green cells indicate a significant pairwise difference in final per-trial branch coverage (p <= 0.05).',
    exportName: `${section.target.key}-branch-mwu-pvalue-matrix`,
  });
  renderMatrixCard(statistics.a12Card, resolveCoverageMatrix(target.branch_a12_matrix, 'branches'), {
    formatter: 'float',
    fractionDigits: 3,
    emptyMessage: 'No branch Vargha-Delaney A12 data.',
    styleForValue: branchA12CellStyle,
    title: 'Branch Vargha-Delaney A12 matrix',
    subtitle: 'Cells above 0.5 favor the row fuzzer, cells below 0.5 favor the column fuzzer.',
    exportName: `${section.target.key}-branch-a12-matrix`,
  });
}

export function createTargetSection(target) {
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

  const section = {
    target,
    el: sectionEl,
    coverageState: { ...(FM_APP.state.coverageByTarget.get(target.key) || { metric: defaultCoverageMetric(target), value: 'abs' }) },
    tableSort: { key: 'branches_union', direction: 'desc' },
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
  };

  const fuzzerTable = createFuzzerTable(section);
  section.fuzzerTable = fuzzerTable;
  installTargetTableSorting(section);
  const targetTableExport = part(sectionEl, 'target-table-export');
  const targetTableExportHost = targetTableExport.parentElement;

  const blocks = part(sectionEl, 'blocks');
  const combinedExtraSections = [
    ...(target.extra_sections || []),
    ...(target.fuzzers || []).flatMap((fuzzer) => fuzzer.extra_sections || []),
  ];
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
  if (customMetricsBlock) blocks.appendChild(customMetricsBlock);
  if (statisticsBlock) blocks.appendChild(statisticsBlock);
  if (debugBlock) blocks.appendChild(debugBlock);

  section.navItems = [
    ['Summary', `#t-${targetId}-summary`],
    ['Coverage', `#t-${targetId}-coverage`],
    ['Throughput', `#t-${targetId}-throughput`],
    ['Bug finding', `#t-${targetId}-bugs`],
    resourceTelemetryBlock ? ['Telemetry', `#t-${targetId}-telemetry`] : null,
    customMetricsBlock ? ['Custom metrics', `#t-${targetId}-custom`] : null,
    statisticsBlock ? ['Statistics', `#t-${targetId}-statistics`] : null,
    debugBlock ? ['Debug', `#t-${targetId}-debug`] : null,
  ].filter(Boolean).map(([label, selector]) => ({ label, selector }));

  return section;
}
