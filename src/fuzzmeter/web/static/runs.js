/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Run list page state, rendering, and browser actions.
 */

import {
  formatSourceFacts,
  invalidSourceText,
  measurementId,
  measurementKey,
  measurementSelection,
  measurementTitle,
} from './report/composite-shared.js';
import { el, fetchJSON } from './report/dom.js';
import { fmtInt, formatDuration } from './report/format.js';

export const RUNS_STATE = {
  runs: [],
  measurements: [],
  invalidSources: [],
  filterText: '',
  selectedRuns: new Set(),
  selectedMeasurements: new Set(),
};

export function formatTs(ts) {
  if (!ts || !Number.isFinite(Number(ts))) return '—';
  return new Date(Number(ts) * 1000).toLocaleString();
}

export function selectedRunIds(state = RUNS_STATE) {
  return Array.from(state.selectedRuns);
}

export function selectedMeasurementIds(state = RUNS_STATE) {
  return Array.from(state.selectedMeasurements);
}

export function toggleRunSelection(state, runId) {
  if (state.selectedRuns.has(runId)) state.selectedRuns.delete(runId);
  else state.selectedRuns.add(runId);
}

export function toggleMeasurementSelection(state, measurementId) {
  if (state.selectedMeasurements.has(measurementId)) state.selectedMeasurements.delete(measurementId);
  else state.selectedMeasurements.add(measurementId);
}

export function normalizedStatusCounts(run) {
  const counts = run.summary?.status_counts || {};
  return Object.entries(counts).reduce((acc, [name, value]) => {
    const status = String(name || '');
    const count = Number(value || 0);
    if (!count) return acc;
    if (status === 'running') acc.running += count;
    else if (status === 'interrupted') acc.interrupted += count;
    else if (status === 'done') acc.done += count;
    else if (status.startsWith('failed')) acc.failed += count;
    else acc.other += count;
    return acc;
  }, { running: 0, interrupted: 0, failed: 0, done: 0, other: 0 });
}

export function statusBadge(run) {
  const counts = normalizedStatusCounts(run);
  if (counts.running > 0) return ['running', 'Running'];
  if (counts.interrupted > 0) return ['issues', 'Interrupted'];
  if (counts.failed > 0) return ['error', 'Failed'];
  if (counts.done > 0 && counts.done === Number(run.summary?.trials || 0)) return ['done', 'Done'];
  return ['', 'Recorded'];
}

export function statusSummaryText(run) {
  const counts = normalizedStatusCounts(run);
  const items = [];
  if (counts.running) items.push(`running: ${counts.running}`);
  if (counts.interrupted) items.push(`interrupted: ${counts.interrupted}`);
  if (counts.failed) items.push(`failed: ${counts.failed}`);
  if (counts.done) items.push(`done: ${counts.done}`);
  if (counts.other) items.push(`other: ${counts.other}`);
  return items.length ? items.join(' · ') : '—';
}

function runDirectoryName(run) {
  return run.directory_name;
}

export function matchesFilter(run, filterText) {
  if (!filterText) return true;
  const haystack = [
    runDirectoryName(run),
    run.run_id,
    run.label || '',
    ...(run.summary?.config?.fuzzers || []),
    ...(run.summary?.config?.targets || []),
    Object.keys(run.summary?.status_counts || {}),
    run.error || '',
  ].join('\n').toLowerCase();
  return haystack.includes(filterText);
}

export function visibleRunIds(runs, filterText) {
  const normalizedFilter = String(filterText || '').trim().toLowerCase();
  return runs.filter((run) => matchesFilter(run, normalizedFilter)).map(runDirectoryName);
}

export function toggleVisibleSelection(state, runIds) {
  const shouldSelectAll = runIds.some((runId) => !state.selectedRuns.has(runId));
  runIds.forEach((runId) => {
    if (shouldSelectAll) state.selectedRuns.add(runId);
    else state.selectedRuns.delete(runId);
  });
}

