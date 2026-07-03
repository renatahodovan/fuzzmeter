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

import {
  byId,
  el,
  fetchJSON,
  formatDuration,
  fmtInt,
} from './report-utils.js';
import {
  formatSourceFacts,
  invalidSourceText,
  measurementId,
  measurementKey,
  measurementSelection,
  measurementTitle,
} from './composite-shared.js';

const COMPOSITE_STATE = {
  measurements: [],
  invalidSources: [],
  runsRoot: '',
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
  COMPOSITE_STATE.runsRoot = data.runs_root || '';
  renderMeasurementOptions();
  const rootText = COMPOSITE_STATE.runsRoot ? ` Scanned: ${COMPOSITE_STATE.runsRoot}.` : '';
  setStatus(`${COMPOSITE_STATE.measurements.length} measurements. ${COMPOSITE_STATE.invalidSources.length} invalid source(s).${rootText}`);
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

function sourceRow(source) {
  const row = el('div', 'source-row');
  const main = el('div', 'source-main');
  main.appendChild(el('div', 'source-title', `${source.fuzzer || '-'} · ${source.benchmark || '-'} / ${source.fuzz_target || '-'}`));
  main.appendChild(el('div', 'muted small', `Run ${source.run_id || '-'} · Source ${source.source_id || '-'} · ${formatSourceFacts(source, formatDuration, fmtInt)}`));
  row.appendChild(main);
  const badges = el('div', 'source-badges');
  badges.appendChild(el('span', `badge ${source.origin === 'fresh' ? 'strong' : ''}`.trim(), source.origin || 'historical'));
  if (source.compatibility?.level) badges.appendChild(el('span', 'badge', source.compatibility.level));
  row.appendChild(badges);
  return row;
}

export function renderSourceSummary(data) {
  const panel = byId('sourcePanel');
  const list = byId('sourceList');
  if (!panel || !list) return;
  const sources = data?.sources || [];
  panel.hidden = !sources.length;
  list.textContent = '';
  sources.forEach((source) => list.appendChild(sourceRow(source)));
}

export function installCompositeControls(reloadReport) {
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
