# src/judgemetrics/ingest/registry.py
"""Registry of source connectors, keyed by the docs/DATA_SOURCES.md name.

Connectors register themselves with the ``@register`` decorator; the
built-in connector modules are imported explicitly (``BUILTIN_CONNECTOR_MODULES``)
the first time a lookup happens, so registration never depends on import
side effects elsewhere. A connector may be registered only for a source
whose register entry is marked verified.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from judgemetrics.ingest.base import SourceConnector

BUILTIN_CONNECTOR_MODULES: tuple[str, ...] = ("judgemetrics.ingest.fjc.connector",)

_REGISTRY: dict[str, type[SourceConnector]] = {}
_loaded = False


class UnknownSourceError(KeyError):
    """No connector is registered for the source id."""


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    source_id: str
    parser_version: str


def register[C: SourceConnector](connector_cls: type[C]) -> type[C]:
    """Class decorator: register ``connector_cls`` under its ``source_id``."""
    source_id = getattr(connector_cls, "source_id", None)
    parser_version = getattr(connector_cls, "parser_version", None)
    if not isinstance(source_id, str) or not source_id:
        msg = f"{connector_cls.__name__} needs a non-empty `source_id`"
        raise ValueError(msg)
    if not isinstance(parser_version, str) or not parser_version:
        msg = f"{connector_cls.__name__} needs a non-empty `parser_version`"
        raise ValueError(msg)
    existing = _REGISTRY.get(source_id)
    if existing is not None and existing is not connector_cls:
        msg = f"source {source_id!r} is already registered by {existing.__name__}"
        raise ValueError(msg)
    _REGISTRY[source_id] = connector_cls
    return connector_cls


def load_builtin_connectors() -> None:
    global _loaded
    if _loaded:
        return
    for module in BUILTIN_CONNECTOR_MODULES:
        importlib.import_module(module)
    _loaded = True


def get_connector(source_id: str) -> SourceConnector:
    """A fresh connector instance for ``source_id``."""
    load_builtin_connectors()
    connector_cls = _REGISTRY.get(source_id)
    if connector_cls is None:
        raise UnknownSourceError(source_id)
    return connector_cls()


def registered_sources() -> list[RegisteredSource]:
    load_builtin_connectors()
    return [
        RegisteredSource(source_id=source_id, parser_version=cls.parser_version)
        for source_id, cls in sorted(_REGISTRY.items())
    ]