function updateSelectionUi(state = RUNS_STATE) {
  const selected = selectedRunIds(state);
  const selectedMeasurements = selectedMeasurementIds(state);
  document.querySelectorAll('.run-card').forEach((card) => {
    card.classList.toggle('selected', state.selectedRuns.has(card.dataset.runId));
  });
  document.querySelectorAll('.measurement-row').forEach((row) => {
    row.classList.toggle('selected', state.selectedMeasurements.has(row.dataset.measurementId));
  });
  const createButton = document.getElementById('btnCreateComposite');
  const selectedCount = document.getElementById('compositeSelectedCount');
  if (createButton) createButton.disabled = selectedMeasurements.length === 0;
  if (selectedCount) selectedCount.textContent = `${selectedMeasurements.length} selected`;
  document.getElementById('btnDeleteSelected').disabled = selected.length === 0;
}

function makeBadge(cls, text) {
  return el('span', `run-badge ${cls}`.trim(), text);
}

function configSection(title, builder) {
  const card = el('section', 'config-card');
  card.appendChild(el('div', 'config-card-title', title));
  builder(card);
  return card;
}

function appendPolicy(host, policy) {
  const dl = el('dl', 'config-kv');
  const rows = [
    ['Run time', formatDuration(policy.time_seconds, { coarse: true })],
    ['Repetitions', fmtInt(policy.repetitions)],
    ['Parallel jobs', fmtInt(policy.parallel_jobs)],
    ['Snapshot every', formatDuration(policy.snapshot_every_seconds, { coarse: true })],
  ];
  rows.forEach(([name, value]) => {
    dl.appendChild(el('dt', null, name));
    dl.appendChild(el('dd', null, value));
  });
  host.appendChild(dl);
}

function renderRunCard(run, state = RUNS_STATE) {
  const directoryName = runDirectoryName(run);
  const card = el('article', 'run-card');
  card.dataset.runId = directoryName;
  card.addEventListener('click', (event) => {
    if (event.target.closest('button, a')) return;
    toggleRunSelection(state, directoryName);
    updateSelectionUi(state);
  });
  const [statusClass, statusText] = statusBadge(run);
  const summary = run.summary || {};
  const config = summary.config || {};

  const head = el('div', 'run-card-head');
  const main = el('div', 'run-card-main');

  const titleWrap = el('div');
  const title = el('div', 'run-card-title mono', directoryName);
  title.title = `Run ID: ${run.run_id}`;
  titleWrap.appendChild(title);
  const subtitle = el('div', 'run-card-subtitle');
  subtitle.appendChild(el('span', null, `Created: ${formatTs(summary.created_ts)}`));
  subtitle.appendChild(el('span', null, `Updated: ${formatTs(run.updated_ts)}`));
  titleWrap.appendChild(subtitle);
  main.appendChild(titleWrap);
  head.appendChild(main);

  const badges = el('div', 'run-card-badges');
  badges.appendChild(makeBadge(statusClass, statusText));
  if (run.has_static_report) badges.appendChild(makeBadge('static', 'Static report available'));
  if (run.error) badges.appendChild(makeBadge('error', 'Metadata read error'));
  head.appendChild(badges);
  card.appendChild(head);

  const summaryRow = el('div', 'run-summary');
  const chips = [
    ['Fuzzers', summary.fuzzer_count, config.fuzzers?.length ? `${config.fuzzers.join(', ')}` : 'from trials'],
    ['Targets', summary.target_count, config.targets?.length ? config.targets.join(', ') : '—'],
    ['Trials', summary.trials, statusSummaryText(run)],
    ['Snapshots', summary.snapshots, 'captured'],
    ['Bugs', summary.bugs, 'unique records'],
  ];
  chips.forEach(([label, value, note]) => {
    const chip = el('div', 'summary-chip');
    chip.appendChild(el('div', 'summary-chip-label', label));
    chip.appendChild(el('div', 'summary-chip-value', fmtInt(value)));
    chip.appendChild(el('div', 'summary-chip-note', note));
    summaryRow.appendChild(chip);
  });
  summaryRow.appendChild(configSection('Run policy', (host) => appendPolicy(host, config.policy || {})));
  card.appendChild(summaryRow);

  const actions = el('div', 'run-actions');
  const actionsMain = el('div', 'run-actions-main');
  const openLive = el('button', 'btn', 'Open live');
  openLive.onclick = () => { location.href = `/run/${encodeURIComponent(directoryName)}`; };
  actionsMain.appendChild(openLive);

  if (run.has_static_report) {
    const openStatic = el('button', 'btn', 'Open static');
    openStatic.onclick = () => window.open(`/file/${encodeURIComponent(directoryName)}/report/report.html`, '_blank');
    actionsMain.appendChild(openStatic);
  }

  const generateStatic = el('button', 'btn', run.has_static_report ? 'Refresh static' : 'Generate static');
  generateStatic.onclick = async () => {
    generateStatic.disabled = true;
    const original = generateStatic.textContent;
    generateStatic.textContent = run.has_static_report ? 'Refreshing…' : 'Generating…';
    try {
      await fetchJSON(`/api/run/${encodeURIComponent(directoryName)}/generate`, { method: 'POST' });
      window.open(`/file/${encodeURIComponent(directoryName)}/report/report.html`, '_blank');
    } finally {
      generateStatic.disabled = false;
      generateStatic.textContent = original;
    }
  };
  actionsMain.appendChild(generateStatic);
  actions.appendChild(actionsMain);

  const actionsSide = el('div', 'run-actions-side');
  actionsSide.appendChild(el('div', 'run-action-help', 'Live reads the current DB. Static opens a saved snapshot report.'));
  const deleteBtn = el('button', 'btn danger', 'Delete');
  deleteBtn.onclick = async () => {
    if (!confirm(`Delete run ${directoryName}?`)) return;
    await fetchJSON(`/api/run/${encodeURIComponent(directoryName)}`, { method: 'DELETE' });
    await refresh(state);
  };
  actionsSide.appendChild(deleteBtn);
  actions.appendChild(actionsSide);
  card.appendChild(actions);

  if (run.error) {
    card.appendChild(el('div', 'muted small', `Metadata read error: ${run.error}`));
  }
  return card;
}

