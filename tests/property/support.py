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
"""

from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
from judgemetrics.synthetic.config import ScaleSpec
from judgemetrics.synthetic.generate import generate_dataset
from tests.conftest import TEST_IDENTIFIER_PEPPER

PEPPER = SecretStr(TEST_IDENTIFIER_PEPPER)
SOURCE_ID = "synthetic"

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
