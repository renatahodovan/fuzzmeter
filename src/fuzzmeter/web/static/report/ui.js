/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Stateful report UI helpers for cells, modals, search, and theme.
 */

import { byId, el } from './dom.js';
import { configPayload } from './report-data.js';
import { FM_APP, THEME_STORAGE_KEY } from './state.js';

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
