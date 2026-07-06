# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Expose composite measurement view helpers.'''

from __future__ import annotations

from .canonical import canonical_digest, canonical_json, canonical_value
from .compatibility import compare_metadata
from .discovery import discover_measurements, discover_sources
from .models import (
    COMPATIBLE,
    COMPOSITE_ORIGIN_FRESH,
    COMPOSITE_ORIGIN_HISTORICAL,
    INCOMPATIBLE,
    METADATA_JSON_SCHEMA_VERSION,
    RISKY,
    CompatibilityIssue,
    CompatibilityResult,
    CompositeDiscovery,
    CompositeMeasurement,
    CompositeMeasurementKey,
    CompositeSelection,
    CompositeSource,
    CompositeView,
    CompositeViewExpired,
    MetadataTriplet,
)
from .registry import CompositeRegistry, CompositeViewStore, selection_from_key

__all__ = [
    'COMPOSITE_ORIGIN_FRESH',
    'COMPOSITE_ORIGIN_HISTORICAL',
    'COMPATIBLE',
    'INCOMPATIBLE',
    'METADATA_JSON_SCHEMA_VERSION',
    'RISKY',
    'CompositeMeasurement',
    'CompositeMeasurementKey',
    'CompositeSelection',
    'CompositeDiscovery',
    'CompositeSource',
    'CompositeView',
    'CompositeViewExpired',
    'CompositeRegistry',
    'CompositeViewStore',
    'CompatibilityIssue',
    'CompatibilityResult',
    'MetadataTriplet',
    'canonical_digest',
    'canonical_json',
    'canonical_value',
    'compare_metadata',
    'discover_measurements',
    'discover_sources',
    'selection_from_key',
]
