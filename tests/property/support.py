# tests/property/support.py
"""Shared machinery for the property tests: generate a dataset for a seed and
scale, read its files, and normalize it through the real synthetic connector.

Strategies in this package draw seeds, orderings, and formatting variants
only; every name in a generated dataset still comes from the generator's
word lists, and nothing here reads ``truth/`` into the connector. A
``Dataset`` is cached per ``(seed, scale)`` for the module so the same
example, replayed by several tests or by Hypothesis's shrinking, is
generated and normalized once. Failure output names the seed and the
scale, never a restricted value.

``frame_from_world`` (Phase 3 Step 1) builds the metrics engine's
``Frame`` from an in-memory world without a database: the world's own
string ids are the frame's ids and the true person ids are ``persons.id``,
so the frame's cohorts can be compared with ``synthetic/truth.py`` on the
same world. Step 2's ``snapshot.py`` is the database loader.
"""

from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import polars as pl
from hypothesis import strategies as st
from pydantic import SecretStr

from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    ChargeDraft,
    DecisionDraft,
    JusticeEventDraft,
    NaturalKey,
    PersonDraft,
    RawArtifact,
    SentenceDraft,
)
from judgemetrics.ingest.synthetic.connector import SyntheticConnector
from judgemetrics.metrics.frame import SCHEMAS, Frame, empty_table, resolve_dtype
from judgemetrics.synthetic.config import ScaleSpec
from judgemetrics.synthetic.generate import build_dataset as build_world_dataset
from judgemetrics.synthetic.generate import generate_dataset
from judgemetrics.synthetic.model import World
from judgemetrics.synthetic.truth import outcomes_of
from tests.conftest import TEST_IDENTIFIER_PEPPER

PEPPER = SecretStr(TEST_IDENTIFIER_PEPPER)
SOURCE_ID = "synthetic"
# The outcomes the synthetic source documents (Step 2 declares the same on its SourceInfo).
SYNTHETIC_OBSERVABLE: frozenset[str] = frozenset(
    {"new_case", "new_charge", "reconviction", "failure_to_appear", "revocation"}
)

# Every seed the generator accepts; a failing example prints the seed, which
# is all a developer needs to regenerate the dataset.
seeds = st.integers(min_value=0, max_value=2**31 - 1)


