# tests/golden/truth_map.py
"""The table from every ``truth/metrics.json`` path to its registry observation.

``expectations(block, subject_type)`` walks one subject's block of the
truth file and yields one ``Expectation`` per truth number: the registry
slug, the window and dimension value that identify the observation, and
the stored columns it must equal (``observed_count``, ``cohort_size``,
``eligible_count``, ``observed_rate``, ``value``, ``distribution``,
``lower_confidence_bound``, ``upper_confidence_bound``). The golden suite
compares each against the current ``metric_observation`` row, and the
unit suite against the drafts ``compute_frame`` returns for the same
world — one table, two readers, so a failure names the truth path, the
slug, the window, the dimension, and the column.

``docs/SYNTHETIC_DATA.md`` "The metric set" documents the same mapping
in prose.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

WINDOWS: tuple[int, ...] = (30, 90, 180, 365, 730, 1095)
# index kind → outcome → registry slug of the fixed-window rate.
RATE_SLUGS: dict[str, dict[str, str]] = {
    "pretrial_release": {
        "failure_to_appear": "failure_to_appear_rate",
        "new_case": "new_case_rate",
        "new_charge": "new_charge_rate",
        "reconviction": "reconviction_rate",
        "revocation": "revocation_rate",
    },
    "disposition": {
        "new_case": "new_case_rate_after_disposition",
        "new_charge": "new_charge_rate_after_disposition",
        "reconviction": "reconviction_rate_after_disposition",
        "revocation": "revocation_rate_after_disposition",
    },
    "sentence": {
        "new_case": "new_case_rate_after_sentence",
        "new_charge": "new_charge_rate_after_sentence",
        "reconviction": "reconviction_rate_after_sentence",
        "revocation": "revocation_rate_after_sentence",
    },
}
# index kind → outcome → registry slug of the Kaplan-Meier estimate.
SURVIVAL_SLUGS: dict[str, dict[str, str]] = {
    "pretrial_release": {
        "failure_to_appear": "failure_to_appear_survival",
        "new_case": "new_case_survival",
        "reconviction": "reconviction_survival",
    }
}
# The registry slugs whose outcome the synthetic source never documents.
NOT_OBSERVABLE_SLUGS: dict[str, str] = {
    "release_violation_rate": "release_violation",
    "rearrest_rate": "rearrest",
}
COURT_ONLY_SLUGS: frozenset[str] = frozenset(
    {"statutory_release_count", "unknown_actor_pretrial_count"}
)


@dataclass(frozen=True, slots=True)
class Expectation:
    """One truth number and the observation columns it fixes."""

    path: str
    slug: str
    window_days: int | None
    dimension_value: str | None
    columns: Mapping[str, Any]

    @property
    def label(self) -> str:
        window = "" if self.window_days is None else f"@{self.window_days}"
        dimension = "" if self.dimension_value is None else f"[{self.dimension_value}]"
        return f"{self.path} -> {self.slug}{window}{dimension}"


def _rate(path: str, slug: str, node: Mapping[str, Any], window: int | None = None) -> Expectation:
    return Expectation(
        path,
        slug,
        window,
        None,
        {
            "observed_count": node["numerator"],
            "cohort_size": node["denominator"],
            "observed_rate": node["value"],
        },
    )


def _median(path: str, slug: str, node: Mapping[str, Any], dimension: str | None) -> Expectation:
    return Expectation(
        path,
        slug,
        None,
        dimension,
        {"cohort_size": node["n"], "observed_count": node["n"], "value": node["value"]},
    )


def _count(path: str, slug: str, value: int) -> Expectation:
    return Expectation(path, slug, None, None, {"observed_count": value})


def expectations(block: Mapping[str, Any], subject_type: str) -> Iterator[Expectation]:
    """Every expectation of one subject's truth block (``judges.<code>`` or ``courts.<code>``)."""
    yield _count("eligible_cases", "eligible_cases", block["eligible_cases"])
    yield _count("eligible_defendants", "eligible_defendants", block["eligible_defendants"])
    pretrial = block["pretrial"]
    yield _count("pretrial.decisions", "pretrial_decisions", pretrial["decisions"])
    yield _count("pretrial.released_count", "pretrial_released", pretrial["released_count"])
    yield _count("pretrial.detained_count", "pretrial_detained", pretrial["detained_count"])
    yield _rate("pretrial.release_share", "pretrial_release_share", pretrial["release_share"])
    if subject_type == "court":
        yield _count(
            "pretrial.statutory_release_count",
            "statutory_release_count",
            pretrial["statutory_release_count"],
        )
        yield _count(
            "pretrial.unknown_actor_count",
            "unknown_actor_pretrial_count",
            pretrial["unknown_actor_count"],
        )
    for kind, outcomes in RATE_SLUGS.items():
        windows = block["index_events"][kind]["windows"]
        for window in WINDOWS:
            entry = windows[str(window)]
            for outcome, slug in outcomes.items():
                path = f"index_events.{kind}.windows.{window}.{outcome}_rate"
                rate = _rate(path, slug, entry[f"{outcome}_rate"], window)
                yield Expectation(
                    path,
                    slug,
                    window,
                    None,
                    {**rate.columns, "eligible_count": entry["cohort"]},
                )
            for outcome, slug in SURVIVAL_SLUGS.get(kind, {}).items():
                path = f"index_events.{kind}.windows.{window}.{outcome}_survival"
                survival = entry[f"{outcome}_survival"]
                yield Expectation(
                    path,
                    slug,
                    window,
                    None,
                    {
                        "eligible_count": entry["cohort"],
                        "cohort_size": entry["cohort"],
                        "observed_count": survival["events"],
                        "observed_rate": survival["value"],
                        "lower_confidence_bound": survival["lower"],
                        "upper_confidence_bound": survival["upper"],
                    },
                )
    yield _rate(
        "judicial_dismissal_rate", "judicial_dismissal_rate", block["judicial_dismissal_rate"]
    )
    distribution = block["disposition_distribution"]
    for value, count in distribution.items():
        yield Expectation(
            f"disposition_distribution.{value}",
            "disposition_distribution",
            None,
            value,
            {
                "observed_count": count,
                "cohort_size": sum(distribution.values()),
                "distribution": dict(distribution),
            },
        )
    yield _median(
        "median_days_to_disposition",
        "median_days_to_disposition",
        block["median_days_to_disposition"],
        None,
    )
    sentences = block["sentences"]
    yield _count("sentences.count", "sentence_count", sentences["count"])
    yield _median(
        "sentences.incarceration_days_median",
        "incarceration_days_median",
        sentences["incarceration_days_median"],
        None,
    )
    yield _median(
        "sentences.probation_days_median",
        "probation_days_median",
        sentences["probation_days_median"],
        None,
    )
    for category, node in sentences["incarceration_days_median_by_offense_category"].items():
        yield _median(
            f"sentences.incarceration_days_median_by_offense_category.{category}",
            "incarceration_days_median_by_offense_category",
            node,
            category,
        )


def subject_blocks(truth: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """``(subject_type, code, block)`` for every judge and court of the truth file."""
    for code, block in truth["judges"].items():
        yield "judge", code, block
    for code, block in truth["courts"].items():
        yield "court", code, block
