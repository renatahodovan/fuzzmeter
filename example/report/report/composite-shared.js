/*
 * Copyright (c) 2026 Renata Hodovan, Akos Kiss.
 *
 * Licensed under the BSD 3-Clause License
 * <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
 * This file may not be copied, modified, or distributed except
 * according to those terms.
 */

/**
 * Shared browser helpers for composite measurement payloads.
 */

export function measurementKey(measurement) {
  return measurement?.key || measurement || {};
}

export function measurementId(measurement) {
  const key = measurementKey(measurement);
  return measurement?.id || key.id || [
    key.source_id,
    key.run_id,
    key.fuzzer,
    key.benchmark,
    key.fuzz_target,
  ].filter(Boolean).join(':');
}

export function measurementTitle(measurement, fallback = '—') {
  const key = measurementKey(measurement);
  return `${key.benchmark || fallback} / ${key.fuzz_target || fallback} / ${key.fuzzer || fallback}`;
}

export function measurementSelection(measurement, origin) {
  return { key: measurementKey(measurement), origin };
}

export function formatSourceFacts(source, formatDuration, fmtInt) {
  const facts = [];
  if (source.runtime_seconds != null) facts.push(`runtime ${formatDuration(source.runtime_seconds)}`);
  if (source.repetitions != null) facts.push(`repetitions ${fmtInt(source.repetitions)}`);
  const fuzzerInfo = source.metadata?.source?.fuzzer_version;
  if (fuzzerInfo && Object.keys(fuzzerInfo).length) facts.push('fuzzer info');
  return facts.join(' · ') || 'metadata only';
}

export function invalidSourceText(source) {
  return `${source?.source_id || 'source'}: ${source?.error || 'Unknown discovery error.'}`;
}
