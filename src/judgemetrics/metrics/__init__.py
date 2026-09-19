# src/judgemetrics/metrics/__init__.py
"""The metrics engine: the versioned registry and the analytic frame.

``registry`` loads and validates ``data/reference/metric_registry.yaml``
and mirrors it into ``metric_definition``; ``frame`` is the typed Polars
frame every metric is computed over; ``attribution`` is the inclusion gate
per registry rule; ``index_events``, ``exposure``, ``windows``,
``censoring``, and ``intervals`` are the pure functions that turn a frame
into cohorts, followed counts, windowed numerators, Kaplan-Meier estimates,
and intervals; ``methodology`` renders ``docs/METHODOLOGY.md`` from the
registry; ``snapshot`` exports the canonical tables to hashed Parquet and
loads a ``Frame`` per source through DuckDB views; ``compute`` dispatches
every registry metric to a pure function over the frame; ``suppression``
flags small cohorts; ``publish`` stores observations and members with
supersession; ``verify`` recomputes every current observation from its
snapshot; ``engine`` chains export, compute, and publish for the CLI and
pipeline step 13 (docs/ARCHITECTURE.md "Metrics engine").
"""
