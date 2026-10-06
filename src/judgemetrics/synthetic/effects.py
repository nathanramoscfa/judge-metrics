# src/judgemetrics/synthetic/effects.py
"""The planted effects (``GENERATOR_VERSION`` 3): the known answer Phase 4 recovers.

Every functional form and constant the case simulation uses to make judges
differ, and the exact probability arithmetic ``truth.py`` needs to compute
the oracle expected counts under the generator's own rules
(docs/SYNTHETIC_DATA.md "Planted effects"):

- **Risk features** of a case at its filing (``risk_features``): the lead
  charge's severity, the charge count (1, 2, 3+), and the person's prior
  cases (0, 1, 2, 3+), prior convictions (0, 1, 2+), prior failures to
  appear (0, 1+), and whether another case is pending, each counted over
  the person's corpus records strictly before the start of the filing day
  (00:00 UTC, the instant the analytic frame's ``cases.filed_at``
  carries). They read observable rows only — never the propensity, the
  age, or the group — and never a row at or after the filing.
- **Risk index** ``R = sum(RISK_WEIGHTS[f] * code_f)`` over the features'
  numeric codes (``feature_codes``).
- **Assignment**: the initial judge is a ``weighted_choice`` among the
  judges serving the court that day with weight ``exp(docket_tilt * R)``.
  Within each court (a judge's first service record) the docket tilts are
  ordered inversely to the new-case effects, so the judge whose released
  defendants are least likely to file a new case draws the riskiest docket
  and the raw rates mislead (planted confounding).
- **Release** (a judge's discretionary pretrial decision):
  ``logistic(RELEASE_INTERCEPT[case_type] + sum(RELEASE_COEFFICIENTS[f] *
  code_f) + leniency)``; a release is then a recognizance or a posted bond,
  a refusal a detention or an unposted bond (subsequent draws).
- **Failure to appear** (a released case, on the hearing the Phase 2 rule
  picks): ``logistic(FTA_INTERCEPT + sum(FTA_COEFFICIENTS[f] * code_f) +
  FTA_PROPENSITY * propensity + FTA_AGE[band] + fta_effect)``, the effect
  being the releasing judge's (none for a statutory release).
- **Next filing**: the person's next case (when the allocation gives one)
  is filed ``int(U ** k * (span + 1))`` days into its span with ``k =
  max(EXPONENT_FLOOR, EXPONENT_BASE + EXPONENT_RISK * R + EXPONENT_PROPENSITY
  * propensity + EXPONENT_AGE[band] + new_case_effect)``, ``R`` being the
  previous (index) case's risk index: a larger ``k`` files sooner; the
  effect is the releasing judge's when the previous case was released by a
  judge, else none. The risk term is what lets the docket tilt mislead the
  raw new-case rates: without it the filing time would read no observable
  feature and adjustment would have nothing to correct.
- ``band`` is the ``age_band`` of the age at the index case's filing — the
  band the connector publishes — so the age effects are the restricted
  positive control no model feature carries; ``synthetic_group`` feeds no
  draw at all (the negative control).

The window probabilities (``window_probability``) are exact for the
generator's discretization: a day offset from a known distribution, then
one of the 540 business-hour minutes (08:00-16:59 UTC) uniformly.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta

from judgemetrics.synthetic.model import Case, Judge, RiskFeatures, World
from judgemetrics.synthetic.rng import uniform
from judgemetrics.synthetic.vocabulary import SEVERITY_RANK, SYNTHETIC_SEVERITIES, age_band_of

# --- the planted parameters -------------------------------------------------------------

# Judge effects: uniform on (-half-width, +half-width) per judge, in code order.
LENIENCY_HALF_WIDTH = 1.8  # release log-odds
NEW_CASE_EFFECT_HALF_WIDTH = 3.0  # next-filing skew exponent
FTA_EFFECT_HALF_WIDTH = 1.2  # failure-to-appear log-odds
DOCKET_TILT_HALF_WIDTH = 2.5  # assignment log-weight per unit of risk index

FEATURES: tuple[str, ...] = (
    "lead_severity",
    "charge_count",
    "prior_cases",
    "prior_convictions",
    "prior_failures_to_appear",
    "pending_case",
)
# Numeric code of the lead severity: the most severe charge scores highest.
SEVERITY_CODE: dict[str, int] = {
    s: len(SYNTHETIC_SEVERITIES) - 1 - SEVERITY_RANK[s] for s in SYNTHETIC_SEVERITIES
}

RISK_WEIGHTS: dict[str, float] = {
    "lead_severity": 0.25,
    "charge_count": 0.20,
    "prior_cases": 0.35,
    "prior_convictions": 0.30,
    "prior_failures_to_appear": 0.50,
    "pending_case": 0.40,
}
RELEASE_INTERCEPT: dict[str, float] = {"felony": 1.6, "misdemeanor": 2.4}
RELEASE_COEFFICIENTS: dict[str, float] = {
    "lead_severity": -0.30,
    "charge_count": -0.20,
    "prior_cases": -0.25,
    "prior_convictions": -0.30,
    "prior_failures_to_appear": -0.80,
    "pending_case": -0.50,
}
# A release is a recognizance with this share by case type (else a posted
# bond); a refusal is an unposted bond with this share (else a detention).
RECOGNIZANCE_SHARE: dict[str, float] = {"felony": 0.45, "misdemeanor": 0.70}
UNPOSTED_BOND_SHARE: dict[str, float] = {"felony": 0.45, "misdemeanor": 0.55}

FTA_INTERCEPT = -2.0
FTA_COEFFICIENTS: dict[str, float] = {
    "lead_severity": -0.05,
    "charge_count": 0.10,
    "prior_cases": 0.15,
    "prior_convictions": 0.10,
    "prior_failures_to_appear": 0.80,
    "pending_case": 0.30,
}
FTA_PROPENSITY = 1.5
EXPONENT_BASE = 0.6
EXPONENT_RISK = 3.0
EXPONENT_PROPENSITY = 2.0
EXPONENT_FLOOR = 0.25
# The restricted positive control: younger filing-age bands are likelier to
# fail to appear and file sooner; the unknown band never occurs in a draw
# (the generator always knows the true age) and carries no effect.
FTA_AGE: dict[str, float] = {
    "18-24": 0.60,
    "25-34": 0.30,
    "35-44": 0.0,
    "45-54": -0.30,
    "55+": -0.60,
    "unknown": 0.0,
}
EXPONENT_AGE: dict[str, float] = {
    "18-24": 0.60,
    "25-34": 0.30,
    "35-44": 0.0,
    "45-54": -0.20,
    "55+": -0.40,
    "unknown": 0.0,
}

# Business hours: a timestamp on a day is 08:00-16:59 UTC, one of 540 minutes.
BUSINESS_START = time(8, 0)
BUSINESS_MINUTES = 540


def parameters() -> dict[str, object]:
    """Every planted constant, as ``truth/effects.json`` records it."""
    return {
        "judge_effects": {
            "leniency_half_width": LENIENCY_HALF_WIDTH,
            "new_case_effect_half_width": NEW_CASE_EFFECT_HALF_WIDTH,
            "fta_effect_half_width": FTA_EFFECT_HALF_WIDTH,
            "docket_tilt_half_width": DOCKET_TILT_HALF_WIDTH,
        },
        "features": list(FEATURES),
        "severity_code": dict(SEVERITY_CODE),
        "risk_weights": dict(RISK_WEIGHTS),
        "release": {
            "intercept": dict(RELEASE_INTERCEPT),
            "coefficients": dict(RELEASE_COEFFICIENTS),
            "recognizance_share": dict(RECOGNIZANCE_SHARE),
            "unposted_bond_share": dict(UNPOSTED_BOND_SHARE),
        },
        "failure_to_appear": {
            "intercept": FTA_INTERCEPT,
            "coefficients": dict(FTA_COEFFICIENTS),
            "propensity": FTA_PROPENSITY,
            "age": dict(FTA_AGE),
        },
        "next_filing": {
            "exponent_base": EXPONENT_BASE,
            "exponent_risk": EXPONENT_RISK,
            "exponent_propensity": EXPONENT_PROPENSITY,
            "exponent_floor": EXPONENT_FLOOR,
            "age": dict(EXPONENT_AGE),
        },
    }


# --- judges ----------------------------------------------------------------------------


def home_court(judge: Judge) -> str:
    """The court of the judge's first service record."""
    return min(judge.services, key=lambda s: (s.start_date, s.court_code)).court_code


