/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Provides shared row comparators for report tables.
 */

export function compareNumericRows(left, right, key, direction) {
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
