# src/judgemetrics/entity_resolution/config.py
"""Model version and the versioned decision thresholds.

``MODEL_VERSION`` names the rule set every candidate row records; a
changed rule or score bumps it, so old candidates stay as history under
the old version. ``THRESHOLDS`` are the deliberately high auto-match and
deliberately low auto-reject boundaries of the probabilistic stage per
entity type; they are versioned data in
``data/reference/entity_resolution_thresholds.yaml`` (``version: 1``),
which this module loads with ``yaml.safe_load`` and a unit test asserts
equal to the constants below (docs/ENTITY_RESOLUTION.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
THRESHOLDS_PATH = REPO_ROOT / "data" / "reference" / "entity_resolution_thresholds.yaml"

MODEL_VERSION = "person-rules-v0"
# ``decided_by`` of every decision the stages make; a human reviewer label
# never starts with this prefix, which is how reruns tell them apart.
SYSTEM_ACTOR_PREFIX = "system:"
SYSTEM_ACTOR = f"{SYSTEM_ACTOR_PREFIX}{MODEL_VERSION}"

ENTITY_PERSON = "person"
ENTITY_JUDGE = "judge"
ENTITY_COURT = "court"
ENTITY_CASE = "case"
ENTITY_TYPES: tuple[str, ...] = (ENTITY_PERSON, ENTITY_JUDGE, ENTITY_COURT, ENTITY_CASE)

# Stage labels recorded on candidates and as ``person.resolution_status``
# of a surviving merge target.
STAGE_DETERMINISTIC = "deterministic"
STAGE_RULE = "rule"
STAGE_PROBABILISTIC = "probabilistic"
STAGE_REVIEW = "review"
STAGES: tuple[str, ...] = (STAGE_DETERMINISTIC, STAGE_RULE, STAGE_PROBABILISTIC, STAGE_REVIEW)

# ``person.resolution_status`` values outside the stage labels.
STATUS_MERGED = "merged"


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Probabilistic-stage boundaries: ``>= auto_match`` merges, ``< auto_reject`` rejects."""

    auto_match: float = 0.95
    auto_reject: float = 0.20

    def __post_init__(self) -> None:
        if not 0.0 <= self.auto_reject < self.auto_match <= 1.0:
            msg = (
                f"thresholds need 0 <= auto_reject < auto_match <= 1, got "
                f"{self.auto_reject} and {self.auto_match}"
            )
            raise ValueError(msg)


THRESHOLDS: Mapping[str, Thresholds] = {
    ENTITY_PERSON: Thresholds(auto_match=0.95, auto_reject=0.20),
    ENTITY_JUDGE: Thresholds(auto_match=0.95, auto_reject=0.20),
    ENTITY_COURT: Thresholds(auto_match=0.95, auto_reject=0.20),
    ENTITY_CASE: Thresholds(auto_match=0.95, auto_reject=0.20),
}
THRESHOLDS_VERSION = 1


class ThresholdsFileError(RuntimeError):
    """The thresholds file is missing or malformed (a deployment defect)."""


@lru_cache(maxsize=1)
def load_thresholds(path: Path = THRESHOLDS_PATH) -> tuple[int, Mapping[str, Thresholds]]:
    """``(version, {entity_type: Thresholds})`` from the YAML file; cached for the process."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"cannot read the entity-resolution thresholds at {path}: {exc}"
        raise ThresholdsFileError(msg) from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("version"), int)
        or payload["version"] < 1
        or not isinstance(payload.get("thresholds"), dict)
    ):
        msg = f"{path}: expected a mapping with a positive `version` and a `thresholds` mapping"
        raise ThresholdsFileError(msg)
    loaded: dict[str, Thresholds] = {}
    for entity_type, values in payload["thresholds"].items():
        if (
            not isinstance(entity_type, str)
            or not isinstance(values, dict)
            or set(values) != {"auto_match", "auto_reject"}
            or not all(isinstance(values[key], int | float) for key in values)
        ):
            msg = f"{path}: entry {entity_type!r} must map auto_match and auto_reject to numbers"
            raise ThresholdsFileError(msg)
        try:
            loaded[entity_type] = Thresholds(
                auto_match=float(values["auto_match"]), auto_reject=float(values["auto_reject"])
            )
        except ValueError as exc:
            msg = f"{path}: entry {entity_type!r}: {exc}"
            raise ThresholdsFileError(msg) from exc
    return int(payload["version"]), loaded


def thresholds_for(entity_type: str) -> Thresholds:
    """The configured thresholds of ``entity_type`` (``KeyError`` for an unknown type)."""
    return THRESHOLDS[entity_type]
