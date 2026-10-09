# src/judgemetrics/ingest/cook_sao/findings.py
"""What the Cook County connector found while it read the exports: counts, never rows.

The connector groups the rows of a case before it normalizes them, so a row it
cannot map (a class no rule table lists, a date that is not a date) cannot be
rejected with an exception the way a single-row connector rejects it. It leaves
the row, or the one field, out and counts the finding here; after the run the
runner persists each finding as one data-quality issue (``SupportsRunIssues``).

Every description is built from this module's templates and names a dataset, a
column, and a count — and, for a coded column no rule table lists, the value
itself (an offense category, a class, a court name: public vocabulary, never a
participant id, a restricted value, or a raw row). The restricted attributes are
described by their kind and a count only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from judgemetrics.db.models.enums import IssueSeverity
from judgemetrics.ingest.base import RunIssue

ENTITY_DATASET = "source_record"

# code -> (severity, entity type, template). A template may use {artifact},
# {detail}, and {count}; ``rejects`` marks a finding whose rows are not published.
JUDGE_UNRESOLVED = "judge_unresolved"
RECEIVED_BEFORE_COVERAGE = "received_before_coverage"
DATE_AFTER_CORPUS_END = "date_after_corpus_end"
UNPARSEABLE_DATE = "unparseable_date"
UNMAPPED_VALUE = "unmapped_value"
IGNORED_VALUE = "ignored_value"
COURT_UNLISTED = "court_unlisted"
ROW_WITHOUT_KEY = "row_without_key"
CASE_WITHOUT_FILING_DATE = "case_without_filing_date"
RESTRICTED_VALUE_UNLISTED = "restricted_value_unlisted"
RESTRICTED_VALUE_CONFLICT = "restricted_value_conflict"
INVALID_AGE = "invalid_age"
CHARGE_VERSION_REPLACED = "charge_version_replaced"
CHARGE_WITHOUT_DISPOSITION_DATE = "charge_without_disposition_date"
BOND_NOT_DRAFTED = "bond_not_drafted"
FACT_UNDATED = "fact_undated"
SENTENCE_PHASE_IGNORED = "sentence_phase_ignored"
SENTENCE_UNMATCHED = "sentence_unmatched"
SENTENCE_WITHOUT_DATE = "sentence_without_date"
SENTENCE_JUDGES_DIFFER = "sentence_judges_differ"
SENTENCE_TERM_FLAGGED = "sentence_term_flagged"

TEMPLATES: dict[str, tuple[IssueSeverity, str, bool]] = {
    JUDGE_UNRESOLVED: (
        IssueSeverity.WARNING,
        "{artifact}: the judge string {detail} is held by judge_aliases.csv; "
        "{count} rows are published without a judge",
        False,
    ),
    RECEIVED_BEFORE_COVERAGE: (
        IssueSeverity.INFO,
        "{count} cases were received in {detail}, before the coverage start; they are kept",
        False,
    ),
    DATE_AFTER_CORPUS_END: (
        IssueSeverity.WARNING,
        "{artifact}: {count} {detail} values are after the corpus end and are ignored",
        False,
    ),
    UNPARSEABLE_DATE: (
        IssueSeverity.WARNING,
        "{artifact}: {count} {detail} values are not dates in either export format and are ignored",
        False,
    ),
    UNMAPPED_VALUE: (
        IssueSeverity.ERROR,
        "{artifact}: {count} rows carry {detail}, which no rule table lists; the rows "
        "are not published",
        True,
    ),
    IGNORED_VALUE: (
        IssueSeverity.WARNING,
        "{artifact}: {count} rows carry {detail}, which no rule table lists; the fact it "
        "records is not published",
        False,
    ),
    COURT_UNLISTED: (
        IssueSeverity.ERROR,
        "{artifact}: {count} rows name a court or courthouse ({detail}) that courts.yaml "
        "does not list; the rows are not published",
        True,
    ),
    ROW_WITHOUT_KEY: (
        IssueSeverity.ERROR,
        "{artifact}: {count} rows have no {detail} and are not published",
        True,
    ),
    CASE_WITHOUT_FILING_DATE: (
        IssueSeverity.ERROR,
        "{count} cases have no valid received date in any export and are not published",
        True,
    ),
    RESTRICTED_VALUE_UNLISTED: (
        IssueSeverity.WARNING,
        "{count} participants carry a {detail} label the vocabulary does not list; it is "
        "not recorded",
        False,
    ),
    RESTRICTED_VALUE_CONFLICT: (
        IssueSeverity.INFO,
        "{count} participants carry different {detail} labels across the exports; the "
        "first export in the order Intake, Initiation, Dispositions, Sentencing, "
        "Diversion wins",
        False,
    ),
    INVALID_AGE: (
        IssueSeverity.WARNING,
        "{count} participants carry an age that is not a whole number from 0 to 130 on "
        "some row; the age band comes from another row or is unknown",
        False,
    ),
    CHARGE_VERSION_REPLACED: (
        IssueSeverity.INFO,
        "{count} charge versions filed in Initiation were replaced by an amended version "
        "of the same charge in a later export and are not published",
        False,
    ),
    CHARGE_WITHOUT_DISPOSITION_DATE: (
        IssueSeverity.INFO,
        "{count} charges have a disposition but no valid disposition date; they are "
        "published without one",
        False,
    ),
    BOND_NOT_DRAFTED: (
        IssueSeverity.INFO,
        "{count} participants have no bond decision: {detail}",
        False,
    ),
    FACT_UNDATED: (
        IssueSeverity.INFO,
        "{count} {detail} have no valid date and are not published",
        False,
    ),
    SENTENCE_PHASE_IGNORED: (
        IssueSeverity.INFO,
        "{artifact}: {count} rows are in the sentence phase {detail}, which "
        "sentence_rules.yaml ignores; no sentence is drafted from them",
        False,
    ),
    SENTENCE_UNMATCHED: (
        IssueSeverity.ERROR,
        "{artifact}: {count} rows carry a sentence phase, type, or commitment type that "
        "sentence_rules.yaml does not list ({detail}); the rows are not published",
        True,
    ),
    SENTENCE_WITHOUT_DATE: (
        IssueSeverity.ERROR,
        "{artifact}: {count} sentences have no valid sentence date and are not published",
        True,
    ),
    SENTENCE_JUDGES_DIFFER: (
        IssueSeverity.INFO,
        "{artifact}: {count} sentences have rows naming different judges; the most "
        "frequent resolved judge (then the smallest key) is kept",
        False,
    ),
    SENTENCE_TERM_FLAGGED: (
        IssueSeverity.INFO,
        "{artifact}: {count} sentence rows carry a term with the flag {detail}; they "
        "contribute no day count",
        False,
    ),
}

# A finding about the corpus, not one file, has no artifact of its own; it is recorded against
# Dispositions' source record (the export that carries the reference rows), so that it
# belongs to the source: ``ingest retire`` removes it with the source's records.
RUN_LEVEL = ""
CORPUS_ARTIFACT = "dispositions.csv"


@dataclass(slots=True)
class Findings:
    """Counts of what the connector left out or flagged, by (code, artifact, detail)."""

    counts: Counter[tuple[str, str, str]] = field(default_factory=Counter)

    def add(self, code: str, artifact: str = RUN_LEVEL, detail: str = "", count: int = 1) -> None:
        if code not in TEMPLATES:
            msg = f"unknown finding {code!r}"
            raise KeyError(msg)
        self.counts[(code, artifact, detail)] += count

    def rejected_rows(self) -> int:
        return sum(count for (code, _, _), count in self.counts.items() if TEMPLATES[code][2])

    def issues(self) -> list[RunIssue]:
        """One issue per finding, in a fixed order (code, file, detail)."""
        issues: list[RunIssue] = []
        for (code, artifact, detail), count in sorted(self.counts.items()):
            severity, template, rejects = TEMPLATES[code]
            issues.append(
                RunIssue(
                    issue_code=code,
                    severity=severity,
                    entity_type=ENTITY_DATASET,
                    description=template.format(artifact=artifact, detail=detail, count=count),
                    artifact_id=artifact or CORPUS_ARTIFACT,
                    rejected_rows=count if rejects else 0,
                )
            )
        return issues
