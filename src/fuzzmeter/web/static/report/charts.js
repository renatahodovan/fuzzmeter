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

import {
  aLink,
  el,
  fmt,
  fmtInt,
  formatGroupedNumber,
  fmtPct,
  formatShortNumber,
  fromTemplate,
  fuzzerColor,
  part,
  quantile,
} from './report-utils.js';

const FONT = '12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
const NUMERIC_KINDS = new Set(['int', 'float', 'pct', 'short', 'text-num']);
const EXPORT_FORMATS = [['png', 'Png'], ['pdf', 'Pdf'], ['latex', 'Latex']];
const EXPORT_BACKGROUND = '#ffffff';
const EXPORT_BORDER = 'rgba(148,163,184,.45)';
const EXPORT_HEADER_BG = 'rgba(241,245,249,.95)';
const EXPORT_TEXT = '#17212f';
const EXPORT_MUTED_TEXT = 'rgba(23,33,47,.68)';
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

function finite(value) {
  return Number.isFinite(Number(value));
}

function number(value, fallback = 0) {
  return finite(value) ? Number(value) : fallback;
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
  if (!finite(value)) return '-';
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
    baselineY: finite(entry.baselineY) ? Number(entry.baselineY) : null,
    color: colorFor(entry, index),
    label: labelFor(entry, index),
    points: (entry.points || [])
      .filter((point) => finite(point.x) && finite(point.y))
      .map((point) => ({
        hi: finite(point.hi) ? Number(point.hi) : null,
        lo: finite(point.lo) ? Number(point.lo) : null,
        tooltipLabel: point.tooltipLabel,
        ts: finite(point.ts) ? Number(point.ts) : null,
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
  })).filter((row) => finite(row.value));
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
    values: (row.values || []).map(Number).filter(Number.isFinite).sort((left, right) => left - right),
  })).filter((row) => row.values.length);
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
    ...entry.points.flatMap((point) => [point.y, point.lo, point.hi].filter(finite).map(Number)),
    ...[entry.baselineY].filter(finite).map(Number),
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
    return { xMax: xs.at(-1), xMin: xs[0], xValues: xs, yMax: number(spec.options.yMax, 100), yMin: 0 };
  }
  const bounds = seriesBounds(spec);
  const pad = (bounds.yMax - bounds.yMin) * 0.08;
  let yMin = Math.max(0, bounds.yMin - pad);
  let yMax = bounds.yMax + pad;
  if (spec.options.yClampPct) {
    yMin = Math.max(0, yMin);
    yMax = Math.min(100, yMax);
  }
  if (!finite(yMin) || !finite(yMax) || yMin === yMax) {
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
    const band = entry.points.filter((point) => finite(point.lo) && finite(point.hi));
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
    if (finite(entry.baselineY)) {
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
    const histogram = new Array(bins).fill(0);
    row.values.forEach((value) => {
      const ratio = Math.max(0, Math.min(0.999999, (value - frame.yMin) / ((frame.yMax - frame.yMin) || 1)));
      histogram[Math.floor(ratio * bins)] += 1;
    });
    const peak = Math.max(...histogram, 1);
    const maxHalfWidth = Math.max(16, Math.min(slot * 0.33, 40));
    frame.ctx.fillStyle = withAlpha(row.color, 0.24);
    frame.ctx.strokeStyle = withAlpha(row.color, 0.62);
    frame.ctx.lineWidth = 1.2;
    frame.ctx.beginPath();
    for (let bin = 0; bin < bins; bin += 1) {
      const y = frame.y(frame.yMin + ((bin + 0.5) / bins) * (frame.yMax - frame.yMin));
      const half = histogram[bin] / peak * maxHalfWidth;
      if (!bin) frame.ctx.moveTo(centerX - half, y);
      else frame.ctx.lineTo(centerX - half, y);
    }
    for (let bin = bins - 1; bin >= 0; bin -= 1) {
      const y = frame.y(frame.yMin + ((bin + 0.5) / bins) * (frame.yMax - frame.yMin));
      frame.ctx.lineTo(centerX + histogram[bin] / peak * maxHalfWidth, y);
    }
    frame.ctx.closePath();
    frame.ctx.fill();
    frame.ctx.stroke();
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
      const nearest = entry.points.reduce((best, point) => (
        !best || Math.abs(point.x - anchor.x) < Math.abs(best.x - anchor.x) ? point : best
      ), null);
      return nearest ? { color: entry.color, label: entry.label, value: nearest.y } : null;
    }).filter(Boolean).sort((left, right) => right.value - left.value);
    const tip = tooltip(canvas);
    tip.textContent = '';
    tip.appendChild(el('div', 'chart-tooltip-title', payload.options.xMode === 'time' ? formatX(anchor.x, payload.options) : String(anchor.tooltipLabel || Math.round(anchor.x))));
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

