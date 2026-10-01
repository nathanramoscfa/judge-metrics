# src/judgemetrics/validation/fairness.py
"""Subgroup calibration over the restricted attributes: aggregate cells only.

This is the one module of the code base that reads the ``restricted``
schema (``tests/unit/test_restricted_readers.py`` holds it to that), and
it reads it on the ingest role's session alone: ``subgroup_calibration``
refuses any other session before it runs a statement (the app role holds
no privilege on the schema and would fail with ``InsufficientPrivilege``
anyway).

``subgroup_calibration(session, snapshot, models, settings=, spec=)``:

1. **One statement** (``attribute_statement``, parameterized): for every
   index event the models score — a pretrial decision, by its id — the
   values of the restricted attributes of the decision's defendant case
   party (decision → its case and person → ``case_party`` → the attribute
   rows). A decision whose party carries two different values of one
   attribute (two merged participants of one case) has none for it.
2. **Per model and attribute**, the pure ``calibration_cells`` aggregates
   the index events of each vocabulary value: their number, the observed
   outcomes ``O``, the expected count ``E`` (the sum of the predicted
   probabilities from the published coefficients — the model never reads
   the attribute), the ratio ``O / E``, and its 95% percentile interval over
   the stored bootstrap replicates (per replicate the person-cluster
   weights of the fit and that replicate's coefficients: ``sum w y / sum w
   p_r``). A cell with fewer than ``minimum_cohort`` index events, or fewer
   than ``minimum_expected`` expected events, or without a fitted model, is
   withheld with its reason (``below_threshold``, ``expected_below_minimum``,
   ``model_unavailable``, the metrics' suppression order) and carries no
   figure at all.

The attribute of an individual index event exists only inside
``subgroup_calibration``'s own frame: it is never logged, written, cached,
or returned, and the log line carries counts only. The function returns
``SubgroupCell``s and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import ARRAY, Select, and_, any_, bindparam, distinct, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import CaseParty, Decision, PartyAttribute
from judgemetrics.logging import get_logger
from judgemetrics.metrics.adjustment.expected import ModelParameters
from judgemetrics.metrics.adjustment.features import DesignFrame
from judgemetrics.metrics.adjustment.logistic import FloatArray, predict
from judgemetrics.metrics.adjustment.resample import replicate_stream, replicates
from judgemetrics.metrics.adjustment.spec import RESTRICTED_KIND, OutcomeModelSpec, load_spec
from judgemetrics.metrics.intervals import round6
from judgemetrics.metrics.snapshot import Snapshot
from judgemetrics.metrics.suppression import adjusted_reason
from judgemetrics.normalization import vocabulary
from judgemetrics.validation.inputs import ModelInput
from judgemetrics.validation.statistics import quantile

log = get_logger(__name__)

DEFENDANT = "defendant"
# A replicate's person-cluster weights and its predicted probabilities, per design row.
Replicate = tuple[FloatArray, FloatArray]


class FairnessError(RuntimeError):
    """The analysis was asked to run on a session that is not the ingest role's."""


@dataclass(frozen=True, slots=True)
class CellFigures:
    """One attribute value's aggregate over one model's index events (all None when withheld)."""

    value: str
    events: int | None
    observed: int | None
    expected: float | None
    ratio: float | None
    lower: float | None
    upper: float | None
    withheld: str | None


@dataclass(frozen=True, slots=True)
class SubgroupCell:
    """One published (or withheld) cell of the subgroup calibration."""

    source: str
    target: str
    window_days: int | None
    attribute: str
    value: str
    events: int | None
    observed: int | None
    expected: float | None
    ratio: float | None
    lower: float | None
    upper: float | None
    withheld: str | None

    @classmethod
    def of(cls, model: ModelInput, attribute: str, figures: CellFigures) -> SubgroupCell:
        return cls(
            source=model.source,
            target=model.target.name,
            window_days=model.window_days,
            attribute=attribute,
            value=figures.value,
            events=figures.events,
            observed=figures.observed,
            expected=figures.expected,
            ratio=figures.ratio,
            lower=figures.lower,
            upper=figures.upper,
            withheld=figures.withheld,
        )


def _withheld(value: str, reason: str) -> CellFigures:
    return CellFigures(value, None, None, None, None, None, None, reason)


