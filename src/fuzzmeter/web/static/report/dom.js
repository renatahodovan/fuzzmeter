/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * DOM and browser utility helpers for the report UI.
 */

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

export function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}
