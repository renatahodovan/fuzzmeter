# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Define domain objects for temporary composite report views.'''

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COMPATIBLE = 'compatible'
RISKY = 'risky'
INCOMPATIBLE = 'incompatible'

COMPOSITE_ORIGIN_FRESH = 'fresh'
COMPOSITE_ORIGIN_HISTORICAL = 'historical'
METADATA_JSON_SCHEMA_VERSION = 1


class CompositeViewExpired(LookupError):
    '''Raised when a temporary composite report view no longer exists.'''


@dataclass(frozen=True)
class CompositeMeasurementKey:
    '''Identify one fuzzer-target measurement inside a discovered run source.'''

    source_id: str
    run_id: str
    fuzzer: str
    benchmark: str
    fuzz_target: str

    def as_id(self) -> str:
        '''Return a stable string id for URLs and JSON payloads.'''
        return ':'.join(_escape(part) for part in (
            self.source_id,
            self.run_id,
            self.fuzzer,
            self.benchmark,
            self.fuzz_target,
        ))

    @classmethod
    def from_id(cls, value: str) -> 'CompositeMeasurementKey':
        '''Parse a stable string id produced by as_id().'''
        parts = [_unescape(part) for part in str(value).split(':')]
        if len(parts) != 5:
            raise ValueError(f'Composite measurement id must have 5 parts: {value!r}.')
        return cls(*parts)

    def to_json(self) -> dict[str, str]:
        '''Return a JSON-compatible representation.'''
        return {
            'source_id': self.source_id,
            'run_id': self.run_id,
            'fuzzer': self.fuzzer,
            'benchmark': self.benchmark,
            'fuzz_target': self.fuzz_target,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'CompositeMeasurementKey':
        '''Build a key from a JSON object.'''
        return cls(
            source_id=str(data.get('source_id') or ''),
            run_id=str(data.get('run_id') or ''),
            fuzzer=str(data.get('fuzzer') or ''),
            benchmark=str(data.get('benchmark') or ''),
            fuzz_target=str(data.get('fuzz_target') or ''),
        )


@dataclass(frozen=True)
class MeasurementMetadata:
    '''Hold comparable environment, config, and user source metadata.'''

    environment: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    environment_digest: str | None = None
    config_digest: str | None = None
    source_digest: str | None = None

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'schema_version': METADATA_JSON_SCHEMA_VERSION,
            'environment': self.environment,
            'config': self.config,
            'source': self.source,
            'digests': {
                'environment': self.environment_digest,
                'config': self.config_digest,
                'source': self.source_digest,
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'MeasurementMetadata':
        '''Build metadata from a JSON object.'''
        digests = data.get('digests') if isinstance(data.get('digests'), dict) else {}
        return cls(
            environment=_dict_or_empty(data.get('environment')),
            config=_dict_or_empty(data.get('config')),
            source=_dict_or_empty(data.get('source')),
            environment_digest=_str_or_none(digests.get('environment') or data.get('environment_digest')),
            config_digest=_str_or_none(digests.get('config') or data.get('config_digest')),
            source_digest=_str_or_none(digests.get('source') or data.get('source_digest')),
        )


@dataclass(frozen=True)
class CompositeMeasurement:
    '''Describe one selectable fuzzer-target measurement descriptor.'''

    key: CompositeMeasurementKey
    source_path: Path
    db_path: Path
    metadata: MeasurementMetadata
    runtime_seconds: int = 0
    repetitions: int = 0
    created_at: int | None = None
    tags: tuple[str, ...] = ()
    display_name: str | None = None

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'id': self.key.as_id(),
            'key': self.key.to_json(),
            'source_path': str(self.source_path),
            'source_db_path': str(self.db_path),
            'metadata': self.metadata.to_json(),
            'runtime_seconds': self.runtime_seconds,
            'repetitions': self.repetitions,
            'created_at': self.created_at,
            'tags': list(self.tags),
            'display_name': self.display_name,
        }


@dataclass(frozen=True)
class CompositeSource:
    '''Describe one discovered run directory or invalid source.'''

    source_id: str
    path: Path
    db_path: Path
    status: str = 'ok'
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'source_id': self.source_id,
            'path': str(self.path),
            'db_path': str(self.db_path),
            'status': self.status,
            'error': self.error,
        }


@dataclass(frozen=True)
class CompositeDiscovery:
    '''Hold all discovered descriptors and invalid sources.'''

    measurements: tuple[CompositeMeasurement, ...] = ()
    invalid_sources: tuple[CompositeSource, ...] = ()


@dataclass(frozen=True)
class CompatibilityIssue:
    '''Describe one compatibility or risk signal for the user.'''

    domain: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'domain': self.domain,
            'severity': self.severity,
            'message': self.message,
            'details': self.details,
        }


@dataclass(frozen=True)
class CompatibilityResult:
    '''Summarize composite measurement compatibility signals.'''

    level: str
    issues: tuple[CompatibilityIssue, ...] = ()
    diffs: tuple[dict[str, Any], ...] = ()
    environment_diff: dict[str, Any] = field(default_factory=dict)
    config_diff: dict[str, Any] = field(default_factory=dict)
    source_diff: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'level': self.level,
            'issues': [issue.to_json() for issue in self.issues],
            'diffs': list(self.diffs),
            'environment_diff': self.environment_diff,
            'config_diff': self.config_diff,
            'source_diff': self.source_diff,
        }


@dataclass(frozen=True)
class CompositeSelection:
    '''Describe one selected measurement inside a temporary view.'''

    selection_id: str
    key: CompositeMeasurementKey
    origin: str = COMPOSITE_ORIGIN_HISTORICAL
    display_fuzzer: str | None = None

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'selection_id': self.selection_id,
            'key': self.key.to_json(),
            'measurement_id': self.key.as_id(),
            'origin': self.origin,
            'display_fuzzer': self.display_fuzzer,
        }


@dataclass(frozen=True)
class CompositeView:
    '''Hold serve-lifetime selected measurements for one report view.'''

    view_id: str
    selections: tuple[CompositeSelection, ...]
    created_at: int
    updated_at: int

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {
            'view_id': self.view_id,
            'selections': [selection.to_json() for selection in self.selections],
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _escape(value: str) -> str:
    return str(value).replace('%', '%25').replace(':', '%3A')


def _unescape(value: str) -> str:
    return str(value).replace('%3A', ':').replace('%25', '%')