function renderRuns(state = RUNS_STATE) {
  const list = document.getElementById('runsList');
  const status = document.getElementById('statusLine');
  list.textContent = '';

  const filterText = state.filterText.trim().toLowerCase();
  const visibleRuns = state.runs.filter((run) => matchesFilter(run, filterText));
  if (!visibleRuns.length) {
    const empty = el('div', 'run-empty', state.runs.length ? 'No runs match the current filter.' : 'No runs found.');
    list.appendChild(empty);
    status.textContent = state.runs.length ? `Showing 0 of ${state.runs.length} runs.` : 'No runs found.';
    updateSelectionUi(state);
    return;
  }

  visibleRuns
    .slice()
    .sort((a, b) => String(runDirectoryName(b)).localeCompare(String(runDirectoryName(a))))
    .forEach((run) => list.appendChild(renderRunCard(run, state)));
  status.textContent = `Showing ${visibleRuns.length} of ${state.runs.length} runs.`;
  updateSelectionUi(state);
}

function renderCompatibilityPreview(measurements) {
  if (measurements.length <= 1) return 'Single measurement';
  const targets = new Set(measurements.map((measurement) => {
    const key = measurementKey(measurement);
    return `${key.benchmark || ''}\n${key.fuzz_target || ''}`;
  }));
  return targets.size === 1 ? 'Same target' : `${targets.size} targets`;
}

