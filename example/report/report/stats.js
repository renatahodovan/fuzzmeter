/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * DOM-independent statistical helpers for report data.
 */

// Missing values (null, undefined, '') stay missing: Number() would silently turn them into 0.
export function finiteOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function isFiniteNumber(value) {
  return finiteOrNull(value) !== null;
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
  const sorted = (values || []).filter((value) => isFiniteNumber(value)).map(Number).sort((a, b) => a - b);
  return quantile(sorted, 0.5);
}

export function cleanFloats(values) {
  return (values || [])
    .filter((value) => isFiniteNumber(value))
    .map(Number);
}

export function rankdataDesc(values) {
  const indexed = values
    .map((value, index) => [index, value])
    .filter(([, value]) => isFiniteNumber(value))
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
