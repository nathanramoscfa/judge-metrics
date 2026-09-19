# src/judgemetrics/metrics/__init__.py
"""The metrics engine: the versioned registry and the analytic frame.

``registry`` loads and validates ``data/reference/metric_registry.yaml``
and mirrors it into ``metric_definition``; ``frame`` is the typed Polars
frame every metric is computed over; ``attribution`` is the inclusion gate
per registry rule; ``index_events``, ``exposure``, ``windows``,
``censoring``, and ``intervals`` are the pure functions that turn a frame
into cohorts, followed counts, windowed numerators, Kaplan-Meier estimates,
and intervals; ``methodology`` renders ``docs/METHODOLOGY.md`` from the
registry (docs/ARCHITECTURE.md "Metrics engine"). Phase 3 Step 2 adds the
snapshot loader, the compute dispatch, suppression, publishing, and
verification on top of these modules.
"""