function installDistributionTooltip(canvas) {
  if (canvas._distributionTooltipInstalled || !canvas.parentElement) return;
  document.addEventListener('click', (event) => {
    if (!canvas.parentElement.contains(event.target)) hideTooltip(canvas);
  });
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
  if (!canvas) return;
  const spec = normalizeSpec(rawSpec);
  const prepared = prepareCanvas(canvas);
  if (!hasRenderableData(spec)) {
    canvas._chartPayload = null;
    canvas._exportPayload = null;
    drawNoData(prepared.ctx, prepared.width, prepared.height, rawSpec.emptyMessage || 'No data');
    return;
  }
  const frame = makeFrame(canvas, spec);
  if (frame.plotWidth <= 0 || frame.plotHeight <= 0) {
    canvas._chartPayload = null;
    canvas._exportPayload = null;
    drawNoData(frame.ctx, frame.width, frame.height, rawSpec.emptyMessage || 'No data');
    return;
  }
  drawFrame(frame);
  MARK_RENDERERS[spec.kind]?.(frame);
  canvas._exportPayload = JSON.parse(JSON.stringify(exportPayload(frame)));
  canvas._chartPayload = { ...canvas._exportPayload, left: frame.left, plotHeight: frame.plotHeight, plotWidth: frame.plotWidth, top: frame.top, xMax: frame.xMax, xMin: frame.xMin };
  if (spec.kind === 'line') installLineTooltip(canvas);
  if (spec.kind === 'distribution') installDistributionTooltip(canvas);
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
export function createSelect(options, value, onChange, className = 'select') {
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

async function exportCanvas(canvas, fileName, format) {
  if (!canvas) return false;
  const sourceCanvas = canvas._exportCanvas || canvas;
  if (format === 'latex') {
    const latex = buildLatex(canvas._exportPayload);
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
  document.addEventListener('click', (event) => {
    if (host.contains(event.target)) return;
    menu.hidden = true;
    host.classList.remove('open');
    triggerButton.setAttribute('aria-expanded', 'false');
  });
}

/**
 * Attach an export menu to an arbitrary table-like element.
 */
export function installElementExportMenu(triggerButton, element, fileName) {
  installExportMenu(triggerButton, (format) => exportElement(element, typeof fileName === 'function' ? fileName() : fileName, format));
}

/**
 * Create a standard canvas chart card.
 */
export function makeCanvasCard({ title, subtitle = '', withLegend = false, exportName = 'chart' }) {
  const card = fromTemplate('tplCanvasCard');
  const titleEl = part(card, 'title');
  const subtitleEl = part(card, 'subtitle');
  const canvas = part(card, 'canvas');
  const legend = part(card, 'legend');
  titleEl.textContent = title;
  subtitleEl.textContent = subtitle;
  legend.hidden = !withLegend;
  let currentExportName = exportName;
  installExportMenu(part(card, 'download'), (format) => exportCanvas(canvas, currentExportName, format));
  return {
    canvas,
    card,
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
    if (canvas) canvas._exportCanvas = null;
    return;
  }
  const legendItems = Array.from(legend.querySelectorAll('.legend-item'));
  if (!legendItems.length) {
    canvas._exportCanvas = null;
    return;
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
  canvas._exportCanvas = exportCanvasEl;
}

/**
 * Create a standard matrix or table card.
 */
export function makeMatrixCard({ title, subtitle = '' }) {
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
export function renderDataTable(host, columns, rows) {
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
export function renderChartCard(card, spec = {}) {
  if (!card || !spec) return;
  if (spec.title !== undefined) card.setTitle?.(spec.title);
  if (spec.subtitle !== undefined) card.setSubtitle?.(spec.subtitle);
  if (spec.exportName !== undefined) card.setExportName?.(spec.exportName);
  if (card.canvas && spec.kind) renderCanvasChart(card.canvas, spec);
  if (card.legend && spec.legend !== false) renderLegend(card.legend, spec.legendSeries || spec.series || []);
  if (card.canvas) updateCanvasExportSurface(card.canvas, card.legend);
}

/**
 * Render a matrix card from matrix data.
 */
export function renderMatrixCard(card, matrixData, options = {}) {
  if (!card) return;
  if (options.title !== undefined) card.setTitle?.(options.title);
  if (options.subtitle !== undefined) card.setSubtitle?.(options.subtitle);
  if (options.exportName !== undefined) card.setExportName?.(options.exportName);
  renderMatrixTable(card.body, matrixData, options);
}

function matrixStyle(value, maxValue, tint) {
  if (!finite(value) || value <= 0 || !finite(maxValue) || maxValue <= 0) return '';
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
export function renderMatrixTable(host, matrixData, options = {}) {
  host.textContent = '';
  if (!matrixData?.fuzzers?.length || !matrixData?.matrix?.length) {
    host.appendChild(el('div', 'matrix-empty', options.emptyMessage || 'No data.'));
    return;
  }
  if (matrixData.note) host.appendChild(el('div', 'matrix-note muted small', matrixData.note));
  const labels = matrixData.fuzzers;
  const maxValue = finite(matrixData.max_value) ? Number(matrixData.max_value) : Math.max(0, ...matrixData.matrix.flat().map(number));
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
      const value = number((matrixData.matrix[rowIndex] || [])[colIndex]);
      const self = rowIndex === colIndex;
      const text = matrixText(value, options);
      const td = el('td', 'num', self && options.allowSelfDash !== false ? '-' : text);
      td.style.cssText = self && options.allowSelfDash !== false
        ? 'background:#ffffff; color:#111827; font-weight:700;'
        : (typeof options.styleForValue === 'function'
          ? options.styleForValue(value, { colIndex, colLabel, matrixData, maxValue, rowIndex, rowLabel })
          : matrixStyle(value, maxValue, options.tint || 'rgba(120,180,255,ALPHA)'));
      td.title = self && options.allowSelfDash !== false ? `${rowLabel}: same row` : `${rowLabel} - ${colLabel}: ${text}`;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}
