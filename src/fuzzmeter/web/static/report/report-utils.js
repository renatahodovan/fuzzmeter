/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Shared report state, formatting, statistics, and DOM helpers.
 */

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

export const VALUE_OPTIONS = [['abs', 'Absolute'], ['pct', 'Percent']];
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
    summarySort: { key: 'coverage_score', direction: 'desc' },
  },
  sections: [],
  redrawAll: () => {},
  activeTocCleanup: null,
  activeNavCleanup: null,
};

export function byId(id) {
  return document.getElementById(id);
}

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function fromTemplate(id) {
  const template = byId(id);
  if (!(template instanceof HTMLTemplateElement)) {
    throw new Error(`Missing template: ${id}`);
  }
  return template.content.firstElementChild.cloneNode(true);
}

export function part(root, name) {
  return root.querySelector(`[data-part='${name}']`);
}

export function aLink(text, href) {
  const a = document.createElement('a');
  a.href = href;
  a.textContent = text;
  a.target = '_blank';
  a.rel = 'noreferrer';
  return a;
}

export function sanitizeId(value) {
  return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

export async function fetchJSON(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

export function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

export function fmtPct(value, digits = 2) {
  return value === null || value === undefined ? '—' : `${fmt(value, digits)}%`;
}

export function fmtInt(value) {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : `${Math.round(Number(value))}`;
}

export function formatGroupedNumber(value, options = {}) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const parts = new Intl.NumberFormat(undefined, options).formatToParts(Number(value));
  return parts.map((part) => (part.type === 'group' ? ' ' : part.value)).join('');
}

export function formatShortNumber(value) {
  if (value == null || !Number.isFinite(Number(value))) return '';
  const n = Number(value);
  const abs = Math.abs(n);
  if (abs < 1000) return String(Math.round(n));
  if (abs < 1e6) return `${(n / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}k`;
  if (abs < 1e9) return `${(n / 1e6).toFixed(abs >= 1e8 ? 0 : 1)}M`;
  return `${(n / 1e9).toFixed(1)}B`;
}

export function maximum(values) {
  const clean = cleanFloats(values);
  return clean.length ? Math.max(...clean) : null;
}

export function minimum(values) {
  const clean = cleanFloats(values);
  return clean.length ? Math.min(...clean) : null;
}

export function formatExecCount(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const n = Number(value);
  const abs = Math.abs(n);
  if (abs < 1e3) return fmtInt(n);
  if (abs < 1e6) return `${(n / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}k`;
  if (abs < 1e9) return `${(n / 1e6).toFixed(abs >= 1e8 ? 0 : 1)}M`;
  return `${(n / 1e9).toFixed(abs >= 1e11 ? 0 : 1)}B`;
}

export function renderAggregateCell(cell, primaryText, detailsText) {
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

export function setTooltip(node, text) {
  if (!node || !text) return node;
  node.title = text;
  return node;
}

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

export function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined
    ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
    : sorted[base];
}

export function median(values) {
  const sorted = (values || []).filter((value) => Number.isFinite(Number(value))).map(Number).sort((a, b) => a - b);
  return quantile(sorted, 0.5);
}

export function cleanFloats(values) {
  return (values || [])
    .filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)))
    .map(Number);
}

export function rankdataDesc(values) {
  const indexed = values
    .map((value, index) => [index, value])
    .filter(([, value]) => Number.isFinite(Number(value)))
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

export function mannWhitneyUPValue(xValues, yValues) {
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

export function cliffsDelta(xValues, yValues) {
  const x = cleanFloats(xValues);
  const y = cleanFloats(yValues);
  if (!x.length || !y.length) return null;
  let gt = 0;
  let lt = 0;
  x.forEach((a) => {
    y.forEach((b) => {
      if (a > b) gt += 1;
      else if (a < b) lt += 1;
    });
  });
  return (gt - lt) / (x.length * y.length);
}

export function erf(value) {
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

export function dedupeBugCount(bugs) {
  return new Set((bugs || []).map((bug) => String(bug?.bug_key || '')).filter(Boolean)).size;
}

export function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return '—';
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

export function ensureConfigModal() {
  const modal = byId('configModal');
  const title = byId('configModalTitle');
  const body = byId('configModalBody');
  const close = byId('configModalClose');
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

export function openConfigModal(fuzzerName, versions) {
  const refs = ensureConfigModal();
  if (!refs) return;
  refs.title.textContent = `${fuzzerName} config`;
  refs.body.textContent = JSON.stringify(configPayload(versions) || {}, null, 2);
  refs.modal.classList.remove('hidden');
}

export function createConfigLink(fuzzer) {
  const payload = configPayload(fuzzer.versions);
  if (!payload) return document.createTextNode('—');
  const link = el('button', 'link-btn', 'view');
  link.type = 'button';
  link.addEventListener('click', () => openConfigModal(fuzzer.fuzzer, fuzzer.versions));
  return link;
}

export function createFuzzerNameButton(fuzzer) {
  const payload = configPayload(fuzzer.versions);
  if (!payload) return el('div', null, fuzzer.fuzzer);
  const button = el('button', 'link-btn fuzzer-name-btn', fuzzer.fuzzer);
  button.type = 'button';
  button.addEventListener('click', () => openConfigModal(fuzzer.fuzzer, fuzzer.versions));
  return button;
}

export function applySearch() {
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

export function preferredTheme() {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function syncThemeToggle() {
  const button = byId('themeToggle');
  if (!button) return;
  button.textContent = FM_APP.state.theme === 'light' ? 'Dark mode' : 'Light mode';
}

export function applyTheme(theme) {
  FM_APP.state.theme = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', FM_APP.state.theme);
  localStorage.setItem(THEME_STORAGE_KEY, FM_APP.state.theme);
  syncThemeToggle();
  FM_APP.redrawAll();
}

export function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}
