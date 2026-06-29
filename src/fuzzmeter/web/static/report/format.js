/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Number and duration formatters for report views.
 */

import { cleanFloats } from './stats.js';

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
