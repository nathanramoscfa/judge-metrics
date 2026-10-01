# src/judgemetrics/validation/recovery.py
"""Recovery of the planted effects on the database path (a synthetic source only).

The synthetic generator plants a release, a new-case, and a
failure-to-appear effect per judge and writes the answer to
``truth/effects.json`` beside ``source/`` (docs/SYNTHETIC_DATA.md "Planted
effects"); no connector reads it. ``tests/golden/test_golden_recovery.py``
proves the estimator recovers it on the world built in memory; this module
checks the figures the database actually published, after ingest, entity
resolution, the snapshot, and the compute:

- ``read_truth(directory)`` reads ``manifest.json`` and
  ``truth/effects.json`` with ``json.loads`` from paths that must resolve
  inside ``directory``; ``truth_matches`` checks that the manifest is the
  one the source ingested (its sha256 among the source's retrieved
  artifacts), so a truth directory is never compared with another dataset.
- ``published_figures`` reads, in one statement, the current
  ``observed_expected`` observations of the snapshot and source with each
  judge's synthetic judge code (the source's own key for the truth's judge).
- ``evaluate`` (pure) takes, per fit the specification's ``recovery`` block
  names, the judges with at least ``minimum_followed_cohort`` members in the
  ratio and computes the Spearman correlation of the log pooled ratio with
  the court-centered planted effect, the sign agreement over the judges whose
  centered effect exceeds ``sign_agreement_above``, the raw rates' Spearman
  for contrast, the Pearson correlation of the expected counts with the
  oracle's ``expected_centered``, and the share of published intervals that
  cover the true ratio — each against the block's tolerance.

Only aggregates leave: no judge code, id, or judge-level figure is returned.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    SYNTHETIC_SOURCE_TYPE,
    Judge,
    MetricDefinition,
    MetricObservation,
    Source,
    SourceRecord,
)
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.metrics.adjustment.catalog import resolve_snapshot
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec, RecoveryFit
from judgemetrics.metrics.registry import OBSERVED_EXPECTED, Registry
from judgemetrics.validation.statistics import pearson, spearman

MANIFEST = "manifest.json"
EFFECTS = ("truth", "effects.json")
JUDGE_CODE = "synthetic_judge_code"
EVALUATED = "evaluated"
TOO_FEW_JUDGES = "too_few_judges"
MINIMUM_JUDGES = 3
FitKey = tuple[str, int | None]


class TruthError(RuntimeError):
    """The truth directory is missing, malformed, or describes another dataset."""


@dataclass(frozen=True, slots=True)
class Truth:
    """A synthetic dataset's manifest and planted effects."""

    manifest: Mapping[str, Any]
    effects: Mapping[str, Any]
    manifest_sha256: str

    @property
    def seed(self) -> int | None:
        value = self.manifest.get("seed")
        return None if value is None else int(value)

    @property
    def scale(self) -> str | None:
        value = self.manifest.get("scale")
        return None if value is None else str(value)

    @property
    def generator_version(self) -> str | None:
        value = self.manifest.get("generator_version")
        return None if value is None else str(value)

    @property
    def truth_version(self) -> str | None:
        value = self.effects.get("truth_version", self.manifest.get("truth_version"))
        return None if value is None else str(value)


@dataclass(frozen=True, slots=True)
class JudgeFigures:
    """One judge's published adjusted figures (in memory only)."""

    code: str
    cohort: int
    observed: int
    expected: float | None
    ratio: float | None
    lower: float | None
    upper: float | None


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """One fit's recovery figures against the specification's tolerances (aggregates only)."""

    target: str
    window_days: int | None
    status: str
    judges: int
    spearman: float | None
    spearman_minimum: float
    raw_spearman: float | None
    sign_checked: int
    sign_agreed: int
    sign_threshold: float
    expected_correlation: float | None
    expected_minimum: float
    coverage: float | None
    coverage_minimum: float

    @property
    def passed(self) -> bool:
        return (
            self.status == EVALUATED
            and self.spearman is not None
            and self.spearman >= self.spearman_minimum
            and self.sign_agreed == self.sign_checked
            and self.expected_correlation is not None
            and self.expected_correlation >= self.expected_minimum
            and self.coverage is not None
            and self.coverage >= self.coverage_minimum
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "window_days": self.window_days,
            "status": self.status,
            "judges": self.judges,
            "spearman": self.spearman,
            "spearman_minimum": self.spearman_minimum,
            "raw_spearman": self.raw_spearman,
            "sign_checked": self.sign_checked,
            "sign_agreed": self.sign_agreed,
            "sign_threshold": self.sign_threshold,
            "expected_correlation": self.expected_correlation,
            "expected_minimum": self.expected_minimum,
            "coverage": self.coverage,
            "coverage_minimum": self.coverage_minimum,
            "passed": self.passed,
        }


