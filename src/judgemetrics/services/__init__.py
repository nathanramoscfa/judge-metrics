# src/judgemetrics/services/__init__.py
"""Application services: assemble response models from repository rows.

Routes handle HTTP (parameters, status codes, headers); services hold the
logic between a request and the queries — name normalization for search,
the similarity threshold, the provenance blocks — and return the schemas
in ``judgemetrics.schemas``. Statistical methodology never lives here;
it belongs to the metrics engine (Phase 3), separate from presentation.
"""
