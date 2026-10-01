# src/judgemetrics/validation/__init__.py
"""The validation of the expected-outcome models (Phase 4 Step 4, docs/VALIDATION.md).

Every diagnostic the brief's ``model_validation`` lists, assembled from a
snapshot's fitted models and their designs:

- ``inputs`` reads the snapshot's models (the catalogue rows and their
  artifacts) and builds each model's design from the snapshot's frame, in
  memory only;
- ``fairness`` is the subgroup calibration over the restricted attributes —
  the one module of the code base that reads the ``restricted`` schema, as
  the ingest role, publishing aggregate cells only;
- ``sensitivity`` compares the complete-case refit with the published fit;
- ``stability`` summarizes the bootstrap stability of the judge-level
  estimates as distributions (interval widths, the share excluding 1, rank
  intervals), never per judge;
- ``recovery`` checks the published pooled ratios of a synthetic source
  against its ``truth/effects.json``;
- ``report`` renders ``docs/VALIDATION.md`` deterministically and compares it
  (``judgemetrics validation report [--check]``).

``statistics`` holds the rank correlations and percentiles they share.
"""