def _contained(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        msg = f"{'/'.join(parts)} does not lie inside the truth directory"
        raise TruthError(msg)
    return path


def _json(path: Path, name: str) -> tuple[Mapping[str, Any], bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        msg = f"the truth directory has no readable {name}"
        raise TruthError(msg) from exc
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        msg = f"{name} is not JSON"
        raise TruthError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"{name} is not a JSON object"
        raise TruthError(msg)
    return payload, data


def read_truth(directory: Path) -> Truth:
    """``manifest.json`` and ``truth/effects.json`` of a synthetic dataset directory."""
    root = directory.resolve()
    if not root.is_dir():
        msg = "the truth directory does not exist"
        raise TruthError(msg)
    manifest, manifest_bytes = _json(_contained(root, MANIFEST), MANIFEST)
    effects, _ = _json(_contained(root, *EFFECTS), "/".join(EFFECTS))
    for field_name in ("targets", "judges"):
        if not isinstance(effects.get(field_name), dict):
            msg = f"truth/effects.json has no {field_name!r} object"
            raise TruthError(msg)
    return Truth(
        manifest=manifest,
        effects=effects,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


def truth_matches(session: Session, source_id: uuid.UUID, truth: Truth) -> bool:
    """Whether the source ingested this manifest (its sha256 among the source's artifacts)."""
    found = session.scalar(
        select(SourceRecord.id)
        .where(
            SourceRecord.source_id == source_id,
            SourceRecord.raw_sha256 == truth.manifest_sha256,
        )
        .limit(1)
    )
    return found is not None


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def published_figures(
    session: Session,
    *,
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    registry: Registry,
) -> dict[FitKey, list[JudgeFigures]]:
    """Per (target, window): every judge's current adjusted figures (one statement)."""
    targets = {
        metric.slug: metric.adjustment.target
        for metric in registry.of_kind(OBSERVED_EXPECTED)
        if metric.adjustment is not None
    }
    rows = session.execute(
        select(
            MetricDefinition.slug,
            MetricObservation.window_days,
            Judge.external_ids[JUDGE_CODE].astext,
            MetricObservation.cohort_size,
            MetricObservation.observed_count,
            MetricObservation.expected_count,
            MetricObservation.standardized_ratio,
            MetricObservation.lower_confidence_bound,
            MetricObservation.upper_confidence_bound,
        )
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .join(Judge, Judge.id == MetricObservation.subject_id)
        .where(
            MetricObservation.source_id == source_id,
            MetricObservation.snapshot_id == snapshot_id,
            MetricObservation.superseded_at.is_(None),
            MetricObservation.subject_type == SubjectType.JUDGE,
            MetricDefinition.slug.in_(sorted(targets)),
        )
    ).all()
    figures: dict[FitKey, list[JudgeFigures]] = {}
    for slug, window, code, cohort, observed, expected, ratio, lower, upper in rows:
        if code is None:
            continue
        figures.setdefault((targets[str(slug)], window), []).append(
            JudgeFigures(
                code=str(code),
                cohort=int(cohort),
                observed=int(observed),
                expected=_float(expected),
                ratio=_float(ratio),
                lower=_float(lower),
                upper=_float(upper),
            )
        )
    return figures


def _truth_judges(effects: Mapping[str, Any], fit: RecoveryFit) -> Mapping[str, Any]:
    block = effects["targets"].get(fit.target)
    if not isinstance(block, dict):
        msg = f"truth/effects.json has no target {fit.target!r}"
        raise TruthError(msg)
    if fit.window_days is None:
        judges = block.get("judges")
    else:
        judges = block.get("windows", {}).get(str(fit.window_days), {}).get("judges")
    if not isinstance(judges, dict):
        msg = f"truth/effects.json has no judges for {fit.target}@{fit.window_days}"
        raise TruthError(msg)
    return judges


def evaluate(
    fit: RecoveryFit,
    figures: Sequence[JudgeFigures],
    effects: Mapping[str, Any],
    spec: OutcomeModelSpec,
) -> RecoveryResult:
    """One fit's recovery against the specification's tolerances (see the module docstring)."""
    recovery = spec.recovery
    truth = _truth_judges(effects, fit)
    effect = str(effects["targets"][fit.target]["effect"])
    planted = effects["judges"]
    kept = sorted(
        (
            item
            for item in figures
            if item.cohort >= recovery.minimum_followed_cohort
            and item.ratio is not None
            and item.ratio > 0.0
            and item.code in planted
            and item.code in truth
        ),
        key=lambda item: item.code,
    )
    base = RecoveryResult(
        target=fit.target,
        window_days=fit.window_days,
        status=TOO_FEW_JUDGES,
        judges=len(kept),
        spearman=None,
        spearman_minimum=recovery.spearman_minimum[fit.target],
        raw_spearman=None,
        sign_checked=0,
        sign_agreed=0,
        sign_threshold=recovery.sign_agreement_above,
        expected_correlation=None,
        expected_minimum=recovery.expected_correlation_minimum,
        coverage=None,
        coverage_minimum=recovery.interval_coverage_minimum,
    )
    if len(kept) < MINIMUM_JUDGES:
        return base
    centered = [float(planted[item.code]["centered"][effect]) for item in kept]
    log_ratio = [math.log(float(item.ratio or 0.0)) for item in kept]
    raw = [item.observed / item.cohort for item in kept]
    checked = agreed = 0
    for value, log_value in zip(centered, log_ratio, strict=True):
        if abs(value) > recovery.sign_agreement_above:
            checked += 1
            agreed += int(math.copysign(1.0, value) == math.copysign(1.0, log_value))
    expected_pairs = [
        (float(item.expected), float(truth[item.code]["expected_centered"]))
        for item in kept
        if item.expected is not None
    ]
    covered = [
        item.lower <= float(truth[item.code]["true_ratio"]) <= item.upper
        for item in kept
        if item.lower is not None
        and item.upper is not None
        and truth[item.code].get("true_ratio") is not None
    ]
    return RecoveryResult(
        target=base.target,
        window_days=base.window_days,
        status=EVALUATED,
        judges=len(kept),
        spearman=spearman(centered, log_ratio),
        spearman_minimum=base.spearman_minimum,
        raw_spearman=spearman(centered, raw),
        sign_checked=checked,
        sign_agreed=agreed,
        sign_threshold=base.sign_threshold,
        expected_correlation=pearson(
            [pair[0] for pair in expected_pairs], [pair[1] for pair in expected_pairs]
        ),
        expected_minimum=base.expected_minimum,
        coverage=None if not covered else sum(covered) / len(covered),
        coverage_minimum=base.coverage_minimum,
    )


def database_recovery(
    session: Session,
    *,
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    truth: Truth,
    spec: OutcomeModelSpec,
    registry: Registry,
) -> list[RecoveryResult]:
    """The recovery of every fit the specification names, from the published observations."""
    if not truth_matches(session, source_id, truth):
        msg = "the truth directory's manifest.json is not the one this source ingested"
        raise TruthError(msg)
    figures = published_figures(
        session, source_id=source_id, snapshot_id=snapshot_id, registry=registry
    )
    return [
        evaluate(fit, figures.get((fit.target, fit.window_days), []), truth.effects, spec)
        for fit in spec.recovery.fits
    ]


def recovery_for_truth(
    session: Session, truth: Truth, *, spec: OutcomeModelSpec, registry: Registry
) -> list[RecoveryResult]:
    """The recovery of the latest snapshot's published figures for the source the truth describes.

    ``TruthError`` when no synthetic source ingested the truth's manifest;
    ``CatalogError`` when no snapshot is recorded.
    """
    snapshot = resolve_snapshot(session, None)
    sources = session.scalars(
        select(Source.id).where(Source.source_type == SYNTHETIC_SOURCE_TYPE).order_by(Source.name)
    ).all()
    for source_id in sources:
        if truth_matches(session, source_id, truth):
            return database_recovery(
                session,
                source_id=source_id,
                snapshot_id=snapshot.id,
                truth=truth,
                spec=spec,
                registry=registry,
            )
    msg = "the truth directory's manifest.json is not the one any synthetic source ingested"
    raise TruthError(msg)
