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

import {
  fromTemplate,
  fuzzerColor,
  part,
} from './report-utils.js';
import {
  makeCanvasCard,
  makeMatrixCard,
  renderChartCard,
  renderDataTable,
  renderMatrixTable,
} from './charts.js';

const LINE_CHART_TYPES = new Set(['line', 'line_shadow', 'lines_with_shadows']);
const ALLOWED_CHART_TYPES = new Set([
  'bar',
  'distribution',
  'line',
  'line_shadow',
  'lines_with_shadows',
  'matrix',
  'stacked_area',
  'stacked_bar',
  'table',
]);

function cloneMatrixForSelected(matrixData, selectedSet) {
  if (!matrixData || !Array.isArray(matrixData.fuzzers) || !Array.isArray(matrixData.matrix)) return null;
  const indices = matrixData.fuzzers
    .map((fuzzer, index) => [String(fuzzer), index])
    .filter(([fuzzer]) => selectedSet.has(fuzzer));
  if (!indices.length) return null;
  const filteredFuzzers = indices.map(([fuzzer]) => fuzzer);
  const filteredMatrix = indices.map(([, rowIndex]) => (
    indices.map(([, colIndex]) => Number((matrixData.matrix[rowIndex] || [])[colIndex] || 0))
  ));
  const filteredCoveredCounts = Array.isArray(matrixData.covered_counts)
    ? indices.map(([, index]) => Number(matrixData.covered_counts[index] || 0))
    : undefined;
  const filteredUniqueCounts = Array.isArray(matrixData.unique_counts)
    ? indices.map(([, index]) => Number(matrixData.unique_counts[index] || 0))
    : undefined;
  const maxValue = Math.max(0, ...filteredMatrix.flat().map((value) => Number(value) || 0));
  return {
    ...matrixData,
    fuzzers: filteredFuzzers,
    matrix: filteredMatrix,
    covered_counts: filteredCoveredCounts,
    unique_counts: filteredUniqueCounts,
    max_value: maxValue,
    has_data: filteredMatrix.some((row) => row.some((value) => value > 0)) || filteredFuzzers.length > 0,
  };
}

function hasTimeXAxis(chart) {
  const axis = String(chart?.x_axis || '').toLowerCase();
  return axis.includes('elapsed') || axis.includes('time') || axis.includes('second');
}

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
  if (chart.groups?.length) return chart.groups;
  const series = normalizeSeries(chart.series);
  const labels = Array.from(new Set(
    series.flatMap((entry) => (entry.points || []).map((point) => String(point.x ?? point.label))),
  ));
  return labels.map((label) => ({
    label,
    segments: series.map((entry) => {
      const point = (entry.points || []).find((candidate) => String(candidate.x ?? candidate.label) === label);
      return { label: entry.label, value: point?.y ?? 0, color: entry.color };
    }),
  }));
}

function createExtraChartCard(section, chart) {
  if (!ALLOWED_CHART_TYPES.has(chart.type)) {
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
    withLegend: LINE_CHART_TYPES.has(chart.type) || chart.type === 'stacked_area' || chart.type === 'stacked_bar',
    exportName: `${section.id}-${chart.id}`,
  });
  const series = normalizeSeries(chart.series);
  const percentAxis = String(chart.y_axis || '').toLowerCase().includes('percent');
  const xMode = hasTimeXAxis(chart) ? 'time' : 'index';
  return {
    card: card.card,
    render() {
      let spec = null;
      if (LINE_CHART_TYPES.has(chart.type)) {
        spec = { kind: 'line', series, options: { xMode, yClampPct: percentAxis } };
      } else if (chart.type === 'stacked_area') {
        spec = { kind: 'stackedArea', series, options: { xMode, yMax: 100 } };
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

function placementOrder(placement) {
  if (placement === 'after:coverage') return 0;
  if (placement === 'after:performance') return 1;
  if (placement === 'after:bugs') return 2;
  if (placement === 'after:target') return 3;
  return 99;
}

export function filterExtraSections(extraSections, selectedSet) {
  const filterSeries = (series) => (series || []).filter((entry) => {
    const key = String(entry.id || entry.label || '');
    return !selectedSet.size || selectedSet.has(key) || selectedSet.has(String(entry.label || ''));
  });

  const filterRows = (rows) => (rows || []).filter((row) => {
    const fuzzer = row?.fuzzer || row?.owner_fuzzer;
    return !fuzzer || !selectedSet.size || selectedSet.has(String(fuzzer));
  });

  return (extraSections || [])
    .map((section) => {
      const charts = (section.charts || [])
        .filter((chart) => ALLOWED_CHART_TYPES.has(chart.type))
        .map((chart) => {
          if (chart.filter_mode === 'static') return chart;
          if (chart.type === 'matrix') {
            const matrix = cloneMatrixForSelected(chart.matrix, selectedSet);
            return matrix?.fuzzers?.length ? { ...chart, matrix } : null;
          }
          if (chart.type === 'table') {
            const rows = filterRows(chart.rows);
            return rows.length ? { ...chart, rows } : null;
          }
          if (chart.type === 'bar' && chart.rows?.length) {
            const rows = filterRows(chart.rows);
            return rows.length ? { ...chart, rows } : null;
          }
          if (chart.type === 'stacked_area') {
            const series = filterSeries(chart.series);
            return series.length ? { ...chart, series } : null;
          }
          const series = filterSeries(chart.series);
          return series.length ? { ...chart, series } : null;
        })
        .filter(Boolean);
      return charts.length ? { ...section, charts } : null;
    })
    .filter(Boolean);
}

export function renderExtraSections(host, extraSections) {
  const sections = [...(extraSections || [])]
    .sort((left, right) => placementOrder(left.placement) - placementOrder(right.placement));
  sections.forEach((section) => {
    const block = fromTemplate('tplReportBlock');
    const blockTitle = section.scope === 'fuzzer' && section.owner_fuzzer
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
