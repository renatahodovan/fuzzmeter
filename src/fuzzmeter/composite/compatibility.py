# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Compare composite measurement metadata without auto-filtering user choices.'''

from __future__ import annotations

from typing import Any

from .models import COMPATIBLE, INCOMPATIBLE, RISKY, CompatibilityIssue, CompatibilityResult, MeasurementMetadata

TARGET_CONFIG_KEYS = {'benchmark', 'fuzz_target', 'input_mode', 'timeout'}
BENCHMARK_SOURCE_SCOPE = 'benchmark_source'


def compare_metadata(reference: MeasurementMetadata, candidate: MeasurementMetadata) -> CompatibilityResult:
    '''Compare two metadata triplets and return user-facing risk signals.'''
    issues: list[CompatibilityIssue] = []
    config_diff = diff_config(reference.config, candidate.config)
    environment_diff = diff_environment(reference, candidate)
    source_diff = diff_source(reference.source, candidate.source)

    target_diff, risky_config = split_config_diff(config_diff)
    if target_diff:
        issues.append(
            CompatibilityIssue(
                domain='config',
                severity='error',
                message='Measurement identity differs.',
                details=target_diff,
            )
        )
        return CompatibilityResult(
            level=INCOMPATIBLE,
            issues=tuple(issues),
            diffs=_diff_rows_for_issues(issues),
            environment_diff=environment_diff,
            config_diff=config_diff,
            source_diff=source_diff,
        )

    if environment_diff:
        issues.append(
            CompatibilityIssue(
                domain='environment',
                severity='warning',
                message='Environment metadata differs.',
                details=environment_diff,
            )
        )
    if risky_config:
        issues.append(
            CompatibilityIssue(
                domain='config',
                severity='warning',
                message='Measurement configuration differs.',
                details=risky_config,
            )
        )
    if source_diff:
        issues.append(
            CompatibilityIssue(
                domain='source',
                severity='warning',
                message='User source metadata is missing or differs.',
                details=source_diff,
            )
        )

    return CompatibilityResult(
        level=level_from_diffs(issues),
        issues=tuple(issues),
        diffs=_diff_rows_for_issues(issues),
        environment_diff=environment_diff,
        config_diff=config_diff,
        source_diff=source_diff,
    )


def diff_environment(reference: MeasurementMetadata, candidate: MeasurementMetadata) -> dict[str, Any]:
    '''Return a field-level environment diff.'''
    if (
        reference.environment_digest
        and candidate.environment_digest
        and reference.environment_digest == candidate.environment_digest
    ):
        return {}
    return _diff_dict(reference.environment, candidate.environment)


def diff_config(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    '''Return a field-level config diff.'''
    return _diff_dict(reference, candidate)


def split_config_diff(config_diff: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    '''Split config diffs into hard target mismatches and warnings.'''
    target_diff: dict[str, Any] = {}
    risky_config: dict[str, Any] = {}
    for key, value in config_diff.items():
        if key in TARGET_CONFIG_KEYS:
            target_diff[key] = value
        else:
            risky_config[key] = value
    return target_diff, risky_config


def diff_source(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    '''Return a field-level benchmark source metadata diff.'''
    target_diff = _diff_source_scope(reference, candidate, BENCHMARK_SOURCE_SCOPE)
    return {BENCHMARK_SOURCE_SCOPE: target_diff} if target_diff else {}


def level_from_diffs(issues: list[CompatibilityIssue]) -> str:
    '''Return the compatibility level implied by issues.'''
    if any(issue.severity == 'error' for issue in issues):
        return INCOMPATIBLE
    if issues:
        return RISKY
    return COMPATIBLE


def _diff_source_scope(reference: dict[str, Any], candidate: dict[str, Any], scope: str) -> dict[str, Any]:
    ref_scope = reference.get(scope)
    cand_scope = candidate.get(scope)
    ref_missing = not _scope_has_data(ref_scope)
    cand_missing = not _scope_has_data(cand_scope)
    if ref_missing or cand_missing:
        return {'metadata': {'reference': _presence_label(ref_missing), 'candidate': _presence_label(cand_missing)}}
    return _diff_dict(_scope_data(ref_scope), _scope_data(cand_scope))


def _scope_has_data(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get('status') != 'ok':
        return False
    data = value.get('data')
    return isinstance(data, dict) and bool(data)


def _scope_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get('data')
    return data if isinstance(data, dict) else {}


def _presence_label(missing: bool) -> str:
    return 'missing' if missing else 'present'


def _diff_rows_for_issues(issues: list[CompatibilityIssue]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for issue in issues:
        rows.extend(_diff_rows(issue.domain, issue.severity, issue.message, issue.details))
    return tuple(rows)


def _diff_rows(
    domain: str,
    severity: str,
    message: str,
    diff: dict[str, Any],
    prefix: str = '',
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in diff.items():
        path = f'{prefix}.{key}' if prefix else str(key)
        if _is_leaf_diff(value):
            rows.append(
                {
                    'domain': domain,
                    'path': path,
                    'severity': severity,
                    'message': message,
                    'reference': value.get('reference'),
                    'candidate': value.get('candidate'),
                }
            )
        elif isinstance(value, dict):
            rows.extend(_diff_rows(domain, severity, message, value, path))
    return rows


def _is_leaf_diff(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {'reference', 'candidate'}


def _diff_dict(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(reference) | set(candidate))
    diff: dict[str, Any] = {}
    for key in keys:
        left = reference.get(key)
        right = candidate.get(key)
        if left == right:
            continue
        if isinstance(left, dict) and isinstance(right, dict):
            child = _diff_dict(left, right)
            if child:
                diff[key] = child
        else:
            diff[key] = {'reference': left, 'candidate': right}
    return diff
