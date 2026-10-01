# src/judgemetrics/metrics/adjustment/__init__.py
"""Risk adjustment (Phase 4): the expected-outcome model behind every adjusted figure.

- ``spec`` loads and validates ``data/reference/outcome_model.yaml``: the
  targets, the features with their known-at and leakage statements, the
  exclusions, the penalty and solver limits, the temporal split, the seed,
  the bootstrap, the pooling bounds, the thresholds, and the recovery
  tolerances.
- ``features`` builds one design row per eligible index event from the
  analytic frame, every history feature read strictly before the index
  case's filing, rows and levels ordered by source-assigned keys.
- ``logistic`` fits the L2-penalized logistic regression by Newton-Raphson,
  deterministically (no BLAS reduction, no randomness).
- ``resample`` draws the person-cluster bootstrap weights from seeded streams.
- ``diagnostics`` computes the temporal-split calibration, Brier score,
  ROC AUC, calibration slope, feature stability, and the complete-case refit.
- ``artifacts`` renders a fitted model as canonical JSON and writes it once,
  content-addressed, under the snapshot directory.
- ``fit`` fits a frame's (``fit_frame``) or a snapshot's (``fit_models``)
  models; ``catalog`` records them in ``outcome_model`` and lists, shows,
  and verifies them (``judgemetrics models fit|list|show|verify``), and
  reads them back from their artifacts for the compute.
- ``expected`` (Phase 4 Step 3) scores a design with a model's published
  coefficients and sums each judge's expected count; ``pooling`` fits the
  gamma–Poisson shape and gives the pooled ratio and its weight;
  ``bootstrap`` replays the fit's person-cluster replicates for the
  interval; ``ratios`` turns them into the ``observed_expected`` drafts.

Nothing here reads the ``restricted`` schema or names a restricted attribute.
"""
