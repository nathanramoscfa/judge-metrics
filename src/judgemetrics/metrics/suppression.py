# src/judgemetrics/metrics/suppression.py
"""Small-cohort suppression: the flag every public surface honours.

``apply(draft, definition)`` returns the draft with ``suppressed_flag``
set when its denominator — ``cohort_size``: the followed members of a
fixed-window rate, the whole cohort of a survival estimate, the
attributed rows of a share, the values a median is taken over — is below
the metric's ``suppression_threshold`` (``data/reference/metric_registry.yaml``;
10 for every share, rate, survival estimate, and median, 0 for counts and
distributions, which are the sample sizes the presentation rules require
beside every rate). The stored row keeps its numbers so ``metrics verify``
can reproduce it; the API (Phase 3 Step 3) withholds the numerator,
denominator, value, and interval of a suppressed observation and says
the cohort was too small.
"""

from __future__ import annotations

from dataclasses import replace

from judgemetrics.metrics.compute import ObservationDraft
from judgemetrics.metrics.registry import MetricDefinitionSpec


def is_suppressed(cohort_size: int, threshold: int) -> bool:
    """Whether a denominator of ``cohort_size`` falls below ``threshold``."""
    return cohort_size < threshold


def apply(draft: ObservationDraft, definition: MetricDefinitionSpec) -> ObservationDraft:
    """The draft with ``suppressed_flag`` set per the definition's threshold."""
    if draft.slug != definition.slug:
        msg = f"draft {draft.slug!r} does not belong to definition {definition.slug!r}"
        raise ValueError(msg)
    flag = is_suppressed(draft.cohort_size, definition.suppression_threshold)
    if flag == draft.suppressed_flag:
        return draft
    return replace(draft, suppressed_flag=flag)
