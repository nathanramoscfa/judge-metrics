# tests/property/test_event_ordering.py
"""A subsequent event never precedes its index event — for any seed, through the
generator and through the normalized drafts (the brief's first property).

For every seed at the ``tiny`` and ``golden`` scales, the generated files
satisfy: every ``truth/subsequent_events.csv`` row has ``outcome_at >
index_at`` and ``days_after >= 1`` (and ``days_after`` is the smallest
whole number of days that covers the gap); every charge is disposed on or
after its filing; every sentence follows its case's disposition; every
decision lies inside its case's filed/closed window. The same dataset
normalized through the synthetic connector satisfies the same on the
``JusticeEventDraft``, ``ChargeDraft``, ``DecisionDraft``, and
``SentenceDraft`` values, so the invariant survives source-to-canonical
mapping and not only generation.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from hypothesis import given

from judgemetrics.ingest.base import ChargeDraft, NaturalKey
from judgemetrics.synthetic.config import GOLDEN, TINY, ScaleSpec
from tests.property.support import Dataset, DatasetCache, parse_day, parse_ts, seeds

pytestmark = pytest.mark.property

SCALES = [TINY, GOLDEN]
SCALE_IDS = [spec.name for spec in SCALES]
OTHER_CASE_EVENTS = frozenset({"new_case", "reconviction"})


@pytest.fixture(scope="module")
def datasets(tmp_path_factory: pytest.TempPathFactory) -> DatasetCache:
    return DatasetCache(tmp_path_factory.mktemp)


def _start_of_day(day: str) -> datetime:
    return datetime.combine(parse_day(day), time.min, UTC)


def _end_of_day(day: str) -> datetime:
    return datetime.combine(parse_day(day), time.max, UTC)


def _case_windows(dataset: Dataset) -> dict[str, tuple[datetime, datetime | None]]:
    """Case number → (filed day start, closed day end or None), from ``cases.csv``."""
    windows: dict[str, tuple[datetime, datetime | None]] = {}
    for row in dataset.source["cases.csv"]:
        closed = _end_of_day(row["closed_date"]) if row["closed_date"] else None
        windows[row["case_number"]] = (_start_of_day(row["filed_date"]), closed)
    return windows


def _case_dispositions(dataset: Dataset) -> dict[str, datetime]:
    """Case number → the latest ``disposed_at`` of its charges, from ``charges.csv``."""
    latest: dict[str, datetime] = {}
    for row in dataset.source["charges.csv"]:
        if not row["disposed_at"]:
            continue
        disposed = parse_ts(row["disposed_at"])
        number = row["case_number"]
        if number not in latest or disposed > latest[number]:
            latest[number] = disposed
    return latest


# --- the generated files -------------------------------------------------------------------


@pytest.mark.parametrize("spec", SCALES, ids=SCALE_IDS)
@given(seed=seeds)
def test_truth_subsequent_events_follow_their_index_events(
    datasets: DatasetCache, spec: ScaleSpec, seed: int
) -> None:
    dataset = datasets.get(seed, spec)
    rows = dataset.truth["subsequent_events.csv"]
    assert rows, dataset
    for row in rows:
        index_at = parse_ts(row["index_at"])
        outcome_at = parse_ts(row["outcome_at"])
        days_after = int(row["days_after"])
        assert outcome_at > index_at, (dataset, row["index_event_type"], row["outcome_type"])
        assert days_after >= 1, (dataset, row["outcome_type"])
        # The smallest whole number of days d with outcome_at <= index_at + d days.
        assert outcome_at <= index_at + timedelta(days=days_after), dataset
        assert outcome_at > index_at + timedelta(days=days_after - 1), dataset


@pytest.mark.parametrize("spec", SCALES, ids=SCALE_IDS)
@given(seed=seeds)
def test_source_charges_sentences_and_decisions_are_ordered(
    datasets: DatasetCache, spec: ScaleSpec, seed: int
) -> None:
    dataset = datasets.get(seed, spec)
    for row in dataset.source["charges.csv"]:
        if row["disposed_at"]:
            assert parse_ts(row["disposed_at"]) >= parse_ts(row["filed_at"]), (
                dataset,
                row["charge_id"],
            )
    dispositions = _case_dispositions(dataset)
    for row in dataset.source["sentences.csv"]:
        disposed = dispositions.get(row["case_number"])
        assert disposed is not None, (dataset, row["sentence_id"])
        assert parse_ts(row["sentence_at"]) > disposed, (dataset, row["sentence_id"])
    windows = _case_windows(dataset)
    for row in dataset.source["decisions.csv"]:
        filed, closed = windows[row["case_number"]]
        decided = parse_ts(row["decision_at"])
        assert decided >= filed, (dataset, row["decision_id"])
        if closed is not None:
            assert decided <= closed, (dataset, row["decision_id"])


# --- the normalized drafts -----------------------------------------------------------------


@pytest.mark.parametrize("spec", SCALES, ids=SCALE_IDS)
@given(seed=seeds)
def test_normalized_drafts_keep_the_ordering(
    datasets: DatasetCache, spec: ScaleSpec, seed: int
) -> None:
    dataset = datasets.get(seed, spec)
    cases = dataset.cases
    charges_by_case = dataset.charges_by_case
    assert cases and charges_by_case, dataset

    def window(case_key: NaturalKey) -> tuple[datetime, datetime | None]:
        case = cases[case_key]
        assert case.filed_date is not None, (dataset, case.source_row_id)
        filed = datetime.combine(case.filed_date, time.min, UTC)
        closed = datetime.combine(case.closed_date, time.max, UTC) if case.closed_date else None
        return filed, closed

    def disposition_of(case_key: NaturalKey) -> datetime | None:
        disposed = [c.disposed_at for c in charges_by_case[case_key] if c.disposed_at is not None]
        return max(disposed) if disposed else None

    for charge in dataset.of_type(ChargeDraft):
        if charge.disposed_at is not None:
            assert charge.disposed_at >= charge.filed_at, (dataset, charge.source_row_id)

    for sentence in dataset.sentences:
        disposed = disposition_of(sentence.case_key)
        assert disposed is not None, (dataset, sentence.source_row_id)
        assert sentence.sentence_at > disposed, (dataset, sentence.source_row_id)

    for decision in dataset.decisions:
        filed, closed = window(decision.case_key)
        assert decision.decision_at >= filed, (dataset, decision.source_row_id)
        if closed is not None:
            assert decision.decision_at <= closed, (dataset, decision.source_row_id)

    cases_by_person = dataset.cases_by_person
    for event in dataset.justice_events:
        assert event.related_case_key is not None, (dataset, event.event_type)
        filed, _ = window(event.related_case_key)
        assert event.event_at >= filed, (dataset, event.event_type)
        if event.event_type not in OTHER_CASE_EVENTS:
            continue
        # A new case or a reconviction is subsequent to something: an earlier
        # filing, or an earlier disposition, in another case of the same person.
        others = cases_by_person[event.person_key] - {event.related_case_key}
        assert others, (dataset, event.event_type)
        if event.event_type == "new_case":
            earlier = [
                charge.filed_at
                for other in others
                for charge in charges_by_case[other]
                if charge.filed_at < event.event_at
            ]
        else:
            earlier = [
                charge.disposed_at
                for other in others
                for charge in charges_by_case[other]
                if charge.disposed_at is not None and charge.disposed_at < event.event_at
            ]
        assert earlier, (dataset, event.event_type)