def calibration_cells(
    predictions: FloatArray | None,
    outcomes: FloatArray,
    groups: Sequence[str | None],
    replicates: Iterable[Replicate],
    *,
    values: Sequence[str],
    minimum_cohort: int,
    minimum_expected: float,
    level: float = 0.95,
) -> list[CellFigures]:
    """Per value of ``values`` (in that order): the cell's figures, or its withholding reason.

    ``groups`` gives each row's value (``None``: unrecorded, in no cell);
    ``predictions`` is ``None`` without a fitted model. ``replicates`` is
    consumed once, and only when some cell is published.
    """
    rows = outcomes.size
    if len(groups) != rows or (predictions is not None and predictions.size != rows):
        msg = "predictions, outcomes, and groups need one value per index event"
        raise ValueError(msg)
    position = {value: index for index, value in enumerate(values)}
    codes = np.fromiter(
        (-1 if group is None else position.get(group, -1) for group in groups),
        dtype=np.int64,
        count=rows,
    )
    member = codes >= 0
    cells = codes[member]
    count = len(values)
    events = np.bincount(cells, minlength=count)
    observed = np.rint(np.bincount(cells, weights=outcomes[member], minlength=count))
    expected = (
        None
        if predictions is None
        else np.bincount(cells, weights=predictions[member], minlength=count)
    )
    reasons = [
        adjusted_reason(
            int(events[index]),
            None if expected is None else float(expected[index]),
            threshold=minimum_cohort,
            minimum_expected=minimum_expected,
        )
        for index in range(count)
    ]
    draws: list[list[float]] = [[] for _ in range(count)]
    if predictions is not None and any(reason is None for reason in reasons):
        for weights, predicted in replicates:
            weighted = weights[member]
            o_r = np.bincount(cells, weights=weighted * outcomes[member], minlength=count)
            e_r = np.bincount(cells, weights=weighted * predicted[member], minlength=count)
            for index in range(count):
                if reasons[index] is None and e_r[index] > 0.0:
                    draws[index].append(float(o_r[index] / e_r[index]))
    tail = (1.0 - level) / 2.0
    result: list[CellFigures] = []
    for index, value in enumerate(values):
        reason = reasons[index]
        if reason is not None or expected is None:
            result.append(_withheld(value, reason or "model_unavailable"))
            continue
        lower = quantile(draws[index], tail)
        upper = quantile(draws[index], 1.0 - tail)
        result.append(
            CellFigures(
                value=value,
                events=int(events[index]),
                observed=int(observed[index]),
                expected=round6(float(expected[index])),
                ratio=round6(float(observed[index]) / float(expected[index])),
                lower=None if lower is None else round6(lower),
                upper=None if upper is None else round6(upper),
                withheld=None,
            )
        )
    return result


def replicate_draws(design: DesignFrame, parameters: ModelParameters) -> Iterator[Replicate]:
    """Each converged replicate's cluster weights and predictions (the fit's own streams)."""
    stream = replicate_stream(design.target, design.window_days)
    weights_of = replicates(
        design.clusters, seed=parameters.seed, stream=stream, count=len(parameters.replicates)
    )
    for coefficients, weights in zip(parameters.replicates, weights_of, strict=True):
        if coefficients is not None:
            yield weights, predict(coefficients, design.matrix)


def attribute_statement(attributes: Sequence[str]) -> Select[tuple[uuid.UUID, str, str, int]]:
    """Per decision id and attribute: the smallest value and the number of distinct values.

    The ids arrive as one bound array (``member_ids``); the attribute names
    as bound values. Nothing is interpolated.
    """
    return (
        select(
            Decision.id,
            PartyAttribute.attribute,
            func.min(PartyAttribute.value),
            func.count(distinct(PartyAttribute.value)),
        )
        .join(
            CaseParty,
            and_(
                CaseParty.case_id == Decision.case_id,
                CaseParty.person_id == Decision.person_id,
                CaseParty.party_type == DEFENDANT,
            ),
        )
        .join(PartyAttribute, PartyAttribute.case_party_id == CaseParty.id)
        .where(
            Decision.id == any_(bindparam("member_ids", type_=ARRAY(UUID(as_uuid=True)))),
            PartyAttribute.attribute.in_(list(attributes)),
        )
        .group_by(Decision.id, PartyAttribute.attribute)
    )


def require_ingest_role(session: Session, settings: Settings) -> None:
    """Refuse a session that is not connected as the configured ingest role."""
    expected = make_url(settings.effective_ingest_database_url).username
    current = session.scalar(select(func.current_user()))
    if not expected or current != expected:
        msg = "the subgroup calibration reads the restricted schema as the ingest role only"
        raise FairnessError(msg)


def subgroup_calibration(
    session: Session,
    snapshot: Snapshot,
    models: Sequence[ModelInput],
    *,
    settings: Settings,
    spec: OutcomeModelSpec | None = None,
) -> list[SubgroupCell]:
    """The aggregate cells of every model and restricted attribute (see the module docstring)."""
    require_ingest_role(session, settings)
    spec = spec or load_spec()
    attributes = vocabulary.values(RESTRICTED_KIND)
    member_ids = sorted({member for model in models for member in model.design.member_ids})
    known: dict[tuple[str, str], str] = {}
    if member_ids:
        result = session.execute(
            attribute_statement(attributes),
            {"member_ids": [uuid.UUID(member) for member in member_ids]},
        )
        for decision_id, attribute, value, distinct_values in result:
            if int(distinct_values) == 1:
                known[(str(decision_id), str(attribute))] = str(value)
    cells: list[SubgroupCell] = []
    for model in models:
        design = model.design
        parameters = model.parameters
        predictions = (
            predict(parameters.coefficients, design.matrix)
            if parameters.fitted and parameters.coefficients is not None
            else None
        )
        draws = [] if predictions is None else list(replicate_draws(design, parameters))
        for attribute in attributes:
            figures = calibration_cells(
                predictions,
                design.outcome,
                [known.get((member, attribute)) for member in design.member_ids],
                draws,
                values=vocabulary.values(attribute),
                minimum_cohort=spec.thresholds.minimum_cohort,
                minimum_expected=spec.thresholds.minimum_expected,
                level=spec.bootstrap.level,
            )
            cells.extend(SubgroupCell.of(model, attribute, item) for item in figures)
    known.clear()
    log.info(
        "validation.subgroup_calibration",
        snapshot=snapshot.content_hash,
        models=len(models),
        cells=len(cells),
        withheld=sum(1 for cell in cells if cell.withheld is not None),
    )
    return cells