def build_effects(world: World, rng: random.Random) -> None:
    """Draw every judge's effects (code order), then order the tilts inversely per court.

    Per judge: ``leniency``, ``new_case_effect``, ``fta_effect``, and a raw
    tilt. Within each court's judges the raw tilts are then reassigned in
    descending order to the judges in ascending order of ``new_case_effect``
    (ties by code), so the tilts are a permutation of the draws.
    """
    raw_tilts: dict[str, float] = {}
    for judge in world.judges:
        judge.leniency = uniform(rng, -LENIENCY_HALF_WIDTH, LENIENCY_HALF_WIDTH)
        judge.new_case_effect = uniform(
            rng, -NEW_CASE_EFFECT_HALF_WIDTH, NEW_CASE_EFFECT_HALF_WIDTH
        )
        judge.fta_effect = uniform(rng, -FTA_EFFECT_HALF_WIDTH, FTA_EFFECT_HALF_WIDTH)
        raw_tilts[judge.code] = uniform(rng, -DOCKET_TILT_HALF_WIDTH, DOCKET_TILT_HALF_WIDTH)
    for court in world.court_codes:
        members = [judge for judge in world.judges if home_court(judge) == court]
        by_effect = sorted(members, key=lambda j: (j.new_case_effect, j.code))
        tilts = sorted((raw_tilts[j.code] for j in members), reverse=True)
        for judge, tilt in zip(by_effect, tilts, strict=True):
            judge.docket_tilt = tilt


