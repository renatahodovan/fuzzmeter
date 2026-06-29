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

export const RUNS_STATE = {
  runs: [],
  filterText: '',
  selectedRuns: new Set(),
};

export async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { cache: 'no-store', ...opts });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return await res.json();
}

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function fmtInt(value) {
  return value == null || Number.isNaN(Number(value)) ? '—' : String(Math.round(Number(value)));
}

export function formatTs(ts) {
  if (!ts || !Number.isFinite(Number(ts))) return '—';
  return new Date(Number(ts) * 1000).toLocaleString();
}

export function formatDuration(seconds) {
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

export function selectedRunIds(state = RUNS_STATE) {
  return Array.from(state.selectedRuns);
}

export function toggleRunSelection(state, runId) {
  if (state.selectedRuns.has(runId)) state.selectedRuns.delete(runId);
  else state.selectedRuns.add(runId);
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

export function matchesFilter(run, filterText) {
  if (!filterText) return true;
  const haystack = [
    run.run_id,
    ...(run.summary?.config?.fuzzers || []),
    ...(run.summary?.config?.targets || []),
    Object.keys(run.summary?.status_counts || {}),
    run.error || '',
  ].join('\n').toLowerCase();
  return haystack.includes(filterText);
}

export function visibleRunIds(runs, filterText) {
  const normalizedFilter = String(filterText || '').trim().toLowerCase();
  return runs.filter((run) => matchesFilter(run, normalizedFilter)).map((run) => run.run_id);
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
  document.querySelectorAll('.run-card').forEach((card) => {
    card.classList.toggle('selected', state.selectedRuns.has(card.dataset.runId));
  });
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
    ['Run time', formatDuration(policy.time_seconds)],
    ['Repetitions', fmtInt(policy.repetitions)],
    ['Parallel jobs', fmtInt(policy.parallel_jobs)],
    ['Snapshot every', formatDuration(policy.snapshot_every_seconds)],
  ];
  rows.forEach(([name, value]) => {
    dl.appendChild(el('dt', null, name));
    dl.appendChild(el('dd', null, value));
  });
  host.appendChild(dl);
}

function renderRunCard(run, state = RUNS_STATE) {
  const card = el('article', 'run-card');
  card.dataset.runId = run.run_id;
  card.addEventListener('click', (event) => {
    if (event.target.closest('button, a')) return;
    toggleRunSelection(state, run.run_id);
    updateSelectionUi(state);
  });
  const [statusClass, statusText] = statusBadge(run);
  const summary = run.summary || {};
  const config = summary.config || {};

  const head = el('div', 'run-card-head');
  const main = el('div', 'run-card-main');

  const titleWrap = el('div');
  titleWrap.appendChild(el('div', 'run-card-title mono', run.run_id));
  const subtitle = el('div', 'run-card-subtitle');
  subtitle.appendChild(el('span', null, `Created: ${formatTs(summary.created_ts)}`));
  subtitle.appendChild(el('span', null, `Updated: ${formatTs(run.updated_ts)}`));
  subtitle.appendChild(el('span', null, `Path: ${run.path}`));
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
  openLive.onclick = () => { location.href = `/run/${encodeURIComponent(run.run_id)}`; };
  actionsMain.appendChild(openLive);

  if (run.has_static_report) {
    const openStatic = el('button', 'btn', 'Open static');
    openStatic.onclick = () => window.open(`/file/${encodeURIComponent(run.run_id)}/report/report.html`, '_blank');
    actionsMain.appendChild(openStatic);
  }

  const generateStatic = el('button', 'btn', run.has_static_report ? 'Refresh static' : 'Generate static');
  generateStatic.onclick = async () => {
    generateStatic.disabled = true;
    const original = generateStatic.textContent;
    generateStatic.textContent = run.has_static_report ? 'Refreshing…' : 'Generating…';
    try {
      await fetchJSON(`/api/run/${encodeURIComponent(run.run_id)}/generate`, { method: 'POST' });
      window.open(`/file/${encodeURIComponent(run.run_id)}/report/report.html`, '_blank');
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
    if (!confirm(`Delete run ${run.run_id}?`)) return;
    await fetchJSON(`/api/run/${encodeURIComponent(run.run_id)}`, { method: 'DELETE' });
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
    .sort((a, b) => String(b.run_id).localeCompare(String(a.run_id)))
    .forEach((run) => list.appendChild(renderRunCard(run, state)));
  status.textContent = `Showing ${visibleRuns.length} of ${state.runs.length} runs.`;
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

async function refresh(state = RUNS_STATE) {
  const status = document.getElementById('statusLine');
  status.textContent = 'Loading runs…';
  const data = await fetchJSON('/api/runs');
  state.runs = data.runs || [];
  const runIds = new Set(state.runs.map((run) => run.run_id));
  state.selectedRuns = new Set(Array.from(state.selectedRuns).filter((runId) => runIds.has(runId)));
  renderRuns(state);
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
  document.getElementById('btnRefresh').onclick = () => refresh(state);
  refresh(state);
}

if (typeof document !== 'undefined' && document.getElementById('runsList')) {
  installRunsPage();
}
