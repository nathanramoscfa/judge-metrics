# src/judgemetrics/metrics/adjustment/availability.py
"""Whether a source can support a target (specification version 3, ``availability``).

A target is fitted for a source only when the source meets three conditions,
checked in this order, each failure recorded with the specification's own text
as the reason (``outcome_model.status = unavailable``, ``diagnostics.reason``):

1. ``gate`` — the source records the judge the target's population is
   attributed to (the registry gate of the population metric, e.g. the
   ``deciding_judge`` of a pretrial decision: ``source.capabilities``);
2. ``outcome`` — the source documents the target's outcome (the release
   target's outcome is the decision itself and is always documented);
3. ``person_key`` — when the specification has person-history features, the
   source's person key crosses cases (``cross_case``).

The rule reads only the snapshot's ``sources`` row, never a frame, so the
catalogue records every source's unavailable targets without building one.
"""

from __future__ import annotations

from judgemetrics.metrics.adjustment.spec import DECISION, OutcomeModelSpec, TargetSpec
from judgemetrics.metrics.registry import Registry, load_registry
from judgemetrics.metrics.snapshot import SourceRow


def unavailable_reason(
    spec: OutcomeModelSpec,
    target: TargetSpec,
    source: SourceRow,
    registry: Registry | None = None,
) -> str | None:
    """The reason the source cannot support ``target`` (``None``: it can)."""
    registry = registry or load_registry()
    gate = registry[target.population].attribution.assignment_gate
    if not source.capabilities.records_gate(gate):
        return spec.availability.gate
    if target.index != DECISION and target.outcome not in source.observable_outcomes:
        return spec.availability.outcome
    if spec.person_history_features and not source.capabilities.crosses_cases:
        return spec.availability.person_key
    return None
