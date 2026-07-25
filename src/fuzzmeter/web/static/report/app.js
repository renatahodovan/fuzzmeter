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

import {
  applySearch,
  applyTheme,
  assignFuzzerColors,
  byId,
  debounce,
  el,
  fetchJSON,
  FM_APP,
  fmt,
  fmtInt,
  formatExecCount,
  median,
  preferredTheme,
  fuzzerColor,
  sanitizeId,
} from './report-utils.js';
import {
  installElementExportMenu,
} from './charts.js';
import {
  deriveReportData,
  installBenchmarkFilter,
  installFuzzerFilter,
  renderBenchmarkFilterOptions,
  renderFuzzerFilterOptions,
  selectNewFilterEntries,
  selectedFuzzerNames,
} from './filters.js';
import {
  installCompositeControls,
} from './composite.js';
import { createTargetSection } from './page.js';

function compareSummaryRows(left, right, key, direction) {
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
    Number.isFinite(Number(row.relcov_score)) || Number.isFinite(Number(row.relbug_score))
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
  const showPairwiseColumns = syncPairwiseRankingColumns(data);

  const rows = [...(data.summary?.rankings || [])].sort((left, right) => (
    compareSummaryRows(left, right, FM_APP.state.summarySort.key, FM_APP.state.summarySort.direction)
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
    tr.appendChild(el('td', 'num', fmtInt(row.exclusive_coverage_count)));
    const relbugCell = el('td', 'num', row.relbug_score === null ? '—' : fmt(row.relbug_score, 2));
    relbugCell.hidden = !showPairwiseColumns;
    tr.appendChild(relbugCell);
    tr.appendChild(el('td', 'num', fmtInt(row.unique_bug_count)));
    tr.appendChild(el('td', 'num', fmtInt(row.exclusive_bug_count)));
    tr.appendChild(el('td', 'num', formatExecCount(row.median_execs_done)));
    rankingsBody.appendChild(tr);
  });

  updateSummarySortIndicators();
  installRankingExport();
}

function bestRowByKey(rows, key) {
  return [...rows]
    .filter((row) => Number.isFinite(Number(row?.[key])))
    .sort((left, right) => compareSummaryRows(left, right, key, 'desc'))[0] || null;
}

function summarizeTargetMetric(targets, extractor) {
  const valuesByFuzzer = new Map();
  targets.forEach((target) => {
    (target.fuzzers || []).forEach((entry) => {
      const value = extractor(entry);
      if (!Number.isFinite(Number(value))) return;
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
  text.appendChild(el('div', 'muted small', formatter(winner.value)));
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
  const execRows = summarizeTargetMetric(data.targets || [], (entry) => entry.final?.execs_per_sec_median);
  const relCovRows = rankingRows.map((row) => ({ fuzzer: row.fuzzer, value: row.relcov_score }));
  const exclusiveCoverageRows = rankingRows.map((row) => ({ fuzzer: row.fuzzer, value: row.exclusive_coverage_count }));

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
      description: 'Reaches a large share of final coverage early in the run.',
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
      description: 'Reaches the largest total branch set that no other fuzzer reaches.',
      winner: bestRowByKey(exclusiveCoverageRows.map((row) => ({ ...row, value: row.value })), 'value'),
      formatter: (value) => `${fmtInt(value)} branches`,
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
    if (!Number.isFinite(Number(value))) return;
    host.appendChild(winnerCard(card.title, card.description, { fuzzer: card.winner.fuzzer, value }, card.formatter));
  });
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

function renderView(data) {
  FM_APP.data = data;
  const meta = data.meta || {};
  const overview = data.overview || {};
  const subtitleParts = [meta.run_id || overview.run_id || 'run'];
  if (overview.elapsed_human) subtitleParts.push(`running for ${overview.elapsed_human}`);
  else if (overview.created_at || meta.generated_at) subtitleParts.push(overview.created_at || meta.generated_at);
  byId('runSubtitle').textContent = subtitleParts.join(' • ');

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
  FM_APP.redrawAll = () => renderFromState();
  byId('searchBox').oninput = applySearch;
  byId('themeToggle').onclick = () => applyTheme(FM_APP.state.theme === 'light' ? 'dark' : 'light');

  window.addEventListener('resize', debounce(() => FM_APP.redrawAll(), 120));
  applyTheme(preferredTheme());
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