# --- risk features ----------------------------------------------------------------------


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


def risk_features(case: Case, cases_of_person: Sequence[Case]) -> RiskFeatures:
    """The case's observable features from rows strictly before the start of its filing day.

    ``cases_of_person`` is every case of the person the caller knows (the
    earlier cases during the simulation, all of them afterwards); rows at or
    after the cutoff are ignored, so a later case, event, or sentence never
    changes the result.
    """
    cutoff = day_start(case.filed_date)
    lead = min(SEVERITY_RANK[charge.offense.severity] for charge in case.charges)
    others = [c for c in cases_of_person if c is not case and day_start(c.filed_date) < cutoff]
    convicted = sum(
        1
        for other in others
        if any(
            charge.convicted and charge.disposed_at is not None and charge.disposed_at < cutoff
            for charge in other.charges
        )
    )
    failures = sum(
        1
        for other in cases_of_person
        for event in other.events
        if event.event_type == "failure_to_appear" and event.event_at < cutoff
    )
    pending = any(
        (disposed := other.disposition_at) is None or disposed >= cutoff for other in others
    )
    return RiskFeatures(
        lead_severity=SYNTHETIC_SEVERITIES[lead],
        charge_count=min(3, len(case.charges)),
        prior_cases=min(3, len(others)),
        prior_convictions=min(2, convicted),
        prior_failures_to_appear=min(1, failures),
        pending_case=pending,
    )


def feature_codes(features: RiskFeatures) -> dict[str, int]:
    """The numeric code of every feature the linear forms multiply."""
    return {
        "lead_severity": SEVERITY_CODE[features.lead_severity],
        "charge_count": features.charge_count - 1,
        "prior_cases": features.prior_cases,
        "prior_convictions": features.prior_convictions,
        "prior_failures_to_appear": features.prior_failures_to_appear,
        "pending_case": int(features.pending_case),
    }


def _linear(coefficients: dict[str, float], features: RiskFeatures) -> float:
    codes = feature_codes(features)
    return sum(coefficients[name] * codes[name] for name in FEATURES)


def risk_index(features: RiskFeatures) -> float:
    return _linear(RISK_WEIGHTS, features)