function renderCompositeMeasurements(state = RUNS_STATE) {
  const list = document.getElementById('measurementsList');
  const status = document.getElementById('measurementsStatusLine');
  if (!list || !status) return;
  list.textContent = '';

  const measurements = [...(state.measurements || [])].sort((left, right) => (
    measurementTitle(left).localeCompare(measurementTitle(right))
    || String(measurementKey(left).source_id || '').localeCompare(String(measurementKey(right).source_id || ''))
  ));
  if (!measurements.length) {
    list.appendChild(el(
      'div',
      'run-empty',
      'No measurements with composite metadata found. Runs created before composite descriptors were introduced appear as invalid sources.',
    ));
  }

  measurements.forEach((measurement) => {
    const id = measurementId(measurement);
    const row = el('button', 'measurement-row');
    row.type = 'button';
    row.dataset.measurementId = id;
    row.addEventListener('click', () => {
      toggleMeasurementSelection(state, id);
      updateSelectionUi(state);
    });
    const key = measurementKey(measurement);
    const main = el('div', 'measurement-main');
    main.appendChild(el('div', 'measurement-title', measurementTitle(measurement)));
    const subtitle = el('div', 'measurement-subtitle', `Run ${key.source_id || '—'}`);
    subtitle.title = `Run ID: ${key.run_id || '—'}\nPath: ${measurement.source_path || '—'}`;
    main.appendChild(subtitle);
    row.appendChild(main);
    const meta = el('div', 'measurement-meta');
    meta.appendChild(makeBadge(
      'static',
      formatSourceFacts(measurement, (seconds) => formatDuration(seconds, { coarse: true }), fmtInt),
    ));
    row.appendChild(meta);
    list.appendChild(row);
  });

  const invalid = state.invalidSources || [];
  if (invalid.length) {
    const invalidList = el('div', 'invalid-source-list');
    invalid.forEach((source) => invalidList.appendChild(el('div', 'invalid-source-row', invalidSourceText(source))));
    list.appendChild(invalidList);
  }
  status.textContent = `${measurements.length} measurements. ${invalid.length} invalid source(s).`;
  updateSelectionUi(state);
}

async function deleteSelectedRuns(state = RUNS_STATE) {
  const runIds = selectedRunIds(state);
  if (!runIds.length) return;
  if (!confirm(`Delete ${runIds.length} selected run(s)?`)) return;
  await fetchJSON('/api/runs/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_ids: runIds }),
  });
  await refresh(state);
}

async function createCompositeView(state = RUNS_STATE) {
  const selected = new Set(selectedMeasurementIds(state));
  const measurements = (state.measurements || []).filter((measurement) => selected.has(measurementId(measurement)));
  if (!measurements.length) return;
  const button = document.getElementById('btnCreateComposite');
  const preview = document.getElementById('compositePreview');
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = 'Creating…';
  }
  if (preview) preview.textContent = renderCompatibilityPreview(measurements);
  try {
    const view = await fetchJSON('/api/composite/views', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        measurements: measurements.map((measurement) => measurementSelection(measurement, 'historical')),
      }),
    });
    location.href = `/compare/${encodeURIComponent(view.view_id)}`;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

export async function refresh(state = RUNS_STATE) {
  const status = document.getElementById('statusLine');
  status.textContent = 'Loading runs…';
  const [data, composite] = await Promise.all([
    fetchJSON('/api/runs'),
    fetchJSON('/api/composite/sources/refresh', { method: 'POST' }),
  ]);
  state.runs = data.runs || [];
  state.measurements = composite.measurements || [];
  state.invalidSources = composite.invalid_sources || [];
  const runIds = new Set(state.runs.map(runDirectoryName));
  state.selectedRuns = new Set(Array.from(state.selectedRuns).filter((runId) => runIds.has(runId)));
  const measurementIds = new Set(state.measurements.map((measurement) => measurementId(measurement)));
  state.selectedMeasurements = new Set(Array.from(state.selectedMeasurements).filter((id) => measurementIds.has(id)));
  renderRuns(state);
  renderCompositeMeasurements(state);
}

export function installRunsPage(state = RUNS_STATE) {
  document.getElementById('searchRuns').addEventListener('input', (event) => {
    state.filterText = event.target.value || '';
    renderRuns(state);
  });

  document.getElementById('btnSelectAll').onclick = () => {
    toggleVisibleSelection(state, visibleRunIds(state.runs, state.filterText));
    updateSelectionUi(state);
  };

  document.getElementById('btnDeleteSelected').onclick = () => deleteSelectedRuns(state);
  document.getElementById('btnCreateComposite').onclick = () => createCompositeView(state);
  document.getElementById('btnRefresh').onclick = () => refresh(state);
  refresh(state);
}

if (typeof document !== 'undefined' && document.getElementById('runsList')) {
  installRunsPage();
}
