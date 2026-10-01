# src/judgemetrics/metrics/suppression.py
"""Small-cohort suppression: the flag every public surface honours, and its reason.

``apply(draft, definition)`` returns the draft with ``suppressed_flag`` set when its denominator
— ``cohort_size``: the followed members of a fixed-window rate, the whole cohort of a survival
estimate, the attributed rows of a share, the values a median is taken over, the members in an
observed-to-expected ratio — is below the metric's ``suppression_threshold``
(``data/reference/metric_registry.yaml``; 10 for every share, rate, survival estimate, and
median, 0 for counts and distributions, which are the sample sizes the presentation rules
require beside every rate, 30 for an observed-to-expected ratio), and the reason with it:
``below_threshold``. An ``observed_expected`` draft is also suppressed when its expected count
is below the metric's ``adjustment.minimum_expected`` (``expected_below_minimum``) or when it
has no expected count because its model is not fitted (``model_unavailable``), the reasons
checked in that order. The stored row keeps its numbers so ``metrics verify`` can reproduce it;
the API withholds the numerator, denominator, value, and interval of a suppressed observation
and says the cohort was too small.
"""

from __future__ import annotations

from dataclasses import replace

from judgemetrics.metrics.compute import ObservationDraft
from judgemetrics.metrics.registry import OBSERVED_EXPECTED, MetricDefinitionSpec

BELOW_THRESHOLD = "below_threshold"
EXPECTED_BELOW_MINIMUM = "expected_below_minimum"
MODEL_UNAVAILABLE = "model_unavailable"
REASONS: tuple[str, ...] = (BELOW_THRESHOLD, EXPECTED_BELOW_MINIMUM, MODEL_UNAVAILABLE)


def is_suppressed(cohort_size: int, threshold: int) -> bool:
    """Whether a denominator of ``cohort_size`` falls below ``threshold``."""
    return cohort_size < threshold


def adjusted_reason(
    cohort_size: int, expected: float | None, *, threshold: int, minimum_expected: float
) -> str | None:
    """Why an observed-to-expected ratio is withheld (``None`` when it is published).

    ``expected`` is ``None`` exactly when the ratio's model is not fitted.
    """
    if is_suppressed(cohort_size, threshold):
        return BELOW_THRESHOLD
    if expected is not None and expected < minimum_expected:
        return EXPECTED_BELOW_MINIMUM
    if expected is None:
        return MODEL_UNAVAILABLE
    return None


def reason_for(draft: ObservationDraft, definition: MetricDefinitionSpec) -> str | None:
    """The suppression reason the definition gives the draft (``None``: not suppressed)."""
    if definition.kind == OBSERVED_EXPECTED:
        if definition.adjustment is None:  # pragma: no cover - the registry requires it
            msg = f"{definition.slug}: an {OBSERVED_EXPECTED} needs its adjustment block"
            raise ValueError(msg)
        return adjusted_reason(
            draft.cohort_size,
            draft.expected_count,
            threshold=definition.suppression_threshold,
            minimum_expected=definition.adjustment.minimum_expected,
        )
    if is_suppressed(draft.cohort_size, definition.suppression_threshold):
        return BELOW_THRESHOLD
    return None


def apply(draft: ObservationDraft, definition: MetricDefinitionSpec) -> ObservationDraft:
    """The draft with ``suppressed_flag`` and ``suppression_reason`` set per the definition."""
    if draft.slug != definition.slug:
        msg = f"draft {draft.slug!r} does not belong to definition {definition.slug!r}"
        raise ValueError(msg)
    reason = reason_for(draft, definition)
    flag = reason is not None
    if flag == draft.suppressed_flag and reason == draft.suppression_reason:
        return draft
    return replace(draft, suppressed_flag=flag, suppression_reason=reason)