def assignment_weights(judges: Sequence[Judge], index: float) -> list[tuple[Judge, float]]:
    """``(judge, exp(docket_tilt * risk index))`` for the judges serving the court that day."""
    return [(judge, math.exp(judge.docket_tilt * index)) for judge in judges]


def filing_age_band(case: Case) -> str:
    """The band of the person's age at the case's filing (the true date of birth)."""
    return age_band_of(case.person.age_on(case.filed_date))


# --- the probabilities --------------------------------------------------------------------


def logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def release_base_logit(case_type: str, features: RiskFeatures) -> float:
    return RELEASE_INTERCEPT[case_type] + _linear(RELEASE_COEFFICIENTS, features)


def fta_base_logit(features: RiskFeatures, propensity: float, band: str) -> float:
    return (
        FTA_INTERCEPT
        + _linear(FTA_COEFFICIENTS, features)
        + FTA_PROPENSITY * propensity
        + FTA_AGE[band]
    )


def base_exponent(index: float, propensity: float, band: str) -> float:
    """The next filing's skew exponent before the judge's effect and the floor."""
    return (
        EXPONENT_BASE
        + EXPONENT_RISK * index
        + EXPONENT_PROPENSITY * propensity
        + EXPONENT_AGE[band]
    )


def exponent(base: float, effect: float) -> float:
    return max(EXPONENT_FLOOR, base + effect)


def share_below(low: int, high: int, limit: int) -> float:
    """``P(randint(low, high) < limit)`` for a uniform integer draw."""
    count = min(high, limit - 1) - low + 1
    return max(0, min(count, high - low + 1)) / (high - low + 1)


# --- window probabilities ------------------------------------------------------------------


def minutes_in(day: date, low: datetime, high: datetime) -> int:
    """How many of ``day``'s 540 business-hour minutes lie in ``(low, high]``."""
    start = datetime.combine(day, BUSINESS_START, UTC)
    minute = timedelta(minutes=1)
    after = (low - start) // minute + 1  # the first minute strictly after low (floor division)
    until = (high - start) // minute  # the last minute at or before high
    first = max(0, after)
    last = min(BUSINESS_MINUTES - 1, until)
    return max(0, last - first + 1)


def window_probability(
    earliest: date,
    days: int,
    cdf: Callable[[int], float],
    low: datetime,
    high: datetime,
) -> float:
    """``P(low < t <= high)`` for ``t`` on day ``earliest + d`` at a uniform business minute.

    ``d`` takes ``0..days-1`` with ``cdf(m) = P(d <= m)``. Days strictly
    between ``low``'s and ``high``'s days lie wholly inside the window; the
    two boundary days contribute their share of minutes.
    """
    if high <= low or days <= 0:
        return 0.0

    def mass(first: int, last: int) -> float:
        first, last = max(first, 0), min(last, days - 1)
        if last < first:
            return 0.0
        return cdf(last) - (cdf(first - 1) if first > 0 else 0.0)

    low_offset = (low.date() - earliest).days
    high_offset = (high.date() - earliest).days
    total = 0.0
    for offset in sorted({low_offset, high_offset}):
        if 0 <= offset < days:
            day = earliest + timedelta(days=offset)
            total += mass(offset, offset) * minutes_in(day, low, high) / BUSINESS_MINUTES
    total += mass(low_offset + 1, high_offset - 1)
    return min(1.0, max(0.0, total))


def skewed_cdf(span: int, k: float) -> Callable[[int], float]:
    """``P(int(U ** k * (span + 1)) <= m) = ((m + 1) / (span + 1)) ** (1 / k)``."""

    def cdf(m: int) -> float:
        if m < 0:
            return 0.0
        if m >= span:
            return 1.0
        return float(((m + 1) / (span + 1)) ** (1.0 / k))

    return cdf


def uniform_cdf(days: int) -> Callable[[int], float]:
    def cdf(m: int) -> float:
        if m < 0:
            return 0.0
        return min(1.0, (m + 1) / days)

    return cdf


def before(earliest: date) -> datetime:
    """An instant before every business minute of ``earliest`` (a window's open lower end)."""
    return day_start(earliest) - timedelta(days=1)
