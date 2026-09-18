# src/judgemetrics/entity_resolution/rules.py
"""Stage 2: rule-based matching on highly reliable combinations — never a name alone.

In order, the first rule whose condition holds decides:

| Rule                                                         | Decision   | Score | Reason                 |
|--------------------------------------------------------------|------------|-------|------------------------|
| same name and date of birth, and a shared case or a related-case link | matched | 0.98 | ``name_dob_case_link`` |
| same name and date of birth, same court, age consistent, no contradiction | review | 0.70 | ``name_dob_same_court`` |
| same name, a date of birth missing on either side            | rejected   | 0.10  | ``name_only``          |
| same name, both dates of birth known and different           | rejected   | 0.02  | ``dob_differs``        |

Anything else yields no decision here and falls to the probabilistic
stage. The review score sits deliberately below the auto-match threshold
so a same-court coincidence is queued for a person, never merged by a
rule; the two rejections are what "never merge people on name alone"
means in code.
"""

from __future__ import annotations

from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.config import STAGE_RULE
from judgemetrics.entity_resolution.features import PairFeatures
from judgemetrics.entity_resolution.stages import StageResult

REASON_NAME_DOB_CASE_LINK = "name_dob_case_link"
REASON_NAME_DOB_SAME_COURT = "name_dob_same_court"
REASON_NAME_ONLY = "name_only"
REASON_DOB_DIFFERS = "dob_differs"

SCORE_NAME_DOB_CASE_LINK = 0.98
SCORE_NAME_DOB_SAME_COURT = 0.70
SCORE_NAME_ONLY = 0.10
SCORE_DOB_DIFFERS = 0.02


def decide(features: PairFeatures) -> StageResult | None:
    """The first rule that applies, or ``None`` when no rule does."""
    if features.same_name_dob and (features.shared_case or features.related_case_link):
        return StageResult(
            ResolutionDecision.MATCHED,
            SCORE_NAME_DOB_CASE_LINK,
            STAGE_RULE,
            REASON_NAME_DOB_CASE_LINK,
        )
    if (
        features.same_name_dob
        and features.same_court
        and features.age_consistent
        and not features.dob_differs
    ):
        return StageResult(
            ResolutionDecision.REVIEW,
            SCORE_NAME_DOB_SAME_COURT,
            STAGE_RULE,
            REASON_NAME_DOB_SAME_COURT,
        )
    if features.same_name and features.dob_missing_either:
        return StageResult(
            ResolutionDecision.REJECTED, SCORE_NAME_ONLY, STAGE_RULE, REASON_NAME_ONLY
        )
    if features.same_name and features.dob_differs:
        return StageResult(
            ResolutionDecision.REJECTED, SCORE_DOB_DIFFERS, STAGE_RULE, REASON_DOB_DIFFERS
        )
    return None
