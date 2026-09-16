# src/judgemetrics/ingest/registry.py
"""Registry of source connectors, keyed by the docs/DATA_SOURCES.md name.

Empty until Phase 1 Step 3 registers the FJC connector; a connector may
be registered only for a source whose register entry is marked verified.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_source(name: str, factory: Callable[..., Any]) -> None:
    if name in _REGISTRY:
        msg = f"source {name!r} is already registered"
        raise ValueError(msg)
    _REGISTRY[name] = factory


def registered_sources() -> list[str]:
    return sorted(_REGISTRY)
