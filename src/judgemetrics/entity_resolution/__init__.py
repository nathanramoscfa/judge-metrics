# src/judgemetrics/entity_resolution/__init__.py
"""Staged person resolution (docs/ENTITY_RESOLUTION.md).

``config`` (model version, versioned thresholds), ``features`` (the pair
feature vector from hashes and case linkage — never a restricted value),
``deterministic`` (stable source identifiers), ``rules`` (reliable
combinations, never a name alone), ``scoring`` (the probabilistic stage,
stubbed until Phase 7), ``candidates`` (the audited candidate rows),
``merge`` (re-pointing every person-bearing row), ``audit`` (the
append-only log), ``queue`` (the manual-review queue), and ``pipeline``
(the hook the ingest runner calls, plus ``rerun``).
"""
