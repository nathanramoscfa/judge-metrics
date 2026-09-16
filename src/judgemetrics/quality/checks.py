# src/judgemetrics/quality/checks.py
"""Data-quality checks over the drafts of one ingest run.

Each check returns ``IssueDraft``s that the runner persists as
``data_quality_issue`` rows linked to the run's source records and, once
published, to the entity they concern. Descriptions name identifiers
(node ids, court names, dates) and never carry raw rows.

Checks from the brief's list implemented here: judge service dates
temporally valid (``service_dates_valid``), judge assignment overlaps
inspected (``service_overlap``), source provenance complete and source
hashes present (``provenance_complete``); ``missing_start_date`` records
appointments the source has not dated yet.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from judgemetrics.db.models.enums import IssueSeverity
from judgemetrics.ingest.base import JudgeServiceDraft, NaturalKey, TaggedRecord

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

SERVICE_DATES_INVALID = "service_dates_invalid"
SERVICE_OVERLAP = "service_overlap"
MISSING_START_DATE = "missing_start_date"
PROVENANCE_INCOMPLETE = "provenance_incomplete"


@dataclass(frozen=True, slots=True)
class IssueDraft:
    entity_type: str
    entity_key: NaturalKey | None
    severity: IssueSeverity
    issue_code: str
    description: str
    source_record_id: uuid.UUID | None = None


def _label(service: JudgeServiceDraft) -> str:
    judge = ":".join(service.judge_key[1:])
    court = service.court_key[1] if len(service.court_key) > 1 else "?"
    return f"judge {judge} at {court!r} as {service.position_type}"


def _services(tagged: Iterable[TaggedRecord]) -> list[tuple[JudgeServiceDraft, uuid.UUID | None]]:
    return [
        (item.record, item.provenance.source_record_id if item.provenance else None)
        for item in tagged
        if isinstance(item.record, JudgeServiceDraft)
    ]


def service_dates_valid(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: a service record whose end date precedes its start date."""
    issues: list[IssueDraft] = []
    for service, record_id in _services(tagged):
        if (
            service.start_date is not None
            and service.end_date is not None
            and service.end_date < service.start_date
        ):
            issues.append(
                IssueDraft(
                    entity_type="judge_service",
                    entity_key=service.natural_key,
                    severity=IssueSeverity.ERROR,
                    issue_code=SERVICE_DATES_INVALID,
                    description=(
                        f"{_label(service)}: end date {service.end_date.isoformat()} precedes "
                        f"start date {service.start_date.isoformat()}"
                    ),
                    source_record_id=record_id,
                )
            )
    return issues


def _overlaps(first: JudgeServiceDraft, second: JudgeServiceDraft) -> bool:
    """Strict overlap: two intervals that merely touch (end == start) do not overlap."""
    if first.start_date is None or second.start_date is None:
        return False
    first_end = first.end_date or date.max
    second_end = second.end_date or date.max
    return first.start_date < second_end and second.start_date < first_end


def service_overlap(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Warning: the same judge at the same court in overlapping intervals."""
    groups: dict[tuple[NaturalKey, NaturalKey], list[tuple[JudgeServiceDraft, uuid.UUID | None]]]
    groups = defaultdict(list)
    for service, record_id in _services(tagged):
        groups[(service.judge_key, service.court_key)].append((service, record_id))
    issues: list[IssueDraft] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(
            members, key=lambda pair: (pair[0].start_date or date.min, pair[0].position_type)
        )
        for index, (later, record_id) in enumerate(ordered):
            for earlier, _ in ordered[:index]:
                if _overlaps(earlier, later):
                    issues.append(
                        IssueDraft(
                            entity_type="judge_service",
                            entity_key=later.natural_key,
                            severity=IssueSeverity.WARNING,
                            issue_code=SERVICE_OVERLAP,
                            description=(
                                f"{_label(later)} from {_iso(later.start_date)} to "
                                f"{_iso(later.end_date)} overlaps service as "
                                f"{earlier.position_type} from {_iso(earlier.start_date)} to "
                                f"{_iso(earlier.end_date)}"
                            ),
                            source_record_id=record_id,
                        )
                    )
    return issues


def missing_start_date(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Info: a service record the source has not dated (no commission or recess date)."""
    return [
        IssueDraft(
            entity_type="judge_service",
            entity_key=service.natural_key,
            severity=IssueSeverity.INFO,
            issue_code=MISSING_START_DATE,
            description=f"{_label(service)}: no start date in the source",
            source_record_id=record_id,
        )
        for service, record_id in _services(tagged)
        if service.start_date is None
    ]


def provenance_complete(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: a draft without a source record, or one whose record lacks a sha256."""
    issues: list[IssueDraft] = []
    for item in tagged:
        key = item.record.natural_key
        if item.provenance is None:
            problem = "no source record"
        elif not _SHA256.match(item.provenance.raw_sha256):
            problem = "source record without a sha256"
        else:
            continue
        issues.append(
            IssueDraft(
                entity_type=key[0],
                entity_key=key,
                severity=IssueSeverity.ERROR,
                issue_code=PROVENANCE_INCOMPLETE,
                description=f"{key[0]} {':'.join(key[1:])}: {problem}",
                source_record_id=item.provenance.source_record_id if item.provenance else None,
            )
        )
    return issues


CHECKS = (service_dates_valid, service_overlap, missing_start_date, provenance_complete)


def run_checks(tagged: Sequence[TaggedRecord]) -> list[IssueDraft]:
    """Every check over the run's drafts, in a fixed order."""
    issues: list[IssueDraft] = []
    for check in CHECKS:
        issues.extend(check(tagged))
    return issues


def _iso(value: date | None) -> str:
    return value.isoformat() if value is not None else "open"