@dataclass(slots=True)
class Dataset:
    """A generated dataset with its source rows and its normalized drafts."""

    seed: int
    spec: ScaleSpec
    root: Path
    source: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    truth: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    drafts: list[CanonicalRecord] = field(default_factory=list)

    def __repr__(self) -> str:  # what a Hypothesis failure prints
        return f"Dataset(seed={self.seed}, scale={self.spec.name!r})"

    @property
    def manifest(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads((self.root / "manifest.json").read_text("utf-8"))
        return payload

    def of_type[R: CanonicalRecord](self, kind: type[R]) -> list[R]:
        return [draft for draft in self.drafts if isinstance(draft, kind)]

    @property
    def cases(self) -> dict[NaturalKey, CaseDraft]:
        return {draft.natural_key: draft for draft in self.of_type(CaseDraft)}

    @property
    def charges_by_case(self) -> dict[NaturalKey, list[ChargeDraft]]:
        grouped: dict[NaturalKey, list[ChargeDraft]] = defaultdict(list)
        for charge in self.of_type(ChargeDraft):
            grouped[charge.case_key].append(charge)
        return grouped

    @property
    def cases_by_person(self) -> dict[NaturalKey, set[NaturalKey]]:
        grouped: dict[NaturalKey, set[NaturalKey]] = defaultdict(set)
        for charge in self.of_type(ChargeDraft):
            grouped[charge.person_key].add(charge.case_key)
        return grouped

    @property
    def persons(self) -> list[PersonDraft]:
        return self.of_type(PersonDraft)

    @property
    def decisions(self) -> list[DecisionDraft]:
        return self.of_type(DecisionDraft)

    @property
    def sentences(self) -> list[SentenceDraft]:
        return self.of_type(SentenceDraft)

    @property
    def justice_events(self) -> list[JusticeEventDraft]:
        return self.of_type(JusticeEventDraft)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, value
    return parsed


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def fetch_all(connector: SyntheticConnector) -> list[RawArtifact]:
    """Every artifact the connector discovers, read from disk."""
    artifacts = asyncio.run(connector.discover())
    return [asyncio.run(connector.fetch(artifact)) for artifact in artifacts]


def normalize_dataset(root: Path) -> list[CanonicalRecord]:
    """The drafts the synthetic connector yields for the dataset at ``root``.

    The real connector path: discover, fetch, ``load_context`` over every
    artifact (manifest drift fails here), validate, parse, normalize.
    """
    connector = SyntheticConnector(root, pepper=PEPPER)
    artifacts = fetch_all(connector)
    connector.load_context(artifacts)
    drafts: list[CanonicalRecord] = []
    for raw in artifacts:
        validation = connector.validate_raw(raw)
        assert validation.ok, validation.errors
        for record in connector.parse(raw):
            drafts.extend(connector.normalize(record))
    return drafts


def build_dataset(seed: int, spec: ScaleSpec, root: Path) -> Dataset:
    """Generate ``seed`` at ``spec`` into ``root`` and normalize it."""
    generate_dataset(seed, spec.name, root)
    dataset = Dataset(seed=seed, spec=spec, root=root)
    for path in sorted((root / "source").glob("*.csv")):
        dataset.source[path.name] = read_csv(path)
    for path in sorted((root / "truth").glob("*.csv")):
        dataset.truth[path.name] = read_csv(path)
    dataset.drafts = normalize_dataset(root)
    return dataset


class DatasetCache:
    """One generated dataset per ``(seed, scale)`` under a session temp directory."""

    def __init__(self, make_dir: Any) -> None:
        self._make_dir = make_dir
        self._datasets: dict[tuple[int, str], Dataset] = {}

    def get(self, seed: int, spec: ScaleSpec) -> Dataset:
        key = (seed, spec.name)
        dataset = self._datasets.get(key)
        if dataset is None:
            dataset = build_dataset(seed, spec, self._make_dir(f"{spec.name}-{seed}"))
            self._datasets[key] = dataset
        return dataset


# --- the analytic frame of an in-memory world --------------------------------------------


def build_world(seed: int, spec: ScaleSpec) -> World:
    """The in-memory world for ``seed`` at ``spec`` with identifiers and plants applied."""
    world, _plants = build_world_dataset(seed, spec)
    return world


def _table(name: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return empty_table(name)
    schema = {column: resolve_dtype(spec, pl.String()) for column, spec in SCHEMAS[name].items()}
    return pl.DataFrame(rows, schema=schema, orient="row")


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


def _end_of_day(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.max, UTC)


def frame_from_world(world: World, spec: ScaleSpec) -> Frame:
    """The metrics engine's ``Frame`` of ``world``: string ids, true person ids, no database.

    Cases, assignments, charges, decisions (with their pretrial-release
    columns), sentences, and events are the world's rows one to one (a
    planted duplicate source record is one row, as after ingest); justice
    events are the truth generator's outcomes per case (``outcomes_of``),
    one row per distinct (person, type, instant, case) as the ingest
    natural key collapses them; the coverage window is the corpus and the
    observable outcomes those the synthetic source documents.
    """
    cases: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    charges: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    sentences: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    justice: dict[tuple[str, str, datetime, str], dict[str, Any]] = {}
    for case in world.cases:
        person_id = case.person.true_id
        cases.append(
            {
                "id": case.case_number,
                "court_id": case.court_code,
                "filed_at": _start_of_day(case.filed_date),
                "closed_at": _end_of_day(case.closed_date),
                "status": case.status,
                "case_type": case.case_type,
            }
        )
        for assignment in case.assignments:
            assignments.append(
                {
                    "case_id": case.case_number,
                    "judge_id": assignment.judge_code,
                    "start_at": assignment.start_at,
                    "end_at": assignment.end_at,
                }
            )
        for charge in case.charges:
            charges.append(
                {
                    "id": charge.charge_id,
                    "case_id": case.case_number,
                    "person_id": person_id,
                    "filed_at": charge.filed_at,
                    "disposed_at": charge.disposed_at,
                    "disposition": charge.disposition,
                    "disposition_actor": charge.disposition_actor,
                    "offense_category": charge.offense.offense_category,
                    "severity": charge.offense.severity,
                    "source_row_id": charge.charge_id,
                }
            )
        for decision in case.decisions:
            pretrial = decision.decision_type == "pretrial_release"
            decisions.append(
                {
                    "id": decision.decision_id,
                    "case_id": case.case_number,
                    "person_id": person_id,
                    "judge_id": decision.judge_code,
                    "decision_type": decision.decision_type,
                    "decision_at": decision.decision_at,
                    "actor_type": decision.actor,
                    "discretion": decision.discretion,
                    "release_at": decision.release_at if pretrial else None,
                    "detained_flag": decision.detained if pretrial else None,
                    "release_type": decision.release_type if pretrial else None,
                }
            )
        if case.sentence is not None:
            sentences.append(
                {
                    "id": case.sentence.sentence_id,
                    "case_id": case.case_number,
                    "person_id": person_id,
                    "judge_id": case.sentence.judge_code,
                    "sentence_at": case.sentence.sentence_at,
                    "incarceration_days": case.sentence.incarceration_days,
                    "probation_days": case.sentence.probation_days,
                }
            )
        for event in case.events:
            events.append(
                {
                    "id": event.event_id,
                    "case_id": case.case_number,
                    "person_id": person_id,
                    "judge_id": event.judge_code,
                    "event_type": event.event_type,
                    "event_at": event.event_at,
                }
            )
        for outcome in outcomes_of(case):
            key = (person_id, outcome.outcome_type, outcome.at, case.case_number)
            justice.setdefault(
                key,
                {
                    "id": "",
                    "person_id": person_id,
                    "event_type": outcome.outcome_type,
                    "event_at": outcome.at,
                    "related_case_id": case.case_number,
                },
            )
    justice_rows = [justice[key] for key in sorted(justice)]
    for index, row in enumerate(justice_rows, start=1):
        row["id"] = f"JE-{index:06d}"
    return Frame(
        cases=_table("cases", cases),
        assignments=_table("assignments", assignments),
        charges=_table("charges", charges),
        decisions=_table("decisions", decisions),
        sentences=_table("sentences", sentences),
        events=_table("events", events),
        justice_events=_table("justice_events", justice_rows),
        persons=_table("persons", [{"id": person.true_id} for person in world.persons]),
        coverage_start=spec.corpus_start,
        coverage_end=spec.corpus_end,
        observable_outcomes=SYNTHETIC_OBSERVABLE,
    )
