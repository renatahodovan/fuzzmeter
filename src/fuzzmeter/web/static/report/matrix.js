/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Filters report matrix payloads to selected fuzzers.
 */

export function cloneMatrixForSelected(matrixData, selectedSet) {
  if (!matrixData || !Array.isArray(matrixData.fuzzers)) return null;
  const indices = matrixData.fuzzers
    .map((fuzzer, index) => [String(fuzzer), index])
    .filter(([fuzzer]) => selectedSet.has(fuzzer));
  if (!indices.length) return null;
  const filterNumericMatrix = (matrix) => (
    Array.isArray(matrix)
      ? indices.map(([, rowIndex]) => indices.map(([, colIndex]) => {
        const value = (matrix[rowIndex] || [])[colIndex];
        return value === null || value === undefined || !Number.isFinite(Number(value)) ? null : Number(value);
      }))
      : undefined
  );
  const filterTextMatrix = (matrix) => (
    Array.isArray(matrix)
      ? indices.map(([, rowIndex]) => indices.map(([, colIndex]) => (
        (matrix[rowIndex] || [])[colIndex]
      )))
      : undefined
  );
  const filterNumericValues = (values, defaultValue = null) => (
    Array.isArray(values)
      ? indices.map(([, index]) => {
        const value = values[index];
        if (value === null || value === undefined || !Number.isFinite(Number(value))) return defaultValue;
        return Number(value);
      })
      : undefined
  );
  const filteredMatrix = filterNumericMatrix(matrixData.matrix);
  const pairwiseAny = filterNumericMatrix(matrixData.pairwise_unique_any);
  const pairwiseAll = filterNumericMatrix(matrixData.pairwise_unique_all);
  const numericValues = [filteredMatrix, pairwiseAny, pairwiseAll]
    .filter(Array.isArray)
    .flat(2)
    .filter((value) => value !== null && Number.isFinite(Number(value)))
    .map(Number);
  const exclusive = matrixData.exclusive ? {
    ...matrixData.exclusive,
    exclusive_any: filterNumericValues(matrixData.exclusive.exclusive_any),
    exclusive_all: filterNumericValues(matrixData.exclusive.exclusive_all),
    exclusive_any_bounds: Array.isArray(matrixData.exclusive.exclusive_any_bounds)
      ? indices.map(([, index]) => matrixData.exclusive.exclusive_any_bounds[index])
      : undefined,
    exclusive_all_bounds: Array.isArray(matrixData.exclusive.exclusive_all_bounds)
      ? indices.map(([, index]) => matrixData.exclusive.exclusive_all_bounds[index])
      : undefined,
  } : undefined;
  return {
    ...matrixData,
    fuzzers: indices.map(([fuzzer]) => fuzzer),
    matrix: filteredMatrix,
    pairwise_unique_any: pairwiseAny,
    pairwise_unique_all: pairwiseAll,
    pairwise_unique_any_bounds: filterTextMatrix(matrixData.pairwise_unique_any_bounds),
    pairwise_unique_all_bounds: filterTextMatrix(matrixData.pairwise_unique_all_bounds),
    exclusive,
    covered_counts: filterNumericValues(matrixData.covered_counts),
    unique_counts: filterNumericValues(matrixData.unique_counts),
    sample_sizes: filterNumericValues(matrixData.sample_sizes, 0),
    usable_sample_sizes: filterNumericValues(matrixData.usable_sample_sizes, 0),
    max_value: Math.max(0, ...numericValues),
    has_data: numericValues.some((value) => value > 0) || indices.length > 0,
  };
}
