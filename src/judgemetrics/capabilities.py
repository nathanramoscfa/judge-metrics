# src/judgemetrics/capabilities.py
"""What a source can record about judges and persons: its capabilities (Phase 5 Step 5).

Every connector declares them in ``SourceInfo.capabilities``; the ingest
runner stores them in ``source.capabilities`` (JSONB, written only when it
differs); the snapshot exports them with the source; the analytic frame carries
them; the metrics engine and the outcome-model catalogue read them:

- ``judge_gates`` — the judge assignment gates of the metric registry the source
  records (``deciding_judge``, ``assigned_at_time``, ``assigned_ever``,
  ``sentencing_judge``, ``disposing_judge``). For a judge subject, a metric
  whose gate the source does not record yields ``NotAttributable`` — no
  observation, never a zero. ``court_of_case`` is not a judge gate: a court's
  metrics are always computed over the court's cases.
- ``person_key_scope`` — how far the source's person key reaches:
  ``cross_case`` (one person across the source's cases), ``case`` (a person is
  a case participation: no person can be followed from one case to another),
  or ``None`` for a source that records no person at all (a reference source).
- ``revocation_scopes`` — which revocations the source documents: ``release``
  (a revoked pretrial release) and ``supervision`` (a revoked probation,
  parole, or other supervision a sentence imposed). The registry declares the
  scope a revocation has after each index event (``revocation_scopes``), so a
  source that documents only revoked supervision observes the revocation rates
  after a disposition and after a sentence and not the rate after a pretrial
  release.

The values are fixed enumerations checked on construction, so a misdeclared
connector fails when it is imported, never at compute time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# The judge assignment gates of the metric registry (metrics.registry.ASSIGNMENT_GATES
# less court_of_case, which never attributes a row to a judge).
JUDGE_GATES: tuple[str, ...] = (
    "deciding_judge",
    "assigned_at_time",
    "assigned_ever",
    "sentencing_judge",
    "disposing_judge",
)
CROSS_CASE = "cross_case"
CASE = "case"
PERSON_KEY_SCOPES: tuple[str, ...] = (CROSS_CASE, CASE)
RELEASE = "release"
SUPERVISION = "supervision"
REVOCATION_SCOPES: tuple[str, ...] = (RELEASE, SUPERVISION)


class CapabilityError(ValueError):
    """A declared capability is not one of the fixed values."""


def _ordered(values: Iterable[str], allowed: tuple[str, ...], name: str) -> tuple[str, ...]:
    """``values`` checked against ``allowed``, once each, in ``allowed`` order."""
    given = list(values)
    unknown = sorted(set(given) - set(allowed))
    if unknown:
        msg = f"{name}: {unknown} are not among {list(allowed)}"
        raise CapabilityError(msg)
    if len(set(given)) != len(given):
        msg = f"{name}: a value is listed twice"
        raise CapabilityError(msg)
    return tuple(value for value in allowed if value in given)


@dataclass(frozen=True, slots=True)
class SourceCapabilities:
    """The judge gates, person-key scope, and revocation scopes a source records."""

    judge_gates: tuple[str, ...] = ()
    person_key_scope: str | None = None
    revocation_scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "judge_gates", _ordered(self.judge_gates, JUDGE_GATES, "judge_gates")
        )
        object.__setattr__(
            self,
            "revocation_scopes",
            _ordered(self.revocation_scopes, REVOCATION_SCOPES, "revocation_scopes"),
        )
        if self.person_key_scope is not None and self.person_key_scope not in PERSON_KEY_SCOPES:
            msg = (
                f"person_key_scope: {self.person_key_scope!r} is not one of "
                f"{list(PERSON_KEY_SCOPES)} or null"
            )
            raise CapabilityError(msg)

    @classmethod
    def full(cls) -> SourceCapabilities:
        """Every gate, a cross-case person key, every revocation scope (the synthetic source)."""
        return cls(JUDGE_GATES, CROSS_CASE, REVOCATION_SCOPES)

    @classmethod
    def from_json(cls, value: Mapping[str, Any] | None) -> SourceCapabilities:
        """The ``source.capabilities`` JSONB (an empty or missing value records nothing)."""
        if not value:
            return cls()
        if not isinstance(value, Mapping):
            msg = "capabilities must be a mapping"
            raise CapabilityError(msg)
        unknown = sorted(set(value) - {"judge_gates", "person_key_scope", "revocation_scopes"})
        if unknown:
            msg = f"capabilities carry unknown keys {unknown}"
            raise CapabilityError(msg)
        scope = value.get("person_key_scope")
        return cls(
            judge_gates=tuple(str(item) for item in value.get("judge_gates") or ()),
            person_key_scope=None if scope is None else str(scope),
            revocation_scopes=tuple(str(item) for item in value.get("revocation_scopes") or ()),
        )

    def as_json(self) -> dict[str, Any]:
        """The ``source.capabilities`` JSONB value (lists in the enumerations' order)."""
        return {
            "judge_gates": list(self.judge_gates),
            "person_key_scope": self.person_key_scope,
            "revocation_scopes": list(self.revocation_scopes),
        }

    def records_gate(self, gate: str) -> bool:
        return gate in self.judge_gates

    @property
    def crosses_cases(self) -> bool:
        return self.person_key_scope == CROSS_CASE
