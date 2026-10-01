<!-- docs/screenshots/phase04-step5/README.md -->
# Phase 4 Step 5 screenshots

The risk-adjusted surfaces in light and dark mode, captured with Playwright
(1440 pixels wide, Next's development indicator hidden) against the local
API and web app over the demo seed (`uv run poe bootstrap`: thirteen fitted
expected-outcome models, methodology 1.0) on 2026-10-01, for the Step 5 pull
request. Pages:

- `judge-adjusted-*.png` — the judge page's "Risk-adjusted comparison"
  panel at the 365-day window: per adjusted metric, the `AdjustedStat`
  (observed and expected events, the pooled ratio with its 95% bootstrap
  interval, the pooling weight in words, the sample size, the brief's
  interpretation, the period, the coverage, the cohort definition, the
  cohort position among the court's published ratios, the model link, and
  "Methodology 1.0") beside the raw rate it adjusts.
- `compare-adjusted-*.png` — `/compare` for the 365-day new-case ratio
  within the synthetic jurisdiction, sorted by the pooled ratio (the
  default), the judge from the panel highlighted, suppressed rows last with
  their reason, and the comparison notes with the pooling formula, the
  methodology and model links, and the interpretation.
- `model-card-*.png` — `/models/<id>` for that ratio's model (new case, 365
  days): status, training counts and range, versions, the temporal
  validation summary with the ten calibration bins, the coefficient table,
  and the links to the methodology section and the validation report.

Every judge and court shown is synthetic (the demo dataset's generated
names); no real person or court appears, and no key, pepper, or connection
string is on screen.
